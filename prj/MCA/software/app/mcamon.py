#!/usr/bin/env python3
"""mcamon — monitor del MCA de la Red Pitaya. Corre en la PC.

    python3 app/mcamon.py [--host 10.73.28.27] [--port 1001] [--conectar]

Del otro lado tiene que estar `app/mca_server.py` corriendo en la placa.

El socket lo maneja un hilo aparte y la GUI nunca lo toca: un espectro completo
son ~110 ms de lectura palabra a palabra en la Pitaya (el esclavo AXI rechaza
las ráfagas), y hacerlo en el hilo de la interfaz la congelaría en cada
refresco.

Refrescar en vivo es barato pese a eso: la lectura del bus tiene prioridad
sobre el pipeline del histograma y el evento que colisiona se cuenta en
`dropped`, pero ocupa el puerto ~2 ciclos cada 6.7 us. Con un refresco por
segundo la pérdida es del orden del 0.01 % de los eventos — y queda a la vista
en el contador de perdidos.
"""

import argparse
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))          # .../software

from PyQt5.QtCore import (QMetaObject, QObject, Qt, QThread, QTimer,
                          pyqtSignal, pyqtSlot)
from PyQt5.QtWidgets import (QAction, QApplication, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QPushButton, QSpinBox, QSizePolicy, QTabWidget,
                             QVBoxLayout, QWidget)

import API.mca as A
from API.mca_net import PORT_DEFAULT
from API.mca_remote import MCARemote
from app.panel_config_mca import PanelConfigMCA
from app.panel_config_osc import PanelConfigOsc
from app.panel_espectro import REFRESCO_ESPECTRO_S, PanelEspectro
from app.panel_generador import PanelGenerador
from app.panel_integracion import PanelIntegracion
from app.panel_log import PanelLog
from app.panel_mapa2d import PanelMapa2D
from app.panel_multitrigger import PanelMultitrigger
from app.panel_pulsos import PanelPulsos

PERIODO_ESTADO_MS = 200


# =============================================================================
# Hilo del socket
# =============================================================================

class EtiquetaRecortada(QLabel):
    """Un QLabel que, si no entra, corta el final con «…» y deja el texto entero
    en el tooltip. Es el estado de la barra de arriba: no tiene que ensanchar la
    ventana."""

    def __init__(self, texto=''):
        super().__init__()
        self._completo = ''
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(120)
        self.setText(texto)

    def setText(self, texto):
        self._completo = texto
        self.setToolTip(texto)
        self._recortar()

    def text(self):
        return self._completo

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._recortar()

    def _recortar(self):
        corto = self.fontMetrics().elidedText(self._completo, Qt.ElideRight,
                                              max(0, self.width() - 2))
        QLabel.setText(self, corto)


