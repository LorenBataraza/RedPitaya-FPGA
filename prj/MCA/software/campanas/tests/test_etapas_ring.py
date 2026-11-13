"""`campanas/run_etapas_ring.py` sin placa: el modelo, la verificación de archivos y las
cuatro etapas contra un ring falso con el generador.

`RingGen` es el ring simulado de la API con el generador (`API/ring_falso.py`,
`RingFalsoGen`): al arrancar con GEN_CTRL.EN dispara las marcas de `predecir` a medida
que pasa el tiempo (`paso` ciclos por cada lectura de WR_SLOT), descarta por captura
ocupada con el tiempo muerto de la placa (escrito allá, no tomado del modelo del
script) y por ring lleno, y escribe cada slot como el RTL con
el patrón. Contra él, lo que se prueba es la plomería del script (que compare los
números que tiene que comparar); el modelo se prueba contra la placa y contra la
simulación del RTL.
"""
import json
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
sys.path.insert(0, os.path.dirname(_AQUI))                  # campanas/

import API.generadores as G                                          # noqa: E402
import API.osciloscope_ring as OR                                    # noqa: E402
import run_etapas_ring as R                                          # noqa: E402
from API.ring_falso import RingFalso                                 # noqa: E402
from API.ring_falso import RingFalsoGen as RingGen                   # noqa: E402

GEOMETRIAS = os.path.join(os.path.dirname(_RAIZ), 'docs', 'event_ring', 'figuras',
                          'tiempos', 'geometrias.txt')


def args(tmp_path, *extra):
    return R.parse_args([str(tmp_path), '--n', '3000', '--seg-max', '0', *extra])


def punto(rf, etapa, modo, tasa, tmp_path, *extra, pre=8, post=24):
    a = args(tmp_path, *extra)
    ring = rf.handle()
    try:
        sh = OR.geometria(pre, post)['slot_shift']
        return R.medir_punto(ring, etapa, pre, post, sh, modo, tasa, a,
                             str(tmp_path / 'c'))
    finally:
        ring.close()


# -----------------------------------------------------------------------------
# El modelo
# -----------------------------------------------------------------------------

def test_el_tiempo_muerto_da_lo_que_dio_la_placa():
    """C2 de test_generadores_placa.py, el 2026-11-09: 100 000 disparos aleatorios a
    3 MHz, 59 762 por DROP_BUSY y 1 por DROP_FULL."""
    assert R.muerto_captura(8, 24) == 67
    d = G.disparos(aleatorio=True, tasa=3e6, dt_min=5, n=100_000, semilla=7)
    busy, marcas = R.modelo(d, 8, 24)
    assert busy == 59_762
    assert marcas.size == 100_000


@pytest.mark.parametrize('periodo', [34, 40, 66, 67, 68, 125, 1000])
def test_el_periodico_tiene_formula(periodo):
    d = G.disparos(periodo=periodo, n=2000)
    marcas = R.marcas_periodico(np.arange(2000), periodo)
    np.testing.assert_array_equal(marcas, G.predecir(10 ** 7, OR.GEN_LAT_TS, **d))
    busy, nada = R.modelo(d, 8, 24)
    assert nada is None
    assert busy == R.descartes_captura(marcas, 67)
    assert (busy == 0) == (periodo >= 67)


def test_un_descarte_no_extiende_el_tiempo_muerto():
    # 0 entra, 60 no, 67 sí (a 67 del 0: el 60 no lo corrió), 120 no, 134 sí. Si el
    # descarte extendiera el tiempo muerto (paralizable), 67, 120 y 134 tampoco.
    assert R.descartes_captura([0, 60, 67, 120, 134], 67) == 2


def test_sin_modelo_si_predecir_cuesta_demasiado():
    d = G.disparos(aleatorio=True, tasa=1e4, n=1000)
    assert R.modelo(d, 8, 24, ciclos_max=1e6) == (None, None)
    assert R.modelo(d, 8, 24, n_max=999) == (None, None)


