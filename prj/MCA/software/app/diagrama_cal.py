#!/usr/bin/env python3
"""La calibración del canal en una franja: el índice de la pestaña «Calibration» y lo
que se midió.

De izquierda a derecha, el camino de la señal y lo que se hace con él:

    referencia ──x[n]──> canal ──y[n]──> modelo (FIR + polos lentos) ──caída──> base del MCA

- la referencia: el generador por OUT1 (x[n] se captura con el lazo digital) o una
  cuadrada de afuera en IN1 (x[n] sale de la propia captura);
- el canal: el cable, la carga y el front-end de IN1, con el offset y el ruido medidos;
- el modelo: la ganancia de corto plazo y la caída lenta Σd/Σc;
- la base del MCA: fija (b0) o dinámica, b0 + κ·caída·(λ̂/f_s)·⟨A⟩·τ, con Δb y la λ̂
  con que se calculó.

Los colores son por función, como en los panoramas: amarillo la fuente (como los
disparos), azul lo analógico (el preprocesamiento), verde el ajuste y naranja lo que
se escribe en el MCA.
"""

import time

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen

from app.franja import (AMARILLO, AZUL, GRIS, GRIS_CORTE, GRIS_LEYENDA, NARANJA,
                        ROJO_PERDIDA, VERDE, Franja, _tasa)

# (clave, título, qué hace, color), en el orden de la señal.
ETAPAS = (
    ('referencia', 'Reference', 'generator via OUT1\nor external square', AMARILLO),
    ('canal', 'Channel', 'cable, load, IN1\nfront-end + ADC', AZUL),
    ('modelo', 'Channel model', 'FIR + slow poles\nslow drop Σd/Σc', VERDE),
    ('base', 'MCA base', 'fixed b0, or dynamic:\nb0 + κ·drop·λ·⟨A⟩·τ', NARANJA),
)
COLOR = {clave: color for clave, _t, _d, color in ETAPAS}

AYUDA = {
    'referencia': 'What the channel is compared against. The generator: the same '
                  'stimulus captured with the digital loopback (x) and without it '
                  '(y), at the same instants. An external square: the ideal step is '
                  'built from the capture itself, so only the slow drop of IN1 comes '
                  'out.',
    'canal': 'Everything analog between the reference and the ADC: the DAC output, '
             'the cable, the 50 Ω load and the IN1 front-end. Its offset is the base '
             'the MCA has to subtract at zero rate.',
    'modelo': 'y = b + FIR * x + Σ d_i · lowpass_i(x): the FIR is the fast response '
              '(344 ns), the slow poles (3.2, 12.8 and 51 µs) the drop that piles up '
              'with the rate and moves the base.',
    'base': 'The fixed base of the MCA (register 0x01C). With the dynamic base, the '
            'server moves it every 250 ms by the mean tail the slow poles leave: '
            'κ·drop·(λ/f_s)·⟨A⟩·τ.',
}


def pct(x):
    return '—' if x is None else f'{100 * float(x):+.2f} %'


