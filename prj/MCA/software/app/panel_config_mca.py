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
marca su etapa en la franja y muestra el aviso con «Borrar»; el aviso se va al
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


def _opciones_features():
    conocidas = [(n, FEATURES[n]) for n in _ORDEN_FEATURES if n in FEATURES]
    # Si alguna vez FEATURES crece, aparece igual en vez de quedar invisible.
    conocidas += [(n, v) for n, v in sorted(FEATURES.items(), key=lambda kv: kv[1])
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
        g = self._grupo('entrada', 'Entrada')
        f = self._forma(g)
        f.addRow(self._check(
            'channel', 'usar IN2 (en vez de IN1)', INVALIDA,
            'Hay UN solo MCA con un mux de canal, no dos MCA independientes.'))
        f.addRow('decimación', self._spin(
            'dec', 1, 0xFFFF, INVALIDA,
            'Decimación propia del MCA. 1 = sin decimar.'))
        f.addRow('retardo (ciclos)', self._spin(
            'pre_dly', 0, 127, INVALIDA,
            'Retardo de la muestra respecto del disparo, para que la ventana '
            'abra en el pie del pulso: el disparo por pendiente llega tarde.\n'
            'Medido en placa con el pulso de la campaña y L=8, G=4: 16.\n'
            'Mueve también las ventanas del trapecio: trap_off = c + pre_dly + 2.\n'
            'La tabla y la regla: docs/mca/register_map_mca.md, "La línea de '
            'retardo".'))
        return g

    def _grupo_linea_base(self):
        g = self._grupo('base', 'Línea de base')
        f = self._forma(g)
        f.addRow(self._check(
            'bl_auto', 'seguidor automático', RIESGO,
            'Con el seguidor apagado se usa el valor fijo de abajo, que es '
            'inmune al problema de bl_k.'))
        f.addRow('bl_k (τ = 2^k) ⚠', self._spin(
            'bl_k', 0, 15, RIESGO,
            'La constante tiene que ser MUCHO más larga que el pulso: si es '
            'comparable, el seguidor persigue el pulso y lo borra antes de que '
            'cruce el umbral, y no se detecta NADA.\n'
            'Medido en placa con un pulso de 62 us:\n'
            '    bl_k=6  (τ=0.5 us)  ->      0 eventos\n'
            '    bl_k=9  (τ=4.1 us)  ->   2002 eventos\n'
            '    bl_k=12 (τ=32.8 us) ->   2001 eventos\n'
            'Regla: τ >= 100x la duración del pulso.'))
        f.addRow('holdoff', self._spin(
            'bl_holdoff', 0, 0xFFFF, INVALIDA,
            'Muestras que el seguidor ignora después de un pulso, para no '
            'aprender del propio pulso.'))
        f.addRow('base fija', self._spin(
            'baseline', 0, 0x3FFF, INVALIDA,
            'En cuentas. Sólo se usa con el seguidor automático apagado.'))
        return g

    def _grupo_trapecio(self):
        self.grp_trapecio = g = self._grupo('trapecio', 'Trapecio (F_TRAP)')
        f = self._forma(g)
        f.addRow('subida k, meseta m', _fila(self._spin(
            'trap_k', 1, 1023, INVALIDA,
            'Subida k, en muestras. Escribirlo reinicia el estado del trapecio. k '
            'largo promedia más ruido pero alarga la separación mínima entre pulsos, '
            'k + m.'), self._spin(
            'trap_m', 0, 1023, INVALIDA,
            'Meseta m, en muestras. Tiene que ser más larga que el tiempo de subida '
            'del pulso, o no hay meseta y F_TRAP promedia el flanco.')))
        f.addRow('M·16 (polo-cero)', self._spin(
            'trap_mq', 0, 0xFFFFF, INVALIDA,
            'M ~ τ − 0.5 de la cola que llega al ADC, y se ajusta en la placa '
            '(en la campaña quedó en 242.8: Mq = 3885).'))
        f.addRow('ventana desde, 2^lw', _fila(self._spin(
            'trap_off', 0, 0xFFFF, INVALIDA,
            'Muestras desde la apertura hasta el promedio sobre la meseta.'),
            self._spin('trap_lw', 0, 7, INVALIDA,
                       'El promedio sobre la meseta dura 2^lw muestras.')))
        f.addRow('escala >> sh', self._spin('trap_sh', 0, 63, INVALIDA))
        g.setToolTip('Sólo si el bitstream trae el trapecio (CAPS bit 2). Cómo '
                     'elegir los parámetros: docs/mca/register_map_mca.md.')
        return g

    def _grupo_segmentacion(self):
        g = self._grupo('segmentacion', 'Disparo y ranuras')
        f = self._forma(g)
        nota = QLabel('El disparo (umbral, histéresis) es del multitrigger: se '
                      'arma en Espectro.')
        nota.setWordWrap(True)
        nota.setStyleSheet('color: #777;')
        f.addRow(nota)
        f.addRow('ranuras', self._spin(
            'n_acc', 1, 4, CALIENTE,
            'Juegos de acumuladores que miden a la vez. Con 1 es la ventana '
            'única de antes; con más, un disparo que llega con una ventana '
            'abierta abre otra, y la pérdida pasa de ~ρ a ~ρ^N/N!.\n'
            'Lo medido sobre la cola de otro pulso viene contaminado: se marca '
            'en las features dt_anterior, dt_siguiente y solape, y lo corrige '
            'el trapecio.\n'
            'No cambia lo que se mide, sólo cuánto se pierde: no marca el '
            'histograma.'))
        return g

    def _grupo_compuertas(self):
        g = self._grupo('estadisticos', 'Ranuras: compuertas')
        f = self._forma(g)
        f.addRow('corta', self._spin(
            'gate_short', 0, 0xFFFF, INVALIDA,
            'Muestras desde el disparo hasta que arranca la integral de cola. '
            'Con 0, Q_cola == Q_total y el evento entra al 1D pero no al 2D.'))
        f.addRow('larga', self._spin(
            'gate_long', 0, 0xFFFF, INVALIDA,
            'Muestras desde el disparo hasta que la ventana cierra, pase lo que '
            'pase con la señal. Cada ranura la retiene al abrir.'))
        nota = QLabel('La ventana de amplitud se pone en Espectro.')
        nota.setWordWrap(True)
        nota.setStyleSheet('color: #777;')
        f.addRow(nota)
        return g

    def _grupo_eje(self):
        g = self._grupo('publicacion', 'Eje del histograma')
        f = self._forma(g)
        f.addRow(self._check(
            'amp_src', 'usar integral de carga', INVALIDA,
            'Apagado: la muestra de pico. Encendido: Q_total >> q_shift.\n'
            'La integral promedia el ruido blanco como sigma/sqrt(N) y es '
            'inmune al jitter de muestreo del pico; con la muestra de pico la '
            'amplitud sale de UNA muestra y el muestreo casi nunca cae en el '
            'máximo real.\n'
            'OJO: escribir este registro también mueve el selector del eje 1D, '
            'por compatibilidad con la campaña vieja.'))
        f.addRow('q_shift', self._spin(
            'q_shift', 0, 31, INVALIDA,
            'Divide la integral para que entre en el eje. Sólo con la integral.'))
        f.addRow('qué mide', self._combo(
            'sel_1d', _opciones_features(), INVALIDA,
            'Qué feature del pulso alimenta el espectro.\n'
            'Es el registro que agarró un bug del RTL en simulación: con el mux '
            'mal, TODO el espectro cae en el canal 0 sin ningún error.'))
        f.addRow('zoom (z)', self._spin(
            'zoom_1d_z', 0, 4, INVALIDA,
            'La ventana del eje es 2^-z del fondo de escala. z=0 es fondo de '
            'escala entero.\n'
            'NO mejora la resolución: sólo recupera la pérdida por binning, que '
            'ya es menor al 0.6 %. Sirve para encuadrar el eje sobre dos picos '
            'juntos, y para poder usar un histograma más chico sin ceder nada.\n'
            'Y la deriva empeora 2^z COMO FRACCIÓN DE LA VENTANA: con z=3 un '
            'corrimiento del 6.45 % mueve el pico un 41 % del ancho.'))
        f.addRow('ventana (k)', self._spin(
            'zoom_1d_k', 0, 255, INVALIDA,
            'Cuál de las 2^z ventanas se mira. Con z=0 no se usa.'))
        self.lbl_rango = QLabel('—')
        self.lbl_rango.setTextFormat(Qt.PlainText)
        f.addRow('rango', self.lbl_rango)
        return g

    def _grupo_discriminador(self):
        g = self._grupo('publicacion', 'Discriminador')
        f = self._forma(g)
        f.addRow(_fila(self._check(
            'discr_en', 'activo', INVALIDA,
            'Rechaza eventos por una feature elegida. Lo que rechaza se cuenta '
            'aparte en cnt_rej_discr, separado de cnt_rej_amp: son criterios '
            'distintos y hay que poder atribuir la pérdida a cada uno.'),
            self._check(
            'discr_ext', 'intervalo externo', INVALIDA,
            'Rechaza adentro del intervalo. Con el intervalo externo, min > max '
            'es legítimo: acepta todo. Con el interno, min > max sería un '
            'intervalo vacío y la API lo rechaza — el síntoma sería un espectro '
            'sin una sola cuenta.')))
        f.addRow('feature', self._combo(
            'discr_sel', _opciones_features(), INVALIDA))
        f.addRow('mínimo … máximo', _fila(
            self._spin('discr_min', 0, 0xFFFF, INVALIDA), QLabel('…'),
            self._spin('discr_max', 0, 0xFFFF, INVALIDA)))
        return g

    def _grupo_histograma(self):
        g = self._grupo('publicacion', 'Histograma')
        f = self._forma(g)
        self._check(
            'keep_if_full', 'seguir con el bin lleno', CALIENTE,
            'Apagado: los eventos que caen en un bin saturado NO se cuentan, y '
            'se acumulan aparte en cnt_full_supp.')
        self.btn_borrar = QPushButton('Borrar el histograma')
        self.btn_borrar.setToolTip(
            'Después de cambiar algo con cuentas en el histograma, para no '
            'mezclar dos configuraciones.')
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
        b = QPushButton('Borrar')
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
            f'El histograma mezcla dos configuraciones desde las {self._mezcla_desde}: '
            f'cambió {"; ".join(partes)}. Conviene borrarlo.')
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
            f'{lo} … {hi} cuentas\n{1 << self.h_aw} canales, {ancho:.1f} por canal')
