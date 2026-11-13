#!/usr/bin/env python3
"""Pestaña del generador de pulsos: `gen_pulsos` (slot 2, 0x4021_0000) y el lazo
digital.

El generador hace pulsos de preamplificador dentro de la FPGA, en el lugar del ASG
de Red Pitaya:

    v(t) = sat14( B + Σ_k A_k h(t − t_k) + r(t) )

Con el **lazo digital** (`digital_loop[0]` de HK) la entrada del datapath deja de
ser el ADC: IN1 recibe OUT1 del generador e IN2 recibe OUT2. Así el MCA se prueba
sin el Rigol y con pulsos conocidos. Sin el lazo, la salida va igual al DAC (los
SMA de OUT1 y OUT2).

Los grupos siguen los términos de la ecuación: los disparos (t_k), la amplitud
(A_k), la forma (h) y la salida (B, r). Docs: `docs/gen_eventos/generador_pulsos.md`.

**«Aplicar» escribe la configuración ENTERA y apaga el generador**
(`GenPulsos.configurar`): no hay escritura campo por campo como en las otras
pestañas, porque el motor de disparos se configura de una vez (la tasa da el
`UMBRAL` o el `PERIODO` según el modo).

Lo derivado (la tasa media que da de verdad, τ_d después de cuantizar `DECAE`, la
Mq del polo-cero y el sigma del ruido) lo calcula el servidor con libmca: el
cliente no la tiene.
"""

import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                             QWidget)

# La tabla de amplitudes es de 14 bits con signo, como el DAC.
AMP_MIN, AMP_MAX = -8192, 8191
SAL_OUT1, SAL_OUT2 = 1 << 0, 1 << 1
FS_HZ = 125e6
INT32_MAX = (1 << 31) - 1                # el tope de un QSpinBox


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
        raise ValueError(f'no es un número: {e}') from None
    if not a:
        raise ValueError('hace falta al menos una amplitud')
    for v in a:
        if v != round(v) or not AMP_MIN <= v <= AMP_MAX:
            raise ValueError(f'amplitud {v:g}: un entero de {AMP_MIN} a {AMP_MAX} '
                             '(cuentas del ADC)')
    if not p:
        p = [1.0] * len(a)
    if len(p) != len(a):
        raise ValueError(f'{len(a)} amplitudes y {len(p)} pesos')
    if any(x < 0 for x in p) or sum(p) <= 0:
        raise ValueError('los pesos son positivos y no todos cero')
    return [[int(v), w] for v, w in zip(a, p)]