@pytest.mark.skipif(not os.path.isfile(GEOMETRIAS), reason='sin docs/ (en la placa)')
def test_los_techos_son_los_de_la_simulacion():
    sim = {}
    for ln in open(GEOMETRIAS):
        c = dict(x.split('=') for x in ln.split())
        sim[(int(c['pre']), int(c['post']))] = (int(c['shift']), int(c['captura']),
                                                int(c['writer']))
    assert sim == R.TECHO_SIM
    for (pre, post), (_, captura, _) in sim.items():
        assert captura == 2 * (pre + post) + 2 == R.muerto_captura(pre, post) - 1


def test_las_ventanas_y_los_puntos():
    a = R.parse_args(['x', '--ventanas', '8+24,16+479@12,100+28', '--tasas', '1e5',
                      '--etapas', 'A,B'])
    assert a.ventanas == [(8, 24, None), (16, 479, 12), (100, 28, None)]
    pts = list(R.puntos(a))
    # 8+24: el periódico suma los períodos 86 y 88 del techo del writer
    per = sorted({round(125e6 / t) for p, q, sh, m, t, e in pts
                  if (p, q, m) == (8, 24, 'periodico')})
    assert per == [86, 88, 1250]
    assert {e for *_, e in pts} == {'A', 'B'}
    assert (100, 28, OR.geometria(100, 28)['slot_shift']) in {p[:3] for p in pts}
    with pytest.raises(SystemExit):
        R.parse_args(['x', '--etapas', 'A,D'])


# -----------------------------------------------------------------------------
# La verificación en numpy (la de la etapa C)
# -----------------------------------------------------------------------------

def _eventos(d, ks, marcas, pre=8, post=24):
    ts = marcas[ks]
    return dict(ts_hw=ts.copy(), snap=(OR.GEN_SNAP_MARCA | (np.asarray(ks) & 0xFFFF)
                                       ).astype(np.uint32),
                seq=np.arange(len(ks), dtype=np.uint32),
                wave=OR.patron_gen(ts, pre, pre + post))


@pytest.mark.parametrize('con_marcas', [True, False])
def test_verificar_eventos_con_descartes(con_marcas):
    d = G.disparos(aleatorio=True, tasa=3e6, dt_min=5, n=500, semilla=3)
    marcas = G.predecir(10 ** 6, OR.GEN_LAT_TS, **d)
    ks = np.array([k for k in range(500) if k % 3 and k < 480])
    v = R._cero_verif()
    c = _eventos(d, ks, marcas)
    # de a dos lotes, como dos archivos
    for sl in (slice(0, 100), slice(100, None)):
        R.verificar_eventos(v, {n: a[sl] for n, a in c.items()}, d, 8, 24,
                            marcas if con_marcas else None)
    assert v['eventos'] == ks.size
    assert sum(v[e] for e in ('err_seq', 'err_marca', 'err_k', 'err_ts', 'err_patron')) == 0
    perdidos = 500 - ks.size
    assert v['k_saltos'] + (500 - 1 - v['k_ultimo']) == perdidos


@pytest.mark.parametrize('rompe, error', [
    ('marca', 'err_marca'), ('ts', 'err_ts'), ('k', 'err_k'), ('patron', 'err_patron'),
    ('seq', 'err_seq'),
])
@pytest.mark.parametrize('modo', ['periodico', 'aleatorio'])
def test_verificar_eventos_ve_cada_error(modo, rompe, error):
    d = (G.disparos(periodo=200, n=50) if modo == 'periodico'
         else G.disparos(aleatorio=True, tasa=1e6, dt_min=5, n=50, semilla=1))
    marcas = G.predecir(10 ** 6, OR.GEN_LAT_TS, **d)
    c = _eventos(d, np.arange(50), marcas)
    i = 17
    if rompe == 'marca':
        c['snap'][i] &= ~np.uint32(OR.GEN_SNAP_MARCA)
    elif rompe == 'ts':
        c['ts_hw'][i] += 1
        c['wave'][i] = OR.patron_gen(c['ts_hw'][i], 8, 32)   # el patrón de esa marca
    elif rompe == 'k':
        c['snap'][i] = OR.GEN_SNAP_MARCA | 30
    elif rompe == 'patron':
        c['wave'][i, 1, 20] ^= 4
    else:
        c['seq'][i:] += 1
    v = R.verificar_eventos(R._cero_verif(), c, d, 8, 24,
                            marcas if modo == 'aleatorio' else None)
    assert v[error] >= 1, v
    assert v['primer_error_seq'] is not None
    if rompe == 'patron':
        assert v['muestras_malas'] == 1


