#!/usr/bin/env python3
"""El MCA por socket (`MCARemote`) y un MCA simulado (`FakeMCA`).

Los dos son `class MCA`: mismo handle, mismos métodos, misma geometría leída
del hardware. Eso es lo que hace que **toda la superficie `mca_*` de API/mca.py
funcione sin tocar una línea**, porque esas funciones acceden al hardware sólo
a través de `h.r32()`, `h.w32()` y los métodos del handle::

    from API.mca import mca_set_thr, mca_get_config, mca_read_histogram
    from API.mca_remote import MCARemote

    h = MCARemote.connect('10.73.28.27')
    mca_set_thr(h, 317)              # read-modify-write, 2 idas y vueltas
    cfg  = mca_get_config(h)         # 1 ida y vuelta (operación en bloque)
    hist = mca_read_histogram(h)     # 1, con payload binario de 64 KB

Es el mismo patrón con el que `RingSource` es drop-in de `BramSource`: la
interfaz la fija el consumidor, no el transporte.

`FakeMCA` no toca nada y simula un fotopico que crece: sirve para desarrollar
la GUI entera en la PC, como `FakeSource` para el pipeline del osciloscopio.
"""

import threading
import time

import numpy as np

from API.mca import (CAP_HIST_H, CAP_HIST_H_PSD, FS_HZ, MCA,
                     R_AMP_MAX, R_AMP_MIN, R_AMP_SRC, R_BASELINE,
                     R_BASELINE_NOW, R_BL_CTRL, R_CAPS, R_CNT_ACCEPTED,
                     R_CNT_DROPPED, R_CNT_PILEUP, R_CNT_REJ_AMP, R_CNT_REJ_PSD,
                     R_CNT_TOTAL, R_CTRL, R_DEADTIME_HI, R_DEADTIME_LO, R_DEC,
                     R_GATE_LEN, R_GATE_MODE, R_H2_SHIFT, R_H_SHIFT, R_HYST,
                     R_LAST_AMP, R_LAST_PSD, R_LAST_QTAIL, R_LAST_QTOT,
                     R_LIVETIME_HI, R_LIVETIME_LO, R_MAGIC, R_MAXLEN,
                     R_REALTIME_HI, R_REALTIME_LO, R_STATUS, R_TAIL_DLY,
                     R_THR, R_WIDTHS, MAGIC)
from API.mca_net import PORT_DEFAULT, Channel, RemoteError, array_desde
# Sólo la escala del ADC, para que el osciloscopio simulado devuelva volts con
# la MISMA constante que usa el real y no con una copia que puede divergir.
# `API/osciloscope.py` es importable en la PC (la librería `rp` se carga
# perezosamente), así que esto no ata este módulo a la placa.
from API.osciloscope import ADC_CNT_PER_V


# =============================================================================
# Handle remoto
# =============================================================================

