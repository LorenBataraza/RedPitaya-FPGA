"""`campanas/run_meritos_pulsos.py` sin placa: las cuentas del script y las dos etapas
sobre la placa simulada (el modelo del generador y la réplica del MCA).

La réplica es lo que la placa tiene que dar, así que contra ella se prueba la plomería:
que el script mida lo que dice medir y que las comprobaciones salten cuando algo no
cierra. Lo que no se puede probar acá es `PlacaReal` (habla con /dev/mem): se prueba
en la placa.
"""
import json
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


def _lecturas_en_vuelo(r, x=7, con_ley=True):
    """Como la base dinámica en la placa: x eventos chocan con una lectura del bus del
    histograma y van a cnt_dropped, sin pasar por cnt_cross ni por el espectro."""
    for c in r['corridas']:
        c['cnt']['dropped'] += x
        c['cnt']['accepted'] += x
        if con_ley:
            c['base_dinamica'] = dict(pasos=[], final={})


def test_comprobar_descuenta_las_lecturas_en_vuelo(placa):
    gen, res = _res(placa)
    _lecturas_en_vuelo(res)
    assert R.comprobar(res, gen['n']) == []
    assert all(c['cnt']['perd_lectura'] == 7 for c in res['corridas'])


def test_comprobar_sin_lecturas_en_vuelo_no_las_perdona(placa):
    """Sin la ley no hay lecturas en vuelo: la misma diferencia es una anomalía."""
    gen, res = _res(placa)
    _lecturas_en_vuelo(res, con_ley=False)
    mal = R.comprobar(res, gen['n'])
    assert any('corrida 0: cross' in m for m in mal), mal


def test_comprobar_con_la_ley_el_espectro_tiene_que_cerrar(placa):
    """Con la ley, si al espectro le falta otro número que el de las lecturas, salta."""
    gen, res = _res(placa)
    _lecturas_en_vuelo(res)
    res['corridas'][0]['hist'][5] += 1
    mal = R.comprobar(res, gen['n'])
    assert any('lecturas en vuelo' in m for m in mal), mal


def _hist_semilla(placa, semilla):
    gen = G.config(periodo=300, n=400, amp_aleat=True, semilla=semilla, tau=50.0,
                   ruido=True, ruido_sh=6)
    res = placa.correr(gen, R.tabla_uniforme(500, 5615), R.mca_de('asg', gen['decae'], 1),
                       {'fuente': 'asg'}, [('trapecio', 0)])
    return np.asarray(res['corridas'][0]['hist'])


def test_gen_pulsos_semillas_2k_y_2k_mas_1_son_la_misma(placa):
    """gen_pulsos fuerza a impar las semillas de la amplitud y del ruido, (SEMILLA ^ K) | 1:
    2k y 2k+1 dan el mismo estímulo. Por eso las tandas de la DNL van de a 2."""
    assert np.array_equal(_hist_semilla(placa, 2), _hist_semilla(placa, 3))
    assert not np.array_equal(_hist_semilla(placa, 3), _hist_semilla(placa, 5))


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

        def correr(self, *a, **kw):
            r = placa.correr(*a, **kw)
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


# -----------------------------------------------------------------------------
# Las cuentas de las etapas nuevas
# -----------------------------------------------------------------------------

def test_forma_k_da_el_banco_y_la_regla_para_las_otras():
    from API.mca import BANCO_PZ_4
    for f in BANCO_PZ_4:
        assert R.forma_k(f[0]) == tuple(f)
    for k in (128, 256, 512):
        k_, m, lw, c, antes, despues = R.forma_k(k)
        w0 = c + R.r2.LAT_PZ                       # la ventana desde el pie
        assert k_ == k and m == 3 * k // 4 and 1 << lw == k // 4
        assert k - 1 <= w0 and w0 + (1 << lw) <= k + m      # adentro de la meseta
        assert antes >= 2 * k + m - 1 - w0 and despues == w0 + (1 << lw)
        assert k + m <= 1023                       # las líneas de retardo del RTL
    for malo in (3, 24, 1024):
        with pytest.raises(ValueError):
            R.forma_k(malo)