class Trabajador(QObject):
    """Dueño único del `MCARemote`. Vive en su propio QThread."""

    conectado = pyqtSignal(dict)
    desconectado = pyqtSignal(str)
    estado = pyqtSignal(dict)
    espectro = pyqtSignal(object, dict)
    mapa2d = pyqtSignal(object)
    config = pyqtSignal(dict)
    integracion = pyqtSignal(dict)
    osc_info = pyqtSignal(dict)
    mtrg_info = pyqtSignal(dict)
    gen_info = pyqtSignal(dict)              # el gen.get del generador de pulsos
    ring_info = pyqtSignal(dict)             # el ring.estado (o el ring.parar)
    ring_fallo = pyqtSignal(str)             # un ring.* rechazado, para la pestaña
    disparo_info = pyqtSignal(dict)          # el estado de la op mca.disparo
    traza = pyqtSignal(dict, object)          # metadata, float32[n_ch, n]
    aviso = pyqtSignal(str)
    fallo = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.h = None
        self._mapa_visible = False

    # ---------- arranque ----------

    @pyqtSlot()
    def arrancar(self):
        # Los temporizadores se crean ACÁ y no en __init__ para que pertenezcan
        # al hilo del trabajador: uno creado en el hilo de la GUI dispararía en
        # el hilo de la GUI y tocaría el socket desde ahí.
        self._t_estado = QTimer(self, interval=PERIODO_ESTADO_MS)
        self._t_estado.timeout.connect(self._tic_estado)
        self._t_espectro = QTimer(self, interval=int(REFRESCO_ESPECTRO_S * 1000))
        self._t_espectro.timeout.connect(self._tic_espectro)

    # ---------- conexión ----------

    @pyqtSlot(str, int)
    def conectar(self, host, port):
        self.desconectar()
        try:
            self.h = MCARemote.connect(host, port, timeout=15.0)
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'could not connect to {host}:{port} — '
                            f'{type(e).__name__}: {e}')
            return
        info = self.h.info
        self.conectado.emit(info)
        if not info.get('presente'):
            self.aviso.emit('connected, but there is no MCA: ' +
                            str(info.get('error')))
            return
        self._leer_config()
        if info.get('has_disparo'):
            self.disparo({})                     # el estado, sin tocar nada
        self._tic_estado()
        self._tic_espectro()
        self._t_estado.start()
        self._t_espectro.start()

    @pyqtSlot()
    def desconectar(self):
        for t in ('_t_estado', '_t_espectro'):
            if hasattr(self, t):
                getattr(self, t).stop()
        if self.h is not None:
            try:
                self.h.close()
            except OSError:
                pass
            self.h = None
            self.desconectado.emit('disconnected')

    def _caido(self, e):
        """Un error de transporte no se reintenta: se cae la conexión."""
        self.fallo.emit(f'{type(e).__name__}: {e}')
        self.desconectar()

    # ---------- poleo ----------

    @pyqtSlot()
    def _tic_estado(self):
        if self.h is None:
            return
        try:
            self.estado.emit(self.h.status())
        except OSError as e:
            self._caido(e)
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'status: {type(e).__name__}: {e}')

    @pyqtSlot()
    def _tic_espectro(self):
        if self.h is None:
            return
        try:
            # Las variantes en bloque del handle remoto: `mca_read_histogram` y
            # `mca_get_metadata` darían lo mismo, pero la segunda relee los 19
            # campos de a uno y son 19 idas y vueltas por refresco.
            self.espectro.emit(self.h.spectrum(), self.h.metadata())
            if self._mapa_visible and self.h._has_2d:
                self.mapa2d.emit(self.h.map2d())
        except OSError as e:
            self._caido(e)
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'read: {type(e).__name__}: {e}')

    def _leer_config(self):
        try:
            self.config.emit(self.h.config())
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'config: {type(e).__name__}: {e}')

    # ---------- comandos ----------

    @pyqtSlot(float, bool)
    def start(self, segundos, borrar_antes):
        if self.h is None:
            return
        try:
            self.h._pedir('ctrl.start', seconds=(segundos or None),
                          clear_first=borrar_antes)
            self.aviso.emit(f'acquisition started'
                            + (f', {segundos:.3f} s of live time'
                               if segundos else ', no limit'))
            self._tic_estado()
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'start: {type(e).__name__}: {e}')

    @pyqtSlot()
    def parar(self):
        if self.h is None:
            return
        try:
            self.h.stop()
            self.aviso.emit('acquisition stopped')
            self._tic_estado()
            self._tic_espectro()
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'stop: {type(e).__name__}: {e}')

    @pyqtSlot()
    def borrar(self):
        if self.h is None:
            return
        try:
            self.h.clear()
            self.aviso.emit('counts, histograms and clocks cleared')
            self._tic_estado()
            self._tic_espectro()
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'clear: {type(e).__name__}: {e}')

    @pyqtSlot(str, int)
    def escribir_campo(self, campo, valor):
        """Escribe UN campo con su `mca_set_<campo>` de API/mca.py.

        No se usa `mca_configure`: el bloque entero escribe R_CTRL con run=0, o
        sea que tocar un campo pararía la medición en curso. Y se pasa por el
        setter público, no por `_escribir_campo`, porque varios validan
        (`dec`, `n_acc`, `pre_dly`, el trapecio).
        """
        if self.h is None:
            return
        try:
            getattr(A, f'mca_set_{campo}')(self.h, valor)
            self.aviso.emit(f'{campo} = {valor}')
            if campo == 'pre_dly':
                self._aviso_pre_dly()
            self._leer_config()
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'{campo}: {type(e).__name__}: {e}')

    def _aviso_pre_dly(self):
        """`pre_dly` mueve las ventanas del trapecio (off = c + pre_dly + 2), y
        trap_ok no lo nota: mira que entren en la compuerta, no que caigan sobre
        la meseta. Sólo importa si alguien está mirando el trapecio."""
        cfg = A.mca_get_config(self.h)
        trap = {A.FEATURES['trapecio'], A.FEATURES['forma']}
        if cfg['n_formas'] > 1 or {cfg['sel_1d'], cfg['sel_2dx'], cfg['sel_2dy']} & trap:
            self.aviso.emit('pre_dly moved the trapezoid windows: trap_off has to be '
                            'recomputed (off = c + pre_dly + 2)')

    # ---------- integración (slot 6) ----------
    #
    # Van por `h.pedir()` y no por una función de API/integration.py porque el
    # handle que tiene el cliente es el del MCA por socket: el driver del slot 6
    # vive en la placa, del lado del servidor. Es la misma división que con
    # `fpga.load_bitstream`.

    def _pedir_integracion(self, op, **args):
        if self.h is None:
            return
        try:
            self.integracion.emit(self.h.pedir(op, **args))
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'{op}: {type(e).__name__}: {e}')

    @pyqtSlot()
    def leer_integracion(self):
        self._pedir_integracion('integracion.get')

    @pyqtSlot(str, int, bool)
    def set_ruteo(self, consumidor, tap, enable):
        self._pedir_integracion('integracion.set_route', consumidor=consumidor,
                                tap=int(tap), enable=bool(enable))
        self.aviso.emit(f'route {consumidor} -> tap {tap}')

    @pyqtSlot()
    def reset_ruteos(self):
        self._pedir_integracion('integracion.reset_routes')
        self.aviso.emit('routes back to native')

    @pyqtSlot(str)
    def ctrl_integracion(self, que):
        self._pedir_integracion('integracion.ctrl', que=que)
        self.aviso.emit(f'global control: {que}')

    # ---------- osciloscopio y multitrigger ----------
    #
    # Mismo criterio que el slot 6: el driver vive en la placa y el cliente sólo
    # puede pedirle al servidor que lo use. La diferencia es `osc.capture`, que
    # trae payload binario y por eso no pasa por `pedir()`.

    def _pedir_osc(self, op, señal, **args):
        if self.h is None:
            return
        try:
            señal.emit(self.h.pedir(op, **args))
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'{op}: {type(e).__name__}: {e}')

    @pyqtSlot()
    def leer_osc(self):
        self._pedir_osc('osc.get', self.osc_info)

    @pyqtSlot(str, int)
    def escribir_campo_osc(self, campo, valor):
        self._pedir_osc('osc.set', self.osc_info, fields={campo: int(valor)})
        self.aviso.emit(f'osc.{campo} = {valor}')

    @pyqtSlot(str)
    def ctrl_osc(self, que):
        self._pedir_osc('osc.ctrl', self.osc_info, que=que)
        self.aviso.emit(f'osc: {que}')

    @pyqtSlot(int, int)
    def capturar_osc(self, pre, post):
        if self.h is None:
            return
        try:
            meta, datos = self.h.capturar_osc(pre=pre, post=post)
            self.traza.emit(meta, datos)
        except OSError as e:
            self._caido(e)
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'osc.capture: {type(e).__name__}: {e}')

    @pyqtSlot()
    def leer_mtrg(self):
        self._pedir_osc('mtrg.get', self.mtrg_info)

    @pyqtSlot(str, int)
    def escribir_campo_mtrg(self, campo, valor):
        self._pedir_osc('mtrg.set', self.mtrg_info, fields={campo: int(valor)})
        self.aviso.emit(f'mtrg.{campo} = {valor}')

    @pyqtSlot(int, int)
    def set_mascara(self, canal, mascara):
        self._pedir_osc('mtrg.set', self.mtrg_info,
                        fields={f'or_mask_ch{int(canal)}': int(mascara)})
        self.aviso.emit(f'mask ch{canal} = {mascara:#010x}')

    @pyqtSlot(dict)
    def disparo(self, args):
        """El disparo del MCA2: arma, desarma o (armar=None) sólo informa."""
        if self.h is None:
            return
        try:
            self.disparo_info.emit(self.h.pedir('mca.disparo', **args))
            if args.get('armar') is not None:
                self.aviso.emit('MCA trigger armed' if args['armar']
                                else 'MCA trigger disarmed')
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'mca.disparo: {type(e).__name__}: {e}')

    @pyqtSlot(dict)
    def armar_mtrg(self, args):
        """El disparo de nivel del scope: {'armar': True, 'thr', 'hyst'} (en volts)
        o {'armar': False}."""
        args = dict(args)
        armar = args.pop('armar', True)
        if armar:
            self._pedir_osc('mtrg.arm', self.mtrg_info, **args)
        else:
            self._pedir_osc('mtrg.disarm', self.mtrg_info)
        self.aviso.emit('level trigger armed' if armar else 'level trigger disarmed')

    # ---------- el generador de pulsos ----------

    @pyqtSlot()
    def leer_gen(self):
        self._pedir_osc('gen.get', self.gen_info)

    @pyqtSlot(dict)
    def configurar_gen(self, cfg):
        self._pedir_osc('gen.configurar', self.gen_info, cfg=cfg)
        self.aviso.emit(f"generator configured: {cfg.get('tasa', 0):.6g} /s, "
                        f"{len(cfg.get('lineas') or ())} amplitude(s)")

    @pyqtSlot(str)
    def ctrl_gen(self, que):
        self._pedir_osc('gen.ctrl', self.gen_info, que=que)
        self.aviso.emit(f'generator: {que}')

    @pyqtSlot(bool)
    def lazo_gen(self, on):
        self._pedir_osc('gen.lazo', self.gen_info, on=bool(on))
        self.aviso.emit('digital loopback ON: the input is the generator' if on
                        else 'digital loopback off: the input is the ADC')

    # ---------- el event_ring ----------
    #
    # Las ops ring.* tienen su propio lock en el servidor: parar una adquisición
    # (unir los hilos de la sesión) no frena el status del MCA.

    def _pedir_ring(self, op, **args):
        if self.h is None:
            return None
        try:
            return self.h.pedir(op, **args)
        except OSError as e:
            self._caido(e)
        except Exception as e:                                   # noqa: BLE001
            mensaje = f'{op}: {type(e).__name__}: {e}'
            self.fallo.emit(mensaje)
            self.ring_fallo.emit(mensaje)
        return None

    @pyqtSlot()
    def leer_ring(self):
        e = self._pedir_ring('ring.estado')
        if e is not None:
            self.ring_info.emit(e)

    @pyqtSlot(dict)
    def iniciar_ring(self, kw):
        info = self._pedir_ring('ring.iniciar', **kw)
        if info is not None:
            self.aviso.emit(f"ring: run in {info.get('run_dir')} "
                            f"({info.get('fs')}), {info.get('n_slots')} slots")
            self.leer_ring()

    @pyqtSlot()
    def parar_ring(self):
        fin = self._pedir_ring('ring.parar')
        if fin is not None:
            st = fin.get('stats') or {}
            self.aviso.emit(f"ring: stopped, {st.get('n_read', 0)} read, "
                            f"{st.get('n_written', 0)} written to {fin.get('run_dir')}")
            self.ring_info.emit(fin)

    @pyqtSlot(float)
    def set_refresco(self, segundos):
        if hasattr(self, '_t_espectro'):
            self._t_espectro.setInterval(max(100, int(segundos * 1000)))

    @pyqtSlot(bool)
    def set_mapa_visible(self, visible):
        # Leer el mapa 2D cuesta ~55 ms en la placa: sólo se lee si se ve.
        self._mapa_visible = visible

    @pyqtSlot(str)
    def cargar_bitstream(self, ruta):
        if self.h is None:
            return
        try:
            self.aviso.emit(f'loading {ruta} — the PL is unreachable for a few seconds')
            info = self.h.load_bitstream(ruta or None)
            self.conectado.emit(info)
            self._leer_config()
            self.aviso.emit('bitstream loaded')
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'load_bitstream: {type(e).__name__}: {e}')


