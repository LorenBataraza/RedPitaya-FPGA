#!/usr/bin/env python3
"""El MCA por socket (`MCARemote`) y un MCA simulado (`FakeMCA`).

Los dos son un `MCA`: mismo handle, mismos métodos, misma geometría leída
del hardware. Eso es lo que hace que **toda la superficie `mca_*` de API/mca.py
funcione sin tocar una línea**::

    from API.mca import mca_set_n_acc, mca_get_config, mca_read_histogram
    from API.mca_remote import MCARemote

    h = MCARemote.connect('10.73.28.27')
    mca_set_n_acc(h, 4)              # 1 ida y vuelta: corre ENTERA en la placa
    cfg  = mca_get_config(h)         # 1
    hist = mca_read_histogram(h)     # 1, con payload binario

Es el mismo patrón con el que `RingSource` es drop-in de `BramSource`: la
interfaz la fija el consumidor, no el transporte.

`FakeMCA` no toca nada y simula un fotopico que crece: sirve para desarrollar
la GUI entera en la PC, como `FakeSource` para el pipeline del osciloscopio.

Desde que la API pasó a C (libmca), los dos se enchufan distinto:

  FakeMCA     hereda de `API.mca.MCA` y su modelo de registros (Python) entra a
              libmca por el backend de callbacks: la lógica que se prueba
              contra el simulador es la MISMA de C que corre en la placa.
  MCARemote   es un proxy, como un cliente SCPI de Red Pitaya: `_via =
              'remoto'`, y cada función `mca_*` sale ENTERA por la op `call` y
              corre en la placa, bajo el lock del servidor. No abre libmca: la
              PC no necesita la biblioteca.
"""

import threading
import time

import numpy as np

from API.mca import (AMP_W, APERTURE_2D, APERTURE_H, CAP_HIST_H,
                     MCANotPresent, R_MAGIC as _R_MAGIC,
                     CAP_HIST_H_PSD, CAP_TRAP, FS_HZ, MAGIC, MCA,
                     R_AMP_MAX, R_AMP_MIN, R_AMP_SRC, R_BASELINE,
                     R_BASELINE_NOW, R_BL_CTRL, R_CAPS, R_CNT_ACCEPTED,
                     R_CNT_CROSS, R_CNT_DROPPED, R_CNT_OPEN, R_CNT_PILEUP,
                     R_CNT_REJ_AMP, R_CNT_REJ_PSD, R_CNT_TOTAL, R_CNT_TRIG,
                     R_CNT_WIN, R_CTRL, R_DEADTIME_HI, R_DEADTIME_LO, R_DEC,
                     R_DISCR_MAX, R_FORMA1_KM, R_FORMA1_MED, R_FORMA1_UMBR,
                     R_FORMA2_KM, R_FORMA2_MED, R_FORMA2_UMBR, R_FORMA3_KM,
                     R_FORMA3_MED, R_FORMA3_UMBR, R_GATE_LEN, R_HIST_CTRL, R_HIST_SEL,
                     R_LAST_AMP, R_LAST_PSD, R_LAST_QTAIL, R_LAST_QTOT,
                     R_LIVETIME_HI, R_LIVETIME_LO, R_MAGIC, R_N_ACC,
                     R_N_ACC_MAX, R_N_FORMAS, R_PRE_DLY, R_PUB_STATE, R_REALTIME_HI,
                     R_REALTIME_LO, R_STATUS, R_T_CLEAR_HI, R_T_CLEAR_LO,
                     R_T_DIV_HI, R_T_DIV_LO, R_T_REARM_HI, R_T_REARM_LO,
                     R_T_OCUP, R_T_WIN_HI, R_T_WIN_LO,
                     R_TRAP_KM, R_TRAP_MED, R_TRAP_MQ, R_TRAP_UMBR, R_VETOTIME_HI,
                     R_VETOTIME_LO, R_WIDTHS, R_ZOOM_1D, R_ZOOM_2DX, TRAP_LAT)
from API.mca_net import PORT_DEFAULT, Channel, RemoteError, array_desde
from API.multitrigger import (CAPS_HAS_PZ, CAPS_HAS_SLOPE, MTRG_MAGIC, R3_CAPS,
                              R3_FLAGS, MtRegion, MultiTrigger,
                              R_FLAGS, R_OR_MASK_CH0, R_OR_MASK_CH1, R_SHIELD_CFG,
                              R_SHIELD_RUN, R_TRIG_SNAP)
from API.mca_net import a_json, de_json
from API._despacho import NoRemota
# Sólo la escala del ADC, para que el osciloscopio simulado devuelva volts con
# la MISMA constante que usa el real y no con una copia que puede divergir.
# `API/osciloscope.py` es importable en la PC (la librería `rp` se carga
# perezosamente), así que esto no ata este módulo a la placa.
from API.osciloscope import (ADC_CNT_PER_V, MAGIC_OSC, R_CANON_CAPS, R_CANON_MAGIC,
                             Osciloscope)


# =============================================================================
# Handle remoto
# =============================================================================

# Los tipos con que una excepción del servidor vuelve a lanzarse en el cliente:
# una subclase de RemoteError Y del tipo original, así sirven `except
# ValueError` (como en la placa) y `except RemoteError` (como antes). Los de la
# familia de OSError NO: un OSError en el cliente quiere decir que se cayó el
# transporte, y la GUI corta la conexión (un TimeoutError del clear queda como
# RemoteError, con `.error == 'TimeoutError'`).
_TIPOS_REMOTOS = {t.__name__: t for t in (
    ValueError, TypeError, KeyError, IndexError, NotImplementedError,
    RuntimeError, MemoryError, MCANotPresent, NoRemota)}
