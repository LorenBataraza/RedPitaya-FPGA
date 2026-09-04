#!/usr/bin/env python3
"""El handle remoto (`API/mca_remote.py`) contra el servidor en modo --fake.

Ésta es la prueba que sostiene el diseño: si la superficie `mca_*` ENTERA pasa
por socket sin que las funciones sepan que hay una red en el medio, entonces la
abstracción del handle es correcta y la GUI puede escribirse contra `API.mca` y
no contra un protocolo.

Levanta `app/mca_server.py --fake` en un puerto libre de loopback. No necesita
placa ni permisos.

    python tests/test_mca_remote.py
    python -m pytest tests/test_mca_remote.py -q
"""

import os
import socket
import threading
import subprocess
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_SOFTWARE = os.path.join(_AQUI, '..')
sys.path.insert(0, _SOFTWARE)

import API.mca as A                                                # noqa: E402
from API.mca_net import RemoteError                                # noqa: E402
from API.mca_remote import MCARemote                               # noqa: E402


# =============================================================================
# Servidor de prueba
# =============================================================================

def _puerto_libre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServidorDePrueba:
    """`mca_server.py --fake` en un subproceso.

    La espera al arranque se hace leyendo la línea "escuchando" de su stdout,
    NO abriendo un socket de sondeo: el servidor acepta un cliente a la vez, y
    el sondeo se gastaría el cupo justo antes de la prueba.
    """

    def __enter__(self):
        self.port = _puerto_libre()
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(_SOFTWARE, 'app', 'mca_server.py'),
             '--fake', '--host', '127.0.0.1', '--port', str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.salida = []
        self._listo = threading.Event()
        threading.Thread(target=self._drenar, daemon=True).start()
        if not self._listo.wait(10.0):
            raise TimeoutError('el servidor no llegó a escuchar:\n' +
                               ''.join(self.salida))
        return self

    def _drenar(self):
        # Hay que vaciar la tubería igual: si se llena, el servidor se bloquea
        # en el print de la conexión siguiente.
        for linea in self.proc.stdout:
            self.salida.append(linea)
            if 'escuchando' in linea:
                self._listo.set()
        self._listo.set()

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def conectar(self):
        return MCARemote.connect('127.0.0.1', self.port, timeout=10.0)


# =============================================================================
# Pruebas
# =============================================================================

def test_identify_trae_la_geometria_del_hardware():
    """El cliente no hardcodea 16384: lo deriva de WIDTHS, como en la placa."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        info = A.mca_identify(h, verbose=False)
        assert info['magic'] == A.MAGIC
        assert (h.h_aw, h.h2_aw, h.psd_aw) == (14, 7, 6)
        assert info['n_channels'] == 16384
        assert info['map2d_shape'] == (128, 64)
        assert h._has_2d is True
        h.close()


def test_accesores_por_campo_por_red():
    """Los mca_get_/mca_set_ de API/mca.py, sin tocarlos, sobre el proxy."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        for setter, getter, valor in (
                (A.mca_set_thr,        A.mca_get_thr,        317),
                (A.mca_set_hyst,       A.mca_get_hyst,        80),
                (A.mca_set_maxlen,     A.mca_get_maxlen,     512),
                (A.mca_set_tail_dly,   A.mca_get_tail_dly,     8),
                (A.mca_set_amp_min,    A.mca_get_amp_min,    100),
                (A.mca_set_amp_max,    A.mca_get_amp_max,  16300),
                (A.mca_set_q_shift,    A.mca_get_q_shift,      5),
                (A.mca_set_gate_long,  A.mca_get_gate_long,  400),
                (A.mca_set_channel,    A.mca_get_channel,      1),
        ):
            setter(h, valor)
            leido = getter(h)
            assert leido == valor, f'{getter.__name__}: puse {valor}, leí {leido}'
        h.close()


def test_read_modify_write_sobrevive_a_la_red():
    """`bl_k` y `bl_holdoff` comparten registro: el RMW son dos idas y vueltas
    y tiene que seguir siendo correcto."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_set_bl_holdoff(h, 0xBEEF)
        A.mca_set_bl_k(h, 13)
        A.mca_set_bl_auto(h, True)
        cfg = A.mca_get_config(h)
        assert (cfg['bl_holdoff'], cfg['bl_k'], cfg['bl_auto']) == (0xBEEF, 13, 1)

        A.mca_set_gate_short(h, 0x5678)
        A.mca_set_gate_long(h, 0x1234)
        cfg = A.mca_get_config(h)
        assert (cfg['gate_short'], cfg['gate_long']) == (0x5678, 0x1234)
        h.close()


def test_configure_en_bloque():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, thr=200, hyst=80, maxlen=1024, tail_dly=8,
                        amp_src=1, q_shift=6, h_shift=2, dec=1)
        cfg = A.mca_get_config(h)
        assert cfg['thr'] == 200 and cfg['amp_src'] == 1
        assert cfg['q_shift'] == 6 and cfg['h_shift'] == 2
        h.close()


def test_configure_valida_del_lado_de_la_placa():
    """tail_dly=0 lo rechaza `MCA.configure`, que corre en el servidor: el
    error tiene que volver con su tipo, no como un fallo de socket."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            A.mca_configure(h, tail_dly=0)
        except RemoteError as e:
            assert e.error == 'ValueError'
            assert 'tail_dly' in e.msg
        else:
            raise AssertionError('tail_dly=0 pasó')
        h.close()


