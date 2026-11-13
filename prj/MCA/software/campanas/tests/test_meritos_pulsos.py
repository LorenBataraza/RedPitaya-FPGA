"""`campanas/run_meritos_pulsos.py` sin placa: las cuentas del script y las dos etapas
sobre la placa simulada (el modelo del generador y la réplica del MCA).

La réplica es lo que la placa tiene que dar, así que contra ella se prueba la plomería:
que el script mida lo que dice medir y que las comprobaciones salten cuando algo no
cierra. Lo que no se puede probar acá es `PlacaReal` (habla con /dev/mem): se prueba
en la placa.
"""
import json
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

import API.generadores as G                                          # noqa: E402
import run_meritos_pulsos as R                                       # noqa: E402

CORTO = ['--ciclos-max', '3e5', '--n-ref', '200', '--semilla', '7']


@pytest.fixture(scope='module')
def placa():
    return R.PlacaSimulada(h_aw=13, ciclos_max=300_000)


# -----------------------------------------------------------------------------
# Las cuentas
# -----------------------------------------------------------------------------

def test_k_par_deja_el_hueco_y_respeta_la_tabla():
    assert R.k_par(2, 3000) == G.N_TABLA            # 1501 no entra: la tabla entera
    assert R.k_par(100, 3000) == 31                 # 31·100 ≥ 100 + 3000
    assert R.k_par(1500, 3000) == 3                 # el par y un cero, al menos
    assert R.k_par(4000, 3000) == 3                 # aunque Δt solo ya sea el hueco
    for dt in (3, 7, 64, 512):
        k = R.k_par(dt, 3000)
        assert (k - 2) * dt + dt >= 3000 or k == G.N_TABLA


def _greedy(t):
    """Lo que hace el multitrigger (volcado_pulsos.disparos_asg), pulso por pulso."""
    out, ult = 0, None
    for x in t:
        if ult is None or x - ult >= R.REARME_ASG:
            ult = x
        else:
            out += 1
    return out


@pytest.mark.parametrize('semilla', range(6))
def test_perdidos_rearme_asg_es_el_greedy_del_multitrigger(semilla):
    rng = np.random.default_rng(semilla)
    d = rng.choice([2, 2, 2, 3, 4, 9], size=3000)       # rachas de intervalos de 2
    t = np.cumsum(d)
    assert R.perdidos_rearme_asg(t) == _greedy(t)


def test_perdidos_rearme_asg_con_los_instantes_del_motor():
    gen = G.config(aleatorio=True, tasa=3e6, dt_min=2, n=20_000, semilla=3)
    t = R.instantes(gen)
    assert t.size == 20_000
    assert R.perdidos_rearme_asg(t) == _greedy(t) > 0
    gen3 = G.config(aleatorio=True, tasa=3e6, dt_min=3, n=20_000, semilla=3)
    assert R.perdidos_rearme_asg(R.instantes(gen3)) == 0


def test_campbell_contra_la_traza_del_generador(placa):
    """El nivel medio y el desvío del apilamiento, contra la salida del modelo del
    generador (sin ruido, sin subida, sin saturar)."""
    lineas, pesos, tau = [500, 1300], [0.6, 0.4], 250.0
    gen = G.config(aleatorio=True, tasa=1e6, dt_min=2, n=3000, amp_aleat=True, semilla=5,
                   tau=tau, ruido=False)
    tabla = R.tabla_lineas(lineas, pesos)
    x, t = placa._traza(gen, tabla)
    y = x[placa.vp.PAD + 2000:placa.vp.PAD + int(t['trig'][-1])].astype(float)
    ap = R.apilamiento(1e6, tau, lineas, pesos)
    assert y.mean() == pytest.approx(ap['nivel_medio'], rel=0.06)
    assert y.std() == pytest.approx(ap['nivel_sigma'], rel=0.08)
    assert not ap['satura'] and R.apilamiento(3e6, tau, lineas, pesos)['satura']


def test_lineas_buenos_y_centroide():
    h = np.zeros(8192, np.int64)
    h[0] = 50                                   # marcados: no son una línea
    h[498:503] = [10, 40, 100, 40, 10]          # centroide 500
    h[1299:1302] = [20, 60, 20]                 # centroide 1300
    h[700] = 3                                  # un apilado suelto
    ls = R.lineas_ref(h, 2)
    assert ls == pytest.approx([500.0, 1300.0])
    assert R.contar_linea(h, 500.0, 0.02) == 200
    assert R.contar_linea(h, 1300.0, 0.02) == 100
    assert R.centroide(h, 500.0) == pytest.approx(500.0)
    assert R.lineas_ref(np.zeros(100), 2) == []


