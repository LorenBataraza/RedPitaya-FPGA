#!/usr/bin/env python3
"""La base de las pestañas de configuración que van por etapas, con una franja arriba.

Cada grupo de controles pertenece a una etapa de la franja (`self.diagrama`, una
`Franja`), y su título lleva el color del bloque. El grupo con el foco o con el ratón
encima se resalta en la franja y en el grupo; un clic en un bloque lleva el foco al
primer control de su etapa. La usan la del MCA (`panel_config_mca.py`) y la del OSC
(`panel_config_osc.py`).

Los grupos se arman con `_grupo(etapa, título)`; los que arma otro panel (los del
ring) se suman con `_adoptar(grupo, etapa)`, y `_reasignar` los cambia de etapa.
"""

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QApplication, QFormLayout, QGroupBox, QWidget

from app.widgets_config import PanelCampos


def css_grupo(nombre, color, resaltado):
    borde = '2px solid #333' if resaltado else '1px solid #b4b4b4'
    return (f'QGroupBox#{nombre} {{ border: {borde}; border-left: 6px solid '
            f'{color.name()}; border-radius: 3px; margin-top: 1.3em; '
            f'padding-top: 4px; }}'
            f'QGroupBox#{nombre}::title {{ subcontrol-origin: margin; left: 10px; '
            f'padding: 1px 6px; background: {color.name()}; color: black; '
            f'border-radius: 2px; }}')


class PanelPorEtapas(PanelCampos):
    """`COLOR` (etapa -> QColor) lo pone la subclase; `self.diagrama` y, si hay,
    `self.scroll` también, antes de armar los grupos."""

    COLOR = {}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.diagrama = None
        self.scroll = None
        self._grupos = {}              # etapa -> [QGroupBox]
        self._etapa_de = {}            # campo -> etapa
        self._etapa_grupo = None       # la del grupo que se está armando
        self._foco = None              # la etapa del control con el foco
        self._raton = None             # la del grupo bajo el ratón
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._al_cambiar_foco)

    # ---------- los grupos ----------

    @staticmethod
    def _forma(g):
        """QFormLayout compacto que NO estira los campos a todo el ancho.

        Con la política por defecto un QSpinBox de cuatro dígitos ocupa 1100 px y la
        columna de etiquetas queda pegada al borde izquierdo, separada de su valor
        por medio panel. Compacto, para que todos los grupos entren sin scroll.
        """
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setVerticalSpacing(3)
        f.setContentsMargins(8, 4, 8, 4)
        return f

    def _grupo(self, etapa, titulo):
        """Un grupo de la etapa `etapa`: el título con su color, y los campos que se
        registren mientras se arma quedan asociados a ella (`_registrar`)."""
        g = QGroupBox(titulo)
        self._adoptar(g, etapa)
        self._etapa_grupo = etapa
        return g

    def _adoptar(self, g, etapa):
        n = sum(len(v) for v in self._grupos.values())
        g.setObjectName(f'g_{etapa}_{n}')
        g.setProperty('etapa', etapa)
        g.setStyleSheet(css_grupo(g.objectName(), self.COLOR[etapa], False))
        g.installEventFilter(self)
        self._grupos.setdefault(etapa, []).append(g)
        return g

    def _reasignar(self, g, etapa):
        """El grupo pasa a otra etapa (el estímulo del ring: el disparo o el
        generador)."""
        vieja = g.property('etapa')
        if vieja == etapa:
            return
        if g in self._grupos.get(vieja, []):
            self._grupos[vieja].remove(g)
        g.setProperty('etapa', etapa)
        self._grupos.setdefault(etapa, []).append(g)
        if self._raton == vieja:
            self._raton = etapa
        self._pintar_resaltado()

    def _registrar(self, campo, w, leer, escribir, cuando, ayuda):
        self._etapa_de[campo] = self._etapa_grupo
        return super()._registrar(campo, w, leer, escribir, cuando, ayuda)

    def _texto_con_marca(self, campo, texto):
        """La etiqueta de un campo con la marca de su clase (casillas aparte: la
        lleva el texto de la casilla)."""
        return texto + self.MARCAS[self._cuando[campo]]

    # ---------- foco, ratón y clic ----------

    def _etapa_de_widget(self, w):
        while w is not None and w is not self:
            etapa = w.property('etapa')
            if etapa:
                return etapa
            w = w.parentWidget()
        return None

    def _al_cambiar_foco(self, _viejo, nuevo):
        self._foco = self._etapa_de_widget(nuevo) if nuevo is not None else None
        self._pintar_resaltado()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Enter:
            self._raton = obj.property('etapa')
            self._pintar_resaltado()
        elif ev.type() == QEvent.Leave and self._raton == obj.property('etapa'):
            self._raton = None
            self._pintar_resaltado()
        return False

    def _pintar_resaltado(self):
        etapa = self._raton or self._foco
        if self.diagrama is not None:
            self.diagrama.resaltar(etapa)
        for clave, grupos in self._grupos.items():
            for g in grupos:
                g.setStyleSheet(css_grupo(g.objectName(), self.COLOR[clave],
                                          clave == etapa))

    def _ir_a_etapa(self, etapa):
        """Clic en un bloque: el foco al primer control habilitado de su etapa."""
        for g in self._grupos.get(etapa, ()):
            if g.isHidden():
                continue
            if self.scroll is not None:
                self.scroll.ensureWidgetVisible(g)
            for w in g.findChildren(QWidget):
                if (w.isEnabled() and w.isVisibleTo(g)
                        and w.focusPolicy() & Qt.TabFocus):
                    w.setFocus(Qt.OtherFocusReason)
                    break
            # El resaltado no espera al foco: con la ventana inactiva no llega.
            self._foco = etapa
            self._pintar_resaltado()
            return
