#!/usr/bin/env python3
"""Figuras de la geometria del mapa 2D: el limite de memoria y las N1 x N2 posibles.

La pregunta que contestan: dado que el mapa es `2^(H2_AW+PSD_AW)` palabras de
`CW` bits en BRAM, que pares (N1, N2) se pueden construir, cual es el limite que
ata en cada caso --BRAM del chip o apertura de 64 KB del bus-- y que par pide
cada aplicacion.

Misma convencion que el resto de [`figuras/`](../): SIN TEXTO ADENTRO de la
figura, solo ejes, leyenda y las marcas imprescindibles. Cuando hay que rotular
muchas cosas lo que va adentro es un NUMERO, y la explicacion en una fila de
tabla del [`README.md`](README.md). Paleta y rcParams de
[`docs/figuras/estilo.py`](../../../figuras/estilo.py).

Todos los numeros se RECALCULAN aca desde los parametros del RTL y los limites
del chip; ninguno se copia de un documento. Si una figura y un documento se
desincronizan, es un bug de este script. Las fuentes de cada constante estan
anotadas al lado.

Son ESQUEMAS de diseño: no entra ningun `.npz`. Los dos unicos numeros medidos
son el FWHM del eje (8.6 canales sobre 8192, 2a campaña) y el costo en tiles del
build actual, con el que se VALIDA el modelo de ocupacion de BRAM.

    python3 figuras_mapa2d.py [--out DIR]
"""

import argparse
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, '..', '..', '..', 'figuras'))
from estilo import (SUP, TINTA, TINTA2, MUDO, GRILLA, AZUL, NARAN,   # noqa: E402
                    ROJO, VERDE, MORADO, RAMPA, FWHM_K,
                    limpiar, panel, escribir_epigrafes)


# =============================================================================
# Los parametros, con su fuente
# =============================================================================

# Geometria y ancho de contador del build actual.
#   mca_top.sv:38-39  -> H2_AW = 7, PSD_AW = 6
#   mca_top.sv:328    -> mca_hist #(.AW(H2_AW+PSD_AW), .CW(32))
H2_AW_HOY  = 7
PSD_AW_HOY = 6
CW_HOY     = 32

# Eje 1D, para comparar.  register_map_mca.md:44 -> H_AW = 13
H_AW = 13

# Tiles de BRAM del chip.  platform.md:130
TILES_7010 = 60
TILES_7020 = 140

# Ocupacion del build.  platform.md:694 -> 25 tiles (24 RAMB36 + 2 RAMB18);
# platform.md:703-705 -> 8 en la captura del scope, 8 en el histograma 1D, el
# mapa 2D y las FIFO/CDC. El mapa 2D de hoy son 8, asi que todo lo demas son 17.
TILES_BUILD     = 25
TILES_MAPA_HOY  = 8
TILES_OTROS     = TILES_BUILD - TILES_MAPA_HOY

# Apertura del bus. register_map_mca.md:314 -> el decode es sys_addr[19:16], o
# sea 2^16 bytes por apertura.
APERTURA_B = 1 << 16

# FWHM del eje, MEDIDO: register_map_mca.md:157 da 8.6 canales/FWHM sobre los
# 2^13 canales del espectro 1D. Expresado como fraccion del fondo de escala es
# lo unico que hace falta para decidir el bineado de cualquier eje.
FWHM_CAN = 8.6
FWHM_FS  = FWHM_CAN / (1 << H_AW)

# Para la saturacion del contador: el techo de lectura medido (platform.md:520)
# y la fraccion de eventos que se lleva el bin mas caliente del mapa.
TASA_EV   = 50e3
FRAC_PICO = 0.02


# =============================================================================
# El modelo de ocupacion, validado contra el build
# =============================================================================

def palabras_por_tile(cw):
    """Palabras de `cw` bits que entran en un RAMB36.

    El tile son 36 kbit con anchos nativos 1Kx36, 2Kx18, 4Kx9. El modelo se
    VALIDA contra el build: 2^13 palabras de 32 bit tienen que dar los 8 tiles
    que platform.md §4.7 le factura al histograma 1D (ver `validar()`).

    La consecuencia que mas pesa en la decision esta en los escalones: CUALQUIER
    `cw` entre 19 y 36 cuesta lo mismo. Bajar de 32 a 24 bits no ahorra un solo
    tile; el unico ahorro real es cruzar a <=18, y eso cuesta la saturacion.
    """
    for ancho, pal in ((9, 4096), (18, 2048), (36, 1024)):
        if cw <= ancho:
            return pal
    raise ValueError(f'cw = {cw} > 36: son varios tiles en paralelo')


