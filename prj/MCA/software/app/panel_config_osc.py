#!/usr/bin/env python3
"""Pestaña «OSC settings»: los registros del osciloscopio y, con su bitstream, el
ring, por etapa del dato.

Arriba, la franja (`diagrama_osc.py`): el osciloscopio en una fila (entrada,
diezmado, disparo, captura en BRAM) y el ring en otra (el estímulo, la ventana, el
ring en la DDR, el lector y los archivos), con los disparos y las pérdidas del ring.
Abajo, los controles por etapa, con el color de su bloque; el grupo con el foco o el
ratón se resalta en la franja y un clic en un bloque lleva a sus controles
(`panel_etapas.py`). La vista de las capturas está en la pestaña «Pulses».

Los campos del OSC son de `API/osciloscope.py` (`BLOQUE = 'osc'`): la ventana los
rutea a `osc.set`. Se escriben en caliente; los marcados con · reinician la captura
en curso y los ⚠ (la calibración), mal puestos, dejan sin disparos.

El ring es el `PanelRing` de siempre, embebido (`self.ring`): sus grupos van en las
dos columnas de la derecha, y su disparo del ADC usa el umbral y la histéresis de la
etapa Disparo (IN1), que son los registros que escribe al armarse. Su configuración
se toma al iniciar una corrida. Las cuentas de la corrida (disparos, pérdidas,
leídos, escritos) van en la franja y no se repiten en su estado.
"""

import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from API.osciloscope import ADC_CNT_PER_V, DEC_LEGAL, N_BUF
from app.diagrama_osc import COLOR, DiagramaOsc
from app.panel_etapas import PanelPorEtapas
from app.panel_ring import PanelRing
from app.widgets_config import CALIENTE, CORTA, RIESGO


