#!/usr/bin/env python3
"""Las ops `ring.*` del servidor contra `mca_server.py --fake`, por `MCARemote`.

El servidor falso trae el ring simulado con el generador (`API/ring_falso.py`), así que
una adquisición entera corre de punta a punta: la sesión en el proceso del servidor,
los archivos en un directorio de esta máquina (que en la placa es el montaje de la PC)
y el control por el socket.

    python -m pytest app/tests/test_ring_red.py -q
"""

import os
import sys
import time

import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.join(_RAIZ, 'campanas'))

import API.generadores as G                                          # noqa: E402
import API.osciloscope_ring as OR                                    # noqa: E402
import run_etapas_ring as R                                          # noqa: E402
from API.mca_net import RemoteError                                  # noqa: E402
from API.osciloscope_store import archivos_de_corrida               # noqa: E402
from test_mca_remote import ServidorDePrueba                         # noqa: E402

CALIB = [R.IDENTIDAD] * OR.N_CH_HW


@pytest.fixture(scope='module')
def srv():
    with ServidorDePrueba() as s:
        yield s


def conectar(srv, plazo_s=5.0):
    """El servidor libera el cupo del cliente anterior un poco después de que éste
    cierra: se reintenta mientras diga Ocupado."""
    t_fin = time.monotonic() + plazo_s
    while True:
        try:
            return srv.conectar()
        except RemoteError as e:
            if e.error != 'Ocupado' or time.monotonic() > t_fin:
                raise
            time.sleep(0.05)


@pytest.fixture
def h(srv):
    h = conectar(srv)
    yield h
    try:
        if h.ring_estado()['corriendo']:
            h.ring_parar()
    finally:
        h.close()


def _kw(run_dir, n=2000, **kw):
    return dict(run_dir=str(run_dir), pre=8, post=24, generador=G.disparos(tasa=1e5, n=n),
                calib=CALIB, capacity=256) | kw


def _hasta_el_fin(h, plazo_s=30.0):
    t_fin, fin_visto = time.monotonic() + plazo_s, False
    while time.monotonic() < t_fin:
        time.sleep(0.02)
        e = h.ring_estado()
        assert e['corriendo'] and e['motivo'] is None, e
        if fin_visto and e['stats']['n_read'] >= e['hw']['hw_ev_cnt']:
            return e
        fin_visto = e['hw']['hw_gen_terminado']
    raise TimeoutError('la adquisición no terminó')


def test_identify_publica_el_ring(h):
    assert h.has_ring and h.has_gen
    assert h.info['ring_corriendo'] is False
    assert h.info['bases']['ring'] == OR.RING_PHYS


def test_una_adquisicion_por_la_red(h, tmp_path):
    info = h.ring_iniciar(**_kw(tmp_path / 'r1'))
    assert info['run_dir'] == str(tmp_path / 'r1') and info['n_slots'] > 0
    assert info['fs']                       # el tipo del sistema de archivos
    _hasta_el_fin(h)
    fin = h.ring_parar()
    hw, st = fin['hw_final'], fin['stats']
    assert fin['error'] is None
    assert hw['hw_gen_cnt'] == 2000 and hw['hw_gen_terminado']
    assert hw['hw_ev_cnt'] + hw['hw_drop_busy'] + hw['hw_drop_full'] == 2000
    assert st['n_read'] == st['n_written'] == hw['hw_ev_cnt']
    # lo que escribió el servidor se verifica de este lado, como en la campaña
    v = R.verificar_archivos(str(tmp_path / 'r1'), G.disparos(tasa=1e5, n=2000), 8, 24,
                             None)
    assert v['errores'] == 0 and v['eventos'] == hw['hw_ev_cnt']
    assert archivos_de_corrida(tmp_path / 'r1')
    # parada, el estado es el final; y parar otra vez da lo mismo
    e = h.ring_estado()
    assert e['corriendo'] is False and e['hw_final'] == hw
    assert h.ring_parar() == fin


def test_una_por_vez(h, tmp_path):
    h.ring_iniciar(**_kw(tmp_path / 'a', n=300_000))
    with pytest.raises(RemoteError, match='ya hay una adquisición del ring'):
        h.ring_iniciar(**_kw(tmp_path / 'b'))
    assert not (tmp_path / 'b').exists()
    h.ring_parar()


@pytest.mark.parametrize('run_dir, error', [
    ('relativo/r', 'absoluto'),
    ('/no/existe/el/montaje/r', 'el punto de montaje no'),
])
def test_el_run_dir_lo_valida_la_placa(h, run_dir, error):
    with pytest.raises(RemoteError, match=error):
        h.ring_iniciar(**_kw(run_dir))
    assert h.ring_estado()['corriendo'] is False


def test_un_argumento_que_no_existe(h, tmp_path):
    with pytest.raises(RemoteError, match='argumentos no reconocidos'):
        h.ring_iniciar(**_kw(tmp_path / 'r'), umbral=3)


def test_sigue_sin_el_cliente(srv, tmp_path):
    h = conectar(srv)
    h.ring_iniciar(**_kw(tmp_path / 'r', n=300_000))
    h.close()
    time.sleep(0.2)
    h = conectar(srv)                        # el cupo de un cliente quedó libre
    try:
        assert h.info['ring_corriendo'] is True
        e = h.ring_estado()
        assert e['corriendo'] and e['stats']['n_read'] > 0
        assert e['run_dir'] == str(tmp_path / 'r')
    finally:
        h.ring_parar()
        h.close()
    assert any('sigue la adquisición del ring' in l for l in srv.salida)


def test_load_bitstream_con_el_ring_corriendo(h, tmp_path):
    h.ring_iniciar(**_kw(tmp_path / 'r', n=300_000))
    with pytest.raises(RemoteError, match=r'ring\.parar'):
        h.load_bitstream()
    assert h.ring_estado()['corriendo']      # no la paró
    h.ring_parar()
    with pytest.raises(RemoteError, match='--fake'):
        h.load_bitstream()                   # parada, el que rechaza es el modo falso


def test_el_disparo_real_arma_y_desarma(h, tmp_path):
    h.ring_iniciar(run_dir=str(tmp_path / 'r'), disparo={'thr': 0.5, 'hyst': 0.02},
                   calib=CALIB)
    assert h._pedir('mtrg.get')[0]['result']['config']['shield_src'] == 3
    fin = h.ring_parar()
    assert fin['error'] is None
    assert h._pedir('mtrg.get')[0]['result']['config']['shield_src'] == 0


def test_parar_sin_ninguna(srv):
    with ServidorDePrueba() as otro:         # uno recién levantado: nunca hubo
        h = otro.conectar()
        try:
            assert h.ring_estado() == dict(corriendo=False, motivo=None, stats=None,
                                           hw=None, error=None)
            with pytest.raises(RemoteError, match='no hubo ninguna'):
                h.ring_parar()
        finally:
            h.close()
