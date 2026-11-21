#!/usr/bin/env python3
"""Pestaña «Calibration»: el canal analógico y la base dinámica del MCA.

En el modo analógico las líneas del MCA se corren con la tasa: los polos lentos del
canal dejan una cola negativa detrás de cada pulso, las colas se apilan y bajan la base
(docs/resultados_meritos_gen_pulsos.md §2.5). Esta pestaña lo mide y lo compensa:

1. **Reference / Measure** (`canal.medir`): el canal con la BRAM, con el generador por
   OUT1 (la medición rápida a ritmo pleno y la lenta diezmada) o con una cuadrada de
   afuera en IN1. Todo lo que la medición toca (el generador, la BRAM, el disparo) se
   restaura al terminar. «Repeatability» mide dos veces y compara IN1 contra el ruido:
   una T floja da cientos de cuentas.
2. **Results**: el canal (offset, ruido, ganancia, caída lenta, latencia, subida,
   −3 dB, residuo, diafonía), y «Save…/Load…» en la PC (.json y .npz).
3. **Origin**: una fila por medición, con un rótulo del conexionado. Comparar
   OUT1 → T 50 Ω → IN1, OUT1 → IN1 sin carga y la cuadrada externa dice de dónde es la
   caída: si la externa no cae, es de la salida cargada y con un sensor no hay que
   compensarla (`veredicto`).
4. **MCA base**: b0 = el offset medido, y la base dinámica (`base.dinamica`, la corre
   el servidor): b0 + κ·caída·(λ̂/f_s)·⟨A⟩·τ, con la caída de la fila elegida y G_F, la
   ganancia del MCA en cuentas de la feature por ADU (`mca.ganancia`, con el lazo
   digital). «Check» (`base.verificar`) corre el generador por OUT1 con la base fija y
   con la dinámica y da el κ que anula el corrimiento.

A la derecha, la respuesta al escalón (rápida y lenta, con una curva por fila de
Origin), |H(f)|, la densidad del piso y Δb en el tiempo.

Docs: docs/APP/calibracion.md.
"""

import json
import time
from collections import deque

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
                             QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit,
                             QPushButton, QSizePolicy, QSpinBox, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from API import canal as C
from app.diagrama_cal import COLOR, DiagramaCal, pct
from app.panel_etapas import PanelPorEtapas

ROJO = '#c0392b'
FS_HZ = 125e6
HISTORIA_S = 60.0
# Qué conexión va con cada referencia, a la vista.
CONEXION = {
    'generador': 'OUT1 → T (50 Ω) → IN1, IN1 jumper on LV, the MCA stopped.',
    'externa': 'A square of ~2 kHz, ~0.5 Vpp → T (50 Ω) → IN1, OUT1 off: gives the '
               'drop of IN1 alone.',
}
ROTULO = {'generador': 'OUT1→T50→IN1', 'externa': 'external→T50→IN1'}
CAIDA_CHICA = 0.01       # por debajo de 1 %, no hay caída que compensar


def veredicto(filas):
    """Qué dicen las filas de Origin sobre de dónde es la caída lenta."""
    ext = [f for f in filas if f['referencia'] == 'externa']
    gen = [f for f in filas if f['referencia'] == 'generador']
    if not ext or not gen:
        return ('Measure OUT1 loaded, OUT1 unloaded and an external square: the rows '
                'tell where the drop comes from.')
    e = float(np.median([f['caida'] for f in ext]))
    g = float(np.median([f['caida'] for f in gen]))
    cifras = f'IN1 alone {pct(e)}, OUT1 + IN1 {pct(g)}: '
    if abs(e) < CAIDA_CHICA <= abs(g):
        return cifras + ('the drop is of the loaded output. With a sensor there is '
                         'nothing to compensate.')
    if abs(e) >= CAIDA_CHICA and abs(g - e) <= 0.3 * abs(g):
        return cifras + 'the drop is of the IN1 front-end. With a sensor, use the external row.'
    return cifras + 'both contribute. With a sensor, use the external row.'


def fila_de(res, rotulo):
    """Una fila de Origin desde un `canal.medir`. Con la referencia externa la
    ganancia no tiene escala (el escalón ideal es de 1000): no se muestra, pero `g`
    queda para dibujar la caída."""
    lento = res.get('lento') or {}
    if lento:
        d, lentos, g = lento['d'], lento['lentos'], lento['ganancia']
    else:
        d, lentos, g = res.get('fir_lentos', []), res.get('lentos', []), res.get('ganancia')
    ref = res.get('referencia', 'generador')
    return dict(rotulo=str(rotulo), referencia=ref,
                caida=float(res.get('caida_lenta_usar', 0.0)),
                ganancia=None if g is None or ref == 'externa' else float(g),
                g=None if g is None else float(g), d=[float(v) for v in d],
                lentos=[float(t) for t in lentos], t=res.get('t_medida', time.time()))


