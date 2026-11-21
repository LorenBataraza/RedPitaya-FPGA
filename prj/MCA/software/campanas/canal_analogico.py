"""El canal analógico OUT1 → coaxial → IN1 en las campañas: lo que la parte analógica (el
DAC, el cable, el front-end y el ADC) le hace a la señal de `gen_pulsos`.

Es el modo analógico de las campañas (`run_meritos_pulsos.py --modo analogico`,
`run_fidelidad_osc.py medir --modo analogico`): las mismas pruebas con el lazo digital
apagado, así que el generador sale por OUT1 y vuelve por IN1.

**La medición y el ajuste viven en `API/canal.py`** (los usa también la pestaña
«Calibration» de la app, y el servidor no importa `campanas/`): acá se reexportan con los
mismos nombres (`CA.ajustar_fir`, `CA.caracterizar`, `CA.residuo`, …), así que las
campañas no cambian. Ahí está también cómo se mide y qué devuelve `caracterizar`.

Lo propio de las campañas:

`CanalSimulado` es un canal de juguete (ganancia, offset, retardo, dos polos, ruido
gaussiano y diafonía) para recorrer las campañas en la PC sin placa: no es un modelo de
la placa, y sus números no se comparan con nada.

`CanalMedido` es el canal de la placa: el FIR y los polos lentos ajustados a un par de
capturas de la BRAM (`canal.npz` de `run_fidelidad_osc.py`), con el ruido del piso
medido. Con él, la placa simulada reproduce lo que el canal le hace al MCA (el
corrimiento de la línea con la tasa, `sim_corrimiento_canal.py`); sin los polos lentos
(`lentos=()`) es el mismo canal sin la caída lenta.
"""
import os
import sys

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from API.canal import *                     # noqa: E402,F401,F403  (lo genérico)
from API.canal import (AMP_MAX, AMP_MIN, LENTOS, ajustar_fir,  # noqa: E402
                       pasabajos, piso, predecir)


# =============================================================================
# El canal de juguete, para la PC
# =============================================================================

class CanalSimulado:
    """y = sat(round(offset + ganancia · (h * x)[n − lat] + ruido)), con h dos polos
    iguales (`polo`: el coeficiente de cada uno), y la diafonía en IN2. El ruido sale de
    una semilla fija y del contenido de la traza: la misma traza da la misma y, como el
    generador (la placa simulada se compara entre corridas de un punto)."""

    DEFECTO = dict(ganancia=0.97, offset=-12.0, lat=9, polo=0.45, ruido=1.3,
                   diafonia=0.003, offset2=-20.0, ruido2=1.3)

    def __init__(self, semilla=1, **kw):
        malos = set(kw) - set(self.DEFECTO)
        if malos:
            raise ValueError(f'canal simulado: {sorted(malos)} no existen '
                             f'({sorted(self.DEFECTO)})')
        self.p = dict(self.DEFECTO, **kw)
        self.semilla = int(semilla)
        a = float(self.p['polo'])
        h1 = (1.0 - a) * a ** np.arange(64)
        self.h = np.convolve(h1, h1)[:96]
        self.h /= self.h.sum()

    @classmethod
    def desde_texto(cls, txt, semilla=1):
        """'ganancia=0.97,lat=9' -> CanalSimulado."""
        kw = {}
        for par in (txt or '').split(','):
            if par.strip():
                k, v = par.split('=')
                kw[k.strip()] = float(v)
        if 'lat' in kw:
            kw['lat'] = int(kw['lat'])
        return cls(semilla=semilla, **kw)

    def _rng(self, x, canal):
        h = int(np.asarray(x, np.int64)[::97].sum()) & 0x7FFF_FFFF
        return np.random.default_rng([self.semilla, canal, int(np.asarray(x).size), h])

    def aplicar(self, x, canal=0):
        """IN1 (canal 0) o IN2 (canal 1) para la salida x del generador."""
        x = np.asarray(x, float)
        p = self.p
        v = np.convolve(x, self.h)[:x.size]
        lat = int(p['lat'])
        v = np.concatenate([np.zeros(lat), v[:x.size - lat]]) if lat else v
        if canal == 0:
            y = p['offset'] + p['ganancia'] * v + p['ruido'] * self._rng(x, 0).standard_normal(x.size)
        else:
            y = (p['offset2'] + p['diafonia'] * p['ganancia'] * v
                 + p['ruido2'] * self._rng(x, 1).standard_normal(x.size))
        return np.clip(np.round(y), AMP_MIN, AMP_MAX).astype(np.int64)

    def describir(self):
        return dict(self.p, semilla=self.semilla)


# =============================================================================
# El canal medido, para la PC
# =============================================================================

class CanalMedido:
    """y = sat(round(predecir(x) + ruido)): el FIR y los polos lentos ajustados a las
    capturas de la placa, y el ruido blanco gaussiano con el σ del piso medido. IN2 es
    su propio ajuste (la diafonía) con el piso de IN2. El ruido sale de una semilla fija
    y del contenido de la traza, como en `CanalSimulado`."""

    def __init__(self, in1, in2, ruido, ruido2, semilla=1, origen=''):
        self.in1, self.in2 = in1, in2
        self.ruido, self.ruido2 = float(ruido), float(ruido2)
        self.semilla = int(semilla)
        self.origen = str(origen)

    @classmethod
    def desde_capturas(cls, ruta, lentos=LENTOS, semilla=1):
        """Desde el `canal.npz` de `run_fidelidad_osc.py` (x, y0, y1, piso0, piso1).
        `lentos=()` ajusta el FIR solo: el mismo canal sin la caída lenta."""
        z = np.load(ruta)
        return cls(ajustar_fir(z['x'], z['y0'], lentos=lentos),
                   ajustar_fir(z['x'], z['y1'], lentos=lentos),
                   piso(z['piso0'])['sigma'], piso(z['piso1'])['sigma'],
                   semilla=semilla, origen=str(ruta))

    def _rng(self, x, canal):
        h = int(np.asarray(x, np.int64)[::97].sum()) & 0x7FFF_FFFF
        return np.random.default_rng([self.semilla, canal, int(np.asarray(x).size), h])

    def lenta(self, x, canal=0):
        """La parte de y que ponen los polos lentos: Σ d_i (p_i * x)."""
        f = self.in2 if canal else self.in1
        out = np.zeros(np.asarray(x).size)
        for di, tau in zip(f['d'], f['lentos']):
            out += float(di) * pasabajos(x, tau)
        return out

    def aplicar(self, x, canal=0):
        """IN1 (canal 0) o IN2 (canal 1) para la salida x del generador."""
        x = np.asarray(x, float)
        f = self.in2 if canal else self.in1
        s = self.ruido2 if canal else self.ruido
        y = predecir(x, f['c'], f['b'], f['lags'], f['d'], f['lentos'])
        y = y + s * self._rng(x, canal).standard_normal(x.size)
        return np.clip(np.round(y), AMP_MIN, AMP_MAX).astype(np.int64)

    def describir(self):
        g = float(np.sum(self.in1['c']))
        return dict(modelo='medido', origen=self.origen, lentos=list(self.in1['lentos']),
                    d=[float(v) for v in self.in1['d']], ganancia=g,
                    caida_lenta=float(np.sum(self.in1['d'])) / g if g else 0.0,
                    offset=self.in1['b'], ruido=self.ruido, semilla=self.semilla)
