#!/usr/bin/env python3
"""Las dos fórmulas de Knoll, deducidas en dos líneas, para `../../tiempo_muerto.md`.

Es el modelo **más simple** que existe para esto, y el que usa la comunidad:
un solo parámetro τ, arribos de Poisson de tasa `n`, tasa registrada `m`, y
una sola idea para los dos modelos —

    m = n · (fracción de tiempo VIVO)

Lo único que cambia entre modelos es cuánto vale esa fracción:

    no paralizable   cada cuenta REGISTRADA abre τ, y nada la extiende, así que
                     el tiempo muerto por segundo es exactamente m·τ:
                         1 − m·τ = m/n   →   m = n/(1 + nτ)
    paralizable      el sistema está muerto en `t` si hubo ALGÚN arribo en
                     (t−τ, t], registrado o no, así que la fracción viva es la
                     probabilidad de que ese intervalo esté vacío:
                         e^{−nτ} = m/n   →   m = n·e^{−nτ}

El resto del documento ([`figuras_tiempo_muerto.py`](figuras_tiempo_muerto.py))
deduce lo mismo por teoría de colas y agrega lo que este modelo NO tiene: el
estímulo periódico (D/D/1/1), la cola de K lugares y la distribución del largo
del período muerto. Acá no hay nada de eso: dos curvas y su corolario de
apilamiento.

Las curvas van en unidades de τ (`n·τ` contra `m·τ`), que es como están en
Knoll y lo que hace que sirvan igual para el lector de Python (τ ≈ 250 µs) y
para el MCA (τ ≈ 5.9 µs).

  knoll_01_tasa_registrada.png
      (a) `m·τ` contra `n·τ` con la diagonal ideal: el no paralizable crece
          monótono y satura en 1/τ; el paralizable tiene un MÁXIMO en nτ=1,
          `m = 1/(eτ)`, y después se desploma.
      (b) la fracción viva `m/n` de la que salen las dos fórmulas: `1 − mτ`
          contra `e^{−nτ}`, con el `1 − nτ` común a primer orden.

  knoll_02_correccion.png
      El problema inverso, que es para lo que se usan las fórmulas: de la
      tasa MEDIDA sacar la REAL.
      (a) `n·τ` contra `m·τ`. El no paralizable se invierte exacto,
          `n = m/(1−mτ)`. El paralizable NO es inyectivo: por cada `m` hay
          dos `n` (ramas W₀ y W₋₁ de Lambert), y arriba de `m = 1/(eτ)` no
          hay ninguna.
      (b) por qué a tasa baja da igual cuál se elija: las dos fórmulas
          coinciden a primer orden y su diferencia relativa es ≈ (nτ)²/2.

  knoll_03_pileup.png
      La figura 17.34 de Knoll: además de `m`, la tasa de eventos
      registrados LIBRES DE APILAMIENTO, `r_pf`, con τ ahora el tiempo de
      resolución de apilamiento. Se agrega la condición "tampoco llegó nada
      en los τ siguientes", que vale `e^{−nτ}` en los dos modelos.

    python3 figuras_knoll.py [--out DIR]

Además imprime las tablas de números que cita el documento.
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.special import lambertw

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, '..', '..', '..', 'figuras'))

from estilo import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, ROJO,    # noqa: E402
                    VERDE, _limpiar, _panel)


# =============================================================================
# Los dos modelos, en unidades de τ: entra x = n·τ, sale m·τ
# =============================================================================

def m_no_paralizable(x):
    """Tipo I. El tiempo muerto por segundo es m·τ y NADA lo extiende:

        m/n = 1 − m·τ      →      m·τ = x/(1+x)

    Satura en m = 1/τ: el sistema nunca entrega más de una cuenta por τ.
    """
    x = np.asarray(x, float)
    return x / (1.0 + x)


def m_paralizable(x):
    """Tipo II. Cualquier arribo reabre la ventana, así que el sistema está
    vivo sólo si el intervalo (t−τ, t] está VACÍO:

        m/n = P(0 arribos en τ) = e^{−nτ}      →      m·τ = x·e^{−x}

    Máximo en x = 1: m = 1/(eτ) ≈ 0.368/τ. Después baja — a tasa alta el
    sistema no vuelve a liberarse nunca.
    """
    x = np.asarray(x, float)
    return x * np.exp(-x)


def pf_no_paralizable(x):
    """Registradas Y libres de apilamiento. Que se haya registrado ya
    garantiza que no hubo nada en los τ ANTERIORES; falta que no haya nada en
    los τ siguientes, que por falta de memoria vale e^{−nτ}:

        r_pf·τ = x·e^{−x}/(1+x)
    """
    return m_no_paralizable(x) * np.exp(-np.asarray(x, float))


def pf_paralizable(x):
    """Lo mismo sobre el paralizable: las dos ventanas, la de atrás y la de
    adelante, son intervalos disjuntos de un Poisson, así que las
    probabilidades se multiplican:

        r_pf·τ = x·e^{−2x}

    Máximo en x = 1/2, con r_pf = 1/(2eτ) = 0.184/τ. El del no paralizable
    está en x = (√5−1)/2 = 0.618, la raíz de x² + x − 1 = 0.
    """
    x = np.asarray(x, float)
    return x * np.exp(-2.0 * x)


# --- el problema inverso: de la medida a la real ----------------------------

def n_de_m_no_paralizable(y):
    """m·τ = y  →  n·τ = y/(1−y). Exacta, inyectiva, y diverge en y = 1."""
    y = np.asarray(y, float)
    return y / (1.0 - y)


def n_de_m_paralizable(y, rama=0):
    """x·e^{−x} = y resuelto con Lambert: x = −W(−y).

    `rama=0` (W₀) da la raíz x ≤ 1, la física mientras no se pase del máximo;
    `rama=-1` (W₋₁) da la otra, x ≥ 1. Fuera de y ≤ 1/e no hay solución: una
    tasa registrada más alta que 1/(eτ) es incompatible con el modelo.
    """
    y = np.asarray(y, float)
    with np.errstate(invalid='ignore'):
        x = -np.real(lambertw(-y, rama))
    return np.where(y <= np.exp(-1.0) + 1e-12, x, np.nan)


# =============================================================================
# 1. La tasa registrada, y la fracción viva de la que sale
# =============================================================================
def fig_tasa_registrada(out):
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.4, 3.6),
                                     layout='constrained')

    x = np.linspace(0, 5, 1001)
    ax_a.plot(x, x, color=TINTA2, lw=0.9, ls=':', label='ideal, $m = n$')
    ax_a.plot(x, m_no_paralizable(x), color=NARAN, lw=1.7,
              label=r'no paralizable, $m\tau = n\tau/(1+n\tau)$')
    ax_a.plot(x, m_paralizable(x), color=VERDE, lw=1.7,
              label=r'paralizable, $m\tau = n\tau\,e^{-n\tau}$')
    ax_a.axhline(1.0, color=MUDO, lw=0.8, ls='--',
                 label=r'techo del no paralizable, $m = 1/\tau$')
    ax_a.plot([1.0], [np.exp(-1.0)], 'o', ms=5, color=ROJO, zorder=5,
              label=r'máximo del paralizable, $m = 1/(e\tau)$')
    ax_a.set_xlim(0, 5)
    ax_a.set_ylim(0, 1.75)
    ax_a.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax_a.set_xlabel(r'tasa real  $n\tau$')
    ax_a.set_ylabel(r'tasa registrada  $m\tau$')
    ax_a.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_a)
    _panel(ax_a, '(a)')

    xb = np.linspace(0, 3, 601)
    ax_b.plot(xb, 1.0 / (1.0 + xb), color=NARAN, lw=1.7,
              label=r'no paralizable, $1 - m\tau$')
    ax_b.plot(xb, np.exp(-xb), color=VERDE, lw=1.7,
              label=r'paralizable, $e^{-n\tau}$')
    ax_b.plot(xb, 1.0 - xb, color=TINTA2, lw=0.9, ls=':',
              label=r'primer orden, $1 - n\tau$')
    ax_b.set_xlim(0, 3)
    ax_b.set_ylim(0, 1.05)
    ax_b.set_xlabel(r'tasa real  $n\tau$')
    ax_b.set_ylabel(r'fracción viva  $m/n$')
    ax_b.legend(loc='upper right')
    _limpiar(ax_b)
    _panel(ax_b, '(b)')

    fig.savefig(os.path.join(out, 'knoll_01_tasa_registrada.png'))
    plt.close(fig)


# =============================================================================
# 2. El problema inverso: corregir la medición
# =============================================================================
def fig_correccion(out):
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.4, 3.6),
                                     layout='constrained')

    y = np.linspace(0, 0.80, 801)
    ax_a.plot(y, y, color=TINTA2, lw=0.9, ls=':', label='ideal, $n = m$')
    ax_a.plot(y, n_de_m_no_paralizable(y), color=NARAN, lw=1.7,
              label=r'no paralizable, $n\tau = m\tau/(1-m\tau)$')

    yp = np.linspace(0, np.exp(-1.0), 601)
    ax_a.plot(yp, n_de_m_paralizable(yp, 0), color=VERDE, lw=1.7,
              label=r'paralizable, rama $n\tau \leq 1$')
    ax_a.plot(yp, n_de_m_paralizable(yp, -1), color=VERDE, lw=1.4, ls='--',
              label=r'paralizable, rama $n\tau \geq 1$')
    ax_a.axvline(np.exp(-1.0), color=ROJO, lw=1.0, ls='-.',
                 label=r'$m\tau = 1/e$: techo del paralizable')
    ax_a.set_xlim(0, 0.80)
    ax_a.set_ylim(0, 5)
    ax_a.set_xlabel(r'tasa registrada  $m\tau$')
    ax_a.set_ylabel(r'tasa real inferida  $n\tau$')
    ax_a.legend(loc='upper center', fontsize=8.5, frameon=True,
                facecolor=SUP, edgecolor='none')
    _limpiar(ax_a)
    _panel(ax_a, '(a)')

    xb = np.logspace(-3, 0.3, 500)
    dif = (m_no_paralizable(xb) - m_paralizable(xb)) / m_no_paralizable(xb)
    ax_b.loglog(xb, dif, color=AZUL, lw=1.7,
                label=r'$(m_{\rm np} - m_{\rm p})/m_{\rm np}$')
    ax_b.loglog(xb, xb ** 2 / 2.0, color=TINTA2, lw=0.9, ls=':',
                label=r'asíntota  $(n\tau)^2/2$')
    ax_b.axhline(0.01, color=MUDO, lw=0.8, ls='--',
                 label='1 % de diferencia')
    ax_b.set_xlim(1e-3, 2)
    ax_b.set_ylim(1e-7, 1)
    ax_b.set_xlabel(r'tasa real  $n\tau$')
    ax_b.set_ylabel('diferencia relativa entre modelos')
    ax_b.legend(loc='upper left')
    _limpiar(ax_b)
    _panel(ax_b, '(b)')

    fig.savefig(os.path.join(out, 'knoll_02_correccion.png'))
    plt.close(fig)


# =============================================================================
# 3. Figura 17.34 de Knoll: lo registrado y lo registrado SIN apilar
# =============================================================================
def fig_pileup(out):
    fig, ax = plt.subplots(figsize=(6.6, 4.2), layout='constrained')

    x = np.linspace(0, 1, 501)
    ax.plot(x, x, color=TINTA, lw=1.2, ls=':', label=r'$r = n$  (ideal)')
    ax.plot(x, m_no_paralizable(x), color=NARAN, lw=1.7,
            label=r'$r = m$,  no paralizable')
    ax.plot(x, m_paralizable(x), color=VERDE, lw=1.7,
            label=r'$r = m$,  paralizable')
    ax.plot(x, pf_no_paralizable(x), color=NARAN, lw=1.5, ls='--',
            label=r'$r = r_{pf}$,  no paralizable')
    ax.plot(x, pf_paralizable(x), color=VERDE, lw=1.5, ls='--',
            label=r'$r = r_{pf}$,  paralizable')

    # los dos máximos de r_pf: el del no paralizable sale de x²+x−1 = 0
    x_np = 0.5 * (np.sqrt(5.0) - 1.0)
    ax.plot([x_np, 0.5], [pf_no_paralizable(x_np), pf_paralizable(0.5)],
            'o', ms=5, ls='none', color=ROJO, zorder=5,
            label=r'máximos de $r_{pf}$: $n\tau = 0.618$ y $1/2$')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 0.62)
    ax.set_xlabel(r'tasa real  $n\tau$')
    ax.set_ylabel(r'tasa registrada  $r\tau$')
    ax.legend(loc='upper left', frameon=True, facecolor=SUP, edgecolor='none')
    _limpiar(ax)

    fig.savefig(os.path.join(out, 'knoll_03_pileup.png'))
    plt.close(fig)


# =============================================================================
# Las tablas que cita el documento
# =============================================================================
def tablas():
    xs = [0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0]
    print('\n| nτ | mτ no para | mτ para | pérdida no para | pérdida para |')
    print('|---|---|---|---|---|')
    for x in xs:
        mn, mp = float(m_no_paralizable(x)), float(m_paralizable(x))
        print(f'| {x:g} | {mn:.4f} | {mp:.4f} | '
              f'{100*(1-mn/x):.1f} % | {100*(1-mp/x):.1f} % |')

    print('\n| nτ | r_pf τ no para | r_pf τ para | '
          'apilado / registrado |')
    print('|---|---|---|---|')
    for x in xs:
        print(f'| {x:g} | {float(pf_no_paralizable(x)):.4f} | '
              f'{float(pf_paralizable(x)):.4f} | '
              f'{100*(1-np.exp(-x)):.1f} % |')

    # dónde empieza a importar cuál de los dos modelos es
    tau_mca, tau_lector = 5.9e-6, 250e-6
    x = np.linspace(1e-4, 3, 300001)
    d = (m_no_paralizable(x) - m_paralizable(x)) / m_no_paralizable(x)
    print('\n| separación entre modelos | nτ | MCA (τ = 5.9 µs) '
          '| lector (τ = 250 µs) |')
    print('|---|---|---|---|')
    for lim in (0.01, 0.05, 0.10):
        xc = float(x[np.searchsorted(d, lim)])
        print(f'| {100*lim:g} % | {xc:.3f} | {xc/tau_mca/1e3:.0f} kcps '
              f'| {xc/tau_lector:.0f} ev/s |')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=_AQUI)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    fig_tasa_registrada(a.out)
    fig_correccion(a.out)
    fig_pileup(a.out)
    tablas()
    print(f'\nfiguras en {a.out}')


if __name__ == '__main__':
    main()
