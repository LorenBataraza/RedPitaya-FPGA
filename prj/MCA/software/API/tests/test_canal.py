"""`API/canal.py` sin placa: la medición lenta (diezmada, sin los flancos), la referencia
externa (el escalón ideal desde la captura) y `CapturaBram`, que tiene que dejar el OSC,
el multitrigger y el generador como estaban.

Los ajustes van contra canales sintéticos con los polos lentos conocidos; la captura,
contra los fakes de registros de `mca_remote` (la lógica de libmca por el backend de
callbacks) con la BRAM sintetizada por `canal_falso.CapturaFalsa`.

Correr:  python3 -m pytest API/tests/test_canal.py -v
"""
import os
import sys

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

from API import canal as C                                           # noqa: E402
from API import canal_falso as CF                                    # noqa: E402


# =============================================================================
# Sin hardware: los ajustes
# =============================================================================

def _cuasi_escalones(n, periodo=16384, alto=3000.0, tau=65535.0, antes=2048):
    """Lo que pone el generador en la medición lenta, a ritmo pleno."""
    from scipy.signal import lfilter
    imp = np.zeros(n)
    t = np.arange(antes, n, periodo)
    imp[t] = np.where(np.arange(t.size) % 2 == 0, alto, -alto)
    return lfilter([1.0], [1.0, -np.exp(-1.0 / tau)], imp)


def test_la_lenta_recupera_la_caida_con_fases_distintas():
    """Cada captura con su fase de diezmado (la x una vez, las y cuatro): los flancos
    quedan fuera y la caída sale igual."""
    canal = CF.CanalFalso(semilla=3)
    rng = np.random.default_rng(5)
    dec, n = C.DEC_LENTO, 8192
    xf = _cuasi_escalones((n + 1) * dec)

    def captura(v):
        return CF.diezmar(v, dec, int(rng.integers(0, dec)))[:n]
    x = captura(xf)
    pares = [(x, captura(canal.aplicar(xf))) for _ in range(4)]
    r = C.caracterizar_lento(pares, dec)
    assert r['caida_lenta'] == pytest.approx(canal.caida, rel=0.05)
    assert r['ganancia'] == pytest.approx(0.95, rel=0.02)
    # Sin los polos lentos el ajuste queda mucho peor: la caída es lo que falta.
    assert r['residuo_rms_sin_lentos'] > 5 * r['residuo_rms']
    assert r['residuo_rms'] < 3 * canal.p['ruido']


def test_con_los_flancos_adentro_la_lenta_se_arruina():
    """Lo que justifica la máscara: sin ella, la fase del diezmado mete cientos de
    cuentas en los flancos."""
    canal = CF.CanalFalso(semilla=3)
    rng = np.random.default_rng(5)
    dec, n = C.DEC_LENTO, 8192
    xf = _cuasi_escalones((n + 1) * dec)
    x = CF.diezmar(xf, dec, 0)[:n]
    y = CF.diezmar(canal.aplicar(xf), dec, int(rng.integers(1, dec)))[:n]
    f = C.ajustar_pares([(x, y)], C.LAGS_LENTO, lentos=C.lentos_diezmados(dec))
    con = C.ajustar_pares([(x, y)], C.LAGS_LENTO, lentos=C.lentos_diezmados(dec),
                          fueras=[C._mascara_flancos(x)])
    assert f['rms'] > 10 * con['rms']


