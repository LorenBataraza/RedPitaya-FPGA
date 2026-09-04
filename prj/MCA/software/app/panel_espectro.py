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
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QMessageBox, QPushButton, QScrollArea, QSpinBox,
                             QVBoxLayout, QWidget)

from API.analisis import gauss_fit_peak
from API.mca import (mca_load_file, mca_save_file_binary, mca_save_file_json,
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
        self.n_canales = 16384
        self.h_shift = 0
        self._cargando = False               # evita el eco de los spinbox
        self._roi_sombra = None
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
        v.addWidget(self._grupo_lectura())
        v.addWidget(self._grupo_umbral())
        v.addWidget(self._grupo_exposicion())
        # Los contadores van ANTES de la ROI: son lectura permanente y tienen
        # que estar a la vista sin desplazar; la ROI se usa a demanda.
        v.addWidget(self._grupo_contadores())
        v.addWidget(self._grupo_roi())
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

    def _grupo_roi(self):
        g = QGroupBox('región de interés')
        v = QVBoxLayout(g)
        self.spn_roi_lo = QSpinBox()
        self.spn_roi_lo.setMaximum(1 << 20)
        self.spn_roi_hi = QSpinBox()
        self.spn_roi_hi.setMaximum(1 << 20)
        self.spn_roi_hi.setValue(16383)
        for s in (self.spn_roi_lo, self.spn_roi_hi):
            s.valueChanged.connect(self._redibujar)
        fila = QHBoxLayout()
        fila.addWidget(QLabel('de'))
        fila.addWidget(self.spn_roi_lo)
        fila.addWidget(QLabel('a'))
        fila.addWidget(self.spn_roi_hi)
        v.addLayout(fila)

        self.btn_ajustar = QPushButton('Ajustar gaussiana')
        self.btn_ajustar.clicked.connect(self._ajustar_roi)
        v.addWidget(self.btn_ajustar)
        self.lbl_roi = QLabel('—')
        self.lbl_roi.setWordWrap(True)
        v.addWidget(self.lbl_roi)
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
        for w in (self.btn_clear, self.btn_ajustar, self.spn_thr,
                  self.spn_hyst, self.spn_amp_min, self.spn_amp_max,
                  self.chk_ventana):
            w.setEnabled(conectado)
        self.btn_start.setEnabled(conectado and not running)
        self.btn_stop.setEnabled(conectado and running)

    def configurar_geometria(self, n_canales, h_shift=0):
        self.n_canales = max(1, int(n_canales))
        self.h_shift = int(h_shift)
        self.hist = None
        self.spn_roi_lo.setMaximum(self.n_canales - 1)
        self.spn_roi_hi.setMaximum(self.n_canales - 1)
        self.spn_roi_hi.setValue(self.n_canales - 1)
        self.ax.set_xlim(0, self.n_canales)
        self._redibujar()

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
        self._redibujar()

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

        if self._roi_sombra is not None:
            self._roi_sombra.remove()
            self._roi_sombra = None
        lo, hi = self.spn_roi_lo.value(), self.spn_roi_hi.value()
        if hi > lo and self.hist is not None:
            self._roi_sombra = self.ax.axvspan(lo, hi, color='#3080ff',
                                               alpha=0.12, zorder=0)

        # Los límites de aceptación viven en cuentas de amplitud; el eje está
        # en canales, que es la amplitud desplazada por h_shift.
        for ln in self._lineas_ventana:
            ln.remove()
        self._lineas_ventana = []
        if self.chk_ventana.isChecked():
            for valor in (self.spn_amp_min.value(), self.spn_amp_max.value()):
                canal = valor >> self.h_shift
                if 0 < canal < self.n_canales:
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

    def _ajustar_roi(self):
        if self.hist is None:
            return
        lo, hi = self.spn_roi_lo.value(), self.spn_roi_hi.value()
        if hi <= lo:
            self.lbl_roi.setText('la región está vacía')
            return
        r = gauss_fit_peak(self.hist, lo, hi)
        if r.get('empty'):
            self.lbl_roi.setText('sin cuentas en la región')
            return
        self.lbl_roi.setText(
            f"centroide {r['centroid']:.1f} · FWHM {r['fwhm']:.2f} canales\n"
            f"área {r['area']:.0f} cuentas · "
            f"resolución {r['resolution_pct']:.3f} %")
        self.log.emit(f"ROI [{lo}, {hi}]: centroide {r['centroid']:.1f}, "
                      f"FWHM {r['fwhm']:.2f}, resolución {r['resolution_pct']:.3f} %")

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
        self.configurar_geometria(hist.size, int(meta.get('h_shift', 0) or 0))
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