_CLASES_REMOTAS = {}


def excepcion_remota(error, msg, hint=None):
    """La excepción de un `call` que falló en el servidor."""
    base = _TIPOS_REMOTOS.get(error)
    if base is None:
        return RemoteError(error, msg, hint)
    cls = _CLASES_REMOTAS.get(error)
    if cls is None:
        cls = _CLASES_REMOTAS[error] = type(f'Remoto{error}', (RemoteError, base),
                                            {'__module__': __name__})
    return cls(error, msg, hint)


class MCARemote(MCA):
    """Un MCA cuyo hardware está del otro lado del socket.

    Es un proxy: hereda los métodos del binding (`configure`, `counters`,
    `spectrum`, ...), que llaman a las funciones `mca_*`, y con `_via =
    'remoto'` el despacho de `@_api` las manda enteras al servidor por la op
    `call`. Cada una es UNA ida y vuelta y corre en la placa bajo el lock del
    servidor, así que un read-modify-write es atómico (antes eran dos idas y
    vueltas, y se podía cruzar con el hilo de exposición).

    No llama al constructor del binding: ése abriría libmca, y el cliente
    remoto no la necesita (igual que un cliente SCPI no corre librp).

    Lo que espera (`acquire`, `acquire_chunks`, `autoscale_q_shift`) no viaja
    por `call`: tendría tomado el lock del servidor. Se arma acá con start,
    sleep y stop remotos, así un script que los use sigue andando.
    """

    impl = 'remoto'
    _via = 'remoto'

    def __init__(self, canal, info):
        self._mmap, self._fd, self._c, self._bus = None, -1, None, None
        self.caps = info['caps']
        self.h_aw, self.h2_aw, self.psd_aw = (info['h_aw'], info['h2_aw'],
                                              info['psd_aw'])
        self._has_2d = bool(self.caps & CAP_HIST_H_PSD)
        # La de la placa: es la que corre lo que llega por `call`.
        self.libmca_version = info.get('libmca_version')
        self._canal = canal
        self._lock = threading.Lock()
        self.info = info
        # Qué bloques trae ESTE bitstream. El cliente crea o no cada pestaña
        # con esto, igual que ya hacía con `_has_2d`; nunca se supone.
        self._has_integracion = bool(info.get('has_integracion'))
        self._has_osc = bool(info.get('has_osc'))
        self._has_mtrg = bool(info.get('has_mtrg'))

    @classmethod
    def connect(cls, host, port=PORT_DEFAULT, timeout=10.0):
        canal = Channel.connect(host, port, timeout)
        try:
            obj, _ = _pedir_en(canal, 'identify')
        except Exception:
            canal.close()
            raise
        info = obj['result']
        if info.get('protocol', 1) < 2:
            canal.close()
            raise RemoteError('ProtocolError', 'el servidor habla el protocolo '
                              f"{info.get('protocol', 1)} y este cliente "
                              'necesita el 2 (la op call)',
                              'actualizar el software de la placa: make placa-sync')
        return cls(canal, info)

    # ---------- transporte ----------

    def _pedir(self, op, **args):
        # El lock es barato y evita que dos hilos entrelacen cabeceras en el
        # mismo socket, que desincronizaría el stream sin diagnóstico posible.
        with self._lock:
            return _pedir_en(self._canal, op, **args)

    def call(self, nombre, *a, **k):
        """Una función de API/mca.py, entera, en la placa (op `call`)."""
        try:
            obj, payload = self._pedir('call', fn=nombre, a=a_json(list(a)),
                                       k=a_json(k))
        except RemoteError as e:
            raise excepcion_remota(e.error, e.msg, e.hint) from None
        if payload is not None:
            return array_desde(obj, payload)
        return de_json(obj['result']['valor'])

    def close(self):
        canal, self._canal = getattr(self, '_canal', None), None
        if canal is not None:
            canal.close()

    # ---------- acceso crudo ----------
    #
    # El binding los resuelve en C (libmca); acá van por las ops r32/w32.

    def w32(self, off, v):
        self._pedir('w32', off=int(off), val=int(v) & 0xFFFFFFFF)

    def r32(self, off):
        return int(self._pedir('r32', off=int(off))[0]['result']['val'])

    def _r64(self, off_lo, off_hi):
        lo = self.r32(off_lo)                   # LO primero: congela la HI
        return (self.r32(off_hi) << 32) | lo

    def _read_words(self, offset, n):
        return np.array([self.r32(offset + 4 * i) for i in range(n)],
                        dtype=np.uint32)

    def tiene_features(self):
        return self.r32(_R_MAGIC) == MAGIC

    def exigir_features(self):
        if not self.tiene_features():
            raise MCANotPresent('el bitstream de la placa no es el "MCA2"')
        return True

    # ---------- lo que espera: no viaja por `call` ----------

    def en_el_cliente(self, nombre):
        """Las funciones que esperan, armadas acá: el despacho de `@_api` las
        pide en vez de mandarlas por `call` (`mca_read_acquire(h, ...)` anda
        igual que `h.acquire(...)`)."""
        return {'mca_read_acquire': self.acquire,
                'mca_read_acquire_chunks': self.acquire_chunks}.get(nombre)

    def acquire(self, seconds, clear_first=True):
        """(espectro, mapa2d|None, contadores) de `seconds` de reloj de pared.

        start, sleep y stop van cada uno por `call` (atómicos en la placa); el
        tiempo lo mide el cliente, con la latencia de la red en los bordes.
        Para exposiciones por tiempo VIVO, `ctrl.start` con `seconds`.
        """
        if clear_first:
            self.stop()
            self.clear()
        self.start()
        time.sleep(seconds)
        self.stop()
        time.sleep(0.01)          # las ranuras abiertas cierran y publican
        m2d = self.map2d() if self._has_2d else None
        return self.spectrum(), m2d, self.counters()

    def acquire_chunks(self, seconds, chunk_s, on_chunk=None):
        self.stop()
        self.clear()
        n = max(1, int(round(seconds / max(chunk_s, 1e-3))))
        for k in range(n):
            self.start()
            time.sleep(chunk_s)
            self.stop()
            time.sleep(0.01)
            if on_chunk is not None and k < n - 1:
                on_chunk(k)
        m2d = self.map2d() if self._has_2d else None
        return self.spectrum(), m2d, self.counters()

    def autoscale_q_shift(self, target_channel=8000, seconds=0.5, **cfg):
        if cfg:
            self.configure(**cfg)
        self.acquire(seconds)
        q = self.last_event()['q_tot']
        if q <= 0:
            return None
        shift = int(round(np.log2(max(q / max(target_channel, 1), 1e-9))))
        return int(np.clip(shift, 0, 31))

    # ---------- extras que sólo tienen sentido por red ----------

    def status(self):
        """Contadores + running + tasas + estado de la exposición.

        Es lo que poléa la GUI: una sola vuelta con todo lo que va en pantalla
        salvo el espectro.
        """
        return self._pedir('status')[0]['result']

    def config(self):
        """Todos los campos de configuración en una ida y vuelta.

        `mca_get_config(h)` da lo mismo, también en una ida y vuelta (`call`):
        ésta es la op que la GUI ya usaba.
        """
        return self._pedir('config.get')[0]['result']

    def metadata(self):
        return self._pedir('read.metadata')[0]['result']

    def pedir(self, op, **args):
        """Una operación del protocolo por su nombre, y su `result`.

        Es la vía para lo que NO es el MCA: el slot 6 (`integracion.*`) tiene su
        driver del lado de la placa, así que el cliente no puede llamar a
        `API/integration.py` — sólo pedirle al servidor que lo haga. Sin esto,
        cada bloque nuevo obligaría a un método más en esta clase.

        Para el MCA en sí NO usar esto: `MCARemote` ES un `MCA`, y toda la
        superficie `mca_*` funciona sobre él sin saber que hay una red.
        """
        return self._pedir(op, **args)[0]['result']

    def capturar_osc(self, pre=0, post=1024):
        """Una ventana del osciloscopio: `(metadata, float32[2, pre+post])`.

        No pasa por `pedir()` porque ésa devuelve sólo el `result` y tira el
        payload binario. Es la segunda operación del protocolo que trae datos
        además de JSON, después del espectro y el mapa 2D.
        """
        obj, payload = self._pedir('osc.capture', pre=int(pre), post=int(post))
        return obj['result'], array_desde(obj, payload)

    def fpga_state(self):
        return self._pedir('fpga.state')[0]['result']

    def load_bitstream(self, path=None):
        """Recarga la PL en el servidor y devuelve el identify nuevo.

        El servidor cierra el mmap ANTES de reprogramar: reconfigurar con
        mapeos abiertos deja el puerto GP0 trabado hasta reiniciar la placa.
        """
        info = self._pedir('fpga.load_bitstream', path=path)[0]['result']
        self.caps = info['caps']
        self.h_aw, self.h2_aw, self.psd_aw = (info['h_aw'], info['h2_aw'],
                                              info['psd_aw'])
        self._has_2d = bool(self.caps & CAP_HIST_H_PSD)
        # El bitstream nuevo puede traer otros bloques que el anterior: si no
        # se refrescan acá, la GUI queda con las pestañas del bitstream viejo.
        self._has_integracion = bool(info.get('has_integracion'))
        self._has_osc = bool(info.get('has_osc'))
        self._has_mtrg = bool(info.get('has_mtrg'))
        self.info = info
        return info

    # ---------- event_ring (slot 2): una adquisición en la placa ----------
    #
    # La sesión corre en el servidor (`AdquisicionRing`) y escribe en un camino de la
    # placa: la SD, /dev/shm o un directorio de la PC montado allá. Por el socket van
    # sólo el control y el estado; los datos, por el montaje.

    @property
    def has_ring(self):
        """¿El bitstream de la placa trae el event_ring?"""
        return bool(self.info.get('has_ring'))

    @property
    def has_gen(self):
        """¿Y su generador de eventos?"""
        return bool(self.info.get('has_gen'))

    def ring_iniciar(self, run_dir, **kw):
        """Arranca una adquisición del ring en la placa: los argumentos de
        `API.osciloscope_ring.AdquisicionRing` (`pre`, `post`, `generador` o
        `disparo`, `calib`, `formato`, `capacity`, `ram_mb`, `margen_mb`, `meta`).
        `run_dir` es un camino de la placa. Devuelve `run_dir`, `fs`, `n_slots` y
        `pool`."""
        return self._pedir('ring.iniciar', run_dir=run_dir, **kw)[0]['result']

    def ring_estado(self):
        """`corriendo`, `motivo`, `stats` (la sesión), `hw` (los contadores del ring) y
        `error`, sin frenar la adquisición."""
        return self._pedir('ring.estado')[0]['result']

    def ring_parar(self):
        """Para la adquisición y devuelve `stats`, `hw_final`, `n_slots` y `error`."""
        return self._pedir('ring.parar')[0]['result']


