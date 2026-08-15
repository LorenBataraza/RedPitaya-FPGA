"""RingSource — fuente de eventos sobre el event_ring en DDR (Fase 2).

Reemplaza a `BramSource` sin tocar el lector: expone la misma interfaz
(`arm` / `wait_event` / `snapshot` / `read_into` / `rearm` / `close`) que consume
`mca/reader.py`.

POR QUE PREFETCHEA EN LOTE (lo más importante de este archivo)

El lector pide un evento por vez, pero medido EN LA PLACA leer un slot suelto de
512 B de la región reservada cuesta ~27 µs — apenas 1.7x mejor que los 45.6 µs de
`rp_AcqGetDataPosV` sobre BRAM, porque lo que domina es el overhead fijo de
Python, no el ancho de banda:

    512 B (1 slot)      27.3 µs    ->  27.3 µs/slot
    64 KB (128 slots)  296   µs    ->   2.31 µs/slot     <- el punto óptimo
    1 MB  (2048)         6.2 ms    ->   3.02 µs/slot

O sea que la ganancia de ~20x sólo existe leyendo en LOTE. `wait_event` copia un
bloque de hasta `MAX_BATCH_BYTES` de una sola vez y después sirve los eventos de
ese bloque uno por uno. El lector no se entera y el costo por evento baja de 27 a
~2.3 µs.

POR QUE SE MIRAN LAS DOS COSAS, WR_SLOT Y EL FOOTER

`WR_SLOT` (registro por GP0) dice cuántos slots cerró el writer, pero se
incrementa cuando el footer fue ACEPTADO por el `axi_wr_fifo` — no cuando llegó a
DDR. El footer `{~seq, seq}` al final del slot es la marca que confirma que el
dato ya está en memoria (AXI garantiza orden entre escrituras del mismo ID).

Entonces: `WR_SLOT` para saber CUÁNTOS pedir (una lectura de 2.3 µs amortizada
sobre todo el lote, ~0.02 µs/evento), y el footer para validar CADA slot antes de
usarlo. Sin el footer se pueden leer slots a medio escribir; sin `WR_SLOT` habría
que poletear footer por footer, que es justamente la lectura suelta que resultó
cara.

RD_SLOT SE PUBLICA POR LOTE, NO POR EVENTO. Publicarlo por evento devolvería el
bus GP0 al camino crítico, que es exactamente lo que esta arquitectura saca.
"""

import struct
import time

import numpy as np

from .events import BASE_FIELDS

# --- registros del event_ring (slot 2) --------------------------------------
RING_PHYS = 0x4020_0000
RING_SIZE = 0x1000

R_CTRL, R_STATUS = 0x00, 0x04
R_SLOT_BASE, R_RING_SZ, R_SLOT_SHIFT = 0x08, 0x0C, 0x10
R_PRE, R_POST = 0x14, 0x18
R_WR_SLOT, R_RD_SLOT, R_SEQ, R_N_SLOTS = 0x20, 0x24, 0x28, 0x2C
R_DROP_BUSY, R_DROP_FULL, R_EV_CNT, R_LVL = 0x30, 0x34, 0x38, 0x3C
R_TS_LO, R_TS_HI, R_AXI_ADDR, R_MAGIC = 0x40, 0x44, 0x48, 0x50

MAGIC = 0x45564E54  # "EVNT"

ADC_CNT_PER_V = 8192        # escala LV (+-1 V), la misma que BramSource
HDR_BYTES = 32              # 4 palabras de 64 b
FOOTER_BYTES = 8

# 64 KB fue el óptimo medido en placa (ver el docstring del módulo).
MAX_BATCH_BYTES = 64 * 1024

_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")


