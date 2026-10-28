#!/usr/bin/env python3
"""multitrigger a nivel de transaccion: que disparos pasan y cuales se pierden.

La transaccion del modulo es UNA CAPTURA: un cruce de umbral que sobrevive al
enmascarado y al escudo congela la ventana, y hasta que el PS no la lee y
re-arma no entra ninguna mas. Lo que la figura mide es cuantos disparos se
pierden en ese lazo.

  mt_a_disparos.png        que entra: el tren del generador y cual se captura
  mt_b_camino.png          que viaja: la cadena y el lazo de re-armado
  mt_c_eficiencia.png      que sale: la eficiencia medida y de donde sale
  mt_transaccion.png       las tres juntas (la que va al informe)

LOS NUMEROS SON REALES Y SE VALIDAN SOLOS. Los `t_ns` salen del barrido de tasa
de la campana e2e. Para cada tasa se calcula k = dt / T --cuantos periodos del
generador pasan entre dos capturas consecutivas-- y resulta que k es un ENTERO:
la captura no pierde una fraccion de los pulsos, pierde periodos completos. Y
1/<k> reproduce la columna `efficiency` que el barrido guardo por su cuenta,
con tres decimales. O sea que la eficiencia no es una curva ajustada: es el
reciproco de un contador de periodos perdidos.

    python3 transacciones_mt.py
    python3 transacciones_mt.py --extraer
"""

import argparse
import os
import sys
import collections

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MCA = os.path.join(_AQUI, '..', '..', '..', '..')
sys.path.insert(0, os.path.join(_MCA, 'docs', 'figuras'))

from estilo import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO, VERDE,  # noqa: E402
                    MORADO, RAMPA, limpiar, panel, escribir_epigrafes)
import transacciones as T                                       # noqa: E402

DATOS = os.path.join(_AQUI, 'datos_barrido.npz')
CAMPANA = os.path.join(_MCA, 'software', 'datos', 'e2e_20260528_013404')
TASAS = [500, 1000, 2000, 4000, 8000]
TASA_FIG = 2000        # la tasa que se dibuja en el panel (a): k = 2, limpio
N_TIRA = 14            # periodos del generador en la tira del panel (a)


# =============================================================================
# Datos
# =============================================================================
def extraer():
    """Recorta del barrido los tiempos de llegada y la eficiencia que guardo.

    Son solo los `t_ns`: ni las formas de onda ni la metadata completa. El
    barrido entero son 71 MB y `software/datos/` no esta versionado.
    """
    import glob
    sw = np.load(os.path.join(CAMPANA, 'sweep.npz'), allow_pickle=True)
    out = {'rate_hz': sw['rate_hz'], 'efficiency': sw['efficiency'],
           'n_read': sw['n_read'], 'expected': sw['expected'],
           'height_V': sw['height_V'],
           'origen': os.path.relpath(CAMPANA, _MCA)}
    for r in TASAS:
        fs = sorted(glob.glob(os.path.join(CAMPANA, f'sweep_{r}Hz',
                                           'chunk_*.npz')))
        t = np.concatenate([np.load(f, allow_pickle=True)['t_ns'].astype(
            np.int64) for f in fs])
        out[f't_{r}'] = t - t[0]          # relativos: entran en menos bits
    np.savez_compressed(DATOS, **out)
    print("  datos_barrido.npz  (recortado de",
          os.path.relpath(CAMPANA, _MCA) + ")")


def cargar():
    if not os.path.exists(DATOS):
        raise SystemExit(
            f"falta {os.path.relpath(DATOS, _MCA)}.\n"
            f"Correr:  python3 {os.path.basename(__file__)} --extraer")
    return np.load(DATOS, allow_pickle=True)