def _pedir_en(canal, op, **args):
    """Una operación sobre un Channel -> (cabecera, payload)."""
    canal.send({'op': op, 'args': args})
    obj, payload = canal.recv()
    if not obj.get('ok'):
        raise RemoteError(obj.get('error', 'Error'), obj.get('msg', ''),
                          obj.get('hint'))
    return obj, payload


# =============================================================================
# MCA simulado
# =============================================================================
#
# Reproduce el mapa "MCA2", no una API paralela: los campos y sus
# read-modify-write, la geometría publicada en WIDTHS, N_ACC, el barrido de
# clear y el registro sombra de los relojes de 64 bits. Si algo anda contra
# FakeMCA y no contra la placa, la diferencia está en el hardware, no en el
# simulador.

_DEFAULTS_RESET = {          # los del RTL, mca_top.sv (reset de la config)
    R_CTRL:       0,
    R_BASELINE:   0,
    R_BL_CTRL:    6 << 4,                     # bl_k=6, auto=0
    R_AMP_MIN:    0,
    R_AMP_MAX:    0xFFFF,
    R_AMP_SRC:    0,
    R_DEC:        1,
    R_GATE_LEN:   (384 << 16) | 32,
    R_HIST_SEL:   0x200,                      # pico, pico, psd
    R_DISCR_MAX:  0xFFFF,
    R_HIST_CTRL:  0,
    R_N_ACC:      1,
    R_PRE_DLY:    11,
    R_TRAP_KM:    (32 << 16) | 64,
    R_TRAP_MQ:    0,
    R_TRAP_MED:   (7 << 24) | (4 << 16) | 72,
    R_N_FORMAS:   1,
    # El banco: cada forma, la mitad de la anterior (mca_top.sv, reset).
    R_FORMA1_KM:  (16 << 16) | 32,
    R_FORMA1_MED: (6 << 24) | (3 << 16) | 40,
    R_FORMA2_KM:  (8 << 16) | 16,
    R_FORMA2_MED: (5 << 24) | (2 << 16) | 22,
    R_FORMA3_KM:  (4 << 16) | 8,
    R_FORMA3_MED: (4 << 24) | (1 << 16) | 13,
}