def test_mca_de_con_el_seguidor_y_otra_m():
    fija = R.mca_de('pz', 65274, 3)
    assert not fija.get('bl_auto')
    seg = R.mca_de('pz', 65274, 3, seguidor=(13, 900))
    assert (seg['bl_auto'], seg['bl_k'], seg['bl_holdoff']) == (True, 13, 900)
    assert R.mca_de('pz', 65274, 3, mq=4000)['trap_mq'] == 4000
    assert fija['trap_mq'] == G.mq_de(65274)


def test_zoom_rango_y_centroides_lineas():
    assert R.zoom_rango(12000, 31000, 13) == (1, 0)
    assert R.zoom_rango(17000, 31000, 13) == (2, 1)
    assert R.zoom_rango(1000, 1100, 13) == (3, 0)
    h = np.zeros(8192)
    h[100:103] = [1, 2, 1]
    h[500] = 7
    h[504] = 1                                  # un hueco de 3: misma línea
    ls = R.centroides_lineas(h, 2)
    assert [d['n'] for d in ls] == [4, 8]
    assert ls[0]['centroide'] == pytest.approx(101.0)
    assert ls[1]['centroide'] == pytest.approx((500 * 7 + 504) / 8)


def test_cortes_forma_deja_la_fraccion_central():
    rng = np.random.default_rng(2)
    v = np.round(rng.normal(700, 10, 20000)).astype(int)
    h = np.bincount(v, minlength=8192)
    (n, q, d), = R.cortes_forma([{'hist': h}], [('ancho_inv', 3)], [0.9], 13)
    assert (n, q, d[0]) == ('ancho_inv', 0.9, 'ancho_inv')
    pasa = ((v >= d[1]) & (v <= d[2])).mean()
    assert 0.9 <= pasa < 0.93                   # q, y un canal de más a lo sumo


def test_meritos_apilamiento_a_mano():
    h = np.zeros(8192, int)
    h[0] = 5                                    # marcados
    h[500] = 60
    h[1300] = 40
    h[900] = 3                                  # entre las líneas
    h[2000] = 2                                 # arriba de la alta
    me = R.meritos_apilamiento(h, 200, [500.0, 1300.0], {'pileup': 7, 'total': 110,
                                                        'rej_discr': 4})
    assert me['picos'] == 100 and me['marcados'] == 5 and me['continuo'] == 5
    assert me['eps'] == 0.5 and me['fondo'] == pytest.approx(5 / 105)
    assert me['arriba'] == pytest.approx(2 / 100) and me['rej_discr'] == 4


def test_analizar_dnl_ve_la_dnl_y_no_inventa():
    rng = np.random.default_rng(5)
    plano = np.zeros(8192)
    plano[1000:5000] = rng.poisson(2000, 4000)
    d = R.analizar_dnl(plano)
    assert d['chi2'] == pytest.approx(1.0, abs=0.15)
    assert d['rms'] == pytest.approx(d['esperado'], rel=0.1)
    assert all(p['rms'] < 3 * p['esperado'] for p in d['plegado'].values())
    # una densidad inclinada (el sobrepico o la compresión del canal la inclinan) no es
    # DNL: la saca el ajuste
    inclinado = np.zeros(8192)
    inclinado[1000:5000] = rng.poisson(np.linspace(1500, 2500, 4000))
    d = R.analizar_dnl(inclinado)
    assert d['chi2'] == pytest.approx(1.0, abs=0.15)
    assert d['rms'] == pytest.approx(d['esperado'], rel=0.1)
    malo = plano.copy()
    malo[1000:5000:4] *= 1.1                    # un código de cada cuatro, 10 % más ancho
    d = R.analizar_dnl(malo)
    assert d['chi2'] > 2
    assert d['plegado']['4']['rms'] > 10 * d['plegado']['4']['esperado']
    assert R.analizar_dnl(np.zeros(8192)) is None


