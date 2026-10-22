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

  02a_tren_poisson.png
      Los arribos EN EL TIEMPO, una fila por ρ, con las ventanas muertas:
      cada arribo que cae adentro de la ventana del anterior se pierde.
      Va sola, sin curvas al lado: se lee contando sobre un eje de tiempo.

  02b_integral_exponencial.png
      (a) la densidad de Δt, n·e^{-n·t}, con el área entre 0 y τ rayada,
          para tres valores de ρ. Esa área es la probabilidad de que el
          próximo arribo caiga dentro de la ventana muerta.
      (b) lo que da esa área, 1 − e^{-ρ}, contra ρ/(1+ρ) y contra ρ: el
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

  04a_trenes_periodicos.png
      Los cuatro trenes periódicos EN EL TIEMPO, con T_prod/T_cons = 2,
      1.25, 0.8, 0.4 (ρ = 0.5, 0.8, 1.25, 2.5): arribos, ventanas muertas
      y cuáles se pierden. Mismos ejes que 02a — poner las dos imágenes
      una al lado de la otra es la comparación central del documento.

  02c_tren_rho05.png  y  02d_tren_rho15.png
      El MISMO tren de arribos con las dos reglas, una arriba de la otra.
      Una imagen por ρ, para que la comparación que hace el ojo sea entre
      las dos REGLAS y no entre los dos ρ. El no paralizable recorta
      ventanas de largo τ siempre; el paralizable las encadena, y cada
      período muerto lleva su largo acotado arriba, en unidades de τ.

  02e_largo_ventana_muerta.png
      (a) la densidad del largo del período muerto: el no paralizable es una
          delta en L = τ; el paralizable conserva un átomo en τ de masa
          e^{-ρ} y le crece una cola, con un quiebre en cada múltiplo de τ
          (uno por extensión).
      (b) la cola, P(L > x), en semilog.

  02f_largo_vs_tasa.png
      (a) media, mediana y p90 contra ρ, con el eje de tasa del MCA arriba.
          E[L]/τ = (e^ρ-1)/ρ, exacta.
      (b) por qué los CUANTILES arrancan planos en τ y la media no: el
          átomo. Mientras e^{-ρ} > q el cuantil q cae adentro del átomo y
          vale exactamente τ.

  04b_periodico.png
      (a) m·τ contra n·τ = T_cons/T_prod para τ fijo (escalera exacta) y
          para τ con dispersión σ/τ = 3 % y 10 %, con Poisson al lado.
      (b) la fracción perdida de las mismas curvas.

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


def fig_tren_poisson(out, rhos=(0.2, 0.5, 1.0), seed=11, t_fin=40.0):
    """Los arribos en el tiempo, solos: una fila por ρ.

    Va aparte de las curvas a propósito. Es la figura que muestra el
    MECANISMO —los arribos se agrupan y los que caen en la ventana del
    anterior se pierden— y se lee mirando el eje de tiempo, no un eje de
    tasas. Mezclarla con los paneles de densidad obligaba a leer dos cosas
    distintas en la misma imagen.
    """
    fig, axs = plt.subplots(len(rhos), 1, figsize=(8.6, 0.95 * len(rhos) + 1.1),
                            sharex=True, layout='constrained')
    for ax, rho in zip(np.atleast_1d(axs), rhos):
        rng = np.random.default_rng(seed)
        t = np.cumsum(rng.exponential(1.0 / rho, size=int(4 * rho * t_fin) + 200))
        t = t[t < t_fin]
        ok = servir_k1(t, 1.0)
        _tren(ax, t, ok, 1.0, t_fin)
        ax.set_ylabel(rf'$\rho = {rho:g}$', rotation=0, labelpad=20,
                      va='center', ha='right', color=TINTA2)
        # Sin anotar la pérdida de la realización: con rho = 0.2 hay ~8
        # arribos en 40 tau y el número muestral se va 10 pp del modelo. Los
        # valores esperados van en el epígrafe, que no finge ser una medición.

    ax0 = np.atleast_1d(axs)[0]
    ax0.vlines([], 0, 1, color=AZUL, lw=1.4, label='registrado')
    ax0.vlines([], 0, 1, color=ROJO, lw=1.4, label='perdido')
    ax0.fill_between([], [], [], color=GRILLA, label=r'ventana muerta $\tau$')
    ax0.legend(loc='lower left', ncol=3, fontsize=8.5,
               bbox_to_anchor=(0.0, 1.02))
    np.atleast_1d(axs)[-1].set_xlabel(r'tiempo  $[\tau]$')

    fig.savefig(os.path.join(out, '02a_tren_poisson.png'))
    plt.close(fig)
    print('  02a_tren_poisson.png')