class PanelCalibracion(PanelPorEtapas):
    """El canal medido, las filas de Origin y la base dinámica."""

    COLOR = COLOR

    pedir_medir = pyqtSignal(dict)          # canal.medir
    pedir_ganancia = pyqtSignal(dict)       # mca.ganancia
    pedir_base = pyqtSignal(dict)           # base.dinamica
    pedir_verificar = pyqtSignal(dict)      # base.verificar
    pedir_campo_mca = pyqtSignal(str, int)  # la base fija (b0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._res = None             # el último canal.medir con el generador
        self._caps = {}
        self._ext = None             # el último con la referencia externa
        self._caps_ext = {}
        self._repetir = None         # None, 'primera' o 'segunda' («Repeatability»)
        self._y_primera = None       # IN1 de la primera de las dos
        self._filas = []             # Origin
        self._ganancia = None        # el último mca.ganancia
        self._cfg = None             # la última config del MCA
        self._base = None            # el último base_dinamica del status
        self._verificacion = None
        self._hist = deque()         # (t, Δb, λ̂) de la base dinámica
        self._hay_gen = True
        self._conectado = False
        self._t_dibujo = 0.0
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        self.diagrama = DiagramaCal()
        self.diagrama.etapa_elegida.connect(self._ir_a_etapa)

        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 0, 0)
        for grupos in ((self._grupo_referencia(), self._grupo_medida(),
                        self._grupo_origen()),
                       (self._grupo_resultados(), self._grupo_base())):
            v = QVBoxLayout()
            for g in grupos:
                v.addWidget(g)
            v.addStretch(1)
            cols.addLayout(v, 1)
        cols.addWidget(self._graficos(), 1)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.addWidget(self.diagrama)
        caja.addLayout(cols, 1)

    def _forma_ancha(self, g):
        """Un formulario cuyos valores ocupan el ancho que queda (y se parten en
        renglones ahí), en vez de quedarse en su tamaño sugerido."""
        f = self._forma(g)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        return f

    @staticmethod
    def _dato(texto='—'):
        """Un valor que se parte en renglones en vez de ensanchar la columna."""
        lbl = QLabel(texto)
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lbl.setMinimumWidth(60)
        return lbl

    @staticmethod
    def _fila(*ws):
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        for w in ws:
            h.addWidget(w)
        h.addStretch(1)
        return h

    def _grupo_referencia(self):
        g = self._grupo('referencia', 'Reference')
        f = self._forma(g)
        self.cmb_ref = QComboBox()
        self.cmb_ref.addItem('generator via OUT1', 'generador')
        self.cmb_ref.addItem('external square on IN1', 'externa')
        self.cmb_ref.currentIndexChanged.connect(self._cambio_referencia)
        f.addRow('reference', self.cmb_ref)
        self.cmb_que = QComboBox()
        self.cmb_que.addItem('fast + slow', 'todo')
        self.cmb_que.addItem('fast only (65 µs)', 'rapido')
        self.cmb_que.addItem('slow only (decimated)', 'lento')
        self.cmb_que.setToolTip('Fast: full rate, the FIR, the noise floor and the '
                                'crosstalk; one capture is 1.3 times the slowest pole. '
                                'Slow: quasi-steps decimated by 8 (~0.5 ms), the slow '
                                'drop well determined.')
        f.addRow('measure', self.cmb_que)
        self.spn_prom = QSpinBox(minimum=1, maximum=16, value=4)
        self.spn_prom.setToolTip('Captures without the loopback (or external) in the '
                                 'slow fit: the noise averages down as 1/√n.')
        self.spn_semilla = QSpinBox(minimum=1, maximum=1 << 30, value=1)
        f.addRow(self._fila(QLabel('captures'), self.spn_prom, QLabel('seed'),
                            self.spn_semilla))
        self.lbl_conexion = self._nota(CONEXION['generador'])
        self.lbl_conexion.setMinimumHeight(2 * self.lbl_conexion.fontMetrics().height())
        f.addRow(self.lbl_conexion)
        return g

    def _grupo_medida(self):
        g = self._grupo('canal', 'Measure')
        f = self._forma_ancha(g)
        self.ed_rotulo = QLineEdit(ROTULO['generador'])
        self.ed_rotulo.setToolTip('How it is connected: it labels the row in Origin.')
        f.addRow('connection', self.ed_rotulo)
        self.btn_medir = QPushButton('Measure')
        self.btn_medir.clicked.connect(self._medir)
        self.btn_repetir = QPushButton('Repeatability')
        self.btn_repetir.setToolTip('Measures twice (fast only) and compares IN1 of the '
                                    'two: with a stable connection the difference is '
                                    'the noise (√2 σ).')
        self.btn_repetir.clicked.connect(self._repetibilidad)
        f.addRow(self._fila(self.btn_medir, self.btn_repetir))
        self.lbl_estado = self._dato()
        f.addRow('status', self.lbl_estado)
        self.lbl_repet = self._dato()
        self.lbl_repet.hide()                # hasta que haya un resultado
        f.addRow(self.lbl_repet)
        self.lbl_error = self._nota('', ROJO)
        f.addRow(self.lbl_error)
        return g

    def _grupo_origen(self):
        g = self._grupo('modelo', 'Origin of the slow drop')
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 4)
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(['connection', 'slow drop', 'gain'])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.Stretch)
        for j in (1, 2):
            cab.setSectionResizeMode(j, QHeaderView.ResizeToContents)
        self.tabla.verticalHeader().setDefaultSectionSize(
            self.tabla.fontMetrics().height() + 4)
        fila = self.tabla.fontMetrics().height() + 4
        self.tabla.setMinimumHeight(3 * fila + 6)       # la cabecera y dos filas
        self.tabla.setMaximumHeight(4 * fila + 6)
        v.addWidget(self.tabla)
        self.btn_borrar_filas = QPushButton('Clear rows')
        self.btn_borrar_filas.clicked.connect(self._borrar_filas)
        v.addLayout(self._fila(self.btn_borrar_filas))
        self.lbl_veredicto = self._nota(veredicto([]))
        v.addWidget(self.lbl_veredicto)
        return g

    def _grupo_resultados(self):
        g = self._grupo('modelo', 'Results')
        f = self._forma_ancha(g)
        self._lbl = {}
        for clave, texto, ayuda in (
                ('piso', 'offset, σ', 'IN1 without pulses: the base at zero rate and '
                 'the noise, in counts.'),
                ('ganancia', 'gain fast, DC', 'Σc (what a pulse sees) and Σc + Σd.'),
                ('caida', 'slow drop', 'Σd/Σc: how much the step drops after the FIR.'),
                ('polos', 'per pole', 'The drop of each slow pole, with its τ.'),
                ('latencia', 'latency, ASG', 'Group delay of the FIR in samples, and '
                 'how many samples the MCA window has to move with the ASG trigger.'),
                ('subida', 'rise, overshoot, BW', '10-90 % rise, overshoot of the '
                 'step and the −3 dB bandwidth.'),
                ('residuo', 'residual, IN2', 'rms of y − model (without the slow '
                 'poles in parentheses), and the crosstalk to IN2.')):
            lbl = self._dato()
            lbl.setToolTip(ayuda)
            self._lbl[clave] = lbl
            f.addRow(texto, lbl)
        self.btn_guardar = QPushButton('Save…')
        self.btn_guardar.clicked.connect(self._guardar_dialogo)
        self.btn_cargar = QPushButton('Load…')
        self.btn_cargar.clicked.connect(self._cargar_dialogo)
        f.addRow(self._fila(self.btn_guardar, self.btn_cargar))
        return g

    def _grupo_base(self):
        g = self._grupo('base', 'MCA base')
        f = self._forma_ancha(g)
        self.btn_b0 = QPushButton('Set b0 = offset')
        self.btn_b0.setToolTip('Writes the measured IN1 offset as the fixed base of '
                               'the MCA: the base at zero rate.')
        self.btn_b0.clicked.connect(self._poner_b0)
        self.lbl_b0 = self._dato()
        f.addRow(self.btn_b0, self.lbl_b0)

        self.chk_din = QCheckBox('dynamic base')
        self.chk_din.setToolTip('The server moves the fixed base every 250 ms by '
                                'κ·drop·(λ/f_s)·⟨A⟩·τ. It keeps running if the GUI '
                                'disconnects.')
        self.chk_din.toggled.connect(self._alternar_dinamica)
        self.cmb_fuente = QComboBox()
        self.cmb_fuente.setToolTip('Which measured drop the dynamic base uses: the '
                                   'external one (IN1 alone) for a sensor, OUT1 + IN1 '
                                   'for the generator via OUT1.')
        self.cmb_fuente.currentIndexChanged.connect(self._reaplicar)
        f.addRow(self._fila(self.chk_din, QLabel('drop from'), self.cmb_fuente))
        self.spn_kappa = QDoubleSpinBox(decimals=3, minimum=0.0, maximum=3.0, value=1.0,
                                        singleStep=0.05)
        self.spn_kappa.setKeyboardTracking(False)
        self.spn_kappa.valueChanged.connect(self._reaplicar)
        self.lbl_tau = QLabel('τ —')
        f.addRow('κ', self._fila(self.spn_kappa, self.lbl_tau))

        self.lbl_gf = QLabel('—')
        self.btn_gf = QPushButton('Measure')
        self.btn_gf.setToolTip('One isolated line of the generator through the DIGITAL '
                               'loopback (no cables), with the pole-zero τ of the MCA. '
                               'CLEARS the spectrum.')
        self.btn_gf.clicked.connect(self._medir_ganancia)
        f.addRow('G_F', self._fila(self.btn_gf, self.lbl_gf))

        self.spn_tasa = QDoubleSpinBox(decimals=0, minimum=10.0, maximum=3000.0,
                                       value=400.0, singleStep=50.0, suffix=' k/s')
        self.btn_check = QPushButton('Check')
        self.btn_check.setToolTip('The generator via OUT1 (the calibration cable) at '
                                  'this rate, with the fixed and the dynamic base, '
                                  'against the lines at 10 k/s: the shift and the κ '
                                  'that cancels it. ~8 s; CLEARS the spectrum.')
        self.btn_check.clicked.connect(self._verificar)
        self.btn_kappa = QPushButton('use κ')
        self.btn_kappa.clicked.connect(self._usar_kappa)
        self.btn_kappa.setEnabled(False)
        f.addRow('check', self._fila(self.spn_tasa, self.btn_check, self.btn_kappa))
        self.lbl_check = self._dato()
        self.lbl_check.hide()                # hasta que haya un resultado
        f.addRow(self.lbl_check)
        self.lbl_vivo = self._dato()
        f.addRow('now', self.lbl_vivo)
        self.lbl_aviso = self._nota('', ROJO)
        f.addRow(self.lbl_aviso)
        f.addRow(self._nota('G_F and Check clear the spectrum. The dynamic base fixes '
                            'the mean shift, not the fluctuation.'))
        return g

    def _graficos(self):
        self.fig = Figure(figsize=(5.6, 6.4), tight_layout=True)
        gs = self.fig.add_gridspec(3, 2, height_ratios=(1.0, 1.0, 0.7))
        self.ax_rapida = self.fig.add_subplot(gs[0, 0])
        self.ax_lenta = self.fig.add_subplot(gs[0, 1])
        self.ax_h = self.fig.add_subplot(gs[1, 0])
        self.ax_psd = self.fig.add_subplot(gs[1, 1])
        self.ax_db = self.fig.add_subplot(gs[2, :])
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumWidth(420)
        self._dibujar()
        return self.canvas

    # =========================================================================
    # Acciones
    # =========================================================================

    def _referencia(self):
        return self.cmb_ref.currentData()

    def _cambio_referencia(self, *_):
        ref = self._referencia()
        self.lbl_conexion.setText(CONEXION[ref])
        if self.ed_rotulo.text() in ROTULO.values():
            self.ed_rotulo.setText(ROTULO[ref])
        self.cmb_que.setEnabled(ref == 'generador')
        self.diagrama.set_referencia(ref)
        self._habilitar()

    def args_medir(self, que=None):
        ref = self._referencia()
        return {'referencia': ref, 'que': que or self.cmb_que.currentData(),
                'semilla': int(self.spn_semilla.value()),
                'promedios': int(self.spn_prom.value())}

    def _medir(self):
        self._repetir = self._y_primera = None
        self._pedir_medida(self.args_medir())

    def _repetibilidad(self):
        self._repetir, self._y_primera = 'primera', None
        self._pedir_medida(dict(self.args_medir('rapido'), referencia='generador'))

    def _pedir_medida(self, args):
        self.lbl_error.setText('')
        self.lbl_estado.setText('measuring…')
        self._ocupado(True)
        self.pedir_medir.emit(args)

    def _ocupado(self, si):
        self._en_curso = bool(si)
        self._habilitar()

    def _habilitar(self):
        libre = self._conectado and not getattr(self, '_en_curso', False)
        gen = libre and self._hay_gen
        self.btn_medir.setEnabled(libre and (gen or self._referencia() == 'externa'))
        self.btn_repetir.setEnabled(gen)
        self.btn_gf.setEnabled(gen and not (self._base or {}).get('on'))
        self.btn_check.setEnabled(gen and self._caida_elegida() is not None
                                  and self._gf() is not None)
        self.btn_b0.setEnabled(libre and self._res is not None and 'offset' in self._res)
        self.chk_din.setEnabled(self._conectado)

    def _borrar_filas(self):
        self._filas = []
        self._pintar_filas()

    def _poner_b0(self):
        if not self._res or 'offset' not in self._res:
            return
        b0 = int(round(self._res['offset']))
        self.pedir_campo_mca.emit('baseline', b0 & 0x3FFF)
        self.log.emit(f'baseline = {b0} (the measured IN1 offset)')

    def _gf(self):
        return None if not self._ganancia else self._ganancia.get('ganancia_mca')

    def _caida_elegida(self):
        i = self.cmb_fuente.currentIndex()
        if 0 <= i < len(self._filas):
            return self._filas[i]['caida']
        return None

    def args_base(self):
        """Lo que pide `base.dinamica` para prenderla, o ValueError con qué falta."""
        caida, gf = self._caida_elegida(), self._gf()
        if caida is None:
            raise ValueError('measure the channel first (the slow drop)')
        if gf is None:
            raise ValueError('measure G_F first (the MCA gain, digital loopback)')
        return {'on': True, 'caida': caida, 'ganancia_mca': gf,
                'kappa': float(self.spn_kappa.value())}

    def _alternar_dinamica(self, on):
        if self._cargando:
            return
        if not on:
            self.pedir_base.emit({'on': False})
            return
        try:
            args = self.args_base()
        except ValueError as e:
            self.lbl_aviso.setText(f'not on: {e}')
            self._cargando = True
            self.chk_din.setChecked(False)
            self._cargando = False
            return
        self.lbl_aviso.setText('')
        self.pedir_base.emit(args)

    def _reaplicar(self, *_):
        """Con la dinámica prendida, la fuente o κ nuevos van al servidor."""
        if self._cargando or not self.chk_din.isChecked():
            self._habilitar()
            return
        try:
            self.pedir_base.emit(self.args_base())
        except ValueError as e:
            self.lbl_aviso.setText(str(e))

    def _medir_ganancia(self):
        self.lbl_aviso.setText('')
        self.lbl_gf.setText('measuring…')
        self.pedir_ganancia.emit({'amplitud': 2000})

    def _verificar(self):
        try:
            caida, gf = self._caida_elegida(), self._gf()
            if caida is None or gf is None:
                raise ValueError('measure the channel and G_F first')
        except ValueError as e:
            self.lbl_aviso.setText(str(e))
            return
        self.lbl_check.setText('running (~8 s)…')
        self.lbl_check.show()
        self.pedir_verificar.emit({'tasa_hz': float(self.spn_tasa.value()) * 1e3,
                                   'caida': caida, 'ganancia_mca': gf,
                                   'kappa': float(self.spn_kappa.value())})

    def _usar_kappa(self):
        k = (self._verificacion or {}).get('kappa_optimo')
        if k is not None:
            self.spn_kappa.setValue(float(k))

    # =========================================================================
    # Desde el servidor
    # =========================================================================

    def mostrar_fallo(self, mensaje):
        """Un canal.medir / mca.ganancia / base.* rechazado."""
        self._ocupado(False)
        self._repetir = self._y_primera = None
        self.lbl_estado.setText('failed')
        self.lbl_error.setText(mensaje)
        if 'ganancia' in mensaje and self.lbl_gf.text() == 'measuring…':
            self.lbl_gf.setText('—')
        if self.lbl_check.text().startswith('running'):
            self.lbl_check.hide()

    def actualizar_medida(self, res, caps):
        """El resultado de `canal.medir` y sus capturas."""
        self._ocupado(False)
        if self._repetir == 'primera':
            self._repetir, self._y_primera = 'segunda', caps.get('y0')
            self.lbl_estado.setText('repeatability: second capture…')
            self._ocupado(True)
            self.pedir_medir.emit(dict(self.args_medir('rapido'), referencia='generador'))
            return
        if self._repetir == 'segunda':
            r = C.repetibilidad(self._y_primera, caps.get('y0'), res.get('ruido', 1.0))
            self._repetir = self._y_primera = None
            self.lbl_repet.show()
            self.lbl_repet.setText(
                f"repeatability: {r['rms']:.1f} rms against {r['esperado']:.1f} of noise, "
                + ('stable' if r['estable'] else 'NOT STABLE (check the T and the '
                   'terminator)'))
            self.lbl_repet.setStyleSheet('' if r['estable'] else f'color: {ROJO};')
        # La externa sólo da la caída de IN1: va a Origin y a la curva lenta, sin
        # pisar el canal medido con el generador (Results y los gráficos rápidos).
        if res.get('referencia') == 'externa':
            self._ext, self._caps_ext = dict(res), dict(caps)
        else:
            self._res, self._caps = dict(res), dict(caps)
        self._filas.append(fila_de(res, self.ed_rotulo.text() or
                                   ROTULO.get(res.get('referencia'), '?')))
        self._pintar_resultado()
        self._pintar_filas()
        self.cmb_fuente.setCurrentIndex(len(self._filas) - 1)
        self.lbl_estado.setText(f"done in {res.get('duracion_s', 0):.1f} s, everything "
                                'restored')
        self.lbl_estado.setToolTip('Restored: ' + ', '.join(res.get('restaurado') or ['—']))
        if res.get('problema'):
            self.lbl_error.setText(res['problema'])

    def actualizar_ganancia(self, info):
        self._ganancia = dict(info)
        self._pintar_gf()
        self._habilitar()

    def actualizar_verificacion(self, r):
        self._verificacion = dict(r)

        def s(x):
            return '—' if x is None else f'{x:+.2f}'
        k = r.get('kappa_optimo')
        self.lbl_check.show()
        self.lbl_check.setText(
            f"shift at {r['tasa_hz'] / 1e3:.0f} k/s: fixed {s(r.get('s_fija'))}, dynamic "
            f"{s(r.get('s_dinamica'))} channels (κ {r.get('kappa', 1):.3g})"
            + ('' if k is None else f'; κ that cancels it {k:.3f}'))
        self.btn_kappa.setEnabled(k is not None and k > 0)

    def actualizar_base(self, info):
        """El `base_dinamica` del status (cada 200 ms) o de `base.dinamica`."""
        if not info:
            return
        self._base = dict(info)
        self.diagrama.actualizar_base(info)
        self._cargando = True
        try:
            self.chk_din.setChecked(bool(info.get('on')))
        finally:
            self._cargando = False
        if info.get('on'):
            lam, a = info.get('lam_hz'), info.get('a_adu')
            self.lbl_vivo.setText(
                ('λ̂ —' if lam is None else f'λ̂ {lam / 1e3:.1f} k/s')
                + ('' if a is None else f', ⟨A⟩ {a:.0f} ADU')
                + f", Δb {info.get('delta_b', 0.0):+.1f} ADU, base {info.get('base')}"
                + f" (b0 {info.get('b0')})")
            self._hist.append((time.time(), float(info.get('delta_b', 0.0)),
                               lam or 0.0))
        else:
            self.lbl_vivo.setText('dynamic base off')
        while self._hist and self._hist[0][0] < time.time() - HISTORIA_S:
            self._hist.popleft()
        if info.get('error'):
            self.lbl_aviso.setText(f"dynamic base: {info['error']}")
        self._avisos()
        self._habilitar()
        if info.get('on') and time.monotonic() - self._t_dibujo > 1.0:
            self._dibujar_db()

    def actualizar_status(self, est):
        if est.get('presente'):
            self.actualizar_base(est.get('base_dinamica'))

    def actualizar_config(self, cfg):
        """La config del MCA: τ del polo-cero, el seguidor y si G_F sigue valiendo."""
        super().actualizar_config(cfg)
        self._cfg = dict(cfg)
        mq = cfg.get('trap_mq')
        self.lbl_tau.setText('τ —' if mq is None else f'τ {float(mq) / 16 + 0.5:.1f} smp')
        self.lbl_tau.setToolTip('The decay of the pulses, from the pole-zero of the '
                                'trapezoid: τ = trap_mq/16 + 1/2 samples.')
        self._pintar_gf()
        self._avisos()

    def set_generador(self, hay):
        """Sin `gen_pulsos` sólo queda la referencia externa."""
        self._hay_gen = bool(hay)
        if not hay:
            self.cmb_ref.setCurrentIndex(1)
        self._habilitar()

    def set_conectado(self, conectado, running=False):
        super().set_conectado(conectado, running)
        self._conectado = bool(conectado)
        if not conectado:
            self._en_curso = False
        self._habilitar()

    # =========================================================================
    # Pintar
    # =========================================================================

    def _avisos(self):
        avisos = []
        cfg = self._cfg or {}
        if cfg.get('bl_auto'):
            avisos.append('the base follower (bl_auto) is on: the dynamic base needs '
                          'the fixed base')
        if self._ganancia and self._cfg and self.ganancia_vieja():
            avisos.append('G_F was measured with another MCA configuration: measure '
                          'it again')
        if avisos:
            self.lbl_aviso.setText('; '.join(avisos))
        elif not (self._base or {}).get('error') and \
                not self.lbl_aviso.text().startswith('not on'):
            self.lbl_aviso.setText('')

    def ganancia_vieja(self):
        """¿Cambió la configuración del MCA desde que se midió G_F?"""
        huella = (self._ganancia or {}).get('huella') or {}
        cfg = self._cfg or {}
        return any(k in cfg and cfg[k] != v for k, v in huella.items())

    def _pintar_gf(self):
        g = self._ganancia
        if not g:
            self.lbl_gf.setText('—')
            return
        self.lbl_gf.setText(f"{g['ganancia_mca']:.4f} /ADU"
                            + (' (old)' if self.ganancia_vieja() else ''))
        self.lbl_gf.setToolTip(f"line of {g.get('amplitud')} ADU in channel "
                               f"{g.get('centroide', 0):.1f}, {g.get('n')} events")

    def _pintar_filas(self):
        self.tabla.setRowCount(len(self._filas))
        for i, f in enumerate(self._filas):
            for j, s in enumerate((f['rotulo'], pct(f['caida']),
                                   '—' if f['ganancia'] is None else f"{f['ganancia']:.3f}")):
                self.tabla.setItem(i, j, QTableWidgetItem(s))
        self.lbl_veredicto.setText(veredicto(self._filas))
        actual = self.cmb_fuente.currentIndex()
        self._cargando = True
        try:
            self.cmb_fuente.clear()
            for f in self._filas:
                self.cmb_fuente.addItem(f"{f['rotulo']}: {pct(f['caida'])}")
            if self._filas:
                self.cmb_fuente.setCurrentIndex(min(max(actual, 0), len(self._filas) - 1))
        finally:
            self._cargando = False
        self._dibujar()
        self._habilitar()

    def _pintar_resultado(self):
        r = self._res or self._ext or {}
        self.diagrama.actualizar_resultado(r)
        L = self._lbl
        for lbl in L.values():
            lbl.setText('—')
            lbl.setStyleSheet('')
        self.lbl_b0.setText('—' if 'offset' not in r else
                            f"→ {int(round(r['offset']))} counts")
        if 'offset' in r:
            L['piso'].setText(f"{r['offset']:+.2f}, {r['ruido']:.2f} counts rms")
            L['ganancia'].setText(f"{r['ganancia']:.4f}, {r.get('ganancia_dc', 0):.4f}")
            if r.get('problema'):
                L['ganancia'].setStyleSheet(f'color: {ROJO};')
            L['latencia'].setText(f"{r['latencia']:.2f} samples, {r.get('lat_asg')}")
            sub, bw = r.get('subida_ns'), r.get('bw_3db_mhz')
            L['subida'].setText(('—' if sub is None else f'{sub:.1f} ns')
                                + f", {100 * r.get('sobrepico', 0):.0f} %, "
                                + ('> Nyquist' if bw is None else f'{bw:.0f} MHz'))
            L['residuo'].setText(f"{r['residuo_rms']:.2f} ({r.get('residuo_rms_fir', 0):.2f}), "
                                 f"{r.get('diafonia_db', 0):.0f} dB")
        lento = r.get('lento') or {}
        fuente = {'lenta': 'slow fit', 'rapida': 'fast fit', 'externa': 'external'}
        if self._ext is not None and r is not self._ext:
            L['caida'].setToolTip(f"IN1 alone (external): {pct(self._ext.get('caida_lenta_usar'))}")
        L['caida'].setText(f"{pct(r.get('caida_lenta_usar'))} "
                           f"({fuente.get(r.get('fuente_caida'), '?')})")
        if lento:
            L['polos'].setText(' / '.join(f'{100 * c:+.2f}' for c in lento['caida_por_polo'])
                               + ' % at ' + ' / '.join(f'{t:.3g}' for t in lento['lentos_us'])
                               + ' µs')
            if 'offset' not in r:
                L['ganancia'].setText(f"{lento['ganancia']:.4f} (slow fit)")
                L['residuo'].setText(f"{lento['residuo_rms']:.2f} "
                                     f"({lento['residuo_rms_sin_lentos']:.2f})")
        self._dibujar()
        self._habilitar()

    def _dibujar(self):
        r = self._res or {}
        for ax in (self.ax_rapida, self.ax_lenta, self.ax_h, self.ax_psd):
            ax.clear()
            ax.grid(True, alpha=0.3)
        self.ax_rapida.set_title('fast step response', fontsize=8)
        self.ax_rapida.set_xlabel('ns', fontsize=7)
        if r.get('escalon'):
            js = np.arange(C.LAGS[0], C.LAGS[0] + len(r['escalon']))
            self.ax_rapida.plot(js * 8.0, r['escalon'], color='#2c7fb8')
        self.ax_lenta.set_title('slow drop (after the FIR)', fontsize=8)
        self.ax_lenta.set_xlabel('µs', fontsize=7)
        self.ax_lenta.set_xscale('log')
        t = np.logspace(-1, np.log10(500.0), 200)          # µs
        for k, f in enumerate(self._filas):
            g = f.get('g', f.get('ganancia'))
            if g:
                s = C.respuesta_lenta(f['d'], f['lentos'], g, t * FS_HZ / 1e6)
                self.ax_lenta.plot(t, s, lw=1.6 if k == len(self._filas) - 1 else 0.9,
                                   label=f['rotulo'])
        if self._filas:
            self.ax_lenta.legend(fontsize=6, loc='lower left')
        self.ax_h.set_title('|H(f)| of the FIR', fontsize=8)
        self.ax_h.set_xlabel('MHz', fontsize=7)
        if r.get('fir'):
            fm, H = C.modulo_h(r['fir'])
            self.ax_h.plot(fm, 20 * np.log10(np.maximum(H, 1e-6)), color='#2c7fb8')
            self.ax_h.axhline(-3, color='gray', lw=0.6, ls='--')
            self.ax_h.set_ylabel('dB', fontsize=7)
        self.ax_psd.set_title('IN1 noise floor', fontsize=8)
        self.ax_psd.set_xlabel('MHz', fontsize=7)
        piso = self._caps.get('piso0') if self._caps else None
        if piso is not None and len(piso) > 64:
            f_hz, P = C.densidad(piso)
            self.ax_psd.semilogy(f_hz[1:] / 1e6, np.sqrt(P[1:]), color='#41ab5d', lw=0.8)
            self.ax_psd.set_ylabel('counts/√Hz', fontsize=7)
        for ax in (self.ax_rapida, self.ax_lenta, self.ax_h, self.ax_psd):
            ax.tick_params(labelsize=6)
        self._dibujar_db(dibujar=False)
        self.canvas.draw_idle()

    def _dibujar_db(self, dibujar=True):
        ax = self.ax_db
        ax.clear()
        ax.grid(True, alpha=0.3)
        ax.set_title('dynamic base: Δb over the last minute', fontsize=8)
        ax.set_ylabel('Δb, ADU', fontsize=7)
        ax.tick_params(labelsize=6)
        if self._hist:
            t0 = self._hist[-1][0]
            ts = np.array([h[0] - t0 for h in self._hist])
            ax.plot(ts, [h[1] for h in self._hist], color='#e6550d')
            ax.set_xlim(-HISTORIA_S, 0)
            ax.set_xlabel('s', fontsize=7)
        self._t_dibujo = time.monotonic()
        if dibujar:
            self.canvas.draw_idle()

    # =========================================================================
    # Guardar y cargar (en la PC)
    # =========================================================================

    def calibracion(self):
        """Todo lo de la pestaña como un dict JSON: lo que se guarda y lo que lee la
        campaña (`run_meritos_pulsos.py --base-tasa dinamica --calibracion`)."""
        i = self.cmb_fuente.currentIndex()
        return {'version': 1, 'canal': self._res, 'externa': self._ext,
                'origen': self._filas,
                'ganancia_mca': self._ganancia, 'kappa': float(self.spn_kappa.value()),
                'fuente': i if 0 <= i < len(self._filas) else None,
                'caida': self._caida_elegida(), 'verificacion': self._verificacion,
                't_guardado': time.time()}

    def guardar(self, ruta):
        ruta = str(ruta)
        base = ruta[:-5] if ruta.endswith('.json') else ruta
        with open(base + '.json', 'w') as f:
            json.dump(self.calibracion(), f, indent=1, default=float)
        caps = dict(self._caps)
        caps.update(self._caps_ext)
        if caps:
            np.savez_compressed(base + '.npz', **{k: np.asarray(v)
                                                  for k, v in caps.items()})
        self.log.emit(f'calibration saved in {base}.json')
        return base + '.json'

    def cargar(self, ruta):
        ruta = str(ruta)
        base = ruta[:-5] if ruta.endswith('.json') else ruta
        with open(base + '.json') as f:
            d = json.load(f)
        self._res = d.get('canal')
        self._ext = d.get('externa')
        self._filas = list(d.get('origen') or [])
        self._ganancia = d.get('ganancia_mca')
        self._verificacion = d.get('verificacion')
        try:
            with np.load(base + '.npz') as z:
                todas = {k: z[k] for k in z.files}
        except OSError:
            todas = {}
        self._caps_ext = {k: v for k, v in todas.items() if k.startswith('externa')}
        self._caps = {k: v for k, v in todas.items() if not k.startswith('externa')}
        self._cargando = True
        try:
            self.spn_kappa.setValue(float(d.get('kappa', 1.0)))
        finally:
            self._cargando = False
        self._pintar_filas()
        if d.get('fuente') is not None and d['fuente'] < len(self._filas):
            self.cmb_fuente.setCurrentIndex(int(d['fuente']))
        self._pintar_resultado()
        self._pintar_gf()
        if self._verificacion:
            self.actualizar_verificacion(self._verificacion)
        self.log.emit(f'calibration loaded from {base}.json')

    def _guardar_dialogo(self):
        ruta, _ = QFileDialog.getSaveFileName(self, 'Save calibration', 'calibracion.json',
                                              'Calibration (*.json)')
        if ruta:
            try:
                self.guardar(ruta)
            except OSError as e:
                self.lbl_error.setText(f'not saved: {e}')

    def _cargar_dialogo(self):
        ruta, _ = QFileDialog.getOpenFileName(self, 'Load calibration', '',
                                              'Calibration (*.json)')
        if ruta:
            try:
                self.cargar(ruta)
            except (OSError, ValueError, KeyError) as e:
                self.lbl_error.setText(f'not loaded: {e}')