def test_verificar_sin_marcas_pasa_la_vuelta_de_16_bits():
    """Sin las marcas del motor (N demasiado grande para predecirlas) k sale del k16
    del snapshot, desenrollado como en C, y tiene que cruzar 65 536 con descartes."""
    n = 70_000
    d = G.disparos(aleatorio=True, tasa=3e6, dt_min=5, n=n, semilla=1)
    marcas = G.predecir(10 ** 7, OR.GEN_LAT_TS, **d)
    ks = np.array([k for k in range(n) if not 65_530 <= k < 65_545 and k % 1000])
    c = _eventos(d, ks, marcas)
    v = R._cero_verif()
    for i in range(0, ks.size, 20_000):              # varios archivos
        R.verificar_eventos(v, {x: a[i:i + 20_000] for x, a in c.items()}, d, 8, 24)
    assert sum(v[e] for e in R.ERRORES_ARCHIVO) == 0, v
    assert v['k_ultimo'] == n - 1
    assert v['k_saltos'] == n - ks.size


def test_verificar_no_mira_lo_de_antes_del_arranque():
    d = G.disparos(aleatorio=True, tasa=3e6, dt_min=5, n=20, semilla=7)
    marcas = G.predecir(10 ** 5, OR.GEN_LAT_TS, **d)
    c = _eventos(d, np.arange(20), marcas)
    assert c['ts_hw'][0] < 8                       # dispara en ts = 2
    c['wave'][0, :, :8 - c['ts_hw'][0]] = 1234     # el pre-trigger viejo
    v = R.verificar_eventos(R._cero_verif(), c, d, 8, 24, marcas)
    assert v['err_patron'] == 0


# -----------------------------------------------------------------------------
# Las etapas contra el ring falso
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('etapa', ['A', 'copia', 'B'])
@pytest.mark.parametrize('modo, tasa', [('periodico', 1e6), ('aleatorio', 3e6)])
def test_etapas_del_lector(tmp_path, etapa, modo, tasa):
    f = punto(RingGen(), etapa, modo, tasa, tmp_path)
    assert f['anomalias'] == [] and f['pasa'], f
    assert f['gen_cnt'] == f['n'] == 3000
    assert f['consumidos'] == f['ev_cnt'] == 3000 - f['drop_busy']
    assert f['drop_busy'] == f['busy_predicho']
    assert (f['drop_busy'] > 0) == (modo == 'aleatorio')
    assert f['drop_full'] == 0
    assert f['sin_perdidas'] == (modo == 'periodico')
    assert (f['bytes'] == 0) == (etapa == 'A')
    if etapa == 'B':
        assert f['errores'] == 0
        assert f['k_saltos'] + (f['n'] - 1 - f['k_ultimo']) == f['drop_busy']


def test_ring_lleno_es_drop_full_y_no_anomalia(tmp_path):
    """Muchos disparos por sondeo en un ring de 16 slots: lo que no entra es
    DROP_FULL. Es lo que se mide, no una falla; DROP_BUSY ya no se compara (un
    descarte por lleno no abre ventana)."""
    rf = RingGen(paso=40_000, ddr_bytes=16 * 256)
    f = punto(rf, 'B', 'periodico', 1e6, tmp_path)
    assert f['drop_full'] > 0
    assert f['anomalias'] == [] and f['pasa'] and not f['sin_perdidas']
    assert f['ev_cnt'] + f['drop_full'] == 3000


def test_una_captura_que_no_es_la_del_modelo_es_anomalia(tmp_path):
    f = punto(RingGen(muerto_mas=1), 'A', 'aleatorio', 3e6, tmp_path)
    assert f['drop_full'] == 0 and f['drop_busy'] > f['busy_predicho']
    assert f['anomalias'] == ['DROP_BUSY distinto del tiempo muerto de la captura']


def test_un_punto_que_vence_para_el_ring_y_apaga_el_generador():
    rf = RingGen()
    ring = rf.handle()
    d = G.disparos(periodo=12_500, n=3000)                 # 10 kHz: 0.3 s de estímulo
    m, e, k, _, vencido = R.correr_medida(ring, d, 8, 24, 'creditos', plazo_s=0.0,
                                          sondeo_s=0.01)
    assert vencido and not e['terminado'] and m['eventos'] < 3000
    assert rf.gst == 0 and rf.reg[OR.R_GEN_CTRL] == 0
    ring.close()


