#!/usr/bin/env python3
"""dsp_tap_mux a nivel de transaccion: la misma muestra vista desde cuatro nodos.

Hay UNA sola cadena de acondicionado por canal y cuatro nodos utilizables sobre
ella. Cada consumidor --osciloscopio, multitrigger y MCA-- tiene su propio
dsp_tap_mux 4:1 y elige en runtime de cual toma sus muestras. La transaccion de
este modulo es, entonces, UNA MUESTRA Y SU VALID: lo que cambia entre nodos no
es solo el valor, es el RITMO.

  comun_a_pulso.png        que entra: el pulso al ritmo del ADC
  comun_b_taps.png         que viaja: la cadena, los cuatro nodos y los muxes
  comun_c_nodos.png        que sale: el mismo pulso en los cuatro nodos
  comun_transaccion.png    las tres juntas (la que va al informe)

QUE ES MEDIDO Y QUE ES MODELO, porque aca no es todo lo mismo:

  - el pulso de entrada es MEDIDO (la misma captura que usa event_ring);
  - el diezmado con promediado y el retardo son EXACTOS: son un promedio de
    bloque de N y un corrimiento de K muestras, y se calculan aca;
  - la calibracion (offset + ganancia) es una etapa de la cadena que esta
    captura ya atraveso, asi que no se puede deshacer ni re-aplicar: se dibuja
    como etapa pero NO se le inventan coeficientes. Por eso los nodos A y B
    salen iguales en la figura, y el epigrafe lo dice.

    python3 transacciones_comun.py
"""

import argparse
import os
import sys

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MCA = os.path.join(_AQUI, '..', '..', '..', '..')
sys.path.insert(0, os.path.join(_MCA, 'docs', 'figuras'))

from estilo import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO, VERDE,  # noqa: E402
                    MORADO, RAMPA, limpiar, panel, escribir_epigrafes)
import transacciones as T                                       # noqa: E402

# La misma captura que event_ring: una sola copia del dato en el repo.
DATOS = os.path.join(_MCA, 'docs', 'event_ring', 'figuras', 'transacciones',
                     'datos_e2e.npz')
EV, CH = 1, 0
DEC = 8                # cfg_dec del dibujo: suficiente para ver el estrobo
DLY = 4                # retardo de disparo, en muestras diezmadas
                       # (chico a proposito: con el retardo real el
                       #  nodo D se iria de la ventana dibujada)
VENTANA = (0, 160)     # muestras del pulso que se dibujan

NODOS = [
    ('A', 'adc_calib_in', 'tap 1 · ADC', 'crudo', RAMPA[4]),
    ('B', 'adc_dec_in', 'tap 2 · DEC_IN', 'post-calibración', RAMPA[2]),
    ('C', 'adc_dly_in', 'sin código de tap', 'post-diezmado', MORADO),
    ('D', 'adc_bram_in', 'tap 3 · BRAM_IN', 'post-retardo', NARAN),
]


def cargar():
    if not os.path.exists(DATOS):
        raise SystemExit(
            f"falta {os.path.relpath(DATOS, _MCA)}.\n"
            f"Correr:  python3 docs/event_ring/figuras/transacciones/"
            f"transacciones_event_ring.py --extraer")
    return np.load(DATOS, allow_pickle=True)


def cadena(x, dec=DEC, dly=DLY):
    """Los cuatro nodos sobre la misma muestra.

    Devuelve, por nodo, (indices de muestra validos, valores). Los indices son
    lo que hace la figura: en A y B hay uno por ciclo y en C y D uno cada
    `dec`, que es el estrobo del que habla la cabecera de dsp_tap_mux.sv.
    """
    n = len(x)
    iA = np.arange(n)
    vA = x.astype(float)

    # calib: offset + ganancia. Esta captura YA paso por aca, y el .npz no
    # guarda los coeficientes, asi que re-aplicarlos seria inventarlos.
    iB, vB = iA, vA

    # rp_decim con promediado: promedio de bloque de `dec` muestras, y el
    # resultado sale una vez cada `dec` ciclos.
    nb = n // dec
    vC = vB[:nb * dec].reshape(nb, dec).mean(axis=1)
    iC = np.arange(nb) * dec + (dec - 1)        # sale al cerrar el bloque

    # rp_delay: el mismo flujo, corrido `dly` muestras diezmadas
    iD, vD = iC + dly * dec, vC
    return {'A': (iA, vA), 'B': (iB, vB), 'C': (iC, vC), 'D': (iD, vD)}