def tiles(aw1, aw2, cw=CW_HOY):
    """Tiles de BRAM del mapa de 2^aw1 x 2^aw2 con contadores de `cw` bits."""
    pal = 1 << (aw1 + aw2)
    return math.ceil(pal / palabras_por_tile(cw))


def bytes_apertura(aw1, aw2, cw=CW_HOY):
    """Bytes que el mapa ocupa en el espacio de direcciones del bus.

    Con `cw <= 16` se asume que el software empaqueta dos contadores por palabra
    de 32 bit; es un cambio de RTL y de `mca_utils`, no sale gratis, pero es la
    unica forma de que bajar `cw` compre bins de verdad y no solo BRAM.
    """
    return (1 << (aw1 + aw2)) * max(1, math.ceil(cw / 8))


def estado(aw1, aw2, cw=CW_HOY, apertura=APERTURA_B):
    """Que hace falta para construir ese mapa. Cuatro categorias ordenadas."""
    t = tiles(aw1, aw2, cw)
    cabe_7010 = t <= TILES_7010 - TILES_OTROS
    cabe_7020 = t <= TILES_7020 - TILES_OTROS
    cabe_ap   = bytes_apertura(aw1, aw2, cw) <= apertura
    if cabe_7010 and cabe_ap:
        return 'hoy'
    if cabe_7010:
        return 'apertura'
    if cabe_7020:
        return '7020'
    return 'no'


def techo(aw2, cw=CW_HOY, tiles_disp=None, apertura=APERTURA_B):
    """El aw1 mas grande que admite cada limite, con aw2 fijo."""
    if tiles_disp is None:
        tiles_disp = TILES_7010 - TILES_OTROS
    pal_bram = tiles_disp * palabras_por_tile(cw)
    pal_ap   = apertura // max(1, math.ceil(cw / 8))
    pal = min(pal_bram, pal_ap)
    return int(math.floor(math.log2(pal))) - aw2


def ensanche(bins_por_fwhm):
    """Ensanchamiento del pico por bineado (Sheppard): sigma_ef^2 = s^2 + w^2/12.

    En unidades de FWHM el factor es sqrt(1 + (FWHM_K/sqrt(12))^2 / nb^2), con
    nb = bins por FWHM. El coeficiente FWHM_K/sqrt(12) = 0.680 es el que hace
    que a 8.6 bins/FWHM de este eje la perdida sea 0.31 %, que es el numero que
    ya esta en register_map_mca.md:157.
    """
    k = FWHM_K / math.sqrt(12.0)
    return np.sqrt(1.0 + (k / np.asarray(bins_por_fwhm, dtype=float)) ** 2)


def t_sat(cw, tasa=TASA_EV, frac=FRAC_PICO):
    """Segundos hasta que el bin mas caliente satura el contador."""
    return (2.0 ** cw) / (tasa * frac)


# Las aplicaciones, con el par (N1, N2) que pide cada una. Los N1 salen de
# `n1_requerido()` sobre el FWHM de cada familia de detector; los N2, de que las
# dos poblaciones de forma estan separadas ~0.12 con FWHM ~0.04 en unidades de
# Q_cola/Q_total, o sea ~3 bins por FWHM con 64 bins sobre el rango completo.
# Son valores TIPICOS de literatura, no medidos: la unica fila medida es la del
# propio eje de esta placa.
APLICACIONES = [
    # n,  etiqueta,                         aw1, aw2, fwhm_fs,  medido
    (1, 'Apilamiento (corte en forma)',       6,  6,  None,     False),
    (2, 'n/gamma PSD, plastico o liquido',    7,  6,  5.4e-2,   False),
    (3, 'alfa/beta/gamma, CsI(Tl) phoswich',  8,  7,  3.1e-2,   False),
    (4, 'NaI(Tl) con compuerta',              9,  6,  1.6e-2,   False),
    (5, 'CdZnTe, corte por tiempo de subida', 10, 6,  6.7e-3,   False),
    (6, 'Telescopio dE-E',                    9,  9,  None,     False),
    (7, 'HPGe, limpieza del fotopico',       12,  7,  5.4e-4,   False),
    (8, 'Matriz gamma-gamma',                12, 12,  5.4e-4,   False),
]