def test_destrabar_un_ring_que_no_para():
    """Con slots sin devolver, `parar` no termina (la ventana en vuelo espera un
    crédito): `destrabar` los devuelve y para."""
    rf = RingGen(trabado=True)
    ring = rf.handle()
    lec = OR.LectorRing(ring, 8, 24, 2, [R.IDENTIDAD] * 2)
    lec.configurar()
    ring.correr()
    for _ in range(5):
        rf.disparar(snap=OR.GEN_SNAP_MARCA)
    with pytest.raises(TimeoutError):
        ring.parar(timeout_s=0.05)
    R.destrabar(ring, lec)
    assert rf.gst == 0
    ring.close()


def _trabado_con_5():
    rf = RingGen(trabado=True)
    ring = rf.handle()
    lec = OR.LectorRing(ring, 8, 24, 2, [R.IDENTIDAD] * 2)
    lec.configurar()
    ring.correr()
    for _ in range(5):
        rf.disparar(snap=OR.GEN_SNAP_MARCA)
    lec.medir('creditos', time.perf_counter_ns() + 5_000_000)      # next = 5
    for _ in range(3):
        rf.disparar(snap=OR.GEN_SNAP_MARCA)
    with pytest.raises(TimeoutError):
        ring.parar(timeout_s=0.05)
    return rf, ring, lec


def test_destrabar_un_ring_que_paro_entre_medio():
    """Lo de la placa (2026-11-12, /dev/shm): el ring terminó de parar después del
    `parar` vencido, con WR_SLOT de vuelta en 0, y `medir` daba 2^32 slots llenos."""
    rf, ring, lec = _trabado_con_5()
    rf._parado()                                   # WR_SLOT = 0, parado
    R.destrabar(ring, lec)
    assert rf.gst == 0
    ring.close()


def test_destrabar_con_clr_si_los_creditos_no_alcanzan():
    rf, ring, lec = _trabado_con_5()
    rf.wr = 0                                      # drenando, y WR_SLOT ya en 0
    R.destrabar(ring, lec)
    assert rf.gst == 0
    assert (OR.R_CTRL, 0x2) in [(o, v) for q, o, v in rf.log if q == 'ring']
    ring.close()


def _fila_buena():
    # 8 + 2 descartes; k_saltos + (N - 1 - k_ultimo) = 7 + 3 = 10.
    return dict(vencido=False, terminado=True, n=100, gen_cnt=100, ev_cnt=90,
                drop_busy=8, drop_full=2, consumidos=90, busy_predicho=None,
                errores=0, k_saltos=7, k_ultimo=96)


@pytest.mark.parametrize('cambio, motivo', [
    (dict(vencido=True), 'venció el plazo'),
    (dict(terminado=False), 'el generador no llegó a N'),
    (dict(n=101), 'el generador no llegó a N'),
    (dict(ev_cnt=91, consumidos=91), 'EV_CNT + descartes != GEN_CNT'),
    (dict(consumidos=89), 'no se consumió todo lo escrito'),
    (dict(escritos=89), 'el escritor no guardó todo lo escrito'),
    (dict(eventos_en_archivos=89), 'los archivos no tienen todo lo escrito'),
    (dict(errores=1), 'errores en los slots'),
    (dict(error_sesion='lector: x'), 'se cayó un hilo de la sesión'),
    (dict(drop_full=0, drop_busy=10, busy_predicho=9),
     'DROP_BUSY distinto del tiempo muerto de la captura'),
    (dict(k_saltos=6), 'los k que faltan no son los descartados'),
])
def test_anomalias_cada_regla(cambio, motivo):
    assert R.anomalias(_fila_buena()) == []
    assert R.anomalias(_fila_buena() | dict(drop_full=0, drop_busy=10,
                                            busy_predicho=10)) == []
    assert R.anomalias(_fila_buena() | cambio) == [motivo]


