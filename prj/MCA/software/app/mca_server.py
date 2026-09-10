#!/usr/bin/env python3
"""Servidor del MCA: expone API/mca.py por TCP. Corre EN LA PITAYA.

    python3 app/mca_server.py --port 1001
    python3 app/mca_server.py --fake        # sin placa, para desarrollar la GUI
    python3 app/mca_server.py --selftest    # identify + 1 s + espectro, y sale

Es el único proceso que puede tocar /dev/mem: si el kernel de Jupyter está vivo
y hace `rp_Init()`, los dos pelean y sale SIGBUS. Por eso acepta **un cliente a
la vez** y todo pasa por un lock.

La adquisición NO se detiene cuando el cliente se va: una medida de media hora
sobrevive a cerrar la GUI, y al reconectar `identify` informa `running=True`.

El MCA es free-running — no hay registro de tiempo de exposición en el
hardware — así que la exposición la implementa el hilo `_vigilante`, que poléa
`livetime_s` y para al llegar al objetivo.
"""

import argparse
import os
import socket
import sys
import threading
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))          # .../software

from API.mca import (CAP_HIST_H_PSD, MCA_PHYS, MCANotPresent,
                     mca_clear, mca_close, mca_configure, mca_get_config,
                     mca_get_baseline_now, mca_get_metadata, mca_open,
                     mca_read_counters, mca_read_last_event, mca_read_map2d,
                     mca_read_histogram, mca_start, mca_stop)
from API.mca_net import PORT_DEFAULT, PROTOCOL_VERSION, Channel, ProtocolError
from API.mca_remote import FakeMCA

BITSTREAM_MCA = '/root/mca_red_pitaya.bit.bin'
PERIODO_VIGILANTE_S = 0.1


def log(*a):
    print(f'[{time.strftime("%H:%M:%S")}]', *a, flush=True)


# =============================================================================
# Servidor
# =============================================================================