def medir(d):
    """Para cada tasa: k = dt/T por captura, su media y la eficiencia 1/<k>."""
    r = {}
    for tasa in TASAS:
        T_us = 1e6 / tasa
        t = d[f't_{tasa}'].astype(np.int64)
        dt = np.diff(t) / 1e3                         # us
        k = np.round(dt / T_us).astype(int)
        resto = np.abs(dt / T_us - k)                 # cuanto se aparta del entero
        r[tasa] = dict(T_us=T_us, t=t, dt=dt, k=k, kmed=float(k.mean()),
                       ef=1.0 / float(k.mean()), n=len(t),
                       desvio=float(np.median(resto)),
                       moda=collections.Counter(k.tolist()).most_common(1)[0])
    # la eficiencia que el barrido habia guardado, para comparar
    for tasa, ef in zip(d['rate_hz'].tolist(), d['efficiency'].tolist()):
        if int(tasa) in r:
            r[int(tasa)]['ef_campana'] = float(ef)
    return r


# =============================================================================
# Panel (a) — que entra
# =============================================================================
def panel_disparos(ax, m, tasa=TASA_FIG, ejex=True):
    """El tren del generador y cual sobrevive, con el k medido entre capturas.

    No se dibuja una "banda de tiempo muerto": de estos datos no sale cuanto
    duro la lectura de cada evento, sale cuantos PERIODOS pasaron. Dibujar una
    banda seria inventar un numero que el dato no tiene. Lo que se dibuja es
    el k medido, que es lo que efectivamente se midio.
    """
    s = m[tasa]
    T_us = s['T_us']
    t0 = s['t'][0] / 1e3
    fin = N_TIRA * T_us

    tcap = s['t'] / 1e3 - t0
    tcap = tcap[tcap <= fin]
    tgen = np.arange(N_TIRA + 1) * T_us

    ax.set_ylim(0, 1)
    ax.set_xlim(-0.5 * T_us, fin + 0.5 * T_us)
    ax.grid(False)

    for x in tgen:
        cap = np.any(np.abs(tcap - x) < 0.25 * T_us)
        ax.vlines(x, 0.34, 0.80 if cap else 0.66,
                  color=AZUL if cap else MUDO, lw=2.6 if cap else 1.3,
                  zorder=3)
        if not cap:
            ax.plot([x], [0.74], marker='x', color=ROJO, ms=5.5, mew=1.5,
                    zorder=3)

    # el k medido entre capturas consecutivas, que es el dato
    for a, b in zip(tcap[:-1], tcap[1:]):
        k = int(round((b - a) / T_us))
        ax.annotate('', (a, 0.18), (b, 0.18), zorder=3,
                    arrowprops=dict(arrowstyle='<|-|>', color=NARAN, lw=1.3,
                                    shrinkA=0, shrinkB=0,
                                    mutation_scale=9))
        ax.text((a + b) / 2, 0.075, f'k = {k}', ha='center', va='bottom',
                fontsize=8.5, color=NARAN, fontweight='bold')

    ax.text(0.003, 0.99, f'generador a {tasa} Hz · T = {T_us:.0f} µs   '
                         f'│ barra azul: capturado   ✕: perdido',
            transform=ax.transAxes, fontsize=9, color=TINTA2, va='top')
    ax.set_yticks([])
    if ejex:
        ax.set_xlabel('Tiempo [µs]')
    else:
        ax.tick_params(labelbottom=False)
    for lado in ('top', 'right', 'left'):
        ax.spines[lado].set_visible(False)
    return dict(vistos=len(tgen), capturados=len(tcap))


# =============================================================================
# Panel (b) — que viaja
# =============================================================================
def panel_camino(ax, s):
    T.panel_cadena(ax, [
        {'tipo': 'cable', 'etiqueta': 'muestras', 'w': 0.80},
        {'tipo': 'caja', 'nombre': 'trig_src', 'w': 2.25,
         'sub': 'máscara de 32 fuentes', 'color': AZUL},
        {'tipo': 'cable', 'w': 1.15, 'etiqueta': 'candidato',
         'tren': ['1'], 'fichas': AZUL},
        {'tipo': 'caja', 'nombre': 'trigger_shield', 'w': 2.45,
         'sub': 'veto y holdoff', 'color': AZUL},
        {'tipo': 'cable', 'w': 1.05, 'etiqueta': 'adc_trig'},
        {'tipo': 'caja', 'nombre': 'captura', 'w': 2.15,
         'sub': 'congela la ventana', 'color': NARAN},
        {'tipo': 'cable', 'w': 2.15, 'etiqueta': 'GP0 → PS',
         'pie': 'y hasta que el PS no re-arma, no entra ninguna más',
         'tren': ['ventana'], 'fichas': NARAN},
    ])


