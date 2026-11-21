#!/usr/bin/env python3
"""Pestaña de configuración del MCA2: los registros del slot 7, por etapa del dato.

Arriba, la franja del datapath (`diagrama_mca.py`): las etapas del panorama con sus
colores, las tasas de cada tramo, lo que se pierde en cada etapa y la leyenda de la
pestaña. Abajo, todos los controles a la vista en tres columnas, una por función
(preprocesamiento; disparo y ranuras; publicación); el título de cada grupo lleva el
color de su bloque. El grupo con el foco o con el ratón encima se
resalta en la franja, y un clic en un bloque lleva a sus controles.

Cada control escribe SOLO su campo, con read-modify-write: escribir el bloque
entero pone `run=0` en `R_CTRL`, o sea que tocar un campo pararía la medición.

**Nada de esto pide parar el MCA.** Todos los `cfg_*` se escriben en caliente y
valen desde el ciclo siguiente: ninguno se toma recién al arrancar (mca_top.sv). Las
ranuras retienen sus compuertas al abrir, y escribir el trapecio reinicia su estado.
Lo que sí se rompe es el histograma: casi todo cambia lo que se mide, y lo acumulado
pasa a mezclar dos configuraciones. Por eso un cambio con cuentas en el histograma
marca su etapa en la franja y muestra el aviso con «Clear»; el aviso se va al
borrar (desde acá, desde Espectro, o con el borrado de una adquisición). Sólo las
ranuras habilitadas y el bin lleno no cambian lo que se mide (CALIENTE).

En el MCA2 la ventana la abre el disparo del multitrigger: el umbral es de él, no
del MCA, y se arma desde la pestaña del espectro, igual que la ventana de amplitud.
"""

import time

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

from API.mca import AMP_W, FEATURES, mca_amplitud_de_canal
from app.diagrama_mca import COLOR, ETAPAS, DiagramaMCA
from app.panel_etapas import PanelPorEtapas
from app.widgets_config import CALIENTE, CORTA, INVALIDA, RIESGO

# Las features que pueden alimentar un eje, en el orden en que conviene verlas.
# Sale de FEATURES de API/mca.py para no tener una segunda lista que se
# desincronice; el orden se fija acá.
_ORDEN_FEATURES = ('pico', 'integral', 'trapecio', 'psd', 'ancho_inv', 'largo',
                   't_subida', 'dt_anterior', 'dt_siguiente', 'solape')

_NOMBRE_ETAPA = {clave: titulo for clave, titulo, _d, _c in ETAPAS}