# =============================================================================
# Paneles
# =============================================================================
def panel_pulso(ax, x, ejex=True):
    a, b = VENTANA
    n = np.arange(a, b)
    ax.plot(n, x[a:b], lw=1.2, color=RAMPA[4])
    ax.plot(n, x[a:b], '.', ms=2.6, color=RAMPA[4])
    ax.set_ylabel('cuentas de ADC')
    ax.set_xlim(a, b - 1)
    ax.text(0.985, 0.08, '125 MSPS · una muestra por ciclo, sin estrobo',
            transform=ax.transAxes, ha='right', va='bottom', fontsize=9,
            color=TINTA2)
    if ejex:
        ax.set_xlabel('Ciclo de adc_clk')
    else:
        ax.tick_params(labelbottom=False)
    limpiar(ax)


def panel_taps(ax):
    T.panel_cadena(ax, [
        {'tipo': 'cable', 'etiqueta': 'ADC', 'w': 0.75},
        {'tipo': 'caja', 'nombre': 'calib', 'w': 1.75,
         'sub': 'offset + ganancia', 'color': AZUL},
        {'tipo': 'cable', 'w': 0.70, 'etiqueta': 'A'},
        {'tipo': 'caja', 'nombre': 'osc_filter', 'w': 1.95,
         'sub': 'ecualizador (opcional)', 'color': MUDO},
        {'tipo': 'cable', 'w': 0.70, 'etiqueta': 'B'},
        {'tipo': 'caja', 'nombre': 'rp_decim', 'w': 1.85,
         'sub': f'promedio de {DEC}', 'color': AZUL},
        {'tipo': 'cable', 'w': 0.70, 'etiqueta': 'C'},
        {'tipo': 'caja', 'nombre': 'rp_delay', 'w': 1.85,
         'sub': 'retardo de disparo', 'color': AZUL},
        {'tipo': 'cable', 'w': 1.75, 'etiqueta': 'D → dsp_tap_mux ×3',
         'pie': 'cada consumidor elige su nodo con ROUTE_* (slot 6)',
         'tren': ['A', 'B', 'C', 'D'], 'fichas': NARAN, 'maxtren': 4},
    ], maxtren=4)


def panel_nodos(ax, nodos, ejex=True):
    """Los cuatro nodos apilados, con una calle de alto FIJO cada uno.

    El alto no puede salir del dato: el nodo D esta corrido y en la ventana
    dibujada tiene menos muestras, asi que una calle proporcional a su maximo
    lo aplastaria contra el de al lado.
    """
    a, b = VENTANA
    todos = np.concatenate([v for _, v in nodos.values()])
    H = 1.55 * float(np.abs(todos).max())

    for k, (lab, sig, tap, que, col) in enumerate(NODOS):
        i, v = nodos[lab]
        sel = (i >= a) & (i < b)
        i, v = i[sel], v[sel]
        base = k * H
        ax.axhline(base, color=GRIS, lw=0.7, zorder=0)
        ax.plot(i, base + v, lw=1.1, color=col, zorder=2)
        ax.plot(i, base + v, '.', ms=2.4 if lab in 'AB' else 5.2, color=col,
                zorder=3)
        ax.text(a + 1.5, base + 0.95 * H, f'{lab} · {sig}', fontsize=9.5,
                color=col, fontweight='bold', va='top')
        rit = '125 MSPS, continuo' if lab in 'AB' else \
              f'125/{DEC} MSPS, con estrobo'
        ax.text(b - 2, base + 0.95 * H, f'{tap} — {que}  ·  {rit}',
                fontsize=8.5, color=TINTA2, ha='right', va='top')

    ax.set_xlim(a, b - 1)
    ax.set_ylim(-0.12 * H, len(NODOS) * H)
    ax.set_yticks([])
    ax.grid(False)
    if ejex:
        ax.set_xlabel('Ciclo de adc_clk')
    else:
        ax.tick_params(labelbottom=False)
    for lado in ('top', 'right', 'left'):
        ax.spines[lado].set_visible(False)


