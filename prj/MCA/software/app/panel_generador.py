#!/usr/bin/env python3
"""Pestaña «Generator»: el generador de pulsos `gen_pulsos` (slot 2, 0x4021_0000) y
el lazo digital, por etapa de la ecuación.

El generador hace pulsos de preamplificador dentro de la FPGA, en el lugar del ASG
de Red Pitaya:

    v(t) = sat14( B + Σ_k A_k h(t − t_k) + r(t) )

Con el **lazo digital** (`digital_loop[0]` de HK) la entrada del datapath deja de
ser el ADC: IN1 recibe OUT1 del generador e IN2 recibe OUT2. Así el MCA se prueba
sin el Rigol y con pulsos conocidos. Sin el lazo, la salida va igual al DAC (los
SMA de OUT1 y OUT2).

Arriba, la franja (`diagrama_gen.py`): los disparos (t_k), la amplitud (A_k), la
forma (h) y la salida (B, r), con la tasa real, el estado de cada etapa y, con el
lazo, la λ̂ del MCA contra la tasa del generador. Abajo, los controles en el mismo
orden, con el color de su bloque; el foco o el ratón resaltan el bloque y un clic
en el bloque lleva a sus controles (`panel_etapas.py`).

**«Apply» escribe la configuración ENTERA y apaga el generador**
(`GenPulsos.configurar`): no hay escritura campo por campo como en las otras
pestañas, porque el motor de disparos se configura de una vez (la tasa da el
`UMBRAL` o el `PERIODO` según el modo). Por eso lo editado y todavía sin aplicar
lleva el punto naranja en su etapa, y se avisa al lado de «Apply». El lazo se
aplica en el momento.

Lo derivado (la tasa media que da de verdad, τ_d después de cuantizar `DECAE`, la
Mq del polo-cero y el sigma del ruido) lo calcula el servidor con libmca: el
cliente no la tiene. Docs: `docs/gen_eventos/generador_pulsos.md`.
"""

import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from app.diagrama_gen import COLOR, ETAPAS, DiagramaGen
from app.panel_etapas import PanelPorEtapas

# La tabla de amplitudes es de 14 bits con signo, como el DAC.
AMP_MIN, AMP_MAX = -8192, 8191
SAL_OUT1, SAL_OUT2 = 1 << 0, 1 << 1
FS_HZ = 125e6
INT32_MAX = (1 << 31) - 1                # el tope de un QSpinBox

_TITULO = {clave: titulo for clave, titulo, _d, _c in ETAPAS}


def leer_lineas(amplitudes, pesos):
    """[[amplitud, peso], ...] desde los dos campos de texto, o ValueError.

    Separados por coma o espacio. Sin pesos, iguales. Los pesos no hace falta que
    sumen 1: el servidor arma la tabla con la proporción.
    """
    def numeros(texto):
        return [float(x) for x in re.split(r'[,;\s]+', texto.strip()) if x]

    try:
        a = numeros(amplitudes)
        p = numeros(pesos)
    except ValueError as e:
        raise ValueError(f'not a number: {e}') from None
    if not a:
        raise ValueError('at least one amplitude is needed')
    for v in a:
        if v != round(v) or not AMP_MIN <= v <= AMP_MAX:
            raise ValueError(f'amplitude {v:g}: an integer from {AMP_MIN} to '
                             f'{AMP_MAX} (ADC counts)')
    if not p:
        p = [1.0] * len(a)
    if len(p) != len(a):
        raise ValueError(f'{len(a)} amplitudes and {len(p)} weights')
    if any(x < 0 for x in p) or sum(p) <= 0:
        raise ValueError('the weights are positive and not all zero')
    return [[int(v), w] for v, w in zip(a, p)]


