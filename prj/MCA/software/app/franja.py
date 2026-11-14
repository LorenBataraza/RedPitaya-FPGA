#!/usr/bin/env python3
"""La base de las franjas de datapath de las pestañas de configuración.

Una franja dibuja las etapas de un bloque como en su panorama (mismos colores), y es
el índice de la pestaña: un clic en un bloque emite `etapa_elegida`, `resaltar` marca
el bloque de los controles con el foco o el ratón, `marcar` le pone un punto, y
`ocultar` apaga los que el bitstream no trae. Las subclases ponen la geometría
(`_alto`, `_geometria` que llena `_cajas`) y el dibujo (`paintEvent`), con los
ayudantes de acá: `_flecha`, `_rotulo`, `_bloque` y `_leyenda`.

Todas las medidas salen de la fuente, así que se acomodan a cualquier DPI.
"""

from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPen, QPolygonF
from PyQt5.QtWidgets import QSizePolicy, QToolTip, QWidget

# Los colores del panorama: `color!p` de TikZ es p % del color y el resto blanco
# (docs/figuras/estilo_tikz.tex: azul 108,172,228; amarillo 252,232,160;
# verde 110,214,142; naranja 252,206,160).
AZUL = QColor(204, 226, 246)          # azul!35
AMARILLO = QColor(253, 238, 184)      # amarillo!75
VERDE = QColor(175, 232, 193)         # verde!55
NARANJA = QColor(253, 221, 189)       # naranja!70
GRIS = QColor(226, 226, 226)          # grisr

ROJO_PERDIDA = QColor(192, 57, 43)
GRIS_CORTE = QColor(120, 120, 120)
NARANJA_MARCA = QColor(230, 126, 34)
GRIS_LEYENDA = QColor(110, 110, 110)


def _tasa(x):
    """1.23 k/s, 45.6 /s: tres cifras, con prefijo."""
    for div, pre in ((1e6, 'M'), (1e3, 'k')):
        if abs(x) >= div:
            return f'{x / div:.3g} {pre}/s'
    return f'{x:.3g} /s'


def _cuenta(x):
    """Una cuenta en poco lugar: 987, 12 345, 49.8 k, 1.20 M."""
    if x >= 1e6:
        return f'{x / 1e6:.3g} M'
    if x >= 1e5:
        return f'{x / 1e3:.3g} k'
    return f'{int(round(x)):,}'.replace(',', ' ')


def _pct(x, N):
    """x sobre N, en % con las cifras que importan: 12 %, 4.2 %, 0.50 %."""
    if N <= 0:
        return ''
    v = 100.0 * x / N
    return f'{v:.0f} %' if v >= 10 else f'{v:.1f} %' if v >= 1 else f'{v:.2f} %'


