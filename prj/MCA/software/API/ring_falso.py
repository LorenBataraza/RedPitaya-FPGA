"""El event_ring simulado: los registros por callbacks y la DDR en un arreglo.

Es al ring lo que `FakeMCA` (`API/mca_remote.py`) es al MCA: lo que usan los tests y el
servidor con `--fake` para correr sin placa. Habla por el mismo `OsciloscopeRing` que
la placa (`handle()`), así que lo que anda acá anda contra libmca, y lo que no, es del
hardware.

- `RingFalso`: los registros, la máquina de parar (corriendo → drenando → parado) y la
  escritura de un slot como la del RTL (`disparar`). Las muestras del slot las da
  `muestras()`: ceros acá; los tests ponen las suyas en una subclase.
- `RingFalsoGen`: más el generador de eventos (`modulos/gen_eventos`). Al arrancar con
  GEN_CTRL.EN dispara las marcas de `predecir` a medida que pasa el tiempo (`paso`
  ciclos por cada lectura de WR_SLOT), descarta por captura ocupada y por ring lleno, y
  escribe cada slot con el patrón, como el RTL.

El tiempo muerto de la captura es el de la placa, `2·S + 3` ciclos entre marcas
(ajustado al caso C2 del 2026-11-09, docs/event_ring/generador.md §6). Va escrito acá
y no importado del modelo de la campaña a propósito: este es el «hardware» contra el
que se prueba ese modelo.
"""

import struct
import threading

import numpy as np

from API._libmca import Bus, Mem
from API.osciloscope_ring import (
    GEN_CTRL_ALEATORIO, GEN_CTRL_EN, GEN_LAT_TS, GEN_MAGIC, GEN_SNAP_MARCA, MAGIC,
    R_CTRL, R_DROP_BUSY, R_DROP_FULL, R_EV_CNT, R_GEN_CNT, R_GEN_CTRL, R_GEN_DT_MIN,
    R_GEN_ESTADO, R_GEN_MAGIC, R_GEN_N, R_GEN_PERIODO, R_GEN_SEMILLA, R_GEN_UMBRAL,
    R_MAGIC, R_N_SLOTS, R_POST, R_PRE, R_RD_SLOT, R_RING_SZ, R_SEQ, R_SLOT_BASE,
    R_SLOT_SHIFT, R_STATUS, R_TS_HI, R_TS_LO, R_WR_SLOT, OsciloscopeRing, patron_gen)

M32 = 0xFFFFFFFF
DDR_PHYS = 0x0A00_0000
DDR_BYTES = 16 << 9                  # 16 slots de 512 B
MUERTO_EXTRA = 3                     # 2·S + 3: el de la placa
TRAMO_SIN_FIN = 50_000               # marcas por tramo con N = 0


