"""`campanas/canal_analogico.py` sin placa: el ajuste del canal, el piso, la respuesta,
el residuo con el que la fidelidad analógica decide si una captura tiene un error, y el
canal de juguete.

Las capturas son sintéticas (un FIR, polos lentos y ruido conocidos), o las de
`run_fidelidad_osc.CapturaSimulada` con el canal de juguete: el análisis tiene que
devolver lo que se puso.
"""
import math
import os
import sys

import numpy as np
import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(_AQUI))                  # campanas/

import canal_analogico as CA                                         # noqa: E402


def _estimulo(n=20000, semilla=1):
    """Escalones y pulsos de los dos signos, sin llegar a los rieles: banda ancha."""
    rng = np.random.default_rng(semilla)
    x = np.zeros(n)
    for t in rng.choice(n - 50, 300, replace=False):
        x[t:] += rng.choice([-1, 1]) * rng.uniform(100, 600) * np.exp(-np.arange(n - t) / 250)
    return np.round(x + rng.normal(0, 20, n))


# -----------------------------------------------------------------------------
# El ajuste
# -----------------------------------------------------------------------------

def test_ajustar_fir_recupera_un_fir_conocido():
    x = _estimulo()
    c = np.zeros(48)
    c[4 + 5], c[4 + 6], c[4 + 7] = 0.3, 0.5, 0.15        # lags −4..43: retardo 5..7
    rng = np.random.default_rng(2)
    y = CA.predecir(x, c, -40.0) + rng.normal(0, 1.5, x.size)
    f = CA.ajustar_fir(x, y, lentos=())
    assert f['b'] == pytest.approx(-40.0, abs=0.3)
    assert np.abs(f['c'] - c).max() < 0.01
    assert f['rms'] == pytest.approx(1.5, rel=0.05)
    assert np.abs(f['c'][:4]).max() < 0.01                # los taps no causales, cero


def test_los_polos_lentos_explican_la_caida():
    x = _estimulo(40000)
    c = np.zeros(48)
    c[4 + 3] = 1.0
    y = CA.predecir(x, c, 0.0, d=[-0.05], lentos=[1600]) + \
        np.random.default_rng(3).normal(0, 1.0, x.size)
    con = CA.ajustar_fir(x, y)
    sin = CA.ajustar_fir(x, y, lentos=())
    assert sum(con['d']) == pytest.approx(-0.05, abs=0.005)
    assert con['rms'] == pytest.approx(1.0, rel=0.1)
    assert sin['rms'] > 2 * con['rms']                     # el FIR solo no alcanza
    # lo ajustado predice el canal que se puso (sin el ruido)
    p = CA.predecir(x, con['c'], con['b'], d=con['d'], lentos=con['lentos'])
    assert np.std(p - CA.predecir(x, c, 0.0, d=[-0.05], lentos=[1600])) < 0.3


def test_ajustar_fir_no_usa_las_muestras_recortadas():
    x = _estimulo()
    c = np.zeros(48)
    c[4 + 2] = 1.0
    y = CA.predecir(x, c, 0.0)
    y[5000:5100] = CA.AMP_MAX                             # el ADC recorta un tramo
    f = CA.ajustar_fir(x, y, lentos=())
    assert np.abs(f['c'] - c).max() < 1e-6 and f['rms'] < 1e-6
    assert not np.isin(np.arange(5000, 5100), f['n']).any()
    with pytest.raises(ValueError):
        CA.ajustar_fir(x, y[:-1])


def test_respuesta_de_un_retardo_puro_y_de_un_sobrepico():
    c = np.zeros(48)
    c[4 + 3] = 1.0
    r = CA.respuesta(c)
    assert (r['ganancia'], r['latencia'], r['lat_asg'], r['sobrepico']) == (1.0, 3.0, 3, 0.0)
    assert r['bw_3db_mhz'] is None and r['no_causal'] == 0.0
    c[4 + 4], c[4 + 5] = 0.4, -0.4                        # sube a 1.4 y vuelve a 1
    r = CA.respuesta(c)
    assert r['sobrepico'] == pytest.approx(0.4) and r['ganancia'] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        CA.respuesta(np.zeros(48))