# Los relojes de 64 b del modelo: (LO, HI) -> nombre del atributo que da
# segundos. t_ocup[j] va aparte.
_RELOJES = {
    R_REALTIME_LO: (R_REALTIME_HI, '_realtime'),
    R_LIVETIME_LO: (R_LIVETIME_HI, '_livetime'),
    R_DEADTIME_LO: (R_DEADTIME_HI, '_muerto'),
    R_T_WIN_LO:    (R_T_WIN_HI, '_muerto'),
    R_VETOTIME_LO: (R_VETOTIME_HI, None),
    R_T_DIV_LO:    (R_T_DIV_HI, None),
    R_T_REARM_LO:  (R_T_REARM_HI, None),
    R_T_CLEAR_LO:  (R_T_CLEAR_HI, None),
}

_CONTADORES = {
    R_CNT_TOTAL: 'total', R_CNT_ACCEPTED: 'accepted', R_CNT_REJ_AMP: 'rej_amp',
    R_CNT_REJ_PSD: 'rej_psd', R_CNT_PILEUP: 'pileup', R_CNT_DROPPED: 'dropped',
    R_CNT_CROSS: 'total', R_CNT_OPEN: 'total', R_CNT_WIN: 'total',
    R_CNT_TRIG: 'total',
}


_MED_DE_FORMA = (R_TRAP_MED, R_FORMA1_MED, R_FORMA2_MED, R_FORMA3_MED)
_UMBR_DE_FORMA = (R_TRAP_UMBR, R_FORMA1_UMBR, R_FORMA2_UMBR, R_FORMA3_UMBR)


