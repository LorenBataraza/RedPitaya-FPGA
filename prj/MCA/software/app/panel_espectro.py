#!/usr/bin/env python3
"""Pestaña del espectro: el histograma 1D y todo lo que se hace con él.

El dibujo va sobre `NavigationToolbar2QT`, que ya trae home / desplazar / zoom
/ guardar imagen: es la misma barra que se ve en la aplicación de referencia y
no hay razón para reimplementarla.

La ventana de amplitud se escribe por campo (`mca_set_amp_min`, read-modify-
write), NO con `mca_configure`: el bloque entero escribe R_CTRL con run=0, o sea
que tocarla pararía la adquisición en curso.

En el MCA2 la ventana la abre el disparo del multitrigger, no un umbral del
MCA: el grupo «disparo» arma el disparo por pendiente en modo continuo
(`multitrigger_armar_mca`, op `mca.disparo` del servidor). Sin él no se mide.
"""

import os

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                             QDoubleSpinBox, QFileDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                             QMessageBox, QPushButton, QScrollArea, QSpinBox,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from API.analisis import buscar_picos
from API.mca import (mca_canal_de_amplitud, mca_load_file,
                     mca_save_file_binary, mca_save_file_json, mca_save_file_n42,
                     mca_write_file_histogram)

COLOR_ESPECTRO = '#ff9900'
REBIN = (1, 2, 4, 8, 16, 32, 64)