class MCARemote(MCA):
    """`class MCA` cuyos accesos van por socket en vez de por /dev/mem.

    Se redefinen `r32`/`w32` (que es lo que hace andar el resto heredado) y,
    por eficiencia, las operaciones que si no costarían muchas idas y vueltas:

      spectrum/map2d   payload binario en una vuelta, en vez de 16384
      counters         12 registros en una
      configure        19 escrituras + la relectura de verificación, en una
      clear            el poll de clear_busy ocurre en la placa
      start/stop       atómicos bajo el lock del servidor: un read-modify-write
                       por red podría cruzarse con el hilo de exposición

    Se hereda intacto todo lo demás: identify, running, channel, last_event,
    acquire, acquire_chunks y los autoscale.
    """

    def __init__(self, canal, info):
        super().__init__(None, -1, info['caps'],
                         info['h_aw'], info['h2_aw'], info['psd_aw'])
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
        return cls(canal, obj['result'])

    # ---------- transporte ----------

    def _pedir(self, op, **args):
        # El lock es barato y evita que dos hilos entrelacen cabeceras en el
        # mismo socket, que desincronizaría el stream sin diagnóstico posible.
        with self._lock:
            return _pedir_en(self._canal, op, **args)

    def close(self):
        self._canal.close()

    # ---------- acceso, redefinido ----------

    def w32(self, off, v):
        self._pedir('w32', off=int(off), val=int(v) & 0xFFFFFFFF)

    def r32(self, off):
        return int(self._pedir('r32', off=int(off))[0]['result']['val'])

    # ---------- operaciones en bloque ----------

    def spectrum(self):
        obj, payload = self._pedir('read.spectrum')
        return array_desde(obj, payload)

    def map2d(self):
        obj, payload = self._pedir('read.map2d')
        return array_desde(obj, payload)

    def counters(self):
        return self._pedir('status')[0]['result']['counters']

    def configure(self, **kw):
        """Escribe el bloque entero. Los campos que no se pasen toman los
        valores por defecto de `MCA.configure`, que es quien los aplica del
        lado de la placa: así la semántica es exactamente la misma."""
        self._pedir('config.set', fields=kw)

    def clear(self, timeout_s=1.0):
        self._pedir('ctrl.clear', timeout_s=timeout_s)

    def start(self):
        self._pedir('ctrl.start')

    def stop(self):
        self._pedir('ctrl.stop')

    # ---------- extras que sólo tienen sentido por red ----------

    def status(self):
        """Contadores + running + tasas + estado de la exposición.

        Es lo que poléa la GUI: una sola vuelta con todo lo que va en pantalla
        salvo el espectro.
        """
        return self._pedir('status')[0]['result']

    def config(self):
        """Los 19 campos en una ida y vuelta.

        `mca_get_config(h)` da lo mismo pero son 19, una por campo: para el
        poleo de una GUI conviene ésta.
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
# Reproduce el mapa de registros, no una API paralela: `_CAMPOS` y sus
# read-modify-write, la geometría publicada en WIDTHS, el barrido de clear y
# el registro sombra de los relojes de 64 bits. Si algo anda contra FakeMCA y
# no contra la placa, la diferencia está en el hardware, no en el simulador.

_DEFAULTS_RESET = {          # los del RTL, mca_top.sv:246-256
    R_CTRL:      0,
    R_THR:       100,
    R_HYST:      50,
    R_BASELINE:  0,
    R_BL_CTRL:   6 << 4,     # bl_k=6, auto=0
    R_MAXLEN:    1024,
    R_TAIL_DLY:  4,
    R_AMP_MIN:   0,
    R_AMP_MAX:   0xFFFF,
    R_AMP_SRC:   0,
    R_H_SHIFT:   0,
    R_H2_SHIFT:  0,
    R_DEC:       1,
    R_GATE_MODE: 0,
    R_GATE_LEN:  (384 << 16) | 32,
}


class FakeMCA(MCA):
    """Un MCA que no existe: fotopico gaussiano que crece con el tiempo vivo.

    Respeta la ventana de aceptación `amp_min`/`amp_max`, así que moverla desde
    la GUI recorta el pico de verdad y `rej_amp` sube. Es lo que permite probar
    los controles sin placa.
    """

    def __init__(self, h_aw=14, h2_aw=7, psd_aw=6,
                 rate_hz=1000.0, centro=8000.0, sigma=45.0, semilla=0):
        super().__init__(None, -1, CAP_HIST_H | CAP_HIST_H_PSD,
                         h_aw, h2_aw, psd_aw)
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

        n = int(self._rng.poisson(self._rate * dt))
        if n == 0:
            return

        h_shift = (self._reg[R_H_SHIFT] >> 0) & 0x1F
        h2_shift = (self._reg[R_H2_SHIFT] >> 0) & 0x1F
        amp_min = self._reg[R_AMP_MIN] & 0xFFFF
        amp_max = self._reg[R_AMP_MAX] & 0xFFFF

        amp = self._rng.normal(self._centro, self._sigma, n)
        # np.intp, NO np.int64: `amp` termina usándose como array de ÍNDICES
        # (bincount, y la fila de np.add.at más abajo). En la Pitaya —armv7l, 32
        # bits— np.intp es int32, y numpy rechaza indexar con int64 por casting
        # "safe": "Cannot cast array data from dtype('int64') to dtype('int32')".
        # En la PC no se nota porque ahí intp ya es int64. Las amplitudes son
        # 0..0xFFFF, así que int32 sobra.
        amp = np.clip(amp, 0, 0xFFFF).astype(np.intp)

        # Apilamiento: un puñado de eventos se cierran por maxlen y no entran.
        n_pile = int(self._rng.binomial(n, 0.01))
        if n_pile:
            amp = amp[n_pile:]
        self._cnt['pileup'] += n_pile
        self._cnt['total'] += n

        dentro = (amp >= amp_min) & (amp <= amp_max)
        self._cnt['rej_amp'] += int((~dentro).sum())
        amp = amp[dentro]
        if amp.size == 0:
            return

        canal = np.clip(amp >> h_shift, 0, self._hist.size - 1)
        self._hist += np.bincount(canal, minlength=self._hist.size
                                  ).astype(np.uint32)
        self._cnt['accepted'] += int(amp.size)

        # Mapa 2D: dos poblaciones en el eje de forma, para que la FOM dé algo.
        n2 = self._m2d.shape[1]
        psd = np.where(self._rng.random(amp.size) < 0.5,
                       self._rng.normal(0.25 * n2, 0.05 * n2, amp.size),
                       self._rng.normal(0.65 * n2, 0.05 * n2, amp.size))
        psd = np.clip(psd, 0, n2 - 1).astype(np.intp)   # índice: intp, ver arriba
        fila = np.clip(amp >> max(h2_shift, 9), 0, self._m2d.shape[0] - 1)
        np.add.at(self._m2d, (fila, psd), 1)

        self._ultimo = {'amp': int(amp[-1]), 'psd': int(psd[-1]),
                        'q_tot': int(amp[-1]) * 8, 'q_tail': int(amp[-1])}

    @property
    def _livetime(self):
        # Una fracción de tiempo muerto proporcional a la tasa, para que
        # livetime y deadtime no sean números decorativos.
        return self._realtime * (1.0 - min(0.3, self._rate * 20e-6))

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
        self._reg[off] = v

    def r32(self, off):
        self._avanzar()
        if off == R_MAGIC:
            return MAGIC
        if off == R_CAPS:
            return self.caps
        if off == R_WIDTHS:
            return (self.psd_aw << 16) | (self.h2_aw << 8) | self.h_aw
        if off == R_STATUS:
            return 0
        if off == R_BASELINE_NOW:
            return 0

        cnt = {R_CNT_TOTAL: 'total', R_CNT_ACCEPTED: 'accepted',
               R_CNT_REJ_AMP: 'rej_amp', R_CNT_REJ_PSD: 'rej_psd',
               R_CNT_PILEUP: 'pileup', R_CNT_DROPPED: 'dropped'}
        if off in cnt:
            return self._cnt[cnt[off]] & 0xFFFFFFFF

        relojes = {R_REALTIME_LO: (R_REALTIME_HI, self._realtime),
                   R_LIVETIME_LO: (R_LIVETIME_HI, self._livetime),
                   R_DEADTIME_LO: (R_DEADTIME_HI,
                                   self._realtime - self._livetime)}
        if off in relojes:
            hi_off, seg = relojes[off]
            ciclos = int(seg * FS_HZ)
            self._sombra[hi_off] = (ciclos >> 32) & 0xFFFFFFFF   # leer LO congela HI
            return ciclos & 0xFFFFFFFF
        if off in (R_REALTIME_HI, R_LIVETIME_HI, R_DEADTIME_HI):
            return self._sombra.get(off, 0)

        ult = {R_LAST_AMP: 'amp', R_LAST_PSD: 'psd',
               R_LAST_QTOT: 'q_tot', R_LAST_QTAIL: 'q_tail'}
        if off in ult:
            return self._ultimo[ult[off]] & 0xFFFFFFFF

        return self._reg.get(off, 0)

    def spectrum(self):
        self._avanzar()
        return self._hist.copy()

    def map2d(self):
        self._avanzar()
        return self._m2d.copy()

    def close(self):
        self._t_ref = None


# =============================================================================
# Osciloscopio y multitrigger simulados
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


class FakeOsc:
    """Un osciloscopio que no existe: pulsos gaussianos sobre ruido.

    Devuelve trazas cuya altura y tasa se parecen a las del `FakeMCA` que corre
    al lado, para que las dos pestañas cuenten la misma historia: si el espectro
    simulado tiene el pico en 8000 cuentas, las formas simuladas también.
    """

    def __init__(self, n_buf=16384, rate_hz=1000.0, altura_cnt=8000.0,
                 ancho_muestras=40.0, ruido_cnt=60.0, semilla=0):
        self._reg = dict(_DEFAULTS_OSC)
        self._rng = np.random.default_rng(semilla)
        self.n_buf = int(n_buf)
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
            return int((time.monotonic() - self._t0) * 1e6) % self.n_buf
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

    def close(self):
        pass


class FakeMultiTrigger:
    """Registros del multitrigger que retienen lo escrito, y un snapshot fijo."""

    _DEFAULTS = {0x210: 0, 0x214: 0, 0x21C: 0,
                 0x240: 0xFFFFFFFF, 0x244: 0xFFFFFFFF}

    def __init__(self):
        self._reg = dict(self._DEFAULTS)

    def r32(self, off):
        if off == 0x218:                 # snapshot: sw + flanco positivo ch0
            return 0b11
        return self._reg.get(off, 0)

    def w32(self, off, v):
        self._reg[off] = int(v) & 0xFFFFFFFF

    def read_snapshot_raw(self):
        return self.r32(0x218)

    def get_flags(self):
        return self.r32(0x21C)

    def close(self):
        pass