class RingFalso:
    """El event_ring: los registros (por callbacks) y la región de DDR (un arreglo).

    `generar`, si está, se llama en cada lectura de WR_SLOT: es el hardware que
    dispara mientras el lazo de C sondea.
    """

    def __init__(self, ddr_bytes=DDR_BYTES, ddr_phys=DDR_PHYS):
        self.ddr = np.zeros(ddr_bytes, dtype=np.uint8)
        self.ddr_phys = ddr_phys
        self.reg = {R_MAGIC: MAGIC, R_SLOT_SHIFT: 9}
        self.run = 0
        self.gst = 0                    # 0 parado, 1 corriendo, 2 drenando
        self.drenaje = 0                # lecturas de STATUS que tarda en parar
        self.al_parar = 0
        self.err_cfg = False
        self.wr = self.rd = self.seq = 0
        self.ev = self.busy = self.full = 0
        self.ts = 0
        self.log = []
        self.generar = None
        self.n_wr_lecturas = 0

    # -- el bus --
    @property
    def n_slots(self):
        return self.reg.get(R_RING_SZ, 0) >> self.reg[R_SLOT_SHIFT]

    def _parado(self):
        self.gst = 0
        self.wr = self.rd = self.seq = 0

    def r32(self, off):
        if off == R_STATUS:
            if self.gst == 2:
                if self.drenaje > 0:
                    self.drenaje -= 1
                else:
                    self._parado()
            return (int(self.err_cfg) << 5) | self.gst
        if off == R_CTRL:
            return (self.gst << 1) | self.run
        if off == R_WR_SLOT:
            self.n_wr_lecturas += 1
            if self.generar is not None:
                self.generar(self)
            return self.wr & M32
        regs = {R_RD_SLOT: self.rd, R_SEQ: self.seq, R_N_SLOTS: self.n_slots,
                R_DROP_BUSY: self.busy, R_DROP_FULL: self.full, R_EV_CNT: self.ev,
                R_TS_LO: self.ts & M32, R_TS_HI: self.ts >> 32}
        if off in regs:
            return regs[off] & M32
        return self.reg.get(off, 0)

    def w32(self, off, v):
        self.log.append(('ring', off, v))
        if off == R_CTRL:
            if v & 2:
                self.ev = self.busy = self.full = 0
                self.err_cfg = False
                self.wr = self.rd = self.seq = 0
            self.run = v & 1
            if self.run and self.gst == 0:
                self.gst = 1
            elif not self.run and self.gst == 1:
                self.gst, self.drenaje = 2, self.al_parar
            return
        if off in (R_SLOT_BASE, R_RING_SZ, R_SLOT_SHIFT, R_PRE, R_POST):
            if self.gst != 0:
                self.err_cfg = True     # se pierde: sólo se toma parado
                return
            mask = {R_SLOT_SHIFT: 0x1F, R_PRE: 0x7FF, R_POST: 0x7FF}.get(off, M32)
            self.reg[off] = v & mask
            return
        if off == R_RD_SLOT:
            self.rd = v
            return
        self.reg[off] = v

    # -- la captura --
    def slot(self, seq):
        sz = 1 << self.reg[R_SLOT_SHIFT]
        off = (seq % self.n_slots) * sz
        return off, sz

    def footer(self, seq, bueno=True):
        off, sz = self.slot(seq)
        f = seq if bueno else seq + 12345
        self.ddr[off + sz - 8:off + sz] = np.frombuffer(
            struct.pack('<Q', (f & M32) | ((~f & M32) << 32)), np.uint8)

    def muestras(self, seq, s):
        """Las palabras de los dos canales del evento `seq`, con el signo extendido
        (lo que el ring escribe en DDR). Ceros: los tests ponen las suyas."""
        return np.zeros(s, '<i2'), np.zeros(s, '<i2')

    def disparar(self, snap=0x1, footer=True, n_samp=None):
        """Un evento, como lo escribe el RTL. Devuelve el seq, o por qué no entró."""
        if self.gst != 1:
            return 'parado'
        if self.wr - self.rd >= self.n_slots:
            self.full += 1
            return 'lleno'
        seq = self.seq
        s = self.reg[R_PRE] + self.reg[R_POST]
        off, sz = self.slot(seq)
        self.ts += 1000 + 7 * seq
        hdr = struct.pack('<QQQQ', self.ts,
                          (seq & M32) | ((n_samp or s) << 32) | (2 << 48), snap, 0)
        c0, c1 = self.muestras(seq, s)
        inter = np.empty(2 * s, dtype='<i2')
        inter[0::2], inter[1::2] = c0, c1
        datos = hdr + inter.tobytes()
        self.ddr[off:off + len(datos)] = np.frombuffer(datos, np.uint8)
        self.ddr[off + len(datos):off + sz] = 0
        if footer:
            self.footer(seq)
        self.seq += 1
        self.wr += 1
        self.ev += 1
        return seq

    def handle(self):
        bus = Bus.callbacks(self.r32, self.w32, size=0x1000)
        return OsciloscopeRing.sobre(bus, Mem.sobre(self.ddr, self.ddr_phys))


