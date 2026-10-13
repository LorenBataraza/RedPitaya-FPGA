#!/usr/bin/env python3
"""Figuras del modelo teórico de tiempo muerto para `../../tiempo_muerto.md`.

Todas son teóricas: un servidor, tiempo de servicio τ, y lo único que cambia
es cómo llegan los eventos y cuántos pueden esperar. Los ejes van en
unidades de τ (`n·τ` y `m·τ`), así una sola curva sirve para el lector de
Python (τ ≈ 250 µs) y para el MCA (τ ≈ 2.9 µs).

Misma convención que [`../figuras_resolucion.py`](../figuras_resolucion.py):
sin texto adentro, sólo ejes, leyenda y las marcas imprescindibles. Paleta y
rcParams se importan de ahí.

  01_tasas_adimensionales.png
      (a) tasa registrada m·τ contra tasa incidente n·τ para los tres
          modelos K=1: periódico (escalera), Poisson no paralizable
          (ρ/(1+ρ)) y paralizable (ρ·e^{-ρ}), con la diagonal ideal.
      (b) la misma información como fracción perdida 1 − m/n, en eje
          logarítmico de ρ: donde los modelos se separan es a ρ chico.

  02_integral_exponencial.png
      (a) un tren Poisson en el tiempo con las ventanas muertas: cada
          arribo que cae adentro de la ventana del anterior se pierde.
      (b) la densidad de Δt, n·e^{-n·t}, con el área entre 0 y τ rayada,
          para tres valores de ρ. Esa área es la probabilidad de que el
          próximo arribo caiga dentro de la ventana muerta.
      (c) lo que da esa área, 1 − e^{-ρ}, contra ρ/(1+ρ) y contra ρ: el
          paralizable es exactamente el área; el no paralizable coincide
          a primer orden y se separa a ρ ~ 1.

  03_cola_K.png
      Poisson, servicio fijo τ, y K lugares en el sistema (1 = sin cola).
      (a) fracción perdida contra ρ para K = 1, 2, 3, 5, 10 y K = ∞. Sale
          de la cadena de Markov embebida en las partidas de M/D/1/K, no
          de una simulación.
      (b) fracción de tiempo ocupado m·τ para los mismos K: SUBE con K.
          La cola no reduce el tiempo ocupado, reduce lo que se pierde
          mientras se está ocupado.

  04_periodico.png
      (a) cuatro trenes periódicos con T_prod/T_cons = 2, 1.25, 0.8, 0.4
          (ρ = 0.5, 0.8, 1.25, 2.5): arribos, ventanas muertas y cuáles se
          pierden.
      (b) m·τ contra n·τ = T_cons/T_prod para τ fijo (escalera exacta) y
          para τ con dispersión σ/τ = 3 % y 10 %, con Poisson al lado.
      (c) la fracción perdida de las mismas curvas.

    python3 figuras_tiempo_muerto.py [--out DIR]
"""

import argparse
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))

from figuras_resolucion import (TINTA, TINTA2, MUDO, GRILLA,   # noqa: E402
                               AZUL, NARAN, ROJO, RAMPA,
                               _limpiar, _panel)

VERDE = '#3a9a5c'       # el modelo paralizable, que se muestra para descartar


# =============================================================================
# Modelos, todos en unidades de τ: entra ρ = n·τ, sale m·τ
# =============================================================================

def m_periodico(rho):
    """D/D/1/1: se registra un arribo cada ⌈τ/T⌉ períodos. m·τ = ρ/⌈ρ⌉."""
    rho = np.asarray(rho, float)
    return rho / np.maximum(np.ceil(rho), 1.0)


def m_poisson(rho):
    """M/G/1/1 no paralizable: ciclo = τ + Exp(n). m·τ = ρ/(1+ρ)."""
    rho = np.asarray(rho, float)
    return rho / (1.0 + rho)


def m_paralizable(rho):
    """Cada arribo re-extiende la ventana: se registra sólo si Δt > τ."""
    rho = np.asarray(rho, float)
    return rho * np.exp(-rho)


