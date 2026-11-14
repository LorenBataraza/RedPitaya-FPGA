#!/usr/bin/env python3
"""Pestaña de Integración: el slot 6, que es donde vive la topología.

`integration_cfg` no es un bloque de procesamiento: es el registro de qué hay en
este bitstream y de POR DÓNDE pasan las muestras. Dos cosas se hacen desde acá:

  - **el ruteo del datapath**: de qué punto de la cadena DSP toma sus muestras
    cada consumidor (OSC, multitrigger, MCA, event_ring);
  - **el control global**: run / clear / soft reset de todo el sistema.

La cadena, para poder leer los taps sin ir al RTL::

    adc_dat -> calib -> osc_filter -> [byp] -> adc_dec_in ------------- TAP 2
       |                                          |            `-> MCA (nativo)
     TAP 1                                    rp_decim -> adc_dly_in
                                                  |          `-> multitrigger (nativo)
                                              rp_delay -> adc_bram_in -- TAP 3
                                                                `-> OSC (nativo)

Lo que NO se hace desde acá: la geometría del histograma. Esta región publica
una copia de `h_aw` que **puede mentir** —ya divergió una vez— y la fuente de
verdad es el registro WIDTHS del MCA. Se muestra igual, marcada, porque ver la
discrepancia es útil para diagnosticar un bitstream desactualizado.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)

from API.integration import TAP_ADC, TAP_BRAM_IN, TAP_DEC_IN, TAP_NATIVE

CONSUMIDORES = (
    ('osc',  'Oscilloscope', 'adc_bram_in'),
    ('mtrg', 'Multitrigger', 'adc_dly_in'),
    ('mca',  'MCA',          'adc_dec_in'),
    ('ring', 'event_ring',   'adc_dec_in'),
)

_AYUDA_TAP = {
    TAP_NATIVE:  'as it was wired before the refactor. It is the reset value.',
    TAP_ADC:     'raw sample, BEFORE calibration and equalizer.',
    TAP_DEC_IN:  'post-calibration and equalizer, PRE-decimation (125 MSPS).',
    TAP_BRAM_IN: 'after all the DSP (decimation + delay).',
}


class PanelIntegracion(QWidget):
    """Ruteo y control global. No hereda de PanelCampos: no escribe campos de
    `_CAMPOS` del MCA sino operaciones propias del slot 6."""

    pedir_ruteo = pyqtSignal(str, int, bool)   # consumidor, tap, enable
    pedir_reset_ruteos = pyqtSignal()
    pedir_ctrl = pyqtSignal(str)               # 'run_on' | 'run_off' | 'clear' | 'srst'
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cargando = False
        self._combos = {}
        self._construir()
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        interior = QWidget()
        v = QVBoxLayout(interior)
        v.addWidget(self._grupo_ruteo())
        v.addWidget(self._grupo_control())
        v.addWidget(self._grupo_topologia())
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(scroll)

    def _grupo_ruteo(self):
        g = QGroupBox('Datapath routing')
        v = QVBoxLayout(g)

        aviso = QLabel(
            'Changing the tap SHIFTS THE LATENCY: the delay counter counts in '
            'decimated samples, so an OSC on adc_dat and a multitrigger on native '
            'end up misaligned in the pre-trigger. It is legitimate, not free.\n'
            'And the AXI path to DDR is not routed: this affects the BRAM capture, '
            'not the rp_AcqAxi* captures.')
        aviso.setWordWrap(True)
        aviso.setStyleSheet('color: #888;')
        v.addWidget(aviso)

        f = QFormLayout()
        for clave, etiqueta, nativo in CONSUMIDORES:
            cb = QComboBox()
            cb.addItem(f'native ({nativo})', TAP_NATIVE)
            cb.addItem('adc_dat  (raw)', TAP_ADC)
            cb.addItem('adc_dec_in  (pre-decimation)', TAP_DEC_IN)
            cb.addItem('adc_bram_in  (post-DSP)', TAP_BRAM_IN)
            cb.setToolTip('\n'.join(
                f'{n}: {_AYUDA_TAP[t]}'
                for t, n in ((TAP_NATIVE, 'native'), (TAP_ADC, 'adc_dat'),
                             (TAP_DEC_IN, 'adc_dec_in'),
                             (TAP_BRAM_IN, 'adc_bram_in'))))
            cb.currentIndexChanged.connect(
                lambda _i, c=clave: self._cambio_tap(c))
            self._combos[clave] = cb
            f.addRow(etiqueta, cb)
        v.addLayout(f)

        fila = QHBoxLayout()
        self.btn_nativo = QPushButton('Everything back to native')
        self.btn_nativo.setToolTip(
            'The hardware reset state, that is, the pre-refactor behaviour. It is '
            'the way back to known ground without reloading the bitstream.')
        self.btn_nativo.clicked.connect(self.pedir_reset_ruteos.emit)
        fila.addWidget(self.btn_nativo)
        fila.addStretch(1)
        v.addLayout(fila)
        return g

    def _grupo_control(self):
        g = QGroupBox('Global control')
        v = QVBoxLayout(g)

        fila = QHBoxLayout()
        self.btn_run = QPushButton('run')
        self.btn_run.setCheckable(True)
        self.btn_run.toggled.connect(
            lambda on: self._ctrl('run_on' if on else 'run_off'))
        self.btn_clear = QPushButton('clear global')
        self.btn_clear.clicked.connect(lambda: self._ctrl('clear'))
        self.btn_srst = QPushButton('soft reset')
        self.btn_srst.setToolTip(
            'Reset pulse to every block. Self-clearing in hardware.')
        self.btn_srst.clicked.connect(lambda: self._ctrl('srst'))
        for b in (self.btn_run, self.btn_clear, self.btn_srst):
            fila.addWidget(b)
        fila.addStretch(1)
        v.addLayout(fila)

        self.lbl_status = QLabel('—')
        self.lbl_status.setTextFormat(Qt.PlainText)
        v.addWidget(self.lbl_status)
        return g

    def _grupo_topologia(self):
        g = QGroupBox('What this bitstream has')
        v = QVBoxLayout(g)
        self.lbl_topologia = QLabel('—')
        self.lbl_topologia.setTextFormat(Qt.PlainText)
        self.lbl_topologia.setStyleSheet('font-family: monospace;')
        v.addWidget(self.lbl_topologia)

        self.lbl_geometria = QLabel('')
        self.lbl_geometria.setWordWrap(True)
        v.addWidget(self.lbl_geometria)
        return g

    # =========================================================================
    # Estado
    # =========================================================================

    def _cambio_tap(self, consumidor):
        if self._cargando:
            return
        cb = self._combos[consumidor]
        self.pedir_ruteo.emit(consumidor, int(cb.currentData()), True)

    def _ctrl(self, que):
        if self._cargando:
            return
        self.pedir_ctrl.emit(que)

    def actualizar(self, info):
        """`info` es lo que devuelve la operación `integracion.get` del servidor."""
        self._cargando = True
        try:
            for clave, r in (info.get('routes') or {}).items():
                cb = self._combos.get(clave)
                if cb is None:
                    continue
                i = cb.findData(int(r.get('tap', 0)))
                cb.setCurrentIndex(max(0, i))
                # Un consumidor deshabilitado no recibe muestras: el `val` se
                # fuerza a 0. Se marca, porque si no, el tap elegido miente.
                cb.setEnabled(True)
                if not r.get('enable', True):
                    cb.setItemText(cb.currentIndex(),
                                   cb.currentText().split('  [')[0] + '  [NO SIGNAL]')

            self.btn_run.setChecked(bool(info.get('run', False)))
            st = info.get('status') or {}
            self.lbl_status.setText(
                f"pll_locked={st.get('pll_locked')}   "
                f"adc_rstn={st.get('adc_rstn')}   run={info.get('run')}")

            mods = info.get('modules') or {}
            slots = info.get('slots') or {}
            presentes = [k for k, v in mods.items() if v]
            filas = [f'modules : {" ".join(presentes) or "(none)"}']
            if slots:
                filas.append('slots   : ' + '  '.join(
                    f'{k}={v}' for k, v in sorted(slots.items(),
                                                  key=lambda kv: kv[1])))
            c = info.get('caps') or {}
            if c:
                filas.append(f'system  : n_ch={c.get("n_ch")} dw={c.get("dw")} '
                             f'rsz={c.get("rsz")} filter={c.get("en_filt")}')
            self.lbl_topologia.setText('\n'.join(filas))

            self._pintar_geometria(info)
        finally:
            self._cargando = False

    def _pintar_geometria(self, info):
        """La copia de la geometría que publica el slot 6, y si miente.

        Se muestra a propósito aunque no haya que usarla: ver la discrepancia es
        cómo se diagnostica un top re-sintetizado a medias.
        """
        c = info.get('caps') or {}
        coincide = info.get('geometria_coincide')
        if coincide is None or not c:
            self.lbl_geometria.setText('')
            return
        if coincide:
            self.lbl_geometria.setStyleSheet('color: #888;')
            self.lbl_geometria.setText(
                f'MCA geometry: h_aw={c.get("h_aw")} (matches WIDTHS)')
        else:
            self.lbl_geometria.setStyleSheet('color: #cc6600;')
            self.lbl_geometria.setText(
                info.get('geometria_motivo')
                or 'the geometry published here does NOT match the MCA one; '
                   'the MCA one holds')

    def set_conectado(self, conectado, running=False):
        for w in list(self._combos.values()) + [
                self.btn_nativo, self.btn_run, self.btn_clear, self.btn_srst]:
            w.setEnabled(conectado)
