#!/usr/bin/env python3
"""Las ops de la pestaña «Calibration» contra `mca_server.py --fake`, por `MCARemote`:
`canal.medir`, `mca.ganancia`, `base.dinamica` y `base.verificar`.

El servidor falso mide con `API/canal_falso.py` (los registros de los fakes y la BRAM
sintetizada con un canal de juguete de caída conocida), y su MCA cuenta `cross`, así que
la base dinámica tiene una λ̂ de verdad: con el lazo digital, la del generador.

    python -m pytest app/tests/test_calibracion.py -q
"""

import os
import sys
import time

import numpy as np
import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)

import API.generadores as G                                          # noqa: E402
from API import base_dinamica as BD                                  # noqa: E402
from API.canal_falso import CanalFalso                               # noqa: E402
from API.mca_net import RemoteError                                  # noqa: E402
from test_mca_remote import ServidorDePrueba                         # noqa: E402

CAIDA_FALSA = CanalFalso().caida


@pytest.fixture(scope='module')
def srv():
    with ServidorDePrueba(h_aw=13, rsz=13) as s:
        yield s


def conectar(srv, plazo_s=5.0):
    t_fin = time.monotonic() + plazo_s
    while True:
        try:
            return srv.conectar()
        except Exception:                                    # noqa: BLE001
            if time.monotonic() > t_fin:
                raise
            time.sleep(0.1)


@pytest.fixture
def h(srv):
    h = conectar(srv)
    yield h
    try:
        h.pedir('base.dinamica', on=False)
        h.pedir('ctrl.stop')
        h.pedir('gen.ctrl', que='parar')
        h.pedir('gen.lazo', on=False)
    finally:
        h.close()


def test_medir_el_canal(h):
    res, caps = h.medir_canal('generador', 'todo', promedios=2)
    assert res['problema'] is None
    assert res['fuente_caida'] == 'lenta'
    assert res['caida_lenta_usar'] == pytest.approx(CAIDA_FALSA, rel=0.08)
    assert res['ganancia'] == pytest.approx(0.95, rel=0.02)
    assert 'generador' in res['restaurado']
    n = res['n_buf']
    assert caps['x'].shape == (n,) and caps['lento_y'].shape == (2, n)
    assert caps['x'].dtype == np.int16


def test_la_externa(h):
    res, caps = h.medir_canal('externa', promedios=2)
    assert res['referencia'] == 'externa'
    assert res['caida_lenta_usar'] == pytest.approx(CAIDA_FALSA, rel=0.08)
    assert caps['externa_y'].shape[0] == 2


def test_no_mide_con_el_mca_corriendo(h):
    h.pedir('ctrl.start')
    try:
        with pytest.raises(RemoteError, match='corriendo'):
            h.medir_canal('generador', 'rapido')
    finally:
        h.pedir('ctrl.stop')


def test_medir_restaura_el_generador(h):
    h.pedir('gen.configurar', cfg={'tasa': 33e3, 'tau_us': 1.5, 'lineas': [[1500, 1.0]]})
    h.pedir('gen.lazo', on=True)
    antes = h.pedir('gen.get')
    h.medir_canal('generador', 'rapido')
    despues = h.pedir('gen.get')
    assert despues['config'] == antes['config']
    assert despues['lineas'] == antes['lineas']
    assert despues['lazo'] is True


def test_la_ganancia_del_mca(h):
    r = h.pedir('mca.ganancia', amplitud=2000, segundos=0.5)
    assert r['ganancia_mca'] > 0 and r['n'] >= 100
    assert r['feature'] == pytest.approx(2000 * r['ganancia_mca'])
    assert 'trap_mq' in r['huella'] and 'baseline' not in r['huella']
    # La base y el seguidor quedaron como estaban.
    cfg = h.pedir('config.get')
    assert cfg['bl_auto'] is False or cfg['bl_auto'] == 0


def _esperar_pasos(h, n, plazo_s=5.0):
    t_fin = time.monotonic() + plazo_s
    while time.monotonic() < t_fin:
        b = h.pedir('status')['base_dinamica']
        if b.get('pasos', 0) >= n and b.get('a_adu') is not None:
            return b
        time.sleep(0.1)
    raise AssertionError(f'la base dinámica no dio {n} pasos: {b}')