def test_analizar_polo_cero_y_forma():
    filas = [dict(dt=100, dm=dm, err_a2=-0.5 * (dm - 0.01), err_a1=0.0)
             for dm in (-0.05, 0.0, 0.05)]
    d = R.analizar_polo_cero(filas)['100']
    assert d['pendiente'] == pytest.approx(-0.5) and d['dm_cero'] == pytest.approx(0.01)
    # T ∝ L^(−1/2) e^(2ρ): el mínimo en ρ = 1/4
    n = 1e5
    filas = []
    for k in (8, 16, 32, 64, 128, 256):
        L = 3 * k
        rho = n * L / R.FS_HZ
        eps = math.exp(-rho)
        filas.append(dict(tasa=n, k=k, rho=rho, eps=eps, limpios=eps, n_in_hz=n,
                          fwhm_rel=L ** -0.5, T=L ** -0.5 / eps ** 2))
    d = R.analizar_forma(filas)[str(n)]
    assert d['k_opt'] == 128 and d['rho_opt'] == pytest.approx(0.25, rel=0.15)


def test_meritos_y_analizar_ciega_a_mano():
    h = np.zeros(8192, int)
    h[2400], h[4000], h[6200], h[0] = 30, 40, 20, 10
    me = R.meritos_ciega(h, 100, [4000.0, 2400.0], {'cross': 120, 'rej_discr': 5})
    assert (me['a1'], me['a2'], me['apilado_aceptado'], me['marcados']) == (0.4, 0.3, 0.2, 0.1)
    assert me['disparos_par'] == 1.2 and me['rechazados'] == 0.05

    def fila(dt, disp, ap):
        return dict(subida=0, fuente='pz', corte='sin', umbral=None, dt=dt,
                    meritos=dict(disparos_par=disp, apilado_aceptado=ap, a1=1.0, a2=1.0))
    an = R.analizar_ciega([fila(2, 1.0, 1.0), fila(4, 1.0, 0.8), fila(6, 2.0, 0.9),
                           fila(8, 2.0, 0.0), fila(12, 2.0, 0.0)])['0/pz/sin/None']
    # con dos disparos (Δt 6) lo de afuera no es apilamiento: la ventana ciega es 4
    assert an['ciega_hasta'] == 4 and an['separa_desde'] == 6 and an['limpio_desde'] == 8
    assert an['conserva'] == 1.0


def test_analizar_deriva_separa_offset_y_ganancia():
    filas = []
    for i in range(7):
        t = 600.0 * i
        temp = 40.0 + 0.5 * i
        off = 0.3 * t / 3600.0                  # 0.3 cuentas por hora
        g = 8.0 * (1 + 20e-6 * i)               # 20 ppm por punto
        filas.append(dict(t_s=t, temp=temp, amplitudes=[1500, 4000],
                          lineas=[dict(valor=g * (1500 + off)), dict(valor=g * (4000 + off))]))
    d = R.analizar_deriva(filas)
    assert d['puntos'] == 7 and d['horas'] == pytest.approx(1.0)
    assert d['offset']['por_hora'] == pytest.approx(0.3, rel=0.02)
    assert d['ganancia_ppm']['rango'] == pytest.approx(120, rel=0.02)
    assert d['offset']['corr_temp'] == pytest.approx(1.0, abs=1e-6)
    assert d['temp'] == dict(min=40.0, max=43.0)
    assert R.analizar_deriva(filas[:1]) == dict(puntos=1)


def test_temperatura_zynq_no_rompe_sin_xadc():
    t = R.temperatura_zynq()
    assert t is None or -40 < t < 125


# -----------------------------------------------------------------------------
# Las demás etapas, enteras, sobre la simulada
# -----------------------------------------------------------------------------

