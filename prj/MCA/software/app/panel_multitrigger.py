#!/usr/bin/env python3
"""Pestaña del multitrigger: qué puede disparar, qué disparó, y el shield, por etapa.

Es el bloque que este proyecto **añadió** al scope original de RedPitaya, en su
región propia (slot 3). El osciloscopio clásico —umbral, decimación, delay,
calibración, BRAM— está en «OSC settings».

Arriba, la franja (`diagrama_mt.py`): las fuentes, la máscara OR, el evento y el
shield, con lo que está mal puesto en rojo y lo que el MCA ve del disparo (la tasa,
el veto, el tiempo sin re-armar). Abajo, los controles por etapa, con el color de su
bloque; el grupo con el foco o el ratón se resalta en la franja y un clic en un
bloque lleva a sus controles (`panel_etapas.py`):

  - **las fuentes**: el estado de la pendiente y del polo-cero de cada canal, y el
    umbral de nivel, que es del OSC. Se arman en otras pestañas (el umbral en «OSC
    settings», el disparo del MCA en «Spectrum») y los botones llevan ahí;
  - **las máscaras OR**: una grilla de fuentes × canal, con las dos polaridades. Los
    nombres de los bits vienen del servidor, y las fuentes de canales que el
    bitstream no trae no se muestran;
  - **el evento**: el snapshot (sticky) y el armado del disparo de nivel del scope;
  - **el shield**: qué lo dispara y sobre qué actúa, en casillas con nombre en vez de
    hexadecimales, el holdoff, lo que hace dicho en palabras, y las configuraciones
    típicas del mapa de registros.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QAction, QCheckBox, QGridLayout, QHBoxLayout, QLabel,
                             QMenu, QPushButton, QScrollArea, QSizePolicy,
                             QToolButton, QVBoxLayout, QWidget)

from API.osciloscope import ADC_CNT_PER_V
from app.diagrama_mt import (CICLO_NS, COLOR, DiagramaMt, canal_txt,
                             describir_escudo, filas_mascara, mascaras_efectivas)
from app.panel_etapas import PanelPorEtapas
from app.widgets_config import CORTA

# Las casillas del shield, por nombre del bit (los nombres los manda el servidor).
_ROTULO_ESCUDO = {'ext_p': 'DIO0 ↑', 'ext_n': 'DIO0 ↓', 'ext_lvl': 'DIO0 level',
                  'mca': 'veto the MCA'}
_AYUDA_FILA = {
    'sw': 'The software trigger (TRIG_SW): «Software trigger» in OSC settings.',
    'adc': 'The level Schmitt of the channel (Red Pitaya): threshold and hysteresis '
           'in OSC settings → Trigger.',
    'slope': 'The slope trigger (a fast trapezoid and a Schmitt): armed for the MCA '
             'from Spectrum.',
    'pz': 'The pole-zero trigger (the trigger of the trapezoid bank): positive '
          'only. Armed by scripts.',
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
    pedir_armar = pyqtSignal(bool)           # True = armar, False = desarmar
    pedir_refresco = pyqtSignal()
    ir_a = pyqtSignal(str)                   # 'osc' (el umbral) | 'espectro' (el MCA)

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
        self._osc_cfg = {}
        self.cnt_por_v = ADC_CNT_PER_V
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
        # La máscara es una grilla angosta; el shield, el que más pide.
        for g, ancho in ((self._grupo_fuentes(), 3), (self._grupo_mascara(), 2),
                         (self._grupo_evento(), 3), (self._grupo_escudo(), 4)):
            v = QVBoxLayout()
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

    def _grupo_fuentes(self):
        g = self._grupo('fuentes', 'Sources')
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 4)
        rej = QGridLayout()
        rej.setVerticalSpacing(2)
        self._lbl_fuente = {}
        fila = 0
        for ch in (0, 1):
            rej.addWidget(QLabel(f'<b>{canal_txt(ch)}</b>'), fila, 0, 1, 2)
            fila += 1
            for clave, rotulo in (('nivel', 'level'), ('pendiente', 'slope'),
                                  ('polo_cero', 'pole-zero')):
                rej.addWidget(self._gris(rotulo), fila, 0, Qt.AlignRight)
                lbl = QLabel('—')
                lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                lbl.setMinimumWidth(100)
                rej.addWidget(lbl, fila, 1)
                self._lbl_fuente[(ch, clave)] = lbl
                fila += 1
        rej.setColumnStretch(1, 1)
        v.addLayout(rej)

        v.addWidget(self._gris('Set in other tabs:'))
        self.btn_ir_osc = QPushButton('Level: OSC settings…')
        self.btn_ir_osc.setToolTip('The level threshold and hysteresis: OSC settings '
                                   '→ Trigger.')
        self.btn_ir_osc.clicked.connect(lambda: self.ir_a.emit('osc'))
        self.btn_ir_espectro = QPushButton('Slope: Spectrum…')
        self.btn_ir_espectro.setToolTip('The slope trigger of the MCA (L, G, threshold, '
                                        'hysteresis): Spectrum → Trigger. The '
                                        'pole-zero trigger is armed by scripts.')
        self.btn_ir_espectro.clicked.connect(lambda: self.ir_a.emit('espectro'))
        for b in (self.btn_ir_osc, self.btn_ir_espectro):
            fila_b = QHBoxLayout()
            fila_b.addWidget(b)
            fila_b.addStretch(1)
            v.addLayout(fila_b)
        return g

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
        v.addWidget(self._gris('What triggered (sticky):'))
        self.lbl_snap = QLabel('—')
        self.lbl_snap.setWordWrap(True)
        self.lbl_snap.setToolTip(
            'The register is STICKY: it accumulates every source that triggered '
            'since the last clear, not the last one. Seeing two sources here does '
            'not mean they triggered together.')
        v.addWidget(self.lbl_snap)
        self.lbl_canales = QLabel('—')
        self.lbl_canales.setWordWrap(True)
        self.lbl_canales.setToolTip(
            'we_keep: continuous, the mask survives the trigger. blocked (dis_act): '
            'the channel triggered and waits for a re-arm.')
        v.addWidget(self.lbl_canales)
        btn = QPushButton('Reread')
        btn.clicked.connect(self.pedir_refresco)
        v.addWidget(btn)

        btn_armar = QPushButton('Arm level trigger')
        btn_armar.setToolTip(
            'The scope arming sequence: the level threshold at 0 V, the shield '
            're-arming IN1 and IN2, arm with we_keep and THEN the masks (adc ↑ on '
            'both). It crosses registers of the oscilloscope and of the '
            'multitrigger, and its order matters: that is why it is a server '
            'operation and not a loose write from here. It replaces the MCA '
            'trigger.')
        btn_armar.clicked.connect(lambda: self.pedir_armar.emit(True))
        btn_desarmar = QPushButton('Disarm')
        btn_desarmar.setToolTip('Clears we_keep and the shield, re-arms the '
                                'channels and resets the capture state machine.')
        btn_desarmar.clicked.connect(lambda: self.pedir_armar.emit(False))
        fila = QHBoxLayout()
        fila.addWidget(btn_armar)
        fila.addWidget(btn_desarmar)
        v.addLayout(fila)
        self._botones = [btn, btn_armar, btn_desarmar]
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
        self._pintar_fuentes()

        est = info.get('status', {})
        fuentes = est.get('fuentes') or []
        crudo = est.get('snapshot', 0)
        self.lbl_snap.setText(
            f'{crudo:#010x} — ' + (', '.join(fuentes) if fuentes
                                  else 'no source recorded'))
        flags = int(est.get('flags', 0) or 0)
        partes = []
        for ch in range(min(self._n_ch, 2)):
            cont = 'continuous' if (flags >> (4 + ch)) & 1 else 'single shot'
            bloq = ' · blocked' if (flags >> ch) & 1 else ''
            partes.append(f'{canal_txt(ch)}: {cont}{bloq}')
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
        """El `osc.get`: el umbral y la histéresis del disparo de nivel."""
        self.cnt_por_v = float(info.get('adc_cnt_per_v', self.cnt_por_v))
        self._osc_cfg = dict(info.get('config') or {})
        self._pintar_fuentes()

    def actualizar_estado(self, est):
        """El `status` del MCA: lo que ve del disparo (tasa, veto, re-armado)."""
        self.diagrama.actualizar_mca(est.get('counters') or {})

    def configurar(self, hay_ring=False):
        self.diagrama.configurar(hay_ring)

    def _pintar_fuentes(self):
        canales = self._info.get('canales') or []
        for ch in (0, 1):
            thr = self._osc_cfg.get(f'thr_ch{ch}')
            hyst = self._osc_cfg.get(f'hyst_ch{ch}')
            self._lbl_fuente[(ch, 'nivel')].setText(
                '—' if thr is None else
                f'thr {int(thr) / self.cnt_por_v:.3f} V\n'
                f'hyst {int(hyst or 0) / self.cnt_por_v:.3f} V')
            c = canales[ch] if ch < len(canales) else {}
            s = c.get('pendiente')
            self._lbl_fuente[(ch, 'pendiente')].setText(
                '—' if s is None and not canales else
                'not in this bitstream' if s is None else
                f"L {s['L']} · G {s['G']}\nthr {s['thr']} · hyst {s['hyst']}"
                if s.get('en') else 'off')
            z = c.get('polo_cero')
            self._lbl_fuente[(ch, 'polo_cero')].setText(
                '—' if z is None and not canales else
                'not in this bitstream' if z is None else
                f"k {z['k']} · m {z['m']} · sh {z['sh']}\nthr {z['thr']} · "
                f"hyst {z['hyst']}" if z.get('en') else 'off')
            for clave in ('nivel', 'pendiente', 'polo_cero'):
                lbl = self._lbl_fuente[(ch, clave)]
                lbl.setToolTip(lbl.text())

    def _pintar_nota_mascara(self):
        cfg = self._info.get('config') or {}
        indep = self._info.get('indep')
        efect = mascaras_efectivas(cfg, self._n_ch, indep)
        notas = []
        for ch in range(1, len(efect)):
            if indep is not None and not (indep >> ch) & 1:
                notas.append(f'{canal_txt(ch)} uses the mask of IN1: indep_mode is '
                             f'off, so its own column has no effect.')
        _filas, ocultos = filas_mascara(self._bits, self._n_ch)
        for ch in range(len(efect)):
            extra = int(cfg.get(f'or_mask_ch{ch}', 0) or 0) & ocultos
            if extra:
                nombres = [n for n, v, _a in self._bits if extra & int(v)]
                notas.append(f'{canal_txt(ch)} also has {", ".join(nombres)}, which '
                             f'this bitstream does not have.')
        self.lbl_nota_mascara.setText('\n'.join(notas))
        self.lbl_nota_mascara.setVisible(bool(notas))

    def set_conectado(self, conectado, running=False):
        super().set_conectado(conectado, running)
        self._conectado = conectado
        for c in self._casillas.values():
            c.setEnabled(conectado)
        for casillas in self._casillas_escudo.values():
            for _v, c in casillas:
                c.setEnabled(conectado)
        for w in getattr(self, '_botones', ()):
            w.setEnabled(conectado)
        self.btn_tipicas.setEnabled(conectado)
        if not conectado:
            self.diagrama.limpiar()