GRIS = '#e1e0d9'


def _guardar(fig, nombre):
    T.guardar(fig, os.path.join(_AQUI, nombre))


# =============================================================================
# Epigrafes, manifiesto y README
# =============================================================================

def documentar(nodos, d, nA, nC):
    items = [
        dict(archivo='comun_a_pulso.png',
             titulo='LO QUE ENTRA: EL PULSO AL RITMO DEL ADC',
             origen=f"campaña e2e, `{str(d['origen'])}`, evento {EV}",
             resumen='Qué entra: el pulso medido, una muestra por ciclo y sin '
                     'estrobo',
             datos='medidos',
             nota=f"Que entra a la cadena. Una muestra por ciclo de adc_clk, "
                  f"125 MSPS, continua: en este nodo el valid vale siempre 1, "
                  f"asi que no hay nada que un consumidor pueda esperar. Son "
                  f"las {VENTANA[1] - VENTANA[0]} muestras del flanco de un "
                  f"pulso real de la campana e2e, el mismo que usa la figura "
                  f"de event_ring --hay una sola copia del dato en el repo--."),
        dict(archivo='comun_b_taps.png',
             titulo='UNA SOLA CADENA, CUATRO NODOS',
             origen='estructura de `dsp_tap_mux.sv` y del top',
             resumen='Qué viaja: la cadena única y los cuatro puntos de donde '
                     'se puede pinchar',
             datos='esquema',
             nota="Que viaja. No hay una cadena por consumidor: hay UNA, y "
                  "cuatro puntos utilizables sobre ella. Cada consumidor "
                  "tiene su propio mux 4:1 y elige el suyo en runtime con los "
                  "registros ROUTE_* de la region de TOP. El mux es "
                  "COMBINACIONAL a proposito: registrarlo corrorria el dato "
                  "un ciclo respecto de las senales de control que lo "
                  "acompanan --adc_we y el write pointer del osciloscopio, la "
                  "alineacion trigger-vs-captura del multitrigger-- y en modo "
                  "nativo el hardware dejaria de ser identico al de antes del "
                  "refactor, que es justo la propiedad que se quiso "
                  "preservar."),
        dict(archivo='comun_c_nodos.png',
             titulo='EL MISMO PULSO EN LOS CUATRO NODOS',
             origen='el pulso medido, con el diezmado y el retardo aplicados',
             resumen='Qué sale: el mismo pulso en los cuatro nodos, y el '
                     'cambio de ritmo',
             datos='medidos + modelo exacto',
             nota=f"Que sale, y lo que importa no es solo el valor: es el "
                  f"RITMO. En A y B hay una muestra por ciclo y el valid es "
                  f"constante; en C y D sale una cada {DEC} ciclos y el dato "
                  f"viaja con estrobo --{nA} muestras contra {nC}, "
                  f"{nA // nC}x menos--. Por eso la cabecera del RTL insiste "
                  f"en que el dato y su valid viajan JUNTOS: un consumidor "
                  f"que cambie de nodo sin arrastrar el valid leeria muestras "
                  f"repetidas o se saltearia muestras, segun el sentido del "
                  f"cambio. El diezmado es con promediado, o sea un promedio "
                  f"de bloque de {DEC} muestras: es el unico bloque de la "
                  f"cadena que cambia la FORMA del pulso, y lo paga en ritmo. "
                  f"D es C corrido {DLY} muestras diezmadas "
                  f"({DLY * DEC} ciclos). A y B salen IGUALES en el dibujo y "
                  f"eso no es que la calibracion no haga nada: es que esta "
                  f"captura ya paso por ella y el archivo no guarda los "
                  f"coeficientes, asi que re-aplicarlos seria inventarlos."),
        dict(archivo='comun_transaccion.png',
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
        "Epigrafes de las figuras de transacciones de comun (dsp_tap_mux).\n"
        "Los genera transacciones_comun.py; no editar a mano.",
        items,
        pie=f"QUE ES MEDIDO Y QUE ES MODELO. El pulso de entrada es medido. "
            f"El diezmado con promediado y el retardo son exactos --un "
            f"promedio de bloque de {DEC} y un corrimiento de "
            f"{DLY * DEC} ciclos-- y se calculan en el script. La "
            f"calibracion se dibuja como etapa pero NO se le inventan "
            f"coeficientes, porque la captura ya paso por ella. La diferencia "
            f"ESTRUCTURAL entre nodos --que operaciones acumulo la muestra en "
            f"cada uno-- esta en docs/TOP/figuras/; esta figura es la version "
            f"con el dato encima.")
    T.escribir_manifiesto(os.path.join(_AQUI, 'transacciones.json'),
                          [{k: v for k, v in it.items()
                            if k in ('archivo', 'titulo', 'origen', 'nota')}
                           for it in items])
    T.escribir_readme(
        os.path.join(_AQUI, 'README.md'),
        'Figuras: dsp_tap_mux a nivel de transacción',
        "Hay **una sola** cadena de acondicionado por canal y cuatro nodos "
        "utilizables sobre ella; cada consumidor elige el suyo en runtime con "
        "los registros `ROUTE_*`. La transacción de este módulo es **una "
        "muestra y su valid**: lo que cambia entre nodos no es sólo el valor, "
        "es el ritmo.\n\nLas genera "
        "[`transacciones_comun.py`](transacciones_comun.py):",
        items,
        "cd prj/MCA/docs/comun/figuras/transacciones\n"
        "python3 transacciones_comun.py",
        extra="**Qué es medido y qué es modelo.** El pulso de entrada es "
              "medido (la misma captura que usa "
              "[event_ring](../../../event_ring/figuras/transacciones/); hay "
              "una sola copia del dato en el repo). El diezmado con "
              f"promediado y el retardo son exactos —promedio de bloque de "
              f"{DEC} y corrimiento de {DLY * DEC} ciclos— y se calculan en "
              "el script. La calibración se dibuja como etapa pero **no se le "
              "inventan coeficientes**: la captura ya pasó por ella, así que "
              "los nodos A y B salen iguales.\n\n"
              "La versión **estructural** de esto —qué operaciones acumuló la "
              "muestra en cada nodo, sin datos encima— está en "
              "[`docs/TOP/figuras/`](../../../TOP/figuras/).")
    return items


def main():
    argparse.ArgumentParser().parse_args()
    d = cargar()
    x = d['wave'][EV][CH].astype(float)
    nodos = cadena(x)

    print("Generando figuras en", _AQUI)
    fig, ax = plt.subplots(figsize=(9.6, 2.6)); panel_pulso(ax, x)
    _guardar(fig, 'comun_a_pulso.png')

    fig, ax = plt.subplots(figsize=(9.6, 2.2)); panel_taps(ax)
    _guardar(fig, 'comun_b_taps.png')

    fig, ax = plt.subplots(figsize=(9.6, 5.2)); panel_nodos(ax, nodos)
    _guardar(fig, 'comun_c_nodos.png')

    fig = plt.figure(figsize=(9.6, 9.6))
    gs = GridSpec(3, 1, figure=fig, height_ratios=[0.80, 0.62, 1.70],
                  hspace=0.38)
    ax = fig.add_subplot(gs[0]); panel(ax, '(a)  lo que entra: el pulso al ritmo del ADC')
    panel_pulso(ax, x)
    ax = fig.add_subplot(gs[1]); panel(ax, '(b)  una sola cadena, cuatro nodos')
    panel_taps(ax)
    ax = fig.add_subplot(gs[2]); panel(ax, '(c)  el mismo pulso en los cuatro nodos')
    panel_nodos(ax, nodos)
    _guardar(fig, 'comun_transaccion.png')

    nA, nC = len(nodos['A'][0]), len(nodos['C'][0])
    print(f"  nodo A/B: {nA} muestras  ·  nodo C/D: {nC} "
          f"({nA / nC:.0f}x menos)  ·  retardo D-C = {DLY * DEC} ciclos")
    documentar(nodos, d, nA, nC)
    print("  epigrafes.txt  transacciones.json  README.md")


if __name__ == '__main__':
    main()