class PanelGenerador(QWidget):
    """Configuración, control y estado del generador de pulsos, y el lazo."""

    pedir_configurar = pyqtSignal(dict)      # la configuración entera (gen.configurar)
    pedir_ctrl = pyqtSignal(str)             # 'arrancar' | 'parar'
    pedir_lazo = pyqtSignal(bool)
    pedir_refresco = pyqtSignal()
    pedir_campo_mca = pyqtSignal(str, int)   # la Mq al trapecio del MCA
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mq = None
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        # Dos columnas: a la izquierda la configuración, en el orden de la
        # ecuación; a la derecha lo que se toca y se mira mientras corre (el lazo,
        # los botones y el estado), para que no haga falta desplazar para
        # arrancar o parar.
        izq = QWidget()
        izq.setMaximumWidth(460)
        v = QVBoxLayout(izq)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._grupo_disparos())
        v.addWidget(self._grupo_amplitud())
        v.addWidget(self._grupo_forma())
        v.addWidget(self._grupo_salida())
        v.addStretch(1)

        der = QWidget()
        der.setMaximumWidth(460)
        v = QVBoxLayout(der)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._grupo_lazo())
        v.addLayout(self._botones())
        # Lo que no se pudo aplicar, al lado del botón y sin diálogo modal: los
        # campos quedan como estaban para corregirlos.
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

    def _grupo_lazo(self):
        g = QGroupBox('Lazo digital')
        v = QVBoxLayout(g)
        self.chk_lazo = QCheckBox('la entrada es el generador (digital_loop[0])')
        self.chk_lazo.setToolTip(
            'IN1 recibe OUT1 del generador e IN2 recibe OUT2; el ADC queda '
            'desconectado. Se aplica en el momento, sin «Aplicar».')
        self.chk_lazo.toggled.connect(self.pedir_lazo)
        v.addWidget(self.chk_lazo)
        return g

    def _grupo_disparos(self):
        g = QGroupBox('Disparos (t_k)')
        f = self._forma(g)
        self.cmb_modo = QComboBox()
        self.cmb_modo.addItem('periódico', False)
        self.cmb_modo.addItem('Poisson', True)
        self.cmb_modo.setToolTip('Periódico: un pulso cada PERIODO ciclos. Poisson: '
                                 'arribos exponenciales, con un mínimo de DT_MIN '
                                 'ciclos entre pulsos.')
        self.cmb_modo.currentIndexChanged.connect(self._cambio_modo)
        f.addRow('modo', self.cmb_modo)

        self.spn_tasa = QDoubleSpinBox(decimals=0, minimum=1.0, maximum=FS_HZ / 2,
                                       value=10e3, singleStep=1000.0)
        self.spn_tasa.setToolTip('Pulsos por segundo. La que da de verdad, después '
                                 'de cuantizar PERIODO o UMBRAL, va en el estado.')
        f.addRow('tasa, 1/s', self.spn_tasa)

        self.spn_dt_min = QSpinBox(minimum=2, maximum=0xFFFF, value=3)
        self.spn_dt_min.setToolTip(
            'Ciclos mínimos entre pulsos (Poisson). Con el disparo por la fuente ASG '
            'tiene que ser ≥ 3: el multitrigger no acepta dos disparos a menos de 3 '
            'ciclos.')
        f.addRow('separación mín., ciclos', self.spn_dt_min)

        self.spn_n = QSpinBox(minimum=0, maximum=INT32_MAX, value=0)
        self.spn_n.setSpecialValueText('sin fin')
        self.spn_n.setToolTip('Cuántos pulsos; al llegar, el generador para solo.')
        f.addRow('pulsos', self.spn_n)

        self.spn_semilla = QSpinBox(minimum=0, maximum=INT32_MAX, value=0)
        self.spn_semilla.setSpecialValueText('la de siempre')
        self.spn_semilla.setToolTip('De los tres xorshift (disparos, amplitud, '
                                    'ruido). La misma semilla da el mismo tren.')
        f.addRow('semilla', self.spn_semilla)
        self._cambio_modo()
        return g

    def _grupo_amplitud(self):
        g = QGroupBox('Amplitud (A_k)')
        f = self._forma(g)
        self.ed_amplitudes = QLineEdit('2000')
        self.ed_pesos = QLineEdit('')
        self.ed_pesos.setPlaceholderText('iguales')
        for ed in (self.ed_amplitudes, self.ed_pesos):
            ed.setMinimumWidth(220)
        self.ed_amplitudes.setToolTip(
            f'Cuentas del ADC, de {AMP_MIN} a {AMP_MAX}, separadas por coma. Una sola '
            'es la amplitud fija; varias son líneas de un espectro, sorteadas con los '
            'pesos (la tabla de 1024 entradas por CDF inversa).')
        self.ed_pesos.setToolTip('Uno por amplitud. Vacío: todas igual de probables.')
        f.addRow('amplitudes, cuentas', self.ed_amplitudes)
        f.addRow('pesos', self.ed_pesos)
        self.lbl_amp_modo = QLabel('—')
        f.addRow('en la placa', self.lbl_amp_modo)
        return g

    def _grupo_forma(self):
        g = QGroupBox('Forma (h)')
        f = self._forma(g)
        self.spn_tau = QDoubleSpinBox(decimals=3, minimum=0.01, maximum=500.0,
                                      value=2.0, singleStep=0.1)
        self.spn_tau.setToolTip('La constante de caída τ_d del preamplificador. El '
                                'trapecio y el disparo con polo-cero la cancelan con '
                                'la Mq del estado.')
        f.addRow('caída τ_d, µs', self.spn_tau)
        self.cmb_subida = QComboBox()
        self.cmb_subida.addItem('sin subida', 0)
        for k in range(1, 8):
            self.cmb_subida.addItem(f'τ_r ≈ {8 << k} ns', k)
        self.cmb_subida.setToolTip('Un pasabajos RC: τ_r ≈ 2^SUBIDA · 8 ns. Sin subida '
                                   'el pico es exactamente la amplitud.')
        f.addRow('subida', self.cmb_subida)
        return g

    def _grupo_salida(self):
        g = QGroupBox('Salida (B, r)')
        f = self._forma(g)
        self.spn_base = QSpinBox(minimum=AMP_MIN, maximum=AMP_MAX, value=0)
        self.spn_base.setToolTip('Sumada a la salida. Con la base fija del MCA en 0, '
                                 'va en 0.')
        f.addRow('base B, cuentas', self.spn_base)
        fila = QHBoxLayout()
        self.chk_ruido = QCheckBox('ruido, sh')
        self.spn_sh = QSpinBox(minimum=0, maximum=15, value=6)
        self.spn_sh.setToolTip('σ = 147.8 / 2^sh cuentas: sh = 6 da 2.3.')
        self.chk_ruido.toggled.connect(self.spn_sh.setEnabled)
        self.spn_sh.setEnabled(False)
        fila.addWidget(self.chk_ruido)
        fila.addWidget(self.spn_sh)
        fila.addStretch(1)
        f.addRow('r', fila)
        fila = QHBoxLayout()
        self.chk_out1 = QCheckBox('OUT1 → IN1')
        self.chk_out2 = QCheckBox('OUT2 → IN2')
        for chk in (self.chk_out1, self.chk_out2):
            chk.setToolTip('A qué canal del DAC va la salida; con el lazo, a qué '
                           'entrada llega.')
        self.chk_out1.setChecked(True)
        fila.addWidget(self.chk_out1)
        fila.addWidget(self.chk_out2)
        fila.addStretch(1)
        f.addRow('canales', fila)
        return g

    def _botones(self):
        fila = QHBoxLayout()
        self.btn_aplicar = QPushButton('Aplicar')
        self.btn_aplicar.setToolTip('Escribe toda la configuración y la tabla. Apaga '
                                    'el generador: después, «Arrancar».')
        self.btn_arrancar = QPushButton('Arrancar')
        self.btn_parar = QPushButton('Parar')
        self.btn_releer = QPushButton('Releer')
        self.btn_releer.setToolTip('Vuelve a cargar los campos con lo que tiene la '
                                   'placa, descartando lo que no se aplicó.')
        self.btn_aplicar.clicked.connect(self._aplicar)
        self.btn_arrancar.clicked.connect(lambda: self.pedir_ctrl.emit('arrancar'))
        self.btn_parar.clicked.connect(lambda: self.pedir_ctrl.emit('parar'))
        self.btn_releer.clicked.connect(self.pedir_refresco)
        for b in (self.btn_aplicar, self.btn_arrancar, self.btn_parar,
                  self.btn_releer):
            fila.addWidget(b)
        fila.addStretch(1)
        return fila

    def _grupo_estado(self):
        g = QGroupBox('Estado')
        f = self._forma(g)
        self.lbl_estado = QLabel('—')
        self.lbl_cnt = QLabel('—')
        self.lbl_tasa = QLabel('—')
        self.lbl_tau = QLabel('—')
        self.lbl_sigma = QLabel('—')
        self.lbl_base_dir = QLabel('—')
        f.addRow('estado', self.lbl_estado)
        f.addRow('pulsos generados', self.lbl_cnt)
        f.addRow('tasa media, 1/s', self.lbl_tasa)
        f.addRow('τ_d, µs', self.lbl_tau)
        f.addRow('σ del ruido, cuentas', self.lbl_sigma)

        fila = QHBoxLayout()
        self.lbl_mq = QLabel('—')
        self.btn_mq = QPushButton('al trapecio del MCA')
        self.btn_mq.setToolTip('Escribe esta Mq en trap_mq del MCA, para que el '
                               'trapecio cancele la caída de estos pulsos.')
        self.btn_mq.clicked.connect(self._mq_al_mca)
        fila.addWidget(self.lbl_mq)
        fila.addWidget(self.btn_mq)
        fila.addStretch(1)
        f.addRow('Mq del polo-cero', fila)
        f.addRow('base', self.lbl_base_dir)
        return g

    # =========================================================================
    # Acciones
    # =========================================================================

    def _cambio_modo(self, *_):
        self.spn_dt_min.setEnabled(bool(self.cmb_modo.currentData()))

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
                raise ValueError('ningún canal de salida: el generador no llegaría '
                                 'a ningún lado')
        except ValueError as e:
            self.lbl_error.setText(f'no se aplicó: {e}')
            self.log.emit(f'generador: no se aplicó: {e}')
            return
        self.lbl_error.setText('')
        self.pedir_configurar.emit(cfg)

    def _mq_al_mca(self):
        if self._mq is not None:
            self.pedir_campo_mca.emit('trap_mq', int(self._mq))
            self.log.emit(f'trap_mq = {self._mq} (la caída del generador)')

    # =========================================================================
    # Desde el servidor
    # =========================================================================

    def actualizar_gen(self, info):
        """El `gen.get`: repuebla los campos con lo que tiene la placa."""
        cfg = info.get('config', {})
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
        if len(lineas) == 1:
            modo = 'una amplitud fija'
        elif cfg.get('amp_aleat'):
            modo = f'{len(lineas)} líneas sorteadas'
        else:
            modo = (f'{len(lineas)} valores EN ORDEN (un barrido): «Aplicar» lo '
                    'cambia a sorteado')
        self.lbl_amp_modo.setText(modo)

        self.lbl_tasa.setText(f'{tasa:.6g}')
        self.lbl_tau.setText(f"{info.get('tau_us', 0.0):.4f}")
        self._mq = info.get('mq')
        self.lbl_mq.setText(str(self._mq) if self._mq is not None else '—')
        self.lbl_sigma.setText(f"{info.get('sigma_ruido', 0.0):.3g}"
                               if cfg.get('ruido') else 'sin ruido')
        base = info.get('base', 0)
        self.lbl_base_dir.setText(f'{base:#010x}' if base else '—')
        est = dict(info.get('estado') or {})
        est['lazo'] = info.get('lazo')
        self.actualizar_estado(est)

    def actualizar_estado(self, est):
        """El estado corto, que viene en cada `status` (`gen`) o en el `gen.get`."""
        if not est:
            return
        if est.get('error'):
            self.lbl_estado.setText(f"error: {est['error']}")
            return
        if est.get('desborde'):
            texto = 'DESBORDE de la forma: bajar las amplitudes o la tasa'
        elif est.get('generando'):
            texto = 'generando'
        elif est.get('terminado'):
            texto = 'terminó (llegó a N)'
        else:
            texto = 'parado'
        self.lbl_estado.setText(texto)
        self.lbl_cnt.setText(f"{int(est.get('gen_cnt', 0)):,}".replace(',', ' '))
        if est.get('lazo') is not None:
            self.chk_lazo.blockSignals(True)
            self.chk_lazo.setChecked(bool(est['lazo']))
            self.chk_lazo.blockSignals(False)
        self.btn_arrancar.setEnabled(self.btn_releer.isEnabled()
                                     and not est.get('generando'))
        self.btn_parar.setEnabled(self.btn_releer.isEnabled()
                                  and bool(est.get('generando')))

    def set_conectado(self, conectado, running=False):
        for w in (self.chk_lazo, self.btn_aplicar, self.btn_arrancar,
                  self.btn_parar, self.btn_releer, self.btn_mq):
            w.setEnabled(conectado)