def _fila(*widgets):
    """Varios controles en una fila del formulario: los que van juntos ahorran alto,
    y la pestaña entra entera sin scroll."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    h.addStretch(1)
    return w


# Cómo se leen en la GUI: los nombres de FEATURES son los de la API.
_NOMBRE_FEATURE = {'pico': 'peak', 'integral': 'integral', 'trapecio': 'trapezoid',
                   'psd': 'psd', 'ancho_inv': 'inverse width', 'largo': 'length',
                   't_subida': 'rise time', 'dt_anterior': 'dt to previous',
                   'dt_siguiente': 'dt to next', 'solape': 'overlap',
                   'forma': 'shape'}


def _opciones_features():
    conocidas = [(_NOMBRE_FEATURE.get(n, n), FEATURES[n]) for n in _ORDEN_FEATURES
                 if n in FEATURES]
    # Si alguna vez FEATURES crece, aparece igual en vez de quedar invisible.
    conocidas += [(_NOMBRE_FEATURE.get(n, n), v)
                  for n, v in sorted(FEATURES.items(), key=lambda kv: kv[1])
                  if n not in _ORDEN_FEATURES]
    return conocidas


class PanelConfigMCA(PanelPorEtapas):

    # `pedir_campo` y `log` los hereda de PanelCampos; ésta es propia porque el
    # borrado no es un campo de configuración sino una acción.
    pedir_clear = pyqtSignal()

    # Casi todo es INVALIDA: la casilla lleva marca sólo si es de riesgo. Lo que
    # cambia lo que se mide lo dice el aviso, cuando de verdad se cambia.
    MARCAS = {CALIENTE: '', CORTA: '', INVALIDA: '', RIESGO: ' ⚠'}
    COLOR = COLOR

    def __init__(self, parent=None):
        super().__init__(parent)
        self.h_aw = 13
        self._hay_trapecio = False
        self._mezcla = {}              # etapa -> {campos cambiados con cuentas}
        self._mezcla_desde = None
        self._hay_cuentas = False
        self._real_ultimo = None
        self._construir()
        self.grp_trapecio.setVisible(False)
        self.diagrama.ocultar({'trapecio'})
        self.set_conectado(False)

    # =========================================================================
    # Construcción
    # =========================================================================

    def _construir(self):
        self.diagrama = DiagramaMCA()
        self.diagrama.etapa_elegida.connect(self._ir_a_etapa)

        interior = QWidget()
        cols = QHBoxLayout(interior)
        cols.setContentsMargins(0, 0, 0, 0)
        # Tres columnas, una por función del panorama y en el orden del dato: el
        # preprocesamiento (azul), el disparo y las ranuras (amarillo y verde) y la
        # publicación (naranja).
        for grupos in ((self._grupo_entrada(), self._grupo_linea_base(),
                        self._grupo_trapecio()),
                       (self._grupo_segmentacion(), self._grupo_compuertas()),
                       (self._grupo_eje(), self._grupo_discriminador(),
                        self._grupo_histograma())):
            v = QVBoxLayout()
            for g in grupos:
                v.addWidget(g)
            v.addStretch(1)
            cols.addLayout(v, 1)

        # Por si la ventana es más chica que lo que entra: no es el caso normal.
        self.scroll = scroll = QScrollArea()
        scroll.setWidget(interior)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        caja = QVBoxLayout(self)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.addWidget(self.diagrama)
        caja.addWidget(self._aviso_mezcla())
        caja.addWidget(scroll, 1)

    # ---------- las etapas, en el orden del dato ----------

    def _grupo_entrada(self):
        g = self._grupo('entrada', 'Input')
        f = self._forma(g)
        f.addRow(self._check(
            'channel', 'use IN2 (instead of IN1)', INVALIDA,
            'There is ONE MCA with a channel mux, not two independent MCAs.'))
        f.addRow('decimation', self._spin(
            'dec', 1, 0xFFFF, INVALIDA,
            'The MCA\'s own decimation. 1 = no decimation.'))
        f.addRow('delay (cycles)', self._spin(
            'pre_dly', 0, 127, INVALIDA,
            'Delay of the sample relative to the trigger, so the window opens at '
            'the foot of the pulse: the slope trigger arrives late.\n'
            'Measured on the board with the campaign pulse and L=8, G=4: 16.\n'
            'It also moves the trapezoid windows: trap_off = c + pre_dly + 2.\n'
            'The table and the rule: docs/mca/register_map_mca.md, "La línea de '
            'retardo".'))
        return g

    def _grupo_linea_base(self):
        g = self._grupo('base', 'Baseline')
        f = self._forma(g)
        f.addRow(self._check(
            'bl_auto', 'automatic tracker', RIESGO,
            'With the tracker off, the fixed value below is used, which is immune '
            'to the bl_k problem.'))
        f.addRow('bl_k (τ = 2^k) ⚠', self._spin(
            'bl_k', 0, 15, RIESGO,
            'The time constant has to be MUCH longer than the pulse: if it is '
            'comparable, the tracker follows the pulse and erases it before it '
            'crosses the threshold, and NOTHING is detected.\n'
            'Measured on the board with a 62 us pulse:\n'
            '    bl_k=6  (τ=0.5 us)  ->      0 events\n'
            '    bl_k=9  (τ=4.1 us)  ->   2002 events\n'
            '    bl_k=12 (τ=32.8 us) ->   2001 events\n'
            'Rule: τ >= 100x the pulse duration.'))
        f.addRow('holdoff', self._spin(
            'bl_holdoff', 0, 0xFFFF, INVALIDA,
            'Samples the tracker ignores after a pulse, so it does not learn from '
            'the pulse itself.'))
        f.addRow('fixed baseline', self._spin(
            'baseline', 0, 0x3FFF, INVALIDA,
            'In counts. Only used with the automatic tracker off.'))
        # Con la base dinámica («Calibration») el servidor la mueve con la tasa.
        self.lbl_base_dinamica = self._nota(
            'The dynamic base is on («Calibration»): the server moves the fixed base '
            'with the rate. Turn it off there to edit it.', '#c0392b')
        self.lbl_base_dinamica.hide()
        f.addRow(self.lbl_base_dinamica)
        return g

    def set_base_dinamica(self, on):
        """Con la base dinámica prendida el campo de la base fija es de sólo lectura:
        lo que se escriba ahí cambiaría b0 en el servidor, no la base en uso."""
        on = bool(on)
        if on == getattr(self, '_base_dinamica', False):
            return
        self._base_dinamica = on
        self._controles['baseline'][0].setReadOnly(on)
        self.lbl_base_dinamica.setVisible(on)

    @property
    def base_dinamica(self):
        return getattr(self, '_base_dinamica', False)

    def _grupo_trapecio(self):
        self.grp_trapecio = g = self._grupo('trapecio', 'Trapezoid (F_TRAP)')
        f = self._forma(g)
        f.addRow('rise k, flat top m', _fila(self._spin(
            'trap_k', 1, 1023, INVALIDA,
            'Rise k, in samples. Writing it resets the trapezoid state. A long k '
            'averages more noise but lengthens the minimum pulse separation, '
            'k + m.'), self._spin(
            'trap_m', 0, 1023, INVALIDA,
            'Flat top m, in samples. It has to be longer than the pulse rise time, '
            'or there is no flat top and F_TRAP averages the edge.')))
        f.addRow('M·16 (pole-zero)', self._spin(
            'trap_mq', 0, 0xFFFFF, INVALIDA,
            'M ~ τ − 0.5 of the tail reaching the ADC, tuned on the board (in the '
            'campaign it ended at 242.8: Mq = 3885).'))
        f.addRow('window from, 2^lw', _fila(self._spin(
            'trap_off', 0, 0xFFFF, INVALIDA,
            'Samples from the window opening to the average over the flat top.'),
            self._spin('trap_lw', 0, 7, INVALIDA,
                       'The average over the flat top lasts 2^lw samples.')))
        f.addRow('scale >> sh', self._spin('trap_sh', 0, 63, INVALIDA))
        g.setToolTip('Only if the bitstream has the trapezoid (CAPS bit 2). How to '
                     'choose the parameters: docs/mca/register_map_mca.md.')
        return g

    def _grupo_segmentacion(self):
        g = self._grupo('segmentacion', 'Segmentation')
        f = self._forma(g)
        nota = QLabel('Each trigger of the multitrigger opens a slot. The trigger '
                      'is set in the Multitrigger tab.')
        nota.setWordWrap(True)
        nota.setStyleSheet('color: #777;')
        f.addRow(nota)
        f.addRow('slots', self._spin(
            'n_acc', 1, 4, CALIENTE,
            'Sets of accumulators that measure at the same time. With 1 it is the '
            'single window of before; with more, a trigger that arrives with a '
            'window open opens another one, and the loss goes from ~ρ to ~ρ^N/N!.\n'
            'What is measured on the tail of another pulse is contaminated: it is '
            'flagged in the features dt_anterior, dt_siguiente and solape, and the '
            'trapezoid corrects it.\n'
            'It does not change what is measured, only how much is lost: it does '
            'not mark the histogram.'))
        return g

    def _grupo_compuertas(self):
        g = self._grupo('estadisticos', 'Slots: gates')
        f = self._forma(g)
        f.addRow('short', self._spin(
            'gate_short', 0, 0xFFFF, INVALIDA,
            'Samples from the trigger until the tail integral starts. With 0, '
            'Q_tail == Q_total and the event goes to the 1D but not to the 2D.'))
        f.addRow('long', self._spin(
            'gate_long', 0, 0xFFFF, INVALIDA,
            'Samples from the trigger until the window closes, whatever the signal '
            'does. Each slot latches it when it opens.'))
        # Q_total suma [0, larga) desde el disparo y Q_cola [corta, larga): la PSD
        # es Q_cola / Q_total (docs/mca/register_map_mca.md).
        self.lbl_compuertas = self._nota()
        f.addRow(self.lbl_compuertas)
        for campo in ('gate_short', 'gate_long', 'dec'):
            self._controles[campo][0].valueChanged.connect(self._pintar_compuertas)
        self._pintar_compuertas()
        return g

    def _pintar_compuertas(self, *_):
        ns = 8.0 * max(1, self._controles['dec'][1]())        # 125 MSPS / dec

        def t(muestras):
            x = muestras * ns
            return f'{x / 1000:.2f} µs' if x >= 1000 else f'{x:.0f} ns'

        corta = self._controles['gate_short'][1]()
        larga = self._controles['gate_long'][1]()
        self.lbl_compuertas.setText(
            f'Counted from the trigger: the window closes at long ({t(larga)}) '
            f'whatever the signal does; Q_total sums all of it and Q_tail from short '
            f'({t(corta)}) on. PSD = Q_tail / Q_total. The amplitude window is in '
            f'Spectrum.')

    def _grupo_eje(self):
        g = self._grupo('publicacion', 'Histogram axis')
        f = self._forma(g)
        f.addRow(self._check(
            'amp_src', 'use the charge integral', INVALIDA,
            'Off: the peak sample. On: Q_total >> q_shift.\n'
            'The integral averages white noise as sigma/sqrt(N) and is immune to '
            'the sampling jitter of the peak; with the peak sample the amplitude '
            'comes from ONE sample and the sampling almost never hits the real '
            'maximum.\n'
            'NOTE: writing this register also moves the 1D axis selector, for '
            'compatibility with the old campaign.'))
        f.addRow('q_shift', self._spin(
            'q_shift', 0, 31, INVALIDA,
            'Divides the integral so it fits in the axis. Only with the integral.'))
        f.addRow('measures', self._combo(
            'sel_1d', _opciones_features(), INVALIDA,
            'Which pulse feature feeds the spectrum.\n'
            'It is the register that caught an RTL bug in simulation: with the mux '
            'wrong, the WHOLE spectrum falls in channel 0 without any error.'))
        f.addRow('zoom (z)', self._spin(
            'zoom_1d_z', 0, 4, INVALIDA,
            'The axis window is 2^-z of full scale. z=0 is the whole full scale.\n'
            'It does NOT improve the resolution: it only recovers the binning loss, '
            'already below 0.6 %. It frames the axis on two close peaks, and lets a '
            'smaller histogram be used without giving anything up.\n'
            'And drift gets 2^z worse AS A FRACTION OF THE WINDOW: with z=3 a 6.45 % '
            'shift moves the peak 41 % of the width.'))
        f.addRow('window (k)', self._spin(
            'zoom_1d_k', 0, 255, INVALIDA,
            'Which of the 2^z windows is shown. Not used with z=0.'))
        self.lbl_rango = QLabel('—')
        self.lbl_rango.setTextFormat(Qt.PlainText)
        f.addRow('range', self.lbl_rango)
        return g

    def _grupo_discriminador(self):
        g = self._grupo('publicacion', 'Discriminator')
        f = self._forma(g)
        f.addRow(_fila(self._check(
            'discr_en', 'active', INVALIDA,
            'Rejects events by a chosen feature. What it rejects is counted apart '
            'in cnt_rej_discr, separate from cnt_rej_amp: they are different '
            'criteria and the loss has to be attributable to each.'),
            self._check(
            'discr_ext', 'outer interval', INVALIDA,
            'Rejects inside the interval. With the outer interval, min > max is '
            'legitimate: it accepts everything. With the inner one, min > max would '
            'be an empty interval and the API rejects it — the symptom would be a '
            'spectrum without a single count.')))
        f.addRow('feature', self._combo(
            'discr_sel', _opciones_features(), INVALIDA))
        f.addRow('minimum … maximum', _fila(
            self._spin('discr_min', 0, 0xFFFF, INVALIDA), QLabel('…'),
            self._spin('discr_max', 0, 0xFFFF, INVALIDA)))
        return g

    def _grupo_histograma(self):
        g = self._grupo('publicacion', 'Histogram')
        f = self._forma(g)
        self._check(
            'keep_if_full', 'keep going with a full bin', CALIENTE,
            'Off: events that fall in a saturated bin are NOT counted, and are '
            'accumulated apart in cnt_full_supp.')
        self.btn_borrar = QPushButton('Clear the histogram')
        self.btn_borrar.setToolTip(
            'After changing something with counts in the histogram, so as not to '
            'mix two configurations.')
        self.btn_borrar.clicked.connect(self._borrar)
        f.addRow(_fila(self._controles['keep_if_full'][0], self.btn_borrar))
        return g

    def _aviso_mezcla(self):
        self.frm_mezcla = w = QFrame()
        w.setStyleSheet('QFrame { background: #fdebd0; border: 1px solid #e67e22; '
                        'border-radius: 3px; } QLabel { border: none; color: black; }')
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 3, 8, 3)
        self.lbl_mezcla = QLabel()
        self.lbl_mezcla.setWordWrap(True)
        h.addWidget(self.lbl_mezcla, 1)
        b = QPushButton('Clear')
        b.clicked.connect(self._borrar)
        h.addWidget(b)
        w.setVisible(False)
        return w

    # =========================================================================
    # El aviso: el histograma mezcla configuraciones
    # =========================================================================

    def _emitir(self, campo, valor):
        if self._cargando:
            return
        super()._emitir(campo, valor)
        if self._cuando.get(campo, CALIENTE) == CALIENTE or not self._hay_cuentas:
            return
        etapa = self._etapa_de.get(campo)
        if etapa is None:
            return
        if not self._mezcla:
            self._mezcla_desde = time.strftime('%H:%M:%S')
        self._mezcla.setdefault(etapa, set()).add(campo)
        self._pintar_mezcla()

    def _pintar_mezcla(self):
        self.diagrama.marcar(self._mezcla)
        if not self._mezcla:
            self.frm_mezcla.setVisible(False)
            return
        partes = []
        for clave, _t, _d, _c in ETAPAS:
            if clave in self._mezcla:
                partes.append(f"{_NOMBRE_ETAPA[clave]} ({', '.join(sorted(self._mezcla[clave]))})")
        self.lbl_mezcla.setText(
            f'The histogram mixes two configurations since {self._mezcla_desde}: '
            f'{"; ".join(partes)} changed. Clear it.')
        self.frm_mezcla.setVisible(True)

    def _limpiar_mezcla(self):
        if self._mezcla:
            self._mezcla = {}
            self._mezcla_desde = None
            self._pintar_mezcla()

    def _borrar(self):
        self.pedir_clear.emit()
        self._limpiar_mezcla()

    @property
    def mezcla(self):
        """{etapa: campos} de los cambios hechos con cuentas en el histograma."""
        return {k: set(v) for k, v in self._mezcla.items()}

    # =========================================================================
    # Estado
    # =========================================================================

    def actualizar_estado(self, est):
        """El `status` del MCA, cada 200 ms: las tasas de la franja, si hay cuentas
        en el histograma, y si se borró (el reloj real vuelve atrás o no queda
        nada): entonces se va el aviso, lo haya borrado quien sea."""
        cnt = est.get('counters') or {}
        self.diagrama.actualizar(cnt, est.get('tasa_entrada_hz', 0.0))
        real = float(cnt.get('realtime_s', 0.0) or 0.0)
        cuentas = int(cnt.get('total', 0) or 0) + int(cnt.get('accepted', 0) or 0)
        borrado = cuentas == 0 or (self._real_ultimo is not None
                                   and real < self._real_ultimo - 0.05)
        if borrado:
            self._limpiar_mezcla()
        self._hay_cuentas = cuentas > 0
        self._real_ultimo = real

    def configurar_mca(self, info):
        """Lo que depende del bitstream: cuántas ranuras y si hay trapecio."""
        n_max = int(info.get('n_acc_max') or 1)
        self._controles['n_acc'][0].setMaximum(max(1, n_max))
        self._hay_trapecio = bool(info.get('trap'))
        self.grp_trapecio.setVisible(self._hay_trapecio)
        self.diagrama.ocultar(set() if self._hay_trapecio else {'trapecio'})

    def set_conectado(self, conectado, running=False):
        super().set_conectado(conectado, running)
        for campo in ('trap_k', 'trap_m', 'trap_mq', 'trap_off', 'trap_lw',
                      'trap_sh'):
            self._controles[campo][0].setEnabled(conectado and self._hay_trapecio)
        self.btn_borrar.setEnabled(conectado)
        if not conectado:
            self.diagrama.limpiar()
            self._limpiar_mezcla()
            self._hay_cuentas = False
            self._real_ultimo = None

    def configurar_geometria(self, n_canales, h_aw=None):
        self.h_aw = int(h_aw) if h_aw is not None else \
            max(1, int(n_canales)).bit_length() - 1
        # El zoom no puede pasar de AMP_W - h_aw: más allá no quedan bits que
        # rebanar y el RTL lo satura en silencio. Se acota el control para que
        # no se pueda pedir algo que el hardware va a recortar.
        z_max = max(0, AMP_W - self.h_aw)
        self._controles['zoom_1d_z'][0].setMaximum(z_max)
        self._refrescar_rango()

    def actualizar_config(self, cfg):
        super().actualizar_config(cfg)
        if cfg.get('h_aw') is not None:
            self.configurar_geometria(1 << int(cfg['h_aw']), int(cfg['h_aw']))
        self._refrescar_rango()

    def _refrescar_rango(self):
        """Qué amplitudes cubre el eje con el zoom actual.

        Sin esto, `z` y `k` son dos números sin unidades y no hay forma de saber
        qué ventana se está mirando sin hacer la cuenta a mano.
        """
        z = self._controles['zoom_1d_z'][1]()
        k = self._controles['zoom_1d_k'][1]()
        lo = mca_amplitud_de_canal(0, self.h_aw, z, k)
        hi = mca_amplitud_de_canal((1 << self.h_aw) - 1, self.h_aw, z, k)
        ancho = (hi - lo) / max(1, (1 << self.h_aw) - 1)
        self.lbl_rango.setText(
            f'{lo} … {hi} counts\n{1 << self.h_aw} channels, {ancho:.1f} per channel')