def fig_integral(out):
    fig, (ax_p, ax_l) = plt.subplots(1, 2, figsize=(8.4, 3.6),
                                     layout='constrained')

    # --- (a) densidad de Δt en unidades de τ, área entre 0 y τ --------------
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
    _panel(ax_p, 'a')

    # --- (b) qué da esa área ------------------------------------------------
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
    _panel(ax_l, 'b')

    fig.savefig(os.path.join(out, '02b_integral_exponencial.png'))
    plt.close(fig)
    print('  02b_integral_exponencial.png')


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


RAZONES = (2.0, 1.25, 0.8, 0.4)              # T_prod / T_cons


def fig_trenes_periodicos(out, t_fin=16.0):
    """Los cuatro trenes periódicos en el tiempo, solos.

    Separada de las curvas por el mismo motivo que `fig_tren_poisson`: acá se
    cuentan rayitas sobre un eje de tiempo, y en la otra se leen tasas. El
    contraste con el tren Poisson de 02a es el punto de todo el documento, y
    se ve mejor con las dos figuras una al lado de la otra que con cada tren
    arrinconado arriba de su propio par de curvas.
    """
    fig, axs = plt.subplots(len(RAZONES), 1,
                            figsize=(8.6, 0.95 * len(RAZONES) + 1.1),
                            sharex=True, layout='constrained')
    for ax, T in zip(axs, RAZONES):
        t = np.arange(0.0, t_fin, T)
        ok = servir_k1(t, 1.0)
        _tren(ax, t, ok, 1.0, t_fin)
        ax.set_ylabel(rf'$T_{{\rm prod}}/T_{{\rm cons}} = {T:g}$', rotation=0,
                      labelpad=8, va='center', ha='right', fontsize=8.5,
                      color=TINTA2)
        # La anotación da la regla EXACTA (1 de cada k), no el conteo de esta
        # ventana: con 16 tau el último ciclo queda cortado y el porcentaje
        # muestral se corre un par de puntos del 1 - 1/k verdadero.
        rho = 1.0 / T
        k = int(np.ceil(rho))
        ax.annotate(rf'$\rho = {rho:.2f}$,  $k = {k}$,  registra 1 de cada {k}'
                    + (rf'  ($1-1/k$ = {100*(1-1/k):.0f} %)' if k > 1 else
                       '  (no pierde)'),
                    xy=(1.0, 1.02), xycoords='axes fraction', ha='right',
                    va='bottom', fontsize=8, color=TINTA2)
    axs[-1].set_xlabel(r'tiempo  $[\tau]$')
    axs[0].vlines([], 0, 1, color=AZUL, lw=1.4, label='registrado')
    axs[0].vlines([], 0, 1, color=ROJO, lw=1.4, label='perdido')
    axs[0].fill_between([], [], [], color=GRILLA, label=r'ventana muerta $\tau$')
    axs[0].legend(loc='lower left', ncol=3, fontsize=8.5,
                  bbox_to_anchor=(0.0, 1.02))

    fig.savefig(os.path.join(out, '04a_trenes_periodicos.png'))
    plt.close(fig)
    print('  04a_trenes_periodicos.png')


def fig_periodico(out):
    razones = RAZONES
    fig, (ax_m, ax_l) = plt.subplots(1, 2, figsize=(8.6, 3.8),
                                     layout='constrained')

    # --- (a) y (b): escalera, dispersión, Poisson --------------------------
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
    _panel(ax_m, 'a')
    _panel(ax_l, 'b')

    fig.savefig(os.path.join(out, '04b_periodico.png'))
    plt.close(fig)
    print('  04b_periodico.png')


