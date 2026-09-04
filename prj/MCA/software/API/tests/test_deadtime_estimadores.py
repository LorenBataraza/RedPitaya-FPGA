#!/usr/bin/env python3
"""Los estimadores de tiempo muerto, contra un K=1 simulado de tau conocido.

Corre en la PC, sin placa. Valida las dos formas de estimar tau en tiempo de
corrida:

    metodo A  DeadTimeAnnotator     cronometra el periodo ocupado del lector
    metodo B  tau_poisson           infiere tau y la TASA INCIDENTE de los Delta-t
              tau_periodico         infiere el bracket de tau y la perdida exacta

CLAVE de la simulacion, y de todo el metodo: las perdidas por TIEMPO MUERTO no
se anotan en `gap`. En el sistema real el scope no estaba armado, no hubo
trigger, y el lector nunca se entero. `gap` solo lleva los descartes por
BACKPRESSURE. La simulacion respeta esa asimetria porque es de donde sale la
validez de filtrar por `gap == 0`.

    python3 test_deadtime_estimadores.py        # RESULT: PASS
"""

import os
import sys
import tempfile

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API.analisis import (tau_poisson, tau_periodico, error_cuantizacion,   # noqa: E402
                          cv_residuo)
from API.osciloscope_store import (AcquisitionSession, DeadTimeAnnotator,   # noqa: E402
                                   FakeSource, load_chunk)

TAU  = 250e-6          # el tau del lector medido en la campana (README, fig. 1)
DUR  = 60.0            # segundos simulados por punto
_fallos = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FALLO ') + msg)
    if not cond:
        _fallos.append(msg)


# =============================================================================
# Simulador: servidor K=1 no paralizable
# =============================================================================

def servidor(arr, tau_mu, tau_sigma, rng, p_backpressure=0.0):
    """Un arribo se acepta solo si el sistema esta libre. Devuelve (t, gap)."""
    t, g, libre, pend_bp = [], [], -np.inf, 0
    for a in arr:
        if a < libre:
            continue                       # perdido por TIEMPO MUERTO: invisible
        serv = rng.normal(tau_mu, tau_sigma) if tau_sigma else tau_mu
        if p_backpressure and rng.random() < p_backpressure:
            pend_bp += 1                   # perdido por BACKPRESSURE: se anota
            libre = a + serv
            continue
        t.append(a)
        g.append(min(pend_bp, 255))
        pend_bp = 0
        libre = a + serv
    return np.array(t), np.array(g, dtype=np.uint8)


def corrida(proceso, param, tau_mu=TAU, dur=DUR, rng=None, tau_sigma=0.0,
            jitter_us=3.0, p_bp=0.0):
    """`param` es la tasa (poisson) o el periodo (periodico)."""
    if proceso == 'poisson':
        arr = np.sort(rng.uniform(0, dur, rng.poisson(param * dur)))
    else:
        arr = np.arange(0, dur, param)
    t, g = servidor(arr, tau_mu, tau_sigma, rng, p_bp)
    t = np.sort(t + rng.normal(0, jitter_us * 1e-6, t.size))
    return (t * 1e9).astype(np.int64), g


# =============================================================================
def caso_poisson():
    """tau y la tasa incidente, en dos decadas de ocupacion."""
    print('\n[1] tau_poisson: rho = 0.05 ... 2')
    rng = np.random.default_rng(7)
    print(f'    {"n":>6} {"rho":>5} | {"tau_est":>9} {"err":>7} | '
          f'{"n_est":>7} {"err":>7} | {"perd_est":>8} {"perd_real":>9}')
    for n in (200, 500, 1000, 2000, 4000, 8000):
        t, g = corrida('poisson', n, rng=rng)
        r = tau_poisson(t, g)
        e_tau = r['tau_s'] / TAU - 1
        e_n   = r['n_incidente'] / n - 1
        real  = 1 - r['m_registrada'] / n
        print(f'    {n:6d} {n*TAU:5.2f} | {r["tau_s"]*1e6:7.1f}us '
              f'{e_tau*100:+6.1f}% | {r["n_incidente"]:7.0f} {e_n*100:+6.1f}% |'
              f' {r["perdida"]:8.3f} {real:9.3f}')
        check(abs(e_tau) < 0.03, f'n={n}: tau dentro de +-3 % ({e_tau*100:+.1f} %)')
        check(abs(e_n) < 0.05, f'n={n}: tasa incidente dentro de +-5 % '
                               f'({e_n*100:+.1f} %)')
        check(abs(r['perdida'] - real) < 0.02,
              f'n={n}: perdida predicha ~ real ({r["perdida"]:.3f} vs {real:.3f})')


