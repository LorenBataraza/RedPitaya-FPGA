"""Fuentes de evento: de donde salen los disparos y las ventanas de muestras.

La interfaz existe para que el dia que se migre a HP/DDR (streaming a la RAM,
ver docs/arquitectura_adquisicion_software.md Parte 5) solo cambie esta capa:

    class EventSource:
        scalar_fields  -> [(nombre, dtype), ...] que aporta al esquema del batch
        samples        -> muestras por ventana
        n_ch           -> canales
        arm()          -> deja el HW listo para disparar
        wait_event(deadline_ns) -> wp_trig del evento nuevo, o None si timeout
        read_into(batch, i, wp) -> escribe EN batch.wave[i], sin devolver nada
        close()

`read_into` escribe en el destino provisto en vez de devolver arrays: evita la
basura de GC de `capture_window_np` (que hace np.zeros por llamada y por canal),
y hace que la version DDR sea un memcpy sin capa intermedia.

`rp` y `multitrigger_utils` se importan DENTRO de BramSource, no arriba: asi
este modulo (y FakeSource) se puede usar en la PC, sin la placa.
"""

import time

import numpy as np

from .events import BASE_FIELDS

N_BUF         = 16384
ADC_CNT_PER_V = 8192           # escala LV (+-1 V); la misma de multitrigger_utils
WP_TRIG_OFF   = (0x1C, 0x11C)  # wp_trig por canal
SNAPSHOT_OFF  = 0x218


