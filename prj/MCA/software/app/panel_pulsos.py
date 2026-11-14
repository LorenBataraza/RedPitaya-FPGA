#!/usr/bin/env python3
"""Pestaña «Pulses»: las capturas del osciloscopio y la tasa del momento.

Es la pestaña que contesta *por qué* el espectro salió como salió. Con el
histograma solo, un fotopico corrido puede ser el umbral, la línea de base, la
forma del pulso o el apilamiento, y no hay manera de distinguirlos. Acá se ven
las dos cosas que lo deciden, y se ven **juntas en el tiempo**:

  - arriba, la ventana capturada alrededor del disparo, en una de dos vistas:
      * **pulso**: la última captura, los dos canales, con persistencia de las
        anteriores en gris;
      * **mapa de calor**: todas las capturas superpuestas y alineadas en el
        disparo, con el color de cuántas pasan por cada punto (t, V), como la
        persistencia de un osciloscopio digital o un diagrama de ojo. Lo que una
        traza sola no dice: la dispersión de la forma, el apilamiento, la cola;
  - abajo, y **con el mismo instante**, la tasa de eventos, con una marca vertical
    en el instante de cada captura.

Leer las dos juntas es el diagnóstico: si la tasa saltó y las formas se ven
apiladas, es apilamiento; si las formas están limpias y la tasa cayó, es el
umbral. Por separado, ninguna de las dos lo dice.

**La curva de tasa no cuesta una lectura nueva.** `rate_inst_hz` y
`rate_avg_hz` ya vienen en cada `status` del MCA, cada 200 ms. La tercera curva
—los disparos que ve el OSC, de Δ`we_cnt`/Δt— sale de sus registros, y **no es la
misma**: los dos caminos tienen tiempos muertos distintos, y la distancia entre
las curvas ES la pérdida del camino lento.

La configuración del osciloscopio (y del ring) está en «OSC settings».
"""

import time
from collections import deque

import numpy as np
from matplotlib import colormaps
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.colors import LogNorm
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QSpinBox, QSplitter, QVBoxLayout, QWidget)

from API.osciloscope import ADC_CNT_PER_V, N_BUF

COLOR_CH = ('#1f77b4', '#d62728')          # IN1, IN2
COLOR_TASA_MCA = '#1f77b4'
COLOR_TASA_OSC = '#ff7f0e'

# Cuántas capturas anteriores quedan dibujadas debajo de la actual. Cinco
# alcanza para ver la dispersión de forma sin que el gráfico se ensucie: con
# muchas más, el fósforo tapa la traza viva en vez de darle contexto. Para ver
# muchas está el mapa de calor.
PERSISTENCIA = 5

# Ventana de la curva de tasa. 180 s a un `status` cada 200 ms son 900 puntos,
# que matplotlib redibuja sin costo y cubren una medida corta entera.
HISTORIA_S = 180.0

# El modo continuo: una captura cada tanto, sólo con la pestaña visible. El mapa
# junta trazas, así que pide más seguido.
CONTINUO_PULSO_MS = 500
CONTINUO_MAPA_MS = 100
# Una captura pedida sin respuesta en este tiempo se da por perdida.
ESPERA_CAPTURA_S = 2.0

VISTA_PULSO = 'pulso'
VISTA_MAPA = 'mapa'


# =============================================================================
# El mapa de calor, sin Qt
# =============================================================================