COLOR_EST = {'hoy': VERDE, 'apertura': AZUL, '7020': NARAN, 'no': MUDO}
NOMBRE_EST = {
    'hoy':      'se construye hoy',
    'apertura': 'entra en la BRAM del 7010, pide apertura mayor',
    '7020':     'pide el 7020',
    'no':       'fuera de alcance en BRAM',
}


# =============================================================================
# 1. El plano de decision (N1, N2)
# =============================================================================
def fig_plano(out):
    aw1s = range(5, 14)
    aw2s = range(4, 14)

    fig, ax = plt.subplots(figsize=(7.8, 5.6))

    # Las anti-diagonales son las curvas de costo constante: el mapa depende de
    # aw1+aw2 y no de como se reparte. Es la observacion que ordena todo el
    # plano, asi que van dibujadas y no explicadas.
    for total, lab in ((14, APERTURA_B // 1024), (15, 2 * APERTURA_B // 1024),
                       (16, 4 * APERTURA_B // 1024)):
        x = np.array([total - max(aw2s), total - min(aw2s)], dtype=float)
        y = float(total) - x
        ax.plot(x, y, color=TINTA2, lw=0.9, ls=':', zorder=2)
        ax.annotate(f'{lab} KB', (total - min(aw2s) - 0.25, min(aw2s) + 0.25),
                    color=TINTA2, fontsize=8, ha='right', va='bottom',
                    rotation=-45, zorder=3)

    for aw1 in aw1s:
        for aw2 in aw2s:
            e = estado(aw1, aw2)
            ax.plot(aw1, aw2, marker='s', ms=11, color=COLOR_EST[e],
                    mec=SUP, mew=0.8, ls='none', zorder=4)

    # El build de hoy.
    ax.plot(H2_AW_HOY, PSD_AW_HOY, marker='o', ms=19, mfc='none', mec=ROJO,
            mew=2.0, ls='none', zorder=6)

    # Las aplicaciones, por numero.
    for n, _, aw1, aw2, _, _ in APLICACIONES:
        ax.annotate(str(n), (aw1, aw2), color=TINTA, fontsize=8.5,
                    fontweight='bold', ha='center', va='center', zorder=7)

    ax.set_xticks(list(aw1s))
    ax.set_xticklabels([f'$2^{{{a}}}$\n{1 << a}' for a in aw1s])
    ax.set_yticks(list(aw2s))
    ax.set_yticklabels([f'$2^{{{a}}}$' for a in aw2s])
    ax.set_xlabel('$N_1$ — bins del eje de amplitud (`H2_AW`)')
    ax.set_ylabel('$N_2$ — bins del segundo eje (`PSD_AW`)')
    ax.set_xlim(min(aw1s) - 0.6, max(aw1s) + 0.6)
    ax.set_ylim(min(aw2s) - 0.6, max(aw2s) + 0.6)

    manijas = [Line2D([], [], marker='s', ms=9, ls='none', mec=SUP,
                      color=COLOR_EST[k], label=NOMBRE_EST[k])
               for k in ('hoy', 'apertura', '7020', 'no')]
    manijas.append(Line2D([], [], marker='o', ms=11, mfc='none', mec=ROJO,
                          mew=1.8, ls='none', label='el build de hoy'))
    ax.legend(handles=manijas, loc='upper right', fontsize=8.5)
    limpiar(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(out, '01_plano_decision.png'))
    plt.close(fig)

    return dict(
        hoy=[(a1, a2) for a1 in aw1s for a2 in aw2s
             if estado(a1, a2) == 'hoy'],
        tope_7010=max(a1 + a2 for a1 in aw1s for a2 in aw2s
                      if estado(a1, a2) in ('hoy', 'apertura')),
        tope_7020=max(a1 + a2 for a1 in aw1s for a2 in aw2s
                      if estado(a1, a2) != 'no'),
        tope_hoy=max(a1 + a2 for a1 in aw1s for a2 in aw2s
                     if estado(a1, a2) == 'hoy'),
    )


# =============================================================================
# 2. El limite de memoria: quien ata, y por que CW=32 es gratis
# =============================================================================
def fig_limite(out):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.6, 4.3))

    # --- (a) tiles contra bins totales, para tres anchos de contador ---------
    totales = np.arange(10, 25)
    for cw, col in ((32, RAMPA[4]), (18, RAMPA[2]), (9, RAMPA[0])):
        t = [math.ceil((1 << k) / palabras_por_tile(cw)) for k in totales]
        ax1.plot(totales, t, color=col, lw=1.6, marker='o', ms=3,
                 label=f'CW = {cw} b')

    disp_10 = TILES_7010 - TILES_OTROS
    disp_20 = TILES_7020 - TILES_OTROS
    ax1.axhline(disp_10, color=ROJO, lw=1.3, ls='--')
    ax1.annotate(f'{disp_10} tiles libres (7010)', (10.2, disp_10), color=ROJO,
                 fontsize=8.5, va='bottom')
    ax1.axhline(disp_20, color=NARAN, lw=1.3, ls='--')
    ax1.annotate(f'{disp_20} tiles libres (7020)', (10.2, disp_20),
                 color=NARAN, fontsize=8.5, va='bottom')

    # La apertura, en bins totales, para CW = 32.
    k_ap = int(math.log2(APERTURA_B // 4))
    ax1.axvline(k_ap, color=TINTA, lw=1.2, ls=':')
    ax1.annotate('apertura 64 KB', (k_ap - 0.2, 1.6), color=TINTA, fontsize=8.5,
                 rotation=90, ha='right', va='bottom')

    ax1.plot(H2_AW_HOY + PSD_AW_HOY, TILES_MAPA_HOY, marker='o', ms=15,
             mfc='none', mec=ROJO, mew=2.0, ls='none', zorder=6)

    ax1.set_yscale('log', base=2)
    ax1.set_xlabel('Bins totales del mapa, $\\log_2(N_1 N_2)$')
    ax1.set_ylabel('Tiles de BRAM (RAMB36)')
    ax1.legend(loc='upper left', fontsize=8.5)
    panel(ax1, '(a)')
    limpiar(ax1)

    # --- (b) el escalon del tile y el precio de bajarlo ----------------------
    cws = np.arange(8, 37)
    t_necesarios = [math.ceil((1 << k_ap) / palabras_por_tile(int(c)))
                    for c in cws]
    ax2.step(cws, t_necesarios, where='post', color=AZUL, lw=1.8,
             label=f'tiles para $2^{{{k_ap}}}$ bins')
    ax2.set_xlabel('Ancho del contador CW [bits]')
    ax2.set_ylabel('Tiles de BRAM', color=AZUL)
    ax2.tick_params(axis='y', colors=AZUL)
    ax2.set_ylim(0, 1.25 * max(t_necesarios))

    axb = ax2.twinx()
    axb.plot(cws, [t_sat(int(c)) for c in cws], color=NARAN, lw=1.8,
             label='tiempo hasta saturar')
    axb.set_yscale('log')
    axb.set_ylabel('Hasta saturar el bin caliente [s]', color=NARAN)
    axb.tick_params(axis='y', colors=NARAN)
    axb.grid(False)
    for seg, et in ((3600.0, '1 h'), (86400.0, '1 dia')):
        axb.axhline(seg, color=MUDO, lw=0.8, ls=':')
        axb.annotate(et, (35.6, seg), color=MUDO, fontsize=8, ha='right',
                     va='bottom')

    # La banda donde bajar CW no ahorra nada: 19..36 bits, un solo escalon.
    ax2.axvspan(19, 36, color=VERDE, alpha=0.10, zorder=0)
    ax2.axvline(CW_HOY, color=ROJO, lw=1.3, ls='--')
    ax2.annotate('CW = 32 (hoy)', (CW_HOY - 0.4, 0.06 * max(t_necesarios)),
                 color=ROJO, fontsize=8.5, rotation=90, ha='right', va='bottom')

    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = axb.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, loc='center left', fontsize=8.5)
    panel(ax2, '(b)')
    limpiar(ax2)

    fig.tight_layout()
    fig.savefig(os.path.join(out, '02_limite_memoria.png'))
    plt.close(fig)

    return dict(disp_10=disp_10, disp_20=disp_20, k_ap=k_ap,
                t_sat_16=t_sat(16), t_sat_18=t_sat(18), t_sat_24=t_sat(24),
                t_sat_32=t_sat(32),
                tiles_ap_32=math.ceil((1 << k_ap) / palabras_por_tile(32)))


# =============================================================================
# 3. Lo que pide cada aplicacion contra lo que se alcanza
# =============================================================================
def n1_requerido(fwhm_fs, nb):
    """Bins de eje para poner `nb` bins dentro de un FWHM de `fwhm_fs` del fondo."""
    return nb / np.asarray(fwhm_fs, dtype=float)


def fig_requisito(out):
    fig, ax = plt.subplots(figsize=(7.8, 5.0))

    x = np.logspace(-4, -1, 400)
    for nb, col in ((3, RAMPA[0]), (4, RAMPA[2]), (5, RAMPA[4])):
        ax.plot(x, n1_requerido(x, nb), color=col, lw=1.7,
                label=f'{nb} bins por FWHM')

    # Los techos alcanzables con N2 = 64, que es el caso de uso real: un eje de
    # forma de 64 bins y todo el resto del presupuesto para amplitud.
    aw2 = PSD_AW_HOY
    for lim, col, et in (
            (techo(aw2), VERDE, 'hoy (apertura 64 KB)'),
            (techo(aw2, apertura=2 * APERTURA_B), AZUL, '7010, apertura 128 KB'),
            (techo(aw2, tiles_disp=TILES_7020 - TILES_OTROS,
                   apertura=4 * APERTURA_B), NARAN, '7020, apertura 256 KB')):
        ax.axhline(1 << lim, color=col, lw=1.4, ls='--')
        ax.annotate(f'$N_1 = {1 << lim}$ — {et}', (1.1e-4, 1 << lim),
                    color=col, fontsize=8.5, va='bottom')

    # Dos aplicaciones pueden pedir el MISMO N1 --HPGe y la matriz gamma-gamma
    # difieren en el segundo eje, no en este-- y ahi los marcadores se pisan.
    # Se agrupan por posicion y el rotulo lleva los dos numeros.
    juntos = {}
    for n, _, aw1, _, fwhm, _ in APLICACIONES:
        if fwhm is not None:
            juntos.setdefault((fwhm, aw1), []).append(n)
    for (fwhm, aw1), ns in juntos.items():
        et = '·'.join(str(n) for n in ns)
        ax.plot(fwhm, 1 << aw1, marker='s', ms=14 + 5 * (len(ns) - 1),
                color=SUP, mec=TINTA2, mew=1.1, ls='none', zorder=5)
        ax.annotate(et, (fwhm, 1 << aw1), color=TINTA, fontsize=8.5,
                    fontweight='bold', ha='center', va='center', zorder=6)

    # El unico punto medido: el FWHM del propio eje de esta placa.
    ax.plot(FWHM_FS, n1_requerido(FWHM_FS, 4), marker='*', ms=17, color=ROJO,
            mec=SUP, mew=0.8, ls='none', zorder=7,
            label='FWHM medido del eje (8.6 canales)')

    ax.set_xscale('log')
    ax.set_yscale('log', base=2)
    ax.set_xlabel('FWHM del pico mas angosto, como fraccion del fondo de escala')
    ax.set_ylabel('$N_1$ necesario')
    ax.set_ylim(2 ** 4, 2 ** 15)
    ax.legend(loc='upper right', fontsize=8.5)
    limpiar(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(out, '03_requisito_vs_alcance.png'))
    plt.close(fig)

    return dict(n1_hoy=1 << techo(aw2),
                n1_7010=1 << techo(aw2, apertura=2 * APERTURA_B),
                n1_7020=1 << techo(aw2,
                                   tiles_disp=TILES_7020 - TILES_OTROS,
                                   apertura=4 * APERTURA_B),
                n1_medido=float(n1_requerido(FWHM_FS, 4)))


# =============================================================================
# 4. Por que N1 no necesita ser grande si el zoom puede moverlo
# =============================================================================
def fig_bineado(out):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.6, 4.3))

    # --- (a) la curva de Sheppard --------------------------------------------
    nb = np.logspace(np.log10(0.3), np.log10(20), 400)
    ax1.plot(nb, 100 * (ensanche(nb) - 1), color=AZUL, lw=1.8)
    for v, col in ((1, MUDO), (3, ROJO), (4, VERDE),
                   (FWHM_CAN, MORADO)):
        e = 100 * (float(ensanche(v)) - 1)
        ax1.plot(v, e, marker='o', ms=6, color=col, ls='none', zorder=5)
        ax1.annotate(f'{v:g} → +{e:.2g} %', (v, e), xytext=(6, 6),
                     textcoords='offset points', color=col, fontsize=8.5)
    ax1.set_xscale('log')
    ax1.set_yscale('log')
    ax1.set_xlabel('Bins por FWHM')
    ax1.set_ylabel('Ensanchamiento del pico [%]')
    panel(ax1, '(a)')
    limpiar(ax1)

    # --- (b) el eje de 128 bins con zoom -------------------------------------
    zmax = 16 - H2_AW_HOY                     # mca_zoom: z_max = FW - AW
    z = np.arange(0, zmax + 1)
    nb_z = FWHM_FS * (1 << H2_AW_HOY) * (2.0 ** z)
    ax2.plot(z, ensanche(nb_z), color=AZUL, lw=1.8, marker='o', ms=4,
             label=f'$N_1 = {1 << H2_AW_HOY}$ con zoom $z$')
    ax2.axhline(1.0, color=MUDO, lw=0.9, ls=':')

    # Donde el eje 2D empata con el 1D.
    z_par = int(np.argmin(np.abs(nb_z - FWHM_CAN)))
    ax2.plot(z_par, float(ensanche(nb_z[z_par])), marker='o', ms=14, mfc='none',
             mec=VERDE, mew=2.0, ls='none', zorder=6)

    # El limite de `k`: con z >= 9 el enmascarado deja k = 0 y solo se puede
    # entrar a la ventana mas baja. Se marca como banda, no como texto.
    ax2.axvspan(8.5, zmax + 0.4, color=ROJO, alpha=0.10, zorder=0)

    ax2.set_xticks(list(z))
    ax2.set_xlabel('Nivel de zoom $z$ del eje (`cfg_zoom_2dx`)')
    ax2.set_ylabel('Ensanchamiento, factor')
    ax2.set_yscale('log')
    ax2.legend(loc='upper right', fontsize=8.5)
    panel(ax2, '(b)')
    limpiar(ax2)

    fig.tight_layout()
    fig.savefig(os.path.join(out, '04_bineado_y_zoom.png'))
    plt.close(fig)

    return dict(zmax=zmax, z_par=z_par, nb_z0=float(nb_z[0]),
                ens_z0=float(ensanche(nb_z[0])),
                ens_zpar=float(ensanche(nb_z[z_par])),
                ancho_z0=1.0 / float(nb_z[0]))