class FakeMCA(MCA):
    """Un MCA2 que no existe: fotopico gaussiano que crece con el tiempo vivo.

    Respeta la ventana de aceptación `amp_min`/`amp_max` (sobre el pico crudo
    de 14 b, o la integral con amp_src, como el RTL) y el zoom del eje 1D, así
    que moverlos desde la GUI recorta y corre el pico de verdad. `centro` y
    `sigma` están en canales del eje 1D a fondo de escala. Las ranuras no se
    modelan: no hay pérdidas ni solapes, y todo el tiempo ocupado cae en
    `t_ocup[1]`.

    Con `trap=True` tiene los registros del banco de trapecios como el RTL
    (`N_FORMAS`, `umbr_ok` y el ok de cada forma, de sólo lectura), para que la
    validación y los avisos se puedan probar; el espectro no cambia. Sin el
    trapecio 0x134 lee cero, como un bitstream sin banco.

    Sólo redefine el acceso: `r32`, `w32` y `_leer_bloque` (las aperturas del
    histograma). `MCA.__init__` los entrega a libmca como backend de
    callbacks, así que configure(), counters() y el resto son el código de C,
    corriendo contra este modelo. Necesita libmca compilada (`make -C libmca`).
    """

    impl = 'fake'
    N_ACC = 4
    N_FORMAS = 4

    def __init__(self, h_aw=14, h2_aw=7, psd_aw=6,
                 rate_hz=1000.0, centro=8000.0, sigma=45.0, semilla=0,
                 trap=False):
        caps = CAP_HIST_H | CAP_HIST_H_PSD | (CAP_TRAP if trap else 0)
        super().__init__(None, -1, caps, h_aw, h2_aw, psd_aw)
        self._reg = dict(_DEFAULTS_RESET)
        self._sombra = {}
        self._rng = np.random.default_rng(semilla)
        self._rate = float(rate_hz)
        self._centro = float(centro)
        self._sigma = float(sigma)
        self._hist = np.zeros(1 << h_aw, dtype=np.uint32)
        self._m2d = np.zeros((1 << h2_aw, 1 << psd_aw), dtype=np.uint32)
        self._cnt = dict(total=0, accepted=0, rej_amp=0, rej_psd=0,
                         pileup=0, dropped=0)
        self._ultimo = dict(amp=0, psd=0, q_tot=0, q_tail=0)
        self._realtime = 0.0
        self._t_ref = None
        # Lo que entra por el lazo digital: una función que da la tasa de pulsos
        # (`FakeGenPulsos.tasa_en_lazo`), o None si el lazo está apagado y la
        # entrada es la fuente propia de `rate_hz`. Sin generador, None.
        self.fuente = None

    # ---------- simulación ----------

    def _avanzar(self):
        """Integra el tiempo transcurrido desde la última llamada."""
        if self._t_ref is None:
            return
        ahora = time.monotonic()
        dt, self._t_ref = ahora - self._t_ref, ahora
        if dt <= 0:
            return
        self._realtime += dt

        tasa = self.fuente() if self.fuente is not None else None
        n = int(self._rng.poisson((self._rate if tasa is None else tasa) * dt))
        if n == 0:
            return

        amp_min = self._reg[R_AMP_MIN] & 0xFFFF
        amp_max = self._reg[R_AMP_MAX] & 0xFFFF

        # La feature de amplitud, de 16 b alineada a la izquierda: el canal a
        # fondo de escala son sus h_aw bits altos.
        corr = AMP_W - self.h_aw
        canal = self._rng.normal(self._centro, self._sigma, n)
        # np.intp, NO np.int64: termina usándose como array de ÍNDICES
        # (bincount, np.add.at). En la Pitaya —armv7l, 32 bits— np.intp es
        # int32 y numpy rechaza indexar con int64 por casting "safe".
        amp = np.clip(canal * (1 << corr), 0, 0xFFFF).astype(np.intp)

        # Un puñado de ventanas con otro disparo adentro: se marcan y se
        # histogramean igual (en el MCA2 el corte lo hace el discriminador).
        self._cnt['pileup'] += int(self._rng.binomial(n, 0.01))
        self._cnt['total'] += n

        # La ventana NO compara la feature del eje: compara el pico crudo de 14 b
        # (mca_slot.sv:251; el eje lo lleva `<< 2`, mca_publish.sv:342), o la
        # integral con amp_src, que sí es la del eje. Igual que replica_mca2.
        comparada = amp if self._reg.get(R_AMP_SRC, 0) & 1 else amp >> (AMP_W - 14)
        dentro = (comparada >= amp_min) & (comparada <= amp_max)
        self._cnt['rej_amp'] += int((~dentro).sum())
        amp = amp[dentro]
        if amp.size == 0:
            return

        self._hist += np.bincount(self._canal(amp, R_ZOOM_1D, self.h_aw),
                                  minlength=self._hist.size).astype(np.uint32)
        self._cnt['accepted'] += int(amp.size)

        # Mapa 2D: dos poblaciones en el eje de forma, para que la FOM dé algo.
        n2 = self._m2d.shape[1]
        psd = np.where(self._rng.random(amp.size) < 0.5,
                       self._rng.normal(0.25 * n2, 0.05 * n2, amp.size),
                       self._rng.normal(0.65 * n2, 0.05 * n2, amp.size))
        psd = np.clip(psd, 0, n2 - 1).astype(np.intp)   # índice: intp, ver arriba
        fila = self._canal(amp, R_ZOOM_2DX, self.h2_aw)
        np.add.at(self._m2d, (fila, psd), 1)

        self._ultimo = {'amp': int(amp[-1]), 'psd': int(psd[-1]),
                        'q_tot': int(amp[-1]) * 8, 'q_tail': int(amp[-1])}

    def _canal(self, amp, off_zoom, aw):
        """El zoom del MCA2 sobre la feature de 16 b, vectorizado: la ventana
        [k*2^(16-z), (k+1)*2^(16-z)), saturando en los bordes."""
        z = min(self._reg.get(off_zoom, 0) & 0xF, max(0, AMP_W - aw))
        k = ((self._reg.get(off_zoom, 0) >> 8) & 0xFF) & ((1 << z) - 1)
        ancho = 1 << (AMP_W - z)
        rel = amp - k * ancho
        c = rel >> (AMP_W - z - aw)
        c = np.where(rel < 0, 0, np.where(rel >= ancho, (1 << aw) - 1, c))
        return c.astype(np.intp)

    @property
    def _livetime(self):
        # Una fracción de tiempo muerto proporcional a la tasa, para que
        # livetime y deadtime no sean números decorativos.
        return self._realtime * (1.0 - min(0.3, self._rate * 20e-6))

    @property
    def _muerto(self):
        return self._realtime - self._livetime

    # ---------- acceso ----------

    def w32(self, off, v):
        v = int(v) & 0xFFFFFFFF
        if off == R_CTRL:
            corriendo = bool(v & 1)
            if corriendo and self._t_ref is None:
                self._t_ref = time.monotonic()
            elif not corriendo and self._t_ref is not None:
                self._avanzar()
                self._t_ref = None
            if v & (1 << 1):                       # clear autolimpiante
                self._hist[:] = 0
                self._m2d[:] = 0
                for k in self._cnt:
                    self._cnt[k] = 0
                self._realtime = 0.0
                v &= ~(1 << 1)
        if off == R_AMP_SRC:
            # Como el RTL: escribir amp_src mueve los selectores de amplitud.
            f = 1 if v & 1 else 0
            sel = self._reg.get(R_HIST_SEL, 0x200)
            self._reg[R_HIST_SEL] = (sel & ~0xFF) | (f << 4) | f
        self._reg[off] = v

    def r32(self, off):
        self._avanzar()
        if off == R_MAGIC:
            return MAGIC
        if off == R_CAPS:
            return self.caps
        if off == R_WIDTHS:
            return (self.psd_aw << 16) | (self.h2_aw << 8) | self.h_aw
        if off == R_N_ACC_MAX:
            return self.N_ACC
        if self.caps & CAP_TRAP:
            if off == R_N_FORMAS:
                return self._estado_banco()
            if off in _MED_DE_FORMA:
                return (self._reg[off] & 0x7FFFFFFF) | (self._forma_ok(off) << 31)
        elif off == R_N_FORMAS:
            return 0
        if off == R_STATUS:
            return 1 << 5                          # puede_abrir, nada ocupado
        if off == R_BASELINE_NOW:
            return 0
        if off == R_PUB_STATE:
            return ((self._cnt['total'] & 0xFFFF) << 16) | (1 << 8)
        if off in _CONTADORES:
            return self._cnt[_CONTADORES[off]] & 0xFFFFFFFF

        # t_ocup: lo libre en j=0, lo ocupado en j=1.
        if R_T_OCUP <= off < R_T_OCUP + 8 * (self.N_ACC + 1) and off % 8 == 0:
            j = (off - R_T_OCUP) // 8
            seg = self._livetime if j == 0 else self._muerto if j == 1 else 0.0
            return self._reloj(off + 4, seg)
        if off in _RELOJES:
            hi_off, attr = _RELOJES[off]
            return self._reloj(hi_off, getattr(self, attr) if attr else 0.0)
        if off in self._sombra:
            return self._sombra[off]

        ult = {R_LAST_AMP: 'amp', R_LAST_PSD: 'psd',
               R_LAST_QTOT: 'q_tot', R_LAST_QTAIL: 'q_tail'}
        if off in ult:
            return self._ultimo[ult[off]] & 0xFFFFFFFF

        return self._reg.get(off, 0)

    def _estado_banco(self):
        # {umbr_ok, N_FORMAS, n_formas}: los umbrales de las formas en uso.
        gate = self._reg[R_GATE_LEN] >> 16
        nf = self._reg[R_N_FORMAS] & 7
        nf = min(nf or 1, self.N_FORMAS)
        umbr_ok = all((self._reg.get(_UMBR_DE_FORMA[f], 0) >> 16) <= gate
                      for f in range(nf))
        return (int(umbr_ok) << 31) | (self.N_FORMAS << 8) | (self._reg[R_N_FORMAS] & 7)

    def _forma_ok(self, off_med):
        # trap_ok de mca_top.sv: off + TRAP_LAT + 2^lw <= gate_long.
        v = self._reg[off_med]
        fin = (v & 0xFFFF) + TRAP_LAT + (1 << ((v >> 16) & 7))
        return int(fin <= (self._reg[R_GATE_LEN] >> 16))

    def _reloj(self, hi_off, seg):
        ciclos = int(seg * FS_HZ)
        self._sombra[hi_off] = (ciclos >> 32) & 0xFFFFFFFF   # leer LO congela HI
        return ciclos & 0xFFFFFFFF

    def _leer_bloque(self, off, n):
        """La lectura en bloque que pide libmca: las dos aperturas salen del
        histograma simulado, de una vez; el resto, registro por registro."""
        self._avanzar()
        if off == APERTURE_H:
            return self._hist[:n]
        if off == APERTURE_2D:
            return self._m2d.ravel()[:n]
        return [self.r32(off + 4 * i) for i in range(n)]

    def close(self):
        self._t_ref = None
        super().close()


