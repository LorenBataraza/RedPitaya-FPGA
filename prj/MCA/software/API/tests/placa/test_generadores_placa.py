#!/usr/bin/env python3
"""Los dos generadores en la placa, por la API de libmca (`API/generadores.py` y el
generador del ring en `OsciloscopeRing`).

Necesita el bitstream del ring con los generadores (78e26188 o posterior,
`out/v3_event_ring/`). No usa el Rigol: todo el estímulo sale de la FPGA.

  A. gen_pulsos por la API: el MAGIC, configurar y releer, la tabla, el lazo digital
     (sin tocar digital_loop[1]), y la región de TOP (bit 6 de MODULES, el slot 2 y la
     base 0x4021_0000), con el ring todavía en 0x4020_0000.
  B. Los 4 bloques de tb_pulsos_mca por el lazo digital: el generador por la API, y el
     MCA y el multitrigger con las mismas escrituras del TB, en el tap ADC. Contra
     `monte-carlo/datos_ref/pulsos_placa_ref.json` (la réplica con la latencia del ASG
     del top): GEN_CNT, los 11 contadores, t_ocup y los espectros de F_PEAK y F_TRISE,
     canal por canal. Una corrida por espectro: el generador es determinista.
  C. gen_eventos en el ring, con el patrón:
       C1. periódico y lento: llegan los N, sin descartes, con seq consecutivo;
       C2. aleatorio y más rápido que la captura: se pierden por DROP_BUSY, y
           EV_CNT + DROP_BUSY + DROP_FULL = GEN_CNT.
     En los dos, cada slot que llega tiene la marca que predice el modelo para su
     índice (el snapshot {1, k}) y todas sus muestras son el patrón de esa marca,
     salvo las de antes del arranque: un disparo con ts < pre (C2 tiene uno en ts = 2)
     trae ahí lo que quedó en el buffer de pre-trigger de la corrida anterior.
  D. los modos de medida del lector (osciloscope_ring_medir: créditos, copia,
     verificar) con los casos de C y uno periódico a 1 MHz: en cada uno la cuenta
     cierra con lo que el lector consumió, y 'verificar' no encuentra errores y sus k
     que faltan son los descartados. Informa la tasa y cuánto se llenó el ring.

Uso (en la Pitaya, recién cargado el bitstream del ring):
    python3 API/tests/placa/test_generadores_placa.py [--salida res.json] [--solo A,B,C,D]
o `make verificar-placa-generadores`.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)

import API.generadores as G                                          # noqa: E402
import API.osciloscope_ring as OR                                    # noqa: E402
from API._libmca import Bus                                          # noqa: E402
from API.integration import (TAP_ADC, integration_close,            # noqa: E402
                             integration_get_base, integration_get_modules,
                             integration_get_slots, integration_open,
                             integration_reset_routes, integration_set_route_mca,
                             integration_set_route_mtrg)
from API.multitrigger import (MtRegion, multitrigger_armar_mca,      # noqa: E402
                              multitrigger_desarmar_mca)
from API.osciloscope import R_DEB_LEN, osciloscope_close, osciloscope_open  # noqa: E402
from test_mca2_placa import MCA2                                     # noqa: E402

DATOS_REF = os.path.join(_RAIZ, 'monte-carlo', 'datos_ref')
ESTIMULO = os.path.join(DATOS_REF, 'pulsos_estimulo.txt')
REF_PLACA = os.path.join(DATOS_REF, 'pulsos_placa_ref.json')
F_PEAK, F_TRISE = 0, 5                       # docs/mca/register_map_mca.md
DEB_LEN_RESET = 62500
IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}

_pass = _fail = 0


def check(nombre, cond, extra=''):
    global _pass, _fail
    print(f'  [{"PASS" if cond else "FAIL"}] {nombre}'
          f'{("  " + str(extra)) if extra != "" else ""}', flush=True)
    if cond:
        _pass += 1
    else:
        _fail += 1
    return cond


# =============================================================================
# A. gen_pulsos por la API
# =============================================================================

def parte_a(g, ig):
    print('\n[A] gen_pulsos por la API')
    check('MAGIC = "PUL1"', g.r32(G.R_MAGIC) == G.MAGIC, f'{g.r32(G.R_MAGIC):#010x}')

    cfg = g.configurar(aleatorio=True, tasa=600e3, dt_min=3, n=300, semilla=44,
                       amp_aleat=True, tau=250.0, subida=2, amp_n=200, base=-100,
                       ruido=True, ruido_sh=4, salidas=G.SAL_OUT1 | G.SAL_OUT2)
    check('configurar y releer', g.leer_config() == cfg, g.leer_config())
    g.configurar()
    check('la configuración por defecto', g.leer_config() == G.config() | {'amp_n': 1024})

    pat = (np.arange(G.N_TABLA) * 37 + 11) % 16384
    pat = np.where(pat >= 8192, pat - 16384, pat)
    g.cargar_tabla(pat)
    check('la tabla: 1024 entradas con signo', np.array_equal(g.leer_tabla(), pat))
    g.cargar_tabla([])
    check('la tabla vacía queda en cero', not g.leer_tabla().any())

    hk = Bus.devmem(G.HK_PHYS, G.HK_SIZE)
    try:
        antes = hk.r32(G.HK_LAZO)
        g.lazo = True
        con = hk.r32(G.HK_LAZO)
        g.lazo = False
        sin = hk.r32(G.HK_LAZO)
        check('el lazo digital: sólo digital_loop[0]',
              con == (antes | 1) and sin == (antes & ~1) and not g.lazo,
              f'antes {antes:#x}, con {con:#x}, sin {sin:#x}')
    finally:
        hk.close()

    mods, slots = integration_get_modules(ig), integration_get_slots(ig)
    check('MODULES: el generador de pulsos', mods['pulsos'], mods)
    check('SLOTS: el slot 2', slots['pulsos'] == 2, slots)
    base = integration_get_base(ig, 'pulsos')
    check('la base 0x4021_0000', base == G.PHYS, f'{base:#x}')
    ring = Bus.devmem(OR.RING_PHYS, OR.RING_SIZE)
    try:
        g.w32(G.R_PERIODO, 777)
        check('el ring sigue en 0x4020_0000, con su generador',
              ring.r32(OR.R_MAGIC) == OR.MAGIC and ring.r32(OR.R_GEN_MAGIC) == OR.GEN_MAGIC
              and g.r32(G.R_PERIODO) == 777)
    finally:
        ring.close()
    g.configurar()


# =============================================================================
# B. Los bloques de tb_pulsos_mca
# =============================================================================

_CLAVES_G = ('aleatorio', 'periodo', 'umbral', 'dt_min', 'n', 'semilla', 'amp_aleat',
             'amp_n', 'decae', 'subida', 'base', 'ruido', 'ruido_sh')


def leer_estimulo(path=ESTIMULO):
    """[(línea B, kw del generador, asg, tabla)], como los lee el TB."""
    tok = open(path).read().split()
    i, out = 0, []
    while tok[i] != 'FIN':
        assert tok[i] == 'B', tok[i]
        b = [int(x) for x in tok[i + 1:i + 50]]
        i += 50
        assert tok[i] == 'G', tok[i]
        gg = [int(x) for x in tok[i + 1:i + 17]]
        i += 17
        n_tab = gg[14]
        tab = [int(x, 16) for x in tok[i:i + n_tab]]
        i += n_tab
        out.append((b, dict(zip(_CLAVES_G, gg[1:14])), bool(gg[0]),
                    [t - 0x4000 if t >= 0x2000 else t for t in tab]))
    return out


def armar_mca(m, mtr, osc, b, asg):
    """El MCA y el disparo con las escrituras del TB (las mismas de 2026-11-09)."""
    (na, gs, gl, pre, asrc, qsh, amin, amax, L, G_, thr, hyst,
     tk, tm, tmq, toff, tlw, tsh) = b[:18]
    nf, an0, de0 = b[18:21]
    fm = b[21:42]
    pz, pzk, pzm, pzmq, pzsh, pzthr, pzhyst = b[42:49]
    m.stop()
    for o, v in ((0x020, 0), (0x01C, 0), (0x030, amin), (0x034, amax),
                 (0x038, (qsh << 8) | asrc), (0x04C, (gl << 16) | gs), (0x120, na),
                 (0x124, pre), (0x128, (tm << 16) | tk), (0x12C, tmq),
                 (0x130, (tsh << 24) | (tlw << 16) | toff), (0x188, (de0 << 16) | an0)):
        m.w32(o, v)
    for f in range(1, 4):
        q = 7 * (f - 1)
        m.w32(0x180 + 16 * f, (fm[q + 1] << 16) | fm[q])
        m.w32(0x184 + 16 * f, (fm[q + 4] << 24) | (fm[q + 3] << 16) | fm[q + 2])
        m.w32(0x188 + 16 * f, (fm[q + 6] << 16) | fm[q + 5])
    m.w32(0x134, nf)
    multitrigger_armar_mca(osc, mtr, ch=0)        # osc continuo, we_keep, shield
    mtr.w32(0x040, 0)
    mtr.w32(0x010, 0x0000_0101)
    if asg:
        osc.w32(R_DEB_LEN, 0)                     # rp_ext_trig también filtra el ASG
        mtr.w32(0x040, 0x0000_0800)
        return 'ASG'
    if pz:
        mtr.w32(0x0B0, pzthr)
        mtr.w32(0x0C0, pzhyst)
        mtr.w32(0x0A0, pzmq)
        mtr.w32(0x090, 0x8000_0000 | (pzsh << 24) | (pzm << 8) | pzk)
        time.sleep(0.001)
        mtr.w32(0x040, 0x0200_0000)
        return 'pz'
    mtr.w32(0x070, thr)
    mtr.w32(0x080, hyst)
    mtr.w32(0x060, 0x8000_0000 | (G_ << 8) | L)
    time.sleep(0.001)
    mtr.w32(0x040, 0x0002_0000)
    return 'pendiente'


def correr_bloque(g, m, mtr, osc, b, gkw, asg, tab, sel):
    g.configurar(**gkw)                           # salidas = OUT1: el lazo del canal 0
    g.cargar_tabla(tab)
    fuente = armar_mca(m, mtr, osc, b, asg)
    m.sel_1d(*sel)
    m.clear()
    time.sleep(0.002)
    m.start()
    time.sleep(0.002)
    try:
        g.arrancar()
        est = g.esperar(timeout_s=5.0)
        time.sleep(0.02)                          # las últimas ventanas cierran
        m.stop()
        time.sleep(0.01)
        d, h = m.leer(), m.espectro()
    finally:
        g.parar()
        multitrigger_desarmar_mca(osc, mtr, ch=0)
        osc.w32(R_DEB_LEN, DEB_LEN_RESET)
    return fuente, est, d, h


def parte_b(g, m, mtr, osc, ig, res):
    print('\n[B] los bloques de tb_pulsos_mca, contra la réplica con la latencia del top')
    with open(REF_PLACA) as f:
        ref = json.load(f)
    print(f'    referencia: la réplica con LAT_ASG = {ref["lat_asg"]}')
    integration_set_route_mca(ig, TAP_ADC)
    integration_set_route_mtrg(ig, TAP_ADC)
    g.lazo = True
    claves = ('total', 'accepted', 'rej_amp', 'rej_psd', 'pileup', 'dropped', 'cross',
              'open', 'lost_active', 'win', 'trig')
    try:
        for (b, gkw, asg, tab), r in zip(leer_estimulo(), ref['bloques']):
            for nombre_f, f, z in (('F_PEAK', F_PEAK, 0), ('F_TRISE', F_TRISE, 3)):
                fuente, est, d, h = correr_bloque(g, m, mtr, osc, b, gkw, asg, tab, (f, z))
                cnt = {k: int(d[k]) for k in claves}
                t_ocup = [int(v) for v in d['t_ocup'][1:]]
                esp = {str(i): int(h[i]) for i in np.flatnonzero(h)}
                esperado = r['espectros'][f'{nombre_f}_z{z}']
                n_t = len(t_ocup)
                ok_t = (t_ocup == r['t_ocup'][:n_t] and not any(r['t_ocup'][n_t:]))
                tag = f'{r["nombre"]} ({fuente}, n_acc={r["n_acc"]}) {nombre_f}'
                check(f'{tag}: GEN_CNT, terminado y sin desborde',
                      est['gen_cnt'] == r['gen_cnt'] and est['terminado']
                      and not est['desborde'], est)
                check(f'{tag}: los 11 contadores', cnt == r['cnt'],
                      {k: (cnt[k], r['cnt'][k]) for k in claves if cnt[k] != r['cnt'][k]})
                check(f'{tag}: t_ocup', ok_t, (t_ocup, r['t_ocup']))
                distintos = sorted(set(esp) ^ set(esperado)
                                   | {k for k in esp if esp.get(k) != esperado.get(k)},
                                   key=int)
                check(f'{tag}: el espectro canal por canal', not distintos,
                      f'{len(distintos)} canales distintos, ej. {distintos[:5]}'
                      if distintos else '')
                res.append(dict(parte='B', bloque=r['nombre'], espectro=nombre_f,
                                gen=est, cnt=cnt, t_ocup=t_ocup, espectro_canales=esp))
    finally:
        g.lazo = False
        integration_reset_routes(ig)


# =============================================================================
# C. gen_eventos en el ring
# =============================================================================

def correr_ring(ring, disparos, pre, post, plazo_s=10.0):
    """Configura el ring y el generador, corre, lee todo y para. Devuelve las
    columnas leídas, el estado del generador y los contadores del ring."""
    s = pre + post
    n = disparos['n']
    lector = OR.LectorRing(ring, pre, post, 2, [IDENTIDAD] * 2)
    lector.configurar()                       # parado: geometría, contadores, footers
    ring.gen_configurar(disparos, patron=True)
    cols = dict(wave=np.zeros((n, 2, s), np.int16), ts_hw=np.zeros(n, np.int64),
                snap=np.zeros(n, np.uint32), seq=np.zeros(n, np.uint32))
    leidos = 0
    ring.correr()
    try:
        t_fin = time.time() + plazo_s
        while time.time() < t_fin:
            got, _, _ = lector.leer(cols, leidos, n - leidos,
                                    time.perf_counter_ns() + 50_000_000)
            leidos += got
            e, k = ring.gen_estado(), ring.contadores()
            if e['terminado'] and leidos == k['ev_cnt']:
                break
    finally:
        ring.parar()
        e, k = ring.gen_estado(), ring.contadores()
        ring.gen_apagar()
    return {c: a[:leidos] for c, a in cols.items()}, e, k


def verificar_ring(tag, cols, e, k, disparos, pre, post, sin_perdidas):
    n = disparos['n']
    check(f'{tag}: GEN_CNT = N y terminado', e['gen_cnt'] == n and e['terminado'], e)
    perd = k['drop_busy'] + k['drop_full']
    check(f'{tag}: EV_CNT + DROP_BUSY + DROP_FULL = GEN_CNT',
          k['ev_cnt'] + perd == e['gen_cnt'],
          f'{k["ev_cnt"]} + {k["drop_busy"]} + {k["drop_full"]} vs {e["gen_cnt"]}')
    m = cols['ts_hw'].size
    check(f'{tag}: llegan todos los escritos', m == k['ev_cnt'], f'{m} de {k["ev_cnt"]}')
    if sin_perdidas:
        check(f'{tag}: sin descartes', perd == 0, k)
    else:
        check(f'{tag}: hay descartes (la tasa supera a la captura)', k['drop_busy'] > 0, k)
    check(f'{tag}: seq consecutivo', np.array_equal(cols['seq'], np.arange(m, dtype=np.uint32)))

    # La marca de cada slot, contra la predicción para su índice k.
    pred = G.predecir(int(1.2 * n * 125e6 / G.tasa(**disparos)) + 10_000, OR.GEN_LAT_TS,
                      n_max=n, **disparos)
    assert pred.size == n, f'la predicción da {pred.size} disparos de {n}: más ciclos'
    idx = np.searchsorted(pred, cols['ts_hw'])
    en_pred = (idx < pred.size) & (pred[np.minimum(idx, pred.size - 1)] == cols['ts_hw'])
    check(f'{tag}: cada marca es la de un disparo del modelo', bool(en_pred.all()),
          f'{int((~en_pred).sum())} que no' if not en_pred.all() else '')
    snap = cols['snap']
    k16 = (idx & 0xFFFF).astype(np.uint32)
    check(f'{tag}: el snapshot {{1, k}} es el índice de esa marca',
          bool(((snap & OR.GEN_SNAP_MARCA) != 0).all() and (snap & 0xFFFF == k16).all()))
    if sin_perdidas:
        check(f'{tag}: las marcas son las N predichas, en orden',
              np.array_equal(cols['ts_hw'], pred))
    # Un disparo en los primeros `pre` ciclos tiene un pre-trigger que mira antes del
    # arranque: esas muestras (ts - pre + j < 0) son lo que quedó en el buffer de la
    # corrida anterior, no el patrón (logica_de_captura_y_axi.md §2.3). Se comparan
    # las demás, y se exige que las distintas sean sólo ésas.
    ts = cols['ts_hw']
    j = np.arange(pre + post)
    antes = (ts[:, None] - pre + j) < 0                       # (m, muestras)
    distinta = (cols['wave'] != OR.patron_gen(ts, pre, pre + post)).any(axis=1)
    malas = np.flatnonzero((distinta & ~antes).any(axis=1))
    check(f'{tag}: todas las muestras desde el arranque son el patrón de su marca',
          malas.size == 0,
          f'{malas.size} slots, ej. seq {list(cols["seq"][malas[:4]])}' if malas.size else '')
    if antes.any():
        n_antes = int(antes.any(axis=1).sum())
        print(f'    {n_antes} slot(s) con ts < pre: {int(antes.sum())} muestras de antes del '
              f'arranque, sin comparar ({int((distinta & antes).sum())} distintas del patrón)')


def parte_c(res):
    print('\n[C] gen_eventos en el ring')
    ring = OR.OsciloscopeRing.open()
    try:
        if not check('el ring tiene el generador ("GEN1")', ring.gen_presente()):
            return
        pre, post = 8, 24
        casos = (('C1 periódico a 125 kHz', G.disparos(periodo=1000, n=20_000), True),
                 ('C2 aleatorio a 3 MHz', G.disparos(aleatorio=True, tasa=3e6, dt_min=5,
                                                     n=100_000, semilla=7), False))
        for tag, d, sin_perdidas in casos:
            t0 = time.time()
            cols, e, k = correr_ring(ring, d, pre, post)
            print(f'    {tag}: {cols["ts_hw"].size} leídos en {time.time() - t0:.2f} s, '
                  f'DROP_BUSY {k["drop_busy"]}, DROP_FULL {k["drop_full"]}', flush=True)
            verificar_ring(tag, cols, e, k, d, pre, post, sin_perdidas)
            res.append(dict(parte='C', caso=tag, disparos=d, gen=e,
                            contadores={c: int(v) for c, v in k.items()},
                            leidos=int(cols['ts_hw'].size)))
    finally:
        ring.close()


# =============================================================================
# D. Los modos de medida del lector
# =============================================================================

def correr_medida(ring, disparos, pre, post, modo, plazo_s=10.0):
    """Como correr_ring, con `LectorRing.medir` en vez de leer columnas."""
    lector = OR.LectorRing(ring, pre, post, 2, [IDENTIDAD] * 2)
    lector.configurar()
    ring.gen_configurar(disparos, patron=True)
    ring.correr()
    try:
        t_fin = time.time() + plazo_s
        while time.time() < t_fin:
            m = lector.medir(modo, time.perf_counter_ns() + 50_000_000, disparos=disparos)
            e, k = ring.gen_estado(), ring.contadores()
            if e['terminado'] and m['eventos'] == k['ev_cnt']:
                break
    finally:
        ring.parar()                 # WR_SLOT vuelve a 0: no se mide más
        e, k = ring.gen_estado(), ring.contadores()
        ring.gen_apagar()
    return lector.medida, e, k


def verificar_medida(tag, modo, m, e, k, disparos, pre, post, sin_perdidas):
    n = disparos['n']
    perd = k['drop_busy'] + k['drop_full']
    check(f'{tag}: GEN_CNT = N y terminado', e['gen_cnt'] == n and e['terminado'], e)
    check(f'{tag}: consumió los EV_CNT', m['eventos'] == k['ev_cnt'],
          f'{m["eventos"]} de {k["ev_cnt"]}')
    check(f'{tag}: EV_CNT + descartados = GEN_CNT', k['ev_cnt'] + perd == e['gen_cnt'],
          f'{k["ev_cnt"]} + {perd} vs {e["gen_cnt"]}')
    check(f'{tag}: los descartados que leyó son los del ring', m['descartados'] == perd,
          f'{m["descartados"]} vs {perd}')
    if sin_perdidas:
        check(f'{tag}: sin descartes', perd == 0, k)
    datos = ((pre + post) * OR.N_CH_HW * 2 + 7) & ~7
    if modo == 'creditos':
        check(f'{tag}: no copió nada', m['bytes'] == 0, m['bytes'])
    else:
        check(f'{tag}: copió cada slot', m['bytes'] == m['eventos'] * (OR.HDR_BYTES + datos),
              m['bytes'])
    if modo == 'verificar':
        check(f'{tag}: sin errores', m['errores'] == 0,
              {c: m[c] for c in ('err_cabecera', 'err_marca', 'err_k', 'err_ts',
                                 'err_patron', 'muestras_malas', 'primer_error_seq')})
        check(f'{tag}: los k que faltan son los descartados',
              m['k_saltos'] + (e['gen_cnt'] - 1 - m['k_ultimo']) == perd,
              f'{m["k_saltos"]} + ({e["gen_cnt"]} - 1 - {m["k_ultimo"]}) vs {perd}')


def parte_d(res):
    print('\n[D] los modos de medida del lector')
    ring = OR.OsciloscopeRing.open()
    try:
        if not ring.gen_presente():
            check('el ring tiene el generador ("GEN1")', False)
            return
        pre, post = 8, 24
        casos = (('periódico a 125 kHz', G.disparos(periodo=1000, n=20_000), True),
                 ('aleatorio a 3 MHz', G.disparos(aleatorio=True, tasa=3e6, dt_min=5,
                                                  n=100_000, semilla=7), False),
                 ('periódico a 1 MHz', G.disparos(periodo=125, n=1_000_000), False))
        for nombre, d, sin_perdidas in casos:
            for modo in ('creditos', 'copia', 'verificar'):
                tag = f'D {nombre}, {modo}'
                m, e, k = correr_medida(ring, d, pre, post, modo)
                dur = max(m['t1_ns'] - m['t0_ns'], 1) * 1e-9
                print(f'    {tag}: {m["eventos"]} en {dur:.3f} s ({m["eventos"] / dur / 1e3:.0f}'
                      f' k/s), trabajo {100 * m["trabajo_ns"] * 1e-9 / dur:.0f} %, '
                      f'ocupación máx {m["ocupacion_max"]} slots, DROP_BUSY '
                      f'{k["drop_busy"]}, DROP_FULL {k["drop_full"]}', flush=True)
                verificar_medida(tag, modo, m, e, k, d, pre, post, sin_perdidas)
                res.append(dict(parte='D', caso=nombre, modo=modo, disparos=d, gen=e,
                                contadores={c: int(v) for c, v in k.items()},
                                medida={c: v for c, v in m.items()}))
    finally:
        ring.close()


# =============================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--salida', help='JSON con lo medido')
    ap.add_argument('--solo', default='A,B,C,D', help='partes, separadas por coma')
    a = ap.parse_args(argv)
    partes = set(a.solo.upper().split(','))
    res = []
    try:
        g = G.GenPulsos.open()
    except G.GenPulsosNotPresent as e:
        print(f'  {e}\n  Cargar el bitstream del ring: python3 campanas/preparar_placa.py '
              '--cargar --bitstream /root/event_ring_red_pitaya_Z10_2CH.bit.bin')
        return 2
    ig = integration_open()
    try:
        if 'A' in partes:
            parte_a(g, ig)
        if 'B' in partes:
            m, mtr, osc = MCA2(), MtRegion.open(), osciloscope_open()
            try:
                parte_b(g, m, mtr, osc, ig, res)
            finally:
                osc.w32(R_DEB_LEN, DEB_LEN_RESET)
                osciloscope_close(osc)
                mtr.close()
                m.close()
        if 'C' in partes:
            parte_c(res)
        if 'D' in partes:
            parte_d(res)
    finally:
        g.parar()
        g.lazo = False
        integration_reset_routes(ig)
        integration_close(ig)
        g.close()
    if a.salida:
        with open(a.salida, 'w') as f:
            json.dump(res, f, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
        print(f'\n  -> {a.salida}')
    print(f'\nRESULT: {"PASS" if _fail == 0 else "FAIL"} ({_pass} ok, {_fail} fallas)')
    return 1 if _fail else 0


if __name__ == '__main__':
    sys.exit(main())