def test_etapa_histeresis_fija_sin_histeresis(tmp_path, placa):
    """La simulada es determinista: la ida y la vuelta dan lo mismo. El seguidor no
    está en la réplica y se saltea."""
    rc, d = _correr(tmp_path, placa, '--etapas', 'histeresis', '--tasas-hist', '1e3,1e5',
                    '--seg-hist', '0.01', '--n-min-hist', '50')
    assert rc == 0 and d['anomalias'] == []
    assert {f['modo'] for f in d['filas']} == {'fija'}
    an = d['meta']['histeresis']['fija']
    assert an['veredicto'] == 'sin histéresis' and an['h_max'] == 0.0
    assert len(d['filas']) == 4 and an['tasas'] == pytest.approx([1e3, 1e5], rel=0.01)


def test_etapa_walk(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'walk', '--amps-walk', '20,150,300,2000,5000',
                    '--fuentes', 'asg,pz,pendiente', '--n-walk', '50')
    assert rc == 0 and d['anomalias'] == []
    w = d['meta']['walk']
    assert w['asg']['efic'] == [1.0] * 5                # el ASG no mira la señal
    assert w['pz']['efic'][0] == 0.0 and w['pz']['efic'][-1] == 1.0
    assert w['pendiente']['efic'][0] == 0.0
    # la pendiente dispara más tarde con un pulso chico que con uno grande: del disparo
    # al pico (t_subida, y el walk contra el ASG) hay menos
    wk = w['pendiente']['walk']
    assert wk['150'] < wk['5000'] - 2
    assert w['asg']['inl_fs'] < 1e-4                  # la aritmética del trapecio


def test_etapa_ruido(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'ruido', '--ruidos-sh', 'sin,6,3,1',
                    '--estimadores', 'forma0,forma2,pico', '--n-ruido', '300')
    assert rc == 0 and d['anomalias'] == []
    r = d['meta']['ruido']
    # la ganancia de ruido va como 1/√k: la forma de k = 64 promedia más que la de 8
    assert 0.1 < r['forma0']['ganancia_ruido'] < r['forma2']['ganancia_ruido'] < 0.8
    assert r['forma0']['sigma_sin_ruido'] < 0.2
    # la simulada recorta a ciclos_max: 100 pulsos de período 3000, todos en la línea
    assert all(p['n'] == 100 for p in r['forma0']['puntos'])


def test_etapa_forma_eps_es_la_fraccion_de_limpios(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'forma', '--ks-forma', '8,64',
                    '--tasas-forma', '3e5', '--n-min-forma', '400')
    assert rc == 0 and d['anomalias'] == []
    f = {x['k']: x for x in d['filas']}
    for x in f.values():
        assert x['eps'] == pytest.approx(x['limpios'], abs=0.02)
        assert x['rho'] == pytest.approx(x['n_in_hz'] * x['L'] / R.FS_HZ)
    assert f[64]['fwhm_rel'] < f[8]['fwhm_rel'] and f[64]['eps'] < f[8]['eps']
    assert set(d['referencias']) == {'forma/8', 'forma/64'}
    assert 'forma' in R.resumen(d['filas'], d['meta'])


def test_etapa_apilamiento(tmp_path):
    larga = R.PlacaSimulada(h_aw=13, ciclos_max=2_000_000)    # el continuo, con estadística
    rc, d = _correr(tmp_path, larga, '--etapas', 'apilamiento', '--tasas-apil', '5e5',
                    '--fuentes-apil', 'pz', '--cortes-dt', '100,400',
                    '--cuantiles-apil', '0.9', '--n-min', '400')
    assert rc == 0 and d['anomalias'] == []
    c = {(f['corte'], f['umbral']): f['meritos'] for f in d['filas']}
    sin = c[('sin', None)]
    assert sin['fondo'] > 0 and sin['rej_discr'] == 0
    # el corte por dt_anterior no pasa de lo que dejan los instantes
    for q in (100, 400):
        assert c[('dt_anterior', q)]['eps'] <= c[('dt_anterior', q)]['ideal']
    assert c[('dt_anterior', 400)]['eps'] < c[('dt_anterior', 100)]['eps'] < sin['eps']
    # con subida 0 el corte por t_subida se lleva la mayor parte del apilamiento
    assert c[('t_subida', 0.9)]['fondo'] < sin['fondo'] / 2
    f = next(x for x in d['filas'] if x['corte'] == 't_subida')
    cnt = f['corridas'][0]['cnt']
    # cnt_accepted cuenta antes del discriminador, como en el RTL
    assert cnt['rej_discr'] > 0
    assert cnt['accepted'] - cnt['rej_discr'] == f['meritos']['aceptados']