def m_periodico_disperso(rho, s):
    """D/G/1/1: τ ~ N(τ̄, s·τ̄). Los arribos siguen en la grilla k·T, así que
    por cada registrado se saltean ⌈τ_i/T⌉ − 1 y m·τ = ρ / E[⌈ρ·X⌉] con
    X ~ N(1, s). Usa ⌈x⌉ = Σ_{k≥0} 1[x > k]."""
    rho = np.atleast_1d(np.asarray(rho, float))
    if s == 0.0:
        return m_periodico(rho)
    p_mayor = 0.5 * np.array([[math.erfc((k / r - 1.0) / (s * math.sqrt(2)))
                               for r in rho] for k in range(64)])
    return rho / p_mayor.sum(axis=0)


def mdk1(rho, K, a_max=120):
    """M/D/1/K: arribos Poisson, servicio fijo τ, K lugares en el sistema
    contando al que se atiende (K=1 es sin cola).

    Cadena embebida en las partidas: el estado q es cuántos quedan en el
    sistema justo después de una partida (0..K−1). Si q=0 el servidor
    espera un arribo (Exp(n)) y arranca con 1 adentro; si no, arranca ya
    con q. Durante el servicio llegan A ~ Poisson(ρ) y entran min(A, K−q₀).
    El tiempo medio entre partidas es τ + π₀/n, así que m·τ = 1/(1+π₀/ρ).
    Devuelve (m·τ, fracción perdida).
    """
    p = np.empty(a_max + 1)
    p[0] = math.exp(-rho)
    for a in range(1, a_max + 1):
        p[a] = p[a - 1] * rho / a
    P = np.zeros((K, K))
    for q in range(K):
        q0 = max(q, 1)
        libres = K - q0
        for a in range(a_max + 1):
            P[q, q0 - 1 + min(a, libres)] += p[a]
    # estacionaria: π P = π, Σπ = 1
    A = np.vstack([P.T - np.eye(K), np.ones(K)])
    b = np.zeros(K + 1)
    b[-1] = 1.0
    pi = np.linalg.lstsq(A, b, rcond=None)[0]
    m_tau = 1.0 / (1.0 + pi[0] / rho)
    return m_tau, max(0.0, 1.0 - m_tau / rho)


def mdk1_curva(rhos, K):
    out = np.array([mdk1(r, K) for r in rhos])
    return out[:, 0], out[:, 1]


# =============================================================================
# Trenes en el tiempo
# =============================================================================

def servir_k1(t_arribos, tau):
    """Servidor K=1 no paralizable: acepta si llegó ≥ τ después del último
    aceptado (así un arribo justo en el borde entra, coherente con ⌈τ/T⌉).
    Devuelve máscara de aceptados."""
    ok = np.zeros(t_arribos.size, bool)
    ultimo = -np.inf
    for i, t in enumerate(t_arribos):
        if t - ultimo >= tau - 1e-12:
            ok[i] = True
            ultimo = t
    return ok


def _tren(ax, t, ok, tau, t_fin):
    """Dibuja arribos (aceptados azul, perdidos rojo) y ventanas muertas."""
    for ti in t[ok]:
        ax.axvspan(ti, min(ti + tau, t_fin), color=GRILLA, lw=0)
    ax.vlines(t[ok], 0, 1, color=AZUL, lw=1.4)
    ax.vlines(t[~ok], 0, 0.55, color=ROJO, lw=1.4)
    ax.set_xlim(0, t_fin)
    ax.set_ylim(0, 1.15)
    ax.set_yticks([])
    ax.grid(False)
    for lado in ('top', 'right', 'left'):
        ax.spines[lado].set_visible(False)


# =============================================================================
# Figuras
# =============================================================================