class ServidorMCA:

    def __init__(self, fake=False, bitstream=BITSTREAM_MCA, fake_h_aw=14):
        self.fake = fake
        self.fake_h_aw = fake_h_aw
        self.bitstream = bitstream
        self.h = None
        self.ig = None                  # slot 6: opcional, puede no estar
        self.motivo_ausente = None      # por qué no hay handle, para el cliente

        self._lock = threading.Lock()   # protege TODO acceso al handle
        self._lock_cliente = threading.Lock()
        self._cliente = None            # (ip, testigo) del cliente en curso
        self._exp_objetivo = None       # segundos de livetime, o None
        self._exp_hecha = False
        self._ultimo = None             # (livetime_s, accepted) para la tasa

        self._parar = threading.Event()
        self.abrir()
        threading.Thread(target=self._vigilante, daemon=True,
                         name='mca-exposicion').start()

    # ---------- ciclo de vida del handle ----------

    def abrir(self):
        """Abre el MCA. Si no se puede, deja el motivo para que el cliente lo
        muestre y pueda pedir la carga del bitstream."""
        if self.fake:
            self.h = FakeMCA(h_aw=self.fake_h_aw)
            self.motivo_ausente = None
            log(f'MCA simulado (--fake), {1 << self.fake_h_aw} canales')
            return
        try:
            # Sondear ANTES de mapear: si la PL no está programada, la primera
            # lectura mata el proceso con SIGBUS y sin traceback. pl_probe lo
            # hace en un hijo, así que el que muere es el hijo.
            from API.fpga import fpga_state, pl_probe
            estado = fpga_state()
            if estado != 'operating':
                raise MCANotPresent(f'la PL no está programada (fpga0/state = {estado!r})')
            ok, detalle = pl_probe(MCA_PHYS, 0)
            if not ok:
                raise MCANotPresent(f'el bus no contesta en {MCA_PHYS:#x}: {detalle}')
            self.h = mca_open()
            self.motivo_ausente = None
            info = self.h.identify(verbose=False)
            log(f"MCA abierto: {info['n_channels']} canales, "
                f"mapa 2D {'si' if info['hist_h_psd'] else 'no'}")
        except Exception as e:
            self.h = None
            self.motivo_ausente = f'{type(e).__name__}: {e}'
            log('sin MCA:', self.motivo_ausente)
        self._abrir_integracion()

    def _abrir_integracion(self):
        """El slot 6, si está. Que falte NO es un error.

        Cualquier bitstream anterior al refactor de registros no lo trae, y el
        MCA anda igual: lo único que se pierde es el ruteo y el descubrimiento.
        Por eso esto no toca `motivo_ausente` ni deja el servidor sin handle.
        """
        if self.fake:
            self.ig = None              # el MCA falso no simula el slot 6
            return
        try:
            from API.integration import integration_open
            self.ig = integration_open()
            log('integración (slot 6) abierta')
        except Exception as e:                                  # noqa: BLE001
            self.ig = None
            log(f'sin integración (slot 6): {type(e).__name__}: {e}')

    def cerrar(self):
        self._parar.set()
        with self._lock:
            if self.h is not None:
                mca_close(self.h)
                self.h = None
            if self.ig is not None:
                try:
                    self.ig.close()
                finally:
                    self.ig = None

    def _handle(self):
        if self.h is None:
            raise MCANotPresent(self.motivo_ausente or 'no hay MCA abierto')
        return self.h

    # ---------- hilo de exposición ----------

    def _vigilante(self):
        """El tiempo de exposición no existe en hardware: se implementa acá.

        Poléa `livetime_s` (dos lecturas de registro, ~5 us) y para el MCA al
        llegar al objetivo. Se mide contra el tiempo VIVO, no el de pared, que
        es lo que hace comparables dos medidas con tasas distintas.
        """
        while not self._parar.wait(PERIODO_VIGILANTE_S):
            with self._lock:
                if self._exp_objetivo is None or self.h is None:
                    continue
                try:
                    if not self.h.running:
                        continue
                    if self.h.counters()['livetime_s'] >= self._exp_objetivo:
                        mca_stop(self.h)
                        self._exp_objetivo = None
                        self._exp_hecha = True
                        log('exposición completa')
                except Exception as e:                       # noqa: BLE001
                    log('vigilante:', e)
                    self._exp_objetivo = None

    # ---------- operaciones ----------

    def op_identify(self):
        if self.h is None:
            return {'presente': False, 'error': self.motivo_ausente,
                    'caps': 0, 'h_aw': 0, 'h2_aw': 0, 'psd_aw': 0,
                    'n_channels': 0, 'map2d_shape': [0, 0],
                    'protocol': PROTOCOL_VERSION, 'fake': self.fake,
                    'fpga_state': self._fpga_state()}
        info = self.h.identify(verbose=False)
        info.update({'presente': True, 'caps': self.h.caps,
                     'map2d_shape': list(info['map2d_shape']),
                     'has_2d': bool(self.h.caps & CAP_HIST_H_PSD),
                     'running': self.h.running,
                     'protocol': PROTOCOL_VERSION, 'fake': self.fake,
                     'fpga_state': self._fpga_state(),
                     # Igual que `has_2d`: el cliente arma la interfaz con lo
                     # que el bitstream traiga, en vez de suponerlo. Sin el
                     # slot 6 no hay pestaña de Integración.
                     'has_integracion': self.ig is not None,
                     'bitstream': self.bitstream})
        return info

    def op_r32(self, off):
        return {'val': self._handle().r32(int(off))}

    def op_w32(self, off, val):
        self._handle().w32(int(off), int(val))
        return {}

    def op_config_get(self):
        return mca_get_config(self._handle())

    def op_config_set(self, fields):
        h = self._handle()
        mca_configure(h, **(fields or {}))
        return mca_get_config(h)

    def op_ctrl_start(self, seconds=None, clear_first=False):
        h = self._handle()
        if clear_first:
            mca_stop(h)
            mca_clear(h)
        self._exp_objetivo = None
        self._exp_hecha = False
        self._ultimo = None
        mca_start(h)
        if seconds:
            # El objetivo se mide sobre el livetime ACUMULADO, así que si no se
            # borró primero, una segunda exposición continúa donde iba.
            self._exp_objetivo = h.counters()['livetime_s'] + float(seconds)
        return {'running': True, 'exposure_target_s': self._exp_objetivo}

    def op_ctrl_stop(self):
        mca_stop(self._handle())
        self._exp_objetivo = None
        return {'running': False}

    def op_ctrl_clear(self, timeout_s=1.0):
        h = self._handle()
        mca_clear(h, timeout_s=float(timeout_s))
        self._ultimo = None
        self._exp_hecha = False
        return {}

    def op_status(self):
        h = self._handle()
        cnt = mca_read_counters(h)
        lt, acc = cnt['livetime_s'], cnt['accepted']

        # Tasa instantánea entre dos status consecutivos; la media, sobre todo
        # el tiempo vivo. Igual que los dos números de la referencia.
        inst = 0.0
        if self._ultimo is not None:
            dlt, dacc = lt - self._ultimo[0], acc - self._ultimo[1]
            if dlt > 1e-3:
                inst = dacc / dlt
        self._ultimo = (lt, acc)

        objetivo = self._exp_objetivo
        return {
            'presente': True,
            'running': h.running,
            'counters': cnt,
            'baseline_now': mca_get_baseline_now(h),
            'rate_inst_hz': inst,
            'rate_avg_hz': acc / lt if lt > 1e-6 else 0.0,
            'exposure': {'target_s': objetivo,
                         'left_s': max(0.0, objetivo - lt) if objetivo else None,
                         'done': self._exp_hecha},
        }

    def op_read_spectrum(self):
        return {}, mca_read_histogram(self._handle())

    def op_read_map2d(self):
        return {}, mca_read_map2d(self._handle())

    def op_read_metadata(self):
        return mca_get_metadata(self._handle())

    def op_read_last_event(self):
        return mca_read_last_event(self._handle())

    def op_fpga_state(self):
        return {'state': self._fpga_state()}

    def op_fpga_load_bitstream(self, path=None):
        """Recarga la PL. Es la operación más delicada del sistema.

        Reprogramar con mapeos abiertos da el `external abort ... *pte=...` de
        dmesg y puede dejar el puerto GP0 trabado hasta reiniciar la placa, así
        que se cierra el handle ANTES.
        """
        if self.fake:
            raise RuntimeError('no hay PL que cargar en modo --fake')
        if self.h is not None and self.h.running:
            raise RuntimeError('hay una adquisición corriendo: pararla primero')

        from API.fpga import load_bitstream
        if self.h is not None:
            mca_close(self.h)
            self.h = None
        ruta = path or self.bitstream
        log('cargando bitstream', ruta)
        load_bitstream(ruta, bridges=True, wait_bus_s=8.0)
        self.bitstream = ruta
        self.abrir()
        if self.h is None:
            raise MCANotPresent(self.motivo_ausente)
        return self.op_identify()

    def _fpga_state(self):
        if self.fake:
            return 'fake'
        try:
            from API.fpga import fpga_state
            return fpga_state()
        except Exception as e:                                # noqa: BLE001
            return f'?: {e}'

    # ---------- integración (slot 6) ----------

    def _ig(self):
        if self.ig is None:
            raise RuntimeError(
                'este bitstream no trae la región de TOP en el slot 6: no hay '
                'ruteo ni descubrimiento (el MCA anda igual)')
        return self.ig

    def op_integracion_get(self):
        """Todo el estado del slot 6 de una: la pestaña se dibuja con esto.

        Va en UNA operación y no en cinco porque el cliente las quiere todas
        juntas para pintar la pestaña, y cinco viajes por refresco sobre un
        socket que además comparte con el espectro no compra nada.
        """
        ig = self._ig()
        info = {'modules': ig.modules(), 'slots': ig.slots(),
                'caps': ig.caps(), 'routes': ig.routes(),
                'status': ig.status(), 'run': ig.get_run()}
        # La geometría que publica esta región es una SEGUNDA copia de la del
        # MCA y puede estar desactualizada. Se informa si coincide para que el
        # cliente pueda mostrarlo, en vez de que la discrepancia quede latente.
        if self.h is not None:
            ok, motivo = ig.geometria_coincide(self.h)
            info['geometria_coincide'] = ok
            info['geometria_motivo'] = motivo
        return info

    def op_integracion_set_route(self, consumidor, tap, enable):
        self._ig().set_route(str(consumidor), int(tap), bool(enable))
        return self.op_integracion_get()

    def op_integracion_reset_routes(self):
        self._ig().reset_routes()
        return self.op_integracion_get()

    def op_integracion_ctrl(self, que):
        ig = self._ig()
        acciones = {'run_on':  lambda: ig.set_run(True),
                    'run_off': lambda: ig.set_run(False),
                    'clear':   ig.clear,
                    'srst':    ig.soft_reset}
        if que not in acciones:
            raise ValueError(f'control desconocido: {que!r}; '
                             f'hay: {sorted(acciones)}')
        acciones[que]()
        return self.op_integracion_get()

    # ---------- despacho ----------

    _OPS = {
        'identify':           ('op_identify', ()),
        'r32':                ('op_r32', ('off',)),
        'w32':                ('op_w32', ('off', 'val')),
        'config.get':         ('op_config_get', ()),
        'config.set':         ('op_config_set', ('fields',)),
        'ctrl.start':         ('op_ctrl_start', ('seconds', 'clear_first')),
        'ctrl.stop':          ('op_ctrl_stop', ()),
        'ctrl.clear':         ('op_ctrl_clear', ('timeout_s',)),
        'status':             ('op_status', ()),
        'read.spectrum':      ('op_read_spectrum', ()),
        'read.map2d':         ('op_read_map2d', ()),
        'read.metadata':      ('op_read_metadata', ()),
        'read.last_event':    ('op_read_last_event', ()),
        'fpga.state':         ('op_fpga_state', ()),
        'fpga.load_bitstream': ('op_fpga_load_bitstream', ('path',)),
        'integracion.get':          ('op_integracion_get', ()),
        'integracion.set_route':    ('op_integracion_set_route',
                                     ('consumidor', 'tap', 'enable')),
        'integracion.reset_routes': ('op_integracion_reset_routes', ()),
        'integracion.ctrl':         ('op_integracion_ctrl', ('que',)),
    }

    def despachar(self, op, args):
        if op not in self._OPS:
            raise ValueError(f'operación desconocida: {op!r}')
        nombre, permitidos = self._OPS[op]
        sobran = set(args) - set(permitidos)
        if sobran:
            raise ValueError(f'{op}: argumentos no reconocidos {sorted(sobran)}')
        with self._lock:
            r = getattr(self, nombre)(**args)
        return r if isinstance(r, tuple) else (r, None)

    # ---------- red ----------

    def servir(self, host='0.0.0.0', port=PORT_DEFAULT):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((host, port))
        except PermissionError:
            # El 1001 por defecto es el de mcpha y en la Pitaya funciona porque
            # ahí se corre como root. En una PC de usuario, no: Linux reserva
            # todo lo que está por debajo de 1024.
            srv.close()
            raise SystemExit(
                f'no se puede escuchar en el puerto {port}: por debajo de 1024 '
                f'hace falta root.\n'
                f'  en la Pitaya  -> ya corrés como root, deberia andar\n'
                f'  en la PC      -> elegí un puerto libre, p. ej. '
                f'--port 5001 (y lo mismo en mcamon.py)')
        except OSError as e:
            srv.close()
            raise SystemExit(f'no se puede escuchar en {host}:{port} — {e}')
        srv.listen(4)
        log(f'escuchando en {host}:{port}'
            f"{' (simulado)' if self.fake else ''}")
        try:
            while True:
                conn, addr = srv.accept()
                # TCP_NODELAY: las cabeceras son de ~100 B y Nagle las retendría
                # esperando compañía, que con un poll cada 200 ms se nota.
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                canal = Channel(conn)
                # El testigo distingue ESTA conexión de la siguiente: sin él,
                # el `finally` de un cliente que se va justo cuando entra otro
                # borra al recién llegado y deja entrar a un tercero.
                testigo = object()
                with self._lock_cliente:
                    ocupado = self._cliente
                    if ocupado is None:
                        self._cliente = (addr[0], testigo)
                if ocupado is not None:
                    log(f'rechazado {addr[0]}: ya hay un cliente')
                    canal.send({'ok': False, 'error': 'Ocupado',
                                'msg': f'ya hay un cliente ({ocupado[0]})',
                                'hint': 'un solo proceso puede tocar /dev/mem'})
                    canal.close()
                    continue
                threading.Thread(target=self._atender,
                                 args=(canal, addr, testigo),
                                 daemon=True, name='mca-cliente').start()
        except KeyboardInterrupt:
            log('cerrando')
        finally:
            srv.close()
            self.cerrar()

    def _atender(self, canal, addr, testigo):
        log('conectado', addr[0])
        try:
            while True:
                try:
                    obj, _ = canal.recv()
                except ProtocolError as e:
                    if 'cerró' not in str(e):
                        log('protocolo:', e)
                    break
                try:
                    result, array = self.despachar(obj.get('op'),
                                                   obj.get('args') or {})
                    canal.send_result(result, array)
                except MCANotPresent as e:
                    canal.send_error(e, hint='cargá mca_red_pitaya.bit.bin')
                except Exception as e:                        # noqa: BLE001
                    log(f'{obj.get("op")}: {type(e).__name__}: {e}')
                    canal.send_error(e)
        except OSError as e:
            log('socket:', e)
        finally:
            canal.close()
            with self._lock_cliente:
                if self._cliente is not None and self._cliente[1] is testigo:
                    self._cliente = None
            log('desconectado', addr[0],
                '(la adquisición sigue)' if self.h is not None
                and self.h.running else '')