# =============================================================================
# El LARGO de la ventana muerta: delta contra distribución
# =============================================================================
# No paralizable: la ventana dura τ siempre. El largo es una delta.
#
# Paralizable: cada arribo que cae adentro la REABRE, así que el período muerto
# dura τ más la suma de los huecos entre los arribos del racimo. Con K el número
# de extensiones y X_i el hueco de cada una:
#
#     L = τ + Σ_{i=1}^{K} X_i
#     P(K = k) = p^k (1-p),  p = P(hueco < τ) = 1 - e^{-ρ}
#     X_i ~ exponencial truncada a (0, τ]
#
# La densidad de L no hace falta simularla: la suma geométrica de convoluciones
# tiene forma cerrada en Fourier. Con u(x) = ρ·e^{-ρx} en (0,1] —la densidad
# SUB-probabilística de "hay extensión y mide x", que integra p— la densidad de
# la parte extendida es
#
#     ĝ(ω) = (1-p) / (1 - û(ω))
#
# donde el término k=0 de la serie es el átomo de masa e^{-ρ} en L = τ: el
# período muerto que no se extiende ni una vez. De ahí sale, exacto,
#
#     E[L] = (e^{ρ} - 1)/n = τ·(e^{ρ} - 1)/ρ
#
# que es el número que importa: a ρ = 0.59 (100 kcps con el τ = 5.9 µs del MCA)
# el período muerto medio ya es 36 % más largo que un pulso solo.

def largo_muerto_densidad(rho, x_max=32.0, n=2**16):
    """Densidad del largo del período muerto paralizable, en unidades de τ.

    Devuelve `(x, g, atomo)`: la grilla desde 1 (el mínimo posible), la
    densidad de la parte continua, y la masa de probabilidad del átomo en
    L = τ, que vale e^{-ρ}.

    `x_max/n` tiene que dar un `1/h` entero para que el corte de la
    exponencial truncada caiga justo en una muestra; con los bordes a medio
    peso (trapecio) la masa da 1 y E[L] coincide con la fórmula exacta en
    cinco decimales, que es lo que valida `tabla()`.
    """
    h = x_max / n
    i1 = int(round(1.0 / h))
    assert abs(i1 * h - 1.0) < 1e-12, 'x_max/n tiene que dar 1/h entero'
    y = np.arange(n) * h                       # L/τ - 1, la parte extendida
    u = np.where(y <= 1.0 + 1e-12, rho * np.exp(-rho * y), 0.0)
    u[0] *= 0.5
    u[i1] *= 0.5
    g = np.fft.irfft(math.exp(-rho) / (1.0 - np.fft.rfft(u * h)), n) / h
    atomo = math.exp(-rho)
    g[0] -= atomo / h                          # el átomo sale del continuo
    return 1.0 + y, np.maximum(g, 0.0), atomo


def largo_muerto_cuantiles(rho, qs=(0.5, 0.9), x_max=32.0, n=2**16):
    """Cuantiles del largo del período muerto paralizable, en unidades de τ."""
    x, g, atomo = largo_muerto_densidad(rho, x_max, n)
    cdf = atomo + np.cumsum(g) * (x[1] - x[0])
    return [float(np.interp(q, cdf, x)) for q in qs]


def largo_muerto_medio(rho):
    """E[L]/τ, analítico."""
    return (math.exp(rho) - 1.0) / rho if rho > 0 else 1.0


def racimos_paralizable(t, tau):
    """Períodos muertos del modelo paralizable sobre un tren de arribos.

    Un racimo es una corrida maximal de arribos separados por menos de τ.
    Cada racimo registra SÓLO a su primer arribo y bloquea desde ahí hasta τ
    después del ÚLTIMO. Devuelve `(ok, periodos)`.
    """
    ok = np.zeros(t.size, bool)
    periodos = []
    i = 0
    while i < t.size:
        j = i
        while j + 1 < t.size and (t[j + 1] - t[j]) < tau:
            j += 1
        ok[i] = True
        periodos.append((t[i], t[j] + tau))
        i = j + 1
    return ok, periodos


def _acotar(ax, t0, t1, y, texto):
    """Línea de cota entre t0 y t1 con el largo escrito encima."""
    ax.annotate('', (t0, y), (t1, y),
                arrowprops=dict(arrowstyle='<|-|>', mutation_scale=7,
                                lw=1.1, color=ROJO, shrinkA=0, shrinkB=0))
    ax.annotate(texto, ((t0 + t1) / 2, y), xytext=(0, 3),
                textcoords='offset points', ha='center', va='bottom',
                fontsize=8.5, color=ROJO)