def test_adquisicion_y_espectro():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, thr=100, hyst=50, maxlen=1024, tail_dly=8)
        A.mca_clear(h)
        A.mca_start(h)
        assert A.mca_get_running(h) is True
        time.sleep(0.6)
        A.mca_stop(h)
        assert A.mca_get_running(h) is False

        hist = A.mca_read_histogram(h)
        assert hist.dtype == np.uint32 and hist.size == 16384
        assert hist.sum() > 0

        cnt = A.mca_read_counters(h)
        assert cnt['accepted'] == int(hist.sum())
        assert cnt['total'] == cnt['accepted'] + cnt['rej_amp'] + cnt['pileup']
        assert cnt['livetime_s'] > 0
        assert abs(cnt['realtime_s'] - cnt['livetime_s'] - cnt['deadtime_s']) < 1e-6
        h.close()


def test_clear_borra_todo():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_start(h)
        time.sleep(0.3)
        A.mca_stop(h)
        assert A.mca_read_histogram(h).sum() > 0
        A.mca_clear(h)
        assert A.mca_read_histogram(h).sum() == 0
        assert A.mca_read_counters(h)['total'] == 0
        h.close()


def test_ventana_de_amplitud_recorta_el_pico():
    """El simulador respeta amp_min/amp_max, así que mover la ventana desde la
    GUI tiene que verse en el espectro y en rej_amp."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, amp_min=0, amp_max=0xFFFF, tail_dly=8)
        A.mca_clear(h)
        A.mca_start(h)
        time.sleep(0.4)
        A.mca_stop(h)
        assert A.mca_read_counters(h)['rej_amp'] == 0

        A.mca_set_amp_min(h, 12000)          # el pico está en ~8000
        A.mca_clear(h)
        A.mca_start(h)
        time.sleep(0.4)
        A.mca_stop(h)
        cnt = A.mca_read_counters(h)
        assert cnt['rej_amp'] > 0
        assert cnt['accepted'] == 0
        h.close()


def test_mapa_2d():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_clear(h)
        A.mca_start(h)
        time.sleep(0.4)
        A.mca_stop(h)
        m = A.mca_read_map2d(h)
        assert m.shape == (128, 64) and m.dtype == np.uint32
        assert m.sum() > 0
        h.close()


def test_metadata_completa_y_guardado():
    """La metadata que viaja por red tiene que servir para escribir el MISMO
    fichero que se escribe en la placa, y `mca_load_file` releerlo."""
    import tempfile
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_configure(h, thr=317, gate_long=400, tail_dly=8)
        A.mca_start(h)
        time.sleep(0.3)
        A.mca_stop(h)

        hist = A.mca_read_histogram(h)
        meta = A.mca_get_metadata(h)
        assert meta['thr'] == 317 and meta['n_channels'] == 16384
        assert meta['schema_version'] == A.SCHEMA_VERSION_MCA
        assert 'livetime_s' in meta and 'fs_hz' in meta

        with tempfile.TemporaryDirectory() as d:
            for nombre, guardar in (('e.csv',  A.mca_write_file_histogram),
                                    ('e.npz',  A.mca_save_file_binary),
                                    ('e.json', A.mca_save_file_json)):
                ruta = os.path.join(d, nombre)
                guardar(hist, ruta, meta=meta)
                h2, m2 = A.mca_load_file(ruta)
                assert np.array_equal(h2, hist), nombre
                assert m2['thr'] == 317, nombre
        h.close()


def test_acquire_heredado():
    """`MCA.acquire` no se redefine: se hereda y funciona sobre el proxy."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        spec, m2d, cnt = A.mca_read_acquire(h, seconds=0.4)
        assert spec.sum() > 0
        assert m2d is not None and m2d.shape == (128, 64)
        assert cnt['accepted'] > 0
        h.close()


def test_status_trae_tasas_y_exposicion():
    with ServidorDePrueba() as s:
        h = s.conectar()
        A.mca_clear(h)
        h._pedir('ctrl.start', seconds=0.5)
        time.sleep(0.25)
        est = h.status()
        assert est['running'] is True
        assert est['exposure']['target_s'] is not None
        assert est['exposure']['left_s'] > 0
        time.sleep(0.6)
        est = h.status()
        assert est['running'] is False
        assert est['exposure']['done'] is True
        assert est['rate_avg_hz'] > 0
        h.close()


def test_un_cliente_a_la_vez():
    """Dos procesos sobre /dev/mem es SIGBUS: el segundo cliente se rechaza."""
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            s.conectar()
        except RemoteError as e:
            assert e.error == 'Ocupado'
        else:
            raise AssertionError('el servidor aceptó un segundo cliente')
        h.close()


def test_operacion_desconocida():
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            h._pedir('borrar.todo')
        except RemoteError as e:
            assert e.error == 'ValueError' and 'desconocida' in e.msg
        else:
            raise AssertionError('el servidor aceptó una operación inventada')
        # y el canal sigue usable después del error
        assert A.mca_get_thr(h) >= 0
        h.close()


def test_load_bitstream_rechazado_en_fake():
    with ServidorDePrueba() as s:
        h = s.conectar()
        try:
            h.load_bitstream()
        except RemoteError as e:
            assert e.error == 'RuntimeError'
        else:
            raise AssertionError('--fake aceptó cargar un bitstream')
        h.close()


def main():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f'  ok    {fn.__name__}')
        except Exception as e:
            fallos += 1
            print(f'  FALLO {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\n{len(pruebas) - fallos}/{len(pruebas)} pruebas OK')
    return 1 if fallos else 0


if __name__ == '__main__':
    raise SystemExit(main())