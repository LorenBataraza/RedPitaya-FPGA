#!/usr/bin/env python3
"""Dos figuras sobre el conformado trapezoidal, calcadas de Knoll cap. 17.

Misma convención que [`figuras_resolucion.py`](figuras_resolucion.py): sin
texto adentro de la figura, sólo ejes, leyenda y las marcas imprescindibles.
Paleta y rcParams se importan de ahí.

  10_sintesis_triangular.png   (Knoll fig. 17.6, de Goulding et al.)
      Un triángulo se aproxima sumando salidas de integradores activos, es
      decir CR-RC^n de distinto orden. Acá los tres términos son CR-RC²,
      CR-RC⁴ y CR-RC⁷ y sus pesos salen de un ajuste por mínimos cuadrados
      contra el triángulo — no son los coeficientes originales de Goulding,
      que el libro no da; lo que se muestra es la idea, no la red.

  11_trapezoidal_tiempo_subida.png   (Knoll fig. 17.7, de Jordanov y Knoll)
      El mismo conformador trapezoidal aplicado a tres pulsos de detector con
      tiempo de subida creciente. Si el techo plano dura más que la dispersión
      del tiempo de subida, los tres llegan a la MISMA amplitud: no hay déficit
      balístico. El conformador es el algoritmo recursivo de Jordanov-Knoll
      (NIM A 345 (1994) 337) con cancelación polo-cero exacta.

    python3 figuras_conformado.py [--out DIR]
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

from figuras_resolucion import (SUP, TINTA, TINTA2, MUDO, GRILLA,   # noqa: E402
                               AZUL, NARAN, ROJO, RAMPA, _limpiar)


# =============================================================================
# 10. Síntesis de un triángulo con CR-RC^n (Goulding)
# =============================================================================

def cr_rcn(t, n, tau=1.0):
    """CR-RC^n normalizado al pico; el pico cae en t = n·tau."""
    with np.errstate(divide='ignore', invalid='ignore'):
        y = (t / (n * tau)) ** n * np.exp(n - t / tau)
    return np.where(t > 0, y, 0.0)


def sintesis_triangular(t_pico=5.0, t_fin=9.5):
    """Triángulo (pico en t_pico, vuelve a cero en t_fin) y su aproximación.

    El tiempo está en unidades de la constante de la diferenciación inicial,
    como en la figura del libro. Devuelve t, los tres términos ya pesados, la
    suma normalizada a 1 y el triángulo de referencia escalado para tener la
    misma pendiente inicial que la suma (que es como lo dibuja el libro:
    curva e por encima de d).
    """
    t = np.linspace(0.0, 15.0, 3001)
    tri = np.clip(np.where(t < t_pico, t / t_pico,
                           (t_fin - t) / (t_fin - t_pico)), 0.0, None)

    # (orden, tau) de los tres integradores; el ajuste da pesos positivos
    terminos = ((2, 1.0), (4, 1.0), (7, 0.75))
    A = np.stack([cr_rcn(t, n, tau) for n, tau in terminos], axis=1)
    w, *_ = np.linalg.lstsq(A, tri, rcond=None)
    assert np.all(w > 0), w

    partes = A * w                  # cada término con su peso
    suma = partes.sum(axis=1)
    escala = suma.max()
    partes /= escala
    suma /= escala

    # la e del libro: mismo flanco inicial que d, así que sobrepasa 1
    pend = suma[t <= 1.5][-1] / 1.5
    tri_e = tri * (pend * t_pico)
    return t, partes, suma, tri_e, terminos


def fig_sintesis(out):
    t, partes, suma, tri, terminos = sintesis_triangular()

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for k, ((n, _), y) in enumerate(zip(terminos, partes.T)):
        ax.plot(t, y, color=RAMPA[k], lw=1.4,
                label=f'${"abc"[k]}$  —  CR-RC$^{n}$')
    ax.plot(t, suma, color=NARAN, lw=2.0, label='$d$  —  suma $a+b+c$')
    ax.plot(t, tri, color=TINTA2, lw=1.2, ls='--',
            label='$e$  —  triángulo simétrico')
    ax.axhline(0.0, color=MUDO, lw=0.8)

    ax.set_xlim(0, 15)
    ax.set_ylim(-0.02, 1.2)
    ax.set_xlabel('tiempo  [constantes de la diferenciación inicial]')
    ax.set_ylabel('amplitud')
    ax.legend(loc='upper right', fontsize=9)
    _limpiar(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(out, '10_sintesis_triangular.png'))
    plt.close(fig)
    print('  10_sintesis_triangular.png')


# =============================================================================
# 11. Trapezoidal contra el tiempo de subida (Jordanov y Knoll)
# =============================================================================

def pulso_detector(t, t_subida, tau_decay):
    """Escalón con subida exponencial y decaimiento largo (preamp. de carga).

    Normalizado a carga unitaria: la salida del preamplificador ya empieza a
    decaer mientras la carga sigue llegando, así que el pico de la forma cruda
    vale td/(ts+td) < 1. Sin esta corrección los tres pulsos no llevarían la
    misma carga y la comparación de amplitudes no sería justa.
    """
    y = (1.0 - np.exp(-t / t_subida)) * np.exp(-t / tau_decay)
    y *= (t_subida + tau_decay) / tau_decay
    return np.where(t >= 0, y, 0.0)


def trapecio_jordanov(v, k, l, M):
    """Conformador trapezoidal recursivo de Jordanov-Knoll.

    k = largo de la rampa, l = largo de rampa + techo (muestras);
    M = 1/(exp(dt/tau_decay) - 1) es la cancelación polo-cero. Salida
    normalizada para que un escalón ideal dé un trapecio de altura 1.
    """
    n = v.size
    vk = np.concatenate([np.zeros(k), v[:n - k]])
    vl = np.concatenate([np.zeros(l), v[:n - l]])
    vkl = np.concatenate([np.zeros(k + l), v[:n - k - l]])
    d = v - vk - vl + vkl
    p = np.cumsum(d)
    r = p + M * d
    s = np.cumsum(r)
    return s / (k * (M + 1.0))


def trapezoidal_vs_subida(subidas=(0.003, 0.012, 0.035), rampa=1.0,
                          techo=0.3, tau_decay=30.0, dt=0.001):
    """Tres pulsos con distinto tiempo de subida por el mismo trapezoidal.

    Tiempos en unidades de la rampa del trapecio (el tau del eje del libro).
    Devuelve t y una salida por tiempo de subida.
    """
    t = np.arange(-1.0, 6.0, dt)
    k = int(round(rampa / dt))
    l = int(round((rampa + techo) / dt))
    M = 1.0 / np.expm1(dt / tau_decay)
    salidas = [trapecio_jordanov(pulso_detector(t, ts, tau_decay), k, l, M)
               for ts in subidas]
    return t, salidas


def fig_trapezoidal(out):
    subidas = (0.003, 0.012, 0.035)
    t, salidas = trapezoidal_vs_subida(subidas)
    colores = (AZUL, NARAN, ROJO)
    etiquetas = ('A', 'B', 'C')

    # Trapecio completo a la izquierda; a la derecha dos zooms, el techo plano
    # y la vuelta a la línea de base. Las cajas sombreadas sobre el trazo
    # principal marcan la región que amplía cada zoom.
    fig = plt.figure(figsize=(8.4, 4.6), layout='constrained')
    gs = fig.add_gridspec(2, 2, width_ratios=(1.6, 1.0))
    ax = fig.add_subplot(gs[:, 0])
    zooms = (fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, 1]))

    for y, c, e, ts in zip(salidas, colores, etiquetas, subidas):
        ax.plot(t, y, color=c, lw=1.4,
                label=f'{e}  —  subida {ts:g} τ')
    ax.axhline(0.0, color=MUDO, lw=0.8)
    ax.set_xlim(-0.5, 3.5)
    ax.set_ylim(-0.1, 1.1)
    ax.set_xlabel('tiempo  [τ = rampa del trapecio]')
    ax.set_ylabel('amplitud relativa')
    ax.legend(loc='center right', fontsize=9)
    _limpiar(ax)

    zonas = (((0.8, 1.6), (0.99, 1.01)),
             ((2.2, 2.8), (-0.01, 0.01)))
    for zx, ((x0, x1), (y0, y1)) in zip(zooms, zonas):
        ax.add_patch(Rectangle((x0, y0 - 0.02), x1 - x0, (y1 - y0) + 0.04,
                               fc=GRILLA, ec=MUDO, lw=0.6, alpha=0.8, zorder=0))
        for y, c in zip(salidas, colores):
            zx.plot(t, y, color=c, lw=1.3)
        zx.axhline(y0 + 0.5 * (y1 - y0), color=MUDO, lw=0.6)
        zx.set_xlim(x0, x1)
        zx.set_ylim(y0, y1)
        zx.tick_params(labelsize=8)
        _limpiar(zx)
    zooms[1].set_xlabel('tiempo  [τ]')

    fig.savefig(os.path.join(out, '11_trapezoidal_tiempo_subida.png'))
    plt.close(fig)
    print('  11_trapezoidal_tiempo_subida.png')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI, help='dónde dejar los PNG')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(f'figuras en {os.path.relpath(a.out)}:')
    fig_sintesis(a.out)
    fig_trapezoidal(a.out)


if __name__ == '__main__':
    main()