def test_el_discriminador_de_la_simulada(placa):
    gen = G.config(aleatorio=True, tasa=5e5, dt_min=2, n=4000, amp_aleat=True, semilla=3,
                   tau=250.0, subida=0, base=0, ruido=True, ruido_sh=6, salidas=G.SAL_OUT1)
    gen['n'] = placa.recortar(gen)
    tabla = R.tabla_lineas([500, 1300], [0.6, 0.4])
    mca = R.mca_de('pz', gen['decae'], 3)
    disp = R.disparo_de('pz', gen['decae'], 0)
    esp = [('dt_anterior', 3)]
    todo = placa.correr(gen, tabla, mca, disp, esp)['corridas'][0]
    dentro = placa.correr(gen, tabla, dict(mca, discr=('dt_anterior', 200, 0xFFFF)), disp,
                          esp)['corridas'][0]
    fuera = placa.correr(gen, tabla, dict(mca, discr=('dt_anterior', 200, 0xFFFF, True)), disp,
                         esp)['corridas'][0]
    n = todo['cnt']['accepted']
    # cnt_accepted cuenta en el publicador, antes del discriminador (mca_top.sv)
    assert dentro['cnt']['accepted'] == fuera['cnt']['accepted'] == n
    assert dentro['hist'].sum() + dentro['cnt']['rej_discr'] == n
    assert dentro['hist'].sum() + fuera['hist'].sum() == n
    assert dentro['hist'][:200].sum() == 0 and fuera['hist'][200:].sum() == 0
    assert np.array_equal(dentro['hist'] + fuera['hist'], todo['hist'])


def test_etapa_dnl(tmp_path, placa):
    chica = R.PlacaSimulada(h_aw=13, ciclos_max=3_000_000)
    rc, d = _correr(tmp_path, chica, '--etapas', 'dnl', '--tandas-dnl', '2', '--seg-dnl', '0.02')
    assert rc == 0 and d['anomalias'] == []
    t, p = d['meta']['dnl']['trapecio'], d['meta']['dnl']['pico']
    # el lazo digital no tiene DNL: lo que queda es Poisson
    for x in (t, p):
        assert x['chi2'] == pytest.approx(1.0, abs=0.25)
    # el pico con zoom 1 es un código por canal: de 500 a 6000 cuentas
    assert p['canales'][0] < 800 and p['canales'][1] > 5600
    assert len(d['filas']) == 2 and d['filas'][0]['gen']['semilla'] != d['filas'][1]['gen']['semilla']


def test_etapa_psd(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'psd', '--amps-psd', '100,2000', '--n-psd', '200')
    assert rc == 0 and d['anomalias'] == []
    p = d['meta']['psd']
    assert p['2000']['fom'] > 3 * p['100']['fom'] > 0
    c = p['2000']['centroides']
    assert c[1] > c[0]                       # la caída más larga deja más carga en la cola


def test_etapa_polo_cero(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'polo_cero', '--dm-pz=-0.05,0,0.05',
                    '--dts-pz', '100', '--n-pares-pz', '40')
    assert rc == 0 and d['anomalias'] == []
    e = {f['dm']: f['err_a2'] for f in d['filas']}
    assert abs(e[0.0]) < 0.002                       # M exacta: A2 mide lo mismo que solo
    assert e[-0.05] > 0.005 and e[0.05] < -0.005     # M corta deja cola; larga, de menos
    assert all(abs(f['err_a1']) < 0.002 for f in d['filas'])
    an = d['meta']['polo_cero']['100']
    assert an['pendiente'] < 0 and abs(an['dm_cero']) < 0.005


