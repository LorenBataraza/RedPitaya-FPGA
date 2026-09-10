#!/usr/bin/env python3
"""Pestaña del osciloscopio: las últimas formas y la tasa del momento.

Es la pestaña que contesta *por qué* el espectro salió como salió. Con el
histograma solo, un fotopico corrido puede ser el umbral, la línea de base, la
forma del pulso o el apilamiento, y no hay manera de distinguirlos. Acá se ven
las dos cosas que lo deciden, y se ven **juntas en el tiempo**:

  - arriba, la ventana capturada alrededor del último trigger, los dos canales,
    con persistencia de las anteriores en gris;
  - abajo, y **con el mismo eje de tiempo**, la tasa instantánea de eventos, con
    una marca vertical en el instante de cada captura.

Leer las dos juntas es el diagnóstico: si la tasa saltó y las formas se ven
apiladas, es apilamiento; si las formas están limpias y la tasa cayó, es el
umbral. Por separado, ninguna de las dos lo dice.

**La curva de tasa no cuesta una lectura nueva.** `rate_inst_hz` y
`rate_avg_hz` ya vienen en cada `status` del MCA, cada 200 ms, y hasta ahora se
mostraban como texto y se tiraban. Acá se acumulan en un buffer circular. La
tercera curva —los disparos que ve el OSC, de Δ`we_cnt`/Δt— sí sale de sus
registros, y **no es la misma**: los dos caminos tienen tiempos muertos
distintos, y la distancia entre las curvas ES la pérdida del camino lento.
"""

import time
from collections import deque

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QSpinBox, QSplitter, QVBoxLayout, QWidget)

from API.osciloscope import ADC_CNT_PER_V, DEC_LEGAL, N_BUF
from app.widgets_config import CALIENTE, CORTA, RIESGO, PanelCampos

COLOR_CH = ('#1f77b4', '#d62728')          # IN1, IN2
COLOR_TASA_MCA = '#1f77b4'
COLOR_TASA_OSC = '#ff7f0e'

# Cuántas capturas anteriores quedan dibujadas debajo de la actual. Cinco
# alcanza para ver la dispersión de forma sin que el gráfico se ensucie: con
# muchas más, el fósforo tapa la traza viva en vez de darle contexto.
PERSISTENCIA = 5

# Ventana de la curva de tasa. 180 s a un `status` cada 200 ms son 900 puntos,
# que matplotlib redibuja sin costo y cubren una medida corta entera.
HISTORIA_S = 180.0


