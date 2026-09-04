#!/usr/bin/env python3
"""Pestaña del mapa 2D: amplitud x factor de forma (PSD).

La pestaña sólo existe si el bitstream la trae: `mca_top` publica en CAPS el
bit `CAP_HIST_H_PSD`, y `mcamon` crea o destruye este panel según lo que diga
el hardware conectado. Con el bitstream del scope, o con una síntesis en la que
`EN_HIST_H_PSD=0`, no aparece.

Es la capacidad que la aplicación de referencia no tiene: separar poblaciones
de pulsos por forma, no sólo por altura.
"""

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.colors import LogNorm, Normalize
from matplotlib.figure import Figure
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
                             QLabel, QPushButton, QSpinBox, QVBoxLayout,
                             QWidget)

from API.analisis import fom


class PanelMapa2D(QWidget):

    log = pyqtSignal(str)

    def __init__(self, forma=(128, 64), parent=None):
        super().__init__(parent)
        self.mapa = np.zeros(forma, dtype=np.uint32)
        self._barra_color = None
        self._construir()
        self.configurar_geometria(forma)

    def _construir(self):
        self.fig = Figure(figsize=(6.0, 4.6), tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel('factor de forma (Q_cola / Q_total)')
        self.ax.set_ylabel('amplitud (bin del mapa)')
        self.imagen = None
        self.canvas = FigureCanvas(self.fig)
        self.barra = NavigationToolbar(self.canvas, self)

        self.chk_log = QCheckBox('escala log')
        self.chk_log.setChecked(True)
        self.chk_log.toggled.connect(self._redibujar)

        pie = QHBoxLayout()
        pie.addWidget(self.barra)
        pie.addStretch(1)
        pie.addWidget(self.chk_log)

        izq = QVBoxLayout()
        izq.addWidget(self.canvas, 1)
        izq.addLayout(pie)

        caja = QHBoxLayout(self)
        caja.addLayout(izq, 1)
        caja.addWidget(self._controles())

    def _controles(self):
        w = QWidget()
        w.setFixedWidth(250)
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 0, 0, 0)

        g = QGroupBox('figura de mérito')
        gv = QVBoxLayout(g)
        gv.addWidget(QLabel('rebanada de amplitud'))
        self.spn_lo = QSpinBox()
        self.spn_hi = QSpinBox()
        fila = QHBoxLayout()
        fila.addWidget(QLabel('de'))
        fila.addWidget(self.spn_lo)
        fila.addWidget(QLabel('a'))
        fila.addWidget(self.spn_hi)
        gv.addLayout(fila)

        btn = QPushButton('Calcular FOM')
        btn.clicked.connect(self._calcular_fom)
        gv.addWidget(btn)
        self.lbl_fom = QLabel('—')
        self.lbl_fom.setWordWrap(True)
        gv.addWidget(self.lbl_fom)
        v.addWidget(g)

        self.lbl_totales = QLabel('sin datos')
        v.addWidget(self.lbl_totales)

        btn_img = QPushButton('Guardar imagen…')
        btn_img.clicked.connect(self._guardar_imagen)
        v.addWidget(btn_img)
        v.addStretch(1)
        return w

    # ---------- datos ----------

    def configurar_geometria(self, forma):
        self.mapa = np.zeros(forma, dtype=np.uint32)
        self.spn_lo.setMaximum(forma[0] - 1)
        self.spn_hi.setMaximum(forma[0] - 1)
        self.spn_hi.setValue(forma[0] - 1)
        self.imagen = None
        self.ax.clear()
        self.ax.set_xlabel('factor de forma (Q_cola / Q_total)')
        self.ax.set_ylabel('amplitud (bin del mapa)')
        self._redibujar()

    def actualizar_mapa(self, mapa):
        self.mapa = np.asarray(mapa)
        self.lbl_totales.setText(f'{int(self.mapa.sum())} eventos en el mapa')
        self._redibujar()

    def _redibujar(self):
        datos = self.mapa.astype(float)
        techo = max(datos.max(), 1.0)
        norma = (LogNorm(vmin=0.5, vmax=techo) if self.chk_log.isChecked()
                 else Normalize(vmin=0, vmax=techo))
        if self.imagen is None:
            self.imagen = self.ax.imshow(datos, origin='lower', aspect='auto',
                                         norm=norma, cmap='inferno',
                                         interpolation='nearest')
            self._barra_color = self.fig.colorbar(self.imagen, ax=self.ax,
                                                  label='cuentas')
        else:
            self.imagen.set_data(datos)
            self.imagen.set_norm(norma)
        self.canvas.draw_idle()

    def _calcular_fom(self):
        lo, hi = self.spn_lo.value(), self.spn_hi.value()
        if hi <= lo:
            self.lbl_fom.setText('la rebanada está vacía')
            return
        try:
            r = fom(self.mapa, lo, hi + 1)
        except ValueError as e:
            self.lbl_fom.setText(str(e))
            return
        if 'reason' in r:
            self.lbl_fom.setText(r['reason'])
            return
        # El umbral de 1.27 es el que se usa para decir que dos poblaciones
        # están separadas; está en el docstring de API.analisis.fom.
        self.lbl_fom.setText(
            f"FOM {r['fom']:.3f} ({'buena' if r['fom'] > 1.27 else 'pobre'} "
            f"separación)\nvalle en el bin {r['valley']}\n"
            f"centroides {r['peak1']['centroid']:.1f} y "
            f"{r['peak2']['centroid']:.1f}")
        self.log.emit(f'FOM en amplitud [{lo}, {hi}] = {r["fom"]:.3f}')

    def _guardar_imagen(self):
        ruta, _ = QFileDialog.getSaveFileName(
            self, 'Guardar imagen', 'mapa2d.png',
            'PNG (*.png);;PDF (*.pdf);;SVG (*.svg)')
        if ruta:
            self.fig.savefig(ruta, dpi=150)
            self.log.emit(f'imagen guardada en {ruta}')
