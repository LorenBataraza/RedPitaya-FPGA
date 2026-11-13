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

Aparece sólo con el bitstream del ring: el del MCA no lo trae.
"""

import os
import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                             QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                             QWidget)

FS_HZ = 125e6
INT32_MAX = (1 << 31) - 1
VENTANA_MAX = 0x7FF                      # PRE y POST son de 11 bits
# El margen de disco que la sesión deja libre: el suyo (200 MB) en la SD o en la
# red, y 16 MB en /dev/shm, que en la placa tiene 231 MB en total.
MARGEN_SHM_MB = 16.0

MOTIVOS = {'disk': 'se llenó el disco (quedó el margen)',
           'source': 'el lector terminó solo',
           'error': 'se cayó un hilo de la sesión'}


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prev = None                    # (t, n_read) para la tasa de lectura
        self.ultimo = {}                     # el último estado, crudo (pruebas, scripts)
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        # Dos columnas, como la del generador: la configuración a la izquierda; a la
        # derecha los botones y el estado, que se miran mientras corre.
        izq = QWidget()
        izq.setMaximumWidth(460)
        v = QVBoxLayout(izq)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._grupo_ventana())
        v.addWidget(self._grupo_estimulo())
        v.addWidget(self._grupo_destino())
        v.addStretch(1)

        der = QWidget()
        der.setMaximumWidth(540)
        v = QVBoxLayout(der)
        v.setContentsMargins(0, 0, 0, 0)
        fila = QHBoxLayout()
        self.btn_iniciar = QPushButton('Iniciar')
        self.btn_iniciar.setToolTip('Arma el ring y la sesión, y empieza a escribir en '
                                    'una carpeta nueva.')
        self.btn_parar = QPushButton('Parar')
        self.btn_parar.setToolTip('Para la sesión y el ring; escribe lo que quedaba.')
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
        v.addWidget(self._grupo_estado())
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
        g = QGroupBox('Ventana')
        f = self._forma(g)
        self.spn_pre = QSpinBox(minimum=0, maximum=VENTANA_MAX, value=8)
        self.spn_post = QSpinBox(minimum=1, maximum=VENTANA_MAX, value=24)
        self.spn_pre.setToolTip('Muestras antes del disparo (8 ns cada una).')
        self.spn_post.setToolTip('Muestras desde el disparo.')
        f.addRow('antes, muestras', self.spn_pre)
        f.addRow('después, muestras', self.spn_post)
        self.cmb_canales = QComboBox()
        self.cmb_canales.addItem('IN1 e IN2', 2)
        self.cmb_canales.addItem('IN1', 1)
        self.cmb_canales.setToolTip('Los que se guardan. El ring escribe siempre los '
                                    'dos, así que el slot y la tasa no cambian.')
        f.addRow('canales', self.cmb_canales)
        return g

    def _grupo_estimulo(self):
        g = QGroupBox('Estímulo')
        f = self._forma(g)
        self.cmb_estimulo = QComboBox()
        self.cmb_estimulo.addItem('disparo del ADC', 'disparo')
        self.cmb_estimulo.addItem('generador de eventos', 'generador')
        self.cmb_estimulo.setToolTip(
            'Disparo del ADC: la ventana es la señal de la entrada. Generador de '
            'eventos: dispara solo y cada slot trae un patrón conocido, para medir el '
            'camino a disco sin señal.')
        self.cmb_estimulo.currentIndexChanged.connect(self._cambio_estimulo)
        f.addRow('fuente', self.cmb_estimulo)

        self.spn_thr = QDoubleSpinBox(decimals=3, minimum=-1.0, maximum=1.0,
                                      value=0.1, singleStep=0.01)
        self.spn_hyst = QDoubleSpinBox(decimals=3, minimum=0.0, maximum=1.0,
                                       value=0.02, singleStep=0.005)
        self.spn_thr.setToolTip('Flanco positivo del ADC, en volts.')
        self.spn_hyst.setToolTip('Re-arma cuando la señal baja de umbral − histéresis.')
        f.addRow('umbral, V', self.spn_thr)
        f.addRow('histéresis, V', self.spn_hyst)

        self.cmb_modo = QComboBox()
        self.cmb_modo.addItem('periódico', False)
        self.cmb_modo.addItem('Poisson', True)
        self.cmb_modo.currentIndexChanged.connect(self._cambio_estimulo)
        self.spn_tasa = QDoubleSpinBox(decimals=0, minimum=1.0, maximum=FS_HZ / 2,
                                       value=100e3, singleStep=10e3)
        self.spn_tasa.setToolTip('Disparos por segundo del generador.')
        self.spn_dt_min = QSpinBox(minimum=2, maximum=0xFFFF, value=2)
        self.spn_dt_min.setToolTip('Ciclos mínimos entre disparos (Poisson).')
        self.spn_n = QSpinBox(minimum=0, maximum=INT32_MAX, value=0)
        self.spn_n.setSpecialValueText('sin fin')
        self.spn_n.setToolTip('Cuántos disparos; al llegar, el generador para (la '
                              'sesión sigue hasta «Parar»).')
        f.addRow('modo', self.cmb_modo)
        f.addRow('tasa, 1/s', self.spn_tasa)
        f.addRow('separación mín., ciclos', self.spn_dt_min)
        f.addRow('disparos', self.spn_n)
        self._form_estimulo = f
        self._cambio_estimulo()
        return g

    def _grupo_destino(self):
        g = QGroupBox('Destino (en la placa)')
        f = self._forma(g)
        self.ed_carpeta = QLineEdit('/dev/shm')
        self.ed_carpeta.setMinimumWidth(220)
        self.ed_carpeta.setToolTip(
            'Una carpeta que exista en la placa: la corrida va en una subcarpeta nueva, '
            'ring_<fecha>_<hora>. /dev/shm es RAM (231 MB, se pierde al apagar); la SD '
            'o un montaje de red guardan.')
        f.addRow('carpeta', self.ed_carpeta)
        self.cmb_formato = QComboBox()
        self.cmb_formato.addItem('NumPy (.npz)', 'npz')
        self.cmb_formato.addItem('LH5 (HDF5)', 'lh5')
        f.addRow('formato', self.cmb_formato)
        self.spn_ram = QDoubleSpinBox(decimals=0, minimum=8, maximum=256, value=64)
        self.spn_ram.setToolTip('Memoria de la sesión para los eventos en vuelo.')
        f.addRow('RAM, MB', self.spn_ram)
        self.spn_margen = QDoubleSpinBox(decimals=0, minimum=0, maximum=10000, value=0)
        self.spn_margen.setSpecialValueText('automático')
        self.spn_margen.setToolTip(
            'Lo que la sesión deja libre en el disco: se para sola por debajo. '
            f'Automático: {MARGEN_SHM_MB:.0f} MB en /dev/shm, 200 MB en otro lado.')
        f.addRow('margen, MB', self.spn_margen)
        return g

    def _grupo_estado(self):
        g = QGroupBox('Estado')
        f = self._forma(g)
        self.lbl_estado = QLabel('—')
        self.lbl_run_dir = QLabel('—')
        self.lbl_run_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
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
        self.bar_ring.setToolTip('Los slots escritos en la DDR que el lector todavía no '
                                 'leyó. Lleno, cada disparo nuevo es un DROP_FULL.')
        f.addRow('estado', self.lbl_estado)
        f.addRow('corrida', self.lbl_run_dir)
        f.addRow('disparos', self.lbl_disparos)
        f.addRow('generados', self.lbl_generados)
        f.addRow('capturados (EV_CNT)', self.lbl_ev)
        f.addRow('captura ocupada (DROP_BUSY)', self.lbl_busy)
        f.addRow('ring lleno (DROP_FULL)', self.lbl_full)
        f.addRow('leídos', self.lbl_leidos)
        f.addRow('escritos', self.lbl_escritos)
        f.addRow('lectura, eventos/s', self.lbl_tasa)
        f.addRow('sin leer en la DDR', self.bar_ring)
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
        f = self._form_estimulo
        for w, ver in ((self.spn_thr, not gen), (self.spn_hyst, not gen),
                       (self.cmb_modo, gen), (self.spn_tasa, gen),
                       (self.spn_dt_min, gen and bool(self.cmb_modo.currentData())),
                       (self.spn_n, gen)):
            w.setVisible(ver)
            f.labelForField(w).setVisible(ver)

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
            raise ValueError(f'carpeta {carpeta!r}: tiene que ser un camino absoluto '
                             'de la placa')
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
            kw['disparo'] = {'thr': float(self.spn_thr.value()),
                             'hyst': float(self.spn_hyst.value())}
        return kw

    def _iniciar(self):
        try:
            kw = self.argumentos()
        except ValueError as e:
            self.lbl_error.setText(f'no se inició: {e}')
            self.log.emit(f'ring: no se inició: {e}')
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
            texto = 'corriendo'
        elif e.get('stats') is None:
            texto = 'sin adquisición'
        else:
            texto = 'parado'
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
            self.lbl_run_dir.setText(f'{nombre}\nen {padre}{fs}')
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
                self.lbl_generados.setText(_n(gen) + (' (terminó)' if hw.get(
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
                                      f"({int(stats.get('chunks', 0))} archivos)")
            ahora = time.monotonic()
            if corriendo and self._prev is not None and ahora > self._prev[0]:
                tasa = (leidos - self._prev[1]) / (ahora - self._prev[0])
                self.lbl_tasa.setText(f'{tasa:.4g}')
            elif not corriendo and stats.get('rate_ev_s') is not None:
                self.lbl_tasa.setText(f"{stats['rate_ev_s']:.4g} (media)")
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
