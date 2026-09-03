#!/usr/bin/env python3
"""Qué compra el seguidor de línea de base, y si explica la deriva que falta.

Corre en la PC, sin placa.

LA PREGUNTA
-----------
El Monte-Carlo de apilamiento corre con base FIJA en 0 (`cfg_bl_auto = 0`): el
seguidor IIR es lo único del MCA que no modela. Y resulta que es el principal
sospechoso del límite dominante del instrumento. De
`docs/mca/limites_resolucion_y_deriva.md`:

    el apilamiento solo produce +0.29 % sobre x50 de tasa, mientras que la placa
    midió +1.28 % sobre x36. La deriva medida es ~4x más grande que lo que el
    apilamiento explica, así que hay un segundo mecanismo llevándose la mayor
    parte — y el sospechoso es justamente lo único que el MC no modela, el
    seguidor de línea de base.

Este script cierra esa pregunta: corre el MISMO estímulo con base fija y con
seguidor, y compara el corrimiento de centroide contra el +1.28 % medido.

QUÉ PERTURBA LA BASE
--------------------
  1. El PEDESTAL POR TASA, que no se inyecta: emerge solo, porque las colas de
     los pulsos vecinos levantan el nivel medio entre pulsos. Es lo que el
     seguidor debería cancelar.
  2. La DERIVA TÉRMICA, la única deriva temporal medida: 0.43 mV en ~18 min
     (`resumen_formas.json: deriva_replica_mv`). Se inyecta como rampa.

    python3 linea_base.py
    python3 linea_base.py --n-eventos 5000        # corrida rápida
    python3 linea_base.py --bl-k 12 --out DIR
"""
import argparse
import json
import os
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.join(_AQUI, '..', '..'))

import pileup as pu                                          # noqa: E402
import mca_utils as mu                                       # noqa: E402

N_CANALES = 16384
A_LINEA   = 1920.0        # amplitud de la línea, en cuentas (la de la campaña)
RES_PCT   = 3.0           # ancho intrínseco de la línea

# Las dos tasas de la campaña que midió el +1.28 % (resultados_validacion_hw.md
# §13). El barrido las incluye para que el contraste sea directo.
TASA_BAJA, TASA_ALTA = 1995.0, 72444.0
DERIVA_MEDIDA_PCT = 1.28          # medido en placa, x36 de tasa
APILAMIENTO_SOLO_PCT = 0.29       # lo que el MC ya explicaba, sin seguidor

TASAS = (TASA_BAJA, 5e3, 1e4, 2e4, 4e4, TASA_ALTA, 1.5e5, 3e5)

# Deriva térmica medida: 0.43 mV en ~18 min. En cuentas de ADC:
DERIVA_MV, DERIVA_SEG = 0.425, 18 * 60.0
DERIVA_CUENTAS = DERIVA_MV * 1e-3 * pu.ADC_CNT_PER_V          # ~3.5 cuentas

TRAIL = 128               # la ventana cierra en ~780, muy adentro del template