# =============================================================================
#
# Mismo criterio que `FakeMCA`: que la GUI se pueda desarrollar y probar sin
# placa. No simulan el RTL —no hay FSM de captura ni trigger real—, simulan lo
# que el CLIENTE ve: registros que retienen lo escrito y formas de onda con
# pulsos donde el umbral dice que los hay.
#
# La diferencia con FakeMCA importa y conviene tenerla presente: FakeMCA
# reproduce los valores de reset del RTL y su aritmética de histograma, así que
# un desacuerdo contra la placa apunta al hardware. Esto de acá es más flojo —
# las formas son gaussianas sintéticas, no pulsos medidos— así que sirve para
# ejercitar controles y dibujo, no para validar el camino de datos.

_DEFAULTS_OSC = {            # los del RTL, modulos/osc/rtl/osc_cfg.sv:302-319
    0x008: 100,   0x00C: 100,        # tresh ch0/ch1
    0x010: 0,     0x110: 0,          # dly
    0x014: 1,     0x114: 1,          # dec
    0x020: 50,    0x024: 50,         # hyst
    0x028: 0,                        # avg_en
    0x090: 62500,                    # deb_len
    0x098: 0,                        # filt_byp
    0x200: 0,     0x204: 0x8000,     # calib ch0
    0x208: 0,     0x20C: 0x8000,     # calib ch1
}