# =============================================================================
# Validacion del modelo y tablas
# =============================================================================
def validar():
    """El modelo de ocupacion tiene que reproducir el build. Si no, es un bug."""
    t1d = math.ceil((1 << H_AW) / palabras_por_tile(32))
    t2d = tiles(H2_AW_HOY, PSD_AW_HOY, CW_HOY)
    assert t1d == 8, f'histograma 1D: el modelo da {t1d} tiles, el build 8'
    assert t2d == TILES_MAPA_HOY, f'mapa 2D: {t2d} vs {TILES_MAPA_HOY}'
    # El 0.31 % de register_map_mca.md:157 a 8.6 bins/FWHM.
    e = 100 * (float(ensanche(FWHM_CAN)) - 1)
    assert abs(e - 0.31) < 0.02, f'Sheppard a 8.6 bins/FWHM da {e:.3f} %'
    return dict(t1d=t1d, t2d=t2d, sheppard=e)


def tabla():
    v = validar()
    print('validacion del modelo contra el build:')
    print(f'  histograma 1D (2^{H_AW} x 32 b) : {v["t1d"]} tiles  (platform.md: 8)')
    print(f'  mapa 2D       (2^{H2_AW_HOY + PSD_AW_HOY} x 32 b)  : '
          f'{v["t2d"]} tiles  (platform.md: {TILES_MAPA_HOY})')
    print(f'  Sheppard a {FWHM_CAN} bins/FWHM  : {v["sheppard"]:.2f} %'
          '  (register_map_mca.md: 0.31 %)')
    print()
    print(f'tiles libres: 7010 -> {TILES_7010 - TILES_OTROS}, '
          f'7020 -> {TILES_7020 - TILES_OTROS}  '
          f'(el resto del build ocupa {TILES_OTROS})')
    print()
    print('geometrias, con CW = 32:')
    print('   N1 x N2      palabras   tiles   apertura   estado')
    for aw1, aw2 in ((6, 6), (7, 6), (8, 6), (7, 7), (9, 6), (8, 7), (8, 8),
                     (10, 6), (9, 9), (12, 7), (12, 12)):
        pal = 1 << (aw1 + aw2)
        print(f'  {1 << aw1:5d} x {1 << aw2:<5d} {pal:9d}   {tiles(aw1, aw2):5d}'
              f'   {bytes_apertura(aw1, aw2) // 1024:6d} KB   '
              f'{NOMBRE_EST[estado(aw1, aw2)]}')
    print()
    print('N1 maximo con N2 = 64:')
    print(f'  hoy (apertura 64 KB, 7010)      : {1 << techo(PSD_AW_HOY)}')
    print('  7010 con apertura de 128 KB     : '
          f'{1 << techo(PSD_AW_HOY, apertura=2 * APERTURA_B)}')
    print('  7020 con apertura de 256 KB     : '
          f'{1 << techo(PSD_AW_HOY, tiles_disp=TILES_7020 - TILES_OTROS, apertura=4 * APERTURA_B)}')