def _fila_b(tasa, ocup, trabajo, full, lee):
    return dict(etapa='B', pre=8, post=24, modo='periodico', tasa=tasa, n=200_000,
                n_slots=131_072, ocupacion_max=ocup, trabajo=trabajo, drop_full=full,
                sin_perdidas=full == 0, tasa_consumo=lee, anomalias=[],
                techo_captura_hz=125e6 / 67, techo_writer_sim_hz=125e6 / 88)


def test_sin_perdidas_con_el_ring_casi_lleno_no_es_techo():
    """Lo de la placa (2026-11-12): B a 1 M/s no perdió porque el ring absorbió el
    atraso de 0.2 s, con 124 992 slots ocupados. El techo es 300 k/s, y lo que lee
    saturado, 439 k/s."""
    filas = [_fila_b(3e5, 203, 0.88, 0, 3e5), _fila_b(1e6, 124_992, 0.99, 0, 4.39e5),
             _fila_b(125e6 / 88, 130_819, 0.99, 16_956, 4.3e5)]
    assert [R.saturado(f) for f in filas] == [False, True, True]
    assert '   300.0 /   1420.5 k/s   pasa   439.0 k/s' in R.resumen(filas)
    # En C no hay ocupación: saturado si la sesión leyó más lento de lo que se
    # escribía (en la placa, C a 300 k/s con 32 muestras leyó a 156 k/s sin perder)
    c = dict(n=200_000, tasa=3e5, ev_cnt=200_000)
    assert R.saturado(c | dict(tasa_consumo=1.556e5))
    assert not R.saturado(c | dict(tasa_consumo=2.8e5))
    assert R.saturado(c | dict(tasa_consumo=2.8e5, drop_full=1))


def test_un_punto_largo_con_un_atraso_pasajero_esta_al_dia():
    """Lo de la placa (2026-11-12): A a 1.4 M/s con 10⁸ disparos y `--carga 2` leyó a
    la tasa del estímulo, pero el ARM ocupado lo demoró 30 ms una vez: 42 191 slots.
    Es al día. En un punto corto, la misma ocupación es un lector que no da abasto."""
    largo = _fila_b(1.4e6, 42_191, 0.50, 0, 1.4e6) | dict(etapa='A', n=100_000_000)
    assert not R.saturado(largo)
    assert '  1404.5 /        - k/s' in R.resumen([largo | dict(tasa=1404494.38)])
    assert R.saturado(largo | dict(n=200_000))
    # el lector lento de un punto largo sigue saturado
    assert R.saturado(largo | dict(ocupacion_max=131_072, trabajo=0.99))


def test_resumen_desde_el_json(tmp_path, capsys):
    json.dump(dict(meta={}, puntos=[_fila_b(3e5, 203, 0.88, 0, 3e5)]),
              open(tmp_path / 'etapas_ring.json', 'w'))
    assert R.main([str(tmp_path), '--resumen']) == 0
    assert '300.0 /        - k/s' in capsys.readouterr().out


def test_con_drop_full_el_busy_no_se_compara():
    f = _fila_buena() | dict(busy_predicho=3)            # drop_full = 2
    assert R.anomalias(f) == []


def test_b_cuenta_un_slot_corrupto(tmp_path):
    f = punto(RingGen(corromper={5}), 'B', 'periodico', 1e6, tmp_path)
    assert (f['err_patron'], f['muestras_malas'], f['errores']) == (1, 1, 1)
    assert f['anomalias'] == ['errores en los slots'] and not f['pasa']


@pytest.mark.parametrize('formato', ['npz', 'lh5'])
def test_etapa_c_escribe_y_verifica(tmp_path, formato):
    if formato == 'lh5':
        pytest.importorskip('h5py')
    f = punto(RingGen(), 'C', 'aleatorio', 3e6, tmp_path, '--formato', formato,
              '--chunk', '1024')
    assert f['anomalias'] == [] and f['pasa'], f
    assert f['escritos'] == f['eventos_en_archivos'] == f['ev_cnt'] > 0
    assert f['drop_busy'] == f['busy_predicho'] > 0
    assert f['errores'] == 0 and f['chunks'] >= 2
    assert not os.listdir(tmp_path / 'c'), 'sin --guardar los archivos se borran'


