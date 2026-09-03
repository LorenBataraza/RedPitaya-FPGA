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
from figuras_resolucion import (SUP, TINTA, TINTA2, GRILLA,        # noqa: E402
                               AZUL, ROJO, _limpiar)

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

    print('\n' + fig_jerarquia(L, a.out))


if __name__ == '__main__':
    main()
