#!/usr/bin/env python3
"""Figuras de `limites_resolucion_y_deriva.md`.

Misma convención que [`figuras_resolucion.py`](figuras_resolucion.py): sin texto
explicativo adentro de la figura, sólo ejes y las marcas imprescindibles. La
paleta y el rcParams se importan de ahí para que las figuras del proyecto sean
un solo sistema visual.

Todos los números se RECALCULAN acá desde los datos medidos o desde las
fórmulas, no se copian del documento: si el documento y la figura se
desincronizan, es un bug de este script.

    python3 figuras_limites.py [--out DIR]
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

# Paleta, rcParams y helpers compartidos con las figuras de resolución.
from figuras_resolucion import (SUP, TINTA, TINTA2, MUDO, GRILLA,  # noqa: E402
                               AZUL, NARAN, ROJO, RAMPA, FWHM_K,
                               _limpiar, _panel, _gauss, _cdf)

NPZ_CAMPANA = os.path.join(_AQUI, '..', '..', '..', 'software', 'datos',
                           'mca_gate_esp_v2', 'sweep_gate_espectro.npz')

RES_PCT   = 0.106      # FWHM/centroide a fondo de escala, modo compuerta (§14.1b)
TASA_MAX  = 794e3      # cps sin pérdidas (§13.1)
AW        = 13         # eje de 8192 canales
CW        = 32         # ancho del contador de bin


# =============================================================================
# Los cinco números, recalculados
# =============================================================================

def limites(fwhm_can=None):
    """Devuelve los límites del sistema expresados TODOS en unidades de FWHM.

    Ponerlos en la misma unidad es todo el punto: es lo que permite ver que
    están separados por órdenes de magnitud, y cuál es el que ata.
    """
    if fwhm_can is None:
        # FWHM a fondo de escala sobre un eje de 2^AW usado entero, sacado de
        # la campaña medida: se reescala el centroide máximo al último canal.
        z = np.load(NPZ_CAMPANA)
        cen, fw = z['cen_gate'], z['fwhm_gate']
        fwhm_can = float(fw[-1] * ((2 ** AW - 1) / cen[-1]))

    sigma = fwhm_can / 2.355

    # (1) Saturación del contador. El bin del pico se lleva 1/(sigma*sqrt(2pi))
    # del total, así que el contador satura con esa fracción inversa de cuentas.
    frac_pico = 0.3989 / sigma
    n_sat     = (2 ** CW) / frac_pico
    # Piso estadístico ahí: Cramer-Rao para la separación de dos gaussianas,
    # d_min = 1.73/(2N)^(1/4) en unidades de sigma.
    d_sat     = 1.732 / (2 * n_sat) ** 0.25
    contador  = 2 * d_sat / 2.355                      # separación, en FWHM

    # (2) Pérdida por binning (Sheppard): sigma_ef^2 = sigma^2 + delta^2/12,
    # con delta = 1 canal.
    binning = np.sqrt(1 + 1 / (12 * sigma ** 2)) - 1   # ya es fracción de sigma

    return {
        'fwhm_can': fwhm_can, 'sigma_can': sigma,
        'frac_pico': frac_pico, 'n_sat': n_sat,
        'horas_sat': n_sat / TASA_MAX / 3600,
        'contador': contador,
        'binning': binning,
        'tolerancia': 0.32,                            # <5% de degradación
        'deriva_x36': 1.28 / RES_PCT,
        'deriva_full': 6.45 / RES_PCT,
    }


# =============================================================================
# Apéndice A: información de Fisher
# =============================================================================
#
# El apéndice A del documento afirma tres cosas que no son fórmulas de manual y
# que por lo tanto conviene recalcular: (1) que I(d) ~ 2d^2 es buena al 1 % en
# el rango que se usa, (2) que con intensidades desiguales la información
# PERFILADA sobre la posición global sigue anulándose como d^2, con
# coeficiente 2*[4w(1-w)]^2, y (3) que el estimador por curtosis necesita el
# denominador (1+d^2)^2 porque opera lejos del régimen de d chico.

_X = np.linspace(-40, 40, 400001)          # grilla para las integrales de Fisher


def _phi(t):
    return np.exp(-t ** 2 / 2) / np.sqrt(2 * np.pi)


def fisher_mezcla(d, w=0.5):
    """Información de Fisher de la mezcla, exacta (por cuadratura).

    Devuelve (I_dd, I_perfilada). La perfilada descuenta la dirección que se
    lleva el parámetro de molestia `mu` (la posición global del doblete):
    I_dd - I_dmu^2/I_mumu. Es la que importa, porque en un espectro real nunca
    se sabe de antemano dónde tiene que caer el centro.
    """
    x = _X
    a, b = _phi(x - d), _phi(x + d)
    p = np.maximum(w * a + (1 - w) * b, 1e-300)
    d_mu = w * (x - d) * a + (1 - w) * (x + d) * b      # dp/dmu en mu=0
    d_d  = w * (x - d) * a - (1 - w) * (x + d) * b      # dp/dd
    I_dd = np.trapz(d_d ** 2 / p, x)
    I_mm = np.trapz(d_mu ** 2 / p, x)
    I_dm = np.trapz(d_mu * d_d / p, x)
    return I_dd, I_dd - I_dm ** 2 / I_mm


def d_min_cr(n, k=3.0, exacta=False):
    """Separación mínima detectable a k sigmas, en unidades de sigma.

    La condición es de PUNTO FIJO, `d > k/sqrt(n*I(d))`, porque I depende de d:
    de ahí sale el exponente 1/4 y no el 1/2 de siempre. Con `exacta=False` se
    usa I = 2d^2 y la condición se resuelve en forma cerrada; con `exacta=True`
    se resuelve por bisección contra la I integrada.
    """
    if not exacta:
        return np.sqrt(k) / (2 * n) ** 0.25
    lo, hi = 1e-5, 3.0
    for _ in range(80):
        d = 0.5 * (lo + hi)
        if d > k / np.sqrt(n * fisher_mezcla(d)[0]):
            hi = d
        else:
            lo = d
    return 0.5 * (lo + hi)


def d_min_curtosis(n, k=3.0, aprox=False):
    """Lo mismo para un estimador por exceso de curtosis.

    gamma2 = -2d^4/(1+d^2)^2 y SE(gamma2) ~ sqrt(24/n), así que la detección
    pide 2d^4/(1+d^2)^2 = k*SE. Con `aprox=True` se tira el denominador, que es
    lo que NO se puede hacer acá: el estimador opera en d ~ 0.3-0.6.
    """
    se = np.sqrt(24.0 / n)
    if aprox:
        return (k * se / 2) ** 0.25
    u = np.sqrt(1.5 * se) if k == 3.0 else np.sqrt(k * se / 2)
    return np.sqrt(u / (1 - u))


def fisher_bineada(d, delta, nsig=14.0, n_fase=8):
    """Información de Fisher sobre `d` cuando los datos vienen HISTOGRAMADOS.

    Con bins de ancho `delta` (en unidades de sigma) lo que se observa es una
    multinomial, y su información es `sum_k (dP_k/dd)^2 / P_k` con
    `P_k = integral del bin`. No hace falta integrar nada: la integral de la
    densidad es una diferencia de CDFs, y su derivada respecto de `d` es una
    diferencia de densidades.

    Comparar esto con la información sin binear es la forma honesta de
    responder "¿sirve agregar canales?": lo que el bineado destruye es
    información, y ningún análisis posterior la recupera.

    Se promedia sobre `n_fase` corrimientos de la grilla dentro de un bin
    porque con pocos canales la información depende bastante de DÓNDE caen los
    bordes respecto del pico, y esa fase es arbitraria: el pico cae donde cae.
    Sin el promedio la curva sale con escalones que parecen ruido numérico y
    son un artefacto de haber fijado la grilla.
    """
    tot = 0.0
    for f in range(n_fase):
        b = np.arange(-nsig, nsig + delta, delta) + f * delta / n_fase
        P  = 0.5 * (_cdf(b, d, 1.0) + _cdf(b, -d, 1.0))
        dP = 0.5 * (_phi(b + d) - _phi(b - d))      # d/dd de esa CDF
        Pk, dPk = np.diff(P), np.diff(dP)
        m = Pk > 1e-15
        tot += float(np.sum(dPk[m] ** 2 / Pk[m]))
    return tot / n_fase


def retencion(d, can_por_fwhm):
    """Fracción de la información sobre `d` que sobrevive al bineado.

    Se normaliza con la Fisher EXACTA y no con la aproximación 2d^2, para que
    el límite de bin infinitamente fino sea 1 y la curva mida sólo el bineado.
    """
    i0 = fisher_mezcla(d)[0]
    return np.array([fisher_bineada(d, FWHM_K / c) / i0
                     for c in np.atleast_1d(can_por_fwhm)])


def significancia(d, n):
    """S = d/sigma_d, el número de sigmas con que se detecta la separación.

    Usa la Fisher exacta porque las figuras barren hasta d ~ 1.2 sigma, donde
    la aproximación 2d^2 ya sobreestima un 60 %. A d chico vale d^2*sqrt(2N).
    """
    return d * np.sqrt(np.asarray(n, float) * fisher_mezcla(d)[0])


def apendice_fisher(ns=(1e4, 1e5, 1e6)):
    """Imprime las tablas del apéndice A."""
    print('\n--- apendice A: informacion de Fisher ---')
    print('A.4  calidad de la aproximacion I ~ 2d^2:')
    for d in (0.0033, 0.046, 0.082, 0.146, 0.20, 0.30):
        r = fisher_mezcla(d)[0] / (2 * d * d)
        print(f'     d={d:7.4f} sigma   I_exacta/2d^2 = {r:.4f}')

    print('A.3/A.4  d_min de Cramer-Rao (3 sigma), en unidades de sigma:')
    for n in ns:
        f, e = d_min_cr(n), d_min_cr(n, exacta=True)
        print(f'     N={n:9.3g}  formula={f:.5f}  exacta={e:.5f}  '
              f'({100*(e/f-1):+.1f} %)   separacion 2d = {2*f/2.355:.4f} FWHM')

    print('A.5  dependencia con el criterio de k sigmas, a N=1e6:')
    for k in (1, 2, 3, 5):
        print(f'     {k} sigma: prefactor {np.sqrt(k):.2f}  '
              f'd_min={d_min_cr(1e6, k=k):.4f} sigma')

    print('A.6  intensidades desiguales: I_perfilada = 2*[4w(1-w)]^2*d^2')
    for w in (0.5, 0.4, 0.3, 0.2, 0.1):
        # d chico a propósito: el coeficiente teórico es el límite d -> 0.
        c_num = fisher_mezcla(0.02, w=w)[1] / 0.02 ** 2
        g2 = (4 * w * (1 - w)) ** 2
        print(f'     w={w:4.2f}  coef numerico={c_num:.4f}  teorico={2*g2:.4f}'
              f'   N_ef/N={g2:.2f}  d_min relativo={g2 ** -0.25:.2f}')

    print('A.7  estimador por curtosis (3 sigma), en unidades de sigma:')
    for n in ns:
        print(f'     N={n:7.1g}  gamma2 exacta={d_min_curtosis(n):.3f}  '
              f'aproximada={d_min_curtosis(n, aprox=True):.3f}')


# =============================================================================
# Figura: la jerarquía de límites
# =============================================================================

def fig_jerarquia(L, out):
    """Los cuatro efectos en un eje logarítmico común, contra la tolerancia.

    PUNTOS y no barras: una barra codifica LARGO desde un cero, y en un eje
    logarítmico no hay cero — el largo terminaría dependiendo de dónde se corte
    el eje, que es una decisión de dibujo y no un dato. El punto codifica
    posición, que es lo único que acá significa algo. La línea fina hasta el
    marcador es sólo guía de lectura y arranca en el borde, no en un origen.

    La tolerancia va como línea de referencia y no como serie: es un umbral.
    """
    filas = [
        ('Saturación del contador de 32 b',      L['contador'],   False),
        ('Pérdida por binning (Sheppard)',       L['binning'],    False),
        ('Deriva medida, ×36 de tasa',           L['deriva_x36'], True),
        ('Deriva medida, barrido completo',      L['deriva_full'],True),
    ]
    y = np.arange(len(filas))[::-1]

    fig, ax = plt.subplots(figsize=(7.6, 3.1))
    for yi, (_, val, viola) in zip(y, filas):
        col = ROJO if viola else AZUL
        ax.plot([5e-4, val], [yi, yi], color=GRILLA, lw=1.4, zorder=2,
                solid_capstyle='butt')
        ax.plot([val], [yi], 'o', ms=11, color=col, mec=SUP, mew=2, zorder=4)
        # Etiqueta directa: la identidad nunca depende sólo del color.
        txt = f'{val:.4f}'.rstrip('0') if val < 1 else f'{val:.0f}'
        ax.text(val * 1.45, yi, txt, va='center', ha='left',
                color=TINTA, fontsize=9.5, zorder=4)

    ax.axvline(L['tolerancia'], color=TINTA2, lw=1.6, ls='--', zorder=2)
    ax.text(L['tolerancia'] * .88, y[0] + .52,
            f'tolerancia  {L["tolerancia"]:.2f}', rotation=90,
            va='bottom', ha='right', color=TINTA2, fontsize=9)

    ax.set_xscale('log')
    ax.set_xlim(5e-4, 5e2)
    ax.set_ylim(-.55, len(filas) - .25)
    ax.set_yticks(y)
    ax.set_yticklabels([f[0] for f in filas], color=TINTA, fontsize=9.5)
    ax.set_xlabel('en unidades de FWHM  (escala logarítmica)')
    ax.grid(axis='x', color=GRILLA, lw=.8, zorder=0)
    ax.set_axisbelow(True)
    _limpiar(ax)
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y', length=0)

    fig.tight_layout()
    p = os.path.join(out, '08_jerarquia_limites.png')
    fig.savefig(p, dpi=160)
    plt.close(fig)
    return p


# =============================================================================
# Figura: qué compran las cuentas, y qué compran los canales
# =============================================================================

# Las dos separaciones que se contrastan, en unidades de sigma:
#   ANCHA  -> el caso "del ojo". La mezcla simétrica es bimodal sólo si
#             d > 1 sigma, y además el valle arranca siendo ridículo: a 2d = 1
#             FWHM el hundimiento es del 6 % y no se ve. A 2d = 1.2 FWHM el
#             valle baja al 72 % del pico, que ya es un valle de verdad.
#   FINA   -> el caso "de la verosimilitud": elegida para que el umbral de
#             3 sigma de Cramér-Rao caiga en N = 1e4, en el medio del barrido.
#             No hay nada que ver y sin embargo hay algo que medir.
D_ANCHA = 0.6 * FWHM_K          # separación 2d = 1.2 FWHM  ->  d = 1.41 sigma
D_FINA  = 0.15                  # separación 2d = 0.127 FWHM
NS_STRIP = (1e2, 1e3, 1e4, 1e5, 1e6)


def _muestra(d, n, rng):
    return rng.choice([-d, d], size=int(n)) + rng.standard_normal(int(n))


def _hist_densidad(m, delta, lim):
    """Histograma normalizado a densidad, para que distintas N y distintos
    anchos de bin se puedan comparar sobre el mismo eje."""
    b = np.arange(-lim, lim + delta, delta)
    h, _ = np.histogram(m, bins=b)
    return b, h / (h.sum() * delta)


def fig_cuentas_vs_canales(out, semilla=7):
    """Figura 14: la separación detectable contra las CUENTAS.

    Dos tiras de histogramas con la misma separación en cada fila y N creciente
    de 1e2 a 1e6, más la curva de significancia que explica las dos filas. La
    fila de arriba es la intuición (el valle emerge del ruido); la de abajo es
    el punto del apéndice A: el ojo no ve NADA en ninguna N y sin embargo la
    separación se vuelve medible a 3 sigma en el medio del barrido.
    """
    rng = np.random.default_rng(semilla)
    delta = FWHM_K / 6                      # ~6 canales/FWHM, como el MCA
    fig = plt.figure(figsize=(9.6, 5.6))
    gs = fig.add_gridspec(3, len(NS_STRIP), height_ratios=[1, 1, 1.35],
                          hspace=.55, wspace=.25)

    for fila, (d, col) in enumerate(((D_ANCHA, AZUL), (D_FINA, NARAN))):
        lim = 4.2 + d
        x = np.linspace(-lim, lim, 600)
        # La gaussiana única de los MISMOS momentos: es con lo que hay que
        # comparar, no con una de sigma 1. sigma_ef^2 = 1 + d^2.
        unica = _gauss(x, 0, np.sqrt(1 + d * d)) / (np.sqrt(2 * np.pi * (1 + d * d)))
        mezcla = 0.5 * (_phi(x - d) + _phi(x + d))
        # Se histograma TODA la fila antes de dibujar, para que las cinco N
        # compartan la escala vertical: es lo que hace comparable la fila, y
        # lo que deja ver que lo único que cambia con N es el ruido. La escala
        # la fija el dato más alto —el pico de Poisson de la N más chica—, así
        # que nada queda recortado.
        hs = [_hist_densidad(_muestra(d, n, rng), delta, lim) for n in NS_STRIP]
        y_top = 1.06 * max(h.max() for _, h in hs)
        for j, (n, (b, h)) in enumerate(zip(NS_STRIP, hs)):
            ax = fig.add_subplot(gs[fila, j])
            ax.stairs(h, b, color=col, lw=1.1, fill=True, alpha=.30)
            ax.stairs(h, b, color=col, lw=1.1)
            ax.plot(x, mezcla, color=TINTA, lw=1.2,
                    label='mezcla verdadera' if (fila, j) == (0, 0) else None)
            ax.plot(x, unica, color=TINTA2, lw=1.1, ls='--',
                    label='gaussiana única' if (fila, j) == (0, 0) else None)
            ax.set_xlim(-lim, lim)
            ax.set_ylim(0, y_top)
            ax.set_yticks([])
            ax.set_xticks([-d, d])
            ax.set_xticklabels([])
            ax.tick_params(length=2.5)
            ax.grid(False)
            _limpiar(ax)
            ax.spines['left'].set_visible(False)
            if fila == 0:
                ax.set_title(f'N = $10^{int(np.log10(n))}$', color=TINTA2,
                             fontsize=9.5, pad=5)
            if j == 0:
                ax.set_ylabel(f'2d = {2*d/FWHM_K:.2f} FWHM', fontsize=9,
                              color=col)
                _panel(ax, '(a)' if fila == 0 else '(b)')
            # La leyenda va en el hueco entre la tira de abajo y el panel (c),
            # que es la única zona de la figura sin datos.
            if (fila, j) == (1, 0):
                ax.legend(*fig.axes[0].get_legend_handles_labels(),
                          loc='upper left', fontsize=8, ncol=2,
                          bbox_to_anchor=(-.02, -.12), handlelength=1.8,
                          columnspacing=1.6)

    # --- panel ancho: la significancia, que es lo que de verdad crece --------
    ax = fig.add_subplot(gs[2, :])
    _panel(ax, '(c)')
    nn = np.logspace(1.6, 7, 200)
    for d, col, lbl in ((D_ANCHA, AZUL, f'2d = {2*D_ANCHA/FWHM_K:.2f} FWHM'),
                        (D_FINA, NARAN, f'2d = {2*D_FINA/FWHM_K:.2f} FWHM')):
        s = significancia(d, nn)
        ax.plot(nn, s, color=col, lw=1.8, label=lbl)
        # Dónde cruza los 3 sigma: es el N mínimo para afirmar que son dos.
        i0 = fisher_mezcla(d)[0]
        n_umbral = 9.0 / (d * d * i0)
        if nn[0] < n_umbral < nn[-1]:
            ax.plot([n_umbral], [3], 'o', ms=8, color=col, mec=SUP, mew=1.8,
                    zorder=5)
    ax.axhline(3, color=ROJO, lw=1.4, ls='--', zorder=2,
               label='umbral de detección, 3 sigma')
    for n in NS_STRIP:
        ax.axvline(n, color=GRILLA, lw=.9, zorder=0)
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlim(nn[0], nn[-1])
    ax.set_ylim(.1, 5e3)
    ax.set_yticks([.1, 1, 3, 10, 100, 1000])
    ax.set_yticklabels(['0.1', '1', '3', '10', '100', '1000'])
    ax.set_xlabel('Cuentas acumuladas N')
    ax.set_ylabel('Significancia de la\nseparación  (sigmas)')
    ax.legend(loc='lower right', fontsize=8.5)
    ax.grid(color=GRILLA, lw=.6)
    _limpiar(ax)

    p = os.path.join(out, '14_cuentas_vs_separacion.png')
    fig.savefig(p, dpi=160, bbox_inches='tight')
    plt.close(fig)
    return p


def fig_bineado_vs_deteccion(out, n=100000, semilla=11):
    """Figura 15: a N FIJA, qué cambia al agregar resolución de bineado.

    (a) la misma muestra histogramada con cuatro anchos de bin; (b) la
    información de Fisher que sobrevive al bineado, que es la respuesta
    cuantitativa: por encima de 4 canales/FWHM la curva ya está plana, así que
    los canales de más no compran poder resolutivo. Es la sección 5 del
    documento con un número en vez de un argumento.
    """
    rng = np.random.default_rng(semilla)
    d = D_ANCHA
    lim = 4.2 + d
    m = _muestra(d, n, rng)

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(9.6, 3.6),
                                 gridspec_kw={'wspace': .28})

    # --- (a) la misma muestra, cuatro bineados -------------------------------
    _panel(ax, '(a)')
    cfs = (1, 2, 4, 16)
    for c, col in zip(cfs, (RAMPA[0], RAMPA[1], RAMPA[2], RAMPA[4])):
        b, h = _hist_densidad(m, FWHM_K / c, lim)
        ax.stairs(h, b, color=col, lw=1.5, label=f'{c} can/FWHM')
    x = np.linspace(-lim, lim, 600)
    ax.plot(x, 0.5 * (_phi(x - d) + _phi(x + d)), color=TINTA, lw=1.2, ls='--',
            label='densidad real')
    ax.set_xlim(-lim, lim)
    ax.set_xlabel('Amplitud  (sigmas)')
    ax.set_ylabel('Densidad')
    ax.legend(fontsize=8.5, loc='upper right')
    _limpiar(ax)

    # --- (b) la información que sobrevive ------------------------------------
    _panel(bx, '(b)')
    cs = np.logspace(0, np.log10(64), 60)
    r_fina = retencion(D_FINA, cs)
    r_ancha = retencion(D_ANCHA, cs)
    shep = 1.0 / (1.0 + (FWHM_K / cs) ** 2 / 12.0)
    bx.plot(cs, r_fina, color=NARAN, lw=1.9,
            label=f'2d = {2*D_FINA/FWHM_K:.2f} FWHM')
    bx.plot(cs, r_ancha, color=AZUL, lw=1.9,
            label=f'2d = {2*D_ANCHA/FWHM_K:.2f} FWHM')
    bx.plot(cs, shep, color=MUDO, lw=1.3, ls=':',
            label='Sheppard, $1/(1+\\Delta^2/12)$')
    bx.axhline(1.0, color=GRILLA, lw=1.2)
    # La banda donde trabaja el MCA, medida (§2 del documento).
    bx.axvspan(6.31, 8.64, color=ROJO, alpha=.10, zorder=0,
               label='donde trabaja el MCA')
    bx.axvline(4, color=TINTA2, lw=1.2, ls='--', zorder=1,
               label='regla de 4 can/FWHM')

    bx.set_xscale('log')
    bx.set_xlim(1, 64)
    bx.set_ylim(.3, 1.06)
    bx.set_xticks([1, 2, 4, 8, 16, 32, 64])
    bx.set_xticklabels(['1', '2', '4', '8', '16', '32', '64'])
    bx.set_xlabel('Canales por FWHM')
    bx.set_ylabel('Información sobre la separación\nque sobrevive al bineado')
    # Eje derecho: la misma curva leída como penalización en d_min. Es un
    # cambio de variable monótono (d_min ~ I^(-1/4)), no una serie nueva.
    sec = bx.secondary_yaxis('right', functions=(lambda v: np.maximum(v, 1e-6) ** -0.25,
                                                 lambda v: np.maximum(v, 1e-6) ** -4))
    sec.set_ylabel('$d_{min}$ relativo')
    bx.legend(fontsize=7.8, loc='lower right', labelspacing=.45)
    bx.grid(color=GRILLA, lw=.6)
    _limpiar(bx)
    bx.spines['right'].set_visible(True)
    bx.spines['right'].set_color('#c3c2b7')

    p = os.path.join(out, '15_bineado_vs_deteccion.png')
    fig.savefig(p, dpi=160, bbox_inches='tight')
    plt.close(fig)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=_AQUI)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    L = limites()
    print(f'FWHM a fondo de escala sobre {2**AW} canales: '
          f'{L["fwhm_can"]:.2f} canales (sigma {L["sigma_can"]:.2f})')
    print(f'bin del pico: {100*L["frac_pico"]:.1f} % del total')
    print(f'saturacion del contador: {L["n_sat"]:.3g} cuentas '
          f'= {L["horas_sat"]:.1f} h a {TASA_MAX/1e3:.0f} kcps')
    print()
    print('limites, todos en unidades de FWHM:')
    for k in ('contador', 'binning', 'tolerancia', 'deriva_x36', 'deriva_full'):
        print(f'  {k:14s} {L[k]:10.4f}')
    print(f'\nla deriva medida es {L["deriva_x36"]/L["tolerancia"]:.0f}x su '
          f'tolerancia y {L["deriva_x36"]/L["contador"]:.0f}x el limite del contador')

    # Se le pasa la N de saturación del contador para que la última fila de la
    # tabla A.3 (el límite duro de §4) salga de acá y no a mano.
    apendice_fisher(ns=(1e4, 1e5, 1e6, L['n_sat']))
    # A.2 y A.8: el centroide de UN pico es un problema regular (I = 1/sigma^2
    # independiente de mu), asi que su precision cae como 1/sqrt(N). Comparar
    # esa precision con la deriva medida es el cierre del apendice.
    sig_cen = 1 / np.sqrt(1e6) / 2.355
    print(f'A.2/A.8  sigma del centroide a N=1e6: {sig_cen:.5f} FWHM  ->  '
          f'la deriva medida es {L["deriva_x36"]/sig_cen:.3g}x')

    # --- los números de las figuras 14 y 15 ----------------------------------
    print('\nfig 14: significancia de la separacion contra las cuentas')
    for d, lbl in ((D_ANCHA, 'ancha'), (D_FINA, 'fina ')):
        s = [f'{significancia(d, n):8.2f}' for n in NS_STRIP]
        n_umbral = 9.0 / (d * d * fisher_mezcla(d)[0])
        print(f'   2d={2*d/FWHM_K:5.2f} FWHM ({lbl}): S =' + ' '.join(s) +
              f'   cruza 3 sigma en N={n_umbral:.3g}')

    print('fig 15: informacion sobre la separacion que sobrevive al bineado')
    print('   can/FWHM   retencion (fina)   d_min relativo   Sheppard')
    for c in (1, 2, 4, 6.31, 8.64, 16, 64):
        r = retencion(D_FINA, c)[0]
        shep = 1 / (1 + (FWHM_K / c) ** 2 / 12)
        print(f'   {c:8.2f}   {r:16.4f}   {r**-0.25:14.4f}   {shep:8.4f}')
    r8, r64 = retencion(D_FINA, 8.64)[0], retencion(D_FINA, 64)[0]
    print(f'   pasar de 8.64 a 64 can/FWHM mejora d_min un '
          f'{100*(1-(r8/r64)**0.25):.2f} %  (y cuesta 7.4x BRAM)')

    print('\n' + fig_jerarquia(L, a.out))
    print(fig_cuentas_vs_canales(a.out))
    print(fig_bineado_vs_deteccion(a.out))


if __name__ == '__main__':
    main()
