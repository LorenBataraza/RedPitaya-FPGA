"""Fuentes de evento: de donde salen los disparos y las ventanas de muestras.

La interfaz existe para que el dia que se migre a HP/DDR (streaming a la RAM,
ver docs/arquitectura_adquisicion_software.md Parte 5) solo cambie esta capa:

    class EventSource:
        scalar_fields  -> [(nombre, dtype), ...] que aporta al esquema del batch
        samples        -> muestras por ventana
        n_ch           -> canales
        wave_dtype     -> opcional: el tipo de `batch.wave` (float32 en volts si no)
        arm()          -> deja el HW listo para disparar
        close()

        opcional, al parar (`AcquisitionSession.stop`, antes de parar el lector):
        detener()      -> corta el estímulo con el HW corriendo
        vaciado()      -> True si no queda nada en vuelo ni sin leer

    y una de dos formas de entregar eventos:

        por lote (la que se usa si existe):
        read_batch(batch, deadline_ns) -> (nuevos, descartados, asignados)
        pending        -> descartados que todavia no fueron a ningun `gap`

        por evento:
        wait_event(deadline_ns) -> wp_trig del evento nuevo, o None si timeout
        snapshot()              -> que fuente disparo
        read_into(batch, i, wp) -> escribe EN batch.wave[i], sin devolver nada
        rearm()

`read_batch` llena las filas desde `batch.n`, sin tocar `batch.n`, hasta llenar el
batch o vencer el plazo. Con `batch=None` no hay donde guardar: cuenta los eventos
como descartados y re-arma. Escribe `wave` y las columnas de BASE_FIELDS, y
`dead_ns` si el batch la tiene. `BramSource` y `RingSource` (en
`API/osciloscope_ring.py`) son por lote, con el lazo en C; `FakeSource`, por evento.

`read_into` escribe en el destino provisto en vez de devolver arrays: evita la
basura de GC y hace que la version DDR sea un memcpy sin capa intermedia.
"""

import time

import numpy as np

from API.multitrigger import BIT_ADC_P0
from API.osciloscope import Lector, _cal_dict, calibracion_adc

from .events import BASE_FIELDS

N_BUF         = 16384          # el anillo de FakeSource; BramSource usa el del bitstream
ADC_CNT_PER_V = 8192           # escala LV (+-1 V); la misma de multitrigger_utils
WP_TRIG_OFF   = (0x1C, 0x11C)  # wp_trig por canal, en el slot 1
DT_NS         = 8.0            # 125 MS/s: `multitrigger_arm` arma sin diezmado