def _corrida(forma, tasa, n_ev, rng, bl_auto, bl_k, bl_holdoff=64,
             deriva_total=0.0):
    """Una adquisición completa a tasa `tasa`. Devuelve picos, base y estado.

    El seguidor se ENCADENA entre grupos con `avanzar_base`: el renderizado por
    grupos no materializa el tiempo muerto entre pulsos, pero el IIR sí corre
    ahí y converge. Sin eso la base quedaría enganchada al último grupo.

    `deriva_total` es la rampa térmica, en cuentas, repartida sobre toda la
    duración simulada.
    """
    amps = pu.sortear_amplitudes(n_ev, 'linea', rng, centro=A_LINEA,
                                 res_pct=RES_PCT)
    t_idx = pu.arribos_poisson(n_ev, tasa, rng=rng)
    n_total = int(t_idx[-1]) + forma.size

    picos, congeladas, bases, n_muestras = [], [], [], 0
    bl_acc = 0
    fin_prev = 0

    for a, b in pu.agrupar(t_idx, forma.size):
        dat, o = pu.render(t_idx[a:b], amps[a:b], forma, rng=rng, trail=TRAIL)

        # rampa térmica: el nivel DC en este tramo
        dc = deriva_total * (o / n_total) if n_total else 0.0
        if deriva_total:
            dat = dat + int(round(dc))

        # saltar el hueco quieto desde el final del grupo anterior
        if bl_auto:
            bl_acc = pu.avanzar_base(bl_acc, dc, o - fin_prev, bl_k)

        ev = pu.segmentar_base(dat, bl_auto=bl_auto, baseline=0, bl_k=bl_k,
                               bl_holdoff=bl_holdoff, traza_base=True,
                               bl_acc0=bl_acc if bl_auto else None,
                               **pu.CFG_MODO0)
        bl_acc = ev['bl_acc_fin']
        fin_prev = o + dat.size

        m = ev['cerrado']
        picos.append(ev['pico'][m])
        congeladas.append(ev['frac_congelada'] * dat.size)
        bases.append(ev['base'].mean() * dat.size)
        n_muestras += dat.size

    picos = np.concatenate(picos) if picos else np.zeros(0)
    return dict(picos=picos,
                frac_congelada=float(sum(congeladas) / max(n_muestras, 1)),
                base_media=float(sum(bases) / max(n_muestras, 1)),
                n_det=int(picos.size), n_gen=int(n_ev))


def _centroide(picos, suave=9):
    """Centroide y FWHM del fotopico, robustos al continuo de apilamiento.

    NO se usa `mca_utils.gauss_fit_peak` acá, y la razón es concreta: ese ajuste
    es log-cuadrático pesado sobre todos los bines con estadística de una ventana
    fija, y a tasa alta esa ventana se traga el continuo de apilamiento, que es
    fuertemente asimétrico (todo cae por encima de la línea). Medido sobre este
    mismo conjunto: dos espectros con moda 1925 y 1930 y medianas 1948 y 1944
    —o sea casi iguales— daban centroides ajustados de 1928 y 1877, con FWHM de
    122 y 306. La diferencia era del ajuste, no de los espectros.

    La mediana tampoco sirve: el continuo la arrastra hacia arriba (+1.3 % contra
    el +0.26 % real a 72 kcps).

    Lo que se hace es el método estándar de fotopico: moda sobre el histograma
    suavizado, FWHM por los cruces de media altura, y centroide pesado sobre
    ±1 FWHM alrededor de la moda. Esa ventana está dominada por eventos limpios,
    así que el continuo no la mueve.
    """
    h = np.bincount(np.clip(picos.astype(np.int64), 0, N_CANALES - 1),
                    minlength=N_CANALES).astype(float)
    if h.sum() < 50:
        return float('nan'), float('nan'), h

    # suavizado por media móvil, sólo para localizar la moda y los cruces
    ker = np.ones(int(suave)) / float(suave)
    hs = np.convolve(h, ker, mode='same')
    pk = int(np.argmax(hs))
    mitad = hs[pk] / 2.0

    izq = np.flatnonzero(hs[:pk] < mitad)
    der = np.flatnonzero(hs[pk:] < mitad)
    a = int(izq[-1]) if izq.size else max(pk - 200, 0)
    b = int(pk + der[0]) if der.size else min(pk + 200, N_CANALES - 1)
    fwhm = float(b - a)

    lo = max(int(pk - fwhm), 0)
    hi = min(int(pk + fwhm) + 1, N_CANALES)
    x = np.arange(lo, hi, dtype=float)
    w = h[lo:hi]
    c = float((x * w).sum() / w.sum()) if w.sum() > 0 else float('nan')
    return c, fwhm, h