def fig_ventana_muerta_tren(out, rho, nombre, seed=11, t_fin=24.0):
    """El mismo tren de arribos, con las dos reglas, una arriba de la otra.

    Es la figura del mecanismo: con los MISMOS arribos, el no paralizable
    recorta ventanas de largo τ siempre, y el paralizable las encadena. Lo
    que hay que mirar es el ANCHO de las bandas grises, no los arribos; por
    eso cada período muerto lleva su largo acotado arriba.

    Una figura por ρ: con dos ρ en la misma imagen el ojo compara el ρ de
    arriba con el de abajo en vez de comparar las dos reglas, que es la
    comparación que importa.
    """
    rng = np.random.default_rng(seed)
    t = np.cumsum(rng.exponential(1.0 / rho, size=int(4 * rho * t_fin) + 200))
    t = t[t < t_fin]

    fig, axs = plt.subplots(2, 1, figsize=(8.6, 3.5), sharex=True,
                            layout='constrained')

    # --- no paralizable: todas las ventanas miden τ
    ok = servir_k1(t, 1.0)
    _tren(axs[0], t, ok, 1.0, t_fin)
    axs[0].set_ylim(0, 1.55)
    t0 = t[ok][0]
    _acotar(axs[0], t0, t0 + 1.0, 1.05, r'1,0 $\tau$')
    axs[0].set_ylabel('no\nparalizable', rotation=0, labelpad=42,
                      va='center', ha='right', color=TINTA2, fontsize=9)

    # --- paralizable: cada arribo de adentro la reabre
    ok, periodos = racimos_paralizable(t, 1.0)
    ax = axs[1]
    for p0, p1 in periodos:
        ax.axvspan(p0, min(p1, t_fin), color=GRILLA, lw=0)
    ax.vlines(t[ok], 0, 1, color=AZUL, lw=1.4)
    ax.vlines(t[~ok], 0, 0.55, color=ROJO, lw=1.4)
    for p0, p1 in periodos:
        if p1 <= t_fin and p1 - p0 > 1.02:        # los que se extendieron
            _acotar(ax, p0, p1, 1.05, f'{p1 - p0:.1f}'.replace('.', ',')
                    + r' $\tau$')
    ax.set_xlim(0, t_fin)
    ax.set_ylim(0, 1.55)
    ax.set_yticks([])
    ax.grid(False)
    for lado in ('top', 'right', 'left'):
        ax.spines[lado].set_visible(False)
    ax.set_ylabel('paralizable', rotation=0, labelpad=42, va='center',
                  ha='right', color=TINTA2, fontsize=9)

    axs[0].vlines([], 0, 1, color=AZUL, lw=1.4, label='registrado')
    axs[0].vlines([], 0, 1, color=ROJO, lw=1.4, label='perdido')
    axs[0].fill_between([], [], [], color=GRILLA, label='período muerto')
    axs[0].annotate('', (0, 0), (0, 0),
                    arrowprops=dict(arrowstyle='<|-|>', color=ROJO, lw=1.1))
    axs[0].plot([], [], color=ROJO, lw=1.1,
                label=r'largo del período muerto $[\tau]$')
    axs[0].legend(loc='lower left', ncol=4, fontsize=8.5,
                  bbox_to_anchor=(0.0, 1.02))
    axs[0].set_title(rf'$\rho = n\tau = {rho:g}$'.replace('.', ','),
                     loc='right', fontsize=10, color=TINTA2, pad=8)
    axs[1].set_xlabel(r'tiempo  $[\tau]$')

    fig.savefig(os.path.join(out, nombre))
    plt.close(fig)
    print(f'  {nombre}')