# =============================================================================
# Epigrafes
# =============================================================================
def epigrafes(out, r1, r2, r3, r4):
    cab = f"""
    Epigrafes de las figuras de `figuras_mapa2d.py` — la geometria N1 x N2 del
    mapa 2D contra el limite de memoria. Los escribe el mismo script que dibuja,
    con los numeros recalculados, para que no puedan desincronizarse.

    Son esquemas de diseño. Los dos unicos numeros medidos son el FWHM del eje
    ({FWHM_CAN} canales sobre 2^{H_AW}, 2a campaña) y el costo en tiles del build
    actual, con el que se valida el modelo de ocupacion de BRAM.
    """

    items = [
        dict(archivo='01_plano_decision.png', nota=f"""
        El plano de decision. Cada cuadrado es una geometria (N1 = 2^H2_AW en
        abscisas, N2 = 2^PSD_AW en ordenadas) y su color dice que hace falta para
        construirla. Las diagonales punteadas son curvas de costo constante: el
        mapa ocupa 2^(H2_AW+PSD_AW) palabras, asi que el costo depende de la SUMA
        de los dos exponentes y no de como se reparta entre los ejes. Esa es la
        propiedad que ordena el plano: moverse por una diagonal es gratis.

        El resultado que importa: con CW = 32 el limite que ata NO es la BRAM,
        es la apertura del bus. La apertura de 64 KB se llena a
        2^{r2['k_ap']} bins, que son {r2['tiles_ap_32']} tiles, cuando en el 7010
        quedan {r2['disp_10']} libres. Hay un factor {r2['disp_10'] / r2['tiles_ap_32']:.1f}
        de BRAM comprada y no usada, y para llegar a ella hay que tocar el decode
        de sys_addr[19:16], no el chip. Con la apertura ensanchada el techo del
        7010 pasa a 2^{r1['tope_7010']} bins totales; el 7020 llega a
        2^{r1['tope_7020']}.

        El circulo rojo es el build de hoy, 128 x 64. Los numeros son las
        aplicaciones de la tabla del README.
        """),

        dict(archivo='02_limite_memoria.png', nota=f"""
        (a) Tiles de BRAM contra bins totales, para tres anchos de contador, con
        los dos techos de chip y la apertura. El modelo de ocupacion son las
        palabras que entran en un RAMB36 segun el ancho nativo (1Kx36, 2Kx18,
        4Kx9) y se valida contra el build: predice 8 tiles para el histograma 1D
        y 8 para el mapa 2D, que es lo que factura platform.md §4.7. El circulo
        rojo es el mapa de hoy.

        (b) Por que CW = 32 es gratis, y es el panel que mas decisiones cierra.
        El escalon azul es la granularidad del tile: cualquier contador de 19 a
        36 bits cuesta EXACTAMENTE lo mismo, porque en los tres casos entran 1024
        palabras por RAMB36 (banda verde). Bajar de 32 a 24 bits no ahorra un
        solo tile. El unico ahorro real es cruzar a <= 18 bits, que duplica los
        bins por tile, y la curva naranja dice lo que cuesta: con el bin caliente
        llevandose el {100 * FRAC_PICO:.0f} % de los eventos a {TASA_EV / 1e3:.0f} kev/s,
        un contador de 16 bits satura en {r2['t_sat_16']:.0f} s y uno de 18 en
        {r2['t_sat_18']:.0f} s, contra {r2['t_sat_32'] / 86400:.0f} dias con los
        32 de hoy. Un contador de 24 bits aguanta {r2['t_sat_24'] / 3600:.1f} h y
        no ahorra nada: es el peor punto de la curva.
        """),

        dict(archivo='03_requisito_vs_alcance.png', nota=f"""
        Lo que pide cada aplicacion contra lo que se alcanza. En abscisas el FWHM
        del pico mas angosto que hay que resolver, como fraccion del fondo de
        escala; en ordenadas el N1 que hace falta para meterle 3, 4 o 5 bins
        adentro. Las tres rectas son N1 = nb / (FWHM/FS), que en log-log son
        paralelas.

        Las lineas horizontales son los techos con N2 = 64 bins de forma, que es
        el reparto de uso real: {r3['n1_hoy']} bins de amplitud hoy,
        {r3['n1_7010']} en este mismo chip si se ensancha la apertura, y
        {r3['n1_7020']} en un 7020. Los cuadrados numerados son las aplicaciones
        de la tabla del README, con el FWHM tipico de cada familia de detector
        --valores de literatura, no medidos.

        La estrella roja es el unico punto medido: el FWHM del eje de esta placa,
        {FWHM_CAN} canales sobre 2^{H_AW}, o sea {FWHM_FS:.2e} del fondo de
        escala. Para ponerlo en el eje X del mapa con 4 bins por FWHM harian
        falta {r3['n1_medido']:.0f} bins. Es el numero que explica por que las
        matrices gamma-gamma historicas son de 4096 x 4096 y por que no viven en
        BRAM: con esa geometria el mapa son 2^24 palabras, tres ordenes de
        magnitud por encima de lo que hay en el chip. Esa familia de
        aplicaciones pide modo lista en DDR y histogramado offline, no un mapa
        mas grande.
        """),

        dict(archivo='04_bineado_y_zoom.png', nota=f"""
        (a) La perdida por bineado (Sheppard): un bin rectangular de ancho w suma
        una varianza w^2/12, asi que el pico aparece ensanchado en
        sqrt(1 + 0.68^2 (w/FWHM)^2). A 1 bin por FWHM son +21 %, a 3 son +2.5 %
        --el piso practico-- y a los {FWHM_CAN} bins por FWHM del eje 1D de esta
        placa son +{100 * (float(ensanche(FWHM_CAN)) - 1):.2f} %. La regla
        que sale de la curva: 3 bins por FWHM de piso, 4 a 5 de objetivo, y por
        encima de 8 la curva ya es plana y los bins de mas no compran nada.

        (b) Por que N1 no necesita ser grande si el zoom puede moverlo, y es el
        panel que contesta la pregunta de diseño. Con los {1 << H2_AW_HOY} bins de
        hoy y sin zoom, el bin del eje X mide {r4['ancho_z0']:.1f} veces el FWHM
        medido y el pico aparece ensanchado {r4['ens_z0']:.1f}x. Pero mca_zoom
        entra con los 16 bits de la feature y no con los {H2_AW_HOY} del eje, asi
        que z llega a {r4['zmax']}: con z = {r4['z_par']} los mismos
        {1 << H2_AW_HOY} bins cubren 1/{1 << r4['z_par']} del fondo de escala y el
        bin vuelve a valer lo que el del espectro 1D, con un ensanchamiento de
        {100 * (r4['ens_zpar'] - 1):.2f} %. Las ventanas estan anidadas en
        potencias de 2 por diseño, asi que dos tomas con zoom distinto se suman
        con aritmetica entera sin re-samplear.

        La banda roja es el limite de k: en mca_zoom el enmascarado es
        8'hFF >> (4'd8 - z), que para z >= 9 envuelve en 4 bits y deja k = 0. Con
        esos niveles solo se puede entrar a la ventana mas baja del rango. Para
        F_INVW, que vive cerca de cero, es justo lo que hace falta; para F_PSD,
        cuyo cociente cae en 0.3-0.6 del fondo, manda todo al bin 0.
        """),
    ]

    pie = f"""
    Las aplicaciones numeradas, en el mismo orden en las figuras 1 y 3:
    """ + "\n" + "\n".join(
        f'      {n}. {et}  ->  {1 << a1} x {1 << a2}'
        for n, et, a1, a2, _, _ in APLICACIONES)

    path = os.path.join(out, 'epigrafes.txt')
    escribir_epigrafes(path, cab, items, pie)
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI, help='donde dejar los PNG')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    validar()
    r1 = fig_plano(a.out)
    r2 = fig_limite(a.out)
    r3 = fig_requisito(a.out)
    r4 = fig_bineado(a.out)
    p = epigrafes(a.out, r1, r2, r3, r4)

    print(f'figuras en {os.path.relpath(a.out)}:')
    for f in ('01_plano_decision.png', '02_limite_memoria.png',
              '03_requisito_vs_alcance.png', '04_bineado_y_zoom.png'):
        print(f'  {f}')
    print(f'  {os.path.basename(p)}')
    print()
    tabla()


if __name__ == '__main__':
    main()