def test_la_base_dinamica_sigue_la_ley(h):
    """Con el lazo digital a 400 k/s, el MCA falso cuenta esa tasa: la base escrita es
    b0 + κ·caída·(λ̂/f_s)·⟨A⟩·τ con lo que el status dice."""
    # τ = 250 muestras en el polo-cero (el falso arranca en trap_mq = 0: τ = 1/2).
    h.pedir('config.set', fields={'baseline': -12, 'bl_auto': 0, 'trap_mq': 3992})
    gf = h.pedir('mca.ganancia', amplitud=2000, segundos=0.3)['ganancia_mca']
    h.pedir('gen.configurar', cfg={'tasa': 400e3, 'tau_us': 2.0, 'lineas': [[2000, 1.0]]})
    h.pedir('gen.lazo', on=True)
    r = h.pedir('base.dinamica', on=True, caida=CAIDA_FALSA, ganancia_mca=gf, kappa=1.0)
    assert r['on'] and r['b0'] == -12 and r['base'] == -12
    h.pedir('ctrl.start', clear_first=True)
    h.pedir('gen.ctrl', que='arrancar')
    b = _esperar_pasos(h, 6)
    st = h.pedir('status')
    b = st['base_dinamica']
    tau = BD.tau_de_mq(h.pedir('config.get')['trap_mq'])
    esperado = CAIDA_FALSA * (b['lam_hz'] / 125e6) * b['a_adu'] * tau
    assert b['lam_hz'] == pytest.approx(400e3, rel=0.15)
    assert b['delta_b'] == pytest.approx(esperado, rel=1e-6)
    assert tau == pytest.approx(250.0)
    assert b['delta_b'] < -10
    assert st['baseline_now'] == b['base'] == round(-12 + b['delta_b'])
    # Escribir la base fija con la dinámica prendida cambia b0.
    h.pedir('config.set', fields={'baseline': -20})
    assert h.pedir('status')['base_dinamica']['b0'] == -20
    # Apagarla devuelve la base a b0.
    h.pedir('gen.ctrl', que='parar')
    h.pedir('ctrl.stop')
    r = h.pedir('base.dinamica', on=False)
    assert r['on'] is False
    assert h.pedir('status')['baseline_now'] == -20


def test_la_dinamica_no_va_con_el_seguidor(h):
    h.pedir('config.set', fields={'bl_auto': 1})
    try:
        with pytest.raises(RemoteError, match='seguidor'):
            h.pedir('base.dinamica', on=True, caida=-0.07, ganancia_mca=4.0)
    finally:
        h.pedir('config.set', fields={'bl_auto': 0})


def test_prender_el_seguidor_apaga_la_dinamica(h):
    h.pedir('config.set', fields={'bl_auto': 0})
    h.pedir('base.dinamica', on=True, caida=-0.07, ganancia_mca=4.0)
    h.pedir('config.set', fields={'bl_auto': 1})
    assert h.pedir('status')['base_dinamica']['on'] is False
    h.pedir('config.set', fields={'bl_auto': 0})


def test_verificar(h):
    """El falso no corre su línea con la base (su espectro no sigue al canal): la
    verificación corre entera y dice que no hay corrimiento que medir."""
    h.pedir('config.set', fields={'bl_auto': 0})
    r = h.pedir('base.verificar', tasa_hz=200e3, lineas=[1300], segundos=0.5,
                caida=CAIDA_FALSA, ganancia_mca=4.0, kappa=1.0)
    assert len(r['referencia']) == 1
    # La línea falsa tiene σ = 45 canales y ~500 eventos por corrida: el centroide
    # se mueve un par de canales entre corridas sin que nada cambie.
    assert abs(r['s_fija']) < 10 and abs(r['s_dinamica']) < 10
    assert set(r['lam_hz']) == {'ref', 'fija', 'dinamica'}
    assert h.pedir('gen.get')['estado']['generando'] is False


def test_argumentos(h):
    with pytest.raises(RemoteError, match='referencia'):
        h.medir_canal('rigol')
    with pytest.raises(RemoteError, match='caida'):
        h.pedir('base.dinamica', on=True)