class PanelOsc(PanelCampos):
    """Formas de onda, tasa, y los registros del slot del osciloscopio.

    Hereda de `PanelCampos` por los controles (antirrebote de tres mecanismos y
    anti-eco ya cableados), pero sus campos NO son de `API/mca.py` sino de
    `API/osciloscope.py`: la ventana los rutea a `osc.set` mirando `BLOQUE`.
    """

    BLOQUE = 'osc'

    pedir_captura = pyqtSignal(int, int)     # pre, post
    pedir_ctrl = pyqtSignal(str)             # 'reset' | 'sw_trig'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.n_buf = N_BUF
        self.fs_hz = 125e6
        self.dec = 1
        self.cnt_por_v = ADC_CNT_PER_V
        self._trazas = deque(maxlen=PERSISTENCIA + 1)   # (t_captura, array)
        self._historia = deque()                        # (t, mca_inst, mca_avg, osc)
        self._marcas = deque(maxlen=PERSISTENCIA + 1)   # instantes de captura
        self._we_prev = None                            # (t, we_cnt) para Δ/Δt
        self._t0 = time.time()
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
        # desde el trigger y el de abajo en segundos de reloj. Comparten el
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
        self.ax_forma.legend(loc='upper right', fontsize=8)
        self._fosforo = []

        self.ax_tasa.grid(True, alpha=0.3)
        self.ax_tasa.set_xlabel('segundos')
        self.ax_tasa.set_ylabel('eventos/s')
        (self.linea_mca,) = self.ax_tasa.plot([], [], color=COLOR_TASA_MCA,
                                              lw=1.2, label='MCA (aceptados)')
        (self.linea_mca_avg,) = self.ax_tasa.plot([], [], color=COLOR_TASA_MCA,
                                                  lw=0.9, ls=':', label='MCA (media)')
        (self.linea_osc,) = self.ax_tasa.plot([], [], color=COLOR_TASA_OSC,
                                              lw=1.0, label='OSC (disparos)')
        self.ax_tasa.legend(loc='upper left', fontsize=8)
        self._lineas_marca = []

        self.canvas = FigureCanvas(self.fig)
        self.barra = NavigationToolbar(self.canvas, self)

        self.lbl_captura = QLabel('sin capturas')
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
        v.addWidget(self._grupo_disparo())
        v.addWidget(self._grupo_muestreo())
        v.addWidget(self._grupo_calibracion())
        v.addWidget(self._grupo_estado())
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(360)
        return scroll

    def _forma(self, g):
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return f

    # ---------- grupos ----------

    def _grupo_captura(self):
        g = QGroupBox('Captura')
        f = self._forma(g)

        self.spn_pre = QSpinBox()
        self.spn_pre.setRange(0, N_BUF - 1)
        self.spn_pre.setValue(256)
        self.spn_pre.setSingleStep(64)
        self.spn_pre.setToolTip(
            'Muestras ANTES del trigger. El trigger queda en esta posición del '
            'array y en t=0 del gráfico.')

        self.spn_post = QSpinBox()
        self.spn_post.setRange(16, N_BUF)
        self.spn_post.setValue(1024)
        self.spn_post.setSingleStep(64)
        self.spn_post.setToolTip(
            f'Muestras DESPUÉS del trigger. pre+post no puede pasar de {N_BUF}, '
            f'que es el buffer del canal.')

        self.btn_capturar = QPushButton('Capturar')
        self.btn_capturar.clicked.connect(self._capturar)
        self.chk_continuo = QCheckBox('continuo')
        self.chk_continuo.setToolTip(
            'Refresca solo mientras esta pestaña está VISIBLE: son 16384 '
            'muestras por canal y no se pagan de fondo.')

        self.chk_fosforo = QCheckBox('persistencia')
        self.chk_fosforo.setChecked(True)
        self.chk_fosforo.setToolTip(
            f'Deja las últimas {PERSISTENCIA} capturas dibujadas en gris. Es lo '
            f'que muestra la dispersión de forma y los pulsos apilados, que en '
            f'una traza sola no se ven.')
        self.chk_fosforo.toggled.connect(self._redibujar_forma)

        fila = QHBoxLayout()
        fila.addWidget(self.btn_capturar)
        fila.addWidget(self.chk_continuo)
        caja = QWidget()
        caja.setLayout(fila)

        # Fila que ocupa las dos columnas: en la del campo, un botón más una
        # casilla no entran y la casilla queda cortada contra el borde.
        f.addRow('pre (muestras)', self.spn_pre)
        f.addRow('post (muestras)', self.spn_post)
        f.addRow(caja)
        f.addRow(self.chk_fosforo)
        return g

    def _grupo_disparo(self):
        g = QGroupBox('Disparo')
        f = self._forma(g)
        # El umbral es de 14 bits CON SIGNO: un pulso negativo dispara con el
        # umbral negativo, y por eso el rango no arranca en cero.
        for ch in (0, 1):
            f.addRow(f'umbral IN{ch + 1}',
                     self._spin(f'thr_ch{ch}', -8192, 8191, CALIENTE,
                                f'Umbral de disparo del canal {ch}, en cuentas '
                                f'de ADC. {ADC_CNT_PER_V} cuentas = 1 V en LV.'))
        for ch in (0, 1):
            f.addRow(f'histéresis IN{ch + 1}',
                     self._spin(f'hyst_ch{ch}', 0, 16383, CALIENTE,
                                'Cuánto tiene que volver la señal antes de '
                                'admitir otro disparo. Muy baja, el ruido '
                                'dispara de más.'))
        # Los dos umbrales en volts, en una fila propia: como campo de un
        # QFormLayout el texto no entra y se corta el segundo canal.
        self.lbl_thr_v = QLabel('—')
        f.addRow(self.lbl_thr_v)

        f.addRow('debounce',
                 self._spin('deb_len', 0, 0xFFFFF, CORTA,
                            'Ciclos de ADC que el disparo queda inhibido tras '
                            'uno. El reset del RTL son 62500 = 500 us.'))
        return g

    def _grupo_muestreo(self):
        g = QGroupBox('Muestreo')
        f = self._forma(g)
        for ch in (0, 1):
            f.addRow(f'decimación IN{ch + 1}',
                     self._combo(f'dec_ch{ch}', [(str(d), d) for d in DEC_LEGAL],
                                 CORTA,
                                 'Sólo estos seis valores son legales. Cambiarla '
                                 'estira la ventana en tiempo real y reinicia '
                                 'la captura en curso.'))
        for ch in (0, 1):
            f.addRow(f'delay IN{ch + 1}',
                     self._spin(f'dly_ch{ch}', 0, N_BUF, CORTA,
                                'Muestras a capturar DESPUÉS del trigger antes '
                                'de cerrar. Es tiempo muerto real: mientras '
                                'corre, no se actualiza wp_trig.'))
        for ch in (0, 1):
            f.addRow(self._check(f'avg_en_ch{ch}', f'promediado IN{ch + 1}',
                                 CORTA,
                                 'Promedia las muestras descartadas por la '
                                 'decimación en vez de tirarlas.'))
        f.addRow('bypass FIR',
                 self._spin('filt_bypass', 0, 0xF, CORTA,
                            'Un bit por canal: saltea el ecualizador FIR de '
                            'entrada. Bit 0 = IN1, bit 1 = IN2.'))
        return g

    def _grupo_calibracion(self):
        g = QGroupBox('Calibración')
        f = self._forma(g)
        for ch in (0, 1):
            f.addRow(f'offset IN{ch + 1}',
                     self._spin(f'calib_off_ch{ch}', -8192, 8191, RIESGO,
                                'Offset de calibración, en cuentas. Mal puesto '
                                'corre la línea de base y con ella todo el '
                                'espectro.'))
            f.addRow(f'ganancia IN{ch + 1}',
                     self._spin(f'calib_gain_ch{ch}', 0, 0xFFFF, RIESGO,
                                'Ganancia de calibración. 0x8000 es la unidad: '
                                'con 0 no entra señal.'))
        return g

    def _grupo_estado(self):
        g = QGroupBox('Estado')
        f = self._forma(g)
        self._estado = {}
        for clave, texto in (('adc_state', 'FSM del ADC'),
                             ('trg_state', 'FSM del disparo'),
                             ('wp_cur_ch0', 'wp actual IN1'),
                             ('wp_trig_ch0', 'wp al disparo IN1'),
                             ('we_cnt_ch0', 'disparos IN1'),
                             ('we_cnt_ch1', 'disparos IN2')):
            lbl = QLabel('—')
            self._estado[clave] = lbl
            f.addRow(texto, lbl)

        self.lbl_base = QLabel('—')
        self.lbl_base.setToolTip(
            'Dirección física del bloque, resuelta por el registro SLOTS del '
            'slot 6. Si no coincide con la constante, este bitstream tiene otra '
            'topología — y verlo acá es cómo se diagnostica.')
        f.addRow('base del bloque', self.lbl_base)

        btn_reset = QPushButton('Reset del OSC')
        btn_reset.setToolTip('Resetea las dos FSM y destraba adc_trg_dis.')
        btn_reset.clicked.connect(lambda: self.pedir_ctrl.emit('reset'))
        btn_trig = QPushButton('Disparo por software')
        btn_trig.setToolTip('Fuerza una captura sin esperar señal. Sirve para '
                            'confirmar que el camino a BRAM funciona.')
        btn_trig.clicked.connect(lambda: self.pedir_ctrl.emit('sw_trig'))
        f.addRow(btn_reset)
        f.addRow(btn_trig)
        return g

    # =========================================================================
    # Entradas
    # =========================================================================

    def _capturar(self):
        pre, post = self.spn_pre.value(), self.spn_post.value()
        if pre + post > self.n_buf:
            self.log.emit(f'la ventana pedida ({pre}+{post}) no entra en el '
                          f'buffer de {self.n_buf} muestras')
            return
        self.pedir_captura.emit(pre, post)

    def quiere_continuo(self):
        """¿Hay que seguir pidiendo capturas? Lo consulta el temporizador."""
        return self.chk_continuo.isChecked()

    def pedir_una(self):
        """Lo llama el temporizador del modo continuo."""
        self._capturar()

    def actualizar_traza(self, meta, datos):
        """Una captura nueva: `meta` del servidor y `float32[n_ch, n]` en volts."""
        self.dec = int(meta.get('dec', 1)) or 1
        self.fs_hz = float(meta.get('fs_hz', self.fs_hz))
        pre = int(meta.get('pre', 0))
        t_cap = float(meta.get('t_captura', time.time()))
        self._trazas.append((pre, np.asarray(datos)))
        self._marcas.append(t_cap)

        n = datos.shape[1] if datos.ndim == 2 else datos.size
        us = n / self.fs_hz * 1e6
        self.lbl_captura.setText(
            f'{n} muestras · dec {self.dec} · {us:.1f} us · wp {meta.get("wp", 0)}')
        self._redibujar_forma()
        self._redibujar_tasa()

    def actualizar_osc(self, info):
        """El `osc.get` del servidor: configuración, estado y base."""
        cfg = info.get('config', {})
        self.actualizar_config(cfg)
        self.n_buf = int(info.get('n_buf', self.n_buf)) or self.n_buf
        self.cnt_por_v = float(info.get('adc_cnt_per_v', self.cnt_por_v))

        v0 = cfg.get('thr_ch0', 0) / self.cnt_por_v
        v1 = cfg.get('thr_ch1', 0) / self.cnt_por_v
        self.lbl_thr_v.setText(f'IN1 {v0:+.3f} V   ·   IN2 {v1:+.3f} V')

        base = info.get('base', 0)
        self.lbl_base.setText(f'{base:#010x}' if base else '—')

        est = info.get('status', {})
        for clave, lbl in self._estado.items():
            if clave in est:
                lbl.setText(str(est[clave]))

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

    def _redibujar_forma(self):
        for ln in self._fosforo:
            ln.remove()
        self._fosforo = []

        if not self._trazas:
            self.canvas.draw_idle()
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
            if i < datos.shape[0]:
                ln.set_data(t_us, datos[i])
                ln.set_zorder(3)
            else:
                ln.set_data([], [])

        self.ax_forma.relim()
        self.ax_forma.autoscale_view()
        self.ax_forma.set_xlabel(f'microsegundos desde el disparo (dec {self.dec})')
        self.canvas.draw_idle()

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
        super().set_conectado(conectado, running)
        for w in (self.btn_capturar, self.chk_continuo, self.spn_pre,
                  self.spn_post):
            w.setEnabled(conectado)
        if not conectado:
            self._we_prev = None