def test_etapa_c_espera_al_lector_despues_del_generador(tmp_path, monkeypatch):
    """El generador termina mucho antes de que el lector alcance: la sesión no se corta
    al ver el fin del motor, sino cuando se leyó todo lo escrito."""
    leer = OR.LectorRing.leer

    def lento(self, cols, i0, n_max, plazo_ns):
        time.sleep(0.002)
        return leer(self, cols, i0, min(n_max, 25), plazo_ns)
    monkeypatch.setattr(OR.LectorRing, 'leer', lento)
    rf = RingGen(paso=100_000, ddr_bytes=1 << 20)    # 800 disparos por sondeo
    f = punto(rf, 'C', 'periodico', 1e6, tmp_path)
    assert f['anomalias'] == [] and f['consumidos'] == f['ev_cnt'] == 3000, f


def test_etapa_c_ve_un_slot_corrupto_en_el_archivo(tmp_path):
    f = punto(RingGen(corromper={11}), 'C', 'periodico', 1e6, tmp_path, '--guardar')
    assert (f['err_patron'], f['errores']) == (1, 1)
    assert f['primer_error_seq'] == 11
    assert 'errores en los slots' in f['anomalias']
    assert os.listdir(tmp_path / 'c'), 'con --guardar quedan'


def test_etapa_c_que_no_entra_en_el_disco_se_saltea(tmp_path, monkeypatch, capsys):
    # 150 MB libres: entran los 7 MB, pero no con los 200 de margen del escritor
    monkeypatch.setattr(R, 'free_space_mb', lambda path: 150.0)
    rc = R.main([str(tmp_path), '--etapas', 'A,C', '--ventanas', '8+24', '--tasas', '1e6',
                 '--modos', 'periodico', '--n', '50000', '--seg-max', '0', '--sin-techo'],
                abrir_ring=lambda: RingGen(paso=20_000).handle())
    assert rc == 0
    res = json.load(open(tmp_path / 'etapas_ring.json'))
    assert [p['etapa'] for p in res['puntos']] == ['A']
    # 50 000 eventos de 157 B (32 muestras × 2 canales × 2 B, más 29 de columnas)
    assert 'SALTEADO (la etapa C escribiría hasta 7 MB' in capsys.readouterr().out


def test_el_margen_va_a_la_guarda_y_al_escritor(tmp_path, monkeypatch):
    """Lo de la placa (2026-11-12): /dev/shm tiene 231 MB y el escritor paraba solo
    por debajo de 200. Con --margen-mb 50 y 150 MB libres, el punto corre entero."""
    from API.osciloscope_store import storage
    monkeypatch.setattr(R, 'free_space_mb', lambda path: 150.0)
    monkeypatch.setattr(storage, 'free_space_mb', lambda path: 150.0)
    f = punto(RingGen(), 'C', 'periodico', 1e6, tmp_path, '--margen-mb', '50',
              '--chunk', '256')
    assert f['anomalias'] == [] and f['escritos'] == 3000, f


def test_main_de_punta_a_punta(tmp_path):
    rc = R.main([str(tmp_path), '--etapas', 'A,B,C', '--ventanas', '8+24,16+112',
                 '--tasas', '1e6', '--n', '1500', '--seg-max', '0', '--sin-techo'],
                abrir_ring=lambda: RingGen().handle())
    assert rc == 0
    res = json.load(open(tmp_path / 'etapas_ring.json'))
    assert len(res['puntos']) == 2 * 2 * 3
    assert all(p['pasa'] for p in res['puntos'])
    assert res['meta']['libmca'] == OR._libmca.version()
    assert not os.path.exists(tmp_path / '_etapa_c')


def test_sin_el_generador_no_corre(tmp_path):
    rf = RingFalso()
    with pytest.raises(SystemExit, match='GEN1'):
        R.main([str(tmp_path), '--ventanas', '8+24', '--tasas', '1e6'],
               abrir_ring=rf.handle)


# -----------------------------------------------------------------------------
# La etapa C por la red: el servidor falso y un directorio que hace de montaje
# -----------------------------------------------------------------------------