def test_la_externa_recupera_la_caida_de_in1():
    canal = CF.CanalFalso(semilla=4)
    rng = np.random.default_rng(2)
    dec, n, per = C.DEC_LENTO, 8192, 62500
    ys = []
    for _ in range(4):
        t = np.arange((n + 1) * dec) + int(rng.integers(0, per))
        xf = np.where((t // (per // 2)) % 2 == 0, 2000.0, -2000.0)
        ys.append(CF.diezmar(canal.aplicar(xf), dec, int(rng.integers(0, dec)))[:n])
    r = C.caracterizar_externo(ys, dec)
    assert r['referencia'] == 'externa'
    assert r['caida_lenta'] == pytest.approx(canal.caida, rel=0.05)
    assert r['escalon_cuentas'] == pytest.approx(2 * 2000 * 0.95, rel=0.15)


def test_sin_cuadrada_no_hay_escalon():
    ruido = np.random.default_rng(0).normal(0, 5, 8192)
    with pytest.raises(ValueError, match='no hay una cuadrada'):
        C.escalon_ideal(ruido)
    un_flanco = np.concatenate([np.zeros(1000), np.full(7192, 3000.0)])
    with pytest.raises(ValueError, match='dos flancos'):
        C.escalon_ideal(un_flanco)


def test_la_mascara_cubre_cada_flanco():
    x = np.zeros(200)
    x[50:120] = 1000.0
    m = C._mascara_flancos(x)
    assert m[48:63].all() and m[118:133].all()
    assert not m[:47].any() and not m[64:117].any() and not m[134:].any()


def test_la_respuesta_lenta_cae_lo_de_los_polos():
    t = np.array([0.0, 1e6])
    s = C.respuesta_lenta([-0.025, -0.045], [400.0, 1600.0], 0.95, t)
    assert s[0] == pytest.approx(1.0)
    assert s[1] == pytest.approx(1.0 - 0.07 / 0.95)


def test_ajustar_pares_es_ajustar_fir_con_un_par():
    canal = CF.CanalFalso(semilla=1)
    rng = np.random.default_rng(0)
    x = np.zeros(20000)
    x[rng.choice(19000, 300, replace=False)] = rng.uniform(-2000, 2000, 300)
    y = canal.aplicar(x)
    a = C.ajustar_fir(x, y)
    b = C.ajustar_pares([(x, y)])
    assert np.allclose(a['c'], b['c'], atol=1e-9)
    assert np.allclose(a['d'], b['d'], atol=1e-9)
    assert a['b'] == pytest.approx(b['b'])


def test_repetibilidad():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 100, 8192)
    a = base + rng.normal(0, 4, 8192)
    b = base + rng.normal(0, 4, 8192)
    assert C.repetibilidad(a, b, 4.0)['estable']
    assert not C.repetibilidad(a, 0.8 * b, 4.0)['estable']


# =============================================================================
# CapturaBram sobre los fakes de registros
# =============================================================================

@pytest.fixture
def fakes():
    pytest.importorskip('scipy')
    from API.mca_remote import FakeGenPulsos, FakeMtRegion, FakeMultiTrigger, FakeOsc
    try:
        osc = FakeOsc(n_buf=8192)
    except OSError as e:                   # sin libmca compilada
        pytest.skip(f'libmca: {e}')
    mtr = FakeMtRegion(osc=osc)
    mt = FakeMultiTrigger(region=mtr)
    gen = FakeGenPulsos().handle()
    return osc, mt, gen


def _estado(osc, mt, gen):
    from API import generadores as G
    from API import multitrigger as MT
    from API import osciloscope as O
    regs = (O.R_THR_CH0, O.R_THR_CH1, O.R_DLY_CH0, O.R_DLY_CH1, O.R_DEC_CH0, O.R_DEC_CH1,
            O.R_HYST_CH0, O.R_HYST_CH1, O.R_AVG_EN, O.R_DEB_LEN)
    return dict(osc={r: osc.r32(r) for r in regs},
                mt={r: mt.r32(r) for r in (MT.R_SHIELD_CFG, MT.R_OR_MASK_CH0,
                                           MT.R_OR_MASK_CH1)},
                cmd=osc._reg.get(O.R_CMD, 0) & 0x0909,
                gen=gen.leer_config(), tabla=list(gen.leer_tabla(G.N_TABLA)),
                lazo=gen.lazo)


def _poner_algo(osc, mt, gen):
    """Un estado del usuario cualquiera: el disparo del MCA armado en continuo, un
    umbral, diezmado 64, el generador con otra config y el lazo prendido."""
    from API import generadores as G
    from API import multitrigger as MT
    from API import osciloscope as O
    osc.w32(O.R_THR_CH0, 1234)
    osc.w32(O.R_DEC_CH0, 64)
    osc.w32(O.R_HYST_CH0, 77)
    osc.w32(O.R_DEB_LEN, 999)
    mt.w32(MT.R_SHIELD_CFG, (5 << 16) | (1 << 8) | 1)
    osc.w32(O.R_CMD, 0x0909)
    mt.w32(MT.R_OR_MASK_CH0, MT.BIT_SLOPE_P0)
    mt.w32(MT.R_OR_MASK_CH1, 0)
    gen.configurar(**G.config(tasa=33e3, tau=180.0, amp_n=2, base=17))
    gen.cargar_tabla(np.array([1500, 4000], np.int16))
    gen.lazo = True


def test_la_medicion_deja_todo_como_estaba(fakes):
    osc, mt, gen = fakes
    _poner_algo(osc, mt, gen)
    antes = _estado(osc, mt, gen)
    with CF.CapturaFalsa(osc, mt, gen, canal=CF.CanalFalso(semilla=2)) as cap:
        res, caps = C.medir(cap, 'generador', 'todo', semilla=1, promedios=2)
        # Mientras mide, la BRAM está en otro diezmado y con otra máscara.
        assert cap.restaurado is None
    assert 'generador' in cap.restaurado and 'captura re-armada (we_keep)' in cap.restaurado
    assert _estado(osc, mt, gen) == antes
    assert res['lento']['caida_lenta'] == pytest.approx(cap.canal.caida, rel=0.08)
    assert res['problema'] is None
    assert set(caps) >= {'x', 'y0', 'y1', 'piso0', 'piso1', 'lento_x', 'lento_y'}
    assert caps['lento_y'].shape == (2, 8192)


def test_tambien_restaura_si_falla(fakes):
    osc, mt, gen = fakes
    _poner_algo(osc, mt, gen)
    antes = _estado(osc, mt, gen)

    class Rota(CF.CapturaFalsa):
        def _esperar_y_leer(self, *a, **k):
            raise TimeoutError('la BRAM no completó el post-trigger')
    with pytest.raises(TimeoutError):
        with Rota(osc, mt, gen) as cap:
            C.medir(cap)
    assert _estado(osc, mt, gen) == antes


def test_no_mide_con_el_generador_generando(fakes):
    osc, mt, gen = fakes
    gen.configurar(**__import__('API.generadores', fromlist=['config']).config(tasa=1e3))
    gen.arrancar()
    try:
        with pytest.raises(RuntimeError, match='generando'):
            with CF.CapturaFalsa(osc, mt, gen):
                pass
    finally:
        gen.parar()


def test_la_rapida_da_el_canal_falso(fakes):
    osc, mt, gen = fakes
    with CF.CapturaFalsa(osc, mt, gen, canal=CF.CanalFalso(semilla=6)) as cap:
        res, _ = C.medir(cap, 'generador', 'rapido')
    assert 'lento' not in res and res['fuente_caida'] == 'rapida'
    assert res['ganancia'] == pytest.approx(0.95, rel=0.02)
    assert res['offset'] == pytest.approx(-12.0, abs=1.0)
    assert res['ruido'] == pytest.approx(4.0, rel=0.1)
    assert res['latencia'] > 9
    assert res['caida_lenta'] == pytest.approx(cap.canal.caida, rel=0.25)


def test_la_externa_con_la_captura(fakes):
    osc, mt, gen = fakes
    with CF.CapturaFalsa(osc, mt, gen, canal=CF.CanalFalso(semilla=8)) as cap:
        res, caps = C.medir(cap, 'externa', promedios=3)
    assert res['referencia'] == 'externa' and res['fuente_caida'] == 'externa'
    assert res['caida_lenta_usar'] == pytest.approx(cap.canal.caida, rel=0.08)
    assert caps['externa_y'].shape == (3, 8192)


def test_argumentos_invalidos(fakes):
    osc, mt, gen = fakes
    cap = CF.CapturaFalsa(osc, mt, gen)
    with pytest.raises(ValueError, match='referencia'):
        C.medir(cap, 'rigol')
    with pytest.raises(ValueError, match='que'):
        C.medir(cap, 'generador', 'medio')