def fig_tasas(out):
    rho = np.linspace(0.0, 6.0, 3001)[1:]
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.4, 3.6),
                                     layout='constrained')

    ax_a.plot(rho, rho, color=TINTA2, lw=0.9, ls=':', label='ideal, $m = n$')
    ax_a.plot(rho, m_periodico(rho), color=AZUL, lw=1.6,
              label=r'periódico  D/D/1/1:  $\rho/\lceil\rho\rceil$')
    ax_a.plot(rho, m_poisson(rho), color=NARAN, lw=1.6,
              label=r'Poisson  M/G/1/1:  $\rho/(1+\rho)$')
    ax_a.plot(rho, m_paralizable(rho), color=VERDE, lw=1.2, ls='-.',
              label=r'paralizable:  $\rho\,e^{-\rho}$')
    ax_a.axhline(1.0, color=MUDO, lw=0.6, ls='--')
    ax_a.set_xlim(0, 6)
    ax_a.set_ylim(0, 1.6)
    ax_a.set_xlabel(r'$n\,\tau$  (tasa incidente × tiempo muerto)')
    ax_a.set_ylabel(r'$m\,\tau$  (tasa registrada × tiempo muerto)')
    ax_a.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_a)
    _panel(ax_a, 'a')

    rho_l = np.logspace(-2, np.log10(6), 2000)
    ax_b.plot(rho_l, 1 - m_periodico(rho_l) / rho_l, color=AZUL, lw=1.6,
              label='periódico')
    ax_b.plot(rho_l, 1 - m_poisson(rho_l) / rho_l, color=NARAN, lw=1.6,
              label='Poisson')
    ax_b.plot(rho_l, 1 - m_paralizable(rho_l) / rho_l, color=VERDE, lw=1.2,
              ls='-.', label='paralizable')
    ax_b.axvline(1.0, color=MUDO, lw=0.6, ls='--')
    ax_b.set_xscale('log')
    ax_b.set_xlim(1e-2, 6)
    ax_b.set_ylim(0, 1)
    ax_b.set_xlabel(r'$\rho = n\,\tau$')
    ax_b.set_ylabel(r'fracción perdida  $1 - m/n$')
    ax_b.legend(loc='upper left', fontsize=8.5)
    _limpiar(ax_b)
    _panel(ax_b, 'b')

    fig.savefig(os.path.join(out, '01_tasas_adimensionales.png'))
    plt.close(fig)
    print('  01_tasas_adimensionales.png')


def fig_integral(out, rho_tren=0.5, seed=11):
    fig = plt.figure(figsize=(8.4, 5.6), layout='constrained')
    gs = fig.add_gridspec(2, 2, height_ratios=(0.55, 1.0))
    ax_t = fig.add_subplot(gs[0, :])
    ax_p = fig.add_subplot(gs[1, 0])
    ax_l = fig.add_subplot(gs[1, 1])

    # --- (a) tren Poisson con ventanas muertas, τ = 1 -----------------------
    rng = np.random.default_rng(seed)
    t_fin = 40.0
    dt = rng.exponential(1.0 / rho_tren, size=400)
    t = np.cumsum(dt)
    t = t[t < t_fin]
    ok = servir_k1(t, 1.0)
    _tren(ax_t, t, ok, 1.0, t_fin)
    ax_t.set_xlabel(r'tiempo  $[\tau]$')
    ax_t.vlines([], 0, 1, color=AZUL, lw=1.4, label='registrado')
    ax_t.vlines([], 0, 1, color=ROJO, lw=1.4, label='perdido')
    ax_t.fill_between([], [], [], color=GRILLA, label=r'ventana muerta $\tau$')
    ax_t.legend(loc='lower right', ncol=3, fontsize=8.5,
                bbox_to_anchor=(1.0, 1.0))
    _panel(ax_t, 'a')

    # --- (b) densidad de Δt en unidades de τ, área entre 0 y τ --------------
    x = np.linspace(0, 5, 1000)
    for rho, col in zip((0.2, 0.5, 1.0), RAMPA[1:4]):
        f = rho * np.exp(-rho * x)
        ax_p.plot(x, f, color=col, lw=1.5, label=rf'$\rho = {rho:g}$')
        ax_p.fill_between(x[x <= 1], f[x <= 1], color=col, alpha=0.18, lw=0)
    ax_p.axvline(1.0, color=MUDO, lw=0.8, ls='--')
    ax_p.set_xlim(0, 5)
    ax_p.set_ylim(0, 1.08)
    ax_p.set_xlabel(r'$\Delta t\,/\,\tau$')
    ax_p.set_ylabel(r'densidad de $\Delta t$,  $\tau\,n\,e^{-n\,\Delta t}$')
    ax_p.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_p)
    _panel(ax_p, 'b')

    # --- (c) qué da esa área ------------------------------------------------
    r = np.logspace(-2, np.log10(6), 1000)
    ax_l.plot(r, r, color=TINTA2, lw=0.9, ls=':', label=r'primer orden: $\rho$')
    ax_l.plot(r, 1 - np.exp(-r), color=VERDE, lw=1.4, ls='-.',
              label=r'área $\int_0^\tau n e^{-nt}dt = 1-e^{-\rho}$  (paralizable)')
    ax_l.plot(r, r / (1 + r), color=NARAN, lw=1.6,
              label=r'$\rho/(1+\rho)$  (no paralizable)')
    ax_l.axvline(1.0, color=MUDO, lw=0.6, ls='--')
    ax_l.set_xscale('log')
    ax_l.set_xlim(1e-2, 6)
    ax_l.set_ylim(0, 1)
    ax_l.set_xlabel(r'$\rho = n\,\tau$')
    ax_l.set_ylabel('fracción perdida')
    ax_l.legend(loc='upper left', fontsize=8)
    _limpiar(ax_l)
    _panel(ax_l, 'c')

    fig.savefig(os.path.join(out, '02_integral_exponencial.png'))
    plt.close(fig)
    print('  02_integral_exponencial.png')