class RingFalsoGen(RingFalso):
    """`RingFalso` con el generador de eventos del ring.

    - `paso`: ciclos de 8 ns que pasan por cada lectura de WR_SLOT.
    - `corromper`: los k cuyo slot sale con una muestra mala.
    - `muerto_mas`: ciclos de más en el tiempo muerto (una captura que no es la de la
      placa).
    - `trabado`: drenando no para mientras haya créditos sin devolver (el ring lleno
      de la placa, STATUS = drenando + no_credit).
    """

    def __init__(self, paso=2000, corromper=(), ddr_bytes=1 << 18, muerto_mas=0,
                 trabado=False):
        super().__init__(ddr_bytes=ddr_bytes)
        self.reg[R_GEN_MAGIC] = GEN_MAGIC
        self.paso = paso
        self.corromper = set(corromper)
        self.muerto_mas = muerto_mas
        self.trabado = trabado
        self.marcas = None
        self._sin_fin = False
        self.gen_cnt = 0
        self.gen_fin = False
        # Leen WR_SLOT el hilo lector y el que pide los contadores, y cada lectura hace
        # avanzar al generador: sin el lock, dos `_avanzar` a la vez escribían el mismo
        # slot (el GIL no hace atómico a un callback de Python).
        self._lock = threading.Lock()
        self.generar = self._avanzar

    def r32(self, off):
        if off == R_GEN_CNT:
            return self.gen_cnt
        if off == R_GEN_ESTADO:
            return int(self.marcas is not None and not self.gen_fin) | int(self.gen_fin) << 1
        if off == R_STATUS and self.trabado and self.gst == 2 and self.wr != self.rd:
            return self.gst
        return super().r32(off)

    def w32(self, off, v):
        arranca = off == R_CTRL and v & 1 and self.gst == 0
        if off == R_CTRL and v & 2:
            self.gen_cnt, self.gen_fin, self.marcas = 0, False, None
        super().w32(off, v)
        if arranca and self.reg.get(R_GEN_CTRL, 0) & GEN_CTRL_EN:
            self._armar()
        if off == R_GEN_N and self.marcas is not None:
            with self._lock:
                self._cortar(v)

    def _cortar(self, n):
        """N escrito con el generador andando, como en el RTL (`hecho = cnt >= N`): dispara
        hasta que GEN_CNT llega a N, y si ya pasó no dispara más. Es lo que hace
        `RingSource.detener` (N ← 1). Volver a sin fin (N = 0) no lo usa nadie."""
        if not n:
            return
        while self._sin_fin and self.marcas.size < n:
            self.marcas = np.concatenate([self.marcas, self._tramo(self.marcas[-1])])
        self._sin_fin = False
        self.marcas = self.marcas[:max(n, self.k)]
        self.gen_fin = self.k >= self.marcas.size

    def _armar(self):
        import API.generadores as G

        r = self.reg
        d = G.disparos(aleatorio=bool(r[R_GEN_CTRL] & GEN_CTRL_ALEATORIO),
                       periodo=r[R_GEN_PERIODO], umbral=r[R_GEN_UMBRAL],
                       dt_min=r[R_GEN_DT_MIN], n=r[R_GEN_N], semilla=r[R_GEN_SEMILLA])
        n = d['n']
        if n:
            self.marcas = G.predecir(int(3 * n * 125e6 / G.tasa(**d)) + 10_000,
                                     GEN_LAT_TS, n_max=n, **d)
            if self.marcas.size != n:
                raise RuntimeError(f'predecir dio {self.marcas.size} marcas de {n}')
        else:
            # Sin fin (N = 0): tramos que se agregan a medida que se gastan (`_tramo`),
            # con la estadística del motor pero no ciclo a ciclo como el RTL. Es para
            # la demo y la GUI; los tests que comparan marcas usan N finito.
            self._d = d
            self._rng = np.random.default_rng(d['semilla'] or 1)
            self.marcas = self._tramo(GEN_LAT_TS)
        self._sin_fin = not n
        self.k, self.reloj, self.libre = 0, 0, -1
        self.muerto = 2 * (r[R_PRE] + r[R_POST]) + MUERTO_EXTRA + self.muerto_mas
        self.gen_cnt, self.gen_fin = 0, False

    def _tramo(self, desde):
        """TRAMO_SIN_FIN marcas después de `desde`: DT_MIN − 1 más una geométrica de
        p = UMBRAL/2^32 (aleatorio), o PERIODO (periódico)."""
        d = self._d
        if d['aleatorio']:
            p = max(d['umbral'], 1) / 2 ** 32
            gaps = max(d['dt_min'], 2) - 1 + self._rng.geometric(p, TRAMO_SIN_FIN)
        else:
            gaps = np.full(TRAMO_SIN_FIN, max(d['periodo'], 2), np.int64)
        return int(desde) + np.cumsum(gaps, dtype=np.int64)

    def _avanzar(self, rf=None):
        with self._lock:
            self._avanzar_solo()

    def _avanzar_solo(self):
        if self.gst != 1 or self.marcas is None or self.gen_fin:
            return
        self.reloj += self.paso
        while True:
            if self._sin_fin and self.k == self.marcas.size:
                self.marcas = np.concatenate(
                    [self.marcas, self._tramo(self.marcas[-1])])
            if not (self.k < self.marcas.size and self.marcas[self.k] <= self.reloj):
                break
            k, ts = self.k, int(self.marcas[self.k])
            self.k += 1
            self.gen_cnt += 1
            if ts < self.libre:
                self.busy += 1
            elif self.wr - self.rd >= self.n_slots:
                self.full += 1
            else:
                self._escribir(k, ts)
                self.libre = ts + self.muerto
        self.gen_fin = not self._sin_fin and self.k == self.marcas.size

    def _escribir(self, k, ts):
        # El footer al final, como el RTL: el lector de C corre sin el GIL y, con el
        # footer antes, copiaba slots a medio escribir.
        seq = self.disparar(snap=GEN_SNAP_MARCA | (k & 0xFFFF), footer=False)
        off, _ = self.slot(seq)
        s = self.reg[R_PRE] + self.reg[R_POST]
        self.ddr[off:off + 8] = np.frombuffer(np.int64(ts).tobytes(), np.uint8)
        p = patron_gen(ts, self.reg[R_PRE], s)
        inter = np.empty(2 * s, '<i2')
        inter[0::2], inter[1::2] = p[0], p[1]
        if k in self.corromper:
            inter[3] ^= 1
        self.ddr[off + 32:off + 32 + inter.nbytes] = np.frombuffer(inter.tobytes(), np.uint8)
        self.footer(seq)