def test_umbral_desde_pide_que_valga_hacia_arriba():
    xs = [2, 4, 8, 16, 32]
    assert R.umbral_desde(xs, [1, 2, 1, 2, 2], lambda y: y == 2) == 16
    assert R.umbral_desde(xs, [2, 2, 2, 2, 2], lambda y: y == 2) == 2
    assert R.umbral_desde(xs, [2, 2, 2, 2, 1], lambda y: y == 2) is None


def test_el_umbral_del_polo_cero_vuelve_entero_por_la_api():
    """`PlacaReal` le pasa a multitrigger_armar_mca el umbral crudo dividido por la
    ganancia, y la API lo multiplica y redondea: tiene que volver el mismo."""
    from API.multitrigger import pz_ganancia
    for tau in (100.0, 250.0, 400.0):
        decae = G.decae_para(tau)
        d = R.disparo_de('pz', decae, 0)
        g = pz_ganancia(d['pz_k'], d['pz_m'], d['pz_mq'], d['pz_sh'])
        assert int(round(d['pz_thr'] / g * g)) == d['pz_thr']
        assert int(round(d['pz_hyst'] / g * g)) == d['pz_hyst']


def test_las_tres_fuentes_dejan_la_ventana_en_el_mismo_lugar(placa):
    """Pulsos aislados: el mismo F_TRAP y el mismo F_TRISE (del disparo al pico) con
    las tres fuentes. F_TRAP solo no alcanza: la meseta es plana, y una ventana corrida
    una muestra mide lo mismo."""
    gen = G.config(periodo=1500, n=30, amp_n=3, tau=250.0, ruido=True, ruido_sh=6)
    tabla = np.array([4000, 2400, 6000], np.int16)
    vistos = {}
    for f in R.FUENTES:
        r = placa.correr(gen, tabla, R.mca_de(f, gen['decae'], 3),
                         R.disparo_de(f, gen['decae'], 0), R._esp(['trapecio', 't_subida']))
        vistos[f] = [r['corridas'][i]['hist'] for i in range(2)]
    for f in ('asg', 'pendiente'):
        assert np.array_equal(vistos[f][0], vistos['pz'][0]), f
        assert np.array_equal(vistos[f][1], vistos['pz'][1]), f
    assert np.flatnonzero(vistos['pz'][1]).tolist() == [7]   # el pico, 7 ciclos adentro


def test_el_walk_del_disparo_por_pendiente(placa):
    """Un pulso chico cruza el umbral de la pendiente más tarde (el walk); el polo-cero
    no: t_subida se corre para uno y no para el otro."""
    gen = G.config(periodo=1500, n=20, amp_n=2, tau=250.0, ruido=False)
    tabla = np.array([300, 4000], np.int16)
    ts = {}
    for f in ('pz', 'pendiente'):
        r = placa.correr(gen, tabla, R.mca_de(f, gen['decae'], 1),
                         R.disparo_de(f, gen['decae'], 0), R._esp(['t_subida']))
        ts[f] = np.flatnonzero(r['corridas'][0]['hist']).tolist()
    assert ts['pz'] == [7] and len(ts['pendiente']) == 2


# -----------------------------------------------------------------------------
# Las comprobaciones
# -----------------------------------------------------------------------------

def _res(placa, n=300):
    gen = G.config(aleatorio=True, tasa=1e6, dt_min=2, n=n, amp_aleat=True, semilla=2,
                   tau=250.0, ruido=True, ruido_sh=6)
    return gen, placa.correr(gen, R.tabla_lineas([500, 1300], [0.6, 0.4]),
                             R.mca_de('asg', gen['decae'], 1), {'fuente': 'asg'},
                             [('trapecio', 0), ('pico', 0)])


def test_comprobar_pasa_con_la_simulada(placa):
    gen, res = _res(placa)
    assert R.comprobar(res, gen['n']) == []


def _todas(campo, delta):
    """Cambia un contador en todas las corridas: si no, lo atrapa el determinismo."""
    def f(r):
        for c in r['corridas']:
            c['cnt'][campo] += delta
    return f


def _relojes_de_placa(r, rearm=5):
    """Contadores como los de la placa: t_rearm medido, y el teselado cerrado."""
    for c in r['corridas']:
        c['cnt'].update(t_rearm=rearm, livetime=c['cnt']['livetime'] - rearm)


