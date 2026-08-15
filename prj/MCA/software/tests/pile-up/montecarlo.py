#!/usr/bin/env python3
"""Monte-Carlo de apilamiento: barre la tasa y guarda todo para graficar aparte.

Corre en la PC, sin placa. Para cada combinación de espectro fuente, modo de
ventana y tasa produce CUATRO espectros sobre el mismo eje calibrado:

  verdad     las amplitudes sorteadas. Se conocen exactas, y es lo único que la
             placa no puede darnos: sin esto no hay contra qué comparar.
  referencia el MISMO MCA con los pulsos aislados —mismo ruido, mismo umbral,
             mismo estimador, cero apilamiento—. Aísla la distorsión por
             apilamiento de todo lo demás. Sin esta curva, lo que se mida
             incluiría el ensanchamiento por ruido y el sesgo del estimador.
  medido     el MCA a la tasa del barrido, con el rechazo que el RTL YA hace.
             Es la línea de base contra la que se juzga cualquier corte nuevo.
  con corte  lo anterior más el corte por factor de forma, para cada
             discriminador y cada ancho de banda k.

    python3 montecarlo.py                          # el barrido completo (~5 min)
    python3 montecarlo.py --n-eventos 5000         # una corrida rápida
    python3 montecarlo.py --espectro linea --modo 0
"""
import argparse
import json
import os
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

import pileup as pu                                          # noqa: E402

N_CANALES = 16384        # H_AW = 14, como el RTL; 1 canal = 1 cuenta verdadera
RAZONES   = ('q_pico', 'psd')
KS        = (1.5, 2.0, 2.5, 3.0, 4.0, 6.0)
TASAS     = (1e3, 5e3, 2e4, 5e4, 1e5, 2e5, 3e5, 5e5)

# Regiones de interés por espectro. `tope` es el punto final de la fuente: por
# encima de eso la fuente NO PUEDE poner nada, así que toda cuenta ahí arriba es
# apilamiento puro y no hay que ajustar nada para verla.
ESPECTROS = {
    'linea':    dict(picos=(1920,), semi_ancho=150, tope=2300),
    'realista': dict(picos=(1250, 2620), semi_ancho=350, tope=3400),
}


def _eventos(dat, modo):
    return (pu.segmentar_rapido(dat, **pu.CFG_MODO0) if modo == 0
            else pu.compuertas_rapido(dat, **pu.CFG_MODO1))


# Rango del pulser de calibración. Arriba se queda por debajo de la saturación
# del ADC (8191) para que el pico no se recorte, y alcanza para cubrir donde
# caen los apilados: el pico suma de la línea está en 3840 y el de la línea alta
# del espectro realista en 5240.
A_PULSER = (110.0, 7000.0)


N_TANDA = 2000           # pulsos por traza aislada; ver `corrida_aislada`


def corrida_aislada(amps, forma, modo, rng, n_tanda=N_TANDA):
    """El MCA a tasa cero: pulsos aislados, apareados 1:1 con su amplitud.

    Devuelve (ev, amp_est, a_verdadera). El apareo es por posición: cada pulso
    está solo en su ranura, así que la ventana que abre después del arribo `k`
    es la del pulso `k`. Los pulsos bajo umbral no abren ninguna y quedan
    afuera del apareo.

    Se procesa POR TANDAS porque los pulsos aislados ocupan `forma.size + trail`
    muestras cada uno: 50 000 pulsos en una sola traza son 1.2e8 muestras, o sea
    ~1 GB en float64 más las copias. Con tandas de 2000 la traza queda en ~35 MB
    y el resultado es idéntico: las tandas son independientes por construcción,
    justamente porque los pulsos no se tocan.
    """
    amps = np.asarray(amps)
    trozos = []
    for a in range(0, amps.size, int(n_tanda)):
        sub = amps[a:a + int(n_tanda)]
        dat, loc = pu.render_aislados(sub, forma, rng=rng)
        ev = _eventos(dat, modo)
        m = ev['cerrado']
        ev = {k: v[m] for k, v in ev.items()}
        slot = np.searchsorted(loc, ev['i0'], side='right') - 1
        trozos.append((ev, pu.amplitud(ev, modo), sub[slot]))

    ev = {k: np.concatenate([t[0][k] for t in trozos]) for k in trozos[0][0]}
    return (ev, np.concatenate([t[1] for t in trozos]),
            np.concatenate([t[2] for t in trozos]))