# Lo que el lazo de C vuelve a mirar `stop`: cada cuanto, como mucho, devuelve.
PLAZO_LOTE_NS = 50_000_000


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

    **El lazo es de C** (`osciloscope_leer_lote`, via `API.osciloscope.Lector`):
    esperar, anotar, leer la ventana, re-armar, sin el GIL. Por eso hace falta un
    scope de libmca (`impl='c'`); con la referencia de Python, TypeError al armar.

    **`wave` son cuentas calibradas** (int16), las de librp: m = gain*(s - offset)
    / base, con los numeros de la EEPROM (`calib=None` los lee al armar; si no se
    pueden leer, error). Son los mismos que antes salian de rint(V*8192) con la V
    de `rp_AcqGetDataPosV`, y van a la metadata.

    El `trigger_shield` se deja activo igual, porque limpia `adc_trg_dis`
    automaticamente y ahorra el pulso a 0x94 en cada re-arm.

    **Dos regiones.** El estado de la FSM y `wp_trig` estan en el slot 1 (`sc`);
    las mascaras y el snapshot, en el slot 3 (`sc.mt`, mt_cfg.sv). El slot 1 ya no
    decodifica 0x240/0x244/0x218: una escritura ahi se pierde sin error, y como en
    single-shot `mt_trig_src` borra la mascara al disparar, el scope captura un
    evento y no dispara mas.
    """

    scalar_fields = BASE_FIELDS
    wave_dtype    = np.int16

    def __init__(self, scope, pre=8, post=24, n_ch=2, thr=0.5, hyst=0.02,
                 mask=None, delay=None, read_snap=True, wp_addr=WP_TRIG_OFF[0],
                 single_shot=True, calib=None):
        self.sc        = scope
        self.mt        = scope.mt
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
        # La calibracion de cada canal: dada, o la de la EEPROM al armar.
        self.calib     = None if calib is None else [_cal_dict(c) for c in calib]
        self._lector   = None

    # -- ciclo de vida ------------------------------------------------------

    def arm(self):
        if self.calib is None:
            self.calib = calibracion_adc(range(self.n_ch))
        if len(self.calib) < self.n_ch:
            raise ValueError(f'{len(self.calib)} calibraciones para {self.n_ch} canales')
        lector = Lector(self.sc, self.mt, pre=self.pre, post=self.post,
                        n_ch=self.n_ch, mascara=self.mask, cal=self.calib[:self.n_ch],
                        wp_off=self.wp_addr, single_shot=self.single_shot,
                        rearmar=True, leer_snap=self.read_snap)

        # ORDEN CRITICO: arma (0x00) y RECIEN DESPUES habilita la mascara.
        # arm_for_adc_trigger ya lo hace internamente.
        self.sc.arm_for_adc_trigger(
            mask_ch0=self.mask, mask_ch1=self.mask,
            thr=self.thr, hyst=self.hyst, delay=self.delay,
            we_keep_both=not self.single_shot, auto_rearm=True)
        lector.iniciar()                 # valida y toma el wp_trig de ahora
        self._lector = lector

    def close(self):
        self.sc.disarm()

    # -- lazo caliente ------------------------------------------------------

    def read_batch(self, batch, deadline_ns):
        """Llena `batch` desde `batch.n`, en C: ver la interfaz arriba.

        Por evento, en este orden: `wp`, `t_ns`, el `gap` con los descartados
        desde el anterior, `snap` (salvo read_snap=False), la ventana de cada
        canal, el re-armado y `dead_ns`, que es el tiempo ciego: del disparo
        visto al re-armado. Es la misma definicion del `DeadTimeAnnotator`.
        """
        if batch is None:
            return self._lector.leer(None, 0, 2**32 - 1, deadline_ns)
        return self._lector.leer(batch, batch.n, batch.capacity - batch.n,
                                 deadline_ns)

    @property
    def pending(self):
        return self._lector.pendientes if self._lector is not None else 0

    # -- metadatos ----------------------------------------------------------

    def meta(self):
        return dict(kind='bram', pre=self.pre, post=self.post,
                    samples=self.samples, n_ch=self.n_ch, thr_V=self.thr,
                    hyst_V=self.hyst, mask=int(self.mask), set_dly=self.delay,
                    read_snap=self.read_snap, single_shot=self.single_shot,
                    adc_cnt_per_V=ADC_CNT_PER_V, dt_ns=DT_NS,
                    wave='cuentas calibradas: las de librp (cmn_CalibCntsSigned)',
                    calib=None if self.calib is None else
                    [dict(c) for c in self.calib[:self.n_ch]],
                    lector='libmca')


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

    def rearm(self):
        """No-op: la fuente sintetica no tiene FSM que re-armar."""

    def read_into(self, batch, i, wp):
        h = self.amplitude * (0.5 + self._rng.random())
        for k in range(self.n_ch):
            batch.wave[i, k] = self._shape * h + self._rng.normal(
                0, 0.002, self.samples).astype(np.float32)

    def meta(self):
        return dict(kind='fake', pre=self.pre, post=self.post,
                    samples=self.samples, n_ch=self.n_ch,
                    amplitude=self.amplitude, adc_cnt_per_V=ADC_CNT_PER_V,
                    dt_ns=DT_NS)
