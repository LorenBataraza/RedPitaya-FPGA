#!/usr/bin/env python3
"""Pestaña del event_ring (slot 2): una adquisición de ventanas a la DDR, con su sesión.

El ring copia, por cada disparo, una ventana de `pre + post` muestras de los dos
canales a un slot de la DDR. En la placa, el lector de libmca los saca y la sesión
(`AcquisitionSession`) los escribe en archivos, en una carpeta **de la placa**: la SD,
/dev/shm o un montaje de red. Es lo que corre el servidor con las ops `ring.*`
(`API.osciloscope_ring.AdquisicionRing`), y sigue aunque se cierre la GUI.

El estímulo es uno de dos:

  - el **disparo del ADC** (umbral e histéresis en volts, flanco positivo), el mismo
    camino que el osciloscopio;
  - el **generador de eventos** del ring (`gen_eventos`), que dispara solo y llena
    cada slot con un patrón conocido en vez del dato. Sirve para medir el camino a
    disco sin señal.

Las pérdidas del ring se **cuentan**, porque el disparo llega y se descarta:
`DROP_BUSY` (la captura todavía escribía la ventana anterior) y `DROP_FULL` (no había
slot libre: el lector no daba abasto). Con ellas, EV_CNT + DROP_BUSY + DROP_FULL = los
disparos. Docs: `docs/event_ring/` y `docs/API/adquisicion_de_eventos.md`.

Aparece sólo con el bitstream del ring: el del MCA no lo trae. En la app va
**embebido** en la pestaña «OSC settings» (`panel_config_osc.py`), como la fila
del camino a DDR de su franja: la pestaña acomoda los grupos (`grp_estimulo`,
`grp_ventana`, `grp_destino`, `caja_control`) y le da el umbral y la histéresis de
su etapa Disparo (`usar_disparo_de`), que son los registros que el ring escribe al
armarse. Sin embeber, arma su propia página, como antes.
"""

import os
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                             QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                             QVBoxLayout, QWidget)

FS_HZ = 125e6
INT32_MAX = (1 << 31) - 1
VENTANA_MAX = 0x7FF                      # PRE y POST son de 11 bits
# El margen de disco que la sesión deja libre: el suyo (200 MB) en la SD o en la
# red, y 16 MB en /dev/shm, que en la placa tiene 231 MB en total.
MARGEN_SHM_MB = 16.0

MOTIVOS = {'disk': 'the disk filled up (down to the margin)',
           'source': 'the reader ended by itself',
           'error': 'a session thread died'}


def margen_para(carpeta, margen_mb):
    """El margen que se pide: el del campo, o con 0 (automático) 16 MB en /dev/shm y
    None (el de la sesión) en otro lado."""
    if margen_mb:
        return float(margen_mb)
    return MARGEN_SHM_MB if os.path.normpath(carpeta).startswith('/dev/shm') else None


def _n(v):
    return f'{int(v):,}'.replace(',', ' ')


