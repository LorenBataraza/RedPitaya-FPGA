#!/usr/bin/env python3
"""Pestaña del multitrigger: todo lo que genera el disparo, por etapa.

Hay UN disparo: el `trigger_event` del multitrigger, el mismo para la captura del
osciloscopio, el MCA y el ring. Ninguno de los tres tiene un disparo propio, así que
esta pestaña es el único lugar donde se configura. «OSC settings» y «Spectrum» sólo
muestran su estado (Spectrum guarda un atajo para armar el del MCA), y «MCA settings»
configura lo que el MCA hace cuando le llega (las ranuras).

Arriba, la franja (`diagrama_mt.py`): las fuentes, la máscara OR, el evento y el
shield, con lo que está mal puesto en rojo y lo que el MCA ve del disparo (la tasa,
el veto, el tiempo sin re-armar). Abajo, los controles por etapa, con el color de su
bloque; el grupo con el foco o el ratón se resalta en la franja y un clic en un
bloque lleva a sus controles (`panel_etapas.py`):

  - **las fuentes**: el Schmitt de nivel (umbral, histéresis y el debounce de DIO0)
    y el disparo del MCA (pendiente o polo-cero, con «Arm for the MCA»). Los del
    nivel son registros del OSC (slot 1, donde los tiene Red Pitaya y los escribe
    `librp`): el comparador está en `mt_top`, que los recibe por puerto. Por eso
    esos campos van a `osc.set` (`pedir_campo_osc`) y los demás a `mtrg.set`;
  - **las máscaras OR**: una grilla de fuentes × canal, con las dos polaridades. Los
    nombres de los bits vienen del servidor, y las fuentes de canales que el
    bitstream no trae no se muestran;
  - **el evento**: el snapshot (sticky) y si cada canal está en continuo o bloqueado;
  - **el shield**: qué lo dispara y sobre qué actúa, en casillas con nombre en vez de
    hexadecimales, el holdoff, lo que hace dicho en palabras, y las configuraciones
    típicas del mapa de registros.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QAction, QCheckBox, QComboBox, QDoubleSpinBox,
                             QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
                             QScrollArea, QSizePolicy, QSpinBox, QToolButton,
                             QVBoxLayout, QWidget)

from API.multitrigger import pz_ganancia
from API.osciloscope import ADC_CNT_PER_V
from app.diagrama_mt import (CICLO_NS, COLOR, DiagramaMt, canal_txt,
                             describir_escudo, filas_mascara, mascaras_efectivas,
                             texto_disparo)
from app.panel_etapas import PanelPorEtapas
from app.widgets_config import CALIENTE, CORTA

# Los del disparo de nivel: registros del OSC (slot 1) que usa el multitrigger.
CAMPOS_OSC = ('thr_ch0', 'thr_ch1', 'hyst_ch0', 'hyst_ch1', 'deb_len')

# Las casillas del shield, por nombre del bit (los nombres los manda el servidor).
_ROTULO_ESCUDO = {'ext_p': 'DIO0 ↑', 'ext_n': 'DIO0 ↓', 'ext_lvl': 'DIO0 level',
                  'mca': 'veto the MCA'}
_AYUDA_FILA = {
    'sw': 'The software trigger (TRIG_SW): «Software trigger» in OSC settings.',
    'adc': 'The level Schmitt of the channel (Red Pitaya): threshold and hysteresis '
           'in Sources → Level.',
    'slope': 'The slope trigger (a fast trapezoid and a Schmitt): Sources → MCA '
             'trigger.',
    'pz': 'The pole-zero trigger (the trigger of the trapezoid bank): positive '
          'only. Sources → MCA trigger.',
    'ext': 'The external input DIO0_P, debounced.',
    'asg': 'The pulse generator (gen_pulsos takes the ASG place): one trigger per '
           'pulse.',
    'cadena': 'The chain from another scope.',
}


class PanelMultitrigger(PanelPorEtapas):
    """Fuentes, máscaras, evento y shield del bloque multitrigger."""

    BLOQUE = 'mtrg'
    COLOR = COLOR

    pedir_mascara = pyqtSignal(int, int)     # canal, máscara
    pedir_armar = pyqtSignal(dict)           # el de nivel: {'armar', 'thr', 'hyst'}
    pedir_disparo = pyqtSignal(dict)         # el del MCA: args de la op mca.disparo
    pedir_campo_osc = pyqtSignal(str, int)   # los de CAMPOS_OSC, a osc.set
    pedir_refresco = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bits = ()                      # [(nombre, valor, ayuda)]
        self._n_ch = 2
        self._casillas = {}                  # (canal, valor) -> QCheckBox
        self._mascaras = {0: 0, 1: 0}
        self._bits_escudo = {}               # 'shield_src' | 'shield_dst' -> bits
        self._casillas_escudo = {}           # campo -> [(valor, QCheckBox)]
        self._escudo = {'shield_src': 0, 'shield_dst': 0}
        self._info = {}
        self.cnt_por_v = ADC_CNT_PER_V
        self._canal_mca = 0                  # el disparo del MCA va en su canal
        self._mq_mca = None                  # el trap_mq del MCA, si tiene trapecio
        self._hay_pz = True
        self._conectado = False
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        self.diagrama = DiagramaMt()
        self.diagrama.etapa_elegida.connect(self._ir_a_etapa)

        interior = QWidget()
        cols = QHBoxLayout(interior)
        cols.setContentsMargins(0, 0, 0, 0)
        # Las fuentes en dos columnas (el nivel y el disparo del MCA); la máscara con
        # el evento debajo; el shield, el que más pide.
        for grupos, ancho in (((self._grupo_nivel(),), 3),
                              ((self._grupo_disparo_mca(),), 3),
                              ((self._grupo_mascara(), self._grupo_evento()), 3),
                              ((self._grupo_escudo(),), 4)):
            v = QVBoxLayout()
            for g in grupos:
                v.addWidget(g)
            v.addStretch(1)
            cols.addLayout(v, ancho)

        self.scroll = scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.addWidget(self.diagrama)
        caja.addWidget(scroll, 1)

    @staticmethod
    def _gris(texto=''):
        lbl = QLabel(texto)
        lbl.setStyleSheet('color: #666;')
        return lbl

    # ---------- las fuentes ----------

    def _grupo_nivel(self):
        """El Schmitt de nivel de cada canal y el debounce de DIO0. Son registros del
        OSC: van por `pedir_campo_osc` (ver `_emitir`)."""
        g = self._grupo('fuentes', 'Level')
        f = self._forma(g)
        # El umbral es de 14 bits CON SIGNO: un pulso negativo dispara con el
        # umbral negativo, y por eso el rango no arranca en cero.
        for ch in (0, 1):
            campo = f'thr_ch{ch}'
            w = self._spin(campo, -8192, 8191, CALIENTE,
                           f'Threshold of the level trigger of {canal_txt(ch)}, in ADC '
                           f'counts ({ADC_CNT_PER_V} counts = 1 V in LV). The register '
                           f'is in the scope (slot 1), where Red Pitaya has it; the '
                           f'comparator is in the multitrigger. With the ring, the one '
                           f'of IN1 also arms its ADC trigger.')
            f.addRow(self._texto_con_marca(campo, f'threshold {canal_txt(ch)}'), w)
        for ch in (0, 1):
            campo = f'hyst_ch{ch}'
            w = self._spin(campo, 0, 16383, CALIENTE,
                           'How far the signal has to come back before another '
                           'trigger is allowed. Too low, noise triggers too often.')
            f.addRow(self._texto_con_marca(campo, f'hysteresis {canal_txt(ch)}'), w)
        # En volts, en una fila propia: como campo de un QFormLayout no entra.
        self.lbl_thr_v = self._gris('—')
        f.addRow(self.lbl_thr_v)
        w = self._spin('deb_len', 0, 0xFFFFF, CORTA,
                       'ADC cycles the external trigger (DIO0) stays inhibited after '
                       'one. The RTL reset value is 62500 = 500 µs.')
        f.addRow(self._texto_con_marca('deb_len', 'debounce DIO0'), w)
        for campo in ('thr_ch0', 'thr_ch1', 'hyst_ch0', 'hyst_ch1'):
            self._controles[campo][0].valueChanged.connect(self._pintar_umbral)

        btn_armar = QPushButton('Arm level trigger')
        btn_armar.setToolTip(
            'The scope arming sequence with the threshold and hysteresis of IN1: the '
            'shield re-arming IN1 and IN2, arm with we_keep and THEN the masks '
            '(level ↑ on both). It crosses registers of the oscilloscope and of the '
            'multitrigger, and its order matters: that is why it is a server '
            'operation and not a loose write from here. It replaces the MCA '
            'trigger.')
        btn_armar.clicked.connect(lambda: self.pedir_armar.emit(dict(
            armar=True, thr=self._volts('thr_ch0'), hyst=self._volts('hyst_ch0'))))
        btn_desarmar = QPushButton('Disarm')
        btn_desarmar.setToolTip('Clears we_keep and the shield, re-arms the '
                                'channels and resets the capture state machine.')
        btn_desarmar.clicked.connect(lambda: self.pedir_armar.emit({'armar': False}))
        fila = QHBoxLayout()
        fila.addWidget(btn_armar)
        fila.addWidget(btn_desarmar)
        f.addRow(fila)
        self._botones = [btn_armar, btn_desarmar]
        return g

    def _volts(self, campo):
        return self._controles[campo][1]() / self.cnt_por_v

    def _pintar_umbral(self, *_):
        self.lbl_thr_v.setText(f"IN1 {self._volts('thr_ch0'):+.3f} V · "
                               f"IN2 {self._volts('thr_ch1'):+.3f} V")

    def _emitir(self, campo, valor):
        """Los del nivel van al OSC, donde están sus registros; los demás, al
        multitrigger."""
        if campo in CAMPOS_OSC:
            if not self._cargando:
                self.pedir_campo_osc.emit(campo, int(valor))
            return
        super()._emitir(campo, valor)

    def campos_por_bloque(self):
        todos = self.campos()
        return {'mtrg': [c for c in todos if c not in CAMPOS_OSC],
                'osc': [c for c in todos if c in CAMPOS_OSC]}

    def _grupo_disparo_mca(self):
        """El disparo del MCA (op `mca.disparo`, `multitrigger_armar_mca`): la fuente
        con sus parámetros, en el canal del MCA. Se escribe al armar: la secuencia
        apaga la fuente, la configura, pone el shield y `we_keep`, y recién después
        la máscara."""
        g = self._grupo('fuentes', 'MCA trigger')
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 4)
        self.lbl_canal_mca = self._gris('on IN1 (the MCA channel)')
        v.addWidget(self.lbl_canal_mca)
        fila = QHBoxLayout()
        fila.addWidget(QLabel('source'))
        self.cmb_fuente = QComboBox()
        self.cmb_fuente.addItem('slope', 'pendiente')
        self.cmb_fuente.addItem('pole-zero', 'pz')
        self.cmb_fuente.setToolTip(
            'Slope: a fast trapezoid on the samples and a Schmitt; it triggers on the '
            'tail of another pulse. Pole-zero: a short trapezoid with the pole-zero '
            'of the MCA (the trigger of the trapezoid bank); it separates pairs from '
            '7–8 samples.')
        self.cmb_fuente.currentIndexChanged.connect(self._cambio_fuente)
        fila.addWidget(self.cmb_fuente)
        fila.addStretch(1)
        v.addLayout(fila)

        def spin(minimo, maximo, valor, ayuda):
            s = QSpinBox(minimum=minimo, maximum=maximo, value=valor)
            s.setToolTip(ayuda)
            return s

        def par(a, b, ra, rb):
            h = QHBoxLayout()
            h.addWidget(self._gris(ra))
            h.addWidget(a)
            h.addWidget(self._gris(rb))
            h.addWidget(b)
            h.addStretch(1)
            return h

        # La pendiente: s = suma de L muestras menos la de L muestras G antes. Para
        # un escalón de alto A, s = L·A.
        self._w_pend = QWidget()
        fp = self._forma(self._w_pend)
        fp.setContentsMargins(0, 0, 0, 0)
        self.spn_l = spin(1, 16, 8, 'Samples in each sum of the slope.')
        self.spn_g = spin(0, 31, 4, 'Gap between the two sums.')
        fp.addRow('sums', par(self.spn_l, self.spn_g, 'L', 'G'))
        self.spn_thr = spin(0, (1 << 18) - 1, 600,
                            'Threshold on the slope s (a step of height A gives '
                            's = L·A). Measured on the board with the campaign '
                            'pulse: 600.')
        self.spn_hyst = spin(0, (1 << 18) - 1, 300,
                             'Re-arms when s drops below thr − hyst: it is what '
                             'allows triggering on the tail of another pulse.')
        fp.addRow('threshold (s)', self.spn_thr)
        fp.addRow('hysteresis (s)', self.spn_hyst)
        v.addWidget(self._w_pend)

        # El polo-cero: el umbral y el re-armado en cuentas de amplitud; el servidor
        # los pasa a unidades de la salida con `pz_ganancia`.
        self._w_pz = QWidget()
        fz = self._forma(self._w_pz)
        fz.setContentsMargins(0, 0, 0, 0)
        self.spn_k = spin(1, 31, 2, 'Rise of the short trapezoid (2 for the Rigol '
                                    'pulse).')
        self.spn_m = spin(0, 30, 1, 'Flat top (1 for the Rigol pulse); k + m ≤ 31.')
        fz.addRow('shape', par(self.spn_k, self.spn_m, 'k', 'm'))
        self.spn_sh = spin(0, 63, 10, 'Shift of the output (10).')
        fz.addRow('shift', self.spn_sh)
        self.spn_mq = spin(0, (1 << 20) - 1, 3992,
                           'The pole-zero constant M·16. It has to be THE SAME as the '
                           'MCA (trap_mq): the one fitted to the tail on the board.')
        self.lbl_mq_mca = self._gris('')
        fila = QHBoxLayout()
        fila.addWidget(self.spn_mq)
        fila.addWidget(self.lbl_mq_mca)
        fila.addStretch(1)
        fz.addRow('Mq', fila)
        self.spn_thr_pz = QDoubleSpinBox(decimals=1, minimum=0.0, maximum=8191.0,
                                         value=50.0)
        self.spn_thr_pz.setToolTip('Threshold in amplitude counts (50 for the Rigol '
                                   'pulse).')
        self.spn_hyst_pz = QDoubleSpinBox(decimals=1, minimum=0.0, maximum=8191.0,
                                          value=25.0)
        self.spn_hyst_pz.setToolTip('Re-arms below threshold − hysteresis, in '
                                    'amplitude counts (25).')
        fz.addRow('threshold', self.spn_thr_pz)
        fz.addRow('hysteresis', self.spn_hyst_pz)
        v.addWidget(self._w_pz)

        self.btn_armar_mca = QPushButton('Arm for the MCA')
        self.btn_armar_mca.setToolTip(
            'Arms this source on the channel of the MCA, in continuous mode: the '
            'source off, its parameters, the shield re-arming the channel, we_keep, '
            'and THEN its bit in the mask. Without it the MCA opens no windows.')
        self.btn_armar_mca.clicked.connect(lambda: self.armar_mca(True))
        self.btn_desarmar_mca = QPushButton('Disarm')
        self.btn_desarmar_mca.setToolTip('Mask, both sources, shield and we_keep off.')
        self.btn_desarmar_mca.clicked.connect(lambda: self.armar_mca(False))
        fila = QHBoxLayout()
        fila.addWidget(self.btn_armar_mca)
        fila.addWidget(self.btn_desarmar_mca)
        v.addLayout(fila)
        self.lbl_disparo = QLabel('—')
        self.lbl_disparo.setWordWrap(True)
        self.lbl_disparo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_disparo.setMinimumWidth(150)
        v.addWidget(self.lbl_disparo)
        self._cambio_fuente()
        return g

    def _cambio_fuente(self, *_):
        pz = self.cmb_fuente.currentData() == 'pz'
        self._w_pend.setVisible(not pz)
        self._w_pz.setVisible(pz)

    def args_disparo(self):
        """Los argumentos de la op `mca.disparo` para armar lo que dice el grupo."""
        a = {'ch': self._canal_mca, 'fuente': self.cmb_fuente.currentData()}
        if a['fuente'] == 'pz':
            a.update(k=self.spn_k.value(), m=self.spn_m.value(),
                     sh=self.spn_sh.value(), mq=self.spn_mq.value(),
                     thr_cuentas=self.spn_thr_pz.value(),
                     hyst_cuentas=self.spn_hyst_pz.value())
        else:
            a.update(L=self.spn_l.value(), G=self.spn_g.value(),
                     thr=self.spn_thr.value(), hyst=self.spn_hyst.value())
        return a

    def armar_mca(self, armar):
        a = self.args_disparo() if armar else {'ch': self._canal_mca}
        a['armar'] = bool(armar)
        self.pedir_disparo.emit(a)

    # ---------- la máscara ----------

    def _grupo_mascara(self):
        g = self._grupo('mascara', 'OR mask')
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 4)
        self._rejilla = QGridLayout()
        self._rejilla.setVerticalSpacing(1)
        self._rejilla.setColumnStretch(5, 1)
        v.addLayout(self._rejilla)
        self.lbl_nota_mascara = QLabel('')
        self.lbl_nota_mascara.setWordWrap(True)
        self.lbl_nota_mascara.setStyleSheet('color: #666;')
        v.addWidget(self.lbl_nota_mascara)
        g.setToolTip('One OR mask per channel: the sources that trigger it. The event '
                     'is the OR of the channels.')
        return g

    def construir_bits(self, bits, n_ch=None):
        """Arma la grilla con los nombres que mandó el servidor.

        Los nombres viajan con el dato en vez de estar duplicados acá: una
        segunda copia de la lista de bits es exactamente cómo se desincroniza
        una interfaz de un RTL que cambió. Filas por fuente, columnas por canal y
        polaridad; las fuentes de canales que el bitstream no trae no se muestran.
        """
        n_ch = self._n_ch if n_ch is None else int(n_ch)
        bits = tuple(tuple(b) for b in bits)
        if bits == self._bits and n_ch == self._n_ch and self._casillas:
            return
        self._bits, self._n_ch = bits, n_ch

        while self._rejilla.count():
            it = self._rejilla.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self._casillas = {}

        canales = range(min(n_ch, 2))
        for ch in canales:
            t = QLabel(f'<b>{canal_txt(ch)}</b>')
            t.setAlignment(Qt.AlignCenter)
            self._rejilla.addWidget(t, 0, 1 + 2 * ch, 1, 2)
            for k, flecha in enumerate(('↑', '↓')):
                f = self._gris(flecha)
                f.setAlignment(Qt.AlignCenter)
                self._rejilla.addWidget(f, 1, 1 + 2 * ch + k)
        filas, _ocultos = filas_mascara(bits, n_ch)
        for i, (fila, rotulo, pols) in enumerate(filas):
            lbl = QLabel(rotulo)
            tipo = fila.rstrip('0123456789')
            lbl.setToolTip(_AYUDA_FILA.get(tipo, ''))
            self._rejilla.addWidget(lbl, 2 + i, 0)
            for k, pol in enumerate(('p', 'n')):
                if pol not in pols:
                    continue
                nombre, valor, ayuda = pols[pol]
                for ch in canales:
                    c = QCheckBox()
                    c.setToolTip(f'{nombre}: {ayuda}\nIn the mask of {canal_txt(ch)}.')
                    c.setEnabled(self._conectado)
                    c.toggled.connect(
                        lambda marcado, ch=ch, v=valor: self._cambio(ch, v, marcado))
                    self._casillas[(ch, valor)] = c
                    self._rejilla.addWidget(c, 2 + i, 1 + 2 * ch + k, Qt.AlignCenter)

    def _cambio(self, canal, valor, marcado):
        if self._cargando:
            return
        nueva = (self._mascaras[canal] | valor) if marcado else \
                (self._mascaras[canal] & ~valor)
        self._mascaras[canal] = nueva & 0xFFFFFFFF
        self.pedir_mascara.emit(canal, self._mascaras[canal])

    # ---------- el evento ----------

    def _grupo_evento(self):
        g = self._grupo('evento', 'Event')
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 4)
        self.lbl_snap = QLabel('—')
        self.lbl_snap.setWordWrap(True)
        self.lbl_snap.setToolTip(
            'What triggered (snapshot). The register is STICKY: it accumulates every '
            'source that triggered since the last clear, not the last one. Seeing '
            'two sources here does not mean they triggered together.')
        v.addWidget(self.lbl_snap)
        self.lbl_canales = QLabel('—')
        self.lbl_canales.setWordWrap(True)
        self.lbl_canales.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_canales.setMinimumWidth(110)
        self.lbl_canales.setToolTip(
            'continuous (we_keep): the mask survives the trigger. single: it turns '
            'off after one. blocked (dis_act): the channel triggered and waits for '
            'a re-arm.')
        self.btn_releer = QPushButton('Reread')
        self.btn_releer.clicked.connect(self.pedir_refresco)
        fila = QHBoxLayout()
        fila.addWidget(self.lbl_canales, 1)
        fila.addWidget(self.btn_releer)
        v.addLayout(fila)
        return g

    # ---------- el shield ----------

    def _grupo_escudo(self):
        g = self._grupo('escudo', 'Shield')
        f = self._forma(g)
        self._contenedores = {}
        for campo, rotulo, ayuda in (
                ('shield_src', 'starts on',
                 'What starts (and reloads) the holdoff: the trigger of a channel, or '
                 'the external input DIO0 (an edge, or its level: then it runs while '
                 'DIO0 is high).'),
                ('shield_dst', 'acts on',
                 'What it does: re-arm a channel (clears its adc_trg_dis when the '
                 'holdoff expires), and/or veto the MCA while it runs (no new '
                 'windows, the live-time clock stops).')):
            w = QWidget()
            rej = QGridLayout(w)
            rej.setContentsMargins(0, 0, 0, 0)
            rej.setVerticalSpacing(0)
            self._contenedores[campo] = rej
            self._casillas_escudo[campo] = []
            self._registrar(campo, w,
                            lambda campo=campo: self._leer_escudo(campo),
                            lambda v, campo=campo: self._escribir_escudo(campo, v),
                            CORTA, ayuda)
            f.addRow(self._texto_con_marca(campo, rotulo), w)

        fila = QHBoxLayout()
        fila.addWidget(self._spin('shield_dur', 0, 0xFFFF, CORTA,
                                  'Cycles of adc_clk (8 ns) before acting. With 0 the '
                                  're-arm happens in the SAME cycle as the trigger, '
                                  'which is what allows re-triggering at HW speed.'))
        self.lbl_holdoff = self._gris('')
        fila.addWidget(self.lbl_holdoff)
        fila.addStretch(1)
        f.addRow(self._texto_con_marca('shield_dur', 'holdoff'), fila)
        self._controles['shield_dur'][0].valueChanged.connect(self._pintar_holdoff)

        self.lbl_escudo = QLabel('—')
        self.lbl_escudo.setWordWrap(True)
        self.lbl_escudo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_escudo.setMinimumWidth(160)
        f.addRow(self.lbl_escudo)

        self.btn_tipicas = QToolButton()
        self.btn_tipicas.setText('Typical setups')
        self.btn_tipicas.setPopupMode(QToolButton.InstantPopup)
        self.btn_tipicas.setMenu(QMenu(self.btn_tipicas))
        f.addRow(self.btn_tipicas)

        self.lbl_runtime = QLabel('—')
        f.addRow('now', self.lbl_runtime)
        self.lbl_flags = QLabel('—')
        self.lbl_flags.setToolTip('dis_act / we_keep, as published by DIS_FLAGS.')
        f.addRow('flags', self.lbl_flags)
        self._pintar_holdoff()
        return g

    def _construir_escudo(self, bits_src, bits_dst):
        """Las casillas del shield, con los nombres del servidor: las de canales que
        el bitstream no trae no se muestran (y sus bits se conservan al escribir)."""
        nuevos = {'shield_src': tuple(tuple(b) for b in (bits_src or ())),
                  'shield_dst': tuple(tuple(b) for b in (bits_dst or ()))}
        if nuevos == self._bits_escudo and all(self._casillas_escudo.values()):
            return
        self._bits_escudo = nuevos
        for campo, bits in nuevos.items():
            rej = self._contenedores[campo]
            while rej.count():
                it = rej.takeAt(0)
                if it.widget() is not None:
                    it.widget().deleteLater()
            casillas = []
            # Los canales en la primera fila; lo demás (DIO0, el MCA) de a dos debajo.
            n_canal = n_otro = 0
            for nombre, valor, ayuda in bits:
                es_canal = nombre.startswith('ch') and nombre[2:].isdigit()
                if es_canal and int(nombre[2:]) >= self._n_ch:
                    continue
                if es_canal:
                    rot = (canal_txt(nombre[2:]) if campo == 'shield_src'
                           else f're-arm {canal_txt(nombre[2:])}')
                    pos = (0, n_canal)
                    n_canal += 1
                else:
                    rot = _ROTULO_ESCUDO.get(nombre, nombre)
                    pos = (1 + n_otro // 2, n_otro % 2)
                    n_otro += 1
                c = QCheckBox(rot)
                c.setToolTip(f'{nombre}: {ayuda}')
                c.setEnabled(self._conectado)
                c.setChecked(bool(self._escudo[campo] & int(valor)))
                c.toggled.connect(lambda _m, campo=campo: self._cambio_escudo(campo))
                casillas.append((int(valor), c))
                rej.addWidget(c, *pos)
            self._casillas_escudo[campo] = casillas
        self._armar_tipicas()

    def _leer_escudo(self, campo):
        v = self._escudo[campo]
        for valor, c in self._casillas_escudo[campo]:
            v = (v | valor) if c.isChecked() else (v & ~valor)
        return v

    def _escribir_escudo(self, campo, v):
        self._escudo[campo] = int(v)
        for valor, c in self._casillas_escudo[campo]:
            c.setChecked(bool(int(v) & valor))

    def _cambio_escudo(self, campo):
        if self._cargando:
            return
        self._escudo[campo] = self._leer_escudo(campo)
        self._emitir(campo, self._escudo[campo])
        self._pintar_escudo()

    def _pintar_holdoff(self, *_):
        dur = self._controles['shield_dur'][1]()
        self.lbl_holdoff.setText(f'cyc = {dur * CICLO_NS / 1000.0:.3g} µs')
        self._pintar_escudo()

    def _pintar_escudo(self):
        if not self._bits_escudo:
            return
        self.lbl_escudo.setText(describir_escudo(
            self._leer_escudo('shield_src'), self._leer_escudo('shield_dst'),
            self._controles['shield_dur'][1](),
            self._bits_escudo['shield_src'], self._bits_escudo['shield_dst']))

    def _armar_tipicas(self):
        """Las configuraciones del mapa de registros (docs/mt/register_map_mt.md,
        «El veto al MCA»), con los valores de los bits que mandó el servidor."""
        src = {n: int(v) for n, v, _a in self._bits_escudo.get('shield_src', ())}
        dst = {n: int(v) for n, v, _a in self._bits_escudo.get('shield_dst', ())}
        menu = self.btn_tipicas.menu()
        menu.clear()
        if not src or not dst:
            return
        dur = self._controles['shield_dur'][1]() or 125
        tipicas = (
            ('Hardware re-arm of IN1 (the MCA trigger)',
             src.get('ch0', 0), dst.get('ch0', 0), 0,
             'Each trigger of IN1 re-arms it in the same cycle. It is what arming '
             'the MCA trigger sets.'),
            ('Veto the MCA while DIO0 is high',
             src.get('ext_lvl', 0), dst.get('mca', 0), 0,
             'The veto is the DIO0 line (about 3 cycles late). There is one shield: '
             'it no longer re-arms IN1, so a continuous trigger stops after its '
             'first pulse.'),
            (f'Veto window of {dur} cycles after DIO0 ↑',
             src.get('ext_p', 0), dst.get('mca', 0), dur,
             'The MCA is vetoed for the holdoff after each rising edge of DIO0. '
             'Same caveat: it no longer re-arms IN1.'),
            ('Off (software re-arm)', 0, 0, 0,
             'A channel that triggered stays blocked until software re-arms it.'),
        )
        for texto, s, d, t, ayuda in tipicas:
            a = QAction(texto, menu)
            a.setToolTip(ayuda)
            a.setStatusTip(ayuda)
            a.triggered.connect(lambda _c=False, s=s, d=d, t=t: self.aplicar_escudo(s, d, t))
            menu.addAction(a)
        menu.setToolTipsVisible(True)

    def aplicar_escudo(self, src, dst, dur):
        """Escribe el shield entero (una configuración típica)."""
        for campo, v in (('shield_src', src), ('shield_dst', dst), ('shield_dur', dur)):
            self.pedir_campo.emit(campo, int(v))
        self.log.emit(f'shield: src={src:#x} dst={dst:#x} dur={dur}')

    # =========================================================================
    # Entradas
    # =========================================================================

    def actualizar_mtrg(self, info):
        """El `mtrg.get` del servidor."""
        self._info = dict(info or {})
        self._n_ch = int(info.get('n_ch') or 2)
        self.construir_bits(info.get('bits', ()), self._n_ch)
        self._construir_escudo(info.get('bits_shield_src'), info.get('bits_shield_dst'))
        cfg = info.get('config', {})
        self.actualizar_config(cfg)

        self._cargando = True
        try:
            for canal, clave in ((0, 'or_mask_ch0'), (1, 'or_mask_ch1')):
                m = int(cfg.get(clave, 0))
                self._mascaras[canal] = m
                for (ch, valor), casilla in self._casillas.items():
                    if ch == canal:
                        casilla.setChecked(bool(m & valor))
        finally:
            self._cargando = False
        self._pintar_nota_mascara()
        canales = info.get('canales') or []
        self._hay_pz = not canales or canales[0].get('polo_cero') is not None
        item = self.cmb_fuente.model().item(self.cmb_fuente.findData('pz'))
        item.setEnabled(self._hay_pz)

        est = info.get('status', {})
        fuentes = est.get('fuentes') or []
        crudo = est.get('snapshot', 0)
        self.lbl_snap.setText('seen: ' + (', '.join(fuentes) if fuentes
                                          else 'no source recorded'))
        self.lbl_snap.setToolTip(f'SNAPSHOT = {crudo:#010x}\n'
                                 + self.lbl_snap.toolTip().split('\n', 1)[-1])
        flags = int(est.get('flags', 0) or 0)
        partes = []
        for ch in range(min(self._n_ch, 2)):
            cont = 'continuous' if (flags >> (4 + ch)) & 1 else 'single shot'
            bloq = ', blocked' if (flags >> ch) & 1 else ''
            partes.append(f'{canal_txt(ch)} {cont}{bloq}')
        self.lbl_canales.setText('\n'.join(partes))
        rt = est.get('shield_runtime')
        if rt is None:
            self.lbl_runtime.setText('—')
        else:
            self.lbl_runtime.setText(
                f'{rt & 0xFFFF} cycles left'
                + (' · active' if est.get('shield_active') else '')
                + (' · VETO to the MCA' if est.get('mca_veto') else ''))
        self.lbl_flags.setText(f'{flags:#06x}')
        self._pintar_escudo()
        self.diagrama.actualizar_mtrg(self._info)

    def actualizar_osc(self, info):
        """El `osc.get`: el umbral, la histéresis y el debounce del disparo de nivel,
        que son registros del OSC."""
        self.cnt_por_v = float(info.get('adc_cnt_per_v', self.cnt_por_v))
        self.actualizar_config(info.get('config') or {})
        self._pintar_umbral()

    def actualizar_disparo(self, est):
        """El estado que devuelve la op `mca.disparo`: la etiqueta, y lo armado vuelve
        a los controles."""
        self.lbl_disparo.setText(texto_disparo(est))
        if not est.get('armado'):
            return
        z = est.get('polo_cero') or {}
        if est.get('fuente') == 'pz' and z:
            self.cmb_fuente.setCurrentIndex(self.cmb_fuente.findData('pz'))
            for s, clave in ((self.spn_k, 'k'), (self.spn_m, 'm'), (self.spn_sh, 'sh'),
                             (self.spn_mq, 'mq')):
                s.setValue(int(z.get(clave, s.value())))
            try:
                gan = pz_ganancia(int(z['k']), int(z['m']), int(z['mq']), int(z['sh']))
            except Exception:                                   # noqa: BLE001
                gan = 0
            if gan > 0:
                self.spn_thr_pz.setValue(float(z.get('thr', 0)) / gan)
                self.spn_hyst_pz.setValue(float(z.get('hyst', 0)) / gan)
        else:
            s = est.get('pendiente') or {}
            self.cmb_fuente.setCurrentIndex(self.cmb_fuente.findData('pendiente'))
            self.spn_l.setValue(int(s.get('L', 8)))
            self.spn_g.setValue(int(s.get('G', 4)))
            self.spn_thr.setValue(int(s.get('thr', 600)))
            self.spn_hyst.setValue(int(s.get('hyst', 300)))

    def actualizar_mca_config(self, cfg):
        """La configuración del MCA: su canal (el disparo va ahí) y su Mq, que el
        polo-cero tiene que repetir."""
        if cfg.get('channel') is not None:
            self._canal_mca = int(cfg['channel'])
            self.lbl_canal_mca.setText(f'on {canal_txt(self._canal_mca)} (the MCA '
                                       f'channel)')
        mq = int(cfg.get('trap_mq') or 0)
        if mq and mq != self._mq_mca:
            if self._mq_mca is None:
                self.spn_mq.setValue(mq)        # la primera vez, la del MCA
            self._mq_mca = mq
        self.lbl_mq_mca.setText(f'MCA: {self._mq_mca}' if self._mq_mca else '')

    def actualizar_estado(self, est):
        """El `status` del MCA: lo que ve del disparo (tasa, veto, re-armado)."""
        self.diagrama.actualizar_mca(est.get('counters') or {})

    def configurar(self, hay_ring=False):
        self.diagrama.configurar(hay_ring)

    def _pintar_nota_mascara(self):
        cfg = self._info.get('config') or {}
        indep = self._info.get('indep')
        efect = mascaras_efectivas(cfg, self._n_ch, indep)
        notas = []
        for ch in range(1, len(efect)):
            if indep is not None and not (indep >> ch) & 1:
                notas.append(f'{canal_txt(ch)} follows IN1 (indep_mode off).')
        _filas, ocultos = filas_mascara(self._bits, self._n_ch)
        for ch in range(len(efect)):
            extra = int(cfg.get(f'or_mask_ch{ch}', 0) or 0) & ocultos
            if extra:
                nombres = [n for n, v, _a in self._bits if extra & int(v)]
                notas.append(f'{canal_txt(ch)} also has {", ".join(nombres)}, which '
                             f'this bitstream does not have.')
        self.lbl_nota_mascara.setText('\n'.join(notas))
        self.lbl_nota_mascara.setVisible(bool(notas))
        self.lbl_nota_mascara.setToolTip(
            'Without indep_mode (the usual: the arming writes 0x0909), mt_cfg gives '
            'every channel the mask of IN1: the column of IN2 has no effect.'
            if notas else '')

    def set_conectado(self, conectado, running=False):
        super().set_conectado(conectado, running)
        self._conectado = conectado
        for c in self._casillas.values():
            c.setEnabled(conectado)
        for casillas in self._casillas_escudo.values():
            for _v, c in casillas:
                c.setEnabled(conectado)
        for w in (*self._botones, self.btn_releer, self.btn_tipicas, self.cmb_fuente,
                  self.btn_armar_mca, self.btn_desarmar_mca, self.spn_l, self.spn_g,
                  self.spn_thr, self.spn_hyst, self.spn_k, self.spn_m, self.spn_sh,
                  self.spn_mq, self.spn_thr_pz, self.spn_hyst_pz):
            w.setEnabled(conectado)
        if not conectado:
            self.diagrama.limpiar()