def test_piso_ruido_blanco_y_una_espuria():
    rng = np.random.default_rng(4)
    n = 1 << 16
    y = 10.0 + rng.normal(0, 2.0, n)
    p = CA.piso(y)
    assert p['media'] == pytest.approx(10.0, abs=0.05)
    assert p['sigma'] == pytest.approx(2.0, rel=0.02)
    assert p['sigma_blanco'] == pytest.approx(2.0, rel=0.1)
    assert p['espurias'] == []
    t = np.arange(n)
    p = CA.piso(y + 5.0 * np.sin(2 * np.pi * 10e6 / CA.FS_HZ * t))
    e = p['espurias'][0]
    assert e['f_mhz'] == pytest.approx(10.0, abs=0.15)
    assert e['rms'] == pytest.approx(5.0 / math.sqrt(2), rel=0.1)


def test_problema():
    assert 'coaxial' in CA.problema(dict(ganancia=0.003))
    assert 'HV' in CA.problema(dict(ganancia=0.05))
    assert CA.problema(dict(ganancia=0.95)) is None


# -----------------------------------------------------------------------------
# El residuo: lo que decide si una captura tiene un error
# -----------------------------------------------------------------------------

def test_residuo_ve_una_palabra_mal_y_nada_mas():
    rng = np.random.default_rng(5)
    pred = 2000 * np.sin(np.arange(20000) / 300.0)
    y = pred + rng.normal(0, 4.0, pred.size)
    r = CA.residuo(y, pred, 4.0)
    assert r['fuera'] == 0 and r['rms'] == pytest.approx(4.0, rel=0.05)
    y[12345] += 300                                       # una muestra mal leída
    r = CA.residuo(y, pred, 4.0, mascara=True)
    assert r['fuera'] == 1 and np.flatnonzero(r['_mascara']).tolist() == [12345]


def test_residuo_tolera_la_alinealidad_y_no_mira_los_recortes():
    rng = np.random.default_rng(6)
    pred = 7000 * np.sin(np.arange(20000) / 300.0)
    # una compresión del 1 % arriba: no es un error de captura
    y = pred * (1 - 0.01 * (np.abs(pred) / 7000) ** 2) + rng.normal(0, 4.0, pred.size)
    assert CA.residuo(y, pred, 4.0)['fuera'] == 0
    # lo que el ADC recorta (y RECUPERA muestras a cada lado) no se compara
    y2 = np.clip(pred * 1.3, CA.AMP_MIN, CA.AMP_MAX)
    r = CA.residuo(y2, pred * 1.3, 4.0)
    assert r['fuera'] == 0 and r['muestras'] < pred.size


# -----------------------------------------------------------------------------
# Todo junto, con el canal de juguete
# -----------------------------------------------------------------------------

@pytest.fixture(scope='module')
def capturas():
    from run_fidelidad_osc import CapturaSimulada, capturar_canal
    canal = CA.CanalSimulado(semilla=2, ganancia=0.9, offset=-30.0, lat=7, ruido=1.0,
                             diafonia=0.003)
    return canal, capturar_canal(CapturaSimulada(['bram'], n_buf=16384, modo='analogico',
                                                 canal=canal))


def test_caracterizar_devuelve_el_canal_de_juguete(capturas):
    canal, d = capturas
    c = CA.caracterizar(**d)
    assert c['ganancia'] == pytest.approx(0.9, rel=0.01)
    assert c['ganancia_dc'] == pytest.approx(0.9, rel=0.02)    # sin caída lenta
    assert c['offset'] == pytest.approx(-30.0, abs=0.3)
    assert c['ruido'] == pytest.approx(1.0, rel=0.1)
    assert c['residuo_rms'] == pytest.approx(1.0, rel=0.15)
    assert c['no_causal'] < 1e-3
    # el retardo: 7 muestras más el de los dos polos (≈ 2 a / (1 − a) = 1.6)
    assert c['latencia'] == pytest.approx(7 + 2 * 0.45 / 0.55, abs=0.3)
    assert 7 <= c['lat_asg'] <= 10
    assert c['diafonia_db'] == pytest.approx(20 * math.log10(0.003), abs=3)
    assert CA.problema(c) is None