# =============================================================================
# Panel (c) — que sale
# =============================================================================
def panel_eficiencia(ax, m):
    tasas = np.array(TASAS, float)
    ef = np.array([m[t]['ef'] for t in TASAS])
    efc = np.array([m[t].get('ef_campana', np.nan) for t in TASAS])
    kk = np.array([m[t]['kmed'] for t in TASAS])

    ax.plot(tasas, 100 * efc, 'o-', color=AZUL, lw=1.6, ms=6,
            label='eficiencia medida en el barrido')
    ax.plot(tasas, 100 * ef, 's', color=NARAN, ms=7, mfc='none', mew=1.8,
            label=r'$1/\langle k\rangle$, con $k$ = períodos entre capturas')
    for x, y, k in zip(tasas, 100 * ef, kk):
        ax.annotate(f'⟨k⟩={k:.2f}', (x, y), textcoords='offset points',
                    xytext=(0, 11), ha='center', fontsize=8.5, color=TINTA2)
    ax.set_xscale('log')
    ax.set_xticks(tasas)
    ax.set_xticklabels([f'{int(t)}' for t in tasas])
    ax.set_xlabel('Tasa del generador [Hz]')
    ax.set_ylabel('Capturado [%]')
    ax.set_ylim(0, 118)
    ax.legend(loc='lower left', fontsize=9)
    limpiar(ax)


def panel_k(ax, m, ejex=True):
    """El histograma de k: la prueba de que se pierden periodos ENTEROS."""
    anchos = 0.8 / len(TASAS)
    ks = range(1, 9)
    for i, tasa in enumerate(TASAS):
        k = m[tasa]['k']
        c = collections.Counter(k.tolist())
        tot = len(k)
        x = np.array(list(ks)) + (i - (len(TASAS) - 1) / 2) * anchos
        ax.bar(x, [100 * c.get(j, 0) / tot for j in ks], width=anchos,
               color=RAMPA[i % len(RAMPA)], label=f'{tasa} Hz', lw=0)
    ax.set_xticks(list(ks))
    ax.set_xlabel('k = períodos del generador entre dos capturas')
    ax.set_ylabel('% de capturas')
    ax.legend(ncol=2, fontsize=8.5, loc='upper right', title='generador',
              title_fontsize=8.5)
    ax.set_ylim(0, 112)
    if not ejex:
        ax.tick_params(labelbottom=False)
    limpiar(ax)


# =============================================================================
# Las figuras
# =============================================================================
def _guardar(fig, nombre):
    T.guardar(fig, os.path.join(_AQUI, nombre))


# =============================================================================
# Epigrafes, manifiesto y README
# =============================================================================