# =============================================================================
# Ventana
# =============================================================================

class Mcamon(QMainWindow):

    sig_conectar = pyqtSignal(str, int)
    sig_desconectar = pyqtSignal()
    sig_start = pyqtSignal(float, bool)
    sig_parar = pyqtSignal()
    sig_borrar = pyqtSignal()
    sig_campo = pyqtSignal(str, int)
    sig_refresco = pyqtSignal(float)
    sig_mapa_visible = pyqtSignal(bool)
    sig_bitstream = pyqtSignal(str)
    sig_pedir_integracion = pyqtSignal()
    sig_ruteo = pyqtSignal(str, int, bool)
    sig_reset_ruteos = pyqtSignal()
    sig_ctrl_integracion = pyqtSignal(str)
    sig_pedir_osc = pyqtSignal()
    sig_campo_osc = pyqtSignal(str, int)
    sig_ctrl_osc = pyqtSignal(str)
    sig_capturar = pyqtSignal(int, int)
    sig_pedir_mtrg = pyqtSignal()
    sig_campo_mtrg = pyqtSignal(str, int)
    sig_mascara = pyqtSignal(int, int)
    sig_armar = pyqtSignal(dict)
    sig_disparo = pyqtSignal(dict)
    sig_pedir_gen = pyqtSignal()
    sig_gen_configurar = pyqtSignal(dict)
    sig_gen_ctrl = pyqtSignal(str)
    sig_gen_lazo = pyqtSignal(bool)
    sig_ring_estado = pyqtSignal()
    sig_ring_iniciar = pyqtSignal(dict)
    sig_ring_parar = pyqtSignal()

    def __init__(self, host='10.73.28.27', port=PORT_DEFAULT):
        super().__init__()
        self.setWindowTitle('mcamon — MCA Red Pitaya')
        self.resize(1240, 860)
        self.info = {}

        self._construir(host, port)
        self._arrancar_hilo()

    # ---------- construcción ----------

    def _construir(self, host, port):
        central = QWidget()
        v = QVBoxLayout(central)
        v.addLayout(self._barra_superior(host, port))

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.South)
        # El aviso del lazo, en la esquina de las pestañas: se ve desde cualquiera y
        # no ensancha la barra de arriba, que ya está justa a 1240 px.
        self.tabs.setCornerWidget(self.lbl_lazo, Qt.BottomRightCorner)
        self.panel_log = PanelLog()
        self.panel_espectro = PanelEspectro()
        self.panel_config = PanelConfigMCA()
        self.panel_mapa = None
        # La de Integración se crea al conectarse, si el bitstream trae el
        # slot 6: mismo criterio que la del mapa 2D. Las del osciloscopio («Pulses»
        # y «OSC settings») y la del Multitrigger, igual, según `has_osc` /
        # `has_mtrg`; el ring va dentro de «OSC settings», según `has_ring`.
        self.panel_integracion = None
        self.panel_pulsos = None
        self.panel_config_osc = None
        self.panel_ring = None          # el embebido en panel_config_osc, o None
        self.panel_mtrg = None
        self.panel_gen = None           # según `has_pulsos`
        self.tabs.addTab(self.panel_log, 'Messages')
        self.tabs.addTab(self.panel_espectro, 'Spectrum')
        self.tabs.addTab(self.panel_config, 'MCA settings')
        self.tabs.setCurrentWidget(self.panel_espectro)
        self.tabs.currentChanged.connect(self._cambio_pestana)
        v.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.panel_espectro.pedir_start.connect(self.sig_start)
        self.panel_espectro.pedir_stop.connect(self.sig_parar)
        self.panel_espectro.pedir_clear.connect(self.sig_borrar)
        self.panel_espectro.pedir_campo.connect(self.sig_campo)
        # El atajo de Spectrum arma con lo que diga la pestaña del Multitrigger.
        self.panel_espectro.pedir_disparo.connect(self._disparo_desde_espectro)
        self.panel_espectro.ir_a.connect(self._ir_a_pestana)
        self.panel_espectro.pedir_refresco.connect(self.sig_refresco)
        self._ultimo_disparo = None     # el último estado del disparo del MCA
        self._ultima_cfg = None         # la última configuración del MCA
        self.panel_espectro.log.connect(self.panel_log.info)

        self.panel_config.pedir_campo.connect(self.sig_campo)
        self.panel_config.pedir_clear.connect(self.sig_borrar)
        self.panel_config.log.connect(self.panel_log.info)

        # El modo continuo del osciloscopio. Sólo dispara con la pestaña «Pulses»
        # VISIBLE y la casilla marcada: una captura son hasta 16384 muestras por
        # canal y no se pagan de fondo, igual que el mapa 2D.
        self._t_traza = QTimer(self, interval=500)
        self._t_traza.timeout.connect(self._tic_traza)
        # El estado del OSC y del ring, con «OSC settings» visible: son unas
        # lecturas de registros y los contadores de la sesión, no los datos.
        self._t_config_osc = QTimer(self, interval=500)
        self._t_config_osc.timeout.connect(self._tic_config_osc)
        # El estado del multitrigger (snapshot, flags, shield), con su pestaña
        # visible: cuatro registros.
        self._t_mtrg = QTimer(self, interval=500)
        self._t_mtrg.timeout.connect(self.sig_pedir_mtrg.emit)

        acc = QAction('Load MCA bitstream…', self)
        acc.triggered.connect(self._cargar_bitstream)
        self.menuBar().addMenu('&Board').addAction(acc)
        self.accion_bitstream = acc

    def _barra_superior(self, host, port):
        self.btn_conectar = QPushButton('Connect')
        self.btn_conectar.clicked.connect(self._alternar_conexion)
        self.ed_host = QLineEdit(host)
        self.ed_host.setFixedWidth(140)
        self.ed_host.returnPressed.connect(self._alternar_conexion)
        self.spn_port = QSpinBox(minimum=1, maximum=65535)
        self.spn_port.setValue(port)

        # El canal, el estimador y la decimación del MCA están en «MCA settings»
        # (Input, Histogram axis), y el refresco del espectro, en «Spectrum»: acá
        # sólo la conexión y el estado.

        # Se corta en vez de ensanchar la ventana: entero, el texto la llevaba a
        # más de 1240 px. Entero, en el tooltip.
        self.lbl_estado = EtiquetaRecortada('not connected')
        # Con el lazo digital el MCA mide el generador y no la entrada. Tiene que
        # verse desde cualquier pestaña: un espectro tomado así sin darse cuenta
        # parece una medición.
        self.lbl_lazo = QLabel('DIGITAL LOOPBACK')
        self.lbl_lazo.setToolTip('The MCA input is the pulse generator, not the ADC.')
        self.lbl_lazo.setStyleSheet('color: white; background: #c0392b; '
                                    'font-weight: bold; padding: 2px 6px;')
        self.lbl_lazo.setVisible(False)

        h = QHBoxLayout()
        for w in (self.btn_conectar, self.ed_host, QLabel(':'), self.spn_port):
            h.addWidget(w)
        h.addSpacing(16)
        h.addWidget(self.lbl_estado, 1)
        return h

    def _arrancar_hilo(self):
        self.hilo = QThread(self)
        self.trabajador = Trabajador()
        self.trabajador.moveToThread(self.hilo)
        self.hilo.started.connect(self.trabajador.arrancar)
        # El trabajador se destruye en SU hilo: sus temporizadores son hijos
        # suyos y Qt no deja pararlos desde otro hilo.
        self.hilo.finished.connect(self.trabajador.deleteLater)

        self.sig_conectar.connect(self.trabajador.conectar)
        self.sig_desconectar.connect(self.trabajador.desconectar)
        self.sig_start.connect(self.trabajador.start)
        self.sig_parar.connect(self.trabajador.parar)
        self.sig_borrar.connect(self.trabajador.borrar)
        self.sig_campo.connect(self.trabajador.escribir_campo)
        self.sig_refresco.connect(self.trabajador.set_refresco)
        self.sig_mapa_visible.connect(self.trabajador.set_mapa_visible)
        self.sig_bitstream.connect(self.trabajador.cargar_bitstream)
        self.sig_pedir_integracion.connect(self.trabajador.leer_integracion)
        self.sig_ruteo.connect(self.trabajador.set_ruteo)
        self.sig_reset_ruteos.connect(self.trabajador.reset_ruteos)
        self.sig_ctrl_integracion.connect(self.trabajador.ctrl_integracion)
        self.sig_pedir_osc.connect(self.trabajador.leer_osc)
        self.sig_campo_osc.connect(self.trabajador.escribir_campo_osc)
        self.sig_ctrl_osc.connect(self.trabajador.ctrl_osc)
        self.sig_capturar.connect(self.trabajador.capturar_osc)
        self.sig_pedir_mtrg.connect(self.trabajador.leer_mtrg)
        self.sig_campo_mtrg.connect(self.trabajador.escribir_campo_mtrg)
        self.sig_mascara.connect(self.trabajador.set_mascara)
        self.sig_armar.connect(self.trabajador.armar_mtrg)
        self.sig_disparo.connect(self.trabajador.disparo)
        self.sig_pedir_gen.connect(self.trabajador.leer_gen)
        self.sig_gen_configurar.connect(self.trabajador.configurar_gen)
        self.sig_gen_ctrl.connect(self.trabajador.ctrl_gen)
        self.sig_gen_lazo.connect(self.trabajador.lazo_gen)
        self.trabajador.gen_info.connect(self._al_gen)
        self.sig_ring_estado.connect(self.trabajador.leer_ring)
        self.sig_ring_iniciar.connect(self.trabajador.iniciar_ring)
        self.sig_ring_parar.connect(self.trabajador.parar_ring)
        self.trabajador.ring_info.connect(self._al_ring)
        self.trabajador.ring_fallo.connect(self._al_ring_fallo)
        self.trabajador.disparo_info.connect(self._al_disparo)

        self.trabajador.integracion.connect(self._al_integracion)
        self.trabajador.osc_info.connect(self._al_osc)
        self.trabajador.mtrg_info.connect(self._al_mtrg)
        self.trabajador.traza.connect(self._al_traza)
        self.trabajador.conectado.connect(self._al_conectar)
        self.trabajador.desconectado.connect(self._al_desconectar)
        self.trabajador.estado.connect(self._al_estado)
        self.trabajador.espectro.connect(self.panel_espectro.actualizar_espectro)
        self.trabajador.config.connect(self._al_config)
        self.trabajador.mapa2d.connect(self._al_mapa)
        self.trabajador.aviso.connect(self.panel_log.info)
        self.trabajador.fallo.connect(self._al_fallo)

        self.hilo.start()

    # ---------- reacciones ----------

    def _alternar_conexion(self):
        if self.btn_conectar.text() == 'Connect':
            self.panel_log.info(f'connecting to {self.ed_host.text()}…')
            self.sig_conectar.emit(self.ed_host.text().strip(),
                                   self.spn_port.value())
        else:
            self.sig_desconectar.emit()

    def _al_conectar(self, info):
        self.info = info
        self.btn_conectar.setText('Disconnect')
        if not info.get('presente'):
            self.lbl_estado.setText('connected — NO MCA')
            self.panel_espectro.set_conectado(False)
            self.panel_log.error('the loaded bitstream has no MCA: ' +
                                 str(info.get('error')))
            QMessageBox.warning(
                self, 'No MCA',
                'The server answered but cannot find the MCA:\n\n'
                f"{info.get('error')}\n\n"
                'In the scope bitstream slot 7 is a stub. Use '
                'Board → Load MCA bitstream.')
            return

        n = info['n_channels']
        self.lbl_estado.setText(
            f"MCA2 · {n} channels · {info.get('n_acc_max', '?')} slots · "
            + (f"bank of {info['n_formas_max']} shapes · "
               if info.get('n_formas_max') else '')
            + ('pole-zero trigger · ' if info.get('has_pz') else '')
            + ('simulated' if info.get('fake') else 'board'))
        self.panel_espectro.configurar_geometria(n)
        self.panel_espectro.set_conectado(True, running=info.get('running', False))
        self.panel_config.configurar_geometria(n, info.get('h_aw'))
        self.panel_config.configurar_mca(info)
        self.panel_config.set_conectado(True)
        if not info.get('has_disparo'):
            self.panel_log.error('the multitrigger region is missing: without its '
                                 'trigger the MCA opens no windows')
        self.panel_log.info(
            f"connected: {n} channels, 2D map {'yes' if info.get('has_2d') else 'no'}, "
            f"PL {info.get('fpga_state')}")
        self._sincronizar_pestana_mapa(bool(info.get('has_2d')),
                                       tuple(info.get('map2d_shape') or (0, 0)))
        self._sincronizar_pestana_integracion(bool(info.get('has_integracion')))
        self._sincronizar_pestanas_osc(bool(info.get('has_osc')),
                                       bool(info.get('has_mtrg')),
                                       bool(info.get('has_ring')),
                                       bool(info.get('has_gen')))
        self._sincronizar_pestana_generador(bool(info.get('has_pulsos')))
        if info.get('ring_corriendo'):
            self.panel_log.info('a ring acquisition is running on the board')
        for nota in info.get('bases_notas') or ():
            self.panel_log.info(f'bases: {nota}')

    def _al_desconectar(self, _motivo):
        self.btn_conectar.setText('Connect')
        self.lbl_estado.setText('not connected')
        self.panel_espectro.set_conectado(False)
        self.panel_config.set_conectado(False)
        for panel in (self.panel_integracion, self.panel_pulsos,
                      self.panel_config_osc, self.panel_mtrg, self.panel_gen):
            if panel is not None:
                panel.set_conectado(False)
        self.lbl_lazo.setVisible(False)
        self._t_config_osc.stop()
        self._t_mtrg.stop()
        self.panel_log.info('disconnected')

    def _al_estado(self, est):
        self.panel_espectro.actualizar_estado(est)
        # Lo que el MCA ve del disparo (tasa, veto, re-armado), en la franja del
        # multitrigger.
        if self.panel_mtrg is not None:
            self.panel_mtrg.actualizar_estado(est)
        # La franja del datapath: tasas, pérdidas y si se borró el histograma.
        self.panel_config.actualizar_estado(est)
        # La curva de tasa de «Pulses» se alimenta del `status` del MCA, que ya
        # llega cada 200 ms: no cuesta ninguna lectura extra.
        if self.panel_pulsos is not None:
            self.panel_pulsos.actualizar_estado(est)
        # El generador también viaja en el status: el aviso del lazo y el estado
        # de su pestaña no cuestan otra vuelta.
        gen = est.get('gen') or {}
        self.lbl_lazo.setVisible(bool(gen.get('lazo')))
        if self.panel_gen is not None and gen:
            self.panel_gen.actualizar_estado(gen)
        # Con el lazo, la franja del generador compara la λ̂ del MCA con su tasa.
        if self.panel_gen is not None:
            self.panel_gen.actualizar_mca(est)

    def _al_config(self, cfg):
        self._ultima_cfg = cfg
        self.panel_espectro.actualizar_config(cfg)
        self.panel_config.actualizar_config(cfg)
        if self.panel_mtrg is not None:
            self.panel_mtrg.actualizar_mca_config(cfg)

    def _al_mapa(self, mapa):
        if self.panel_mapa is not None:
            self.panel_mapa.actualizar_mapa(mapa)

    def _al_fallo(self, mensaje):
        self.panel_log.error(mensaje)

    # ---------- pestaña 2D, según lo que publique el hardware ----------

    def _sincronizar_pestana_mapa(self, hay_2d, forma):
        """La pestaña existe si y sólo si el bitstream trae el motor 2D.

        `CAPS` lo publica el propio `mca_top`, así que recargar un bitstream
        sin PSD la hace desaparecer sin que el usuario tenga que saber nada.
        """
        if hay_2d and self.panel_mapa is None:
            self.panel_mapa = PanelMapa2D(forma)
            self.panel_mapa.log.connect(self.panel_log.info)
            self.tabs.addTab(self.panel_mapa, '2D map (PSD)')
        elif hay_2d:
            self.panel_mapa.configurar_geometria(forma)
        elif self.panel_mapa is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_mapa))
            self.panel_mapa.deleteLater()
            self.panel_mapa = None
        self._cambio_pestana()

    def _sincronizar_pestana_integracion(self, hay_integracion):
        """Igual que la del mapa 2D: existe si el bitstream trae el slot 6.

        Cualquier bitstream anterior al refactor de registros no lo trae, y el
        MCA anda igual — lo único que se pierde es el ruteo y el
        descubrimiento. Que la pestaña no aparezca es la forma honesta de
        decirlo, en vez de mostrar controles que no escriben en ningún lado.
        """
        if hay_integracion and self.panel_integracion is None:
            self.panel_integracion = PanelIntegracion()
            self.panel_integracion.log.connect(self.panel_log.info)
            self.panel_integracion.pedir_ruteo.connect(self.sig_ruteo)
            self.panel_integracion.pedir_reset_ruteos.connect(self.sig_reset_ruteos)
            self.panel_integracion.pedir_ctrl.connect(self.sig_ctrl_integracion)
            self.tabs.addTab(self.panel_integracion, 'Integration')
            self.panel_integracion.set_conectado(True)
            self.sig_pedir_integracion.emit()
        elif hay_integracion:
            self.panel_integracion.set_conectado(True)
            self.sig_pedir_integracion.emit()
        elif self.panel_integracion is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_integracion))
            self.panel_integracion.deleteLater()
            self.panel_integracion = None
        self._cambio_pestana()

    def _al_integracion(self, info):
        if self.panel_integracion is not None:
            self.panel_integracion.actualizar(info)

    # ---------- pestañas del osciloscopio (con el ring) y del Multitrigger ----------

    def _sincronizar_pestanas_osc(self, hay_osc, hay_mtrg, hay_ring=False,
                                  hay_gen=False):
        """Existen si el bitstream trae el bloque, igual que las otras.

        Del osciloscopio son dos: «Pulses», la vista de las capturas, y
        «OSC settings», sus registros por etapa y, con el bitstream del ring, el
        ring como la fila del camino a DDR. El Multitrigger es otra pestaña para el
        mismo slot físico a propósito: el osciloscopio clásico y el multitrigger son
        dos APIs sobre la misma región, y juntarlas escondería eso.
        """
        if hay_osc and self.panel_pulsos is None:
            self.panel_pulsos = PanelPulsos()
            self.panel_pulsos.log.connect(self.panel_log.info)
            self.panel_pulsos.pedir_captura.connect(self.sig_capturar)
            self.tabs.addTab(self.panel_pulsos, 'Pulses')
        elif not hay_osc and self.panel_pulsos is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_pulsos))
            self.panel_pulsos.deleteLater()
            self.panel_pulsos = None
        if self.panel_pulsos is not None:
            self.panel_pulsos.set_conectado(True)

        hay_cfg = hay_osc or hay_ring
        if hay_cfg and self.panel_config_osc is None:
            self.panel_config_osc = PanelConfigOsc()
            self.panel_config_osc.log.connect(self.panel_log.info)
            self.panel_config_osc.pedir_campo.connect(self.sig_campo_osc)
            self.panel_config_osc.ir_a.connect(self._ir_a_pestana)
            self.panel_config_osc.pedir_ctrl.connect(self.sig_ctrl_osc)
            self.tabs.addTab(self.panel_config_osc, 'OSC settings')
        elif not hay_cfg and self.panel_config_osc is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_config_osc))
            self.panel_config_osc.deleteLater()
            self.panel_config_osc = None
        ring = None
        if self.panel_config_osc is not None:
            self.panel_config_osc.configurar(hay_osc, hay_ring, hay_gen)
            self.panel_config_osc.set_conectado(True)
            ring = self.panel_config_osc.ring
        if ring is not None and ring is not self.panel_ring:
            ring.log.connect(self.panel_log.info)
            ring.pedir_iniciar.connect(self.sig_ring_iniciar)
            ring.pedir_parar.connect(self.sig_ring_parar)
            ring.pedir_estado.connect(self.sig_ring_estado)
        self.panel_ring = ring
        if hay_osc:
            self.sig_pedir_osc.emit()
        if ring is not None:
            self.sig_ring_estado.emit()

        if hay_mtrg and self.panel_mtrg is None:
            self.panel_mtrg = PanelMultitrigger()
            self.panel_mtrg.log.connect(self.panel_log.info)
            self.panel_mtrg.pedir_campo.connect(self.sig_campo_mtrg)
            self.panel_mtrg.pedir_mascara.connect(self.sig_mascara)
            self.panel_mtrg.pedir_armar.connect(self.sig_armar)
            self.panel_mtrg.pedir_refresco.connect(self.sig_pedir_mtrg)
            self.panel_mtrg.pedir_disparo.connect(self.sig_disparo)
            self.panel_mtrg.pedir_campo_osc.connect(self.sig_campo_osc)
            if self._ultima_cfg is not None:
                self.panel_mtrg.actualizar_mca_config(self._ultima_cfg)
            if self._ultimo_disparo is not None:
                self.panel_mtrg.actualizar_disparo(self._ultimo_disparo)
            self.tabs.addTab(self.panel_mtrg, 'Multitrigger')
        elif not hay_mtrg and self.panel_mtrg is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_mtrg))
            self.panel_mtrg.deleteLater()
            self.panel_mtrg = None
        if self.panel_mtrg is not None:
            self.panel_mtrg.configurar(hay_ring=hay_ring)
            self.panel_mtrg.set_conectado(True)
            self.sig_pedir_mtrg.emit()
        self._cambio_pestana()

    def _ir_a_pestana(self, destino):
        """«OSC settings» y «Spectrum» muestran el disparo y llevan al Multitrigger,
        que es donde se configura: a sus fuentes."""
        if destino == 'mtrg' and self.panel_mtrg is not None:
            self.tabs.setCurrentWidget(self.panel_mtrg)
            self.panel_mtrg._ir_a_etapa('fuentes')

    def _disparo_desde_espectro(self, args):
        """El atajo de Spectrum: armar usa la fuente y los parámetros de la pestaña
        del Multitrigger (sin ella, los del servidor)."""
        if args.get('armar') and self.panel_mtrg is not None:
            args = dict(self.panel_mtrg.args_disparo(), **args)
        self.sig_disparo.emit(args)

    def _al_disparo(self, est):
        self._ultimo_disparo = est
        self.panel_espectro.actualizar_disparo(est)
        if self.panel_mtrg is not None:
            self.panel_mtrg.actualizar_disparo(est)
            # Armar o desarmar cambia la máscara, el shield y la fuente.
            self.sig_pedir_mtrg.emit()

    # ---------- pestaña del generador de pulsos ----------

    def _sincronizar_pestana_generador(self, hay):
        """Existe si el bitstream trae `gen_pulsos`, como las otras."""
        if hay and self.panel_gen is None:
            self.panel_gen = PanelGenerador()
            self.panel_gen.log.connect(self.panel_log.info)
            self.panel_gen.pedir_configurar.connect(self.sig_gen_configurar)
            self.panel_gen.pedir_ctrl.connect(self.sig_gen_ctrl)
            self.panel_gen.pedir_lazo.connect(self.sig_gen_lazo)
            self.panel_gen.pedir_refresco.connect(self.sig_pedir_gen)
            self.panel_gen.pedir_campo_mca.connect(self.sig_campo)
            self.tabs.addTab(self.panel_gen, 'Generator')
        elif not hay and self.panel_gen is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_gen))
            self.panel_gen.deleteLater()
            self.panel_gen = None
        if self.panel_gen is not None:
            self.panel_gen.set_conectado(True)
            self.sig_pedir_gen.emit()

    # ---------- el event_ring, dentro de «OSC settings» ----------

    def _al_ring(self, e):
        if self.panel_config_osc is not None:
            self.panel_config_osc.actualizar_ring(e)

    def _al_ring_fallo(self, mensaje):
        if self.panel_config_osc is not None:
            self.panel_config_osc.mostrar_fallo_ring(mensaje)

    def _al_gen(self, info):
        self.lbl_lazo.setVisible(bool(info.get('lazo')))
        if self.panel_gen is not None:
            self.panel_gen.actualizar_gen(info)

    def _al_osc(self, info):
        if self.panel_pulsos is not None:
            self.panel_pulsos.actualizar_osc(info)
        if self.panel_config_osc is not None:
            self.panel_config_osc.actualizar_osc(info)
        if self.panel_mtrg is not None:
            self.panel_mtrg.actualizar_osc(info)

    def _al_mtrg(self, info):
        if self.panel_mtrg is not None:
            self.panel_mtrg.actualizar_mtrg(info)
        if self.panel_config_osc is not None:
            self.panel_config_osc.actualizar_mtrg(info)

    def _al_traza(self, meta, datos):
        if self.panel_pulsos is not None:
            self.panel_pulsos.actualizar_traza(meta, datos)

    def _tic_traza(self):
        """Pide una captura si el modo continuo está activo y la pestaña se ve."""
        p = self.panel_pulsos
        if p is None or not self.info.get('has_osc'):
            return
        if self.tabs.currentWidget() is not p:
            return
        # El mapa de calor junta trazas y pide más seguido que el pulso.
        if self._t_traza.interval() != p.intervalo_continuo_ms():
            self._t_traza.setInterval(p.intervalo_continuo_ms())
        if p.quiere_continuo():
            p.pedir_una()
            # El `osc.get` va en el mismo tic: es de donde sale la tasa de
            # disparos del OSC (Δwe_cnt/Δt), que sin refresco no tiene serie.
            self.sig_pedir_osc.emit()

    def _tic_config_osc(self):
        """Con «OSC settings» visible: el estado del OSC, el del ring y qué fuentes
        disparan (las máscaras del multitrigger)."""
        if self.info.get('has_osc'):
            self.sig_pedir_osc.emit()
        if self.panel_mtrg is not None:
            self.sig_pedir_mtrg.emit()
        if self.panel_ring is not None:
            self.sig_ring_estado.emit()

    def _cambio_pestana(self, *_):
        visible = (self.panel_mapa is not None and
                   self.tabs.currentWidget() is self.panel_mapa)
        self.sig_mapa_visible.emit(visible)
        pulsos_visible = (self.panel_pulsos is not None and
                          self.tabs.currentWidget() is self.panel_pulsos)
        if pulsos_visible and not self._t_traza.isActive():
            self._t_traza.start()
        elif not pulsos_visible and self._t_traza.isActive():
            self._t_traza.stop()
        cfg_visible = (self.panel_config_osc is not None and
                       self.tabs.currentWidget() is self.panel_config_osc)
        if cfg_visible and not self._t_config_osc.isActive():
            self._tic_config_osc()
            self._t_config_osc.start()
        elif not cfg_visible and self._t_config_osc.isActive():
            self._t_config_osc.stop()
        mtrg_visible = (self.panel_mtrg is not None and
                        self.tabs.currentWidget() is self.panel_mtrg)
        if mtrg_visible and not self._t_mtrg.isActive():
            self.sig_pedir_mtrg.emit()
            self._t_mtrg.start()
        elif not mtrg_visible and self._t_mtrg.isActive():
            self._t_mtrg.stop()

    # ---------- bitstream ----------

    def _cargar_bitstream(self):
        if not self.info:
            QMessageBox.information(self, 'Bitstream',
                                    'connect to the server first')
            return
        ruta, ok = QInputDialog.getText(
            self, 'Load bitstream',
            'Path of the .bit.bin ON THE PITAYA:',
            text=self.info.get('bitstream', '/root/mca_red_pitaya.bit.bin'))
        if not ok or not ruta.strip():
            return
        r = QMessageBox.question(
            self, 'Load bitstream',
            f'The PL is going to be reprogrammed with:\n\n{ruta}\n\n'
            'The server closes its mappings first. Any other process with '
            '/dev/mem open (a Jupyter kernel, for instance) can leave the GP0 '
            'port stuck until the board is rebooted.\n\n'
            'Continue?')
        if r == QMessageBox.Yes:
            self.sig_bitstream.emit(ruta.strip())

    # ---------- cierre ----------

    def closeEvent(self, ev):
        # Bloqueante a propósito: hay que parar los temporizadores y cerrar el
        # socket DENTRO del hilo del trabajador antes de terminar su lazo.
        if self.hilo.isRunning():
            QMetaObject.invokeMethod(self.trabajador, 'desconectar',
                                     Qt.BlockingQueuedConnection)
        self.hilo.quit()
        self.hilo.wait(3000)
        super().closeEvent(ev)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--host', default='10.73.28.27')
    p.add_argument('--port', type=int, default=PORT_DEFAULT)
    p.add_argument('--conectar', action='store_true',
                   help='connect at startup, without pressing the button')
    a = p.parse_args()

    app = QApplication(sys.argv)
    v = Mcamon(a.host, a.port)
    v.show()
    if a.conectar:
        QTimer.singleShot(0, v._alternar_conexion)
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
