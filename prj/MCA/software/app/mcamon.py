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
from PyQt5.QtWidgets import (QAction, QApplication, QComboBox, QDoubleSpinBox,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QMainWindow, QMessageBox, QPushButton, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)

import API.mca as A
from API.mca_net import PORT_DEFAULT
from API.mca_remote import MCARemote
from app.panel_config_mca import PanelConfigMCA
from app.panel_espectro import PanelEspectro
from app.panel_integracion import PanelIntegracion
from app.panel_log import PanelLog
from app.panel_mapa2d import PanelMapa2D
from app.panel_multitrigger import PanelMultitrigger
from app.panel_osc import PanelOsc

PERIODO_ESTADO_MS = 200
REFRESCO_ESPECTRO_S = 1.0


# =============================================================================
# Hilo del socket
# =============================================================================

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
            self.fallo.emit(f'no se pudo conectar a {host}:{port} — '
                            f'{type(e).__name__}: {e}')
            return
        info = self.h.info
        self.conectado.emit(info)
        if not info.get('presente'):
            self.aviso.emit('conectado, pero no hay MCA: ' +
                            str(info.get('error')))
            return
        self._leer_config()
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
            self.desconectado.emit('desconectado')

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
            self.fallo.emit(f'lectura: {type(e).__name__}: {e}')

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
            self.aviso.emit(f'medición iniciada'
                            + (f', {segundos:.3f} s de tiempo vivo'
                               if segundos else ', sin límite'))
            self._tic_estado()
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'start: {type(e).__name__}: {e}')

    @pyqtSlot()
    def parar(self):
        if self.h is None:
            return
        try:
            self.h.stop()
            self.aviso.emit('medición detenida')
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
            self.aviso.emit('cuentas, histogramas y relojes reiniciados')
            self._tic_estado()
            self._tic_espectro()
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'clear: {type(e).__name__}: {e}')

    @pyqtSlot(str, int)
    def escribir_campo(self, campo, valor):
        """Escribe UN campo con su `mca_set_<campo>` de API/mca.py.

        No se usa `mca_configure`: el bloque entero escribe R_CTRL con run=0, o
        sea que tocar un umbral pararía la medición en curso. Y se pasa por el
        setter público, no por `_escribir_campo`, porque tres de ellos validan
        (`bl_k`, `tail_dly`, `dec`).
        """
        if self.h is None:
            return
        try:
            getattr(A, f'mca_set_{campo}')(self.h, valor)
            self.aviso.emit(f'{campo} = {valor}')
            self._leer_config()
        except Exception as e:                                   # noqa: BLE001
            self.fallo.emit(f'{campo}: {type(e).__name__}: {e}')

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
        self.aviso.emit(f'ruteo {consumidor} -> tap {tap}')

    @pyqtSlot()
    def reset_ruteos(self):
        self._pedir_integracion('integracion.reset_routes')
        self.aviso.emit('ruteos de vuelta a nativo')

    @pyqtSlot(str)
    def ctrl_integracion(self, que):
        self._pedir_integracion('integracion.ctrl', que=que)
        self.aviso.emit(f'control global: {que}')

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
        self.aviso.emit(f'máscara ch{canal} = {mascara:#010x}')

    @pyqtSlot(bool)
    def armar_mtrg(self, armar):
        self._pedir_osc('mtrg.arm' if armar else 'mtrg.disarm', self.mtrg_info)
        self.aviso.emit('disparo armado' if armar else 'disparo desarmado')

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
            self.aviso.emit(f'cargando {ruta} — la PL queda inaccesible unos segundos')
            info = self.h.load_bitstream(ruta or None)
            self.conectado.emit(info)
            self._leer_config()
            self.aviso.emit('bitstream cargado')
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
    sig_armar = pyqtSignal(bool)

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
        self.panel_log = PanelLog()
        self.panel_espectro = PanelEspectro()
        self.panel_config = PanelConfigMCA()
        self.panel_mapa = None
        # La de Integración se crea al conectarse, si el bitstream trae el
        # slot 6: mismo criterio que la del mapa 2D. Las de OSC y Multitrigger,
        # igual, según `has_osc` / `has_mtrg`.
        self.panel_integracion = None
        self.panel_osc = None
        self.panel_mtrg = None
        self.tabs.addTab(self.panel_log, 'Mensajes')
        self.tabs.addTab(self.panel_espectro, 'Espectro')
        self.tabs.addTab(self.panel_config, 'MCA')
        self.tabs.setCurrentWidget(self.panel_espectro)
        self.tabs.currentChanged.connect(self._cambio_pestana)
        v.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.panel_espectro.pedir_start.connect(self.sig_start)
        self.panel_espectro.pedir_stop.connect(self.sig_parar)
        self.panel_espectro.pedir_clear.connect(self.sig_borrar)
        self.panel_espectro.pedir_campo.connect(self.sig_campo)
        self.panel_espectro.log.connect(self.panel_log.info)

        self.panel_config.pedir_campo.connect(self.sig_campo)
        self.panel_config.pedir_clear.connect(self.sig_borrar)
        self.panel_config.log.connect(self.panel_log.info)

        # El modo continuo del osciloscopio. Sólo dispara con la pestaña
        # VISIBLE y la casilla marcada: una captura son hasta 16384 muestras por
        # canal y no se pagan de fondo, igual que el mapa 2D.
        self._t_traza = QTimer(self, interval=500)
        self._t_traza.timeout.connect(self._tic_traza)

        acc = QAction('Cargar bitstream del MCA…', self)
        acc.triggered.connect(self._cargar_bitstream)
        self.menuBar().addMenu('&Placa').addAction(acc)
        self.accion_bitstream = acc

    def _barra_superior(self, host, port):
        self.btn_conectar = QPushButton('Conectar')
        self.btn_conectar.clicked.connect(self._alternar_conexion)
        self.ed_host = QLineEdit(host)
        self.ed_host.setFixedWidth(140)
        self.ed_host.returnPressed.connect(self._alternar_conexion)
        self.spn_port = QSpinBox(minimum=1, maximum=65535)
        self.spn_port.setValue(port)

        self.cmb_canal = QComboBox()
        self.cmb_canal.addItems(['IN1', 'IN2'])
        self.cmb_canal.currentIndexChanged.connect(
            lambda i: self._campo_si_conectado('channel', i))

        self.cmb_estimador = QComboBox()
        self.cmb_estimador.addItems(['pico', 'integral'])
        self.cmb_estimador.currentIndexChanged.connect(
            lambda i: self._campo_si_conectado('amp_src', i))

        self.spn_dec = QSpinBox(minimum=1, maximum=0xFFFF)
        self.spn_dec.setKeyboardTracking(False)
        self.spn_dec.valueChanged.connect(
            lambda v: self._campo_si_conectado('dec', v))

        self.spn_refresco = QDoubleSpinBox()
        self.spn_refresco.setDecimals(1)
        self.spn_refresco.setRange(0.2, 60.0)
        self.spn_refresco.setSingleStep(0.5)
        self.spn_refresco.setValue(REFRESCO_ESPECTRO_S)
        self.spn_refresco.setSuffix(' s')
        self.spn_refresco.valueChanged.connect(self.sig_refresco)

        self.lbl_estado = QLabel('sin conectar')

        h = QHBoxLayout()
        for w in (self.btn_conectar, self.ed_host, QLabel(':'), self.spn_port):
            h.addWidget(w)
        h.addSpacing(16)
        h.addWidget(QLabel('canal'))
        h.addWidget(self.cmb_canal)
        h.addWidget(QLabel('estimador'))
        h.addWidget(self.cmb_estimador)
        h.addWidget(QLabel('decimación'))
        h.addWidget(self.spn_dec)
        h.addWidget(QLabel('refresco'))
        h.addWidget(self.spn_refresco)
        h.addStretch(1)
        h.addWidget(self.lbl_estado)
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
        if self.btn_conectar.text() == 'Conectar':
            self.panel_log.info(f'conectando a {self.ed_host.text()}…')
            self.sig_conectar.emit(self.ed_host.text().strip(),
                                   self.spn_port.value())
        else:
            self.sig_desconectar.emit()

    def _al_conectar(self, info):
        self.info = info
        self.btn_conectar.setText('Desconectar')
        if not info.get('presente'):
            self.lbl_estado.setText('conectado — SIN MCA')
            self.panel_espectro.set_conectado(False)
            self.panel_log.error('no hay MCA en el bitstream cargado: ' +
                                 str(info.get('error')))
            QMessageBox.warning(
                self, 'Sin MCA',
                'El servidor respondió pero no encuentra el MCA:\n\n'
                f"{info.get('error')}\n\n"
                'En el bitstream del scope el slot 7 es un stub. Usá '
                'Placa → Cargar bitstream del MCA.')
            return

        n = info['n_channels']
        self.lbl_estado.setText(
            f"MCA1 · {n} canales · {'simulado' if info.get('fake') else 'placa'}")
        self.panel_espectro.configurar_geometria(n)
        self.panel_espectro.set_conectado(True, running=info.get('running', False))
        self.panel_config.configurar_geometria(n, info.get('h_aw'))
        self.panel_config.set_conectado(True)
        self.panel_log.info(
            f"conectado: {n} canales, mapa 2D {'sí' if info.get('has_2d') else 'no'}, "
            f"PL {info.get('fpga_state')}")
        self._sincronizar_pestana_mapa(bool(info.get('has_2d')),
                                       tuple(info.get('map2d_shape') or (0, 0)))
        self._sincronizar_pestana_integracion(bool(info.get('has_integracion')))
        self._sincronizar_pestanas_osc(bool(info.get('has_osc')),
                                       bool(info.get('has_mtrg')))
        for nota in info.get('bases_notas') or ():
            self.panel_log.info(f'bases: {nota}')

    def _al_desconectar(self, _motivo):
        self.btn_conectar.setText('Conectar')
        self.lbl_estado.setText('sin conectar')
        self.panel_espectro.set_conectado(False)
        self.panel_config.set_conectado(False)
        for panel in (self.panel_integracion, self.panel_osc, self.panel_mtrg):
            if panel is not None:
                panel.set_conectado(False)
        self.panel_log.info('desconectado')

    def _al_estado(self, est):
        self.panel_espectro.actualizar_estado(est)
        # La curva de tasa del OSC se alimenta del `status` del MCA, que ya
        # llega cada 200 ms: no cuesta ninguna lectura extra.
        if self.panel_osc is not None:
            self.panel_osc.actualizar_estado(est)

    def _al_config(self, cfg):
        self.panel_espectro.actualizar_config(cfg)
        self.panel_config.actualizar_config(cfg)
        for widget, clave in ((self.cmb_canal, 'channel'),
                              (self.cmb_estimador, 'amp_src')):
            widget.blockSignals(True)
            widget.setCurrentIndex(int(cfg.get(clave, 0)))
            widget.blockSignals(False)
        self.spn_dec.blockSignals(True)
        self.spn_dec.setValue(max(1, int(cfg.get('dec', 1))))
        self.spn_dec.blockSignals(False)

    def _al_mapa(self, mapa):
        if self.panel_mapa is not None:
            self.panel_mapa.actualizar_mapa(mapa)

    def _al_fallo(self, mensaje):
        self.panel_log.error(mensaje)

    def _campo_si_conectado(self, campo, valor):
        if self.info.get('presente'):
            self.sig_campo.emit(campo, int(valor))

    # ---------- pestaña 2D, según lo que publique el hardware ----------

    def _sincronizar_pestana_mapa(self, hay_2d, forma):
        """La pestaña existe si y sólo si el bitstream trae el motor 2D.

        `CAPS` lo publica el propio `mca_top`, así que recargar un bitstream
        sin PSD la hace desaparecer sin que el usuario tenga que saber nada.
        """
        if hay_2d and self.panel_mapa is None:
            self.panel_mapa = PanelMapa2D(forma)
            self.panel_mapa.log.connect(self.panel_log.info)
            self.tabs.addTab(self.panel_mapa, 'Mapa 2D (PSD)')
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
            self.tabs.addTab(self.panel_integracion, 'Integración')
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

    # ---------- pestañas de OSC y Multitrigger ----------

    def _sincronizar_pestanas_osc(self, hay_osc, hay_mtrg):
        """Las dos existen si el bitstream trae el bloque, igual que las otras.

        Son dos pestañas para un mismo slot físico a propósito: el osciloscopio
        clásico y el multitrigger son dos APIs sobre la misma región, y juntarlas
        escondería eso. Pueden aparecer por separado porque el servidor abre los
        handles por separado.
        """
        if hay_osc and self.panel_osc is None:
            self.panel_osc = PanelOsc()
            self.panel_osc.log.connect(self.panel_log.info)
            self.panel_osc.pedir_campo.connect(self.sig_campo_osc)
            self.panel_osc.pedir_ctrl.connect(self.sig_ctrl_osc)
            self.panel_osc.pedir_captura.connect(self.sig_capturar)
            self.tabs.addTab(self.panel_osc, 'OSC')
        elif not hay_osc and self.panel_osc is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_osc))
            self.panel_osc.deleteLater()
            self.panel_osc = None
        if self.panel_osc is not None:
            self.panel_osc.set_conectado(True)
            self.sig_pedir_osc.emit()

        if hay_mtrg and self.panel_mtrg is None:
            self.panel_mtrg = PanelMultitrigger()
            self.panel_mtrg.log.connect(self.panel_log.info)
            self.panel_mtrg.pedir_campo.connect(self.sig_campo_mtrg)
            self.panel_mtrg.pedir_mascara.connect(self.sig_mascara)
            self.panel_mtrg.pedir_armar.connect(self.sig_armar)
            self.panel_mtrg.pedir_refresco.connect(self.sig_pedir_mtrg)
            self.tabs.addTab(self.panel_mtrg, 'Multitrigger')
        elif not hay_mtrg and self.panel_mtrg is not None:
            self.tabs.removeTab(self.tabs.indexOf(self.panel_mtrg))
            self.panel_mtrg.deleteLater()
            self.panel_mtrg = None
        if self.panel_mtrg is not None:
            self.panel_mtrg.set_conectado(True)
            self.sig_pedir_mtrg.emit()
        self._cambio_pestana()

    def _al_osc(self, info):
        if self.panel_osc is not None:
            self.panel_osc.actualizar_osc(info)

    def _al_mtrg(self, info):
        if self.panel_mtrg is not None:
            self.panel_mtrg.actualizar_mtrg(info)

    def _al_traza(self, meta, datos):
        if self.panel_osc is not None:
            self.panel_osc.actualizar_traza(meta, datos)

    def _tic_traza(self):
        """Pide una captura si el modo continuo está activo y la pestaña se ve."""
        if self.panel_osc is None or not self.info.get('has_osc'):
            return
        if self.tabs.currentWidget() is not self.panel_osc:
            return
        if self.panel_osc.quiere_continuo():
            self.panel_osc.pedir_una()
            # El `osc.get` va en el mismo tic: es de donde sale la tasa de
            # disparos del OSC (Δwe_cnt/Δt), que sin refresco no tiene serie.
            self.sig_pedir_osc.emit()

    def _cambio_pestana(self, *_):
        visible = (self.panel_mapa is not None and
                   self.tabs.currentWidget() is self.panel_mapa)
        self.sig_mapa_visible.emit(visible)
        osc_visible = (self.panel_osc is not None and
                       self.tabs.currentWidget() is self.panel_osc)
        if osc_visible and not self._t_traza.isActive():
            self._t_traza.start()
        elif not osc_visible and self._t_traza.isActive():
            self._t_traza.stop()

    # ---------- bitstream ----------

    def _cargar_bitstream(self):
        if not self.info:
            QMessageBox.information(self, 'Bitstream',
                                    'primero hay que conectarse al servidor')
            return
        ruta, ok = QInputDialog.getText(
            self, 'Cargar bitstream',
            'Ruta del .bit.bin EN LA PITAYA:',
            text=self.info.get('bitstream', '/root/mca_red_pitaya.bit.bin'))
        if not ok or not ruta.strip():
            return
        r = QMessageBox.question(
            self, 'Cargar bitstream',
            f'Se va a reprogramar la PL con:\n\n{ruta}\n\n'
            'El servidor cierra sus mapeos antes de hacerlo. Cualquier otro '
            'proceso con /dev/mem abierto (un kernel de Jupyter, por ejemplo) '
            'puede dejar el puerto GP0 trabado hasta reiniciar la placa.\n\n'
            '¿Seguir?')
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
                   help='conectar al arrancar, sin apretar el botón')
    a = p.parse_args()

    app = QApplication(sys.argv)
    v = Mcamon(a.host, a.port)
    v.show()
    if a.conectar:
        QTimer.singleShot(0, v._alternar_conexion)
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