def fig_largo_ventana_muerta(out, rhos=(0.2, 0.5, 1.0, 2.0)):
    """La distribución del largo del período muerto.

    (a) la densidad: el no paralizable es una delta en L = τ; el paralizable
        conserva un átomo en τ de masa e^{-ρ} y le crece una cola.
    (b) la cola, P(L > x), en semilog.
    """
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(8.6, 3.8),
                                     layout='constrained')
    cols = [RAMPA[i] for i in (0, 1, 2, 4)]

    # --- (a) la densidad, con el átomo en L = τ como masa de probabilidad
    ax_a.vlines(1.0, 0, 1.0, color=TINTA, lw=2.4)
    ax_a.plot([1.0], [1.0], 'o', ms=7, color=TINTA,
              label='no paralizable: δ en τ')
    for rho, col in zip(rhos, cols):
        x, g, atomo = largo_muerto_densidad(rho)
        ax_a.plot(x, g, color=col, lw=1.6, label=rf'$\rho = {rho:g}$')
        ax_a.plot([1.0], [atomo], 'o', ms=6.5, color=col, zorder=6)
    ax_a.plot([], [], 'o', ms=6.5, color=MUDO,
              label=r'átomo en $\tau$:  $e^{-\rho}$')
    ax_a.set_xlim(0.85, 5.0)
    ax_a.set_ylim(0, 1.12)
    ax_a.set_xlabel(r'largo del período muerto  $L/\tau$')
    ax_a.set_ylabel('densidad   ·   masa del átomo')
    ax_a.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_a)
    _panel(ax_a, 'a')

    # --- (b) la cola
    for rho, col in zip(rhos, cols):
        x, g, atomo = largo_muerto_densidad(rho)
        sf = 1.0 - (atomo + np.cumsum(g) * (x[1] - x[0]))
        ax_b.semilogy(x, np.clip(sf, 1e-6, 1.0), color=col, lw=1.6,
                      label=rf'$\rho = {rho:g}$')
    ax_b.semilogy([1.0, 1.0], [1.0, 1e-6], color=TINTA, lw=2.0, ls='--',
                  label='no paralizable')
    ax_b.set_xlim(1.0, 8.0)
    ax_b.set_ylim(1e-4, 1.3)
    ax_b.set_xlabel(r'$x/\tau$')
    ax_b.set_ylabel(r'$P(L > x)$')
    ax_b.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_b)
    _panel(ax_b, 'b')

    fig.savefig(os.path.join(out, '02e_largo_ventana_muerta.png'))
    plt.close(fig)
    print('  02e_largo_ventana_muerta.png')