def caso_periodico():
    """El bracket contiene tau, la perdida es exacta, y el barrido lo aprieta."""
    print('\n[2] tau_periodico: barrido en T')
    rng = np.random.default_rng(7)
    print(f'    {"T[us]":>7} {"tau/T":>6} | {"k":>3} {"bracket tau [us]":>18} |'
          f' {"perd_est":>8} {"perd_real":>9}')
    brackets = []
    for T in (1000e-6, 500e-6, 300e-6, 250e-6, 200e-6, 125e-6, 100e-6, 50e-6):
        t, g = corrida('periodico', T, rng=rng, tau_sigma=2e-6)
        r = tau_periodico(t, g, T_s=T)
        real = 1 - r['m_registrada'] * T
        brackets.append((r['tau_lo'], r['tau_hi']))
        br = '(%.0f, %.0f]' % (r['tau_lo'] * 1e6, r['tau_hi'] * 1e6)
        print(f'    {T*1e6:7.0f} {TAU/T:6.2f} | {r["k_moda"]:3d} {br:>18} |'
              f' {r["perdida"]:8.3f} {real:9.3f}')
        check(r['tau_lo'] < TAU <= r['tau_hi'],
              f'T={T*1e6:.0f}us: el bracket contiene tau')
        check(abs(r['perdida'] - real) < 0.005,
              f'T={T*1e6:.0f}us: perdida exacta ({r["perdida"]:.3f} vs {real:.3f})')

    lo = max(b[0] for b in brackets)
    hi = min(b[1] for b in brackets)
    print(f'    interseccion de los 8 brackets: ({lo*1e6:.0f}, {hi*1e6:.0f}] us')
    check(lo < TAU <= hi, 'la interseccion sigue conteniendo tau')
    check(hi - lo < 0.3 * TAU,
          f'el barrido aprieta tau a menos del 30 % ({(hi-lo)*1e6:.0f} us)')
    # Es el mismo intervalo irreducible que reporta el README con los 6 puntos
    # del lector: dos caminos independientes que dan lo mismo.
    check(abs(lo - 200e-6) < 1e-6 and abs(hi - 250e-6) < 1e-6,
          'la interseccion reproduce el (200, 250] us del README')


def caso_borde_localiza_tau():
    """Con tau/T entero se pueblan dos k, y el borde localiza tau."""
    print('\n[3] tau/T = 5.00 (el punto de 20 kev/s): el borde localiza tau')
    rng = np.random.default_rng(7)
    t, g = corrida('periodico', 50e-6, rng=rng, tau_sigma=2e-6)
    r = tau_periodico(t, g, T_s=50e-6)
    print(f'    k poblados: {r["k_frac"]}')
    check('tau_est' in r, 'detecta los dos k adyacentes y reporta tau_est')
    if 'tau_est' in r:
        print(f'    tau_est = {r["tau_est"]*1e6:.0f} us (verdadero {TAU*1e6:.0f})')
        check(abs(r['tau_est'] - TAU) < 1e-6, 'tau_est cae sobre el tau verdadero')


def caso_discriminador():
    """El CV se equivoca en los bordes; el error de cuantizacion no."""
    print('\n[4] por que el modelo se declara y no se adivina')
    rng = np.random.default_rng(7)
    print(f'    {"caso":>24} | {"CV":>5} {"dice":>10} | {"err_cuant":>9} {"dice":>10}')
    fallos_cv = 0
    for T in (1000e-6, 250e-6, 200e-6, 125e-6, 50e-6):
        t, g = corrida('periodico', T, rng=rng, tau_sigma=2e-6)
        cv = cv_residuo(t, g)
        ec = error_cuantizacion(t, g, T)
        d_cv = 'poisson' if cv > 0.65 else 'periodico'
        d_ec = 'periodico' if ec < 0.15 else 'poisson'
        fallos_cv += (d_cv != 'periodico')
        print(f'    {"PERIODICO tau/T=%.2f" % (TAU/T):>24} | {cv:5.2f} '
              f'{d_cv:>10} | {ec:9.3f} {d_ec:>10}'
              f'{"   <-- CV SE EQUIVOCA" if d_cv != "periodico" else ""}')
        check(d_ec == 'periodico',
              f'T={T*1e6:.0f}us: el error de cuantizacion acierta')
    for n in (500, 2000, 4000):
        t, g = corrida('poisson', n, rng=rng)
        ec = error_cuantizacion(t, g, 1.0 / n)
        print(f'    {"POISSON n=%d" % n:>24} | {cv_residuo(t, g):5.2f} '
              f'{"poisson":>10} | {ec:9.3f} '
              f'{"periodico" if ec < 0.15 else "poisson":>10}')
        check(ec > 0.15, f'n={n}: el error de cuantizacion rechaza Poisson')
    check(fallos_cv >= 3, f'el CV falla en >=3 casos periodicos ({fallos_cv}): '
                          'documentado como NO-selector')


