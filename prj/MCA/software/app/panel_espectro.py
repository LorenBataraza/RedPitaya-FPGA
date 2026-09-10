#!/usr/bin/env python3
"""Pestaña del espectro: el histograma 1D y todo lo que se hace con él.

El dibujo va sobre `NavigationToolbar2QT`, que ya trae home / desplazar / zoom
/ guardar imagen: es la misma barra que se ve en la aplicación de referencia y
no hay razón para reimplementarla.

Los controles de umbral escriben por campo (`mca_set_thr`, read-modify-write),
NO con `mca_configure`: el bloque entero escribe R_CTRL con run=0, o sea que
tocar un umbral pararía la adquisición en curso.
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
                     mca_save_file_binary, mca_save_file_json,
                     mca_write_file_histogram)

COLOR_ESPECTRO = '#ff9900'
REBIN = (1, 2, 4, 8, 16, 32, 64)


class PanelEspectro(QWidget):

    pedir_start = pyqtSignal(float, bool)    # segundos (0 = sin límite), borrar antes
    pedir_stop = pyqtSignal()
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
        self.ax.set_xlabel('canal')
        self.ax.set_ylabel('cuentas')
        (self.linea,) = self.ax.step([0], [0], where='post',
                                     color=COLOR_ESPECTRO, lw=1.2)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.mpl_connect('motion_notify_event', self._sobre_grafico)
        self.barra = NavigationToolbar(self.canvas, self)

        self.chk_log = QCheckBox('escala log')
        self.chk_log.toggled.connect(self._redibujar)
        self.cmb_rebin = QComboBox()
        self.cmb_rebin.addItems(str(r) for r in REBIN)
        self.cmb_rebin.currentIndexChanged.connect(self._redibujar)

        pie = QHBoxLayout()
        pie.addWidget(self.barra)
        pie.addStretch(1)
        pie.addWidget(self.chk_log)
        pie.addWidget(QLabel('agrupar bins'))
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
        f.addRow('bin / cuentas', bajo_cursor)
        f.addRow('cuentas totales', self.lbl_total)
        f.addRow('tasa inst., 1/s', self.lbl_rate_inst)
        f.addRow('tasa media, 1/s', self.lbl_rate_avg)
        return g

    def _grupo_umbral(self):
        g = QGroupBox('umbral y ventana')
        f = QFormLayout(g)

        self.spn_thr = self._spin(0, 0x3FFF, 'thr')
        self.spn_hyst = self._spin(0, 0x3FFF, 'hyst')
        f.addRow('umbral (cuentas)', self.spn_thr)
        f.addRow('histéresis', self.spn_hyst)

        self.chk_ventana = QCheckBox('ventana de amplitud')
        self.chk_ventana.toggled.connect(self._cambio_ventana)
        self.spn_amp_min = self._spin(0, 0xFFFF, 'amp_min')
        self.spn_amp_max = self._spin(0, 0xFFFF, 'amp_max')
        f.addRow(self.chk_ventana)
        f.addRow('mín', self.spn_amp_min)
        f.addRow('máx', self.spn_amp_max)
        return g

    def _grupo_exposicion(self):
        g = QGroupBox('tiempo de exposición (vivo)')
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

        self.chk_sin_limite = QCheckBox('sin límite (parar a mano)')
        v.addWidget(self.chk_sin_limite)
        self.lbl_restante = QLabel('—')
        v.addWidget(self.lbl_restante)

        self.btn_start = QPushButton('Iniciar')
        self.btn_stop = QPushButton('Detener')
        self.btn_clear = QPushButton('Reiniciar cuentas')
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
        g = QGroupBox('picos detectados')
        v = QVBoxLayout(g)

        self.tabla_picos = QTableWidget(0, 5)
        self.tabla_picos.setHorizontalHeaderLabels(
            ['canal', 'FWHM', 'res %', 'cuentas', 'área'])
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

        self.lbl_picos = QLabel('sin espectro')
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
            'Canales de la media móvil con la que se buscan los máximos.\n\n'
            'Sin suavizar, en un histograma de Poisson casi cualquier canal es '
            'un máximo local de sus vecinos. Subirlo agrupa picos angostos; '
            'bajarlo separa más, a costa de encontrar estructura que es ruido.')

        self.spn_prominencia = QDoubleSpinBox()
        self.spn_prominencia.setRange(0.1, 100.0)
        self.spn_prominencia.setValue(5.0)
        self.spn_prominencia.setSuffix(' %')
        self.spn_prominencia.setToolTip(
            'Prominencia mínima, como porcentaje de la del pico mayor.\n\n'
            'Se filtra por prominencia y no por altura: un hombro sobre un fondo '
            'alto es un pico, y un rizo sobre el fotopico no lo es. Bajarlo '
            'saca picos más chicos — hasta el piso de ruido de conteo, que es '
            'un segundo criterio y no se puede desactivar desde acá.')

        for w in (self.spn_suavizado, self.spn_prominencia):
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._recalcular_picos)

        f.addRow('suavizado', self.spn_suavizado)
        f.addRow('prominencia mín.', self.spn_prominencia)
        v.addLayout(f)

        self.chk_marcar = QCheckBox('marcar en el gráfico')
        self.chk_marcar.setChecked(True)
        self.chk_marcar.toggled.connect(self._redibujar)
        v.addWidget(self.chk_marcar)
        return g

    def _grupo_contadores(self):
        """Los contadores propios del MCA: son los que dicen si la medida vale.

        `dropped` es la suma combinacional de las tres fuentes de pérdida del
        RTL (divisor ocupado, colisión de lectura, barrido de borrado), así que
        también es el precio del refresco en vivo, a la vista.
        """
        g = QGroupBox('contadores y tiempos')
        v = QVBoxLayout(g)
        # Un bloque monoespaciado en vez de una grilla de QLabel: entran los
        # nueve números sin truncar ninguna etiqueta y ocupa cuatro renglones.
        self.lbl_contadores = QLabel()
        self.lbl_contadores.setFont(QFont('monospace', 9))
        self.lbl_contadores.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl_contadores)
        self._pintar_contadores({})
        return g

    def _pintar_contadores(self, cnt, baseline='—'):
        def n(clave):
            return int(cnt.get(clave, 0))

        def s(clave):
            return float(cnt.get(clave, 0.0))

        self.lbl_contadores.setText(
            f"aceptados   {n('accepted'):>9}   perdidos  {n('dropped'):>7}\n"
            f"rech. ampl. {n('rej_amp'):>9}   apilados  {n('pileup'):>7}\n"
            f"rech. forma {n('rej_psd'):>9}   base      {baseline:>7}\n"
            f"real {s('realtime_s'):7.3f} s  vivo {s('livetime_s'):7.3f} s\n"
            f"muerto {s('deadtime_s'):5.3f} s")

    def _grupo_archivo(self):
        g = QGroupBox()
        h = QHBoxLayout(g)
        for texto, ayuda, slot in (
                ('Guardar', 'espectro + metadata en csv, npz o json',
                 self._guardar_archivo),
                ('Cargar', 'releer un espectro guardado', self._cargar_archivo),
                ('Imagen', 'png, pdf o svg del gráfico', self._guardar_imagen)):
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

    def set_conectado(self, conectado, running=False):
        for w in (self.btn_clear, self.spn_thr,
                  self.spn_hyst, self.spn_amp_min, self.spn_amp_max,
                  self.chk_ventana):
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
            self.spn_thr.setValue(int(cfg.get('thr', 0)))
            self.spn_hyst.setValue(int(cfg.get('hyst', 0)))
            self.spn_amp_min.setValue(int(cfg.get('amp_min', 0)))
            self.spn_amp_max.setValue(int(cfg.get('amp_max', 0xFFFF)))
            abierta = (int(cfg.get('amp_min', 0)) == 0 and
                       int(cfg.get('amp_max', 0xFFFF)) == 0xFFFF)
            self.chk_ventana.setChecked(not abierta)
            self.h_shift = int(cfg.get('h_shift', 0))
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
        self.lbl_rate_inst.setText(f"{est.get('rate_inst_hz', 0.0):.2e}")
        self.lbl_rate_avg.setText(f"{est.get('rate_avg_hz', 0.0):.2e}")
        self._pintar_contadores(cnt, self.baseline if self.baseline is not None
                                else '—')

        exp = est.get('exposure') or {}
        restante = exp.get('left_s')
        if est.get('running') and restante is not None:
            self.lbl_restante.setText(f'restan {restante:.1f} s de tiempo vivo')
        elif est.get('running'):
            self.lbl_restante.setText('corriendo, sin límite')
        else:
            self.lbl_restante.setText('detenido')
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
                            'El pico no baja a media altura antes de que se '
                            'acabe el eje, así que su ancho no está definido.\n'
                            'Pasa con medio pico contra el canal 0 y con el '
                            'escalón de apilamiento contra el tope de escala.')
                    self.tabla_picos.setItem(fila, col, it)
            if canal_sel is not None:
                self._seleccionar_canal(canal_sel)
        finally:
            self.tabla_picos.blockSignals(False)

        if self.hist is None:
            self.lbl_picos.setText('sin espectro')
        elif not self.picos:
            self.lbl_picos.setText(
                'ningún pico por encima del ruido de conteo')
        else:
            n = len(self.picos)
            self.lbl_picos.setText(
                f"{n} pico{'s' if n != 1 else ''} · FWHM y resolución en "
                f"canales del eje actual")

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
            f"pico en canal {p['canal']:.1f}: " +
            ('FWHM no definido (truncado por el borde del eje)' if p['truncado']
             else f"FWHM {p['fwhm']:.2f} canales, "
                  f"resolución {p['resolucion_pct']:.2f} %") +
            f", área {p['area']:.0f} cuentas")

    # ---------- archivo ----------

    def _guardar_archivo(self):
        if self.hist is None:
            QMessageBox.information(self, 'Guardar', 'todavía no hay espectro')
            return
        ruta, _ = QFileDialog.getSaveFileName(
            self, 'Guardar espectro', 'espectro.csv',
            'CSV con metadata (*.csv);;NumPy (*.npz);;JSON (*.json)')
        if not ruta:
            return
        ext = os.path.splitext(ruta)[1].lower()
        guardar = {'.npz': mca_save_file_binary,
                   '.json': mca_save_file_json}.get(ext, mca_write_file_histogram)
        if ext not in ('.npz', '.json', '.csv'):
            ruta += '.csv'
        try:
            guardar(self.hist, ruta, meta=self.meta)
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.critical(self, 'Guardar', f'{type(e).__name__}: {e}')
            return
        self.log.emit(f'espectro guardado en {ruta} '
                      f'({len(self.meta)} claves de metadata)')

    def _cargar_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, 'Cargar espectro', '',
            'Espectros (*.csv *.npz *.json);;Todos (*)')
        if not ruta:
            return
        try:
            hist, meta = mca_load_file(ruta)
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.critical(self, 'Cargar', f'{type(e).__name__}: {e}')
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
            self.log.emit(f'{os.path.basename(ruta)}: sin zoom en la metadata, '
                          'se asume fondo de escala (fichero anterior al '
                          'registro del zoom)')
        self.actualizar_espectro(hist, meta)
        self.log.emit(f'cargado {ruta}: {hist.size} canales, '
                      f'{int(hist.sum())} cuentas')

    def _guardar_imagen(self):
        ruta, _ = QFileDialog.getSaveFileName(
            self, 'Guardar imagen', 'espectro.png',
            'PNG (*.png);;PDF (*.pdf);;SVG (*.svg)')
        if ruta:
            self.fig.savefig(ruta, dpi=150)
            self.log.emit(f'imagen guardada en {ruta}')