def fig_largo_vs_tasa(out, tau_mca_us=5.9, qs=(0.5, 0.9)):
    """Cómo crece el largo del período muerto con la tasa.

    (a) media, mediana y p90 contra ρ, con el eje de tasa del MCA arriba.
    (b) POR QUÉ los cuantiles arrancan planos en τ: la distribución tiene un
        átomo en L = τ de masa e^{-ρ}, y mientras esa masa sea mayor que el
        cuantil pedido, el cuantil CAE ADENTRO del átomo y vale exactamente
        τ. El p90 despega en e^{-ρ} = 0.9, o sea ρ = ln(10/9) = 0.105, y la
        mediana en e^{-ρ} = 0.5, o sea ρ = ln 2 = 0.693. La MEDIA, en cambio,
        no es plana en ningún tramo: vale (e^ρ-1)/ρ ≈ 1 + ρ/2 desde el
        origen; lo que pasa es que arranca con pendiente 1/2 y a ρ chico se
        confunde con una recta horizontal.
    """
    fig, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(8.0, 6.4),
                                     layout='constrained',
                                     gridspec_kw={'height_ratios': [1.55, 1.0]})

    # --- (a) las curvas
    r = np.linspace(0.005, 2.5, 300)
    med = np.array([largo_muerto_medio(ri) for ri in r])
    q50 = np.array([largo_muerto_cuantiles(ri, qs)[0] for ri in r])
    q90 = np.array([largo_muerto_cuantiles(ri, qs)[1] for ri in r])
    ax_a.fill_between(r, q50, q90, color=VERDE, alpha=0.14, lw=0,
                      label='paralizable: mediana a p90')
    ax_a.plot(r, med, color=VERDE, lw=2.2, label=r'media  $(e^{\rho}-1)/\rho$')
    ax_a.plot(r, q90, color=VERDE, lw=1.2, ls=':', label='p90')
    ax_a.plot(r, q50, color=VERDE, lw=1.2, ls='--', label='mediana')
    ax_a.axhline(1.0, color=TINTA, lw=1.8, label=r'no paralizable: $L = \tau$')

    rho_mediana = math.log(2.0)
    rho_p90 = math.log(1.0 / qs[1])
    for rho_q, lab in ((rho_p90, 'p90'), (rho_mediana, 'mediana')):
        ax_a.plot([rho_q], [1.0], '|', ms=14, mew=2.0, color=ROJO, zorder=6)
        ax_a.annotate(f'{lab} despega en ρ = {rho_q:.2f}'.replace('.', ','),
                      (rho_q, 1.0), xytext=(4, -6), textcoords='offset points',
                      fontsize=8.5, color=ROJO, va='top')

    rho_100k = 1e5 * tau_mca_us * 1e-6
    ax_a.plot([rho_100k], [largo_muerto_medio(rho_100k)], 'o', ms=7,
              color=ROJO, zorder=6,
              label=f'MCA a 100 kcps: {largo_muerto_medio(rho_100k):.2f} τ')
    ax_a.set_xlim(0, 2.5)
    ax_a.set_ylim(0.82, 4.0)
    ax_a.set_xlabel(r'$\rho = n\tau$')
    ax_a.set_ylabel(r'largo del período muerto  $[\tau]$')
    ax_a.legend(loc='upper left', fontsize=8.5)
    _limpiar(ax_a)
    _panel(ax_a, 'a')
    sec = ax_a.secondary_xaxis(
        'top', functions=(lambda x: x / (tau_mca_us * 1e-3),
                          lambda k: k * tau_mca_us * 1e-3))
    sec.set_xlabel(f'tasa incidente [kcps] con el τ = {tau_mca_us} µs '
                   'del MCA en modo 0')

    # --- (b) por qué: la masa del átomo contra el cuantil pedido
    ax_b.plot(r, np.exp(-r), color=TINTA, lw=2.0,
              label=r'$P(L = \tau) = e^{-\rho}$')
    for q, rho_q, col, lab in ((qs[1], rho_p90, VERDE, 'p90'),
                               (qs[0], rho_mediana, VERDE, 'mediana')):
        ax_b.axhline(q, color=col, lw=1.1,
                     ls=':' if lab == 'p90' else '--',
                     label=f'cuantil {lab}  (q = {q:g})')
        ax_b.plot([rho_q], [q], 'o', ms=6.5, color=ROJO, zorder=6)
        ax_b.vlines(rho_q, 0, q, color=ROJO, lw=1.0, ls='-', alpha=0.6)
    ax_b.set_xlim(0, 2.5)
    ax_b.set_ylim(0, 1.02)
    ax_b.set_xlabel(r'$\rho = n\tau$')
    ax_b.set_ylabel('masa en  $L = \\tau$')
    ax_b.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_b)
    _panel(ax_b, 'b')

    fig.savefig(os.path.join(out, '02f_largo_vs_tasa.png'))
    plt.close(fig)
    print('  02f_largo_vs_tasa.png')


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
    print('largo del período muerto paralizable, en unidades de tau')
    print('   rho   P(L=tau)   E[L] num   E[L] exacto   mediana      p90')
    for r in (0.1, 0.2, 0.5, 0.59, 1.0, 1.5, 2.0):
        x, g, atomo = largo_muerto_densidad(r)
        dx = x[1] - x[0]
        masa = atomo + g.sum() * dx
        e_num = atomo * 1.0 + (x * g).sum() * dx
        q50, q90 = largo_muerto_cuantiles(r)
        print(f'  {r:5g}   {atomo:8.3f}   {e_num/masa:8.4f}   '
              f'{largo_muerto_medio(r):11.4f}   {q50:7.2f}  {q90:7.2f}')
    print('  (E[L] numérico es la validación de la densidad por Fourier')
    print('   contra la fórmula exacta E[L] = tau(e^rho - 1)/rho)')

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
    fig_tren_poisson(a.out)
    fig_integral(a.out)
    fig_ventana_muerta_tren(a.out, 0.5, '02c_tren_rho05.png')
    fig_ventana_muerta_tren(a.out, 1.5, '02d_tren_rho15.png')
    fig_largo_ventana_muerta(a.out)
    fig_largo_vs_tasa(a.out)
    fig_cola(a.out)
    fig_trenes_periodicos(a.out)
    fig_periodico(a.out)
    tabla()


if __name__ == '__main__':
    main()
