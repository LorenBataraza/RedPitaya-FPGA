#!/usr/bin/env python3
"""Pestaña de configuración del MCA: los registros del slot 7, agrupados.

Es la vista completa de lo que `mca_configure()` sabe escribir, pero campo por
campo: escribir el bloque entero pone `run=0` en `R_CTRL`, o sea que tocar un
umbral pararía la medición en curso. Cada control escribe SOLO su campo, con
read-modify-write.

El umbral y la ventana de amplitud siguen estando también en la pestaña del
espectro, a propósito: son los dos que se tocan mirando el histograma. Acá están
otra vez porque ésta es la vista completa, y los dos controles se mantienen
sincronizados solos — los dos reciben `actualizar_config` del mismo hardware.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from API.mca import AMP_W, FEATURES, mca_amplitud_de_canal
from app.widgets_config import CALIENTE, CORTA, INVALIDA, RIESGO, PanelCampos

# Las features que pueden alimentar un eje, en el orden en que conviene verlas.
# Sale de FEATURES de API/mca.py para no tener una segunda lista que se
# desincronice; el orden se fija acá.
_ORDEN_FEATURES = ('pico', 'integral', 'psd', 'ancho_inv', 'largo', 't_subida')


def _opciones_features():
    conocidas = [(n, FEATURES[n]) for n in _ORDEN_FEATURES if n in FEATURES]
    # Si alguna vez FEATURES crece, aparece igual en vez de quedar invisible.
    conocidas += [(n, v) for n, v in sorted(FEATURES.items(), key=lambda kv: kv[1])
                  if n not in _ORDEN_FEATURES]
    return conocidas


class PanelConfigMCA(PanelCampos):

    # `pedir_campo` y `log` los hereda de PanelCampos; ésta es propia porque el
    # borrado no es un campo de configuración sino una acción.
    pedir_clear = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.h_aw = 13
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        interior = QWidget()
        v = QVBoxLayout(interior)
        v.addWidget(self._grupo_disparo())
        v.addWidget(self._grupo_linea_base())
        v.addWidget(self._grupo_ventana_temporal())
        v.addWidget(self._grupo_estimador())
        v.addWidget(self._grupo_eje())
        v.addWidget(self._grupo_discriminador())
        v.addWidget(self._grupo_entrada())
        v.addWidget(self._leyenda())
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(scroll)

    @staticmethod
    def _forma(g):
        """QFormLayout que NO estira los campos a todo el ancho.

        Con la política por defecto un QSpinBox de cuatro dígitos ocupa 1100 px
        y la columna de etiquetas queda pegada al borde izquierdo, separada de
        su valor por medio panel.
        """
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f.setLabelAlignment(Qt.AlignRight)
        return f

    def _grupo_disparo(self):
        g = QGroupBox('Disparo')
        f = self._forma(g)
        f.addRow('umbral (cuentas)', self._spin(
            'thr', 0, 0x3FFF, CALIENTE,
            'Umbral sobre la línea de base. 14 bits con signo.'))
        f.addRow('histéresis', self._spin(
            'hyst', 0, 0x3FFF, CALIENTE,
            'La ventana cierra al bajar de thr − hyst. Evita que el ruido '
            'alrededor del umbral parta un pulso en varios.'))
        return g

    def _grupo_linea_base(self):
        g = QGroupBox('Línea de base')
        f = self._forma(g)
        f.addRow(self._check(
            'bl_auto', 'seguidor automático', RIESGO,
            'Con el seguidor apagado se usa el valor fijo de abajo, que es '
            'inmune al problema de bl_k.'))
        f.addRow('bl_k (τ = 2^k muestras)', self._spin(
            'bl_k', 0, 15, RIESGO,
            'La constante tiene que ser MUCHO más larga que el pulso: si es '
            'comparable, el seguidor persigue el pulso y lo borra antes de que '
            'cruce el umbral, y no se detecta NADA.\n'
            'Medido en placa con un pulso de 62 us:\n'
            '    bl_k=6  (τ=0.5 us)  ->      0 eventos\n'
            '    bl_k=9  (τ=4.1 us)  ->   2002 eventos\n'
            '    bl_k=12 (τ=32.8 us) ->   2001 eventos\n'
            'Regla: τ >= 100x la duración del pulso.'))
        f.addRow('holdoff', self._spin(
            'bl_holdoff', 0, 0xFFFF, CALIENTE,
            'Muestras que el seguidor ignora después de un pulso, para no '
            'aprender del propio pulso.'))
        f.addRow('base fija (cuentas)', self._spin(
            'baseline', 0, 0x3FFF, CALIENTE,
            'Sólo se usa con el seguidor automático apagado.'))
        return g

    def _grupo_ventana_temporal(self):
        g = QGroupBox('Ventana temporal')
        f = self._forma(g)
        f.addRow('maxlen (muestras)', self._spin(
            'maxlen', 1, 0xFFFF, CORTA,
            'Largo máximo de la ventana de un evento. Al llegar, el evento se '
            'cierra y cuenta como APILAMIENTO: no entra al histograma.\n'
            'Si ves todo en cnt_pileup y nada en accepted, el pulso es más '
            'largo que esto.'))
        f.addRow('tail_dly (muestras)', self._spin(
            'tail_dly', 1, 0xFFFF, CORTA,
            'Muestras desde el pico hasta que arranca la integral de cola. '
            'Tiene que ser >= 1: con 0, Q_cola == Q_total y el RTL lo rechaza.'))
        f.addRow(self._check(
            'gate_mode', 'compuertas de largo fijo', CORTA,
            'Apagado: la ventana la define la histéresis. Encendido: dos '
            'compuertas de largo fijo (las de abajo).'))
        f.addRow('compuerta corta', self._spin(
            'gate_short', 0, 0xFFFF, CORTA, 'Sólo con compuertas fijas.'))
        f.addRow('compuerta larga', self._spin(
            'gate_long', 0, 0xFFFF, CORTA, 'Sólo con compuertas fijas.'))
        return g

    def _grupo_estimador(self):
        g = QGroupBox('Estimador de amplitud')
        f = self._forma(g)
        f.addRow(self._check(
            'amp_src', 'usar integral de carga', INVALIDA,
            'Apagado: la muestra de pico. Encendido: Q_total >> q_shift.\n'
            'La integral promedia el ruido blanco como sigma/sqrt(N) y es '
            'inmune al jitter de muestreo del pico; con la muestra de pico la '
            'amplitud sale de UNA muestra y el muestreo casi nunca cae en el '
            'máximo real.\n'
            'OJO: escribir este registro también mueve el selector del eje 1D, '
            'por compatibilidad con la campaña vieja.'))
        f.addRow('q_shift', self._spin(
            'q_shift', 0, 31, INVALIDA,
            'Divide la integral para que entre en el eje. Sólo con la integral.'))
        f.addRow('decimación', self._spin(
            'dec', 1, 0xFFFF, CORTA,
            'Decimación propia del MCA. 1 = sin decimar.'))
        return g

    def _grupo_eje(self):
        g = QGroupBox('Eje del histograma')
        f = self._forma(g)
        f.addRow('qué mide el eje 1D', self._combo(
            'sel_1d', _opciones_features(), INVALIDA,
            'Qué feature del pulso alimenta el espectro.\n'
            'Es el registro que agarró un bug del RTL en simulación: con el mux '
            'mal, TODO el espectro cae en el canal 0 sin ningún error.'))
        f.addRow('zoom (z)', self._spin(
            'zoom_1d_z', 0, 4, INVALIDA,
            'La ventana del eje es 2^-z del fondo de escala. z=0 es fondo de '
            'escala entero.\n'
            'NO mejora la resolución: sólo recupera la pérdida por binning, que '
            'ya es menor al 0.6 %. Sirve para encuadrar el eje sobre dos picos '
            'juntos, y para poder usar un histograma más chico sin ceder nada.\n'
            'Y la deriva empeora 2^z COMO FRACCIÓN DE LA VENTANA: con z=3 un '
            'corrimiento del 6.45 % mueve el pico un 41 % del ancho.'))
        f.addRow('ventana (k)', self._spin(
            'zoom_1d_k', 0, 255, INVALIDA,
            'Cuál de las 2^z ventanas se mira. Con z=0 no se usa.'))
        self.lbl_rango = QLabel('—')
        self.lbl_rango.setTextFormat(Qt.PlainText)
        f.addRow('rango del eje', self.lbl_rango)
        f.addRow(self._check(
            'keep_if_full', 'seguir contando con el bin lleno', CALIENTE,
            'Apagado: los eventos que caen en un bin saturado NO se cuentan, y '
            'se acumulan aparte en cnt_full_supp.'))
        return g

    def _grupo_discriminador(self):
        g = QGroupBox('Discriminador')
        f = self._forma(g)
        f.addRow(self._check(
            'discr_en', 'activo', CALIENTE,
            'Rechaza eventos por una feature elegida. Lo que rechaza se cuenta '
            'aparte en cnt_rej_discr, separado de cnt_rej_amp: son criterios '
            'distintos y hay que poder atribuir la pérdida a cada uno.'))
        f.addRow('sobre qué feature', self._combo(
            'discr_sel', _opciones_features(), CALIENTE))
        f.addRow('mínimo', self._spin('discr_min', 0, 0xFFFF, CALIENTE))
        f.addRow('máximo', self._spin('discr_max', 0, 0xFFFF, CALIENTE))
        f.addRow(self._check(
            'discr_ext', 'intervalo externo (rechaza adentro)', CALIENTE,
            'Con el intervalo externo, min > max es legítimo: acepta todo. Con '
            'el interno, min > max sería un intervalo vacío y la API lo '
            'rechaza — el síntoma sería un espectro sin una sola cuenta.'))
        return g

    def _grupo_entrada(self):
        g = QGroupBox('Entrada')
        f = self._forma(g)
        f.addRow(self._check(
            'channel', 'usar IN2 (en vez de IN1)', CORTA,
            'Hay UN solo MCA con un mux de canal, no dos MCA independientes.'))
        return g

    def _leyenda(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 4, 0, 0)
        for texto in (
                'Sin marca: se puede cambiar midiendo.',
                '·  reinicia la cuenta en curso.',
                '··  cambia el significado del eje: conviene borrar después.',
                '⚠  mal puesto, deja el sistema sin eventos.'):
            e = QLabel(texto)
            e.setStyleSheet('color: #888;')
            v.addWidget(e)

        fila = QHBoxLayout()
        self.btn_borrar = QPushButton('Borrar el histograma')
        self.btn_borrar.setToolTip(
            'Después de cambiar algo marcado con ·· , para no mezclar dos ejes '
            'en el mismo histograma.')
        self.btn_borrar.clicked.connect(self.pedir_clear.emit)
        fila.addWidget(self.btn_borrar)
        fila.addStretch(1)
        v.addLayout(fila)
        return w

    # =========================================================================
    # Estado
    # =========================================================================

    def configurar_geometria(self, n_canales, h_aw=None):
        self.h_aw = int(h_aw) if h_aw is not None else \
            max(1, int(n_canales)).bit_length() - 1
        # El zoom no puede pasar de AMP_W - h_aw: más allá no quedan bits que
        # rebanar y el RTL lo satura en silencio. Se acota el control para que
        # no se pueda pedir algo que el hardware va a recortar.
        z_max = max(0, AMP_W - self.h_aw)
        self._controles['zoom_1d_z'][0].setMaximum(z_max)
        self._refrescar_rango()

    def actualizar_config(self, cfg):
        super().actualizar_config(cfg)
        if cfg.get('h_aw') is not None:
            self.configurar_geometria(1 << int(cfg['h_aw']), int(cfg['h_aw']))
        self._refrescar_rango()

    def _refrescar_rango(self):
        """Qué amplitudes cubre el eje con el zoom actual.

        Sin esto, `z` y `k` son dos números sin unidades y no hay forma de saber
        qué ventana se está mirando sin hacer la cuenta a mano.
        """
        z = self._controles['zoom_1d_z'][1]()
        k = self._controles['zoom_1d_k'][1]()
        lo = mca_amplitud_de_canal(0, self.h_aw, z, k)
        hi = mca_amplitud_de_canal((1 << self.h_aw) - 1, self.h_aw, z, k)
        ancho = (hi - lo) / max(1, (1 << self.h_aw) - 1)
        self.lbl_rango.setText(
            f'{lo} … {hi} cuentas   ({1 << self.h_aw} canales, '
            f'{ancho:.1f} cuentas/canal)')