class DiagramaCal(Franja):
    """Una fila: los cuatro bloques y el MCA, con el estado debajo."""

    AYUDA = AYUDA

    LEYENDA = (
        (('The measurements use the generator, the BRAM and the trigger, and restore '
          'what they touch. ', GRIS_LEYENDA),
         ('red', ROJO_PERDIDA),
         (': the channel is not the calibration one (no cable, HV jumper).',
          GRIS_LEYENDA)),
    )

    def __init__(self, parent=None):
        self._res = None                  # el último canal.medir (o el cargado)
        self._base = None                 # el base_dinamica del status
        self._referencia = 'generador'
        super().__init__(parent)

    # ---------- lo que la pestaña le dice ----------

    def actualizar_resultado(self, res):
        self._res = dict(res) if res else None
        if res and res.get('referencia'):
            self._referencia = res['referencia']
        self.update()

    def actualizar_base(self, info):
        self._base = dict(info) if info else None
        self.update()

    def set_referencia(self, ref):
        self._referencia = ref
        self.update()

    def limpiar(self):
        self._res = self._base = None
        self.update()

    # ---------- medidas ----------

    def _medidas(self):
        f_tit, f_chico = self._fuentes()
        fmt, fmc = QFontMetrics(f_tit), QFontMetrics(f_chico)
        lc = fmc.height()
        y0 = 6.0
        h = fmt.height() + 2 * lc + 10.0
        return f_tit, f_chico, fmc, lc, y0, h

    def _alto(self):
        _ft, _fc, _fm, lc, y0, h = self._medidas()
        return int(y0 + h + 4 + 2 * lc + 6 + lc + 6)

    def _geometria(self):
        f_tit, f_chico, fmc, lc, y0, h = self._medidas()
        x0 = 6.0
        ancho_s = max(fmc.horizontalAdvance(t) for t in ('to the MCA', 'base − x[n]')) + 16
        hueco = max(fmc.horizontalAdvance(t) for t in ('x[n]', 'y[n]', 'drop')) + 22.0
        x_s = self.width() - 6.0 - ancho_s
        ancho = max(60.0, (x_s - hueco - x0 - 3 * hueco) / 4)
        self._cajas = {clave: QRectF(x0 + i * (ancho + hueco), y0, ancho, h)
                       for i, (clave, *_r) in enumerate(ETAPAS)}
        mca = QRectF(x_s, y0 + 4, ancho_s, h - 8)
        return f_tit, f_chico, fmc, lc, y0, h, mca

    # ---------- lo que va debajo de cada bloque ----------

    def lineas(self):
        """{etapa: [(texto, color)]}: el estado, sin Qt de por medio (las pruebas)."""
        res = self._res or {}
        base = self._base or {}
        out = {}
        ref = 'external square on IN1' if self._referencia == 'externa' \
            else 'generator via OUT1'
        out['referencia'] = [(ref, None)]
        if res.get('t_medida'):
            out['referencia'].append(
                (time.strftime('measured %H:%M:%S', time.localtime(res['t_medida'])),
                 GRIS_CORTE))
        if 'offset' in res:
            out['canal'] = [(f"offset {res['offset']:+.1f}, noise {res['ruido']:.2f}",
                             GRIS_CORTE)]
            bw = res.get('bw_3db_mhz')
            out['canal'].append(
                (f"gain {res['ganancia']:.3f}, −3 dB "
                 + ('> Nyquist' if bw is None else f'{bw:.0f} MHz'),
                 ROJO_PERDIDA if res.get('problema') else GRIS_CORTE))
        elif res.get('lento'):
            out['canal'] = [(f"step {res['lento'].get('escalon_cuentas', 0):.0f} counts"
                             if res.get('referencia') == 'externa'
                             else f"gain {res['lento']['ganancia']:.3f}", GRIS_CORTE)]
        if res:
            fuente = {'lenta': 'slow fit, decimated', 'rapida': 'fast fit only',
                      'externa': 'IN1 alone (external)'}.get(res.get('fuente_caida'), '')
            out['modelo'] = [(f"slow drop {pct(res.get('caida_lenta_usar'))}", None),
                             (fuente, GRIS_CORTE)]
        if base.get('on'):
            lam = base.get('lam_hz')
            out['base'] = [
                (f"Δb {base.get('delta_b', 0.0):+.1f} ADU"
                 + (f" at {_tasa(lam)}" if lam else ''), None),
                (f"base {base.get('base')} (b0 {base.get('b0')})",
                 ROJO_PERDIDA if base.get('error') else GRIS_CORTE)]
        elif base:
            out['base'] = [('fixed: dynamic off', GRIS_CORTE)]
        return out

    # ---------- el dibujo ----------

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        texto = self._texto()
        f_tit, f_chico, fmc, lc, y0, h, mca = self._geometria()
        c = self._cajas
        ym = y0 + h / 2

        def rotulo(x, y_base, s, color=texto, centro=True, ancho_max=None):
            self._rotulo(p, f_chico, x, y_base, s, color, centro, ancho_max)

        claves = [e[0] for e in ETAPAS]
        rotulos = {('referencia', 'canal'): 'x[n]', ('canal', 'modelo'): 'y[n]',
                   ('modelo', 'base'): 'drop'}
        for a, b in zip(claves, claves[1:]):
            self._flecha(p, c[a].right(), ym, c[b].left(), ym, texto)
            rotulo((c[a].right() + c[b].left()) / 2, ym - 5, rotulos[(a, b)])
        self._flecha(p, c['base'].right(), ym, mca.left(), ym, texto)

        p.setPen(QPen(QColor(90, 90, 90), 1.0))
        p.setBrush(GRIS)
        p.drawRoundedRect(mca, 3, 3)
        p.setBrush(Qt.NoBrush)
        y = mca.center().y() - lc + fmc.ascent()
        for k, s in enumerate(('to the MCA', 'base − x[n]')):
            rotulo(mca.center().x(), y + k * lc, s, Qt.black, ancho_max=mca.width() - 4)

        for clave, titulo, desc, color in ETAPAS:
            self._bloque(p, clave, titulo, desc, color, c[clave], f_tit, f_chico)

        yb = y0 + h + 4 + fmc.ascent()
        debajo = self.lineas()
        for i, clave in enumerate(claves):
            r = c[clave]
            sig = c[claves[i + 1]].left() if i + 1 < len(claves) else mca.right()
            for k, (s, color) in enumerate(debajo.get(clave, [])[:2]):
                rotulo(r.left() + 2, yb + k * lc, s, texto if color is None else color,
                       centro=False, ancho_max=sig - r.left() - 6)

        self._leyenda(p, f_chico, 6, yb + 2 * lc + 6, self.width() - 12, self.LEYENDA)