class FakeOsc(Osciloscope):
    """Un osciloscopio que no existe: pulsos gaussianos sobre ruido.

    Devuelve trazas cuya altura y tasa se parecen a las del `FakeMCA` que corre
    al lado, para que las dos pestañas cuenten la misma historia: si el espectro
    simulado tiene el pico en 8000 cuentas, las formas simuladas también.

    La lógica de los registros es la de libmca, que llega acá por el backend de
    callbacks. La profundidad la publica como un bitstream: en el mapa canónico.
    """

    def __init__(self, n_buf=16384, rate_hz=1000.0, altura_cnt=8000.0,
                 ancho_muestras=40.0, ruido_cnt=60.0, semilla=0):
        rsz = int(n_buf).bit_length() - 1
        if 1 << rsz != int(n_buf):
            raise ValueError(f'n_buf={n_buf}: el anillo es una potencia de 2')
        super().__init__(None, -1)
        self._reg = dict(_DEFAULTS_OSC)
        self._reg[R_CANON_MAGIC] = MAGIC_OSC
        self._reg[R_CANON_CAPS] = (rsz << 16) | (14 << 8) | 2
        self._rng = np.random.default_rng(semilla)
        self._n = int(n_buf)
        self._rate = float(rate_hz)
        self._altura = float(altura_cnt)
        self._ancho = float(ancho_muestras)
        self._ruido = float(ruido_cnt)
        self._we_cnt = 0
        self._t0 = time.monotonic()

    # ---------- registros ----------

    def r32(self, off):
        # Los punteros de escritura y el contador de eventos avanzan solos: es
        # lo que hace que la curva de tasa de la GUI tenga algo que dibujar.
        if off in (0x018, 0x118, 0x01C, 0x11C):
            return int((time.monotonic() - self._t0) * 1e6) % self._n
        if off in (0x02C, 0x12C):
            return int((time.monotonic() - self._t0) * self._rate)
        if off == 0x000:
            return 1
        return self._reg.get(off, 0)

    def w32(self, off, v):
        self._reg[off] = int(v) & 0xFFFFFFFF

    # ---------- formas ----------

    def capturar(self, pre=0, post=1024, n_ch=2):
        """Una ventana por canal, en VOLTS, como la devolvería la placa.

        El trigger queda en la muestra `pre`, igual que en `capture_window_np`:
        la ventana es [ref-pre, ref+post-1] y el cliente dibuja con t=0 ahí.
        """
        n = int(pre) + int(post)
        dec = max(1, self._reg.get(0x014, 1))
        # La tasa de eventos en la ventana depende de la decimación: con dec
        # alto, la misma ventana en muestras cubre más tiempo real y entran más
        # pulsos. Es el efecto que hace que subir la decimación "apile".
        dur_s = n * dec / FS_HZ
        n_ev = self._rng.poisson(max(0.0, self._rate * dur_s))

        t = np.arange(n, dtype=np.float32)
        salida = np.zeros((n_ch, n), dtype=np.float32)
        for c in range(n_ch):
            y = self._rng.normal(0.0, self._ruido, n).astype(np.float32)
            # El pulso del trigger, siempre en `pre`; los demás, al azar.
            centros = [float(pre)]
            if n_ev:
                centros += list(self._rng.uniform(0, n, int(n_ev)))
            for c0 in centros:
                alt = self._rng.normal(self._altura, self._altura * 0.02)
                y += (alt * np.exp(-0.5 * ((t - c0) / self._ancho) ** 2)
                      ).astype(np.float32)
            salida[c] = y / ADC_CNT_PER_V
        self._we_cnt += 1
        return salida


class FakeMultiTrigger(MultiTrigger):
    """Registros del multitrigger que retienen lo escrito, y un snapshot fijo. La
    lógica es la de libmca, que llega acá por el backend de callbacks.

    Con `region` (un `FakeMtRegion`) lee y escribe los registros de esa región, como
    en la placa, donde las dos fachadas son la misma región: lo que arma el disparo
    del MCA se ve en las máscaras, y FLAGS sale del scope. Sola, retiene lo suyo."""

    _DEFAULTS = {R_SHIELD_CFG: 0, R_SHIELD_RUN: 0, R_FLAGS: 0,
                 R_OR_MASK_CH0: 0xFFFFFFFF, R_OR_MASK_CH1: 0xFFFFFFFF}

    def __init__(self, region=None):
        super().__init__(None, -1)
        self._reg = dict(self._DEFAULTS)
        self._region = region

    def r32(self, off):
        if off == R_TRIG_SNAP:           # snapshot: sw + flanco positivo ch0
            return 0b11
        if self._region is not None:
            return self._region.r32(off)
        return self._reg.get(off, 0)

    def w32(self, off, v):
        if self._region is not None:
            self._region.w32(off, v)
        else:
            self._reg[off] = int(v) & 0xFFFFFFFF


class FakeMtRegion(MtRegion):
    """La región propia del multitrigger, simulada: registros que retienen lo
    escrito, con el disparo por pendiente presente.

    `we_keep` vive en el slot 1 (el scope), así que FLAGS lo toma del
    `FakeOsc` que se le pase: es lo que hace que `multitrigger_armar_mca`
    compruebe en el simulador lo mismo que en la placa.
    """

    def __init__(self, osc=None):
        super().__init__(None, -1)
        self._reg = {0x000: MTRG_MAGIC,
                     R3_CAPS: CAPS_HAS_PZ | CAPS_HAS_SLOPE | (2 << 12) | 2}
        self._osc = osc

    def r32(self, off):
        if off == R3_FLAGS:
            arm = getattr(self._osc, '_reg', {}).get(0x000, 0)
            # we_keep es el bit 3 de cada byte de 0x000 del scope.
            return sum(1 << (4 + c) for c in range(2) if (arm >> (8 * c + 3)) & 1)
        return self._reg.get(off, 0)

    def w32(self, off, v):
        self._reg[off] = int(v) & 0xFFFFFFFF