def calibracion_pulser(forma, modo, rng, n=12_000, rango=A_PULSER):
    """Calibra ganancia y lugar geométrico con un PULSER DESLIZANTE.

    HACE FALTA que sea un barrido uniforme y no el propio espectro fuente, y
    esto es lo que decide si el corte mide algo: el lugar geométrico hay que
    conocerlo en TODO el rango de amplitudes donde caen los eventos, y los
    apilados caen justo donde la fuente no pone nada —entre la línea y el pico
    suma—. Calibrando con una línea monoenergética el lugar geométrico quedaría
    definido en un puñado de canales y `np.interp` extrapolaría plano hacia
    arriba: el corte rechazaría los eventos apilados por estar fuera del rango
    calibrado y no por tener la forma mal. Sería un corte en amplitud disfrazado
    de corte en forma, y daría un resultado espectacular y falso.

    El barrido uniforme de amplitud es además el estímulo canónico del
    laboratorio (es el mismo que `sliding_pulser_wave` usa para la DNL), así que
    esta calibración es reproducible en la placa.
    """
    amps = rng.uniform(rango[0], rango[1], int(n))
    ev, amp_est, a_ver = corrida_aislada(amps, forma, modo, rng)
    cal = pu.calibrar(amp_est, a_ver)
    locus = {r: pu.locus_forma(amp_est, pu.razon_forma(ev, r)) for r in RAZONES}
    return cal, locus, ev, amp_est


def corrida_poisson(amps, t_idx, forma, modo, rng):
    """El MCA a tasa `lambda`. Devuelve los eventos concatenados de todos los grupos.

    `n_arr` es cuántos pulsos verdaderos entró cada evento: 1 es limpio, >1 es
    apilado. Es lo que después permite separar eficiencia de rechazo.
    """
    trozos = []
    for a, b in pu.agrupar(t_idx, forma.size):
        dat, o = pu.render(t_idx[a:b], amps[a:b], forma, rng=rng)
        ev = _eventos(dat, modo)
        m = ev['cerrado']
        ev = {k: v[m] for k, v in ev.items()}
        ev['n_arr'] = pu.contar_arribos(ev, t_idx[a:b] - o)
        trozos.append(ev)
    if not trozos:
        return {}
    return {k: np.concatenate([t[k] for t in trozos]) for k in trozos[0]}