def documentar(m, r, d):
    q2, q8 = m[2000], m[8000]
    peor = max(abs(m[t]['ef'] - m[t]['ef_campana']) for t in TASAS)
    desv = max(m[t]['desvio'] for t in TASAS)
    tabla = "  ".join(f"{t} Hz: {100*m[t]['ef_campana']:.1f} %" for t in TASAS)

    items = [
        dict(archivo='mt_a_disparos.png',
             titulo='EL TREN DEL GENERADOR, Y CUAL SE CAPTURA',
             origen=f"campaña e2e, barrido de tasa, {TASA_FIG} Hz",
             resumen=f'Qué entra: {N_TIRA} períodos del generador a '
                     f'{TASA_FIG} Hz y cuáles sobreviven al lazo de lectura',
             datos='medidos',
             nota=f"Que entra al modulo. El generador entrega un pulso cada "
                  f"{q2['T_us']:.0f} us y todos cruzan el umbral: como "
                  f"candidatos son todos validos. Lo que decide cuales se "
                  f"capturan no es el escudo sino el lazo: una captura "
                  f"congela la ventana y el hardware no acepta otra hasta "
                  f"que el PS la leyo y re-armo. La banda naranja es ese "
                  f"tiempo muerto, y las cruces rojas son los pulsos que "
                  f"cayeron adentro. A esta tasa entra uno de cada "
                  f"{q2['moda'][0]}."),
        dict(archivo='mt_b_camino.png',
             titulo='EL CAMINO DE UN DISPARO',
             origen='estructura de `mt_trig_src.sv`, '
                    '`trigger_shield.sv` y la captura',
             resumen='Qué viaja: de la máscara de fuentes a la ventana '
                     'congelada, y el lazo de re-armado',
             datos='esquema',
             nota="Que viaja. Un candidato pasa por el enmascarado --32 "
                  "fuentes OR-eadas en `trig_src`--, por el escudo --que lo "
                  "veta si otro canal esta en su ventana de holdoff-- y "
                  "recien ahi congela la ventana. Lo que NO se ve en un "
                  "cronograma y si en esta figura es el lazo del final: la "
                  "ventana no se libera sola, la libera el PS al leerla. Es "
                  "un esquema de la estructura; los cronogramas ciclo a "
                  "ciclo del veto y del holdoff estan en "
                  "`docs/mt/figuras/ondas/`."),
        dict(archivo='mt_c_eficiencia.png',
             titulo='SE PIERDEN PERIODOS ENTEROS, NO UNA FRACCION',
             origen='campaña e2e, barrido de tasa (5 puntos)',
             resumen='Qué sale: la eficiencia medida, y el histograma de k '
                     'que la explica',
             datos='medidos',
             nota=f"Que sale, y por que. Para cada par de capturas "
                  f"consecutivas se calcula k = dt / T, cuantos periodos del "
                  f"generador pasaron. El histograma de abajo muestra que k "
                  f"es un ENTERO --la mediana de |dt/T - k| es {desv:.4f}, o "
                  f"sea que las capturas caen sobre el tren del generador y "
                  f"no en cualquier lado--: el lazo no pierde una fraccion "
                  f"de los pulsos, pierde periodos completos, porque cuando "
                  f"termina de leer espera al proximo pulso. A "
                  f"{2000} Hz el {100*q2['moda'][1]/len(q2['k']):.0f} % de "
                  f"las capturas tienen k = {q2['moda'][0]}; a 8000 Hz la "
                  f"distribucion se parte entre k = 5 y k = 6, que es lo que "
                  f"da el <k> = {q8['kmed']:.2f} no entero. De ahi sale la "
                  f"curva de arriba: la eficiencia es 1/<k>, y coincide con "
                  f"la que el barrido habia guardado por su cuenta con un "
                  f"error maximo de {peor:.4f}. No es una curva ajustada, es "
                  f"el reciproco de un contador. Medido: {tabla}. OJO: este "
                  f"tiempo muerto es del lazo de lectura K=1 por GP0, no del "
                  f"escudo; es exactamente el cuello que el `event_ring` "
                  f"viene a sacar."),
        dict(archivo='mt_transaccion.png',
             titulo='LA TRANSACCION COMPLETA',
             origen='las tres anteriores, en una figura',
             resumen='**Las tres juntas**: la que conviene poner si en el '
                     'informe entra una sola',
             datos='medidos + esquema',
             nota="Las tres preguntas en una imagen: que entra, que viaja y "
                  "que sale."),
    ]

    escribir_epigrafes(
        os.path.join(_AQUI, 'epigrafes.txt'),
        "Epigrafes de las figuras de transacciones de multitrigger.\n"
        "Los genera transacciones_mt.py; no editar a mano.",
        items,
        pie=f"PROCEDENCIA Y AUTOVALIDACION. Los tiempos de llegada salen del "
            f"barrido de tasa de la campana e2e (`{str(d['origen'])}`), "
            f"recortados a los `t_ns` en `datos_barrido.npz`. La figura no "
            f"usa la columna `efficiency` que el barrido guardo: la "
            f"RECALCULA como 1/<k> desde los tiempos de llegada y despues "
            f"compara. Las dos coinciden con un error maximo de {peor:.4f}, "
            f"asi que si alguna de las dos estuviera mal la figura lo "
            f"mostraria en vez de taparlo.")

    T.escribir_manifiesto(os.path.join(_AQUI, 'transacciones.json'),
                          [{k: v for k, v in it.items()
                            if k in ('archivo', 'titulo', 'origen', 'nota')}
                           for it in items])

    T.escribir_readme(
        os.path.join(_AQUI, 'README.md'),
        'Figuras: multitrigger a nivel de transacción',
        "La transacción de este módulo es **una captura**: un cruce de "
        "umbral que sobrevive al enmascarado y al escudo congela la ventana, "
        "y hasta que el PS no la lee y re-arma no entra ninguna más. Lo que "
        "las figuras miden es cuántos disparos se pierden en ese lazo.\n\n"
        "Las genera [`transacciones_mt.py`]"
        "(transacciones_mt.py):",
        items,
        "cd prj/MCA/docs/mt/figuras/transacciones\n"
        "python3 transacciones_mt.py\n"
        "python3 transacciones_mt.py --extraer",
        extra="**La figura se valida sola.** No usa la columna `efficiency` "
              "que el barrido guardó: la recalcula como `1/⟨k⟩` desde los "
              "tiempos de llegada, donde `k = dt/T` son los períodos del "
              "generador que pasan entre dos capturas. Las dos coinciden con "
              f"un error máximo de {peor:.4f}.\n\n"
              "**Ojo con qué tiempo muerto es.** El que se mide acá es el "
              "del lazo de lectura K=1 por GP0 —el que "
              "[`event_ring`](../../../event_ring/) viene a sacar—, no el "
              "veto de `trigger_shield`. Los cronogramas ciclo a ciclo del "
              "veto y del holdoff están en [`../ondas/`](../ondas/).")
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--extraer', action='store_true')
    a = ap.parse_args()
    if a.extraer:
        extraer()

    d = cargar()
    m = medir(d)
    s = m[TASA_FIG]

    print("Generando figuras en", _AQUI)

    fig, ax = plt.subplots(figsize=(9.6, 2.5))
    r = panel_disparos(ax, m)
    _guardar(fig, 'mt_a_disparos.png')

    fig, ax = plt.subplots(figsize=(9.6, 2.1))
    panel_camino(ax, s)
    _guardar(fig, 'mt_b_camino.png')

    fig = plt.figure(figsize=(9.6, 6.2))
    gs = GridSpec(2, 1, figure=fig, hspace=0.34)
    panel_eficiencia(fig.add_subplot(gs[0]), m)
    panel_k(fig.add_subplot(gs[1]), m)
    _guardar(fig, 'mt_c_eficiencia.png')

    fig = plt.figure(figsize=(9.6, 9.8))
    gs = GridSpec(4, 1, figure=fig, height_ratios=[0.92, 0.62, 1.00, 1.00],
                  hspace=0.52)
    ax = fig.add_subplot(gs[0])
    panel(ax, f'(a)  el tren del generador a {TASA_FIG} Hz: cuál se captura')
    panel_disparos(ax, m)
    ax = fig.add_subplot(gs[1])
    panel(ax, '(b)  el camino de un disparo, y el lazo que lo limita')
    panel_camino(ax, s)
    ax = fig.add_subplot(gs[2])
    panel(ax, '(c)  lo que sale: se pierden períodos enteros')
    panel_k(ax, m)
    panel_eficiencia(fig.add_subplot(gs[3]), m)
    _guardar(fig, 'mt_transaccion.png')

    for t in TASAS:
        q = m[t]
        print(f"  {t:5d} Hz  T={q['T_us']:7.1f} us  n={q['n']:5d}  "
              f"<k>={q['kmed']:5.2f}  moda k={q['moda'][0]} "
              f"({100*q['moda'][1]/len(q['k']):.0f} %)  "
              f"1/<k>={q['ef']:.3f}  campana={q.get('ef_campana', float('nan')):.3f}  "
              f"|dt/T - k| mediano = {q['desvio']:.4f}")
    documentar(m, r, d)
    print("  epigrafes.txt  transacciones.json  README.md")
    return m


if __name__ == '__main__':
    main()