class Franja(QWidget):
    """Lo común: el estado de los bloques, el ratón y los ayudantes de dibujo."""

    etapa_elegida = pyqtSignal(str)

    # clave -> texto del tooltip de cada bloque
    AYUDA = {}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._resaltada = None
        self._marcadas = set()
        self._ocultas = set()
        self._cajas = {}                  # clave -> QRectF, del último pintado
        self.setFixedHeight(self._alto())

    # ---------- lo que la pestaña le dice ----------

    def resaltar(self, clave):
        if clave != self._resaltada:
            self._resaltada = clave
            self.update()

    def marcar(self, claves):
        claves = set(claves)
        if claves != self._marcadas:
            self._marcadas = claves
            self.update()

    def ocultar(self, claves):
        """Las etapas que el bitstream no trae: se dibujan apagadas."""
        self._ocultas = set(claves)
        self.update()

    @property
    def resaltada(self):
        return self._resaltada

    @property
    def marcadas(self):
        return set(self._marcadas)

    @property
    def ocultas(self):
        return set(self._ocultas)

    # ---------- medidas ----------

    def _fuentes(self):
        f_tit = QFont(self.font())
        f_tit.setBold(True)
        f_chico = QFont(self.font())
        f_chico.setPointSizeF(max(6.5, self.font().pointSizeF() - 1.5))
        return f_tit, f_chico

    def _alto(self):
        raise NotImplementedError

    def _reajustar(self):
        self.setFixedHeight(self._alto())
        self.update()

    def changeEvent(self, ev):
        if ev.type() == ev.FontChange:
            self.setFixedHeight(self._alto())
        super().changeEvent(ev)

    def sizeHint(self):
        sh = super().sizeHint()
        sh.setHeight(self._alto())
        return sh

    def resizeEvent(self, ev):
        # Las cajas se recalculan acá también: el ratón las usa antes del primer
        # pintado (y sin pantalla, como en las pruebas, no hay pintado).
        self._geometria()
        super().resizeEvent(ev)

    def _geometria(self):
        raise NotImplementedError

    def caja(self, clave):
        """El rectángulo de un bloque, con la geometría del ancho actual."""
        self._geometria()
        return self._cajas.get(clave)

    # ---------- el ratón ----------

    def _etapa_en(self, pos):
        for clave, r in self._cajas.items():
            if r.contains(QPointF(pos)):
                return clave
        return None

    def mousePressEvent(self, ev):
        clave = self._etapa_en(ev.pos())
        if clave is not None and clave not in self._ocultas:
            self.etapa_elegida.emit(clave)

    def mouseMoveEvent(self, ev):
        clave = self._etapa_en(ev.pos())
        self.setCursor(Qt.PointingHandCursor if clave and clave not in self._ocultas
                       else Qt.ArrowCursor)
        if clave and clave in self.AYUDA:
            QToolTip.showText(ev.globalPos(), self.AYUDA[clave], self)
        else:
            QToolTip.hideText()

    # ---------- ayudantes de dibujo ----------

    def _texto(self):
        return self.palette().windowText().color()

    @staticmethod
    def _flecha(p, x1, y1, x2, y2, color, grosor=1.3, punteada=False):
        pen = QPen(color, grosor)
        if punteada:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        dx, dy = x2 - x1, y2 - y1
        L = max(1e-6, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / L, dy / L
        a, b = 7.0, 3.5
        p.setPen(QPen(color, grosor))
        p.setBrush(color)
        p.drawPolygon(QPolygonF([
            QPointF(x2, y2),
            QPointF(x2 - a * ux - b * uy, y2 - a * uy + b * ux),
            QPointF(x2 - a * ux + b * uy, y2 - a * uy - b * ux)]))
        p.setBrush(Qt.NoBrush)

    @staticmethod
    def _rotulo(p, fuente, x, y_base, s, color, centro=True, ancho_max=None):
        fm = QFontMetrics(fuente)
        p.setFont(fuente)
        p.setPen(color)
        if ancho_max is not None:
            s = fm.elidedText(s, Qt.ElideRight, int(ancho_max))
        w = fm.horizontalAdvance(s)
        p.drawText(QPointF(x - w / 2 if centro else x, y_base), s)

    def _bloque(self, p, clave, titulo, desc, color, r, f_tit, f_chico):
        """Un bloque: el color de su función, el título, dos líneas de qué hace; el
        borde grueso si está resaltado y un punto naranja si está marcado."""
        fmt, fmc = QFontMetrics(f_tit), QFontMetrics(f_chico)
        apagada = clave in self._ocultas
        resaltada = clave == self._resaltada and not apagada
        p.setPen(QPen(QColor(20, 20, 20) if resaltada else QColor(90, 90, 90),
                      3.0 if resaltada else 1.0))
        p.setBrush(QColor(240, 240, 240) if apagada else color)
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
        p.setBrush(Qt.NoBrush)
        tinta = QColor(150, 150, 150) if apagada else QColor(Qt.black)
        p.setFont(f_tit)
        p.setPen(tinta)
        t = fmt.elidedText(titulo, Qt.ElideRight, int(r.width() - 8))
        y = r.top() + 5 + fmt.ascent()
        p.drawText(QPointF(r.center().x() - fmt.horizontalAdvance(t) / 2, y), t)
        p.setFont(f_chico)
        for k, linea in enumerate(desc.split('\n')[:2]):
            t = fmc.elidedText(linea, Qt.ElideRight, int(r.width() - 8))
            p.drawText(QPointF(r.center().x() - fmc.horizontalAdvance(t) / 2,
                               y + fmt.descent() + 2 + fmc.ascent() + fmc.height() * k), t)
        if clave in self._marcadas:
            p.setPen(QPen(Qt.white, 1.5))
            p.setBrush(NARANJA_MARCA)
            p.drawEllipse(QPointF(r.right() - 3, r.top() + 3), 6.5, 6.5)
            p.setBrush(Qt.NoBrush)

    @staticmethod
    def _leyenda(p, fuente, x, y_base, ancho, filas):
        """Filas de tramos (texto, color), una debajo de otra desde `y_base`. Lo que
        no entra en `ancho` se corta con «…»."""
        fm = QFontMetrics(fuente)
        p.setFont(fuente)
        for k, tramos in enumerate(filas):
            xx, y = x, y_base + k * fm.height()
            for s, color in tramos:
                libre = x + ancho - xx
                if libre <= 4:
                    break
                s2 = fm.elidedText(s, Qt.ElideRight, int(libre))
                p.setPen(color)
                p.drawText(QPointF(xx, y), s2)
                xx += fm.horizontalAdvance(s2)
                if s2 != s:
                    break
