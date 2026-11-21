"""`API/base_dinamica.py` sin placa: la ley de la base dinámica, el Clear, los topes y
los 14 bits, y un lazo cerrado contra una planta de juguete (la línea se corre con el
error de base que queda).

Correr:  python3 -m pytest API/tests/test_base_dinamica.py -v
"""
import os
import sys

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

from API import base_dinamica as BD                                  # noqa: E402

H_AW = 13
FS = 125e6


def _valores():
    return BD.valores_de_canales(1 << H_AW, H_AW)


class Planta:
    """Contadores y un histograma que avanzan: λ pulsos/s con la línea en `canal`."""

    def __init__(self, lam, canal):
        self.lam, self.canal = lam, canal
        self.cnt = dict(cross=0, lost_veto=0, realtime_s=0.0, vetotime_s=0.0, t_rearm_s=0.0)
        self.hist = np.zeros(1 << H_AW, np.int64)
        self._resto = 0.0

    def avanzar(self, dt, canal=None):
        n = self.lam * dt + self._resto
        k = int(n)
        self._resto = n - k
        self.cnt['cross'] += k
        self.cnt['realtime_s'] += dt
        c = self.canal if canal is None else canal
        self.hist[int(round(c))] += k
        return self.cnt, self.hist


def test_la_ley():
    """Con λ, ⟨A⟩ y τ fijos, Δb = κ·caída·(λ/f_s)·⟨A⟩·τ."""
    v = _valores()
    canal = 2000
    g = 4.0                      # cuentas de la feature por ADU
    a = v[canal] / g
    bd = BD.BaseDinamica(caida=-0.07, ganancia_mca=g, b0=-12, kappa=1.0, suavizado_s=0)
    p = Planta(400e3, canal)
    for _ in range(5):
        r = bd.paso(*p.avanzar(0.25), v, 250.0)
    esperado = -0.07 * (400e3 / FS) * a * 250.0
    assert r['lam_hz'] == pytest.approx(400e3, rel=1e-3)
    assert r['a_adu'] == pytest.approx(a)
    assert r['delta_b'] == pytest.approx(esperado, rel=1e-3)
    assert r['base'] == round(-12 + esperado)
    bd.kappa = 0.5
    r = bd.paso(*p.avanzar(0.25), v, 250.0)
    assert r['delta_b'] == pytest.approx(0.5 * esperado, rel=1e-3)


def test_el_suavizado_converge():
    v = _valores()
    bd = BD.BaseDinamica(caida=-0.07, ganancia_mca=4.0, b0=0, suavizado_s=1.0)
    p = Planta(400e3, 2000)
    bd.paso(*p.avanzar(0.25), v, 250.0)
    primero = bd.paso(*p.avanzar(0.25), v, 250.0)['lam_hz']
    p.lam = 800e3
    lams = [bd.paso(*p.avanzar(0.25), v, 250.0)['lam_hz'] for _ in range(40)]
    assert primero == pytest.approx(400e3, rel=1e-3)
    assert lams[0] < 600e3                   # no salta
    assert lams[-1] == pytest.approx(800e3, rel=1e-3)


def test_un_clear_no_mueve_la_base():
    v = _valores()
    bd = BD.BaseDinamica(caida=-0.07, ganancia_mca=4.0, b0=0, suavizado_s=0)
    p = Planta(400e3, 2000)
    for _ in range(3):
        r = bd.paso(*p.avanzar(0.25), v, 250.0)
    antes = r['base']
    p.cnt = {k: 0 for k in p.cnt}            # el Clear
    p.hist[:] = 0
    r = bd.paso(*p.avanzar(0.25), v, 250.0)
    assert r['base'] == antes and r['reinicios'] == 1
    r = bd.paso(*p.avanzar(0.25), v, 250.0)
    assert r['base'] == antes


def test_parado_no_cambia():
    v = _valores()
    bd = BD.BaseDinamica(caida=-0.07, ganancia_mca=4.0, b0=5, suavizado_s=0)
    p = Planta(400e3, 2000)
    for _ in range(3):
        bd.paso(*p.avanzar(0.25), v, 250.0)
    antes = bd.estado()
    r = bd.paso(*p.avanzar(0.0), v, 250.0)
    assert r['base'] == antes['base'] and r['pasos'] == antes['pasos']