class RingSource:
    """Fuente de eventos leídos del ring en DDR.

    `scope` se usa sólo para configurar el trigger (umbral, histéresis, máscara);
    la captura y la lectura no lo tocan.
    """

    scalar_fields = BASE_FIELDS

    def __init__(self, scope, ring_mem, ddr_mem, ddr_phys, ddr_size,
                 pre=8, post=24, n_ch=2, thr=0.5, hyst=0.02, mask=None,
                 slot_shift=None):
        self.sc = scope
        self._rg = ring_mem            # mmap de 0x4020_0000
        self._mem = ddr_mem            # mmap de la región reservada
        self.ddr_phys = ddr_phys
        self.ddr_size = ddr_size

        self.pre = pre
        self.post = post
        self.samples = pre + post
        self.n_ch = n_ch
        self.thr = thr
        self.hyst = hyst
        self.mask = mask

        # El slot tiene que albergar cabecera + muestras + footer, y ser potencia
        # de 2 para que la dirección salga de un shift (ver el RTL).
        need = HDR_BYTES + self.samples * n_ch * 2 + FOOTER_BYTES
        if slot_shift is None:
            slot_shift = max(6, (need - 1).bit_length())
        if (1 << slot_shift) < need:
            raise ValueError(
                f"slot_shift={slot_shift} da {1 << slot_shift} B pero hacen "
                f"falta {need} B (cabecera+ventana+footer)")
        self.slot_shift = slot_shift
        self.slot_sz = 1 << slot_shift
        self.n_slots = ddr_size >> slot_shift

        self._next = 0          # seq del próximo evento a entregar
        self._buf = None        # bloque prefetcheado (bytes)
        self._buf_first = 0     # seq del primer slot del bloque
        self._buf_n = 0         # slots válidos en el bloque
        self._buf_i = 0         # índice dentro del bloque
        self._last_meta = None
        self._published = 0     # último RD_SLOT publicado

        self.batch_slots = max(1, MAX_BATCH_BYTES // self.slot_sz)

    # -- helpers de registro ------------------------------------------------
    def _r(self, off):
        return _U32.unpack_from(self._rg, off)[0]

    def _w(self, off, val):
        # Asignación por slice, NUNCA struct.pack_into: pack_into hace un memset
        # previo que sale como stores de a byte -> external abort -> SIGBUS.
        self._rg[off:off + 4] = _U32.pack(val & 0xFFFFFFFF)

    # -- ciclo de vida ------------------------------------------------------
    def arm(self):
        from multitrigger_utils import BIT_ADC_P0

        if self._r(R_MAGIC) != MAGIC:
            raise RuntimeError(
                "el bitstream cargado no tiene el event_ring en el slot 2 "
                "(esperaba MAGIC 'EVNT' en 0x4020_0050)")

        # Geometría: sólo latchea con la adquisición parada.
        self._w(R_CTRL, 0)
        self._w(R_CTRL, 0x2)                 # clr: contadores y sticky
        self._w(R_SLOT_BASE, self.ddr_phys)
        self._w(R_RING_SZ, self.ddr_size)
        self._w(R_SLOT_SHIFT, self.slot_shift)
        self._w(R_PRE, self.pre)
        self._w(R_POST, self.post)

        got = self._r(R_N_SLOTS)
        if got != self.n_slots:
            raise RuntimeError(f"N_SLOTS={got}, esperaba {self.n_slots}")

        # Trigger: el mismo camino que usa BramSource. we_keep para que la
        # máscara no se auto-limpie y el shield para el re-arm por hardware.
        mask = BIT_ADC_P0 if self.mask is None else self.mask
        self.sc.arm_for_adc_trigger(
            mask_ch0=mask, mask_ch1=mask, thr=self.thr, hyst=self.hyst,
            delay=1, we_keep_both=True, auto_rearm=True)

        self._next = 0
        self._buf = None
        self._buf_n = self._buf_i = 0
        self._published = 0
        self._w(R_CTRL, 0x1)                 # run

    def rearm(self):
        """No-op: el hardware re-arma solo en ~24 ns.

        Se mantiene en la interfaz porque el lector la llama también en el
        camino de descarte. Acá el descarte no necesita ninguna acción: el ring
        sigue capturando por su cuenta y lo que el PS no consuma se cuenta en
        DROP_FULL del lado del hardware.
        """

    def close(self):
        self._w(R_CTRL, 0)                   # stop ordenado (DRAINING)
        deadline = time.perf_counter() + 0.5
        while (self._r(R_STATUS) & 0x7) != 0 and time.perf_counter() < deadline:
            pass
        self.sc.disarm()

    # -- lazo caliente ------------------------------------------------------
    def _publish_rd(self):
        """Devuelve créditos. Una escritura por LOTE, no por evento."""
        if self._next != self._published:
            self._w(R_RD_SLOT, self._next)
            self._published = self._next

    def _prefetch(self):
        """Copia de una sola vez el bloque de slots listos. True si trajo algo.

        Lee slots contiguos SIN dar la vuelta al ring: si el lote cruzara el
        final, se corta ahí y el resto viene en la llamada siguiente. Copiar a
        través del wrap requeriría dos slices y complicaría el indexado sin
        ganar nada.
        """
        wr = self._r(R_WR_SLOT)
        avail = wr - self._next
        if avail <= 0:
            return False

        first_idx = self._next % self.n_slots
        n = min(avail, self.batch_slots, self.n_slots - first_idx)

        off = first_idx * self.slot_sz
        self._buf = self._mem[off:off + n * self.slot_sz]
        self._buf_first = self._next
        self._buf_n = n
        self._buf_i = 0
        return True

    def _slot_ok(self, i):
        """Valida el footer del slot i del bloque contra su seq esperado.

        WR_SLOT avanza cuando el footer fue ACEPTADO por el axi_wr_fifo, no
        cuando aterrizó en DDR. El footer es la única confirmación de que el
        slot está completo.
        """
        base = i * self.slot_sz
        foot = _U64.unpack_from(self._buf, base + self.slot_sz - 8)[0]
        lo = foot & 0xFFFFFFFF
        hi = (foot >> 32) & 0xFFFFFFFF
        return hi == (~lo) & 0xFFFFFFFF and lo == (
            (self._buf_first + i) & 0xFFFFFFFF)

    def wait_event(self, deadline_ns):
        """Devuelve el seq del próximo evento listo, o None si venció el plazo."""
        pc = time.perf_counter_ns
        while True:
            if self._buf_i < self._buf_n:
                if self._slot_ok(self._buf_i):
                    return self._buf_first + self._buf_i
                # Footer todavía no aterrizó: descartar lo que queda del bloque
                # y volver a pedirlo. No se avanza `_next`, así que no se pierde
                # ningún evento.
                self._buf_n = self._buf_i = 0

            # El plazo se chequea SIEMPRE, antes de volver a pedir. Si estuviera
            # sólo en la rama de "no hay nada", un slot con el footer todavía en
            # vuelo haría girar el lazo para siempre: WR_SLOT dice que hay un
            # evento, el prefetch lo trae, el footer lo rechaza, y vuelta a
            # empezar sin mirar nunca el reloj.
            if pc() > deadline_ns:
                return None

            self._publish_rd()
            self._prefetch()

    def snapshot(self):
        """Qué fuente disparó. Sale de la cabecera del slot ya leído: a
        diferencia de BramSource, no cuesta una lectura de registro (2.3 µs)."""
        m = self._last_meta
        return 0 if m is None else m[2]

    def read_into(self, batch, i, seq):
        """Copia la ventana del slot `seq` a batch.wave[i].

        El slot ya está en `self._buf` (lo trajo `wait_event` con el resto del
        lote), así que acá no hay ningún acceso a hardware: es un reshape sobre
        memoria de proceso.
        """
        j = self._buf_i
        base = j * self.slot_sz

        ts = _U64.unpack_from(self._buf, base)[0]
        w1 = _U64.unpack_from(self._buf, base + 8)[0]
        w2 = _U64.unpack_from(self._buf, base + 16)[0]
        n_samp = (w1 >> 32) & 0xFFFF
        n_ch = (w1 >> 48) & 0xFF
        self._last_meta = (ts, n_samp, w2 & 0x1FFFF)

        total = n_samp * n_ch
        raw = np.frombuffer(self._buf, dtype="<i2", count=total,
                            offset=base + HDR_BYTES)
        # (n_samp, n_ch) -> transpuesta = (n_ch, n_samp), y a volts como
        # entrega rp_AcqGetDataPosV, para que el resto del pipeline no cambie.
        batch.wave[i] = raw.reshape(n_samp, n_ch).T / ADC_CNT_PER_V

        self._buf_i = j + 1
        self._next = seq + 1

    # -- diagnóstico --------------------------------------------------------
    def hw_counters(self):
        """Contadores del hardware, para el resumen de la corrida.

        `drop_full` y `drop_busy` son la pérdida que hasta ahora era INVISIBLE:
        con la BRAM, un segundo trigger mientras el software leía el anterior no
        quedaba registrado en ningún lado.
        """
        return {
            "hw_ev_cnt": self._r(R_EV_CNT),
            "hw_drop_busy": self._r(R_DROP_BUSY),
            "hw_drop_full": self._r(R_DROP_FULL),
            "hw_wr_slot": self._r(R_WR_SLOT),
            "hw_rd_slot": self._r(R_RD_SLOT),
            "hw_status": self._r(R_STATUS),
            "hw_n_slots": self.n_slots,
            "hw_slot_sz": self.slot_sz,
        }
