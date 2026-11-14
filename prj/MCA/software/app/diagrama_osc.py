#!/usr/bin/env python3
"""El datapath del osciloscopio y del ring en una franja: el índice de la pestaña
«Configuración OSC», y los disparos y las pérdidas del ring.

Los bloques siguen el panorama del scope con el ring
(docs/osc/figuras/panorama_rp_scope_mt_com_ring.tex), con sus colores: azul el
acondicionamiento, amarillo el disparo, verde la captura en BRAM y naranja el camino
a DDR. Dos filas:

- **arriba, el osciloscopio**: entrada (calibración y filtro), diezmado, disparo y la
  captura en BRAM, que es lo que muestra la pestaña «Pulsos». En la flecha del
  disparo a la BRAM va la tasa de disparos (Δ`we_cnt`/Δt), y bajo la BRAM el estado
  de sus dos FSM;
- **abajo, el ring** (sólo con su bitstream): el disparo baja a la ventana, o la
  dispara el generador de eventos; la ventana va a un slot del ring en la DDR, y el
  lector de la placa la saca a archivos. Las flechas llevan las cuentas de la corrida
  (disparos, capturados, leídos, escritos) y, debajo, lo que se pierde: `DROP_BUSY`
  (la captura todavía escribía la anterior) y `DROP_FULL` (no había slot libre). La
  flecha del estímulo que no se usa va punteada. La cuenta es `flujo_ring`, sin Qt.

Bajo la entrada y el diezmado, que no pierden nada, va la leyenda de la pestaña.
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen

from app.franja import (AMARILLO, AZUL, GRIS, GRIS_CORTE, GRIS_LEYENDA, NARANJA,
                        ROJO_PERDIDA, VERDE, Franja, _cuenta, _pct, _tasa)

# (clave, título, qué hace, color), en el orden del dato.
ETAPAS_OSC = (
    ('entrada', 'Entrada', 'offset, ganancia\nfiltro', AZUL),
    ('diezmado', 'Diezmado', 'factor\ncon o sin promedio', AZUL),
    ('disparo', 'Disparo', 'umbral, histéresis\nantirrebote', AMARILLO),
    ('bram', 'Captura BRAM', 'anillo de 2^RSZ\nretardo post-disparo', VERDE),
)
ETAPAS_RING = (
    ('generador', 'Generador', 'de eventos\n(sin señal)', AMARILLO),
    ('ventana', 'Ventana', 'pre + post\nde los dos canales', NARANJA),
    ('ddr', 'Ring en DDR', 'slots\ncon créditos', NARANJA),
    ('archivos', 'Lector y archivos', 'lotes en RAM\ncarpeta, formato', NARANJA),
)
ETAPAS = ETAPAS_OSC + ETAPAS_RING
COLOR = {clave: color for clave, _t, _d, color in ETAPAS}

AYUDA = {
    'entrada': 'La calibración de cada canal (offset y ganancia) y el filtro de '
               'entrada, que se puede saltear por canal.',
    'diezmado': 'El factor de diezmado (sólo seis valores legales) y si promedia las '
                'muestras que descarta. Estira la ventana en tiempo real.',
    'disparo': 'El disparo por flanco del ADC: umbral, histéresis y el antirrebote. '
               'Es del multitrigger, por el puente de los registros del scope. Con '
               'el ring, también dispara sus ventanas.',
    'bram': 'El anillo en BRAM de cada canal y su FSM: después del disparo escribe '
            'el retardo y para. Es lo que lee la pestaña «Pulsos».',
    'generador': 'El generador de eventos del ring: dispara solo, periódico o '
                 'Poisson, y llena cada slot con un patrón conocido. Sirve para medir '
                 'el camino a disco sin señal.',
    'ventana': 'Por cada disparo, pre + post muestras de los dos canales.\n'
               'Pérdida: DROP_BUSY, el disparo llegó con la captura todavía '
               'escribiendo la ventana anterior.',
    'ddr': 'El ring de slots en la DDR, con créditos: el lector libera los que ya '
           'leyó.\nPérdida: DROP_FULL, no había slot libre (el lector no daba abasto).',
    'archivos': 'En la placa, el lector de libmca saca los slots en lotes y la sesión '
                'los escribe en archivos, en la carpeta elegida.',
}


# =============================================================================
# La cuenta, sin Qt
# =============================================================================

def flujo_ring(e):
    """Las cuentas de una corrida del ring desde su `ring.estado` (o lo que devuelve
    `ring.parar`). None si todavía no hay contadores.

    disparos = capturados (EV_CNT) + ocupada (DROP_BUSY) + lleno (DROP_FULL): todo
    disparo se captura o se cuenta perdido. `leidos` y `escritos` son de la sesión;
    `sin_leer` son los slots escritos que el lector todavía no sacó (la resta sin
    signo que da la vuelta es cero)."""
    if not e:
        return None
    hw = e.get('hw') or e.get('hw_final') or {}
    if not hw:
        return None
    stats = e.get('stats') or {}
    ev = int(hw.get('hw_ev_cnt', 0) or 0)
    busy = int(hw.get('hw_drop_busy', 0) or 0)
    full = int(hw.get('hw_drop_full', 0) or 0)
    sin_leer = int(hw.get('hw_no_leidos', 0) or 0) & 0xFFFFFFFF
    if sin_leer >= 1 << 31:
        sin_leer = 0
    disparos = ev + busy + full
    return dict(disparos=disparos, capturados=ev, ocupada=busy, lleno=full,
                perdidos=busy + full,
                frac_perdidos=(busy + full) / disparos if disparos else 0.0,
                leidos=int(stats.get('n_read', 0) or 0),
                escritos=int(stats.get('n_written', 0) or 0),
                archivos=int(stats.get('chunks', 0) or 0),
                sin_leer=sin_leer, n_slots=int(hw.get('hw_n_slots') or
                                               e.get('n_slots') or 0),
                corriendo=bool(e.get('corriendo')))


# =============================================================================
# El widget
# =============================================================================

class DiagramaOsc(Franja):
    """Dos filas en la misma grilla de cuatro columnas: el osciloscopio y el ring.
    Sin ring, sólo la de arriba."""

    AYUDA = AYUDA

    LEYENDA = (
        (('·', GRIS_LEYENDA), (' reinicia la captura en curso    ', GRIS_LEYENDA),
         ('⚠', GRIS_LEYENDA), (' mal puesto, no llega ningún disparo', GRIS_LEYENDA)),
        (('rojo', ROJO_PERDIDA), (': disparo perdido    ', GRIS_LEYENDA),
         ('gris', GRIS_CORTE), (': estado', GRIS_LEYENDA)),
    )
    LEYENDA_RING = (('El ring toma su configuración al iniciar.', GRIS_LEYENDA),)

    def __init__(self, parent=None):
        self._hay_ring = False
        self._estimulo = 'disparo'
        self._osc = None                 # {we_cnt, tasa, adc_state, trg_state}
        self._ring = None                # flujo_ring
        self._tasa_lectura = None
        super().__init__(parent)

    # ---------- lo que la pestaña le dice ----------

    def configurar(self, hay_osc, hay_ring):
        self._hay_ring = bool(hay_ring)
        self.ocultar(set() if hay_osc else {k for k, *_ in ETAPAS_OSC})
        self._reajustar()

    def set_estimulo(self, estimulo):
        if estimulo != self._estimulo:
            self._estimulo = estimulo
            self.update()

    def actualizar_osc(self, estado, tasa_disparos=None):
        est = estado or {}
        self._osc = dict(we_cnt=est.get('we_cnt_ch0'), tasa=tasa_disparos,
                         adc_state=est.get('adc_state'), trg_state=est.get('trg_state'))
        self.update()

    def actualizar_ring(self, e, tasa_lectura=None):
        self._ring = flujo_ring(e)
        self._tasa_lectura = tasa_lectura
        self.update()

    def limpiar(self):
        self._osc = None
        self._ring = None
        self._tasa_lectura = None
        self.update()

    @property
    def hay_ring(self):
        return self._hay_ring

    @property
    def flujo(self):
        return self._ring

    # ---------- medidas ----------

    def _medidas(self):
        f_tit, f_chico = self._fuentes()
        fmt, fmc = QFontMetrics(f_tit), QFontMetrics(f_chico)
        lc = fmc.height()
        h = fmt.height() + 2 * lc + 10.0
        y0 = 6.0
        # bajo la fila de arriba: tres líneas (leyenda, estado) y el codo del disparo
        y1 = y0 + h + 4 + 3 * lc + 18.0
        return f_tit, f_chico, fmc, lc, h, y0, y1

    def _alto(self):
        _ft, _fc, _fm, lc, h, y0, y1 = self._medidas()
        # abajo de la última fila: tres líneas bajo la del OSC (la leyenda), dos bajo
        # la del ring (las pérdidas y el total)
        if getattr(self, '_hay_ring', False):
            return int(y1 + h + 4 + 2 * lc + 6)
        return int(y0 + h + 4 + 3 * lc + 6)

    def _geometria(self):
        f_tit, f_chico, fmc, lc, h, y0, y1 = self._medidas()
        x_ent = fmc.horizontalAdvance('ADC') + 22.0
        ancho_s = max(fmc.horizontalAdvance(t) for t in (
            'a la vista', 'perdidos 9.99 %', '99.9 k de 9.99 M', '999 999 escritos',
            '9999 archivos', 'a la carpeta')) + 12.0
        hueco = max(fmc.horizontalAdvance(t) for t in (
            'capturados', 'disparos', '9.99 M', '999 k/s')) + 16.0
        x_s = self.width() - 6.0 - ancho_s
        ancho = max(60.0, (x_s - hueco - x_ent - 3 * hueco) / 4)
        self._cajas = {}
        for fila, y in ((ETAPAS_OSC, y0), (ETAPAS_RING, y1)):
            if fila is ETAPAS_RING and not self._hay_ring:
                continue
            for i, (clave, *_r) in enumerate(fila):
                self._cajas[clave] = QRectF(x_ent + i * (ancho + hueco), y, ancho, h)
        salida_osc = QRectF(x_s, y0 + 4, ancho_s, h - 8)
        salida_ring = QRectF(x_s, y1 + 4, ancho_s, h - 8)
        return f_tit, f_chico, fmc, lc, h, y0, y1, x_ent, salida_osc, salida_ring

    # ---------- el dibujo ----------

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        texto = self._texto()
        (f_tit, f_chico, fmc, lc, h, y0, y1, x_ent,
         salida_osc, salida_ring) = self._geometria()
        c = self._cajas

        def rotulo(x, y_base, s, color=texto, centro=True, ancho_max=None):
            self._rotulo(p, f_chico, x, y_base, s, color, centro, ancho_max)

        def en_flecha(ra, rb, ym, arriba, abajo=None):
            xc = (ra.right() + rb.left()) / 2
            rotulo(xc, ym - 5, arriba)
            if abajo:
                rotulo(xc, ym + fmc.ascent() + 4, abajo)

        def caja_gris(r, lineas):
            p.setPen(QPen(QColor(90, 90, 90), 1.0))
            p.setBrush(GRIS)
            p.drawRoundedRect(r, 3, 3)
            p.setBrush(Qt.NoBrush)
            y = r.center().y() - (len(lineas) * lc) / 2 + fmc.ascent()
            for k, s in enumerate(lineas):
                rotulo(r.center().x(), y + k * lc, s, Qt.black, ancho_max=r.width() - 4)

        # ===================== arriba: el osciloscopio =====================
        ym = y0 + h / 2
        self._flecha(p, 4, ym, c['entrada'].left(), ym, texto)
        rotulo(x_ent / 2, ym - 5, 'ADC')
        claves = [e[0] for e in ETAPAS_OSC]
        o = self._osc or {}
        for a, b in zip(claves, claves[1:]):
            self._flecha(p, c[a].right(), ym, c[b].left(), ym, texto)
        if o.get('tasa') is not None:
            en_flecha(c['disparo'], c['bram'], ym, 'disparos', _tasa(o['tasa']))
        else:
            en_flecha(c['disparo'], c['bram'], ym, 'disparos')
        self._flecha(p, c['bram'].right(), ym, salida_osc.left(), ym, texto)
        caja_gris(salida_osc, ['a la vista', '«Pulsos»'])
        for clave, titulo, desc, color in ETAPAS_OSC:
            self._bloque(p, clave, titulo, desc, color, c[clave], f_tit, f_chico)

        yb = y0 + h + 4 + fmc.ascent()
        rb = c['bram']
        if o:
            filas = []
            if o.get('we_cnt') is not None:
                filas.append(f"IN1: {_cuenta(o['we_cnt'])} disparos")
            if o.get('adc_state') is not None:
                filas.append(f"FSM: ADC {o['adc_state']} · disparo {o.get('trg_state')}")
            for k, s in enumerate(filas):
                rotulo(rb.left() + 2, yb + k * lc, s, GRIS_CORTE, centro=False,
                       ancho_max=salida_osc.right() - rb.left() - 4)

        filas_leyenda = list(self.LEYENDA)
        if self._hay_ring:
            filas_leyenda.append(self.LEYENDA_RING)
        self._leyenda(p, f_chico, 6, yb, c['disparo'].left() - 16, filas_leyenda)

        if not self._hay_ring:
            return

        # ===================== abajo: el ring =====================
        ym2 = y1 + h / 2
        fl = self._ring
        gen = self._estimulo == 'generador'
        activo, inactivo = texto, QColor(170, 170, 170)

        # el estímulo: el disparo baja por un codo, o el generador entra de costado
        rd, rv = c['disparo'], c['ventana']
        x_d = rd.center().x()
        y_codo = y1 - 9
        col = inactivo if gen else activo
        pen = QPen(col, 1.3)
        if gen:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawLine(int(x_d), int(rd.bottom()), int(x_d), int(y_codo))
        p.drawLine(int(x_d), int(y_codo), int(rv.center().x()), int(y_codo))
        self._flecha(p, rv.center().x(), y_codo, rv.center().x(), rv.top(), col,
                     punteada=gen)
        rg = c['generador']
        self._flecha(p, rg.right(), ym2, rv.left(), ym2,
                     activo if gen else inactivo, punteada=not gen)
        if fl:
            s = f"disparos {_cuenta(fl['disparos'])}"
            if gen:
                en_flecha(rg, rv, ym2, 'disparos', _cuenta(fl['disparos']))
            else:
                rotulo(rv.center().x() + 6, y_codo - 3, s, centro=False,
                       ancho_max=x_d - rv.center().x() - 10)

        self._flecha(p, rv.right(), ym2, c['ddr'].left(), ym2, texto)
        self._flecha(p, c['ddr'].right(), ym2, c['archivos'].left(), ym2, texto)
        self._flecha(p, c['archivos'].right(), ym2, salida_ring.left(), ym2, texto)
        if fl:
            en_flecha(rv, c['ddr'], ym2, 'capturados', _cuenta(fl['capturados']))
            en_flecha(c['ddr'], c['archivos'], ym2, 'leídos', _cuenta(fl['leidos']))
            caja_gris(salida_ring, ['a la carpeta',
                                    f"{_cuenta(fl['escritos'])} escritos",
                                    f"{fl['archivos']} archivos"])
        else:
            en_flecha(rv, c['ddr'], ym2, 'capturados')
            en_flecha(c['ddr'], c['archivos'], ym2, 'leídos')
            caja_gris(salida_ring, ['a la carpeta'])

        for clave, titulo, desc, color in ETAPAS_RING:
            self._bloque(p, clave, titulo, desc, color, c[clave], f_tit, f_chico)
        if not gen:
            # el generador no se usa: se nota sin taparlo
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 120))
            p.drawRoundedRect(rg.adjusted(1, 1, -1, -1), 4, 4)
            p.setBrush(Qt.NoBrush)

        if not fl:
            return
        yb2 = y1 + h + 4 + fmc.ascent()
        N = fl['disparos']

        def pct(x):
            return f' · {_pct(x, N)}' if N > 0 else ''

        debajo = {
            'ventana': [(f"captura ocupada {_cuenta(fl['ocupada'])}{pct(fl['ocupada'])}",
                         ROJO_PERDIDA)],
            'ddr': [(f"ring lleno {_cuenta(fl['lleno'])}{pct(fl['lleno'])}",
                     ROJO_PERDIDA)]
                   + ([(f"sin leer {_cuenta(fl['sin_leer'])} de "
                        f"{_cuenta(fl['n_slots'])}", GRIS_CORTE)] if fl['n_slots'] else []),
            'archivos': [(('lectura ' + _tasa(self._tasa_lectura)) if
                          self._tasa_lectura is not None else '', GRIS_CORTE),
                         ('corriendo' if fl['corriendo'] else 'parado', GRIS_CORTE)],
        }
        orden = [e[0] for e in ETAPAS_RING]
        for clave, filas in debajo.items():
            r = c[clave]
            i = orden.index(clave)
            sig = c[orden[i + 1]].left() if i + 1 < len(orden) else salida_ring.left()
            for k, (s, color) in enumerate(f for f in filas if f[0]):
                rotulo(r.left() + 2, yb2 + k * lc, s, color, centro=False,
                       ancho_max=sig - r.left() - 6)
        if N > 0:
            rotulo(salida_ring.center().x(), yb2,
                   f"perdidos {_pct(fl['perdidos'], N)}", ROJO_PERDIDA)
            rotulo(salida_ring.center().x(), yb2 + lc,
                   f"{_cuenta(fl['perdidos'])} de {_cuenta(N)}", ROJO_PERDIDA)