def bloque_tasa(forma, n_ev, bl_k, semilla, verbose=True):
    """A. Barrido de tasa, base fija contra seguidor."""
    filas = []
    for bl_auto in (False, True):
        etiqueta = 'seguidor' if bl_auto else 'base fija'
        if verbose:
            print(f'\n  --- {etiqueta} ---')
            print(f'  {"tasa":>9} {"centroide":>10} {"corrim.":>9} {"FWHM":>7} '
                  f'{"base":>7} {"congel.":>8} {"n":>7}')
        for tasa in TASAS:
            rng = np.random.default_rng(semilla)      # mismo estímulo en ambos
            r = _corrida(forma, tasa, n_ev, rng, bl_auto, bl_k)
            c, fw, _ = _centroide(r['picos'])
            filas.append(dict(bl_auto=bool(bl_auto), tasa=float(tasa),
                              centroide=float(c), fwhm=float(fw),
                              base_media=r['base_media'],
                              frac_congelada=r['frac_congelada'],
                              n_det=r['n_det'], n_gen=r['n_gen']))
            if verbose:
                c0 = filas[0 if not bl_auto else len(TASAS)]['centroide']
                print(f'  {tasa:9.0f} {c:10.2f} {100*(c-c0)/c0:+8.2f} % '
                      f'{fw:7.2f} {r["base_media"]:7.2f} '
                      f'{100*r["frac_congelada"]:7.1f} % {r["n_det"]:7d}')
    return filas


def bloque_bl_k(forma, n_ev, semilla, tasa, ks=(3, 6, 9, 12, 15), verbose=True):
    """B. Barrido de bl_k. Con pulso de 2 us la placa lo midió PLANO."""
    filas = []
    if verbose:
        print(f'\n  a {tasa:.0f} cps')
        print(f'  {"bl_k":>5} {"tau":>10} {"centroide":>10} {"FWHM":>7} '
              f'{"base":>7} {"n":>7}')
    for k in ks:
        rng = np.random.default_rng(semilla)
        r = _corrida(forma, tasa, n_ev, rng, True, int(k))
        c, fw, _ = _centroide(r['picos'])
        filas.append(dict(bl_k=int(k), centroide=float(c), fwhm=float(fw),
                          base_media=r['base_media'], n_det=r['n_det'],
                          frac_congelada=r['frac_congelada']))
        if verbose:
            print(f'  {k:5d} {(1 << k)*8e-3:9.1f}us {c:10.2f} {fw:7.2f} '
                  f'{r["base_media"]:7.2f} {r["n_det"]:7d}')
    return filas


