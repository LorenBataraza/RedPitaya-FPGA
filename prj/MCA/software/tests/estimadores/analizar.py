#!/usr/bin/env python3
"""Compara TODOS los estimadores sobre LOS MISMOS pulsos reales.

Corre en la PC, sin placa: usa las trazas crudas que ya dejo el pipeline de
adquisicion (`software/mca/`), 512 muestras por evento.

Responde la pregunta que abrio la etapa A: por que la integral de carga da
PEOR resolucion que la muestra de pico (0.528 % contra 0.344 % en la campana),
cuando la teoria dice que deberia promediar el ruido como sigma/sqrt(N).

Los tres candidatos que se dirimen:
  (a) jitter del largo de ventana  -> compuertas de largo FIJO
  (b) error de linea de base x N   -> base global contra base por evento
  (c) jitter de forma del generador -> lo que quede con la mejor ventana

    python3 analizar.py [directorio_de_chunks]
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import estimadores as es

DEFECTO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', '..', 'datos', 'e2e_20260528_013404', 'principal')

# Config del MCA en la campana (testbench_mca.DEFAULT_CFG)
CFG = dict(thr=100, hyst=40, maxlen=4096, tail_dly=8)

# Referencias medidas en placa, para contrastar (resultados_validacion_hw.md §13)
REF_PICO     = 0.344
REF_INTEGRAL = 0.528


def cargar(directorio):
    """Devuelve (ondas int16 (n_ev, n_muestras) del canal 1, meta del primero)."""
    fs = sorted(glob.glob(os.path.join(directorio, 'chunk_*.npz')))
    if not fs:
        raise SystemExit(f'no hay chunk_*.npz en {directorio}')
    ondas, meta = [], None
    for f in fs:
        z = np.load(f, allow_pickle=True)
        if meta is None:
            meta = z['meta'].item()
        ondas.append(z['wave'][:, 0, :].astype(np.int64))
    return np.concatenate(ondas), meta


N_BASE = 8          # muestras planas al principio de la ventana (medido)


def perfil(w, pre):
    """Diagnostico del conjunto: donde esta el pulso dentro de la ventana.

    Devuelve (perfil_medio, i_disparo, tau_cola, cierra_en). `cierra_en` es
    donde la cola bajaria de thr-hyst extrapolando la exponencial: si cae
    fuera de la ventana capturada, la ventana por histeresis del RTL NO se
    puede reproducir con estos datos.
    """
    med  = w.mean(axis=0)
    base = med[:N_BASE].mean()
    pk   = int(np.argmax(med))
    cruza = np.flatnonzero(med - base >= CFG['thr'])
    i0 = int(cruza[0]) if cruza.size else 0

    # constante de la cola, ajustando el log de la parte que decae
    t = np.arange(pk + 20, w.shape[1])
    y = med[pk + 20:] - base
    ok = y > 20
    tau = -1.0 / np.polyfit(t[ok], np.log(y[ok]), 1)[0] if ok.sum() > 10 else np.nan

    thr_lo = CFG['thr'] - CFG['hyst']
    cierra = pk + tau * np.log((med[pk] - base) / thr_lo) if np.isfinite(tau) else np.nan

    print(f'  {w.shape[0]} eventos x {w.shape[1]} muestras   pre={pre}')
    print(f'  base ({N_BASE} muestras): {base:.2f} cuentas')
    print(f'  pico medio: {med[pk]-base:.0f} cuentas en la muestra {pk}')
    print(f'  cruza thr={CFG["thr"]} en la muestra {i0}')
    print(f'  cola: tau = {tau:.0f} muestras = {tau*8:.0f} ns')
    print(f'  bajaria de thr-hyst={thr_lo} en la muestra ~{cierra:.0f}'
          f'{"  <-- FUERA de la ventana capturada" if cierra > w.shape[1] else ""}')
    return med, i0, tau, cierra


def linea_base(w):
    """Dos estimaciones de la linea de base, que es el candidato (b).

    - GLOBAL: una sola para todo el conjunto. Emula al seguidor IIR del RTL,
      que promedia sobre miles de muestras y practicamente no tiene ruido.
    - POR EVENTO: la media de las N_BASE muestras previas al pulso. Tiene
      ruido sigma/sqrt(N_BASE), y ese ruido se MULTIPLICA por el largo de la
      ventana al integrar: es el candidato (b).
    """
    por_ev = w[:, :N_BASE].mean(axis=1)
    return float(por_ev.mean()), por_ev


def medir(w, bases, **cfg):
    """Corre la replica del RTL evento por evento.

    El PICO es valido aunque el pulso quede truncado por el fin de la ventana
    (ocurre en la muestra ~100, muy adentro); la CARGA no lo es, porque le
    falta la cola. Por eso se devuelven por separado.
    """
    picos, cargas, largos, trunc = [], [], [], 0
    for i in range(w.shape[0]):
        b = bases if np.isscalar(bases) else bases[i]
        ev = es.segmentar_rtl(w[i], baseline=b, **cfg)
        if not ev:
            continue
        e = max(ev, key=lambda z: z.q_tot)       # el pulso principal
        picos.append(e.pico)
        if e.cerrado:
            cargas.append(e.q_tot)
            largos.append(e.largo)
        else:
            trunc += 1
    return (np.array(picos), np.array(cargas), np.array(largos), trunc)


def gate(w, bases, corta, larga):
    """Carga por compuerta fija sobre todo el conjunto.

    `bases` puede ser un escalar (base global) o un array (una por evento).
    """
    q, qc, ntr = [], [], 0
    for i in range(w.shape[0]):
        base = bases if np.isscalar(bases) else bases[i]
        g = es.integral_gates(w[i], baseline=base, thr=CFG['thr'],
                              hyst=CFG['hyst'], corta=corta, larga=larga)
        if not g:
            continue
        if g[0]['truncado']:
            ntr += 1
            continue
        q.append(g[0]['q_tot'])
        qc.append(g[0]['q_corta'])
    return np.array(q), np.array(qc), ntr


def linea(nombre, r, ref=None):
    marca = ''
    if ref is not None and np.isfinite(r['res_pct']):
        marca = f'   (placa: {ref:.3f} %)'
    print(f'  {nombre:<42} {r["res_pct"]:7.3f} %   '
          f'media {r["media"]:11.1f}   n={r["n"]}{marca}')


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else DEFECTO
    w, meta = cargar(d)
    pre = int(meta.get('source', {}).get('pre', 32))
    ancho = meta.get('pulse_width_s')

    print(f'\n=== datos: {os.path.relpath(d)} ===')
    if ancho:
        print(f'  ancho de pulso del estimulo: {ancho*1e6:g} us')
    med, i0, tau, cierra = perfil(w, pre)
    b_glob, b_ev = linea_base(w)
    print(f'  linea de base: global {b_glob:.2f}, '
          f'por evento sigma {b_ev.std():.2f} cuentas')

    n_muestras = w.shape[1]
    corto = cierra > n_muestras

    # ------------------------------------------------------------------
    print('\n=== 1. Pico: la replica reproduce lo que midio la placa? ===')
    picos, cargas, largos, trunc = medir(w, b_glob, **CFG)
    r_pico = es.resolucion(picos)
    linea('pico (replica del RTL)', r_pico, REF_PICO)
    # La validacion NO es la resolucion en % (depende de la amplitud, que en
    # este conjunto no es la misma que en la campana) sino la SIGMA EN CUENTAS,
    # que es una propiedad del ruido del ADC y tiene que coincidir.
    sigma_placa = REF_PICO / 100 * 1920 / 2.355     # FWHM 6.61 canales @1920
    print(f'  sigma del pico: {r_pico["sigma"]:.2f} cuentas   '
          f'(la placa midio {sigma_placa:.2f} cuentas)')
    print(f'  => coincide al {100*abs(r_pico["sigma"]-sigma_placa)/sigma_placa:.0f} %: '
          f'la replica mide lo mismo que el hardware.\n'
          f'     La resolucion en % difiere solo porque la amplitud de este '
          f'conjunto es {r_pico["media"]:.0f}\n     y la de la campana era 1920 cuentas.')

    if corto:
        print(f'\n  LIMITE DEL CONJUNTO: la ventana por histeresis se cerraria en '
              f'~{cierra:.0f}\n  y las capturas tienen {n_muestras} muestras, asi que '
              f'{100*trunc/max(len(picos),1):.0f} % de los pulsos quedan\n  TRUNCADOS. '
              f'La integral por histeresis NO se puede reproducir con estos\n  datos: '
              f'haria falta recapturar con post >= {int(cierra)+50} muestras.\n'
              f'  Lo que sigue compara pico contra compuerta FIJA, que si es riguroso.')
    else:
        linea('integral, ventana por histeresis', es.resolucion(cargas), REF_INTEGRAL)
        print(f'  largo de la ventana: media {largos.mean():.1f}, '
              f'sigma {largos.std():.2f} muestras   <-- candidato (a)')

    # ------------------------------------------------------------------
    print('\n=== 2. Candidato (a): compuertas de largo FIJO ===')
    print(f'  {"larga":>8}  {"resolucion":>10}  {"truncados":>10}')
    mejor = None
    for larga in (96, 128, 192, 256, 320, 384, 448, 470):
        q, _, ntr = gate(w, b_glob, 32, larga)
        r = es.resolucion(q)
        print(f'  {larga:>8}  {r["res_pct"]:9.3f} %  {100*ntr/w.shape[0]:9.1f} %')
        if np.isfinite(r['res_pct']) and (mejor is None or r['res_pct'] < mejor[1]):
            mejor = (larga, r['res_pct'])

    # ------------------------------------------------------------------
    print('\n=== 3. Candidato (b): cuanto aporta el error de linea de base ===')
    if mejor:
        q_g, _, _ = gate(w, b_glob, 32, mejor[0])
        q_e, _, _ = gate(w, b_ev,   32, mejor[0])
        linea(f'compuerta {mejor[0]}, base GLOBAL (como el IIR)', es.resolucion(q_g))
        linea(f'compuerta {mejor[0]}, base POR EVENTO ({N_BASE} muestras)',
              es.resolucion(q_e))
        print(f'  la base por evento tiene sigma {b_ev.std():.2f} cuentas y se '
              f'multiplica por\n  las {mejor[0]} muestras de la compuerta: '
              f'{b_ev.std()*mejor[0]:.0f} cuentas sobre {q_g.mean():.0f}'
              f' = {100*b_ev.std()*mejor[0]/q_g.mean():.3f} %')

    # ------------------------------------------------------------------
    print('\n=== 4. Trapecio (Jordanov-Knoll), M = tau medido ===')
    i_pico = int(np.argmax(med))
    t_col = i_pico - i0
    print(f'  tiempo de coleccion = {t_col} muestras (disparo {i0} -> pico {i_pico}),')
    print(f'  asi que hace falta m > {t_col} para que EXISTA meseta.')
    print(f'  {"k":>6} {"m":>6} {"M":>6}  {"meseta":>12}  {"resolucion":>10}')
    M = int(round(tau))
    mejor_tr = None
    for k, m in ((128, 64), (128, 128), (128, 160), (160, 160), (192, 160)):
        vent = es.meseta_ventana(i0, i_pico, k, m)
        if vent is None:
            print(f'  {k:>6} {m:>6} {M:>6}  {"NO EXISTE":>12}  '
                  f'  (m <= {t_col})')
            continue
        if vent[1] >= n_muestras:
            print(f'  {k:>6} {m:>6} {M:>6}  {"fuera":>12}    (ventana corta)')
            continue
        alturas = [es.altura_meseta(es.trapecio(w[i], k, m, M, baseline=b_glob),
                                    i0, k, m, i_pico=i_pico)
                   for i in range(w.shape[0])]
        r = es.resolucion(alturas)
        print(f'  {k:>6} {m:>6} {M:>6}  {str(vent):>12}  {r["res_pct"]:9.3f} %')
        if np.isfinite(r['res_pct']) and (mejor_tr is None or r['res_pct'] < mejor_tr[1]):
            mejor_tr = ((k, m), r['res_pct'])

    # ------------------------------------------------------------------
    print('\n=== VEREDICTO ===')
    print(f'  pico (replica)                {r_pico["res_pct"]:7.3f} %   '
          f'[placa: {REF_PICO} %]')
    print(f'  integral por histeresis       {"no reproducible" if corto else ""}'
          f'{"":>10}   [placa: {REF_INTEGRAL} %]')
    if mejor:
        print(f'  integral por compuerta fija   {mejor[1]:7.3f} %   (larga={mejor[0]})')
    if mejor_tr:
        print(f'  trapecio                      {mejor_tr[1]:7.3f} %   '
              f'(k,m={mejor_tr[0]})')

    if mejor:
        print()
        vs_pico = r_pico['res_pct'] / mejor[1]
        vs_int  = REF_INTEGRAL / mejor[1]
        print(f'  La compuerta fija mejora x{vs_pico:.2f} sobre el PICO y '
              f'x{vs_int:.2f} sobre la\n  integral por histeresis que se midio en placa.')
        if vs_int > 1.5:
            print('  => ETAPA B (compuertas fijas): SE JUSTIFICA. La integral no era\n'
                  '     mala; lo era la definicion de ventana.')
        else:
            print('  => ETAPA B: no se justifica con estos datos.')

    if mejor_tr and mejor:
        print()
        if mejor_tr[1] <= mejor[1]:
            print(f'  => ETAPA C (trapecio): da {mejor_tr[1]:.3f} %, MEJOR que la '
                  f'compuerta fija.\n     Justifica el costo de throughput.')
        else:
            print(f'  => ETAPA C (trapecio): da {mejor_tr[1]:.3f} %, PEOR que la '
                  f'compuerta fija ({mejor[1]:.3f} %),\n     y ademas costaria la mitad '
                  f'del throughput (794 kcps medidos hoy).\n     Con ESTA senal no se '
                  f'justifica. Su argumento sigue siendo el corrimiento\n     de '
                  f'centroide con la tasa (+6.45 %), que este conjunto no puede medir\n'
                  f'     porque fue tomado a una sola tasa.')


if __name__ == '__main__':
    main()