@pytest.mark.parametrize('rompe,texto', [
    (lambda r: r['gen'].update(gen_cnt=r['gen']['gen_cnt'] - 1), 'generador'),
    (lambda r: r['gen'].update(desborde=True), 'generador'),
    (_todas('cross', 1), 'corrida 0: cross'),
    (_todas('total', -1), 'corrida 0: total'),
    (lambda r: r['corridas'][1]['cnt'].update(pileup=r['corridas'][1]['cnt']['pileup'] + 1),
     'determinista'),
    (lambda r: r['corridas'][0]['hist'].__setitem__(5, r['corridas'][0]['hist'][5] + 1),
     'corrida 0: el espectro'),
    (lambda r: (_relojes_de_placa(r), _todas('livetime', -1)(r)), 'corrida 0: el teselado'),
])
def test_comprobar_salta(placa, rompe, texto):
    gen, res = _res(placa)
    rompe(res)
    mal = R.comprobar(res, gen['n'])
    assert any(texto in m for m in mal), mal


def test_comprobar_acepta_los_relojes_de_la_placa(placa):
    """Con t_rearm medido (la placa) y el teselado cerrado, no hay anomalía."""
    gen, res = _res(placa)
    _relojes_de_placa(res)
    assert R.comprobar(res, gen['n']) == []


def test_meritos_tasa_a_mano():
    """λ̂ descuenta el veto y el re-armado del tiempo del generador; un disparo de más
    no es un pulso perdido."""
    n, T = 1000, 125_000                              # 1 ms de generador
    cnt = dict(cross=1010, open=900, lost_active=100, dropped=10, lost_veto=0,
               accepted=900, total=900, pileup=0, rej_amp=0, rej_psd=0, windows=900,
               trig_edges=1010, realtime=200_000, vetotime=1000, t_win=20_000, t_div=5000,
               t_rearm=24_000, livetime=150_000, t_ocup=[])
    m = R.meritos_tasa({'t_gen': T, 'corridas': [{'cnt': cnt, 'hist': np.zeros(8)}]}, n,
                       None)
    assert m['n_in_hz'] == pytest.approx(1e6)
    assert m['lam_hz'] == pytest.approx(1010 * 125e6 / (T - 1000 - 24_000))
    assert m['perd_disparo'] == 0 and m['extra_disparos'] == 10
    assert m['muerto'] == pytest.approx((20_000 + 5000 + 24_000) / T)
    assert m['muerto_mca'] == pytest.approx(25_000 / T)
    assert 'buenos' not in m


def test_las_perdidas_suman_los_pulsos(placa):
    """N = sin disparo + sin ranura + publicador + veto + aceptados, sin rechazos."""
    gen, res = _res(placa, n=2000)
    m = R.meritos_tasa(res, gen['n'], None)
    suma = (m['perd_disparo'] + m['perd_ranura'] + m['perd_publicador'] + m['perd_veto']
            + m['eficiencia'])
    assert suma == pytest.approx(1.0)
    assert m['n_in_hz'] == pytest.approx(1e6, rel=0.06)
    assert m['perd_ranura'] > 0                     # 1 ranura a 1 M/s: pierde


# -----------------------------------------------------------------------------
# Las dos etapas, enteras
# -----------------------------------------------------------------------------

def _correr(tmp_path, placa, *extra):
    rc = R.main([str(tmp_path), '--simulada', *CORTO, *extra], placa=placa)
    with open(tmp_path / 'meritos.json') as f:
        return rc, json.load(f)


def test_etapa_tasa(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'tasa', '--tasas', '1e4,2e6',
                    '--fuentes', 'asg,pz', '--n-acc', '1,3', '--n-min', '50')
    assert rc == 0 and d['anomalias'] == []
    assert set(d['referencias']) == {'tasa/asg', 'tasa/pz'}
    for ref in d['referencias'].values():
        assert len(ref['trapecio']['lineas']) == 2
        assert ref['trapecio']['ganancia'] == pytest.approx([7.81, 7.81], rel=0.01)
    filas = {(f['fuente'], f['n_acc'], f['tasa']): f for f in d['filas']}
    assert len(filas) == 8
    for (fuente, n_acc, tasa), f in filas.items():
        m = f['corridas'][0]['meritos']
        n = f['gen']['n']
        if fuente == 'asg':
            # el disparo del ASG pierde exactamente los pulsos a menos de 3 ciclos
            assert f['corridas'][0]['cnt']['cross'] == n - f['perdidos_rearme_asg']
        if tasa == 1e4:
            assert m['eficiencia'] > 0.99 and m['frac_buenos'] > 0.99
            assert not f['apilamiento']['satura']
    alta1, alta3 = filas[('pz', 1, 2e6)], filas[('pz', 3, 2e6)]
    m1, m3 = alta1['corridas'][0]['meritos'], alta3['corridas'][0]['meritos']
    assert m3['aceptados_hz'] > m1['aceptados_hz']      # las ranuras sirven
    assert m1['perd_ranura'] > m3['perd_ranura']
    assert m1['perd_disparo'] == m3['perd_disparo']     # el disparo no depende del MCA