def caso_periodico_rechaza_poisson():
    """Pasarle datos Poisson a tau_periodico tiene que fallar, no mentir."""
    print('\n[5] tau_periodico se niega ante un estimulo que no es periodico')
    rng = np.random.default_rng(3)
    t, g = corrida('poisson', 1000, rng=rng)
    try:
        tau_periodico(t, g, T_s=1e-3)
        check(False, 'deberia haber lanzado ValueError')
    except ValueError as exc:
        msg = str(exc)
        check('no es periódico' in msg and 'tau_poisson' in msg,
              'lanza ValueError y manda a tau_poisson')
        check('error de cuantización' in msg,
              'el motivo es el test de cuantización, no el chequeo de T_s')


def caso_filtro_gap():
    """Sin filtrar por gap, la tasa incidente sale sesgada."""
    print('\n[6] el filtro por gap==0 (backpressure del 20 %)')
    rng = np.random.default_rng(7)
    t, g = corrida('poisson', 1000, rng=rng, p_bp=0.20)
    r = tau_poisson(t, g)
    dt = np.diff(t) / 1e9
    tau_sin = float(np.quantile(dt, 0.001))
    n_sin   = 1.0 / (dt.mean() - tau_sin)
    print(f'    filtrando gap==0 : tau {r["tau_s"]*1e6:6.1f} us   n '
          f'{r["n_incidente"]:6.0f}   ({r["n_intervalos"]} de {dt.size} pares)')
    print(f'    SIN filtrar      : tau {tau_sin*1e6:6.1f} us   n {n_sin:6.0f}')
    check(abs(r['n_incidente'] / 1000 - 1) < 0.05,
          'filtrando, la tasa incidente sale bien')
    check(n_sin / 1000 < 0.85,
          f'sin filtrar sale sesgada >15 % ({(n_sin/1000-1)*100:+.0f} %): '
          'el filtro no es decorativo')


def caso_annotator_end_to_end():
    """El metodo A: la columna llega al .npz sin tocar lector ni escritor."""
    print('\n[7] DeadTimeAnnotator, pipeline completo con FakeSource')
    out = tempfile.mkdtemp(prefix='deadtime_')
    src = FakeSource(pre=8, post=24, rate_hz=2000.0, n_events=4000, seed=1)
    ann = DeadTimeAnnotator()
    with AcquisitionSession(src, out, capacity=1024, annotators=(ann,),
                            verbose=False) as s:
        s.wait(duration_s=30)

    check(s.stats['n_read'] == 4000, f'leidos {s.stats["n_read"]} de 4000')
    check(ann.n == s.stats['n_read'],
          f'el annotator vio los mismos eventos que el lector ({ann.n})')

    chunks = sorted(f for f in os.listdir(out) if f.endswith('.npz'))
    arr, meta = load_chunk(os.path.join(out, chunks[0]))
    check('dead_ns' in arr, f'la columna llego al archivo: {sorted(arr)}')
    check('dead_ns' in meta['fields'], f'y al esquema: {meta["fields"]}')
    if 'dead_ns' in arr:
        d = arr['dead_ns']
        print(f'    dead_ns: mediana {np.median(d)/1000:.1f} us, '
              f'max {d.max()/1000:.1f} us, n={d.size}')
        check((d > 0).all(), 'todos los dead_ns son positivos')
        check(0.0 <= ann.busy_fraction() <= 1.0,
              f'busy_fraction en rango ({ann.busy_fraction():.4f})')

    for f in os.listdir(out):
        os.unlink(os.path.join(out, f))
    os.rmdir(out)


CASOS = (caso_poisson, caso_periodico, caso_borde_localiza_tau,
         caso_discriminador, caso_periodico_rechaza_poisson, caso_filtro_gap,
         caso_annotator_end_to_end)


def correr():
    print(f'tau verdadero = {TAU*1e6:.0f} us,  {DUR:.0f} s por punto,  '
          'jitter de reloj 3 us')
    _fallos.clear()
    for caso in CASOS:
        caso()
    return _fallos


# --- pytest -----------------------------------------------------------------
#
# Un solo punto de entrada, y no un `test_` por caso: `check()` acumula en vez
# de lanzar (para que una corrida a mano muestre TODOS los fallos y no el
# primero), así que un `test_` por caso pasaría siempre. Acá el assert es el que
# convierte lo acumulado en un fallo de verdad.

def test_estimadores_tiempo_muerto():
    fallos = correr()
    assert not fallos, ('estimadores de tiempo muerto:\n'
                        + '\n'.join('  - ' + f for f in fallos))


# =============================================================================
if __name__ == '__main__':
    fallos = correr()
    print(f'\nRESULT: {"PASS" if not fallos else "FAIL"}'
          + ('' if not fallos else f'  ({len(fallos)} fallos)'))
    for f in fallos:
        print('  -', f)
    sys.exit(1 if fallos else 0)