def test_etapa_ventana_ciega(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'ventana_ciega', '--dts-ciega', '2,4,16',
                    '--subidas-ciega', '0', '--fuentes-ciega', 'pz', '--cuantiles-ciega', '0.9',
                    '--n-pares-ciega', '40')
    assert rc == 0 and d['anomalias'] == []
    m = {(f['dt'], f['corte']): f['meritos'] for f in d['filas']}
    # a 2 ciclos el polo-cero da un disparo: sin corte, el apilado pasa; con subida 0, el
    # corte por t_subida lo ve
    assert m[(2, 'sin')]['disparos_par'] == 1.0 and m[(2, 'sin')]['apilado_aceptado'] > 0.9
    assert m[(2, 't_subida')]['apilado_aceptado'] < 0.05 and m[(2, 't_subida')]['rechazados'] > 0.9
    assert m[(16, 'sin')]['disparos_par'] == 2.0
    an = d['meta']['ventana_ciega']
    assert an['0/pz/sin/None']['ciega_hasta'] == 4
    assert an['0/pz/t_subida/0.9']['ciega_hasta'] is None


def test_etapa_deriva_en_el_lazo_no_corre(tmp_path, placa):
    rc, d = _correr(tmp_path, placa, '--etapas', 'deriva', '--puntos-deriva', '3',
                    '--cada-deriva', '0', '--seg-deriva', '0.01')
    assert rc == 0 and d['anomalias'] == []
    assert [f['punto'] for f in d['filas']] == [0, 1, 2]
    de = d['meta']['deriva']
    assert de['puntos'] == 3
    for k in ('linea1', 'linea2', 'offset', 'ganancia_ppm'):
        assert de[k]['rango'] == 0.0
    v = [x['valor'] for x in d['filas'][0]['lineas']]
    assert v[1] / v[0] == pytest.approx(4000 / 1500, rel=0.005)


def test_tasa_con_el_seguidor_no_se_simula(tmp_path, placa, capsys):
    rc, d = _correr(tmp_path, placa, '--etapas', 'tasa', '--base-tasa', 'seguidor')
    assert rc == 0 and d['filas'] == []
    assert 'no se simula' in capsys.readouterr().out


def test_modo_analogico_simulado(tmp_path):
    placa = R.PlacaSimulada(h_aw=13, ciclos_max=300_000, modo='analogico',
                            canal=R.CA.CanalSimulado(ganancia=0.9, offset=-30.0))
    rc, d = _correr(tmp_path, placa, '--modo', 'analogico', '--etapas', 'tasa',
                    '--tasas', '1e4', '--fuentes', 'asg,pz', '--n-acc', '3', '--n-min', '50')
    assert rc == 0 and d['meta']['modo'] == 'analogico'
    c = d['meta']['canal']
    assert c['ganancia'] == pytest.approx(0.9, rel=0.02)
    assert c['offset'] == pytest.approx(-30.0, abs=0.5)
    for f in d['filas']:
        assert f['corridas'][0]['meritos']['frac_buenos'] > 0.95
    # la base del MCA es el offset de IN1, y con el ASG la ventana se corre lat_asg
    assert R.base_de(c) == round(c['offset'])
    assert R.mca_de('asg', 65274, 1, c)['pre_dly'] == max(0, R.PRE_DLY['asg'] - c['lat_asg'])


def test_modo_analogico_sin_canal_corta(tmp_path, capsys):
    placa = R.PlacaSimulada(h_aw=13, ciclos_max=300_000, modo='analogico',
                            canal=R.CA.CanalSimulado(ganancia=0.0))
    rc = R.main([str(tmp_path), '--simulada', *CORTO, '--modo', 'analogico', '--etapas', 'tasa'],
                placa=placa)
    assert rc == 3 and 'SIN CANAL' in capsys.readouterr().out