def test_etapa_par(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'par', '--dts', '4,16,512',
                    '--fuentes', 'asg,pz', '--n-acc-par', '1,3', '--n-pares', '40')
    assert rc == 0 and d['anomalias'] == []
    assert set(d['referencias']) == {'par/pz'}           # el ASG no aplica
    # la referencia son pulsos aislados: el pico de A2 no monta en la cola de A1
    # (con 8192 canales, el del pico es la mitad de la amplitud)
    assert d['referencias']['par/pz']['pico']['lineas'] == pytest.approx([1200, 2000], abs=1.5)
    filas = {(f['n_acc'], f['dt']): f for f in d['filas']}
    m = {k: [c['meritos'] for c in f['corridas']] for k, f in filas.items()}
    # el polo-cero funde a 4 ciclos y separa a 16
    assert m[(3, 4)][0]['disparos_par'] == 1.0
    assert m[(3, 16)][0]['disparos_par'] == 2.0
    # con 3 ranuras el banco mide los dos a 16; con 1, el segundo no tiene ranura
    assert m[(3, 16)][0]['frac_a1'] == m[(3, 16)][0]['frac_a2'] == 1.0
    assert m[(1, 16)][0]['eventos_par'] == 1.0 and m[(1, 16)][0]['frac_a2'] == 0.0
    # aislados (512 ciclos): el trapecio mide los dos; el pico ve al segundo sobre la
    # cola del primero
    assert m[(1, 512)][0]['frac_a1'] == m[(1, 512)][0]['frac_a2'] == 1.0
    pico = m[(1, 512)][1]
    assert pico['frac_a1'] == 1.0 and pico['frac_a2'] == 0.0 and pico['sesgo_a2'] is None
    assert 'resolución' in R.resumen(d['filas'])


def test_par_recortado_deja_pares_enteros(tmp_path):
    """La simulada recorta N: lo que queda tiene que ser un número entero de pares."""
    chica = R.PlacaSimulada(h_aw=13, ciclos_max=50_000)
    rc = R.main([str(tmp_path), '--simulada', '--n-ref', '100', '--etapas', 'par',
                 '--dts', '16', '--fuentes', 'pz', '--n-acc-par', '3', '--n-pares', '40',
                 '--espectros-par', 'trapecio,t_subida'], placa=chica)
    d = json.load(open(tmp_path / 'meritos.json'))
    f = d['filas'][0]
    assert rc == 0 and f['gen']['n'] % f['k'] == 0 and f['n_pares'] < 40
    m = f['corridas'][0]['meritos']
    assert m['disparos_par'] == 2.0 and m['frac_a1'] == m['frac_a2'] == 1.0
    assert f['corridas'][1]['meritos']['t_subida']['media'] > 0
    assert d['referencias']['par/pz']['t_subida']['lineas'] is None


def test_una_corrida_que_no_cierra_sale_con_1(tmp_path, placa):
    class Rota:
        nombre, h_aw, n_acc_max = 'rota', placa.h_aw, placa.n_acc_max

        def recortar(self, gen):
            return placa.recortar(gen)

        def correr(self, *a):
            r = placa.correr(*a)
            r['corridas'][0]['cnt']['open'] -= 1
            return r

        def close(self):
            pass

    rc = R.main([str(tmp_path), *CORTO, '--etapas', 'tasa', '--tasas', '1e5',
                 '--fuentes', 'asg', '--n-acc', '1', '--n-min', '50'], placa=Rota())
    d = json.load(open(tmp_path / 'meritos.json'))
    assert rc == 1 and any('cross' in x for x in d['anomalias'])


def test_comparar(tmp_path, placa, capsys):
    for sub in ('a', 'b'):
        (tmp_path / sub).mkdir()
        rc, _ = _correr(tmp_path / sub, placa, '--etapas', 'tasa', '--tasas', '1e5',
                        '--fuentes', 'pz', '--n-acc', '2', '--n-min', '50')
        assert rc == 0
    assert R.main(['--comparar', str(tmp_path / 'a' / 'meritos.json'),
                   str(tmp_path / 'b' / 'meritos.json')]) == 0
    out = capsys.readouterr().out
    assert 'tasa pz 2 100000.0 trapecio' in out and 'eficiencia' in out