def bloque_deriva(forma, n_ev, bl_k, semilla, tasa=2e4, verbose=True):
    """C. Deriva térmica: rampa comprimida a la duración simulada.

    La rampa medida son 0.43 mV (3.5 cuentas) en 18 min. La corrida simulada
    dura n_ev/tasa segundos —con 15 k eventos a 20 kcps, 0.75 s— así que la
    rampa se COMPRIME a esa ventana. Sigue siendo ~10^4 veces más lenta que
    tau = 32.8 us, o sea que el seguidor la ve igual de cuasi-estática que en la
    placa: el régimen es el mismo y la conclusión vale. Lo que NO se puede leer
    de acá es la escala de tiempo, sólo el efecto de una rampa lenta.
    """
    filas = []
    dur = n_ev / tasa
    if verbose:
        print(f'\n  rampa de {DERIVA_CUENTAS:.2f} cuentas ({DERIVA_MV} mV) '
              f'comprimida a {dur:.2f} s de corrida')
        print(f'  (medida: {DERIVA_MV} mV en {DERIVA_SEG/60:.0f} min; '
              f'comprimir es {DERIVA_SEG/dur:.0f}x más rápido, y aun así '
              f'{dur/((1<<bl_k)*8e-9):.0f} taus)')
        print(f'  {"config":>12} {"deriva":>8} {"centroide":>10} {"FWHM":>7}')
    for bl_auto in (False, True):
        for deriva in (0.0, DERIVA_CUENTAS):
            rng = np.random.default_rng(semilla)
            r = _corrida(forma, tasa, n_ev, rng, bl_auto, bl_k,
                         deriva_total=deriva)
            c, fw, _ = _centroide(r['picos'])
            filas.append(dict(bl_auto=bool(bl_auto), deriva=float(deriva),
                              centroide=float(c), fwhm=float(fw),
                              n_det=r['n_det']))
            if verbose:
                print(f'  {"seguidor" if bl_auto else "base fija":>12} '
                      f'{deriva:8.2f} {c:10.2f} {fw:7.2f}')
    return filas


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n-eventos', type=int, default=15000)
    ap.add_argument('--bl-k', type=int, default=12, help='el default del driver')
    ap.add_argument('--semilla', type=int, default=0)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    forma, info = pu.forma_referencia()
    out = a.out or os.path.join(_AQUI, '..', '..', 'datos',
                                time.strftime('base_%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)

    print('=== seguidor de línea de base ===')
    print(f'  forma: FWHM {info["fwhm_pts"]:.0f} muestras '
          f'({info["fwhm_pts"]*1e6/pu.FS_HZ:.2f} µs), cola tau {info["tau"]:.0f}')
    print(f'  línea en {A_LINEA:.0f} cuentas, {RES_PCT} % de FWHM intrínseco')
    print(f'  bl_k = {a.bl_k} (tau = {(1 << a.bl_k)*8e-3:.1f} µs), '
          f'bl_holdoff = 64, {a.n_eventos} eventos por punto')
    print(f'  salida: {out}')

    t0 = time.perf_counter()
    print('\n=== A. barrido de tasa: base fija contra seguidor ===')
    filas_tasa = bloque_tasa(forma, a.n_eventos, a.bl_k, a.semilla)

    print('\n=== B. barrido de bl_k ===')
    filas_k = bloque_bl_k(forma, a.n_eventos, a.semilla, TASA_ALTA)

    print('\n=== C. deriva térmica ===')
    filas_d = bloque_deriva(forma, a.n_eventos, a.bl_k, a.semilla)

    # ------------------------------------------------------------------
    # El contraste que importa: x36 de tasa, 1995 -> 72444 Hz
    # ------------------------------------------------------------------
    def corrim(bl_auto):
        f = {r['tasa']: r['centroide'] for r in filas_tasa
             if r['bl_auto'] == bl_auto}
        return 100.0 * (f[TASA_ALTA] - f[TASA_BAJA]) / f[TASA_BAJA]

    d_fija, d_seg = corrim(False), corrim(True)
    print(f'\n=== VEREDICTO: corrimiento de centroide, '
          f'{TASA_BAJA:.0f} -> {TASA_ALTA:.0f} Hz (x36) ===')
    print(f'  placa (medido)                {DERIVA_MEDIDA_PCT:+7.2f} %')
    print(f'  MC con base fija              {d_fija:+7.2f} %   '
          f'(el MC anterior ya daba ~{APILAMIENTO_SOLO_PCT:+.2f} %)')
    print(f'  MC con seguidor (bl_k={a.bl_k})     {d_seg:+7.2f} %')
    falta = DERIVA_MEDIDA_PCT - d_fija
    explica = (d_seg - d_fija) / falta if falta else float('nan')
    print(f'\n  lo que el apilamiento NO explicaba: {falta:+.2f} %')
    print(f'  lo que agrega el seguidor:          {d_seg-d_fija:+.2f} %  '
          f'({100*explica:.0f} % de lo que faltaba)')
    if abs(d_seg) > abs(d_fija):
        print('  => el seguidor EMPEORA la deriva.')
    else:
        print('  => el seguidor MEJORA la deriva.')

    resumen = dict(n_eventos=a.n_eventos, bl_k=a.bl_k, semilla=a.semilla,
                   forma=info, tasas=list(TASAS), a_linea=A_LINEA,
                   res_pct=RES_PCT, deriva_cuentas=DERIVA_CUENTAS,
                   deriva_medida_pct=DERIVA_MEDIDA_PCT,
                   apilamiento_solo_pct=APILAMIENTO_SOLO_PCT,
                   tasa_baja=TASA_BAJA, tasa_alta=TASA_ALTA,
                   corrimiento_fija_pct=d_fija, corrimiento_seguidor_pct=d_seg,
                   tasa=filas_tasa, bl_k_barrido=filas_k, deriva=filas_d)
    with open(os.path.join(out, 'resumen.json'), 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=float)
    print(f'\nlisto en {time.perf_counter()-t0:.0f} s -> {out}')
    print(f'ahora: python3 graficar_base.py {out}')


if __name__ == '__main__':
    main()
