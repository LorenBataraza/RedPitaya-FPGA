#!/usr/bin/env python3
"""Validacion OFFLINE del generador de arribos Poisson (`poisson_train_wave`).

No necesita la Pitaya ni el Rigol: valida la forma que se le va a subir al
instrumento. Es donde se atrapan los errores que en la placa se ven como
"numeros plausibles pero falsos".

Lo que se chequea, y por que:

  1. INTERVALOS EXPONENCIALES (KS). Es la propiedad que define al proceso; si
     falla, todo el barrido de perdidas mide otra cosa.
  2. N ~ POISSON (media == varianza). Distingue el proceso de Poisson de un
     proceso binomial con N fijo.
  3. LA COSTURA. El ARB REPITE la forma, asi que el intervalo entre el ultimo
     arribo de un ciclo y el primero del siguiente es parte del proceso. Con un
     `cumsum` de exponenciales ese intervalo queda determinista (y distinto del
     resto), y contamina la estadistica en cada repeticion. Aca se verifica que
     el gap que cruza la costura viene de la misma distribucion que los otros.
  4. PILE-UP medido contra 1-exp(-2*lambda*w).
  5. ESCALA ESTABLE entre semillas: la altura de un pulso aislado NO puede
     depender de cuanto apilamiento le toco a esa realizacion (si dependiera,
     el pico del espectro se correria de un trozo al otro).

Uso:
    python3 test_poisson_wave.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from rigol_dg4162 import poisson_train_wave, ARB_MAX_POINTS   # noqa: E402

FALLAS = []


def check(nombre, ok, detalle=''):
    print(f'  [{"PASS" if ok else "FAIL"}] {nombre}' + (f'  {detalle}' if detalle else ''))
    if not ok:
        FALLAS.append(nombre)
    return ok


def arribos(info, wave=None, seed=0, **kw):
    """Re-deriva las posiciones de arribo re-corriendo el sorteo del generador.

    Se rehace el sorteo con la misma semilla en vez de leerlas de la forma
    (detectarlas sobre la onda con pile-up seria circular: usaria el mismo
    criterio que se quiere validar).
    """
    rng = np.random.default_rng(seed)
    n = int(rng.poisson(info['rate_hz'] * info['T_ciclo_s']))
    return np.sort(rng.uniform(0.0, info['n_pts'], n)) * info['dt_s']


def ks_exponencial(gaps, lam):
    """Estadistico KS de `gaps` contra Exp(lam) y su p-valor asintotico."""
    from scipy import stats
    return stats.kstest(gaps, 'expon', args=(0.0, 1.0 / lam))


# =============================================================================

def test_intervalos_exponenciales():
    print('\n== 1. intervalos ~ Exp(lambda) (KS sobre muchas realizaciones) ==')
    lam, w, n_ev = 217e3, 2e-6, 64
    todos = []
    for seed in range(60):
        _, _, info = poisson_train_wave(lam, w, n_events=n_ev, seed=seed)
        t = arribos(info, seed=seed)
        T = info['T_ciclo_s']
        # gaps CIRCULARES: el ultimo cierra contra el primero del ciclo siguiente
        todos.append(np.diff(np.concatenate([t, [t[0] + T]])))
    gaps = np.concatenate(todos)
    ks = ks_exponencial(gaps, lam)
    check('KS contra Exp(lambda)', ks.pvalue > 0.01,
          f'D={ks.statistic:.4f} p={ks.pvalue:.3f} n={gaps.size}')
    check('media de los intervalos ~ 1/lambda',
          abs(gaps.mean() * lam - 1.0) < 0.05,
          f'{gaps.mean()*1e6:.3f} us vs {1e6/lam:.3f} us')


def test_conteo_poisson():
    print('\n== 2. N ~ Poisson: media == varianza ==')
    lam, w, n_ev = 217e3, 2e-6, 64
    ns = np.array([poisson_train_wave(lam, w, n_events=n_ev, seed=s)[2]['n_events']
                   for s in range(400)])
    check('media ~ lambda*T', abs(ns.mean() - n_ev) < 0.15 * n_ev,
          f'media={ns.mean():.1f} esperado={n_ev}')
    check('varianza ~ media (Poisson, no binomial)',
          abs(ns.var() / ns.mean() - 1.0) < 0.25,
          f'var/media={ns.var()/ns.mean():.3f}')

    ns_fijo = np.array([poisson_train_wave(lam, w, n_events=n_ev, fixed_n=True,
                                           seed=s)[2]['n_events']
                        for s in range(20)])
    check('fixed_n=True fuerza N exacto', np.all(ns_fijo == n_ev),
          f'unicos={set(ns_fijo.tolist())}')


def test_costura():
    print('\n== 3. la costura del ciclo: sesgada por longitud, como corresponde ==')
    # El ARB REPITE la forma, asi que el intervalo entre el ultimo arribo de un
    # ciclo y el primero del siguiente forma parte del proceso.
    #
    # OJO con la intuicion: ese intervalo NO tiene que parecerse a los otros.
    # Contiene un punto FIJO (la costura), y el intervalo que contiene un punto
    # fijo de un proceso de Poisson esta sesgado por longitud (paradoja de la
    # inspeccion): su media es 2/lambda, no 1/lambda. Que de 2/lambda es
    # justamente la prueba de que la construccion es correcta.
    #
    # El error que esto atrapa: sortear N intervalos exponenciales con `cumsum`
    # y cerrar el ciclo con el ultimo. Ahi el gap de la costura es un
    # exponencial comun (media 1/lambda), o sea SISTEMATICAMENTE CORTO, y ese
    # sesgo se repite en cada vuelta del ARB.
    lam, w, n_ev = 217e3, 2e-6, 64
    cruce, resto = [], []
    for seed in range(300):
        _, _, info = poisson_train_wave(lam, w, n_events=n_ev, seed=seed)
        t = arribos(info, seed=seed)
        T = info['T_ciclo_s']
        g = np.diff(np.concatenate([t, [t[0] + T]]))
        cruce.append(g[-1])                 # el que cruza la costura
        resto.extend(g[:-1].tolist())
    cruce, resto = np.array(cruce), np.array(resto)
    r = cruce.mean() * lam
    check('gap de la costura sesgado por longitud (media ~ 2/lambda)',
          1.7 < r < 2.3, f'media={r:.2f}/lambda (esperado 2, un cumsum daria 1)')
    check('el resto de los gaps es 1/lambda',
          abs(resto.mean() * lam - 1.0) < 0.06,
          f'media={resto.mean()*lam:.3f}/lambda')

    # Y la propiedad operativa: el flujo CONCATENADO (que es lo que sale del
    # instrumento) tiene intervalos exponenciales.
    todos = np.concatenate([cruce, resto])
    ks = ks_exponencial(todos, lam)
    check('flujo concatenado ~ Exp(lambda)', ks.pvalue > 0.01,
          f'D={ks.statistic:.4f} p={ks.pvalue:.3f}')


def test_pileup():
    print('\n== 4. pile-up medido vs 1-exp(-2*lambda*w) ==')
    w = 2e-6
    for lam in (50e3, 217e3):
        fr, teo = [], None
        for seed in range(40):
            _, _, info = poisson_train_wave(lam, w, n_events=64, seed=seed)
            fr.append(info['frac_pileup'])
            teo = info['frac_pileup_teo']
        med = float(np.mean(fr))
        check(f'lambda={lam/1e3:.0f} kcps: medido {med:.3f} vs teorico {teo:.3f}',
              abs(med - teo) < 0.05, f'|dif|={abs(med-teo):.3f}')


def test_escala_estable():
    print('\n== 5. la altura de un pulso aislado no depende de la semilla ==')
    # UN pulso por ciclo: el maximo de la forma es, sin ambiguedad, un pulso
    # solo. (Con varios pulsos el maximo de la forma es justamente el
    # apilamiento mas grande, no un pulso aislado.)
    picos = []
    for seed in range(15):
        wave, _, _ = poisson_train_wave(2e3, 20e-6, n_events=1, fixed_n=True,
                                        seed=seed)
        picos.append(wave.max())
    picos = np.array(picos)
    check('pico constante entre semillas', picos.ptp() < 1e-9,
          f'min={picos.min():.4f} max={picos.max():.4f}')
    check('pico == amplitud/headroom (1/3)', abs(picos.mean() - 1 / 3) < 1e-6,
          f'{picos.mean():.4f}')

    # Y con pile-up de por medio: los pulsos que quedaron AISLADOS tienen que
    # medir lo mismo que en el caso anterior.
    aislados = []
    for seed in range(30):
        wave, _, info = poisson_train_wave(217e3, 2e-6, n_events=64, seed=seed)
        t = arribos(info, seed=seed) / info['dt_s']          # en puntos
        L = info['n_pulso_pts']
        g = np.diff(np.concatenate([t, [t[0] + info['n_pts']]]))
        solo = (g > L) & (np.roll(g, 1) > L)                 # sin vecino cerca
        for k in np.flatnonzero(solo):
            i = int(t[k])
            aislados.append(wave[i:i + L].max() if i + L <= wave.size
                            else wave[i:].max())
    aislados = np.array(aislados)
    check('pulsos aislados dentro de una forma con pile-up: misma altura',
          aislados.size > 20 and abs(aislados.mean() - 1 / 3) < 0.01
          and aislados.std() < 0.01,
          f'n={aislados.size} media={aislados.mean():.4f} std={aislados.std():.4f}')

    # Y el contraste: normalizando por el maximo (lo que hace load_arb por
    # default) la altura del pulso individual SI se mueve con el pile-up.
    lam2 = 217e3
    rel = []
    for seed in range(15):
        wave, _, info = poisson_train_wave(lam2, 2e-6, n_events=64, seed=seed)
        rel.append(info['amp_single_rel'] / max(wave.max(), 1e-9))
    rel = np.array(rel)
    check('normalizar por el maximo movería el pico (por eso normalize=False)',
          rel.ptp() > 0.05, f'variacion relativa={rel.ptp():.3f}')


def test_geometria_y_errores():
    print('\n== 6. geometria y mensajes de error ==')
    lam, w, n_ev = 217e3, 2e-6, 64
    wave, freq, info = poisson_train_wave(lam, w, n_events=n_ev, seed=1)
    check('n_pts == memoria del ARB', wave.size == ARB_MAX_POINTS, f'{wave.size}')
    check('freq_hz == rate/n_events', abs(freq - lam / n_ev) < 1e-6 * freq,
          f'{freq:.3f} Hz')
    check('dt == n_events/(rate*n_pts)',
          abs(info['dt_s'] - n_ev / (lam * ARB_MAX_POINTS)) < 1e-15,
          f'{info["dt_s"]*1e9:.2f} ns')
    check('forma dentro de [-1, 1]', np.abs(wave).max() <= 1.0,
          f'max={wave.max():.4f}')
    check('sin recorte a esta tasa', info['frac_clip'] == 0.0)

    # tasa baja + pulso angosto: tiene que fallar con un mensaje accionable
    try:
        poisson_train_wave(400.0, 2e-6, n_events=64)
        check('rechaza la combinacion imposible', False, 'no levanto ValueError')
    except ValueError as e:
        msg = str(e)
        check('rechaza la combinacion imposible',
              'width_s' in msg and 'n_events' in msg, msg[:90] + '...')

    # srate por encima del instrumento
    try:
        poisson_train_wave(1e9, 1e-9, n_events=64)
        check('rechaza srate imposible', False, 'no levanto ValueError')
    except ValueError as e:
        check('rechaza srate imposible', 'Sa/s' in str(e), str(e)[:70] + '...')


if __name__ == '__main__':
    print('validacion offline de poisson_train_wave')
    test_intervalos_exponenciales()
    test_conteo_poisson()
    test_costura()
    test_pileup()
    test_escala_estable()
    test_geometria_y_errores()
    print('\nRESULT:', 'PASS' if not FALLAS else f'FAIL ({len(FALLAS)}): {FALLAS}')
    sys.exit(1 if FALLAS else 0)