def test_el_canal_de_juguete_es_determinista():
    ch = CA.CanalSimulado(semilla=3)
    x = np.round(1000 * np.sin(np.arange(5000) / 50.0))
    assert np.array_equal(ch.aplicar(x), ch.aplicar(x))
    assert not np.array_equal(ch.aplicar(x, 0), ch.aplicar(x, 1))
    assert CA.CanalSimulado.desde_texto('ganancia=0.5,lat=3').p['lat'] == 3
    with pytest.raises(ValueError):
        CA.CanalSimulado(ganacia=1.0)


# -----------------------------------------------------------------------------
# El canal medido, para la placa simulada
# -----------------------------------------------------------------------------

@pytest.fixture(scope='module')
def capturas_medidas(tmp_path_factory):
    """Un canal.npz como el de run_fidelidad_osc con un FIR, un polo lento y un ruido
    conocidos en IN1, y una diafonía chica en IN2."""
    x = _estimulo(40000)
    c = np.zeros(48)
    c[4 + 3], c[4 + 4] = 0.6, 0.35
    rng = np.random.default_rng(7)
    y0 = CA.predecir(x, c, -45.0, d=[-0.05], lentos=[1600]) + rng.normal(0, 2.0, x.size)
    y1 = CA.predecir(x, 0.002 * c, -100.0) + rng.normal(0, 3.0, x.size)
    ruta = tmp_path_factory.mktemp('canal') / 'canal.npz'
    np.savez(ruta, x=x, y0=np.round(y0), y1=np.round(y1),
             piso0=np.round(-45.0 + rng.normal(0, 2.0, 8192)),
             piso1=np.round(-100.0 + rng.normal(0, 3.0, 8192)))
    return ruta, c


def test_el_canal_medido_devuelve_lo_que_se_midio(capturas_medidas):
    ruta, c = capturas_medidas
    ch = CA.CanalMedido.desde_capturas(ruta, lentos=(1600,))
    d = ch.describir()
    assert d['ganancia'] == pytest.approx(0.95, abs=0.005)
    assert d['caida_lenta'] == pytest.approx(-0.05 / 0.95, abs=0.005)
    assert ch.ruido == pytest.approx(2.0, rel=0.05) and ch.ruido2 == pytest.approx(3.0, rel=0.05)
    # un escalón largo: sube a 0.95 y cae a 0.90 con el polo lento, sobre el offset
    x = np.zeros(20000)
    x[2000:] = 1000.0
    y = ch.aplicar(x).astype(float)
    assert y[:1500].mean() == pytest.approx(-45.0, abs=0.5)
    assert y[2100:2200].mean() + 45.0 == pytest.approx(950.0 - 50.0 * (1 - np.exp(-150 / 1600)), abs=3)
    assert y[-1000:].mean() + 45.0 == pytest.approx(900.0, abs=3)
    assert ch.lenta(x)[-1] == pytest.approx(-50.0, abs=1.5)
    y1 = ch.aplicar(x, 1).astype(float)                                 # IN2: la diafonía
    assert y1[:1500].mean() == pytest.approx(-100.0, abs=0.5)
    assert y1[3000:].mean() + 100.0 == pytest.approx(0.002 * 950.0, abs=0.3)


def test_el_canal_medido_sin_lentos_no_tiene_caida(capturas_medidas):
    ruta, _ = capturas_medidas
    ch = CA.CanalMedido.desde_capturas(ruta, lentos=())
    x = np.zeros(20000)
    x[2000:] = 1000.0
    assert not ch.lenta(x).any() and ch.describir()['d'] == []
    y = ch.aplicar(x).astype(float)
    assert np.ptp(y[3000:].reshape(-1, 1000).mean(axis=1)) < 2.0       # plano después del flanco


def test_el_canal_medido_es_determinista(capturas_medidas):
    ch = CA.CanalMedido.desde_capturas(capturas_medidas[0], semilla=3)
    x = np.round(1000 * np.sin(np.arange(5000) / 50.0))
    assert np.array_equal(ch.aplicar(x), ch.aplicar(x))
    assert not np.array_equal(ch.aplicar(x), CA.CanalMedido.desde_capturas(
        capturas_medidas[0], semilla=4).aplicar(x))