class BramSource:
    """Eventos desde el buffer BRAM del scope multitrigger.

    **Modo single-shot, no continuo.** Es una correccion medida en la placa, no
    una preferencia: con `we_keep=1` el buffer NUNCA se congela y da la vuelta
    cada 131 us (16384 muestras a 125 MS/s), asi que la ventana alrededor de
    `wp_trig` ya fue sobrescrita para cuando el lector llega a leerla (tarda
    ~100-200 us por evento). Medido, altura mediana de un pulso de 0.6 V leido
    con demora deliberada:

        demora     we_keep=1   single-shot
             0 us      0.600 V      0.602 V
           100 us      0.001 V      0.600 V     <- el continuo ya perdio el dato
          1000 us      0.001 V      0.600 V

    En single-shot la FSM detiene la escritura al completar el post-trigger
    (`adc_we <= 0`, rp_bram_sm.v:67) y el buffer queda congelado hasta el
    proximo arm: el lector puede tardar lo que quiera. Ese freeze es
    exactamente para lo que existe (ver docs/orden_arm_trigger_captura.md).

    El precio es que hay que re-armar por software despues de cada lectura, y
    mientras tanto el scope esta ciego: ese es el dead-time real del metodo.

    El `trigger_shield` se deja activo igual, porque limpia `adc_trg_dis`
    automaticamente y ahorra el pulso a 0x94 en cada re-arm.
    """

    def __init__(self, scope, pre=8, post=24, n_ch=2, thr=0.5, hyst=0.02,
                 mask=None, delay=None, read_snap=True, wp_addr=WP_TRIG_OFF[0],
                 single_shot=True):
        import struct
        from multitrigger_utils import BIT_ADC_P0

        self.sc        = scope
        self.pre       = pre
        self.post      = post
        self.samples   = pre + post
        self.n_ch      = n_ch
        self.thr       = thr
        self.hyst      = hyst
        self.mask      = BIT_ADC_P0 if mask is None else mask
        # El post-trigger ES dead-time real: mientras corre, adc_dly_do bloquea
        # la actualizacion de wp_trig (rp_bram_sm.v:91). Se pide el minimo que
        # cubre la ventana. Nunca 0: set_dly=0 es el caso degenerado que no
        # congela nunca el buffer (ver rp_bram_sm.v:67, comparacion == 1 exacta).
        self.delay     = max(1, post if delay is None else delay)
        self.read_snap   = read_snap
        self.wp_addr     = wp_addr
        self.single_shot = single_shot

        self._u32      = struct.Struct('<I')
        self._mem      = scope._mmap
        self._wp_prev  = 0
        self._fbufs    = None
        self._views    = None
        self._chs      = None

    # -- ciclo de vida ------------------------------------------------------

    scalar_fields = BASE_FIELDS

    def arm(self):
        import ctypes
        import rp

        self._chs = (rp.RP_CH_1, rp.RP_CH_2, rp.RP_CH_3, rp.RP_CH_4)[:self.n_ch]

        # ORDEN CRITICO: arma (0x00) y RECIEN DESPUES habilita la mascara
        # (0x240/0x244). arm_for_adc_trigger ya lo hace internamente.
        self.sc.arm_for_adc_trigger(
            mask_ch0=self.mask, mask_ch1=self.mask,
            thr=self.thr, hyst=self.hyst, delay=self.delay,
            we_keep_both=not self.single_shot, auto_rearm=True)

        # Un fBuffer por canal, reusado en todo el lazo. La vista numpy se arma
        # UNA vez sobre el puntero del buffer (no por evento): asi `read_into`
        # es una sola copia hacia la fila del batch.
        n = self.samples
        self._fbufs = [rp.fBuffer(n) for _ in range(self.n_ch)]
        self._views = [
            np.frombuffer((ctypes.c_float * n)
                          .from_address(int(fb.cast().__int__())),
                          dtype=np.float32)
            for fb in self._fbufs]

        self._wp_prev = self._u32.unpack_from(self._mem, self.wp_addr)[0]

    def _rearm(self):
        """Re-arma para el proximo evento. Tres escrituras, ~6 us.

        ORDEN CRITICO: primero 0x00 (arma la bram_sm) y RECIEN DESPUES la
        mascara (0x240/0x244). Al reves, un flanco que llegue en el hueco
        gasta la mascara con la FSM todavia sin armar y queda esperando un
        trigger imposible (ver docs/orden_arm_trigger_captura.md).

        No hace falta pulsar 0x94: el `trigger_shield` limpia adc_trg_dis solo.
        Tampoco se usa `set_or_mask`, que valida con dos lecturas de readback:
        aca cada microsegundo es dead-time.
        """
        w32 = self.sc.w32
        w32(0x00, 0x0000_0101)          # arm ch0+ch1, single-shot
        w32(0x240, self.mask)
        w32(0x244, self.mask)

    def close(self):
        self.sc.disarm()

    # -- lazo caliente ------------------------------------------------------

    def wait_event(self, deadline_ns):
        """Espera a que haya un evento listo. Devuelve wp_trig, o None.

        En single-shot la senal correcta es `adc_we == 0` (bit 0 de adc_state
        @0x00): la FSM completo el post-trigger y CONGELO el buffer. Es
        inequivoca, a diferencia de mirar cambios de wp_trig, que falla si dos
        triggers consecutivos caen en la misma posicion del buffer circular
        (posible con una fuente periodica que aliasee con las 16384 muestras).
        """
        mem, unpack = self._mem, self._u32.unpack_from
        pc = time.perf_counter_ns
        if self.single_shot:
            while True:
                if not (unpack(mem, 0x00)[0] & 0x1):     # adc_we == 0: congelado
                    return unpack(mem, self.wp_addr)[0]
                if pc() > deadline_ns:
                    return None
        off, prev = self.wp_addr, self._wp_prev
        while True:
            wp = unpack(mem, off)[0]
            if wp != prev:
                self._wp_prev = wp
                return wp
            if pc() > deadline_ns:
                return None

    def snapshot(self):
        """Que fuente disparo (0x218). Cuesta una lectura mas (~2.3 us, 2.5%
        del presupuesto por evento): se puede apagar con read_snap=False."""
        if not self.read_snap:
            return 0
        return self._u32.unpack_from(self._mem, SNAPSHOT_OFF)[0]

    def read_into(self, batch, i, wp):
        """Ventana [wp-pre, wp+post-1] de cada canal -> batch.wave[i, k].

        Se usa `rp_AcqGetDataPosV` y no un acceso directo al mmap: medido, el
        acceso directo por numpy es 3.6x mas lento, y un memcpy sobre la region
        de BRAM CUELGA EL PUERTO AXI y reinicia la placa (el esclavo de la PL
        solo atiende accesos de 32 b alineados). Ver el doc, Parte 3.

        `end_pos` es INCLUSIVO y la API resuelve el wrap circular sola (start >
        end en una sola llamada da bit a bit lo mismo que partirlo en dos:
        verificado en tests/bench_reader_budget.py).
        """
        import rp

        n     = self.samples
        start = (wp - self.pre) % N_BUF
        end   = (start + n - 1) % N_BUF
        dst   = batch.wave[i]
        get   = rp.rp_AcqGetDataPosV
        for k, ch in enumerate(self._chs):
            get(ch, start, end, self._fbufs[k], n)
            dst[k] = self._views[k]
        if self.single_shot:
            # Re-armar AL FINAL: entre el trigger y esta linea el scope esta
            # ciego, y ese hueco es el dead-time real del metodo.
            self._rearm()

    # -- metadatos ----------------------------------------------------------

    def meta(self):
        return dict(kind='bram', pre=self.pre, post=self.post,
                    samples=self.samples, n_ch=self.n_ch, thr_V=self.thr,
                    hyst_V=self.hyst, mask=int(self.mask), set_dly=self.delay,
                    read_snap=self.read_snap, single_shot=self.single_shot,
                    adc_cnt_per_V=ADC_CNT_PER_V)