class PanelConfigOsc(PanelPorEtapas):
    """Configuración del slot del osciloscopio y, si está, del ring."""

    BLOQUE = 'osc'
    COLOR = COLOR

    pedir_ctrl = pyqtSignal(str)             # 'reset' | 'sw_trig'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cnt_por_v = ADC_CNT_PER_V
        self.ring = None                     # PanelRing embebido, con el ring
        self.tasa_disparos = None            # Δwe_cnt/Δt del IN1
        self._we_prev = None
        self._hay_osc = True
        self._conectado = False
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        self.diagrama = DiagramaOsc()
        self.diagrama.etapa_elegida.connect(self._ir_a_etapa)

        interior = QWidget()
        cols = QHBoxLayout(interior)
        cols.setContentsMargins(0, 0, 0, 0)
        self._columnas = []
        # Las dos del osciloscopio, en el orden del dato; las dos del ring se llenan
        # al conectarse, si el bitstream lo trae.
        for grupos in ((self._grupo_entrada(), self._grupo_diezmado()),
                       (self._grupo_disparo(), self._grupo_bram()), (), ()):
            v = QVBoxLayout()
            for g in grupos:
                v.addWidget(g)
            v.addStretch(1)
            cols.addLayout(v, 1)
            self._columnas.append(v)

        self.scroll = scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.addWidget(self.diagrama)
        caja.addWidget(scroll, 1)

    def _fila(self, f, campo, texto, w):
        f.addRow(self._texto_con_marca(campo, texto), w)

    # ---------- el osciloscopio ----------

    def _grupo_entrada(self):
        g = self._grupo('entrada', 'Input')
        f = self._forma(g)
        for ch in (0, 1):
            self._fila(f, f'calib_off_ch{ch}', f'offset IN{ch + 1}',
                       self._spin(f'calib_off_ch{ch}', -8192, 8191, RIESGO,
                                  'Calibration offset, in counts. Set wrong, it '
                                  'shifts the baseline and with it the whole '
                                  'spectrum.'))
            self._fila(f, f'calib_gain_ch{ch}', f'gain IN{ch + 1}',
                       self._spin(f'calib_gain_ch{ch}', 0, 0xFFFF, RIESGO,
                                  'Calibration gain. 0x8000 is unity: with 0 no '
                                  'signal gets in.'))
        self._fila(f, 'filt_bypass', 'skip filter',
                   self._spin('filt_bypass', 0, 0xF, CORTA,
                              'One bit per channel: bypasses the input filter. '
                              'Bit 0 = IN1, bit 1 = IN2.'))
        return g

    def _grupo_diezmado(self):
        g = self._grupo('diezmado', 'Decimation')
        f = self._forma(g)
        for ch in (0, 1):
            self._fila(f, f'dec_ch{ch}', f'factor IN{ch + 1}',
                       self._combo(f'dec_ch{ch}', [(str(d), d) for d in DEC_LEGAL],
                                   CORTA,
                                   'Only these six values are legal. Changing it '
                                   'stretches the window in real time and restarts '
                                   'the capture in progress.'))
        for ch in (0, 1):
            f.addRow(self._check(f'avg_en_ch{ch}', f'average IN{ch + 1}', CORTA,
                                 'Averages the samples dropped by the decimation '
                                 'instead of discarding them.'))
        return g

    def _grupo_disparo(self):
        g = self._grupo('disparo', 'Trigger')
        f = self._forma(g)
        # El umbral es de 14 bits CON SIGNO: un pulso negativo dispara con el
        # umbral negativo, y por eso el rango no arranca en cero.
        for ch in (0, 1):
            self._fila(f, f'thr_ch{ch}', f'threshold IN{ch + 1}',
                       self._spin(f'thr_ch{ch}', -8192, 8191, CALIENTE,
                                  f'Trigger threshold of channel {ch}, in ADC '
                                  f'counts. {ADC_CNT_PER_V} counts = 1 V in LV.'))
        for ch in (0, 1):
            self._fila(f, f'hyst_ch{ch}', f'hysteresis IN{ch + 1}',
                       self._spin(f'hyst_ch{ch}', 0, 16383, CALIENTE,
                                  'How far the signal has to come back before '
                                  'another trigger is allowed. Too low, noise '
                                  'triggers too often.'))
        # En volts, en una fila propia: como campo de un QFormLayout no entra.
        self.lbl_thr_v = QLabel('—')
        f.addRow(self.lbl_thr_v)
        self._fila(f, 'deb_len', 'debounce',
                   self._spin('deb_len', 0, 0xFFFFF, CORTA,
                              'ADC cycles the trigger stays inhibited after one. '
                              'The RTL reset value is 62500 = 500 us.'))
        for campo in ('thr_ch0', 'thr_ch1', 'hyst_ch0'):
            self._controles[campo][0].valueChanged.connect(self._refrescar_umbral)
        return g

    def _grupo_bram(self):
        g = self._grupo('bram', 'BRAM capture')
        f = self._forma(g)
        for ch in (0, 1):
            self._fila(f, f'dly_ch{ch}', f'delay IN{ch + 1}',
                       self._spin(f'dly_ch{ch}', 0, N_BUF, CORTA,
                                  'Samples to capture AFTER the trigger before '
                                  'closing. It is real dead time: while it runs, '
                                  'wp_trig is not updated.'))
        self.lbl_fsm = QLabel('—')
        self.lbl_wp = QLabel('—')
        self.lbl_we = QLabel('—')
        self.lbl_fsm.setToolTip('The state of the two FSMs: the ADC write one and the '
                                'trigger one.')
        self.lbl_wp.setToolTip('The write pointer of IN1: the current one and the one '
                               'at the last trigger.')
        self.lbl_we.setToolTip('Accumulated triggers per channel (we_cnt).')
        f.addRow('FSM', self.lbl_fsm)
        f.addRow('wp IN1', self.lbl_wp)
        f.addRow('triggers', self.lbl_we)
        self.lbl_base = QLabel('—')
        self.lbl_base.setToolTip(
            'Physical address of the block, resolved by the SLOTS register of slot 6. '
            'If it does not match the constant, this bitstream has another topology — '
            'and seeing it here is how that gets diagnosed.')
        f.addRow('block base', self.lbl_base)

        self.btn_reset = QPushButton('Reset')
        self.btn_reset.setToolTip('Resets both OSC FSMs and releases adc_trg_dis.')
        self.btn_reset.clicked.connect(lambda: self.pedir_ctrl.emit('reset'))
        self.btn_sw = QPushButton('Software trigger')
        self.btn_sw.setToolTip('Forces a capture without waiting for a signal. It '
                               'confirms that the path to BRAM works.')
        self.btn_sw.clicked.connect(lambda: self.pedir_ctrl.emit('sw_trig'))
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(self.btn_reset)
        fila.addWidget(self.btn_sw)
        caja = QWidget()
        caja.setLayout(fila)
        f.addRow(caja)
        return g

    # ---------- el ring ----------

    def _armar_ring(self):
        r = self.ring = PanelRing(self, embebido=True)
        r.hide()
        r.grp_estimulo.setTitle('Ring stimulus')
        r.grp_ventana.setTitle('Ring window')
        r.grp_destino.setTitle('Reader and files')
        r.grp_estado.setTitle('Ring status')
        self._adoptar(r.grp_estimulo, 'disparo')
        self._adoptar(r.grp_ventana, 'ventana')
        self._adoptar(r.grp_destino, 'archivos')
        self._adoptar(r.grp_estado, 'ddr')
        for i, ws in ((2, (r.grp_estimulo, r.grp_ventana)),
                      (3, (r.caja_control, r.grp_destino))):
            for k, w in enumerate(ws):
                self._columnas[i].insertWidget(k, w)
        r.cmb_estimulo.currentIndexChanged.connect(self._al_cambiar_estimulo)
        r.usar_disparo_de(self._disparo_v)
        self._al_cambiar_estimulo()

    def _desarmar_ring(self):
        r = self.ring
        for g in (r.grp_estimulo, r.grp_ventana, r.grp_destino, r.grp_estado):
            etapa = g.property('etapa')
            if g in self._grupos.get(etapa, []):
                self._grupos[etapa].remove(g)
        for w in (r.grp_estimulo, r.grp_ventana, r.grp_destino, r.caja_control):
            w.setParent(None)
            w.deleteLater()
        r.deleteLater()
        self.ring = None

    def _al_cambiar_estimulo(self, *_):
        estimulo = self.ring.estimulo()
        self._reasignar(self.ring.grp_estimulo,
                        'generador' if estimulo == 'generador' else 'disparo')
        self.diagrama.set_estimulo(estimulo)

    def _disparo_v(self):
        """El umbral y la histéresis de IN1, en volts: con los que se arma el ring."""
        return (self._controles['thr_ch0'][1]() / self.cnt_por_v,
                self._controles['hyst_ch0'][1]() / self.cnt_por_v)

    def fijar_disparo_v(self, thr, hyst):
        """Escribe el umbral y la histéresis de IN1 en volts (los scripts de placa)."""
        self._controles['thr_ch0'][2](int(round(thr * self.cnt_por_v)))
        self._controles['hyst_ch0'][2](int(round(hyst * self.cnt_por_v)))

    def configurar(self, hay_osc, hay_ring, hay_generador=False):
        """Lo que trae el bitstream: el osciloscopio, el ring y su generador."""
        self._hay_osc = bool(hay_osc)
        if hay_ring and self.ring is None:
            self._armar_ring()
        elif not hay_ring and self.ring is not None:
            self._desarmar_ring()
        if self.ring is not None:
            self.ring.configurar_ring(hay_generador)
        self.diagrama.configurar(hay_osc, hay_ring)
        self.set_conectado(self._conectado)

    # =========================================================================
    # Desde el servidor
    # =========================================================================

    def actualizar_config(self, cfg):
        super().actualizar_config(cfg)
        self._refrescar_umbral()

    def _refrescar_umbral(self, *_):
        v0 = self._controles['thr_ch0'][1]() / self.cnt_por_v
        v1 = self._controles['thr_ch1'][1]() / self.cnt_por_v
        self.lbl_thr_v.setText(f'IN1 {v0:+.3f} V   ·   IN2 {v1:+.3f} V')
        if self.ring is not None:
            self.ring.mostrar_disparo()

    def actualizar_osc(self, info):
        """El `osc.get` del servidor: configuración, estado y base."""
        self.cnt_por_v = float(info.get('adc_cnt_per_v', self.cnt_por_v))
        self.actualizar_config(info.get('config', {}))
        n_buf = int(info.get('n_buf', 0) or 0)
        if n_buf:
            for ch in (0, 1):
                self._controles[f'dly_ch{ch}'][0].setMaximum(n_buf)
        base = info.get('base', 0)
        self.lbl_base.setText(f'{base:#010x}' if base else '—')

        est = info.get('status', {})
        if 'adc_state' in est:
            self.lbl_fsm.setText(f"ADC {est['adc_state']} · trigger "
                                 f"{est.get('trg_state', '—')}")
        if 'wp_cur_ch0' in est:
            self.lbl_wp.setText(f"{est['wp_cur_ch0']} · trig "
                                f"{est.get('wp_trig_ch0', '—')}")
        if 'we_cnt_ch0' in est:
            self.lbl_we.setText(f"IN1 {est['we_cnt_ch0']} · IN2 "
                                f"{est.get('we_cnt_ch1', '—')}")

        # La tasa de disparos, de Δwe_cnt/Δt: una cuenta acumulada. Un we_cnt que
        # retrocede es un reset del contador y no da tasa.
        we = est.get('we_cnt_ch0')
        if we is not None:
            ahora = time.monotonic()
            if self._we_prev is not None:
                dt, dwe = ahora - self._we_prev[0], we - self._we_prev[1]
                if dt > 1e-3 and dwe >= 0:
                    self.tasa_disparos = dwe / dt
            self._we_prev = (ahora, we)
        self.diagrama.actualizar_osc(est, self.tasa_disparos)

    def actualizar_ring(self, e):
        if self.ring is None:
            return
        self.ring.actualizar_ring(e)
        self.diagrama.actualizar_ring(e, self.ring.tasa_lectura
                                      if e.get('corriendo') else None)

    def mostrar_fallo_ring(self, mensaje):
        if self.ring is not None:
            self.ring.mostrar_fallo(mensaje)

    # =========================================================================
    # Estado de conexión
    # =========================================================================

    def set_conectado(self, conectado, running=False):
        self._conectado = conectado
        super().set_conectado(conectado and self._hay_osc, running)
        for b in (self.btn_reset, self.btn_sw):
            b.setEnabled(conectado and self._hay_osc)
        if self.ring is not None:
            self.ring.set_conectado(conectado)
        if not conectado:
            self._we_prev = None
            self.tasa_disparos = None
            self.diagrama.limpiar()