def test_etapa_c_por_la_red(tmp_path):
    """La campaña en "la PC" y la sesión en "la placa" (`mca_server.py --fake`, con el
    ring simulado). En la placa `--destino` es el montaje (/mnt/pc/etapas) y
    `--destino-pc` el mismo directorio en la PC; acá son el mismo camino."""
    sys.path.insert(0, os.path.join(_RAIZ, 'app', 'tests'))
    from test_mca_remote import ServidorDePrueba

    dest = tmp_path / 'montaje'
    with ServidorDePrueba() as srv:
        rc = R.main([str(tmp_path / 'out'), '--etapas', 'C',
                     '--red', f'127.0.0.1:{srv.port}', '--destino', str(dest),
                     '--destino-pc', str(dest), '--ventanas', '8+24',
                     '--modos', 'periodico,aleatorio', '--tasas', '1e5', '--sin-techo',
                     '--n', '3000', '--seg-max', '0', '--guardar'])
        log = ''.join(srv.salida)
    assert rc == 0
    j = json.load(open(tmp_path / 'out' / 'etapas_ring.json'))
    filas = j['puntos']
    assert [f['modo'] for f in filas] == ['periodico', 'aleatorio']
    for f in filas:
        assert f['pasa'] and f['anomalias'] == [] and f['errores'] == 0
        assert f['fs'] and f['eventos_en_archivos'] == f['ev_cnt'] == f['consumidos']
        assert f['gen_cnt'] == 3000
    assert filas[1]['drop_busy'] == filas[1]['busy_predicho']
    assert j['meta']['servidor'] == f'127.0.0.1:{srv.port}'
    assert 'ring: adquisición en ' + str(dest) in log
    # los archivos quedaron del lado de "la PC" (--guardar)
    assert sorted(os.listdir(dest)) == sorted(
        f'c_8_24_{m}_100000' for m in ('periodico', 'aleatorio'))


@pytest.mark.parametrize('extra, error', [
    (['--etapas', 'A,C'], 'sólo la etapa C'),
    (['--etapas', 'C', '--carga', '1'], 'no va con --red'),
    (['--etapas', 'C', '--destino', '/mnt/pc/e'], '--destino-pc'),
    (['--etapas', 'C', '--destino', 'rel/e', '--destino-pc', '/x'], 'absoluto'),
])
def test_los_argumentos_de_la_red(tmp_path, capsys, extra, error):
    with pytest.raises(SystemExit):
        R.parse_args([str(tmp_path), '--red', 'placa', *extra])
    assert error in capsys.readouterr().err


def test_destino_pc_sin_red(tmp_path, capsys):
    with pytest.raises(SystemExit):
        R.parse_args([str(tmp_path), '--etapas', 'C', '--destino-pc', '/x'])
    assert '--destino-pc va con --red' in capsys.readouterr().err


class _AdqFalsa:
    """Un ejecutor de `correr_sesion` que termina en el primer sondeo, con los errores
    que se le den: el del sondeo y el de `parar`."""

    def __init__(self, error_estado=None, error_parar=None):
        self.error_estado, self.error_parar = error_estado, error_parar

    def iniciar(self):
        return {'fs': 'nfs'}

    def estado(self):
        return dict(motivo='error' if self.error_estado else None,
                    error=self.error_estado, stats={'n_read': 5},
                    hw={'hw_ev_cnt': 5, 'hw_gen_terminado': True})

    def parar(self):
        return dict(stats={'n_read': 5}, hw_final={'hw_ev_cnt': 5}, n_slots=16,
                    error=self.error_parar)


@pytest.mark.parametrize('estado, parar, esperado', [
    (None, None, None),
    # lo que sólo dice parar (el ring que hubo que destrabar) no se pierde
    (None, 'parar no terminó: el ring estaba lleno (creditos)',
     'parar no terminó: el ring estaba lleno (creditos)'),
    # y lo que ya vio el sondeo no se repite
    ('escritor: OSError()', 'escritor: OSError(); parar no terminó: el ring estaba lleno (clr)',
     'escritor: OSError(); parar no terminó: el ring estaba lleno (clr)'),
])
def test_correr_sesion_junta_los_errores(estado, parar, esperado):
    st, fin, n_slots, vencido, error, fs = R.correr_sesion(
        _AdqFalsa(estado, parar), plazo_s=5, sondeo_s=0.001)
    assert (error, fs, n_slots, vencido) == (esperado, 'nfs', 16, False)