class PanelEspectro(QWidget):

    pedir_start = pyqtSignal(float, bool)    # segundos (0 = sin límite), borrar antes
    pedir_stop = pyqtSignal()
    pedir_disparo = pyqtSignal(dict)         # args de la op mca.disparo
    pedir_clear = pyqtSignal()
    pedir_campo = pyqtSignal(str, int)       # campo de _CAMPOS, valor
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hist = None
        self.meta = {}
        self.contadores = {}
        self.baseline = None
        # La geometría real llega en `configurar_geometria` al conectarse, leída
        # del registro WIDTHS. Estos defaults sólo cubren el rato antes de la
        # primera conexión, y se derivan de h_aw para que no puedan
        # contradecirse entre sí.
        self.h_aw = 13                       # 8192 canales
        self.n_canales = 1 << self.h_aw
        self.h_shift = 0                     # DEPRECADO: no gobierna el eje
        self._canal = 0                      # el del MCA: el disparo va ahí
        self.zoom_z = 0                      # ventana = 2^-z del fondo de escala
        self.zoom_k = 0                      # cuál de las 2^z ventanas
        self._cargando = False               # evita el eco de los spinbox
        self.picos = []                      # lo que devolvió `buscar_picos`
        self._marcas_picos = []
        self._lineas_ventana = []

        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        caja = QHBoxLayout(self)
        caja.addWidget(self._zona_grafico(), 1)
        caja.addWidget(self._zona_controles())

    def _zona_grafico(self):
        self.fig = Figure(figsize=(7.0, 4.6), tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('channel')
        self.ax.set_ylabel('counts')
        (self.linea,) = self.ax.step([0], [0], where='post',
                                     color=COLOR_ESPECTRO, lw=1.2)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.mpl_connect('motion_notify_event', self._sobre_grafico)
        self.barra = NavigationToolbar(self.canvas, self)

        self.chk_log = QCheckBox('log scale')
        self.chk_log.toggled.connect(self._redibujar)
        self.cmb_rebin = QComboBox()
        self.cmb_rebin.addItems(str(r) for r in REBIN)
        self.cmb_rebin.currentIndexChanged.connect(self._redibujar)

        pie = QHBoxLayout()
        pie.addWidget(self.barra)
        pie.addStretch(1)
        pie.addWidget(self.chk_log)
        pie.addWidget(QLabel('group bins'))
        pie.addWidget(self.cmb_rebin)

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.canvas, 1)
        v.addLayout(pie)
        return w

    def _zona_controles(self):
        interior = QWidget()
        v = QVBoxLayout(interior)
        v.setContentsMargins(6, 0, 6, 0)
        # Primero lo que se MIRA, después lo que se TOCA. Los tres primeros
        # grupos son lectura permanente y tienen que entrar sin desplazar: en un
        # portátil de 768 px, con los controles arriba la tabla de picos quedaba
        # abajo de todo y había que buscarla con la barra.
        v.addWidget(self._grupo_lectura())
        v.addWidget(self._grupo_contadores())
        v.addWidget(self._grupo_picos())
        v.addWidget(self._grupo_umbral())
        v.addWidget(self._grupo_exposicion())
        v.addWidget(self._grupo_archivo())
        v.addStretch(1)

        # En un portátil de 768 px de alto la columna no entra entera; con el
        # scroll se ve igual en cualquier pantalla en vez de recortarse.
        scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(352)
        return scroll

    def _grupo_lectura(self):
        g = QGroupBox()
        f = QFormLayout(g)
        self.lbl_bin_cuentas = QLabel('—')
        self.lbl_bin_numero = QLabel('—')
        self.lbl_total = QLabel('0')
        self.lbl_rate_inst = QLabel('0.00e+00')
        self.lbl_rate_avg = QLabel('0.00e+00')

        bajo_cursor = QHBoxLayout()
        bajo_cursor.addWidget(self.lbl_bin_numero)
        bajo_cursor.addWidget(QLabel('→'))
        bajo_cursor.addWidget(self.lbl_bin_cuentas)
        bajo_cursor.addStretch(1)
        f.addRow('bin / counts', bajo_cursor)
        f.addRow('total counts', self.lbl_total)
        f.addRow('input inst., 1/s', self.lbl_rate_inst)
        f.addRow('input mean, 1/s', self.lbl_rate_avg)
        # La tasa de los pulsos que llegan, no la de los aceptados: ésa queda en
        # la curva de la pestaña Pulsos. La cuenta está en `arribos_y_tiempo` del
        # servidor.
        ayuda = ('Pulses arriving per second, corrected for dead time:\n'
                 '(cross − lost_veto) / (real − veto − t_rearm).\n'
                 'It also counts the ones lost for lack of a slot. t_rearm leaves '
                 'the denominator because a pulse arriving while the trigger is '
                 'not re-armed cannot be counted.\n'
                 'inst.: between two reads (200 ms); mean: the whole run.')
        for lbl in (self.lbl_rate_inst, self.lbl_rate_avg):
            lbl.setToolTip(ayuda)
            f.labelForField(lbl).setToolTip(ayuda)
        return g

    def _grupo_umbral(self):
        g = QGroupBox('trigger and window')
        f = QFormLayout(g)

        # El disparo por pendiente del multitrigger: s = suma de L muestras
        # menos la de L muestras G antes. Para un escalón de alto A, s = L·A.
        self.spn_l = QSpinBox(minimum=1, maximum=16, value=8)
        self.spn_g = QSpinBox(minimum=0, maximum=31, value=4)
        self.spn_thr = QSpinBox(minimum=0, maximum=(1 << 18) - 1, value=600)
        self.spn_hyst = QSpinBox(minimum=0, maximum=(1 << 18) - 1, value=300)
        for spn, ayuda in (
                (self.spn_l, 'Samples in each sum of the slope.'),
                (self.spn_g, 'Gap between the two sums.'),
                (self.spn_thr, 'Threshold on the slope s (a step of height A '
                               'gives s = L·A). Measured on the board with the '
                               'campaign pulse: 600.'),
                (self.spn_hyst, 'Re-arms when s drops below thr − hyst: it is '
                                'what allows triggering on the tail of another '
                                'pulse.')):
            spn.setToolTip(ayuda)
        fila = QHBoxLayout()
        fila.addWidget(QLabel('L'))
        fila.addWidget(self.spn_l)
        fila.addWidget(QLabel('G'))
        fila.addWidget(self.spn_g)
        f.addRow('slope', fila)
        f.addRow('threshold (s)', self.spn_thr)
        f.addRow('hysteresis (s)', self.spn_hyst)
        self.btn_armar = QPushButton('Arm trigger')
        self.btn_desarmar = QPushButton('Disarm')
        self.btn_armar.clicked.connect(lambda: self._disparo(True))
        self.btn_desarmar.clicked.connect(lambda: self._disparo(False))
        fila = QHBoxLayout()
        fila.addWidget(self.btn_armar)
        fila.addWidget(self.btn_desarmar)
        f.addRow(fila)
        self.lbl_disparo = QLabel('—')
        f.addRow('status', self.lbl_disparo)

        self.chk_ventana = QCheckBox('amplitude window')
        self.chk_ventana.toggled.connect(self._cambio_ventana)
        self.spn_amp_min = self._spin(0, 0xFFFF, 'amp_min')
        self.spn_amp_max = self._spin(0, 0xFFFF, 'amp_max')
        f.addRow(self.chk_ventana)
        f.addRow('min', self.spn_amp_min)
        f.addRow('max', self.spn_amp_max)
        return g

    def _grupo_exposicion(self):
        g = QGroupBox('exposure time (live)')
        v = QVBoxLayout(g)

        self.spn_h = QSpinBox()
        self.spn_h.setMaximum(999)
        self.spn_m = QSpinBox()
        self.spn_m.setMaximum(59)
        self.spn_s = QDoubleSpinBox()
        self.spn_s.setDecimals(3)
        self.spn_s.setMaximum(59.999)
        self.spn_s.setValue(50.0)
        fila = QHBoxLayout()
        for spn, unidad in ((self.spn_h, 'h'), (self.spn_m, 'm'), (self.spn_s, 's')):
            fila.addWidget(spn)
            fila.addWidget(QLabel(unidad))
        v.addLayout(fila)

        self.chk_sin_limite = QCheckBox('no limit (stop by hand)')
        v.addWidget(self.chk_sin_limite)
        self.lbl_restante = QLabel('—')
        v.addWidget(self.lbl_restante)

        self.btn_start = QPushButton('Start')
        self.btn_stop = QPushButton('Stop')
        self.btn_clear = QPushButton('Clear counts')
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self.pedir_stop)
        self.btn_clear.clicked.connect(self._clear)
        fila_btn = QHBoxLayout()
        fila_btn.addWidget(self.btn_start)
        fila_btn.addWidget(self.btn_stop)
        v.addLayout(fila_btn)
        v.addWidget(self.btn_clear)
        return g

    def _grupo_picos(self):
        """Los picos que hay en el espectro, con su ancho. Se llena solo.

        Reemplaza al ajuste gaussiano sobre una región marcada a mano. El cambio
        no es de presentación: antes había que saber **dónde** estaba el pico
        para poder medirlo, y en un espectro desconocido eso es justamente lo que
        no se sabe. Los dos números que interesan de un fotopico —dónde cae y
        cuán ancho es— salen igual, y salen para todos a la vez.
        """
        g = QGroupBox('detected peaks')
        v = QVBoxLayout(g)

        self.tabla_picos = QTableWidget(0, 5)
        self.tabla_picos.setHorizontalHeaderLabels(
            ['channel', 'FWHM', 'res %', 'counts', 'area'])
        self.tabla_picos.verticalHeader().setVisible(False)
        self.tabla_picos.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla_picos.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla_picos.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla_picos.setFont(QFont('monospace', 9))
        self.tabla_picos.setAlternatingRowColors(True)
        self.tabla_picos.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        # Alto fijo de unas seis filas: la tabla crece con lo que encuentre, y
        # sin tope empujaría fuera de la vista a los grupos de abajo.
        self.tabla_picos.setMinimumHeight(150)
        self.tabla_picos.setMaximumHeight(190)
        # Elegir una fila centra el eje en ese pico: es la manera de ir de la
        # lista al espectro sin buscar el canal a mano con el zoom.
        self.tabla_picos.itemSelectionChanged.connect(self._ir_al_pico)
        v.addWidget(self.tabla_picos)

        self.lbl_picos = QLabel('no spectrum')
        self.lbl_picos.setWordWrap(True)
        v.addWidget(self.lbl_picos)

        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.spn_suavizado = QSpinBox()
        self.spn_suavizado.setRange(1, 101)
        self.spn_suavizado.setValue(3)
        self.spn_suavizado.setSingleStep(2)
        self.spn_suavizado.setToolTip(
            'Channels of the moving average used to look for maxima.\n\n'
            'Without smoothing, in a Poisson histogram almost any channel is a '
            'local maximum of its neighbours. Raising it merges narrow peaks; '
            'lowering it separates more, at the cost of finding structure that is '
            'noise.')

        self.spn_prominencia = QDoubleSpinBox()
        self.spn_prominencia.setRange(0.1, 100.0)
        self.spn_prominencia.setValue(5.0)
        self.spn_prominencia.setSuffix(' %')
        self.spn_prominencia.setToolTip(
            'Minimum prominence, as a percentage of that of the largest peak.\n\n'
            'It filters by prominence and not by height: a shoulder on a high '
            'background is a peak, and a ripple on the photopeak is not. Lowering '
            'it brings out smaller peaks — down to the counting-noise floor, which '
            'is a second criterion and cannot be turned off from here.')

        for w in (self.spn_suavizado, self.spn_prominencia):
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._recalcular_picos)

        f.addRow('smoothing', self.spn_suavizado)
        f.addRow('min. prominence', self.spn_prominencia)
        v.addLayout(f)

        self.chk_marcar = QCheckBox('mark on the plot')
        self.chk_marcar.setChecked(True)
        self.chk_marcar.toggled.connect(self._redibujar)
        v.addWidget(self.chk_marcar)
        return g

    def _grupo_contadores(self):
        """Los contadores propios del MCA: son los que dicen si la medida vale.

        Por defecto, el tiempo muerto en total; con «detail», desglosado por
        etapa (ver `_desglose`).
        """
        g = QGroupBox('counters and times')
        v = QVBoxLayout(g)
        # Un bloque monoespaciado en vez de una grilla de QLabel: entran los
        # nueve números sin truncar ninguna etiqueta y ocupa cuatro renglones.
        self.lbl_contadores = QLabel()
        self.lbl_contadores.setFont(QFont('monospace', 9))
        self.lbl_contadores.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl_contadores)
        self.chk_detalle = QCheckBox('detail')
        self.chk_detalle.setToolTip(
            'Breaks down dead time and triggers by stage: veto, no slot, '
            'publisher, trigger re-arm and live.')
        self.chk_detalle.toggled.connect(lambda _v: self._pintar_contadores(
            self.contadores, self.baseline if self.baseline is not None else '—'))
        v.addWidget(self.chk_detalle)
        self._pintar_contadores({})
        return g

    def _pintar_contadores(self, cnt, baseline='—'):
        """`muerto` es `deadtime_real_s` = t_win + t_div + t_rearm, el que corrige
        pérdidas; su porcentaje es sobre el tiempo medido, real − veto. Con el
        veto, real = veto + muerto + vivo.

        `perdidos` son los disparos que llegaron y no se midieron: `lost_active`
        (sin ranura) + `dropped` (esperando al publicador, más las colisiones de
        lectura y el barrido de borrado). Los vetados no están: el veto es una
        exclusión pedida, no una pérdida.
        """
        def n(clave):
            return int(cnt.get(clave, 0))

        def s(clave):
            return float(cnt.get(clave, 0.0))

        medido = s('realtime_s') - s('vetotime_s')
        muerto = s('deadtime_real_s')
        pct = 100.0 * muerto / medido if medido > 1e-9 else 0.0
        texto = (
            f"accepted    {n('accepted'):>9}   lost      "
            f"{n('lost_active') + n('dropped'):>7}\n"
            f"rej. ampl.  {n('rej_amp'):>9}   piled-up  {n('pileup'):>7}\n"
            f"rej. shape  {n('rej_psd'):>9}   baseline  {baseline:>7}\n"
            f"real {s('realtime_s'):7.3f} s  live {s('livetime_s'):7.3f} s\n"
            f"dead {muerto:7.3f} s ({pct:.1f} %)"
            # Sólo si hay veto: un bitstream sin él lee 0 y no hace falta
            # ocupar la línea.
            + (f"  veto {s('vetotime_s'):5.3f} s" if s('vetotime_s') else '')
            + ('  [VETOED]' if cnt.get('vetoed') else ''))
        if self.chk_detalle.isChecked():
            texto += '\n\n' + self._desglose(cnt)
        self.lbl_contadores.setText(texto)

    @staticmethod
    def _desglose(cnt):
        """Cada etapa con su tiempo y sus disparos: la columna de tiempo suma
        `realtime` y la de disparos suma `cross`. Es el teselado del MCA (cada
        ciclo va a la primera condición que vale, en este orden) y la atribución
        de arribos, una al lado de la otra.

        El re-armado no tiene cuenta: un pulso que llega con el disparo sin
        re-armar no genera flanco, y lo único medible es el tiempo.

        `lost_busy` no tiene registro propio (va dentro de `dropped`): sale de
        la atribución. Leído con la medición corriendo puede no cerrar por unas
        cuentas, porque cada contador se lee en un ciclo distinto; por eso el
        recorte en cero.
        """
        def n(clave):
            return int(cnt.get(clave, 0))

        def s(clave):
            return float(cnt.get(clave, 0.0))

        lost_busy = max(0, n('cross') - n('open') - n('lost_active')
                        - n('lost_veto'))
        filas = (('veto', s('vetotime_s'), n('lost_veto')),
                 ('no slot', s('t_win_s'), n('lost_active')),
                 ('publisher', s('t_div_s'), lost_busy),
                 ('re-arm', s('t_rearm_s'), None),
                 ('live', s('livetime_s'), n('open')),
                 ('total', s('realtime_s'), n('cross')))
        lineas = [f"{'':11}{'time':>10} {'triggers':>10}"]
        for nombre, t, k in filas:
            lineas.append(f"{nombre:<11}{t:8.3f} s {'—' if k is None else k:>10}")
        # Lo que se descartó DESPUÉS de abrir una ranura: colisiones de lectura
        # y barrido de borrado. Está en `perdidos` pero no es un disparo perdido.
        lineas.append(f"{'dropped on publish':<22}"
                      f"{max(0, n('dropped') - lost_busy):>10}")
        return '\n'.join(lineas)

    def _grupo_archivo(self):
        g = QGroupBox()
        h = QHBoxLayout(g)
        for texto, ayuda, slot in (
                ('Save', 'spectrum + metadata in csv, npz or json',
                 self._guardar_archivo),
                ('Load', 'reread a saved spectrum', self._cargar_archivo),
                ('Image', 'png, pdf or svg of the plot', self._guardar_imagen)):
            b = QPushButton(texto)
            b.setToolTip(ayuda)
            b.clicked.connect(slot)
            h.addWidget(b)
        return g

    def _spin(self, minimo, maximo, campo):
        """Un spinbox que escribe su campo en el hardware, con antirrebote.

        Sin el antirrebote, arrastrar la flecha del spinbox manda una escritura
        por paso; con 250 ms se manda sólo el valor con el que se quedó.
        """
        s = QSpinBox()
        s.setRange(minimo, maximo)
        s.setKeyboardTracking(False)
        temporizador = QTimer(s, singleShot=True, interval=250)
        temporizador.timeout.connect(
            lambda: self.pedir_campo.emit(campo, s.value()))
        s.valueChanged.connect(
            lambda _v: None if self._cargando else temporizador.start())
        s.setProperty('campo', campo)
        return s

    # =========================================================================
    # Estado
    # =========================================================================

    def _disparo(self, armar):
        self.pedir_disparo.emit({
            'ch': self._canal, 'armar': bool(armar),
            'L': self.spn_l.value(), 'G': self.spn_g.value(),
            'thr': self.spn_thr.value(), 'hyst': self.spn_hyst.value()})

    def actualizar_disparo(self, est):
        """El estado que devuelve la op `mca.disparo`."""
        p = est.get('pendiente') or {}
        if est.get('armado') and est.get('fuente') == 'pz':
            # Lo armó un script: esta pestaña sólo arma por pendiente. Los spins
            # son de la pendiente, así que no se tocan.
            z = est.get('polo_cero') or {}
            self.lbl_disparo.setText(
                f"armed with pole-zero: k={z.get('k')} m={z.get('m')} "
                f"thr={z.get('thr')} mq={z.get('mq')}"
                + ('' if est.get('we_keep') else ' (no we_keep!)')
                + '. «Arm trigger» switches it to slope')
        elif est.get('armado'):
            self.lbl_disparo.setText(
                f"armed: L={p.get('L')} G={p.get('G')} thr={p.get('thr')} "
                f"hyst={p.get('hyst')}" + ('' if est.get('we_keep')
                                            else ' (no we_keep!)'))
            self.spn_l.setValue(int(p.get('L', 8)))
            self.spn_g.setValue(int(p.get('G', 4)))
            self.spn_thr.setValue(int(p.get('thr', 600)))
            self.spn_hyst.setValue(int(p.get('hyst', 300)))
        else:
            self.lbl_disparo.setText('NO TRIGGER: the MCA opens no windows')

    def set_conectado(self, conectado, running=False):
        for w in (self.btn_clear, self.spn_thr, self.spn_hyst, self.spn_l,
                  self.spn_g, self.btn_armar, self.btn_desarmar,
                  self.spn_amp_min, self.spn_amp_max, self.chk_ventana):
            w.setEnabled(conectado)
        self.btn_start.setEnabled(conectado and not running)
        self.btn_stop.setEnabled(conectado and running)

    def configurar_geometria(self, n_canales, h_shift=0, h_aw=None):
        # `h_shift` quedo obsoleto: el eje ya no es `amp >> h_shift` sino los
        # h_aw bits altos de la feature normalizada. Se conserva el argumento
        # para no romper llamadores, pero la escala sale de h_aw.
        self.n_canales = max(1, int(n_canales))
        self.h_shift = int(h_shift)
        self.h_aw = int(h_aw) if h_aw is not None else \
            max(1, int(n_canales)).bit_length() - 1
        # Al reconectar puede haber cambiado el bitstream: el zoom de la sesión
        # anterior no vale nada acá. Lo repuebla `actualizar_config` en cuanto
        # llegue la config real del hardware.
        self.zoom_z = 0
        self.zoom_k = 0
        self.hist = None
        self.ax.set_xlim(0, self.n_canales)
        self._recalcular_picos()

    def actualizar_config(self, cfg):
        """Refleja lo que hay en el hardware, sin reenviarlo."""
        self._cargando = True
        try:
            self._canal = int(cfg.get('channel', 0))
            self.spn_amp_min.setValue(int(cfg.get('amp_min', 0)))
            self.spn_amp_max.setValue(int(cfg.get('amp_max', 0xFFFF)))
            abierta = (int(cfg.get('amp_min', 0)) == 0 and
                       int(cfg.get('amp_max', 0xFFFF)) == 0xFFFF)
            self.chk_ventana.setChecked(not abierta)
            if cfg.get('h_aw') is not None:
                self.h_aw = int(cfg['h_aw'])
            # Contra el bitstream viejo estas claves no existen o leen 0, que es
            # exactamente "sin zoom, fondo de escala": el mismo código sirve
            # para los dos bitstreams sin preguntar cuál está cargado.
            self.zoom_z = int(cfg.get('zoom_1d_z', 0) or 0)
            self.zoom_k = int(cfg.get('zoom_1d_k', 0) or 0)
        finally:
            self._cargando = False
        self._redibujar()

    def actualizar_estado(self, est):
        # Se guarda el estado crudo además de pintarlo: lo que se muestra está
        # formateado, y quien quiera el número (una prueba, un script) no
        # debería tener que parsear una etiqueta.
        self.contadores = est.get('counters', {})
        self.baseline = est.get('baseline_now')
        cnt = self.contadores
        self.lbl_total.setText(f"{cnt.get('accepted', 0):,}".replace(',', ' '))
        self.lbl_rate_inst.setText(f"{est.get('tasa_entrada_inst_hz', 0.0):.2e}")
        self.lbl_rate_avg.setText(f"{est.get('tasa_entrada_hz', 0.0):.2e}")
        self._pintar_contadores(cnt, self.baseline if self.baseline is not None
                                else '—')

        exp = est.get('exposure') or {}
        restante = exp.get('left_s')
        if est.get('running') and restante is not None:
            self.lbl_restante.setText(f'{restante:.1f} s of live time left')
        elif est.get('running'):
            self.lbl_restante.setText('running, no limit')
        else:
            self.lbl_restante.setText('stopped')
        self.set_conectado(True, running=bool(est.get('running')))

    def actualizar_espectro(self, hist, meta=None):
        self.hist = np.asarray(hist)
        if meta:
            self.meta = meta
        # El dato cambió, así que los picos también: `_recalcular_picos` redibuja.
        self._recalcular_picos()

    # =========================================================================
    # Dibujo
    # =========================================================================

    def _agrupado(self):
        """(x, y) ya rebineados. x en canales originales."""
        if self.hist is None or self.hist.size == 0:
            return np.zeros(1), np.zeros(1)
        r = REBIN[self.cmb_rebin.currentIndex()]
        n = (self.hist.size // r) * r
        y = self.hist[:n].reshape(-1, r).sum(axis=1) if r > 1 else self.hist
        return np.arange(0, n, r, dtype=float), y.astype(float)

    def _redibujar(self):
        x, y = self._agrupado()
        self.linea.set_data(x, y)

        log = self.chk_log.isChecked()
        self.ax.set_yscale('log' if log else 'linear')
        techo = float(y.max()) if y.size else 1.0
        self.ax.set_ylim(0.5 if log else 0, max(techo * 1.1, 1.0))

        # Cada pico: un punto en la cima y una barra horizontal en la media
        # altura, que ES el FWHM dibujado. La barra dice de un vistazo si el
        # ancho de la tabla corresponde al pico que uno está mirando — y si un
        # doblete sin resolver se está midiendo como uno solo.
        for artista in self._marcas_picos:
            artista.remove()
        self._marcas_picos = []
        if self.chk_marcar.isChecked():
            for p in self.picos:
                self._marcas_picos.append(self.ax.plot(
                    [p['canal']], [p['cuentas']], marker='v', ms=6,
                    color='#3080ff', ls='none', zorder=5)[0])
                if not p['truncado']:
                    media = p['fondo'] + p['prominencia'] / 2.0
                    self._marcas_picos.append(self.ax.plot(
                        [p['fwhm_lo'], p['fwhm_hi']], [media, media],
                        color='#3080ff', lw=1.4, alpha=0.8, zorder=5)[0])

        # Los límites de aceptación viven en cuentas de amplitud de AMP_W bits;
        # el eje está en canales, que son los h_aw bits altos de la feature
        # después del zoom. La conversión NO es `>> h_shift`: ese registro quedó
        # deprecado y ya no gobierna el datapath, así que usarlo acá ponía las
        # líneas 2^(AMP_W-h_aw) veces más a la derecha — un factor 8 con 8192
        # canales — y las de amplitud alta ni se dibujaban por caerse del eje.
        for ln in self._lineas_ventana:
            ln.remove()
        self._lineas_ventana = []
        if self.chk_ventana.isChecked():
            for valor in (self.spn_amp_min.value(), self.spn_amp_max.value()):
                canal = mca_canal_de_amplitud(valor, self.h_aw,
                                              self.zoom_z, self.zoom_k)
                # Los extremos SÍ se dibujan: con zoom, un límite fuera de la
                # ventana satura contra el borde, y ver la línea pegada al
                # borde es justamente la señal de que la ventana lo dejó afuera.
                self._lineas_ventana.append(
                    self.ax.axvline(canal, color='#cc3333', ls='--', lw=0.9))

        self.canvas.draw_idle()

    def _sobre_grafico(self, ev):
        if ev.inaxes is not self.ax or self.hist is None:
            return
        x, y = self._agrupado()
        if x.size < 1:
            return
        i = int(np.clip(np.searchsorted(x, ev.xdata, side='right') - 1,
                        0, x.size - 1))
        self.lbl_bin_numero.setText(str(int(x[i])))
        self.lbl_bin_cuentas.setText(str(int(y[i])))

    # =========================================================================
    # Acciones
    # =========================================================================

    def _start(self):
        segundos = 0.0 if self.chk_sin_limite.isChecked() else (
            self.spn_h.value() * 3600 + self.spn_m.value() * 60 + self.spn_s.value())
        self.pedir_start.emit(segundos, False)

    def _clear(self):
        self.pedir_clear.emit()
        if self.hist is not None:
            self.hist = np.zeros_like(self.hist)
            self._redibujar()

    def _cambio_ventana(self, activa):
        if self._cargando:
            return
        # Desactivar la ventana es abrirla del todo: el hardware no tiene un
        # bit de "sin ventana", tiene amp_min=0 y amp_max=0xFFFF.
        if not activa:
            self.pedir_campo.emit('amp_min', 0)
            self.pedir_campo.emit('amp_max', 0xFFFF)
        else:
            self.pedir_campo.emit('amp_min', self.spn_amp_min.value())
            self.pedir_campo.emit('amp_max', self.spn_amp_max.value())
        self._redibujar()

    # ---------- picos ----------

    def _recalcular_picos(self):
        """Busca los picos y repuebla la tabla. **No** se llama al redibujar.

        Cuesta ~20 ms sobre 8192 canales, y `_redibujar` corre además con cada
        cambio de escala log o de rebin — que no cambian el dato. Los picos
        dependen del histograma y de los dos controles de sensibilidad, así que
        se recalculan sólo cuando cambia alguno de esos tres.
        """
        if self.hist is None:
            self.picos = []
        else:
            self.picos = buscar_picos(
                self.hist,
                suavizado=self.spn_suavizado.value(),
                prominencia_rel=self.spn_prominencia.value() / 100.0)
        self._pintar_tabla_picos()
        self._redibujar()

    def _pintar_tabla_picos(self):
        # La selección se guarda por CANAL y no por número de fila: la lista se
        # repuebla sola mientras la medida crece, y un pico nuevo a la izquierda
        # correría todas las filas de lugar.
        canal_sel = self._canal_seleccionado()

        self.tabla_picos.blockSignals(True)
        try:
            self.tabla_picos.setRowCount(len(self.picos))
            for fila, p in enumerate(self.picos):
                truncado = p['truncado']
                celdas = (
                    f"{p['canal']:.1f}",
                    '—' if truncado else f"{p['fwhm']:.2f}",
                    '—' if truncado else f"{p['resolucion_pct']:.2f}",
                    f"{p['cuentas']:.0f}",
                    f"{p['area']:.0f}",
                )
                for col, texto in enumerate(celdas):
                    it = QTableWidgetItem(texto)
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if truncado:
                        it.setToolTip(
                            'The peak does not drop to half height before the '
                            'axis ends, so its width is undefined.\n'
                            'It happens with half a peak against channel 0 and '
                            'with the pile-up step against full scale.')
                    self.tabla_picos.setItem(fila, col, it)
            if canal_sel is not None:
                self._seleccionar_canal(canal_sel)
        finally:
            self.tabla_picos.blockSignals(False)

        if self.hist is None:
            self.lbl_picos.setText('no spectrum')
        elif not self.picos:
            self.lbl_picos.setText(
                'no peak above the counting noise')
        else:
            n = len(self.picos)
            self.lbl_picos.setText(
                f"{n} peak{'s' if n != 1 else ''} · FWHM and resolution in "
                f"channels of the current axis")

    def _canal_seleccionado(self):
        filas = self.tabla_picos.selectionModel().selectedRows() \
            if self.tabla_picos.selectionModel() else []
        if not filas:
            return None
        i = filas[0].row()
        return self.picos[i]['canal'] if 0 <= i < len(self.picos) else None

    def _seleccionar_canal(self, canal):
        """Vuelve a marcar el pico más cercano al que estaba elegido."""
        if not self.picos:
            return
        i = min(range(len(self.picos)),
                key=lambda k: abs(self.picos[k]['canal'] - canal))
        if abs(self.picos[i]['canal'] - canal) <= max(2.0, self.n_canales / 200):
            self.tabla_picos.selectRow(i)

    def _ir_al_pico(self):
        """Centra el eje en el pico elegido, con unos anchos de margen."""
        canal = self._canal_seleccionado()
        if canal is None:
            return
        i = min(range(len(self.picos)),
                key=lambda k: abs(self.picos[k]['canal'] - canal))
        p = self.picos[i]
        ancho = p['fwhm'] if np.isfinite(p['fwhm']) else self.n_canales / 50
        margen = max(6.0 * ancho, 20.0)
        self.ax.set_xlim(max(0.0, canal - margen),
                         min(float(self.n_canales), canal + margen))
        self.canvas.draw_idle()
        self.log.emit(
            f"peak at channel {p['canal']:.1f}: " +
            ('FWHM undefined (truncated by the edge of the axis)' if p['truncado']
             else f"FWHM {p['fwhm']:.2f} channels, "
                  f"resolution {p['resolucion_pct']:.2f} %") +
            f", area {p['area']:.0f} counts")

    # ---------- archivo ----------

    def _guardar_archivo(self):
        if self.hist is None:
            QMessageBox.information(self, 'Save', 'there is no spectrum yet')
            return
        formatos = {'CSV with metadata (*.csv)': ('.csv', mca_write_file_histogram),
                    'NumPy (*.npz)': ('.npz', mca_save_file_binary),
                    'JSON (*.json)': ('.json', mca_save_file_json),
                    'N42.42 (*.n42)': ('.n42', mca_save_file_n42)}
        ruta, filtro = QFileDialog.getSaveFileName(
            self, 'Save spectrum', 'espectro.csv', ';;'.join(formatos))
        if not ruta:
            return
        # Manda la extensión que se escribió; sin una conocida, el filtro elegido.
        ext = os.path.splitext(ruta)[1].lower()
        por_ext = dict(formatos.values())
        if ext not in por_ext:
            ext = formatos.get(filtro, ('.csv',))[0]
            ruta += ext
        guardar = por_ext[ext]
        try:
            guardar(self.hist, ruta, meta=self.meta)
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.critical(self, 'Save', f'{type(e).__name__}: {e}')
            return
        self.log.emit(f'spectrum saved to {ruta} '
                      f'({len(self.meta)} metadata keys)')

    def _cargar_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, 'Load spectrum', '',
            'Spectra (*.csv *.npz *.json *.n42);;All (*)')
        if not ruta:
            return
        try:
            hist, meta = mca_load_file(ruta)
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.critical(self, 'Load', f'{type(e).__name__}: {e}')
            return
        self.configurar_geometria(hist.size, int(meta.get('h_shift', 0) or 0),
                                  h_aw=meta.get('h_aw'))
        # El zoom del fichero, si lo trae. Los espectros guardados ANTES de que
        # `mca_get_config` releyera el zoom no lo tienen, y ahí no hay forma de
        # saber sobre qué ventana se tomaron: se asume fondo de escala, que es
        # lo que era cierto mientras nadie usó el zoom, y se avisa.
        self.zoom_z = int(meta.get('zoom_1d_z', 0) or 0)
        self.zoom_k = int(meta.get('zoom_1d_k', 0) or 0)
        if 'zoom_1d_z' not in meta:
            self.log.emit(f'{os.path.basename(ruta)}: no zoom in the metadata, '
                          'full scale assumed')
        self.actualizar_espectro(hist, meta)
        self.log.emit(f'loaded {ruta}: {hist.size} channels, '
                      f'{int(hist.sum())} counts')
        if meta.get('n42_n_espectros', 1) > 1:
            self.log.emit(f"{os.path.basename(ruta)}: has "
                          f"{meta['n42_n_espectros']} spectra, showing the first")

    def _guardar_imagen(self):
        ruta, _ = QFileDialog.getSaveFileName(
            self, 'Save image', 'espectro.png',
            'PNG (*.png);;PDF (*.pdf);;SVG (*.svg)')
        if ruta:
            self.fig.savefig(ruta, dpi=150)
            self.log.emit(f'image saved to {ruta}')