def test_topes():
    v = _valores()
    bd = BD.BaseDinamica(caida=-0.5, ganancia_mca=1.0, b0=-8000, suavizado_s=0, tope=1000)
    p = Planta(3e6, 8000)
    for _ in range(3):
        r = bd.paso(*p.avanzar(0.25), v, 250.0)
    assert r['delta_b'] == -1000
    assert r['base'] == BD.BASE_MIN


def test_sin_eventos_no_hay_amplitud():
    """λ̂ sin ⟨A⟩ (todo en el canal 0, que no cuenta) no corre la base."""
    v = _valores()
    bd = BD.BaseDinamica(caida=-0.07, ganancia_mca=4.0, b0=3, suavizado_s=0)
    p = Planta(400e3, 0)
    for _ in range(3):
        r = bd.paso(*p.avanzar(0.25), v, 250.0)
    assert r['a_adu'] is None and r['base'] == 3


def test_ganancia_invalida():
    with pytest.raises(ValueError, match='ganancia'):
        BD.BaseDinamica(caida=-0.07, ganancia_mca=0, b0=0)


def test_lazo_cerrado_con_una_planta():
    """La línea se corre s·(Δb_real − Δb_puesta) canales. Con la caída de la planta, la
    dinámica la devuelve a su lugar; con la base fija queda corrida."""
    v = _valores()
    g, s, caida, tau, lam = 4.0, 0.41, -0.07, 250.0, 400e3
    c0 = 2000.0
    a_real = v[int(c0)] / g
    db_real = caida * (lam / FS) * a_real * tau

    def correr(bd):
        p = Planta(lam, c0)
        puesta = 0.0
        for _ in range(30):
            c = c0 + s * (db_real - puesta)
            r = bd.paso(*p.avanzar(0.25, c), v, tau) if bd else None
            puesta = r['delta_b'] if r else 0.0
        return c0 + s * (db_real - puesta)
    fija = correr(None)
    dinamica = correr(BD.BaseDinamica(caida, g, b0=0, suavizado_s=0.5))
    assert fija - c0 < -10                   # ~ −11 canales, como la placa a 400 k/s
    assert abs(dinamica - c0) < 1.0


def test_cebada_arranca_en_su_lugar():
    """Cebada con λ y ⟨A⟩ del estímulo, la base está bien desde el primer paso, y con
    `fijar_a` el histograma (otra feature, como t_subida) no mueve ⟨A⟩."""
    v = _valores()
    bd = BD.BaseDinamica(caida=-0.07, ganancia_mca=4.0, b0=-12, suavizado_s=1.0)
    r = bd.cebar(400e3, 900.0, 250.0)
    esperado = -0.07 * (400e3 / FS) * 900.0 * 250.0
    assert r['delta_b'] == pytest.approx(esperado) and r['base'] == round(-12 + esperado)
    bd.fijar_a = True
    p = Planta(400e3, 7000)                   # la feature en otro lado
    for _ in range(4):
        r = bd.paso(*p.avanzar(0.25), v, 250.0)
    assert r['a_adu'] == 900.0
    assert r['delta_b'] == pytest.approx(esperado, rel=1e-3)


def test_kappa_optimo():
    assert BD.kappa_optimo(-9.3, 3.1, 1.0) == pytest.approx(9.3 / 12.4)
    assert BD.kappa_optimo(-9.3, -2.0, 0.5) == pytest.approx(0.5 * 9.3 / 7.3)
    assert BD.kappa_optimo(0.0, 0.0, 1.0) is None
    assert BD.kappa_optimo(None, 1.0, 1.0) is None


def test_los_valores_son_los_del_eje():
    from API.mca import mca_amplitud_de_canal
    v = BD.valores_de_canales(1 << H_AW, H_AW, z=2, k=1)
    for c in (0, 17, 4000):
        lo = mca_amplitud_de_canal(c, H_AW, 2, 1)
        hi = mca_amplitud_de_canal(c + 1, H_AW, 2, 1)
        assert v[c] == pytest.approx(0.5 * (lo + hi))


def test_centroides():
    h = np.zeros(8192)
    h[1000:1005] = [1, 4, 6, 4, 1]
    h[3000:3003] = [2, 5, 2]
    ls = BD.centroides_lineas(h, 2)
    assert [round(x['centroide'], 3) for x in ls] == [1002.0, 3001.0]
    h[901:1104] += 1                          # un continuo parejo en la ventana
    assert BD.centroide_en(h, 1002.0) == pytest.approx(1002.0, abs=0.01)
    assert BD.centroide_en(np.zeros(8192), 1002.0) is None