def fig_cola(out):
    rho = np.logspace(-2, np.log10(6), 160)
    Ks = (1, 2, 3, 5, 10)
    cols = list(reversed(RAMPA))
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.4, 3.6),
                                     layout='constrained')

    for K, col in zip(Ks, cols):
        m_tau, perdida = mdk1_curva(rho, K)
        ax_a.plot(rho, perdida, color=col, lw=1.6 if K == 1 else 1.3,
                  label=f'$K = {K}$')
        ax_b.plot(rho, m_tau, color=col, lw=1.6 if K == 1 else 1.3,
                  label=f'$K = {K}$')
    # K = ∞: sin pérdida hasta ρ = 1, después el servidor satura en 1/τ
    ax_a.plot(rho, np.maximum(0.0, 1 - 1 / rho), color=TINTA2, lw=1.0,
              ls='--', label=r'$K = \infty$')
    ax_b.plot(rho, np.minimum(rho, 1.0), color=TINTA2, lw=1.0, ls='--',
              label=r'$K = \infty$')

    for ax in (ax_a, ax_b):
        ax.axvline(1.0, color=MUDO, lw=0.6, ls='--')
        ax.set_xscale('log')
        ax.set_xlim(1e-2, 6)
        ax.set_ylim(0, 1)
        ax.set_xlabel(r'$\rho = n\,\tau$')
        _limpiar(ax)
    ax_a.set_ylabel(r'fracción perdida  $1 - m/n$')
    ax_b.set_ylabel(r'fracción de tiempo ocupado  $m\,\tau$')
    ax_a.legend(loc='upper left', fontsize=8.5)
    ax_b.legend(loc='upper left', fontsize=8.5)
    _panel(ax_a, 'a')
    _panel(ax_b, 'b')

    fig.savefig(os.path.join(out, '03_cola_K.png'))
    plt.close(fig)
    print('  03_cola_K.png')