class FakeSource:
    """Fuente sintetica: pulsos generados en SW, sin placa ni modulo `rp`.

    Existe para poder desarrollar y testear TODO el pipeline en la PC. El
    `rate_hz` es nominal: se respeta con un sleep grueso, asi que no sirve para
    medir dead-time, solo para validar la mecanica (colas, descartes, formato).
    """

    scalar_fields = BASE_FIELDS

    def __init__(self, pre=8, post=24, n_ch=2, rate_hz=1000.0, amplitude=0.5,
                 seed=0, n_events=None):
        self.pre       = pre
        self.post      = post
        self.samples   = pre + post
        self.n_ch      = n_ch
        self.period_ns = 1e9 / rate_hz if rate_hz else 0.0
        self.amplitude = amplitude
        self.n_events  = n_events
        self._rng      = np.random.default_rng(seed)
        self._wp       = 0
        self._emitted  = 0
        self._next_ns  = 0
        # Forma de pulso fija: subida rapida, caida exponencial (aprox. a un
        # pulso de centelleo). La altura se sortea por evento.
        t = np.arange(self.samples, dtype=np.float32) - pre
        self._shape = np.where(t < 0, 0.0, np.exp(-t / max(post / 4.0, 1.0)))
        self._shape = self._shape.astype(np.float32)

    def arm(self):
        self._next_ns = time.perf_counter_ns()

    def close(self):
        pass

    @property
    def exhausted(self):
        """Fuente finita: le avisa al lector que no van a llegar mas eventos.

        Sin esto, el lector no puede distinguir 'todavia no llego nada' de 'no
        va a llegar nunca mas' y gira en timeouts para siempre. `BramSource` no
        lo define: nunca se agota.
        """
        return self.n_events is not None and self._emitted >= self.n_events

    def wait_event(self, deadline_ns):
        if self.exhausted:
            return None
        pc = time.perf_counter_ns
        while pc() < self._next_ns:
            if pc() > deadline_ns:
                return None
        self._next_ns += self.period_ns
        self._emitted += 1
        self._wp = (self._wp + 137) % N_BUF        # avanza como un wp real
        return self._wp

    def snapshot(self):
        return 2                                    # BIT_ADC_P0

    def read_into(self, batch, i, wp):
        h = self.amplitude * (0.5 + self._rng.random())
        for k in range(self.n_ch):
            batch.wave[i, k] = self._shape * h + self._rng.normal(
                0, 0.002, self.samples).astype(np.float32)

    def meta(self):
        return dict(kind='fake', pre=self.pre, post=self.post,
                    samples=self.samples, n_ch=self.n_ch,
                    amplitude=self.amplitude, adc_cnt_per_V=ADC_CNT_PER_V)