def test_canal_medido_va_con_la_simulada_analogica(tmp_path):
    for malo in ([str(tmp_path), '--canal-medido', 'canal.npz'],
                 [str(tmp_path), '--simulada', '--canal-medido', 'canal.npz'],
                 [str(tmp_path), '--simulada', '--modo', 'analogico', '--sin-lentos'],
                 [str(tmp_path), '--simulada', '--modo', 'analogico', '--canal-medido', 'c.npz',
                  '--canal-sim', 'ganancia=0.9']):
        with pytest.raises(SystemExit):
            R.parse_args(malo)
    a = R.parse_args([str(tmp_path), '--simulada', '--modo', 'analogico',
                      '--canal-medido', 'canal.npz', '--sin-lentos'])
    assert a.canal_medido == 'canal.npz' and a.sin_lentos


# =============================================================================
# La base dinámica en la etapa tasa (`--base-tasa dinamica`)
# =============================================================================

def test_la_base_dinamica_es_del_analogico(tmp_path):
    with pytest.raises(SystemExit):
        R.parse_args([str(tmp_path), '--simulada', '--base-tasa', 'dinamica'])
    with pytest.raises(SystemExit):
        R.parse_args([str(tmp_path), '--modo', 'analogico', '--base-tasa', 'dinamica',
                      '--calibracion', str(tmp_path / 'no_existe.json')])
    a = R.parse_args([str(tmp_path), '--modo', 'analogico', '--base-tasa', 'dinamica',
                      '--kappa', '0.8'])
    assert a.base_tasa == 'dinamica' and a.kappa == 0.8 and a.calibracion is None


def test_la_simulada_no_corre_la_dinamica(tmp_path, capsys):
    a = R.parse_args([str(tmp_path), '--simulada', '--modo', 'analogico', '--etapas',
                      'tasa', '--base-tasa', 'dinamica'])
    c = R.Campana.__new__(R.Campana)
    c.a, c.placa = a, type('P', (), {'nombre': 'simulada'})()
    assert c.etapa_tasa() is None
    assert 'no se simula' in capsys.readouterr().out


def _campana_con_canal(tmp_path, cal=None, kappa=None):
    args = [str(tmp_path), '--modo', 'analogico', '--base-tasa', 'dinamica']
    if cal is not None:
        p = tmp_path / 'cal.json'
        p.write_text(json.dumps(cal))
        args += ['--calibracion', str(p)]
    if kappa is not None:
        args += ['--kappa', str(kappa)]
    c = R.Campana.__new__(R.Campana)
    c.a = R.parse_args(args)
    c.canal = {'ganancia': 0.95, 'caida_lenta': -0.06}
    return c


def test_la_calibracion_de_la_dinamica(tmp_path):
    c = _campana_con_canal(tmp_path, cal={'caida': -0.0735, 'kappa': 0.75})
    cal = c.calibracion_dinamica()
    assert cal['caida'] == -0.0735 and cal['kappa'] == 0.75
    assert _campana_con_canal(tmp_path, cal={'caida': -0.07}, kappa=1.2) \
        .calibracion_dinamica()['kappa'] == 1.2
    # Sin el .json, la caída de la medición rápida de la corrida.
    sin = _campana_con_canal(tmp_path).calibracion_dinamica()
    assert sin['caida'] == -0.06 and sin['kappa'] == 1.0
    # --caida manda sobre el .json.
    c = _campana_con_canal(tmp_path, cal={'caida': -0.07})
    c.a.caida = -0.05
    assert c.calibracion_dinamica()['caida'] == -0.05