class MapaPulsos:
    """Cuántas trazas pasan por cada celda (t, V), con todas alineadas en el disparo.

    Cada traza suma uno en las celdas que recorre su línea, no sólo en sus muestras:
    entre dos muestras seguidas se llenan las celdas de V entre una y otra, como
    dibuja un osciloscopio. Así un flanco rápido se ve como una línea y no como dos
    puntos sueltos. Por columna se guarda la diferencia (+1 al entrar, −1 al salir)
    y la cuenta es su suma acumulada: cada traza cuesta O(muestras).

    El eje V se ajusta a lo que llega: si una traza se sale, se agranda con margen y
    se rehace con las trazas guardadas. Se guardan las últimas `max_trazas` (las más
    viejas se restan al salir), así que el mapa es de las últimas capturas. Cambiar la
    ventana (pre, largo o diezmado) lo empieza de nuevo: el eje de tiempo es otro.
    """

    NY = 160
    MAX_COLUMNAS = 800
    # Memoria de las trazas guardadas, por mapa: 8 M de muestras float32 = 32 MB.
    PRESUPUESTO_MUESTRAS = 8_000_000

    def __init__(self, ny=NY, max_trazas=4000):
        self.ny = int(ny)
        self.max_trazas_pedido = int(max_trazas)
        self.limpiar()

    def limpiar(self):
        self._trazas = deque()
        self._D = None
        self.clave = None               # (pre, n, dec)
        self.v_lo = self.v_hi = None
        self.agregadas = 0              # desde el último limpiar, incluidas las que salieron

    @property
    def n(self):
        """Trazas en el mapa."""
        return len(self._trazas)

    @property
    def max_trazas(self):
        if self.clave is None:
            return self.max_trazas_pedido
        return max(50, min(self.max_trazas_pedido,
                           self.PRESUPUESTO_MUESTRAS // max(1, self.clave[1])))

    def _columnas(self, n):
        m = n - 1                       # segmentos entre muestras
        nx = min(m, self.MAX_COLUMNAS)
        return m, nx, (np.arange(m) * nx) // m

    def _filas(self, traza):
        r = np.floor((traza - self.v_lo) / (self.v_hi - self.v_lo) * self.ny)
        return np.clip(r, 0, self.ny - 1).astype(np.intp)

    def _sumar(self, traza, signo):
        r = self._filas(traza)
        lo = np.minimum(r[:-1], r[1:])
        hi = np.maximum(r[:-1], r[1:]) + 1
        np.add.at(self._D, (self._col, lo), signo)
        np.add.at(self._D, (self._col, hi), -signo)

    def _reescalar(self, lo, hi):
        if self.v_lo is not None:
            lo, hi = min(lo, self.v_lo), max(hi, self.v_hi)
        span = max(hi - lo, 0.01)
        self.v_lo, self.v_hi = lo - 0.15 * span, hi + 0.15 * span
        self._D[:] = 0
        for t in self._trazas:
            self._sumar(t, 1)

    def agregar(self, traza, pre, dec=1):
        traza = np.asarray(traza, dtype=np.float32).ravel()
        if traza.size < 2:
            return
        clave = (int(pre), int(traza.size), int(dec))
        if clave != self.clave:
            self.limpiar()
            self.clave = clave
            _m, nx, self._col = self._columnas(traza.size)
            self._D = np.zeros((nx, self.ny + 1), dtype=np.int32)
        lo, hi = float(traza.min()), float(traza.max())
        if self.v_lo is None or lo < self.v_lo or hi > self.v_hi:
            self._reescalar(lo, hi)
        self._trazas.append(traza)
        self._sumar(traza, 1)
        self.agregadas += 1
        while len(self._trazas) > self.max_trazas:
            self._sumar(self._trazas.popleft(), -1)

    def matriz(self):
        """(H[ny, nx], (t0, t1) en muestras desde el disparo, (v_lo, v_hi)), o None."""
        if self._D is None or not self._trazas:
            return None
        H = np.cumsum(self._D[:, :self.ny], axis=1).T
        pre, n, _dec = self.clave
        return H, (-pre, n - 1 - pre), (self.v_lo, self.v_hi)


# =============================================================================
# La pestaña
# =============================================================================

class PanelPulsos(QWidget):
    """Las capturas del osciloscopio (pulso o mapa de calor) y la curva de tasa."""

    pedir_captura = pyqtSignal(int, int)     # pre, post
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.n_buf = N_BUF
        self.fs_hz = 125e6
        self.dec = 1
        self.cnt_por_v = ADC_CNT_PER_V
        self._trazas = deque(maxlen=PERSISTENCIA + 1)   # (pre, array)
        self._historia = deque()                        # (t, mca_inst, mca_avg, osc)
        self._marcas = deque(maxlen=PERSISTENCIA + 1)   # instantes de captura
        self._we_prev = None                            # (t, we_cnt) para Δ/Δt
        self._t0 = time.time()
        self._mapas = (MapaPulsos(), MapaPulsos())       # IN1, IN2
        self._wp_ultimo = None                          # el disparo de la última traza
        self.repetidas = 0                              # capturas sin disparo nuevo
        self._pedida = None                             # instante de la captura en vuelo
        self._imagen = None
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        div = QSplitter(Qt.Horizontal)
        div.addWidget(self._zona_graficos())
        div.addWidget(self._zona_controles())
        div.setStretchFactor(0, 1)
        div.setStretchFactor(1, 0)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(div)

    def _zona_graficos(self):
        self.fig = Figure(figsize=(7.6, 5.4), tight_layout=True)
        # Los dos ejes NO comparten el eje x: el de arriba está en microsegundos
        # desde el disparo y el de abajo en segundos de reloj. Comparten el
        # INSTANTE, que es lo que dibuja la marca vertical, no la escala.
        self.ax_forma = self.fig.add_subplot(211)
        self.ax_tasa = self.fig.add_subplot(212)

        self.ax_forma.grid(True, alpha=0.3)
        self.ax_forma.set_ylabel('volts')
        self.lineas_ch = []
        for i, color in enumerate(COLOR_CH):
            (ln,) = self.ax_forma.plot([], [], color=color, lw=1.0,
                                       label=f'IN{i + 1}')
            self.lineas_ch.append(ln)
        self._leyenda_forma = self.ax_forma.legend(loc='upper right', fontsize=8)
        self._fosforo = []

        self.ax_tasa.grid(True, alpha=0.3)
        self.ax_tasa.set_xlabel('seconds')
        self.ax_tasa.set_ylabel('events/s')
        (self.linea_mca,) = self.ax_tasa.plot([], [], color=COLOR_TASA_MCA,
                                              lw=1.2, label='MCA (accepted)')
        (self.linea_mca_avg,) = self.ax_tasa.plot([], [], color=COLOR_TASA_MCA,
                                                  lw=0.9, ls=':', label='MCA (mean)')
        (self.linea_osc,) = self.ax_tasa.plot([], [], color=COLOR_TASA_OSC,
                                              lw=1.0, label='OSC (triggers)')
        self.ax_tasa.legend(loc='upper left', fontsize=8)
        self._lineas_marca = []

        self.canvas = FigureCanvas(self.fig)
        self.barra = NavigationToolbar(self.canvas, self)

        self.lbl_captura = QLabel('no captures')
        pie = QHBoxLayout()
        pie.addWidget(self.barra)
        pie.addStretch(1)
        pie.addWidget(self.lbl_captura)

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
        v.addWidget(self._grupo_captura())
        v.addWidget(self._grupo_vista())
        nota = QLabel('The trigger, the decimation and the calibration are set in '
                      '«OSC settings».')
        nota.setWordWrap(True)
        nota.setStyleSheet('color: #777;')
        v.addWidget(nota)
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(320)
        return scroll

    @staticmethod
    def _forma(g):
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return f

    def _grupo_captura(self):
        g = QGroupBox('Capture')
        f = self._forma(g)

        self.spn_pre = QSpinBox()
        self.spn_pre.setRange(0, N_BUF - 1)
        self.spn_pre.setValue(256)
        self.spn_pre.setSingleStep(64)
        self.spn_pre.setToolTip(
            'Samples BEFORE the trigger. The trigger sits at this position of the '
            'array and at t=0 of the plot.')

        self.spn_post = QSpinBox()
        self.spn_post.setRange(16, N_BUF)
        self.spn_post.setValue(1024)
        self.spn_post.setSingleStep(64)
        self.spn_post.setToolTip(
            f'Samples AFTER the trigger. pre+post cannot exceed {N_BUF}, the '
            f'channel buffer.')

        self.btn_capturar = QPushButton('Capture')
        self.btn_capturar.clicked.connect(self._capturar)
        self.chk_continuo = QCheckBox('continuous')
        self.chk_continuo.setToolTip(
            'Refreshes only while this tab is VISIBLE: up to 16384 samples per '
            'channel are not paid for in the background. With the heat map it asks '
            f'for one every {CONTINUO_MAPA_MS} ms; with the pulse, every '
            f'{CONTINUO_PULSO_MS} ms.')

        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(self.btn_capturar)
        fila.addWidget(self.chk_continuo)
        caja = QWidget()
        caja.setLayout(fila)

        # Fila que ocupa las dos columnas: en la del campo, un botón más una
        # casilla no entran y la casilla queda cortada contra el borde.
        f.addRow('pre (samples)', self.spn_pre)
        f.addRow('post (samples)', self.spn_post)
        f.addRow(caja)
        return g

    def _grupo_vista(self):
        g = QGroupBox('View')
        f = self._forma(g)
        self.cmb_vista = QComboBox()
        self.cmb_vista.addItem('pulse', VISTA_PULSO)
        self.cmb_vista.addItem('heat map', VISTA_MAPA)
        self.cmb_vista.setToolTip(
            'Pulse: the last capture, with the previous ones in grey.\n'
            'Heat map: all captures overlaid and aligned on the trigger; the colour '
            'is how many pass through each point. Like an eye diagram: it shows the '
            'spread of the shape and the pile-up.')
        self.cmb_vista.currentIndexChanged.connect(self._cambio_vista)
        f.addRow('view', self.cmb_vista)

        self.chk_fosforo = QCheckBox('persistence')
        self.chk_fosforo.setChecked(True)
        self.chk_fosforo.setToolTip(
            f'Keeps the last {PERSISTENCIA} captures drawn in grey. It shows the '
            f'spread of the shape and the piled-up pulses, which a single trace '
            f'does not show.')
        self.chk_fosforo.toggled.connect(self._redibujar_forma)
        f.addRow(self.chk_fosforo)

        self.cmb_canal_mapa = QComboBox()
        self.cmb_canal_mapa.addItems(['IN1', 'IN2'])
        self.cmb_canal_mapa.currentIndexChanged.connect(self._redibujar_forma)
        f.addRow('map channel', self.cmb_canal_mapa)
        self.btn_borrar_mapa = QPushButton('Start over')
        self.btn_borrar_mapa.setToolTip('Clears the traces accumulated in the maps.')
        self.btn_borrar_mapa.clicked.connect(self.borrar_mapa)
        f.addRow(self.btn_borrar_mapa)
        self.lbl_mapa = QLabel('—')
        self.lbl_mapa.setWordWrap(True)
        self.lbl_mapa.setToolTip(
            'A capture that returns the same trigger as the previous one (there was '
            'no new one in between) is not added to the map: it would count the same '
            'pulse twice.')
        f.addRow(self.lbl_mapa)
        self._form_vista = f
        self._cambio_vista()
        return g

    # =========================================================================
    # Entradas
    # =========================================================================

    def vista(self):
        return self.cmb_vista.currentData()

    def _cambio_vista(self, *_):
        mapa = self.vista() == VISTA_MAPA
        self.chk_fosforo.setEnabled(not mapa)
        for w in (self.cmb_canal_mapa, self.btn_borrar_mapa, self.lbl_mapa):
            w.setVisible(mapa)
        self._form_vista.labelForField(self.cmb_canal_mapa).setVisible(mapa)
        self._redibujar_forma()

    def intervalo_continuo_ms(self):
        return CONTINUO_MAPA_MS if self.vista() == VISTA_MAPA else CONTINUO_PULSO_MS

    def borrar_mapa(self):
        for m in self._mapas:
            m.limpiar()
        self._wp_ultimo = None
        self.repetidas = 0
        self._redibujar_forma()

    def _set_n_buf(self, n_buf):
        """El anillo que dice el servidor, no el que traía el módulo.

        Re-rangea los spinbox además de guardar el número: si el bitstream trae
        RSZ menor, `N_BUF` deja elegir ventanas que no existen y el hardware NO
        avisa —devuelve el anillo repetido—, así que el tope tiene que moverse
        con el bitstream y no quedarse en el del último que hubo.
        """
        if n_buf == self.n_buf and self.spn_post.maximum() == n_buf:
            return
        self.n_buf = n_buf
        self.spn_pre.setRange(0, n_buf - 1)
        self.spn_post.setRange(16, n_buf)
        self.spn_post.setToolTip(
            f'Samples AFTER the trigger. pre+post cannot exceed {n_buf}, the '
            f'channel buffer.')

    def _capturar(self):
        pre, post = self.spn_pre.value(), self.spn_post.value()
        if pre + post > self.n_buf:
            self.log.emit(f'the requested window ({pre}+{post}) does not fit in the '
                          f'{self.n_buf}-sample buffer')
            return
        self._pedida = time.monotonic()
        self.pedir_captura.emit(pre, post)

    def quiere_continuo(self):
        """¿Hay que seguir pidiendo capturas? Lo consulta el temporizador."""
        return self.chk_continuo.isChecked()

    def pedir_una(self):
        """Lo llama el temporizador del modo continuo. Con una captura en vuelo no
        pide otra: a 100 ms, una placa lenta acumularía pedidos en la cola."""
        if (self._pedida is not None
                and time.monotonic() - self._pedida < ESPERA_CAPTURA_S):
            return
        self._capturar()

    def actualizar_traza(self, meta, datos):
        """Una captura nueva: `meta` del servidor y `float32[n_ch, n]` en volts."""
        self._pedida = None
        self.dec = int(meta.get('dec', 1)) or 1
        self.fs_hz = float(meta.get('fs_hz', self.fs_hz))
        pre = int(meta.get('pre', 0))
        t_cap = float(meta.get('t_captura', time.time()))
        datos = np.atleast_2d(np.asarray(datos))
        self._trazas.append((pre, datos))
        self._marcas.append(t_cap)

        # Al mapa, si es un disparo nuevo: el mismo wp es el mismo pulso.
        wp = meta.get('wp')
        if wp is not None and wp == self._wp_ultimo:
            self.repetidas += 1
        else:
            for i, m in enumerate(self._mapas):
                if i < datos.shape[0]:
                    m.agregar(datos[i], pre, self.dec)
        self._wp_ultimo = wp

        n = datos.shape[-1]
        us = n / self.fs_hz * 1e6
        self.lbl_captura.setText(
            f'{n} samples · dec {self.dec} · {us:.1f} us · wp {meta.get("wp", 0)}')
        self._redibujar_forma()
        self._redibujar_tasa()

    def actualizar_osc(self, info):
        """El `osc.get` del servidor: el largo del anillo y la tasa de disparos."""
        self._set_n_buf(int(info.get('n_buf', self.n_buf)) or self.n_buf)
        self.cnt_por_v = float(info.get('adc_cnt_per_v', self.cnt_por_v))
        est = info.get('status', {})
        # La tasa de disparos del OSC sale de Δwe_cnt/Δt. Es una CUENTA
        # ACUMULADA, así que hace falta la muestra anterior; la primera vuelta
        # no da tasa, sólo referencia.
        we = est.get('we_cnt_ch0')
        if we is not None:
            ahora = time.time()
            if self._we_prev is not None:
                dt = ahora - self._we_prev[0]
                dwe = we - self._we_prev[1]
                # Un we_cnt que retrocede es un reset del contador: se descarta
                # la muestra en vez de dibujar una tasa negativa.
                if dt > 1e-3 and dwe >= 0:
                    self._anotar_tasa(ahora, osc=dwe / dt)
            self._we_prev = (ahora, we)

    def actualizar_estado(self, est):
        """El `status` del MCA. De acá salen las dos curvas de tasa del MCA."""
        if not est.get('presente'):
            return
        self._anotar_tasa(time.time(),
                          mca_inst=est.get('rate_inst_hz'),
                          mca_avg=est.get('rate_avg_hz'))

    # =========================================================================
    # Historia de tasa
    # =========================================================================

    def _anotar_tasa(self, t, mca_inst=None, mca_avg=None, osc=None):
        """Un punto del historial. Las tres curvas llegan por caminos distintos
        y a ritmos distintos, así que cada una guarda None cuando no le tocó."""
        self._historia.append((t, mca_inst, mca_avg, osc))
        limite = t - HISTORIA_S
        while self._historia and self._historia[0][0] < limite:
            self._historia.popleft()
        self._redibujar_tasa()

    def _serie(self, indice):
        """(t relativo, valor) de una de las tres curvas, salteando los huecos."""
        xs, ys = [], []
        for fila in self._historia:
            if fila[indice] is not None:
                xs.append(fila[0] - self._t0)
                ys.append(fila[indice])
        return xs, ys

    # =========================================================================
    # Dibujo
    # =========================================================================

    def _redibujar_forma(self, *_):
        for ln in self._fosforo:
            ln.remove()
        self._fosforo = []
        if self.vista() == VISTA_MAPA:
            self._dibujar_mapa()
        else:
            self._dibujar_pulso()
        self.canvas.draw_idle()

    def _dibujar_pulso(self):
        if self._imagen is not None:
            self._imagen.set_visible(False)
        self._leyenda_forma.set_visible(True)
        self.ax_forma.set_title('')
        if not self._trazas:
            for ln in self.lineas_ch:
                ln.set_data([], [])
            return

        # El fósforo primero y con zorder bajo: la traza viva tiene que quedar
        # arriba, si no las anteriores la tapan justo cuando hay dispersión.
        if self.chk_fosforo.isChecked():
            for pre, datos in list(self._trazas)[:-1]:
                t_us = self._eje_us(datos.shape[-1], pre)
                for fila in np.atleast_2d(datos):
                    (ln,) = self.ax_forma.plot(t_us, fila, color='#999999',
                                               lw=0.6, alpha=0.35, zorder=1)
                    self._fosforo.append(ln)

        pre, datos = self._trazas[-1]
        datos = np.atleast_2d(datos)
        t_us = self._eje_us(datos.shape[-1], pre)
        for i, ln in enumerate(self.lineas_ch):
            ln.set_visible(True)
            if i < datos.shape[0]:
                ln.set_data(t_us, datos[i])
                ln.set_zorder(3)
            else:
                ln.set_data([], [])

        self.ax_forma.relim()
        self.ax_forma.autoscale_view()
        self.ax_forma.set_xlabel(f'microseconds from the trigger (dec {self.dec})')

    def _dibujar_mapa(self):
        for ln in self.lineas_ch:
            ln.set_visible(False)
        self._leyenda_forma.set_visible(False)
        canal = self.cmb_canal_mapa.currentIndex()
        mapa = self._mapas[canal]
        m = mapa.matriz()
        if m is None:
            if self._imagen is not None:
                self._imagen.set_visible(False)
            self.ax_forma.set_title('heat map: no captures yet', fontsize=9)
            self.lbl_mapa.setText('no traces')
            return
        H, (m0, m1), (v_lo, v_hi) = m
        extent = (m0 / self.fs_hz * 1e6, m1 / self.fs_hz * 1e6, v_lo, v_hi)
        datos = np.ma.masked_equal(H, 0)
        vmax = max(2, int(H.max()))
        if self._imagen is None:
            cmap = colormaps['inferno'].copy()
            cmap.set_bad(cmap(0.0))
            self._imagen = self.ax_forma.imshow(
                datos, origin='lower', aspect='auto', extent=extent,
                interpolation='nearest', cmap=cmap, norm=LogNorm(vmin=1, vmax=vmax),
                zorder=0)
        else:
            self._imagen.set_data(datos)
            self._imagen.set_extent(extent)
            self._imagen.set_norm(LogNorm(vmin=1, vmax=vmax))
        self._imagen.set_visible(True)
        self.ax_forma.set_xlim(extent[0], extent[1])
        self.ax_forma.set_ylim(v_lo, v_hi)
        self.ax_forma.set_xlabel(f'microseconds from the trigger (dec {self.dec})')
        self.ax_forma.set_title(
            f'IN{canal + 1}: {mapa.n} traces overlaid · up to {int(H.max())} per '
            'cell (log scale)', fontsize=9)
        texto = f'{mapa.n} traces in the map'
        if mapa.agregadas > mapa.n:
            texto += f' (the last {mapa.max_trazas})'
        if self.repetidas:
            texto += f'; {self.repetidas} captures without a new trigger, not added'
        self.lbl_mapa.setText(texto)

    def _eje_us(self, n, pre):
        return (np.arange(n) - pre) / self.fs_hz * 1e6

    def _redibujar_tasa(self):
        self.linea_mca.set_data(*self._serie(1))
        self.linea_mca_avg.set_data(*self._serie(2))
        self.linea_osc.set_data(*self._serie(3))

        for ln in self._lineas_marca:
            ln.remove()
        self._lineas_marca = []
        # La marca es lo que ata los dos gráficos: dice en qué punto de la curva
        # de tasa se tomó la forma que está arriba.
        for i, t_cap in enumerate(self._marcas):
            viva = (i == len(self._marcas) - 1)
            self._lineas_marca.append(self.ax_tasa.axvline(
                t_cap - self._t0, color='#cc3333' if viva else '#999999',
                ls='--' if viva else ':', lw=1.0 if viva else 0.6,
                alpha=1.0 if viva else 0.4))

        self.ax_tasa.relim()
        self.ax_tasa.autoscale_view()
        self.canvas.draw_idle()

    # =========================================================================
    # Estado de conexión
    # =========================================================================

    def set_conectado(self, conectado, running=False):
        for w in (self.btn_capturar, self.chk_continuo, self.spn_pre,
                  self.spn_post):
            w.setEnabled(conectado)
        if not conectado:
            self._we_prev = None
            self._pedida = None