class FakeGenPulsos:
    """El generador de pulsos (`gen_pulsos`, slot 2) y el `digital_loop` de HK,
    simulados. La lógica es la de libmca: `handle()` devuelve un `GenPulsos` abierto
    sobre estos registros por el backend de callbacks.

    Los registros siguen a `gen_pulsos.sv` como el modelo de
    `API/tests/test_libmca_generadores.py`: el ancho de cada campo, BASE y la tabla
    releídos con el signo extendido, GEN_CNT, ESTADO y MAGIC de sólo lectura, y el
    estado que se reinicia en el flanco de `en`. Lo que cambia es el tiempo: acá
    GEN_CNT avanza con el reloj de la PC, a la tasa configurada, hasta N.

    `tasa_en_lazo()` es lo que el `FakeMCA` ve por la entrada (su atributo
    `fuente`): con el lazo prendido, la tasa del generador mientras genera y 0 si
    está parado, porque el ADC queda desconectado; con el lazo apagado, None, y el
    MCA ve su fuente de siempre. Sólo la tasa: el espectro falso no sigue a la tabla
    de amplitudes.
    """

    def __init__(self):
        from API import generadores as G
        self._G = G
        self.ANCHO = {G.R_CTRL: 0x1F, G.R_DT_MIN: 0xFFFF, G.R_DECAE: 0xFFFF,
                      G.R_SUBIDA: 0x7, G.R_AMP_N: 0x3FF, G.R_RUIDO: 0x10F}
        self.reg = {G.R_CTRL: 0, G.R_PERIODO: 1000, G.R_UMBRAL: 0, G.R_DT_MIN: 2,
                    G.R_N: 0, G.R_SEMILLA: 0, G.R_DECAE: G.DECAE_RESET,
                    G.R_SUBIDA: 0, G.R_AMP_N: 0, G.R_BASE: 0, G.R_RUIDO: 0}
        self.tabla = [0] * G.N_TABLA
        self.hk = 0
        self._t0 = None             # el arranque, en time.monotonic()
        self._tasa = 0.0            # la de la configuración, fijada al arrancar
        self._cnt = 0               # GEN_CNT congelado al parar

    @staticmethod
    def _s14(v):
        v &= 0x3FFF
        return v - 0x4000 if v & 0x2000 else v

    def _en(self):
        return bool(self.reg[self._G.R_CTRL] & self._G.CTRL_EN)

    def _gen_cnt(self):
        if not self._en() or self._t0 is None:
            return self._cnt
        n = int(self._tasa * (time.monotonic() - self._t0))
        tope = self.reg[self._G.R_N]
        return min(n, tope) if tope else n

    def _hecho(self):
        tope = self.reg[self._G.R_N]
        return tope != 0 and self._gen_cnt() >= tope

    def tasa_en_lazo(self):
        if not self.hk & 1:
            return None
        return self._tasa if self._en() and not self._hecho() else 0.0

    # ---------- los registros ----------

    def r32(self, off):
        G = self._G
        if off >= G.R_TABLA:
            return self._s14(self.tabla[(off - G.R_TABLA) >> 2]) & 0xFFFFFFFF
        if off == G.R_GEN_CNT:
            return self._gen_cnt() & 0xFFFFFFFF
        if off == G.R_ESTADO:
            hecho = self._hecho()
            return int(self._en() and not hecho) | (int(hecho) << 1)
        if off == G.R_MAGIC:
            return G.MAGIC
        if off == G.R_BASE:
            return self._s14(self.reg[G.R_BASE]) & 0xFFFFFFFF
        return self.reg.get(off, 0)

    def w32(self, off, v):
        G = self._G
        v = int(v) & 0xFFFFFFFF
        if off >= G.R_TABLA:
            self.tabla[(off - G.R_TABLA) >> 2] = v & 0x3FFF
            return
        if off not in self.reg:
            return                      # GEN_CNT, ESTADO, MAGIC: sólo lectura
        v &= self.ANCHO.get(off, 0xFFFFFFFF)
        if off == G.R_BASE:
            v &= 0x3FFF
        if off == G.R_CTRL:
            antes = self._en()
            ahora = bool(v & G.CTRL_EN)
            if ahora and not antes:                 # el arranque
                r = self.reg
                self._tasa = G.tasa(aleatorio=bool(v & G.CTRL_ALEATORIO),
                                    periodo=r[G.R_PERIODO], umbral=r[G.R_UMBRAL],
                                    dt_min=r[G.R_DT_MIN])
                self._t0, self._cnt = time.monotonic(), 0
            elif antes and not ahora:               # GEN_CNT queda
                self._cnt = self._gen_cnt()
                self._t0 = None
        self.reg[off] = v

    def hk_r32(self, off):
        return self.hk if off == self._G.HK_LAZO else 0

    def hk_w32(self, off, v):
        if off == self._G.HK_LAZO:
            self.hk = int(v) & 0x3

    def handle(self):
        from API._libmca import Bus
        G = self._G
        bus = Bus.callbacks(self.r32, self.w32, size=G.SIZE)
        hk = Bus.callbacks(self.hk_r32, self.hk_w32, size=G.HK_SIZE)
        return G.GenPulsos.sobre(bus, hk)