# =============================================================================
# Autoprueba
# =============================================================================

def selftest(srv):
    """identify + clear + 1 s + espectro completo, con /proc/uptime a los lados.

    Es la misma guarda que usa API/tests/placa/diag_mca_hw.py: si la placa se reinicia
    durante la lectura, el uptime del final es menor que el del principio.
    """
    def uptime():
        try:
            with open('/proc/uptime') as f:
                return float(f.read().split()[0])
        except OSError:
            return float('nan')

    t0 = uptime()
    log('uptime antes', t0)
    log('identify', srv.despachar('identify', {})[0])
    srv.despachar('ctrl.clear', {})
    srv.despachar('ctrl.start', {'seconds': 1.0})
    time.sleep(1.4)
    est = srv.despachar('status', {})[0]
    log('running', est['running'], 'counters', est['counters'])
    hist = srv.despachar('read.spectrum', {})[1]
    log(f'espectro {hist.size} canales, {int(hist.sum())} cuentas, '
        f'pico en {int(hist.argmax())}')
    t1 = uptime()
    log('uptime después', t1)
    if t1 < t0:
        log('*** LA PLACA SE REINICIÓ durante la prueba ***')
        return 1
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=PORT_DEFAULT)
    p.add_argument('--fake', action='store_true',
                   help='MCA simulado, para desarrollar sin placa')
    p.add_argument('--bitstream', default=BITSTREAM_MCA)
    p.add_argument('--selftest', action='store_true')
    # Sólo con --fake. Existe para poder ejercitar al cliente contra las dos
    # geometrías reales: 14 es el bitstream viejo (16384 canales) y 13 el nuevo
    # (8192). El cliente no debería notar la diferencia, y hasta que esto se
    # pudo variar, no había forma de comprobarlo sin la placa.
    p.add_argument('--fake-h-aw', type=int, default=14, metavar='N',
                   help='canales del MCA simulado, como exponente (13 = 8192)')
    a = p.parse_args()

    srv = ServidorMCA(fake=a.fake, bitstream=a.bitstream, fake_h_aw=a.fake_h_aw)
    if a.selftest:
        try:
            return selftest(srv)
        finally:
            srv.cerrar()
    srv.servir(a.host, a.port)
    return 0


if __name__ == '__main__':
    sys.exit(main())