def una_combinacion(espectro, modo, tasas, n_ev, semilla, forma, verbose=True):
    """Todo el barrido de tasas para un espectro y un modo."""
    roi = ESPECTROS[espectro]
    rng = np.random.default_rng(semilla)

    # --- 1. calibración con pulser deslizante (ganancia + lugar geométrico) --
    cal, locus, ev_cal, amp_cal = calibracion_pulser(forma, modo, rng)
    razon_cal = {r: pu.razon_forma(ev_cal, r) for r in RAZONES}

    # --- 2. referencia: el MISMO espectro fuente, con los pulsos aislados ----
    amps_ref = pu.sortear_amplitudes(n_ev, espectro, rng)
    ev_ref, amp_ref, _ = corrida_aislada(amps_ref, forma, modo, rng)
    L0 = float(ev_ref['largo'].mean())

    h_ver = pu.histograma(pu.a_canal(amps_ref, (1.0, 0.0), n_canales=N_CANALES),
                          N_CANALES)
    h_ref = pu.histograma(pu.a_canal(amp_ref, cal, n_canales=N_CANALES), N_CANALES)

    if verbose:
        d = 100 * (locus['q_pico'][1][-1] / locus['q_pico'][1][0] - 1)
        print(f'  pulser: {amp_cal.size} eventos entre {A_PULSER[0]:.0f} y '
              f'{A_PULSER[1]:.0f} cuentas, ganancia {cal[0]:.3f}')
        print(f'  deriva de Q/pico en todo el rango: {d:+.1f} %')
        print(f'  referencia: {amp_ref.size} eventos de {n_ev}, ventana '
              f'{L0:.0f} muestras ({L0/pu.FS_HZ*1e6:.2f} us)')

    # --- barrido ------------------------------------------------------------
    filas, hists, mapas = [], {}, {}
    for tasa in tasas:
        t0 = time.perf_counter()
        amps = pu.sortear_amplitudes(n_ev, espectro, rng)
        t_idx = pu.arribos_poisson(n_ev, tasa, rng=rng)
        ev = corrida_poisson(amps, t_idx, forma, modo, rng)
        amp = pu.amplitud(ev, modo)
        can = pu.a_canal(amp, cal, n_canales=N_CANALES)
        h_med = pu.histograma(can, N_CANALES)

        limpio = ev['n_arr'] <= 1
        base = dict(tasa=float(tasa), n_gen=int(n_ev), n_det=int(amp.size),
                    frac_limpios=float(limpio.mean()),
                    frac_rtl_apilado=float(ev['apilado'].mean()),
                    largo_medio=float(ev['largo'].mean()))
        for p in roi['picos']:
            base[f'm{p}'] = pu.metricas(h_med, h_ref, p, roi['semi_ancho'],
                                        roi['tope'])

        # --- cortes por factor de forma ------------------------------------
        h_cortes = np.zeros((len(RAZONES), len(KS), N_CANALES), dtype=np.int64)
        cortes = []
        for ir, r in enumerate(RAZONES):
            razon = pu.razon_forma(ev, r)
            for ik, k in enumerate(KS):
                ok = pu.aplicar_corte(amp, razon, locus[r], k=k)
                h_cortes[ir, ik] = pu.histograma(can[ok], N_CANALES)
                fila = dict(razon=r, k=float(k),
                            eficiencia=float(ok[limpio].mean()),
                            rechazo=float(1.0 - ok[~limpio].mean())
                                    if (~limpio).any() else float('nan'),
                            n=int(ok.sum()))
                for p in roi['picos']:
                    fila[f'm{p}'] = pu.metricas(h_cortes[ir, ik], h_ref, p,
                                                roi['semi_ancho'], roi['tope'])
                cortes.append(fila)
        base['cortes'] = cortes
        filas.append(base)

        clave = f'{espectro}_modo{modo}_{tasa:.0f}'
        hists[clave] = dict(h_med=h_med, h_cortes=h_cortes)
        # Muestra de eventos para el mapa 2D. Se guarda la tasa más cercana a
        # 100 kcps: suficientemente alta para que la población apilada se vea,
        # suficientemente baja para que la limpia siga siendo mayoría.
        if tasa == min(tasas, key=lambda t: abs(t - 1e5)):
            s = slice(None, 60_000)
            mapas[clave] = dict(amp=amp[s], n_arr=ev['n_arr'][s],
                                **{f'r_{r}': pu.razon_forma(ev, r)[s]
                                   for r in RAZONES})
        if verbose:
            p0 = roi['picos'][0]
            m = base[f'm{p0}']
            print(f'  {tasa:8.0f} cps: {amp.size:6d} ev, limpios '
                  f'{100*base["frac_limpios"]:5.1f} %, área {m["area_rel"]:.3f}, '
                  f'corrim {m["corrimiento"]:+6.1f} can, continuo '
                  f'{100*m["continuo"]:5.2f} %, L1 {m["l1"]:.3f}   '
                  f'[{time.perf_counter()-t0:.1f} s]')

    return dict(h_ver=h_ver, h_ref=h_ref, hists=hists, mapas=mapas,
                filas=filas, cal=cal, L0=L0, locus=locus,
                amp_cal=amp_cal, razon_cal=razon_cal)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--espectro', default='ambos',
                    choices=['linea', 'realista', 'ambos'])
    ap.add_argument('--modo', default='ambos', choices=['0', '1', 'ambos'])
    ap.add_argument('--tasas', default=','.join(f'{t:g}' for t in TASAS))
    ap.add_argument('--n-eventos', type=int, default=50_000)
    ap.add_argument('--semilla', type=int, default=0)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    espectros = ['linea', 'realista'] if a.espectro == 'ambos' else [a.espectro]
    modos = [0, 1] if a.modo == 'ambos' else [int(a.modo)]
    tasas = [float(x) for x in a.tasas.split(',')]

    out = a.out or os.path.join(_AQUI, '..', '..', 'datos',
                                time.strftime('pileup_%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)

    forma, info = pu.forma_referencia()
    print(f'forma: FWHM {info["fwhm_pts"]:.0f} muestras '
          f'({info["fwhm_pts"]/pu.FS_HZ*1e6:.2f} us), cola tau {info["tau"]:.0f}, '
          f'pico en {info["i_pico"]}, template {info["n"]}')
    print(f'salida: {out}\n')

    resumen = dict(forma=info, n_eventos=a.n_eventos, semilla=a.semilla,
                   tasas=tasas, razones=list(RAZONES), ks=list(KS),
                   n_canales=N_CANALES, cfg_modo0=pu.CFG_MODO0,
                   cfg_modo1=pu.CFG_MODO1, q_shift=pu.Q_SHIFT,
                   sigma_ruido=pu.SIGMA_RUIDO, espectros={}, combinaciones=[])

    t_ini = time.perf_counter()
    for esp in espectros:
        resumen['espectros'][esp] = ESPECTROS[esp]
        for modo in modos:
            print(f'=== espectro {esp}, modo {modo} '
                  f'({"histéresis" if modo == 0 else "compuertas fijas"}) ===')
            r = una_combinacion(esp, modo, tasas, a.n_eventos,
                                a.semilla + 100 * modo, forma)
            base = f'{esp}_modo{modo}'
            guardar = dict(h_ver=r['h_ver'], h_ref=r['h_ref'],
                           tasas=np.array(tasas), ks=np.array(KS),
                           cal=np.array(r['cal']), L0=np.array(r['L0']),
                           amp_cal=r['amp_cal'])
            for rz in RAZONES:
                guardar[f'locus_{rz}'] = np.stack(r['locus'][rz])
                guardar[f'razon_cal_{rz}'] = r['razon_cal'][rz]
            guardar['h_med'] = np.stack([r['hists'][f'{base}_{t:.0f}']['h_med']
                                         for t in tasas])
            guardar['h_cortes'] = np.stack(
                [r['hists'][f'{base}_{t:.0f}']['h_cortes'] for t in tasas])
            for clave, mp in r['mapas'].items():
                for kk, vv in mp.items():
                    guardar[f'mapa_{kk}'] = vv
                guardar['mapa_tasa'] = np.array(float(clave.rsplit('_', 1)[1]))
            np.savez_compressed(os.path.join(out, f'{base}.npz'), **guardar)
            print(f'  guardado en {base}.npz\n')

            resumen['combinaciones'].append(
                dict(espectro=esp, modo=modo, cal=list(r['cal']), L0=r['L0'],
                     filas=r['filas']))

    with open(os.path.join(out, 'resumen.json'), 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=float)
    print(f'listo en {time.perf_counter()-t_ini:.0f} s -> {out}')
    print(f'ahora: python3 graficar.py {out}')
    return out


if __name__ == '__main__':
    main()
