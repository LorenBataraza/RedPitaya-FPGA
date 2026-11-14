#!/usr/bin/env python3
"""El datapath del MCA en una franja: el índice de la pestaña de configuración, y
las tasas y las pérdidas de la medición.

Los bloques son las etapas del panorama (docs/mca/figuras/panorama_mca_top.tex),
con sus colores: azul el preprocesamiento, amarillo la segmentación, verde los
estadísticos del pulso, naranja la publicación. La franja hace tres cosas:

- **índice**: un clic en un bloque emite `etapa_elegida`, y `resaltar` marca el
  bloque de los controles que tienen el foco;
- **aviso**: `marcar` pone un punto sobre los bloques que se cambiaron con cuentas
  en el histograma (lo acumulado mezcla dos configuraciones);
- **flujo**: `actualizar` escribe la tasa de cada tramo y, debajo de cada etapa, lo
  que se pierde ahí. La cuenta es `flujo_mca`, que no depende de Qt.

Bajo el preprocesamiento, que no pierde nada, va la leyenda de la pestaña: qué
dicen el punto y la ⚠ de los controles, y los colores de las pérdidas. La base
común con la franja del OSC está en `franja.py`.

Las pérdidas (rojo) son lo que llegó y no se midió; los cortes (gris) son lo que
el usuario pidió descartar: la ventana de amplitud y el discriminador.
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen

from app.franja import (AMARILLO, AZUL, GRIS, GRIS_CORTE, GRIS_LEYENDA,  # noqa: F401
                        NARANJA, NARANJA_MARCA, ROJO_PERDIDA, VERDE, Franja, _cuenta,
                        _pct, _tasa)

# (clave, título, qué hace, color). El orden es el del dato.
ETAPAS = (
    ('entrada', 'Entrada', 'canal, decim.\nretardo', AZUL),
    ('base', 'Base', 'seguidor\no fija', AZUL),
    ('trapecio', 'Trapecios', 'k, m, M', AZUL),
    ('segmentacion', 'Disparo', 'asigna\nla ranura', AMARILLO),
    ('estadisticos', 'Ranuras', 'compuertas', VERDE),
    ('publicacion', 'Publicación', 'eje, discr.\nhistograma', NARANJA),
)
COLOR = {clave: color for clave, _t, _d, color in ETAPAS}

AYUDA = {
    'entrada': 'El canal (IN1/IN2), la decimación propia del MCA y el retardo '
               'de la muestra respecto del disparo.',
    'base': 'La línea de base que se resta: un seguidor IIR quieto durante las '
            'ventanas, o un valor fijo.',
    'trapecio': 'El banco de trapecios con polo-cero: un filtro continuo que '
                'comparten las ranuras.',
    'segmentacion': 'El disparo llega del multitrigger (se arma en Espectro); el '
                    'asignador le da la ranura libre de menor índice.\n'
                    'Pérdidas: el re-armado del disparo (estimada con λ̂), sin '
                    'ranura libre, y esperando al publicador.',
    'estadisticos': 'Cada ranura mide su ventana: pico, integrales, largo. La '
                    'ventana de amplitud (en Espectro) descarta al cerrar.',
    'publicacion': 'De la ventana cerrada al histograma: qué feature va al eje, el '
                   'zoom, el discriminador y el histograma.',
}


# =============================================================================
# La cuenta, sin Qt
# =============================================================================

def flujo_mca(cnt, tasa_entrada_hz=0.0):
    """Los eventos de cada tramo del MCA y lo que se pierde en cada etapa, desde los
    contadores (`mca_read_counters`) y la tasa de entrada estimada λ̂ (la del
    `status`). Todo sobre el tiempo medido, T = real − veto, desde el último borrado.

    Tramos (cuentas y tasas = cuentas / T):
      - `pulsos`: N̂ = λ̂·T, los que llegaron (estimado: incluye los que cayeron con
        el disparo sin re-armar, que no dejan cuenta);
      - `disparos`: cross − lost_veto, los flancos fuera del veto;
      - `ventanas`: open, los que consiguieron ranura;
      - `cerradas`: total, las ventanas que cerraron;
      - `publicados`: accepted, los que pasaron la ventana de amplitud;
      - `al_histograma`: publicados − discriminador − bin lleno − colisiones.

    Pérdidas (lo que llegó y no se midió):
      - `rearmado`: N̂ − disparos, estimada;
      - `sin_ranura`: lost_active, todas midiendo;
      - `publicador`: lost_busy = cross − open − lost_active − lost_veto, sin
        ranura con alguna esperando al publicador;
      - `colisiones`: dropped − lost_busy, el histograma ocupado por una lectura
        o un borrado (1D y 2D juntos: el contador es uno).
    Cortes (lo que se pidió descartar): `fuera_amplitud` (rej_amp),
    `discriminador` (rej_discr), `bin_lleno` (full_supp).

    `perdidos` suma las pérdidas por tiempo muerto (re-armado, sin ranura,
    publicador) y `frac_perdidos` es sobre N̂. Leídos con la medición corriendo,
    los contadores son de ciclos distintos: las restas se recortan en cero."""
    def n(clave):
        return int(cnt.get(clave, 0) or 0)

    def s(clave):
        return float(cnt.get(clave, 0.0) or 0.0)

    T = max(0.0, s('realtime_s') - s('vetotime_s'))
    lam = float(tasa_entrada_hz or 0.0)
    disparos = max(0, n('cross') - n('lost_veto'))
    pulsos = lam * T
    lost_busy = max(0, n('cross') - n('open') - n('lost_active') - n('lost_veto'))
    cuentas = {
        'pulsos': pulsos,
        'disparos': disparos,
        'ventanas': n('open'),
        'cerradas': n('total'),
        'publicados': n('accepted'),
        'rearmado': max(0.0, pulsos - disparos),
        'sin_ranura': n('lost_active'),
        'publicador': lost_busy,
        'colisiones': max(0, n('dropped') - lost_busy),
        'veto': n('lost_veto'),
        'fuera_amplitud': n('rej_amp'),
        'discriminador': n('rej_discr'),
        'bin_lleno': n('full_supp'),
    }
    cuentas['al_histograma'] = max(0, cuentas['publicados'] - cuentas['discriminador']
                                   - cuentas['bin_lleno'] - cuentas['colisiones'])
    perdidos = cuentas['rearmado'] + cuentas['sin_ranura'] + cuentas['publicador']
    return dict(
        T=T, cuentas=cuentas,
        tasas={k: (v / T if T > 0 else 0.0) for k, v in cuentas.items()},
        perdidos=perdidos,
        frac_perdidos=(perdidos / pulsos if pulsos > 0 else 0.0))


# =============================================================================
# El widget
# =============================================================================

class DiagramaMCA(Franja):
    """La franja del MCA: bloques, tasas en las flechas, pérdidas debajo y, bajo el
    preprocesamiento (que no pierde nada), la leyenda de la pestaña."""

    AYUDA = AYUDA

    # Los tramos de eventos llevan su nombre y su tasa en la flecha: necesitan un
    # hueco más ancho que los de la señal.
    FLECHAS_CON_TASA = {('segmentacion', 'estadisticos'): 'ventanas',
                        ('estadisticos', 'publicacion'): 'cerradas'}

    # La leyenda: lo que dicen las marcas de los controles y los colores de abajo.
    LEYENDA = (
        (('Todo vale en caliente: nada pide parar el MCA.', GRIS_LEYENDA),),
        (('●', NARANJA_MARCA),
         (' cambiado con cuentas: mezcla dos configuraciones', GRIS_LEYENDA)),
        (('⚠ mal puesto, no llega ningún evento', GRIS_LEYENDA),),
        (('rojo', ROJO_PERDIDA), (': llegó y no se midió   ', GRIS_LEYENDA),
         ('gris', GRIS_CORTE), (': descartado a propósito', GRIS_LEYENDA)),
    )

    def __init__(self, parent=None):
        self._flujo = None
        super().__init__(parent)

    def actualizar(self, cnt, tasa_entrada_hz):
        self._flujo = flujo_mca(cnt or {}, tasa_entrada_hz)
        self.update()

    def limpiar(self):
        self._flujo = None
        self.update()

    @property
    def flujo(self):
        return self._flujo

    # ---------- medidas ----------

    def _alto(self):
        f_tit, f_chico = self._fuentes()
        lt, lc = QFontMetrics(f_tit).height(), QFontMetrics(f_chico).height()
        # el disparo arriba, el bloque (título y dos líneas), cuatro de pérdidas
        return int(lc + 10 + (lt + 2 * lc + 10) + 4 * lc + 10)

    def _geometria(self):
        """Dónde va cada cosa, para el ancho actual: (y0, h, x de la flecha de
        entrada, la caja del histograma, el alto de línea chica)."""
        f_tit, f_chico = self._fuentes()
        fmt, fmc = QFontMetrics(f_tit), QFontMetrics(f_chico)
        lc = fmc.height()
        y0 = lc + 10.0
        h = fmt.height() + 2 * lc + 10.0
        x_ent = fmc.horizontalAdvance('999 k/s') + 18.0
        ancho_h = max(fmc.horizontalAdvance(t) for t in (
            'al histograma', 'perdidos 9.99 %', '99.9 k de 9.99 M',
            '(estimado con λ)')) + 12.0
        hueco_s = 22.0
        hueco_e = max(fmc.horizontalAdvance(t) for t in ('999 k/s', 'ventanas',
                                                          'cerradas')) + 16.0
        claves = [e[0] for e in ETAPAS]
        huecos = [hueco_e if (a, b) in self.FLECHAS_CON_TASA else hueco_s
                  for a, b in zip(claves, claves[1:])]
        x_h = self.width() - 6.0 - ancho_h
        libre = x_h - hueco_s - x_ent - sum(huecos)
        ancho = max(50.0, libre / len(ETAPAS))
        self._cajas = {}
        x = x_ent
        for i, clave in enumerate(claves):
            self._cajas[clave] = QRectF(x, y0, ancho, h)
            x += ancho + (huecos[i] if i < len(huecos) else 0.0)
        caja_h = QRectF(x_h, y0 + 4, ancho_h, h - 8)
        return f_tit, f_chico, y0, h, x_ent, caja_h, lc

    # ---------- el dibujo ----------

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        texto = self._texto()
        f_tit, f_chico, y0, h, x_ent, caja_h, lc = self._geometria()
        fmc = QFontMetrics(f_chico)
        ym = y0 + h / 2
        fl = self._flujo
        tasas = fl['tasas'] if fl else {}

        def flecha(x1, y1, x2, y2, color=texto):
            self._flecha(p, x1, y1, x2, y2, color)

        def rotulo(x, y_base, s, color=texto, centro=True, ancho_max=None):
            self._rotulo(p, f_chico, x, y_base, s, color, centro, ancho_max)

        # --- la entrada: los pulsos que llegan (λ̂) ---
        r0 = self._cajas['entrada']
        flecha(4, ym, r0.left(), ym)
        rotulo(x_ent / 2, ym - 5, 'pulsos')
        if fl:
            rotulo(x_ent / 2, ym + fmc.ascent() + 4, _tasa(tasas['pulsos']))

        # --- las flechas entre bloques: la señal, y después los eventos ---
        claves = [e[0] for e in ETAPAS]
        for a, b in zip(claves, claves[1:]):
            ra, rb = self._cajas[a], self._cajas[b]
            flecha(ra.right(), ym, rb.left(), ym)
            nombre = self.FLECHAS_CON_TASA.get((a, b))
            if nombre:
                xc = (ra.right() + rb.left()) / 2
                rotulo(xc, ym - 5, nombre)
                if fl:
                    rotulo(xc, ym + fmc.ascent() + 4, _tasa(tasas[nombre]))

        # --- el disparo, que baja del multitrigger a la segmentación ---
        rs = self._cajas['segmentacion']
        flecha(rs.center().x(), 2, rs.center().x(), y0)
        s = 'disparos del multitrigger'
        if fl:
            s += '   ' + _tasa(tasas['disparos'])
        rotulo(rs.center().x() + 7, fmc.ascent() + 2, s, centro=False)

        # --- la salida: al histograma, y el total perdido ---
        rp = self._cajas['publicacion']
        flecha(rp.right(), ym, caja_h.left(), ym)
        p.setPen(QPen(QColor(90, 90, 90), 1.0))
        p.setBrush(GRIS)
        p.drawRoundedRect(caja_h, 3, 3)
        p.setBrush(Qt.NoBrush)
        lineas = ['al histograma'] + ([_tasa(tasas['al_histograma'])] if fl else [])
        y = caja_h.center().y() - (len(lineas) * lc) / 2 + fmc.ascent()
        for k, s in enumerate(lineas):
            rotulo(caja_h.center().x(), y + k * lc, s, Qt.black)
        if fl and fl['cuentas']['pulsos'] > 0:
            yb = y0 + h + 4 + fmc.ascent()
            rotulo(caja_h.center().x(), yb,
                   f"perdidos {_pct(fl['perdidos'], fl['cuentas']['pulsos'])}",
                   ROJO_PERDIDA)
            rotulo(caja_h.center().x(), yb + lc,
                   f"{_cuenta(fl['perdidos'])} de {_cuenta(fl['cuentas']['pulsos'])}",
                   ROJO_PERDIDA)
            rotulo(caja_h.center().x(), yb + 2 * lc, '(estimado con λ)', GRIS_CORTE)

        # --- los bloques ---
        for clave, titulo, desc, color in ETAPAS:
            self._bloque(p, clave, titulo, desc, color, self._cajas[clave],
                         f_tit, f_chico)

        # --- la leyenda, bajo el preprocesamiento: ahí no se pierde nada ---
        x_fin = self._cajas['segmentacion'].left() - 10
        self._leyenda(p, f_chico, 6, y0 + h + 4 + fmc.ascent(), x_fin - 6, self.LEYENDA)

        # --- lo que se pierde (rojo) y lo que se corta (gris), bajo cada etapa ---
        if not fl:
            return
        c = fl['cuentas']
        N = c['pulsos']

        def pct(x):
            return f' · {_pct(x, N)}' if N > 0 else ''

        debajo = {
            'segmentacion': [(f"re-armado ≈{_cuenta(c['rearmado'])}{pct(c['rearmado'])}",
                              ROJO_PERDIDA),
                             (f"sin ranura {_cuenta(c['sin_ranura'])}"
                              f"{pct(c['sin_ranura'])}", ROJO_PERDIDA),
                             (f"publicador {_cuenta(c['publicador'])}"
                              f"{pct(c['publicador'])}", ROJO_PERDIDA)]
                            + ([(f"vetados {_cuenta(c['veto'])}", GRIS_CORTE)]
                               if c['veto'] else []),
            'estadisticos': [(f"fuera de ampl. {_cuenta(c['fuera_amplitud'])}",
                              GRIS_CORTE)],
            'publicacion': [(f"discrim. {_cuenta(c['discriminador'])}", GRIS_CORTE),
                            (f"bin lleno {_cuenta(c['bin_lleno'])}", GRIS_CORTE),
                            (f"colisiones {_cuenta(c['colisiones'])}", ROJO_PERDIDA)],
        }
        claves_orden = [e[0] for e in ETAPAS]
        for clave, filas in debajo.items():
            r = self._cajas[clave]
            i = claves_orden.index(clave)
            sig = (self._cajas[claves_orden[i + 1]].left() if i + 1 < len(claves_orden)
                   else caja_h.left())
            for k, (s, color) in enumerate(filas):
                rotulo(r.left() + 2, r.bottom() + 4 + fmc.ascent() + k * lc, s, color,
                       centro=False, ancho_max=sig - r.left() - 6)