def fig_periodico(out):
    razones = (2.0, 1.25, 0.8, 0.4)          # T_prod / T_cons
    fig = plt.figure(figsize=(8.4, 6.2), layout='constrained')
    gs = fig.add_gridspec(2, 2, height_ratios=(1.0, 1.15))
    gs_t = gs[0, :].subgridspec(len(razones), 1, hspace=0.05)
    axs_t = [fig.add_subplot(gs_t[i]) for i in range(len(razones))]
    ax_m = fig.add_subplot(gs[1, 0])
    ax_l = fig.add_subplot(gs[1, 1])

    # --- (a) cuatro trenes, τ = 1, T = razón -------------------------------
    t_fin = 16.0
    for ax, T in zip(axs_t, razones):
        t = np.arange(0.0, t_fin, T)
        ok = servir_k1(t, 1.0)
        _tren(ax, t, ok, 1.0, t_fin)
        ax.set_ylabel(rf'$T_{{\rm prod}}/T_{{\rm cons}} = {T:g}$', rotation=0,
                      labelpad=8, va='center', ha='right', fontsize=8.5,
                      color=TINTA2)
        if ax is not axs_t[-1]:
            ax.set_xticklabels([])
    axs_t[-1].set_xlabel(r'tiempo  $[\tau]$')
    axs_t[0].vlines([], 0, 1, color=AZUL, lw=1.4, label='registrado')
    axs_t[0].vlines([], 0, 1, color=ROJO, lw=1.4, label='perdido')
    axs_t[0].fill_between([], [], [], color=GRILLA, label=r'ventana muerta $\tau$')
    axs_t[0].legend(loc='lower right', ncol=3, fontsize=8.5,
                    bbox_to_anchor=(1.0, 1.0))
    _panel(axs_t[0], 'a')

    # --- (b) y (c): escalera, dispersión, Poisson --------------------------
    rho = np.linspace(0.0, 6.0, 3001)[1:]
    ax_m.plot(rho, rho, color=TINTA2, lw=0.9, ls=':', label='ideal')
    ax_l.plot(rho, 0 * rho, color=TINTA2, lw=0.9, ls=':', label='ideal')
    for s, col, lw in ((0.0, AZUL, 1.6), (0.03, RAMPA[1], 1.1),
                       (0.10, RAMPA[0], 1.1)):
        m = m_periodico_disperso(rho, s)
        et = 'periódico, $\\tau$ fijo' if s == 0 else \
             rf'periódico, $\sigma_\tau/\tau = {s*100:.0f}\,\%$'
        ax_m.plot(rho, m, color=col, lw=lw, label=et)
        ax_l.plot(rho, 1 - m / rho, color=col, lw=lw, label=et)
    ax_m.plot(rho, m_poisson(rho), color=NARAN, lw=1.4, label='Poisson')
    ax_l.plot(rho, 1 - m_poisson(rho) / rho, color=NARAN, lw=1.4,
              label='Poisson')
    # los cuatro trenes de arriba, sobre la curva
    r4 = 1.0 / np.array(razones)
    ax_m.plot(r4, m_periodico(r4), 'o', color=TINTA, ms=4.5, zorder=5)
    ax_l.plot(r4, 1 - m_periodico(r4) / r4, 'o', color=TINTA, ms=4.5,
              zorder=5)

    for ax in (ax_m, ax_l):
        ax.axvline(1.0, color=MUDO, lw=0.6, ls='--')
        ax.set_xlim(0, 6)
        ax.set_xlabel(r'$n\,\tau = T_{\rm cons}\,/\,T_{\rm prod}$')
        _limpiar(ax)
    ax_m.set_ylim(0, 1.6)
    ax_m.axhline(1.0, color=MUDO, lw=0.6, ls='--')
    ax_m.set_ylabel(r'$m\,\tau$')
    ax_l.set_ylim(0, 1)
    ax_l.set_ylabel(r'fracción perdida  $1 - m/n$')
    ax_m.legend(loc='upper right', fontsize=8)
    _panel(ax_m, 'b')
    _panel(ax_l, 'c')

    fig.savefig(os.path.join(out, '04_periodico.png'))
    plt.close(fig)
    print('  04_periodico.png')


# =============================================================================
# Números que cita el documento
# =============================================================================

def tabla():
    print()
    print('fracción perdida [%] — Poisson, servicio fijo, K lugares')
    print('  rho     K=1     K=2     K=3     K=5    K=10   1-e^-rho')
    for r in (0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0):
        fila = [100 * mdk1(r, K)[1] for K in (1, 2, 3, 5, 10)]
        print(f'  {r:<5g}' + ''.join(f'{v:8.2f}' for v in fila)
              + f'{100*(1-math.exp(-r)):10.2f}')
    print()
    print('periódico con dispersión: m/n [%] cerca del borde rho = 2')
    print('  rho    s=0    s=3%   s=10%')
    for r in (1.8, 1.9, 1.95, 2.0, 2.05, 2.1, 2.2):
        fila = [100 * float(m_periodico_disperso(r, s)[0]) / r
                for s in (0.0, 0.03, 0.10)]
        print(f'  {r:<5g}' + ''.join(f'{v:7.1f}' for v in fila))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI, help='dónde dejar los PNG')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(f'figuras en {os.path.relpath(a.out)}:')
    fig_tasas(a.out)
    fig_integral(a.out)
    fig_cola(a.out)
    fig_periodico(a.out)
    tabla()


if __name__ == '__main__':
    main()
