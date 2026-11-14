#!/usr/bin/env python3
"""El generador de pulsos en una franja: el índice de su pestaña y lo que está dando.

Los bloques siguen el panorama de `gen_pulsos`
(docs/gen_eventos/figuras/panorama_gen_pulsos.tex), con sus colores: amarillo los
disparos, verde la amplitud, azul la forma del pulso y naranja la salida. Es la
ecuación de izquierda a derecha:

    v(t) = sat14( B + Σ_k A_k h(t − t_k) + r(t) )

- en la flecha de los disparos, la tasa que da de verdad (después de cuantizar);
- bajo cada bloque, su estado: los pulsos generados, cómo se sortean las alturas,
  τ_d con la Mq del polo-cero, y el ruido o el DESBORDE de la forma (en rojo);
- a la derecha, a dónde va: al DAC, o con el lazo digital a la entrada del MCA, y
  entonces la tasa de entrada que mide el MCA (λ̂) contra la del generador.

`marcar` pone el punto sobre las etapas editadas y todavía sin aplicar: «Apply»
escribe la configuración entera y apaga el generador. La cuenta de λ̂ contra la
tasa es `comparar_tasas`, sin Qt.
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen

from app.franja import (AMARILLO, AZUL, GRIS, GRIS_CORTE, GRIS_LEYENDA, NARANJA,
                        NARANJA_MARCA, ROJO_PERDIDA, VERDE, Franja, _cuenta, _tasa)

# (clave, título, qué hace, color), en el orden de la ecuación.
ETAPAS = (
    ('disparos', 'Triggers', 'periodic or Poisson\nt_k', AMARILLO),
    ('amplitud', 'Amplitude', 'table of 1024\nA_k', VERDE),
    ('forma', 'Pulse shape', 'Σ A_k h(t − t_k)\nτ_d, τ_r', AZUL),
    ('salida', 'Output', 'base B, noise r\nsat14, channels', NARANJA),
)
COLOR = {clave: color for clave, _t, _d, color in ETAPAS}

AYUDA = {
    'disparos': 'The trigger engine: one pulse every PERIOD cycles, or Poisson '
                'arrivals with a minimum spacing. It stops by itself after N '
                'pulses. Each pulse also triggers the multitrigger (ASG source).',
    'amplitud': 'The height of each pulse, from a table of 1024 entries: one fixed '
                'value, lines of a spectrum drawn with their weights (inverse CDF), '
                'or a sweep in order.',
    'forma': 'The preamplifier pulse: exponential decay τ_d and an optional RC '
             'rise τ_r. The trapezoid and the pole-zero trigger cancel the decay '
             'with Mq.',
    'salida': 'Adds the base B and the noise r, saturates to 14 bits and goes to '
              'the DAC channels. With the digital loopback, IN1 gets OUT1 and IN2 '
              'gets OUT2 instead of the ADC.',
}


# =============================================================================
# La cuenta, sin Qt
# =============================================================================

def comparar_tasas(tasa_gen, lam_mca):
    """λ̂ del MCA contra la tasa del generador: la diferencia relativa, o None si
    alguna de las dos no está (generador parado, MCA sin medir)."""
    if not tasa_gen or tasa_gen <= 0 or lam_mca is None or lam_mca <= 0:
        return None
    return lam_mca / tasa_gen - 1.0


# =============================================================================
# El widget
# =============================================================================

class DiagramaGen(Franja):
    """Una fila: los cuatro bloques y la salida, con el estado debajo."""

    AYUDA = AYUDA

    LEYENDA = (
        (('●', NARANJA_MARCA),
         (' edited, not applied yet: «Apply» writes everything and stops the '
          'generator.   ', GRIS_LEYENDA),
         ('red', ROJO_PERDIDA), (': the shape overflows.   ', GRIS_LEYENDA),
         ('The loopback applies at once.', GRIS_LEYENDA)),
    )

    def __init__(self, parent=None):
        self._info = None                 # lo último del gen.get
        self._estado = None               # lo último del status (gen)
        self._lazo = False
        self._lam_mca = None
        super().__init__(parent)

    # ---------- lo que la pestaña le dice ----------

    def actualizar_gen(self, info):
        self._info = dict(info or {})
        self.update()

    def actualizar_estado(self, est):
        self._estado = dict(est or {})
        if est and est.get('lazo') is not None:
            self._lazo = bool(est['lazo'])
        self.update()

    def set_lazo(self, on):
        self._lazo = bool(on)
        self.update()

    def actualizar_mca(self, lam):
        self._lam_mca = lam
        self.update()

    def limpiar(self):
        self._info = self._estado = self._lam_mca = None
        self.update()

    @property
    def lazo(self):
        return self._lazo

    def diferencia(self):
        """λ̂ del MCA contra la tasa del generador, con el lazo y generando."""
        est = self._estado or {}
        if not (self._lazo and est.get('generando') and self._info):
            return None
        return comparar_tasas(self._info.get('tasa_hz'), self._lam_mca)

    # ---------- medidas ----------

    def _medidas(self):
        f_tit, f_chico = self._fuentes()
        fmt, fmc = QFontMetrics(f_tit), QFontMetrics(f_chico)
        lc = fmc.height()
        y0 = lc + 10.0                       # arriba, el disparo al multitrigger
        h = fmt.height() + 2 * lc + 10.0
        return f_tit, f_chico, fmc, lc, y0, h

    def _alto(self):
        _ft, _fc, _fm, lc, y0, h = self._medidas()
        # dos líneas de estado bajo los bloques y una de leyenda
        return int(y0 + h + 4 + 2 * lc + 6 + lc + 6)

    def _geometria(self):
        f_tit, f_chico, fmc, lc, y0, h = self._medidas()
        x0 = 6.0
        ancho_s = max(fmc.horizontalAdvance(t) for t in (
            'to the MCA input', 'IN1 · IN2 (loopback)', 'MCA λ 99.9 k/s',
            '−99.99 % vs generator')) + 14.0
        hueco = max(fmc.horizontalAdvance(t) for t in ('pulses', '999 k/s')) + 18.0
        x_s = self.width() - 6.0 - ancho_s
        ancho = max(60.0, (x_s - hueco - x0 - 3 * hueco) / 4)
        self._cajas = {clave: QRectF(x0 + i * (ancho + hueco), y0, ancho, h)
                       for i, (clave, *_r) in enumerate(ETAPAS)}
        salida = QRectF(x_s, y0 + 4, ancho_s, h - 8)
        return f_tit, f_chico, fmc, lc, y0, h, salida

    # ---------- el dibujo ----------

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        texto = self._texto()
        f_tit, f_chico, fmc, lc, y0, h, salida = self._geometria()
        c = self._cajas
        ym = y0 + h / 2
        info = self._info or {}
        cfg = info.get('config') or {}
        est = self._estado or {}

        def rotulo(x, y_base, s, color=texto, centro=True, ancho_max=None):
            self._rotulo(p, f_chico, x, y_base, s, color, centro, ancho_max)

        # --- el disparo de cada pulso, al multitrigger (la fuente ASG) ---
        rd = c['disparos']
        self._flecha(p, rd.center().x(), y0, rd.center().x(), 2, texto)
        rotulo(rd.center().x() + 7, fmc.ascent() + 2,
               'trigger to the multitrigger (ASG source)', centro=False)

        # --- las flechas, con la tasa en la de los disparos ---
        claves = [e[0] for e in ETAPAS]
        rotulos = {('disparos', 'amplitud'): 'pulses', ('amplitud', 'forma'): 'A_k',
                   ('forma', 'salida'): 'v(t)'}
        for a, b in zip(claves, claves[1:]):
            self._flecha(p, c[a].right(), ym, c[b].left(), ym, texto)
            xc = (c[a].right() + c[b].left()) / 2
            rotulo(xc, ym - 5, rotulos[(a, b)])
        if info.get('tasa_hz'):
            xc = (c['disparos'].right() + c['amplitud'].left()) / 2
            rotulo(xc, ym + fmc.ascent() + 4, _tasa(float(info['tasa_hz'])))

        # --- la salida: al DAC, o con el lazo a la entrada del MCA ---
        self._flecha(p, c['salida'].right(), ym, salida.left(), ym, texto)
        if self._lazo:
            p.setPen(QPen(ROJO_PERDIDA, 2.0))
            p.setBrush(QColor(250, 219, 216))
            lineas = ['to the MCA input', 'IN1 · IN2 (loopback)']
        else:
            p.setPen(QPen(QColor(90, 90, 90), 1.0))
            p.setBrush(GRIS)
            lineas = ['to the DAC', 'OUT1 · OUT2']
        p.drawRoundedRect(salida, 3, 3)
        p.setBrush(Qt.NoBrush)
        y = salida.center().y() - (len(lineas) * lc) / 2 + fmc.ascent()
        for k, s in enumerate(lineas):
            rotulo(salida.center().x(), y + k * lc, s, Qt.black,
                   ancho_max=salida.width() - 4)

        for clave, titulo, desc, color in ETAPAS:
            self._bloque(p, clave, titulo, desc, color, c[clave], f_tit, f_chico)

        # --- el estado, bajo cada bloque ---
        yb = y0 + h + 4 + fmc.ascent()
        debajo = {}
        if est or info:
            if est.get('error'):
                estado = ('error', ROJO_PERDIDA)
            elif est.get('generando'):
                estado = ('generating', texto)
            elif est.get('terminado'):
                estado = ('finished (reached N)', GRIS_CORTE)
            else:
                estado = ('stopped', GRIS_CORTE)
            debajo['disparos'] = [estado]
            if est.get('gen_cnt') is not None:
                debajo['disparos'].append(
                    (f"{_cuenta(int(est['gen_cnt']))} generated", GRIS_CORTE))
        lineas_amp = info.get('lineas') or []
        if lineas_amp:
            if len(lineas_amp) == 1:
                s = f'fixed: {int(lineas_amp[0][0])} counts'
            elif cfg.get('amp_aleat'):
                s = f'{len(lineas_amp)} lines, drawn'
            else:
                s = f'{len(lineas_amp)} values in order'
            debajo['amplitud'] = [(s, GRIS_CORTE)]
        if info.get('tau_us') is not None:
            debajo['forma'] = [(f"τ_d {float(info['tau_us']):.3f} µs", GRIS_CORTE)]
            if info.get('mq') is not None:
                debajo['forma'].append((f"Mq {info['mq']}", GRIS_CORTE))
        filas_sal = []
        if est.get('desborde'):
            filas_sal.append(('OVERFLOW: lower A_k or the rate', ROJO_PERDIDA))
        if info:
            filas_sal.append((f"noise σ {float(info.get('sigma_ruido', 0)):.3g} counts"
                              if cfg.get('ruido') else 'no noise', GRIS_CORTE))
        if filas_sal:
            debajo['salida'] = filas_sal
        for i, clave in enumerate(claves):
            r = c[clave]
            sig = c[claves[i + 1]].left() if i + 1 < len(claves) else salida.left()
            for k, (s, color) in enumerate(debajo.get(clave, [])[:2]):
                rotulo(r.left() + 2, yb + k * lc, s, color, centro=False,
                       ancho_max=sig - r.left() - 6)

        # --- con el lazo: lo que mide el MCA contra lo que da el generador ---
        dif = self.diferencia()
        if dif is not None:
            rotulo(salida.center().x(), yb, f'MCA λ {_tasa(self._lam_mca)}', texto)
            rotulo(salida.center().x(), yb + lc, f'{100 * dif:+.2f} % vs generator',
                   ROJO_PERDIDA if abs(dif) > 0.05 else GRIS_CORTE)

        # --- la leyenda, abajo de todo ---
        self._leyenda(p, f_chico, 6, yb + 2 * lc + 6, self.width() - 12, self.LEYENDA)