class PanelRing(QWidget):
    """Configuración, control y estado de una adquisición del event_ring."""

    pedir_iniciar = pyqtSignal(dict)         # los argumentos de ring.iniciar
    pedir_parar = pyqtSignal()
    pedir_estado = pyqtSignal()
    log = pyqtSignal(str)

    def __init__(self, parent=None, embebido=False):
        super().__init__(parent)
        self._prev = None                    # (t, n_read) para la tasa de lectura
        self.ultimo = {}                     # el último estado, crudo (pruebas, scripts)
        self.tasa_lectura = None             # eventos/s, del último par de estados
        self.fuente_disparo = None           # () -> (thr, hyst) en volts, embebido
        self._construir_grupos()
        if embebido:
            # Las cuentas van en la franja de la pestaña que lo embebe. Las filas se
            # sacan del formulario (ocultas, en Qt 5 dejarían su espaciado); los
            # rótulos siguen vivos y actualizándose, para las pruebas y los scripts.
            for w in (self.lbl_disparos, self.lbl_ev, self.lbl_busy, self.lbl_full,
                      self.lbl_leidos, self.lbl_escritos, self.lbl_tasa,
                      self.bar_ring):
                fila = self._form_estado.takeRow(w)
                for item in (fila.labelItem, fila.fieldItem):
                    if item is not None and item.widget() is not None:
                        item.widget().setVisible(False)
        else:
            self._armar()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir_grupos(self):
        self.grp_ventana = self._grupo_ventana()
        self.grp_estimulo = self._grupo_estimulo()
        self.grp_destino = self._grupo_destino()

        # Los botones, el error y el estado: lo que se mira mientras corre.
        self.caja_control = QWidget()
        v = QVBoxLayout(self.caja_control)
        v.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        self.btn_iniciar = QPushButton('Start')
        self.btn_iniciar.setToolTip('Arms the ring and the session, and starts writing to '
                                    'a new folder.')
        self.btn_parar = QPushButton('Stop')
        self.btn_parar.setToolTip('Stops the session and the ring; writes what was left.')
        self.btn_iniciar.clicked.connect(self._iniciar)
        self.btn_parar.clicked.connect(self.pedir_parar)
        fila.addWidget(self.btn_iniciar)
        fila.addWidget(self.btn_parar)
        fila.addStretch(1)
        v.addLayout(fila)
        self.lbl_error = QLabel('')
        self.lbl_error.setStyleSheet('color: #c0392b;')
        self.lbl_error.setWordWrap(True)
        v.addWidget(self.lbl_error)
        self.grp_estado = self._grupo_estado()
        v.addWidget(self.grp_estado)

    def _armar(self):
        # Dos columnas, como la del generador: la configuración a la izquierda; a la
        # derecha los botones y el estado, que se miran mientras corre.
        izq = QWidget()
        izq.setMaximumWidth(460)
        v = QVBoxLayout(izq)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.grp_ventana)
        v.addWidget(self.grp_estimulo)
        v.addWidget(self.grp_destino)
        v.addStretch(1)

        der = QWidget()
        der.setMaximumWidth(540)
        v = QVBoxLayout(der)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.caja_control)
        v.addStretch(1)

        interior = QWidget()
        h = QHBoxLayout(interior)
        h.addWidget(izq, 0, Qt.AlignTop)
        h.addWidget(der, 0, Qt.AlignTop)
        h.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(scroll)

    @staticmethod
    def _forma(g):
        f = QFormLayout(g)
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return f

    def _grupo_ventana(self):
        g = QGroupBox('Window')
        f = self._forma(g)
        self.spn_pre = QSpinBox(minimum=0, maximum=VENTANA_MAX, value=8)
        self.spn_post = QSpinBox(minimum=1, maximum=VENTANA_MAX, value=24)
        self.spn_pre.setToolTip('Samples before the trigger (8 ns each).')
        self.spn_post.setToolTip('Samples from the trigger on.')
        f.addRow('before, samples', self.spn_pre)
        f.addRow('after, samples', self.spn_post)
        self.cmb_canales = QComboBox()
        self.cmb_canales.addItem('IN1 and IN2', 2)
        self.cmb_canales.addItem('IN1', 1)
        self.cmb_canales.setToolTip('The ones that are saved. The ring always writes '
                                    'both, so the slot and the rate do not change.')
        f.addRow('channels', self.cmb_canales)
        return g

    def _grupo_estimulo(self):
        g = QGroupBox('Stimulus')
        f = self._forma(g)
        self.cmb_estimulo = QComboBox()
        self.cmb_estimulo.addItem('ADC trigger', 'disparo')
        self.cmb_estimulo.addItem('event generator', 'generador')
        self.cmb_estimulo.setToolTip(
            'ADC trigger: the window is the input signal. Event generator: it '
            'triggers by itself and each slot carries a known pattern, to measure the '
            'path to disk without a signal.')
        self.cmb_estimulo.currentIndexChanged.connect(self._cambio_estimulo)
        f.addRow('source', self.cmb_estimulo)

        self.spn_thr = QDoubleSpinBox(decimals=3, minimum=-1.0, maximum=1.0,
                                      value=0.1, singleStep=0.01)
        self.spn_hyst = QDoubleSpinBox(decimals=3, minimum=0.0, maximum=1.0,
                                       value=0.02, singleStep=0.005)
        self.spn_thr.setToolTip('Rising edge of the ADC, in volts.')
        self.spn_hyst.setToolTip('Re-arms when the signal drops below threshold − hysteresis.')
        f.addRow('threshold, V', self.spn_thr)
        f.addRow('hysteresis, V', self.spn_hyst)
        # Embebido, el umbral es el de nivel de IN1, que se configura en el
        # Multitrigger: una sola vez en la GUI.
        self.lbl_disparo = QLabel('—')
        self.lbl_disparo.setWordWrap(True)
        self.lbl_disparo.setToolTip(
            'On start, the ring arms the ADC trigger with the level threshold and '
            'hysteresis of IN1 (Multitrigger → Sources → Level): the same registers.')
        f.addRow('threshold', self.lbl_disparo)

        self.cmb_modo = QComboBox()
        self.cmb_modo.addItem('periodic', False)
        self.cmb_modo.addItem('Poisson', True)
        self.cmb_modo.currentIndexChanged.connect(self._cambio_estimulo)
        self.spn_tasa = QDoubleSpinBox(decimals=0, minimum=1.0, maximum=FS_HZ / 2,
                                       value=100e3, singleStep=10e3)
        self.spn_tasa.setToolTip('Generator triggers per second.')
        self.spn_dt_min = QSpinBox(minimum=2, maximum=0xFFFF, value=2, suffix=' cyc')
        self.spn_dt_min.setToolTip('Minimum cycles between triggers (Poisson).')
        self.spn_n = QSpinBox(minimum=0, maximum=INT32_MAX, value=0)
        self.spn_n.setSpecialValueText('endless')
        self.spn_n.setToolTip('How many triggers; once reached, the generator stops '
                              '(the session goes on until «Stop»).')
        f.addRow('mode', self.cmb_modo)
        f.addRow('rate, 1/s', self.spn_tasa)
        f.addRow('min. gap', self.spn_dt_min)
        f.addRow('triggers', self.spn_n)
        self._form_estimulo = f
        self._cambio_estimulo()
        return g

    def _grupo_destino(self):
        g = QGroupBox('Destination (on the board)')
        f = self._forma(g)
        self.ed_carpeta = QLineEdit('/dev/shm')
        self.ed_carpeta.setMinimumWidth(160)
        self.ed_carpeta.setToolTip(
            'A folder that exists on the board: the run goes in a new subfolder, '
            'ring_<date>_<time>. /dev/shm is RAM (231 MB, lost at power-off); the SD '
            'card or a network mount keep it.')
        f.addRow('folder', self.ed_carpeta)
        self.cmb_formato = QComboBox()
        self.cmb_formato.addItem('NumPy (.npz)', 'npz')
        self.cmb_formato.addItem('LH5 (HDF5)', 'lh5')
        f.addRow('format', self.cmb_formato)
        self.spn_ram = QDoubleSpinBox(decimals=0, minimum=8, maximum=256, value=64)
        self.spn_ram.setToolTip('Session memory for the events in flight.')
        f.addRow('RAM, MB', self.spn_ram)
        self.spn_margen = QDoubleSpinBox(decimals=0, minimum=0, maximum=10000, value=0)
        self.spn_margen.setSpecialValueText('automatic')
        self.spn_margen.setToolTip(
            'What the session leaves free on the disk: it stops by itself below it. '
            f'Automatic: {MARGEN_SHM_MB:.0f} MB in /dev/shm, 200 MB elsewhere.')
        f.addRow('margin, MB', self.spn_margen)
        return g

    def _grupo_estado(self):
        g = QGroupBox('Status')
        f = self._forma(g)
        self.lbl_estado = QLabel('—')
        self.lbl_run_dir = QLabel('—')
        self.lbl_run_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Un camino largo no ensancha la columna: se corta, y entero va en el tooltip.
        self.lbl_run_dir.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_run_dir.setMinimumWidth(170)
        self.lbl_disparos = QLabel('—')
        self.lbl_generados = QLabel('—')
        self.lbl_ev = QLabel('—')
        self.lbl_busy = QLabel('—')
        self.lbl_full = QLabel('—')
        self.lbl_leidos = QLabel('—')
        self.lbl_escritos = QLabel('—')
        self.lbl_tasa = QLabel('—')
        self.bar_ring = QProgressBar()
        self.bar_ring.setFormat('%v / %m slots')
        self.bar_ring.setMinimumWidth(200)
        self.bar_ring.setToolTip('The slots written to DDR that the reader has not read '
                                 'yet. Full, every new trigger is a DROP_FULL.')
        f.addRow('status', self.lbl_estado)
        f.addRow('run', self.lbl_run_dir)
        f.addRow('triggers', self.lbl_disparos)
        f.addRow('generated', self.lbl_generados)
        f.addRow('captured (EV_CNT)', self.lbl_ev)
        f.addRow('capture busy (DROP_BUSY)', self.lbl_busy)
        f.addRow('ring full (DROP_FULL)', self.lbl_full)
        f.addRow('read', self.lbl_leidos)
        f.addRow('written', self.lbl_escritos)
        f.addRow('reading, events/s', self.lbl_tasa)
        f.addRow('unread in DDR', self.bar_ring)
        self._form_estado = f
        self._ver_generados(False)
        return g

    def _ver_generados(self, ver):
        self.lbl_generados.setVisible(ver)
        self._form_estado.labelForField(self.lbl_generados).setVisible(ver)

    # =========================================================================
    # Acciones
    # =========================================================================

    def _cambio_estimulo(self, *_):
        gen = self.cmb_estimulo.currentData() == 'generador'
        propio = self.fuente_disparo is None
        f = self._form_estimulo
        for w, ver in ((self.spn_thr, not gen and propio),
                       (self.spn_hyst, not gen and propio),
                       (self.lbl_disparo, not gen and not propio),
                       (self.cmb_modo, gen), (self.spn_tasa, gen),
                       (self.spn_dt_min, gen and bool(self.cmb_modo.currentData())),
                       (self.spn_n, gen)):
            w.setVisible(ver)
            f.labelForField(w).setVisible(ver)

    def usar_disparo_de(self, fuente):
        """Embebido: `fuente()` da (umbral, histéresis) en volts, los de la etapa
        Disparo de la pestaña. Reemplaza los dos campos propios."""
        self.fuente_disparo = fuente
        self._cambio_estimulo()
        self.mostrar_disparo()

    def mostrar_disparo(self):
        if self.fuente_disparo is not None:
            thr, hyst = self.fuente_disparo()
            self.lbl_disparo.setText(f'{thr:+.3f} V, hysteresis {hyst:.3f} V\n'
                                     '(the level of IN1, set in Multitrigger)')

    def estimulo(self):
        """'disparo' o 'generador': lo que dispara las ventanas."""
        return self.cmb_estimulo.currentData()

    def configurar_ring(self, hay_generador):
        """Al conectarse: sin el generador de eventos (el ring del 2026-11-09 para
        atrás), la única fuente es el disparo."""
        i = self.cmb_estimulo.findData('generador')
        modelo = self.cmb_estimulo.model()
        modelo.item(i).setEnabled(bool(hay_generador))
        if not hay_generador and self.cmb_estimulo.currentData() == 'generador':
            self.cmb_estimulo.setCurrentIndex(self.cmb_estimulo.findData('disparo'))

    def argumentos(self, ahora=None):
        """Los de `ring.iniciar`, o ValueError. La carpeta de la corrida se arma acá:
        una nueva por corrida, con la fecha y la hora de esta máquina."""
        carpeta = self.ed_carpeta.text().strip()
        if not carpeta.startswith('/'):
            raise ValueError(f'folder {carpeta!r}: it has to be an absolute path on '
                             'the board')
        nombre = time.strftime('ring_%Y%m%d_%H%M%S', time.localtime(ahora))
        kw = {'run_dir': os.path.join(carpeta, nombre),
              'pre': int(self.spn_pre.value()), 'post': int(self.spn_post.value()),
              'n_ch': int(self.cmb_canales.currentData()),
              'formato': self.cmb_formato.currentData(),
              'ram_mb': float(self.spn_ram.value()),
              'margen_mb': margen_para(carpeta, self.spn_margen.value())}
        if self.cmb_estimulo.currentData() == 'generador':
            kw['generador'] = {'aleatorio': bool(self.cmb_modo.currentData()),
                               'tasa': float(self.spn_tasa.value()),
                               'dt_min': int(self.spn_dt_min.value()),
                               'n': int(self.spn_n.value())}
        else:
            thr, hyst = (self.fuente_disparo() if self.fuente_disparo is not None
                         else (self.spn_thr.value(), self.spn_hyst.value()))
            kw['disparo'] = {'thr': float(thr), 'hyst': float(hyst)}
        return kw

    def _iniciar(self):
        try:
            kw = self.argumentos()
        except ValueError as e:
            self.lbl_error.setText(f'not started: {e}')
            self.log.emit(f'ring: not started: {e}')
            return
        self.lbl_error.setText('')
        self._prev = None
        self.pedir_iniciar.emit(kw)

    # =========================================================================
    # Desde el servidor
    # =========================================================================

    def actualizar_ring(self, e):
        """El `ring.estado` (o lo que devuelve `ring.parar`): la sesión y el ring."""
        self.ultimo = dict(e)
        corriendo = bool(e.get('corriendo'))
        stats = e.get('stats') or {}
        hw = e.get('hw') or e.get('hw_final') or {}
        if corriendo:
            texto = 'running'
        elif e.get('stats') is None:
            texto = 'no acquisition'
        else:
            texto = 'stopped'
        motivo = e.get('motivo')
        if motivo:
            texto += f': {MOTIVOS.get(motivo, motivo)}'
        self.lbl_estado.setText(texto)
        self.lbl_error.setText(f"error: {e['error']}" if e.get('error') else '')
        if e.get('run_dir'):
            # El nombre arriba y dónde está abajo: un camino entero no entra en la
            # columna, y partido en las barras no se lee.
            fs = f" ({e['fs']})" if e.get('fs') else ''
            padre, nombre = os.path.split(os.path.normpath(e['run_dir']))
            self.lbl_run_dir.setText(f'{nombre}\nin {padre}{fs}')
            self.lbl_run_dir.setToolTip(e['run_dir'])

        if hw:
            ev = int(hw.get('hw_ev_cnt', 0))
            busy = int(hw.get('hw_drop_busy', 0))
            full = int(hw.get('hw_drop_full', 0))
            disp = ev + busy + full

            def pct(x):
                return f' ({100 * x / disp:.2f} %)' if disp else ''

            gen = hw.get('hw_gen_cnt')
            self.lbl_disparos.setText(_n(disp))
            self._ver_generados(gen is not None)
            if gen is not None:
                self.lbl_generados.setText(_n(gen) + (' (finished)' if hw.get(
                    'hw_gen_terminado') else ''))
            self.lbl_ev.setText(_n(ev))
            self.lbl_busy.setText(_n(busy) + pct(busy))
            self.lbl_full.setText(_n(full) + pct(full))
            n_slots = int(hw.get('hw_n_slots') or e.get('n_slots') or 0)
            self.bar_ring.setMaximum(max(1, n_slots))
            # `hw_no_leidos` es wr_slot − next en 32 bits sin signo, leídos en dos
            # momentos: si el lector avanzó entre las dos lecturas sale "negativo" (un
            # número enorme), y es que no queda nada sin leer.
            sin_leer = int(hw.get('hw_no_leidos', 0)) & 0xFFFFFFFF
            if sin_leer >= 1 << 31:
                sin_leer = 0
            self.bar_ring.setValue(min(sin_leer, max(1, n_slots)))
        if stats:
            leidos = int(stats.get('n_read', 0))
            self.lbl_leidos.setText(_n(leidos))
            self.lbl_escritos.setText(f"{_n(stats.get('n_written', 0))} "
                                      f"({int(stats.get('chunks', 0))} files)")
            ahora = time.monotonic()
            if corriendo and self._prev is not None and ahora > self._prev[0]:
                tasa = (leidos - self._prev[1]) / (ahora - self._prev[0])
                self.tasa_lectura = tasa
                self.lbl_tasa.setText(f'{tasa:.4g}')
            elif not corriendo and stats.get('rate_ev_s') is not None:
                self.tasa_lectura = float(stats['rate_ev_s'])
                self.lbl_tasa.setText(f"{stats['rate_ev_s']:.4g} (mean)")
            self._prev = (ahora, leidos) if corriendo else None
        self._set_corriendo(corriendo)

    def mostrar_fallo(self, mensaje):
        """Un `ring.*` que el servidor rechazó: la carpeta, la geometría, otra corrida."""
        self.lbl_error.setText(mensaje)

    def _set_corriendo(self, corriendo):
        self._corriendo = corriendo
        conectado = getattr(self, '_conectado', False)
        self.btn_iniciar.setEnabled(conectado and not corriendo)
        self.btn_parar.setEnabled(conectado and corriendo)

    def corriendo(self):
        return getattr(self, '_corriendo', False)

    def set_conectado(self, conectado, running=False):
        self._conectado = conectado
        self._set_corriendo(getattr(self, '_corriendo', False))