class PanelGenerador(PanelPorEtapas):
    """Configuración, control y estado del generador de pulsos, y el lazo."""

    COLOR = COLOR

    pedir_configurar = pyqtSignal(dict)      # la configuración entera (gen.configurar)
    pedir_ctrl = pyqtSignal(str)             # 'arrancar' | 'parar'
    pedir_lazo = pyqtSignal(bool)
    pedir_refresco = pyqtSignal()
    pedir_campo_mca = pyqtSignal(str, int)   # la Mq al trapecio del MCA

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mq = None
        self._tasa_hz = None
        self._editadas = set()           # etapas con cambios sin aplicar
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        self.diagrama = DiagramaGen()
        self.diagrama.etapa_elegida.connect(self._ir_a_etapa)

        interior = QWidget()
        cols = QHBoxLayout(interior)
        cols.setContentsMargins(0, 0, 0, 0)
        # En el orden de la ecuación; a la derecha lo que se toca y se mira
        # mientras corre: los botones y el estado.
        for grupos in ((self._grupo_disparos(),),
                       (self._grupo_amplitud(), self._grupo_forma()),
                       (self._grupo_salida(), self._grupo_lazo()),
                       (self._caja_control(),)):
            v = QVBoxLayout()
            for g in grupos:
                v.addWidget(g)
            v.addStretch(1)
            cols.addLayout(v, 1)

        self.scroll = scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.addWidget(self.diagrama)
        caja.addWidget(scroll, 1)

    def _vigilar(self, etapa, *senales):
        """Un cambio en estas señales marca la etapa como editada sin aplicar."""
        for s in senales:
            s.connect(lambda *_a, e=etapa: self._editado(e))

    # ---------- las etapas, en el orden de la ecuación ----------

    def _grupo_disparos(self):
        g = self._grupo('disparos', 'Triggers (t_k)')
        f = self._forma(g)
        self.cmb_modo = QComboBox()
        self.cmb_modo.addItem('periodic', False)
        self.cmb_modo.addItem('Poisson', True)
        self.cmb_modo.setToolTip('Periodic: one pulse every PERIOD cycles. Poisson: '
                                 'exponential arrivals, with at least DT_MIN cycles '
                                 'between pulses.')
        self.cmb_modo.currentIndexChanged.connect(self._cambio_modo)
        f.addRow('mode', self.cmb_modo)

        self.spn_tasa = QDoubleSpinBox(decimals=0, minimum=1.0, maximum=FS_HZ / 2,
                                       value=10e3, singleStep=1000.0)
        self.spn_tasa.setToolTip('Pulses per second. The one it really gives, after '
                                 'quantizing PERIOD or THRESHOLD, is on the franja.')
        f.addRow('rate, 1/s', self.spn_tasa)

        self.spn_dt_min = QSpinBox(minimum=2, maximum=0xFFFF, value=3)
        self.spn_dt_min.setToolTip(
            'Minimum cycles between pulses (Poisson). With the trigger through the '
            'ASG source it has to be ≥ 3: the multitrigger does not accept two '
            'triggers less than 3 cycles apart.')
        f.addRow('min. gap, cycles', self.spn_dt_min)

        self.spn_n = QSpinBox(minimum=0, maximum=INT32_MAX, value=0)
        self.spn_n.setSpecialValueText('endless')
        self.spn_n.setToolTip('How many pulses; once reached, the generator stops '
                              'by itself.')
        f.addRow('pulses', self.spn_n)

        self.spn_semilla = QSpinBox(minimum=0, maximum=INT32_MAX, value=0)
        self.spn_semilla.setSpecialValueText('the usual one')
        self.spn_semilla.setToolTip('Of the three xorshifts (triggers, amplitude, '
                                    'noise). The same seed gives the same train.')
        f.addRow('seed', self.spn_semilla)
        self._vigilar('disparos', self.cmb_modo.currentIndexChanged,
                      self.spn_tasa.valueChanged, self.spn_dt_min.valueChanged,
                      self.spn_n.valueChanged, self.spn_semilla.valueChanged)
        self._cambio_modo()
        return g

    def _grupo_amplitud(self):
        g = self._grupo('amplitud', 'Amplitude (A_k)')
        f = self._forma(g)
        self.ed_amplitudes = QLineEdit('2000')
        self.ed_pesos = QLineEdit('')
        self.ed_pesos.setPlaceholderText('equal')
        for ed in (self.ed_amplitudes, self.ed_pesos):
            ed.setMinimumWidth(130)
        self.ed_amplitudes.setToolTip(
            f'ADC counts, from {AMP_MIN} to {AMP_MAX}, comma separated. A single one '
            'is the fixed amplitude; several are lines of a spectrum, drawn with the '
            'weights (the 1024-entry table by inverse CDF).')
        self.ed_pesos.setToolTip('One per amplitude. Empty: all equally likely.')
        f.addRow('amplitudes', self.ed_amplitudes)
        f.addRow('weights', self.ed_pesos)
        self.lbl_amp_modo = QLabel('—')
        self.lbl_amp_modo.setWordWrap(True)
        f.addRow('on the board', self.lbl_amp_modo)
        self._vigilar('amplitud', self.ed_amplitudes.textEdited,
                      self.ed_pesos.textEdited)
        return g

    def _grupo_forma(self):
        g = self._grupo('forma', 'Shape (h)')
        f = self._forma(g)
        self.spn_tau = QDoubleSpinBox(decimals=3, minimum=0.01, maximum=500.0,
                                      value=2.0, singleStep=0.1)
        self.spn_tau.setToolTip('The decay constant τ_d of the preamplifier. The '
                                'trapezoid and the pole-zero trigger cancel it with '
                                'the Mq on the franja.')
        f.addRow('decay τ_d, µs', self.spn_tau)
        self.cmb_subida = QComboBox()
        self.cmb_subida.addItem('no rise', 0)
        for k in range(1, 8):
            self.cmb_subida.addItem(f'τ_r ≈ {8 << k} ns', k)
        self.cmb_subida.setToolTip('An RC low-pass: τ_r ≈ 2^RISE · 8 ns. Without a '
                                   'rise the peak is exactly the amplitude.')
        f.addRow('rise', self.cmb_subida)
        self._vigilar('forma', self.spn_tau.valueChanged,
                      self.cmb_subida.currentIndexChanged)
        return g

    def _grupo_salida(self):
        g = self._grupo('salida', 'Output (B, r)')
        f = self._forma(g)
        self.spn_base = QSpinBox(minimum=AMP_MIN, maximum=AMP_MAX, value=0)
        self.spn_base.setToolTip('In ADC counts, added to the output. With the MCA '
                                 'fixed baseline at 0, it goes at 0.')
        f.addRow('base B', self.spn_base)
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        self.chk_ruido = QCheckBox('noise, sh')
        self.spn_sh = QSpinBox(minimum=0, maximum=15, value=6)
        self.spn_sh.setToolTip('σ = 147.8 / 2^sh counts: sh = 6 gives 2.3.')
        self.chk_ruido.toggled.connect(self.spn_sh.setEnabled)
        self.spn_sh.setEnabled(False)
        fila.addWidget(self.chk_ruido)
        fila.addWidget(self.spn_sh)
        fila.addStretch(1)
        f.addRow('r', fila)
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        self.chk_out1 = QCheckBox('OUT1')
        self.chk_out2 = QCheckBox('OUT2')
        for chk in (self.chk_out1, self.chk_out2):
            chk.setToolTip('Which DAC channel the output goes to. With the loopback, '
                           'OUT1 reaches IN1 and OUT2 reaches IN2.')
        self.chk_out1.setChecked(True)
        fila.addWidget(self.chk_out1)
        fila.addWidget(self.chk_out2)
        fila.addStretch(1)
        f.addRow('channels', fila)
        self._vigilar('salida', self.spn_base.valueChanged, self.chk_ruido.toggled,
                      self.spn_sh.valueChanged, self.chk_out1.toggled,
                      self.chk_out2.toggled)
        return g

    def _grupo_lazo(self):
        g = self._grupo('salida', 'Digital loopback')
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 4)
        self.chk_lazo = QCheckBox('MCA input = generator')
        self.chk_lazo.setToolTip(
            'digital_loop[0]: IN1 gets OUT1 of the generator and IN2 gets OUT2; the '
            'ADC is disconnected. It applies at once, without «Apply».')
        self.chk_lazo.toggled.connect(self.pedir_lazo)
        self.chk_lazo.toggled.connect(self.diagrama.set_lazo)
        v.addWidget(self.chk_lazo)
        return g

    def _caja_control(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        fila = QGridLayout()
        self.btn_aplicar = QPushButton('Apply')
        self.btn_aplicar.setToolTip('Writes the whole configuration and the table. It '
                                    'stops the generator: then, «Start».')
        self.btn_arrancar = QPushButton('Start')
        self.btn_parar = QPushButton('Stop')
        self.btn_releer = QPushButton('Reread')
        self.btn_releer.setToolTip('Reloads the fields with what the board has, '
                                   'discarding what was not applied.')
        self.btn_aplicar.clicked.connect(self._aplicar)
        self.btn_arrancar.clicked.connect(lambda: self.pedir_ctrl.emit('arrancar'))
        self.btn_parar.clicked.connect(lambda: self.pedir_ctrl.emit('parar'))
        self.btn_releer.clicked.connect(self.pedir_refresco)
        # Dos por fila: aplicar o releer la configuración; arrancar o parar.
        for i, b in enumerate((self.btn_aplicar, self.btn_releer, self.btn_arrancar,
                               self.btn_parar)):
            fila.addWidget(b, i // 2, i % 2)
        v.addLayout(fila)
        # Lo editado sin aplicar, y lo que no se pudo aplicar, al lado del botón y
        # sin diálogo modal: los campos quedan como estaban para corregirlos.
        self.lbl_pendiente = QLabel('')
        self.lbl_pendiente.setStyleSheet('color: #b9600f;')
        self.lbl_pendiente.setWordWrap(True)
        v.addWidget(self.lbl_pendiente)
        self.lbl_error = QLabel('')
        self.lbl_error.setStyleSheet('color: #c0392b;')
        self.lbl_error.setWordWrap(True)
        v.addWidget(self.lbl_error)
        v.addWidget(self._grupo_estado())
        return w

    def _grupo_estado(self):
        g = QGroupBox('Status')
        f = self._forma(g)
        self.lbl_estado = QLabel('—')
        self.lbl_cnt = QLabel('—')
        f.addRow('status', self.lbl_estado)
        f.addRow('generated', self.lbl_cnt)
        # La tasa, τ_d y σ van en la franja; los rótulos quedan para las pruebas y
        # los scripts, fuera del formulario.
        self.lbl_tasa = QLabel('—', self)
        self.lbl_tau = QLabel('—', self)
        self.lbl_sigma = QLabel('—', self)
        for lbl in (self.lbl_tasa, self.lbl_tau, self.lbl_sigma):
            lbl.hide()

        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        self.lbl_mq = QLabel('—')
        self.btn_mq = QPushButton('to the trapezoid')
        self.btn_mq.setToolTip('The pole-zero Mq of this decay. Writes it into '
                               'trap_mq of the MCA, so the trapezoid cancels the '
                               'decay of these pulses.')
        self.btn_mq.clicked.connect(self._mq_al_mca)
        fila.addWidget(self.lbl_mq)
        fila.addWidget(self.btn_mq)
        fila.addStretch(1)
        f.addRow('Mq', fila)
        self.lbl_base_dir = QLabel('—')
        f.addRow('block base', self.lbl_base_dir)
        return g

    # =========================================================================
    # Acciones
    # =========================================================================

    def _cambio_modo(self, *_):
        self.spn_dt_min.setEnabled(bool(self.cmb_modo.currentData()))

    def _editado(self, etapa):
        if self._cargando:
            return
        self._editadas.add(etapa)
        self._pintar_pendiente()

    def _pintar_pendiente(self):
        self.diagrama.marcar(self._editadas)
        if self._editadas:
            nombres = ', '.join(_TITULO[k] for k, *_r in ETAPAS if k in self._editadas)
            self.lbl_pendiente.setText(f'Edited, not applied: {nombres}. «Apply» '
                                       'writes everything and stops the generator.')
        else:
            self.lbl_pendiente.setText('')

    @property
    def editadas(self):
        return set(self._editadas)

    def configuracion(self):
        """Lo que hay en los campos, como lo pide `gen.configurar`. ValueError si
        las amplitudes no se entienden."""
        salidas = ((SAL_OUT1 if self.chk_out1.isChecked() else 0)
                   | (SAL_OUT2 if self.chk_out2.isChecked() else 0))
        return {'aleatorio': bool(self.cmb_modo.currentData()),
                'tasa': float(self.spn_tasa.value()),
                'dt_min': int(self.spn_dt_min.value()),
                'n': int(self.spn_n.value()),
                'semilla': int(self.spn_semilla.value()),
                'lineas': leer_lineas(self.ed_amplitudes.text(),
                                      self.ed_pesos.text()),
                'tau_us': float(self.spn_tau.value()),
                'subida': int(self.cmb_subida.currentData()),
                'base': int(self.spn_base.value()),
                'ruido': int(self.chk_ruido.isChecked()),
                'ruido_sh': int(self.spn_sh.value()),
                'salidas': salidas}

    def _aplicar(self):
        try:
            cfg = self.configuracion()
            if not cfg['salidas']:
                raise ValueError('no output channel: the generator would not reach '
                                 'anything')
        except ValueError as e:
            self.lbl_error.setText(f'not applied: {e}')
            self.log.emit(f'generator: not applied: {e}')
            return
        self.lbl_error.setText('')
        self.pedir_configurar.emit(cfg)

    def _mq_al_mca(self):
        if self._mq is not None:
            self.pedir_campo_mca.emit('trap_mq', int(self._mq))
            self.log.emit(f'trap_mq = {self._mq} (the generator decay)')

    # =========================================================================
    # Desde el servidor
    # =========================================================================

    def actualizar_gen(self, info):
        """El `gen.get`: repuebla los campos con lo que tiene la placa. Lo que se
        había editado sin aplicar se pierde: los campos vuelven a decir lo de la
        placa, y se van las marcas."""
        cfg = info.get('config', {})
        self._cargando = True
        try:
            self.cmb_modo.setCurrentIndex(1 if cfg.get('aleatorio') else 0)
            tasa = float(info.get('tasa_hz', 0.0))
            if tasa > 0:
                self.spn_tasa.setValue(round(tasa))
            self.spn_dt_min.setValue(int(cfg.get('dt_min', 2)))
            self.spn_n.setValue(min(int(cfg.get('n', 0)), INT32_MAX))
            self.spn_semilla.setValue(min(int(cfg.get('semilla', 0)), INT32_MAX))
            self.spn_tau.setValue(float(info.get('tau_us', self.spn_tau.value())))
            self.cmb_subida.setCurrentIndex(int(cfg.get('subida', 0)) & 7)
            self.spn_base.setValue(int(cfg.get('base', 0)))
            self.chk_ruido.setChecked(bool(cfg.get('ruido')))
            # Con el ruido apagado, el `sh` de la placa es el del reset (0, σ = 148
            # cuentas): copiarlo haría que prender el ruido después diera eso. Se
            # deja el del panel.
            if cfg.get('ruido'):
                self.spn_sh.setValue(int(cfg.get('ruido_sh', 6)))
            # Recién cargado el bitstream CTRL está en 0 y `salidas` se relee 0. Se
            # muestra OUT1, el de `API.generadores.config`: es lo que se aplicaría.
            sal = int(cfg.get('salidas', 0)) or SAL_OUT1
            self.chk_out1.setChecked(bool(sal & SAL_OUT1))
            self.chk_out2.setChecked(bool(sal & SAL_OUT2))

            lineas = info.get('lineas') or []
            if lineas:
                self.ed_amplitudes.setText(', '.join(str(int(a)) for a, _p in lineas))
                self.ed_pesos.setText('' if len(lineas) == 1 else
                                      ', '.join(f'{p:.4g}' for _a, p in lineas))
        finally:
            self._cargando = False
        self._editadas.clear()
        self._pintar_pendiente()

        if len(lineas) == 1:
            modo = 'one fixed amplitude'
        elif cfg.get('amp_aleat'):
            modo = f'{len(lineas)} lines, drawn'
        else:
            modo = (f'{len(lineas)} values IN ORDER (a sweep): «Apply» changes it '
                    'to drawn')
        self.lbl_amp_modo.setText(modo)

        self._tasa_hz = tasa
        self.lbl_tasa.setText(f'{tasa:.6g}')
        self.lbl_tau.setText(f"{info.get('tau_us', 0.0):.4f}")
        self._mq = info.get('mq')
        self.lbl_mq.setText(str(self._mq) if self._mq is not None else '—')
        self.lbl_sigma.setText(f"{info.get('sigma_ruido', 0.0):.3g}"
                               if cfg.get('ruido') else 'no noise')
        base = info.get('base', 0)
        self.lbl_base_dir.setText(f'{base:#010x}' if base else '—')
        self.diagrama.actualizar_gen(info)
        est = dict(info.get('estado') or {})
        est['lazo'] = info.get('lazo')
        self.actualizar_estado(est)

    def actualizar_estado(self, est):
        """El estado corto, que viene en cada `status` (`gen`) o en el `gen.get`."""
        if not est:
            return
        self.diagrama.actualizar_estado(est)
        if est.get('error'):
            self.lbl_estado.setText(f"error: {est['error']}")
            return
        if est.get('desborde'):
            texto = 'shape OVERFLOW: lower the amplitudes or the rate'
        elif est.get('generando'):
            texto = 'generating'
        elif est.get('terminado'):
            texto = 'finished (reached N)'
        else:
            texto = 'stopped'
        self.lbl_estado.setText(texto)
        self.lbl_cnt.setText(f"{int(est.get('gen_cnt', 0)):,}".replace(',', ' '))
        if est.get('lazo') is not None:
            self.chk_lazo.blockSignals(True)
            self.chk_lazo.setChecked(bool(est['lazo']))
            self.chk_lazo.blockSignals(False)
            self.diagrama.set_lazo(bool(est['lazo']))
        self.btn_arrancar.setEnabled(self.btn_releer.isEnabled()
                                     and not est.get('generando'))
        self.btn_parar.setEnabled(self.btn_releer.isEnabled()
                                  and bool(est.get('generando')))

    def actualizar_mca(self, est):
        """El `status` del MCA: su tasa de entrada λ̂, para compararla con la del
        generador cuando el lazo está prendido."""
        if est.get('presente'):
            self.diagrama.actualizar_mca(est.get('tasa_entrada_hz'))

    def set_conectado(self, conectado, running=False):
        super().set_conectado(conectado, running)
        for w in (self.chk_lazo, self.btn_aplicar, self.btn_arrancar,
                  self.btn_parar, self.btn_releer, self.btn_mq):
            w.setEnabled(conectado)
        if not conectado:
            self.diagrama.limpiar()