def test_g_f_y_el_cebado_de_la_dinamica(tmp_path):
    """G_F es la ganancia de la referencia (feature por ADU del generador) sobre la del
    canal; el cebado, la tasa de la config y la amplitud media de la tabla en IN1."""
    c = _campana_con_canal(tmp_path, cal={'caida': -0.07})
    ref = {'trapecio': {'ganancia': [3.8, 3.9]}, 't_subida': {'ganancia': None}}
    gen = G.config(aleatorio=True, tasa=400e3, dt_min=2, n=1000, amp_aleat=True,
                   tau=250.0)
    tabla = np.array([500] * 512 + [1300] * 512, np.int16)
    d = c.dinamica_de(ref, gen, tabla, c.calibracion_dinamica())
    assert d['ganancia_mca']['trapecio'] == pytest.approx(3.85 / 0.95)
    assert d['ganancia_mca']['t_subida'] == 1.0
    assert d['a0'] == pytest.approx(900 * 0.95)
    assert d['lam0'] == pytest.approx(G.tasa(**R.disparos_cfg(gen)))


class _MCAFalso:
    """Lo que `_esperar_con_ley` le pide al MCA: contadores que avanzan a λ, un
    histograma con la línea en un canal, trap_mq y la base escrita."""

    def __init__(self, lam, canal, h_aw=13):
        self.lam, self.canal = lam, canal
        self.t = 0.0
        self.hist = np.zeros(1 << h_aw, np.int64)
        self.bases = []

    def mca_get_trap_mq(self, h):
        return 3992

    def mca_read_counters(self, h):
        self.t += 0.25
        self.hist[self.canal] += int(self.lam * 0.25)
        return {'cross': int(self.lam * self.t), 'lost_veto': 0, 'realtime_s': self.t,
                'vetotime_s': 0.0, 't_rearm_s': 0.0}

    def mca_read_histogram(self, h):
        return self.hist.copy()

    def mca_set_baseline(self, h, v):
        self.bases.append(int(v))


def test_el_lazo_de_la_placa_escribe_la_base(monkeypatch):
    """`PlacaReal._esperar_con_ley` sin la placa: un paso por período hasta que el
    generador termina, con la base escrita en cada uno."""
    from API import base_dinamica as BD
    monkeypatch.setattr(R, 'PASO_BASE_S', 0.0)
    M = _MCAFalso(400e3, 2000)
    estados = iter([{'terminado': False}] * 5 + [{'terminado': True, 'gen_cnt': 9,
                                                   'desborde': False}])
    p = R.PlacaReal.__new__(R.PlacaReal)
    p.M, p.h, p.h_aw = M, None, 13
    p.g = type('G', (), {'estado': lambda self: next(estados)})()
    mca = {'baseline': -12, 'trap_mq': 3992}
    v = BD.valores_de_canales(1 << 13, 13)
    gf = 4.0
    din = dict(caida=-0.07, ganancia_mca={'trapecio': gf}, kappa=1.0, lam0=400e3,
               a0=v[2000] / gf)
    ley = p._ley(mca, din, 'trapecio')
    esperado = -0.07 * (400e3 / 125e6) * (v[2000] / gf) * 250.0
    assert ley.base() == round(-12 + esperado)        # cebada: bien desde el principio
    est, pasos = p._esperar_con_ley(ley, 0, plazo=10.0)
    assert est['terminado'] and len(pasos) == 6
    assert M.bases == [p_['base'] for p_ in pasos]
    assert pasos[-1]['delta_b'] == pytest.approx(esperado, rel=1e-3)
    assert pasos[-1]['lam_hz'] == pytest.approx(400e3, rel=1e-3)
    # Con t_subida, ⟨A⟩ queda en el cebado.
    assert p._ley(mca, dict(din, ganancia_mca={'t_subida': 1.0}), 't_subida').fijar_a


def test_la_linea_dice_el_delta_b():
    c = {'base_dinamica': {'pasos': [{'delta_b': -40.0}, {'delta_b': -44.0}]}}
    assert R._txt_dinamica(c) == ', Δb -42.0 ADU'
    assert R._txt_dinamica({}) == ''
