#!/usr/bin/env python3
"""Figuras que explican los problemas de determinación de resolución del MCA.

Las figuras van **sin texto adentro**: sólo ejes, leyenda y las marcas
imprescindibles. Todo lo que hay que decir de cada una está junto en
[`epigrafes.txt`](epigrafes.txt), que este mismo script escribe con los números
recalculados, para que epígrafe y gráfico no se desincronicen.

Las que se pueden hacer con datos MEDIDOS usan los `.npz` de la 2ª campaña
(`software/datos/mca_20260528_001034/`); las que no —la DNL, que este generador
no permite medir (§14 de `decisiones_diseno_mca.md`)— son esquemas sintéticos.

    python3 figuras_resolucion.py [--datos DIR] [--out DIR]
"""

import argparse
import os
import re
import sys
import textwrap

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, '..', '..', '..', 'software'))
import mca_utils as mu                                          # noqa: E402

DATOS_DEF = os.path.join(_AQUI, '..', '..', '..', 'software', 'datos',
                         'mca_20260528_001034')

# --- paleta (validada con scripts/validate_palette.js, modo claro) -----------
SUP    = '#fcfcfb'   # superficie
TINTA  = '#0b0b0b'   # tinta primaria
TINTA2 = '#52514e'   # tinta secundaria
MUDO   = '#898781'   # ejes y etiquetas
GRILLA = '#e1e0d9'
AZUL   = '#2a78d6'   # serie 1: lo medido
NARAN  = '#eb6834'   # serie 2: lo real/deformado en los esquemas
ROJO   = '#d03b3b'   # crítico: el desvío que se está señalando
RAMPA  = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281']  # ordinal

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})

FWHM_K = 2.0 * np.sqrt(2.0 * np.log(2.0))          # sigma -> FWHM


def _limpiar(ax):
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def _panel(ax, letra):
    ax.set_title(letra, loc='left', fontweight='bold', color=TINTA2, pad=6)


def _gauss(x, c, s):
    return np.exp(-0.5 * ((x - c) / s) ** 2)


def _cdf(x, c, s):
    from math import erf, sqrt
    return np.array([0.5 * (1 + erf((xi - c) / (s * sqrt(2)))) for xi in x])


# =============================================================================
# 1. El mismo pulso, muchas veces: FWHM e INL sobre el pico medido
# =============================================================================
def fig_pico_unico(d, out):
    spec = np.load(os.path.join(d, 'single_peak.npz'))['spec'].astype(float)
    sw = np.load(os.path.join(d, 'sweep_amplitude.npz'))
    a, b = np.polyfit(sw['amps'], sw['centroids'], 1)

    n = int(spec.sum())
    pk = int(np.argmax(spec))
    fit = mu.gauss_fit_peak(spec, pk - 40, pk + 40)
    c, s, fwhm = fit['centroid'], fit['sigma'], fit['fwhm']
    ideal = a * 0.5 + b                     # 0.5 Vpp fue la consigna
    inl = c - ideal

    nz = np.nonzero(spec)[0]
    lo, hi = nz.min() - 10, nz.max() + 10
    x = np.arange(lo, hi)

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    ax.bar(x, spec[lo:hi], width=0.9, color=AZUL, linewidth=0,
           label='espectro medido')
    xf = np.linspace(lo, hi, 600)
    ax.plot(xf, fit['area'] / (s * np.sqrt(2 * np.pi)) * _gauss(xf, c, s),
            color=TINTA, lw=1.3, ls='--', label='ajuste gaussiano')
    ax.axvline(ideal, color=TINTA2, lw=1.2, ls=':', label='canal ideal')

    ymax = spec[lo:hi].max()
    hm = 0.5 * ymax
    ax.add_patch(FancyArrowPatch((c - fwhm / 2, hm), (c + fwhm / 2, hm),
                                 arrowstyle='<|-|>', mutation_scale=9, lw=1.4,
                                 color=ROJO, shrinkA=0, shrinkB=0, zorder=6))
    ax.annotate('FWHM', (c - fwhm / 2, hm), xytext=(-8, 0),
                textcoords='offset points', ha='right', va='center',
                color=ROJO, fontweight='bold', zorder=7)
    ax.add_patch(FancyArrowPatch((c, 0.92 * ymax), (ideal, 0.92 * ymax),
                                 arrowstyle='<|-|>', mutation_scale=9, lw=1.4,
                                 color=TINTA, shrinkA=0, shrinkB=0, zorder=6))
    ax.annotate('INL', ((c + ideal) / 2, 0.93 * ymax), ha='center', va='bottom',
                color=TINTA, fontweight='bold', zorder=7)

    ax.set_xlabel('Canal del espectro')
    ax.set_ylabel('Cuentas')
    ax.legend(loc='upper left')
    _limpiar(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(out, '01_pico_unico.png'))
    plt.close(fig)
    return dict(centroide=c, sigma=s, fwhm=fwhm, ideal=ideal, inl=inl, n=n,
                a=a, b=b, res=100 * fwhm / c, err=s / np.sqrt(n),
                nbins=int((spec > 0).sum()))


# =============================================================================
# 2. Linealidad: lo que mide el MCA contra lo que pide el generador
# =============================================================================
def fig_linealidad(d, out, seconds=4.0, rate_hz=2e3):
    sw = np.load(os.path.join(d, 'sweep_amplitude.npz'))
    amps, cent, fw = sw['amps'], sw['centroids'], sw['fwhms']
    res_i, res_v = sw['resid'], sw['resid_vuelta']
    a, b, resid, inl_pct = mu.energy_calibration(cent, amps)
    n_pto = int(seconds * rate_hz)

    # todo en volts: el canal se lleva a Vpp con la propia calibración
    v_mca = (cent - b) / a
    err_v = (fw / 2) / a
    r_ida, r_vuelta = res_i / a * 1e3, res_v / a * 1e3      # residuo en mV

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7.6, 6.2), sharex=True,
        gridspec_kw=dict(height_ratios=[1.25, 1], hspace=0.10))

    ax1.errorbar(amps, v_mca, yerr=err_v, fmt='o', ms=5, color=AZUL,
                 ecolor=AZUL, elinewidth=1.4, capsize=3, label='medido ± FWHM/2')
    xr = np.linspace(amps.min(), amps.max(), 50)
    ax1.plot(xr, xr, color=TINTA, lw=1.2, ls='--', label='ajuste lineal')
    ax1.set_ylabel('Amplitud determinada por MCA (Vpp) [V]')
    ax1.legend(loc='upper left')
    _limpiar(ax1)

    ax2.axhline(0, color=MUDO, lw=0.8)
    ax2.errorbar(amps, r_ida, yerr=err_v * 1e3, fmt='o', ms=5, color=AZUL,
                 ecolor=AZUL, elinewidth=1.4, capsize=3, label='ida')
    ax2.plot(amps, r_vuelta, 'x', ms=7, mew=1.5, color=ROJO, label='vuelta')
    ax2.set_xlabel('Amplitud pulso en Rigol (Vpp) [V]')
    ax2.set_ylabel('Residuo [mV]')
    ax2.legend(loc='lower left')
    _limpiar(ax2)

    fig.tight_layout()
    fig.savefig(os.path.join(out, '02_linealidad_inl.png'))
    plt.close(fig)
    i_max = int(np.argmax(np.abs(resid)))
    return dict(a=a, b=b, inl_pct=inl_pct, fs=cent.max() - cent.min(),
                corr=float(np.corrcoef(res_i, res_v)[0, 1]), n_pto=n_pto,
                resid_max=resid[i_max], resid_max_mv=resid[i_max] / a * 1e3,
                fwhm_med=float(fw.mean()), en_fwhm=abs(resid[i_max]) / fw[i_max],
                err_mv=float((fw.mean() / FWHM_K / np.sqrt(n_pto)) / a * 1e3))


# =============================================================================
# 3. DNL — esquema
# =============================================================================
def fig_dnl(out, n_ch=14, seed=7, exageracion=0.30):
    rng = np.random.default_rng(seed)
    w = 1.0 + exageracion * rng.uniform(-1, 1, n_ch)
    w *= n_ch / w.sum()                       # mismo rango total: INL = 0
    bordes = np.concatenate(([0.0], np.cumsum(w)))
    centros = 0.5 * (bordes[1:] + bordes[:-1])
    dnl = (w - w.mean()) / w.mean()
    i_max, i_min = int(np.argmax(dnl)), int(np.argmin(dnl))

    fig, (ax0, ax1, ax2) = plt.subplots(
        3, 1, figsize=(7.6, 7.0),
        gridspec_kw=dict(height_ratios=[0.5, 1, 1], hspace=0.45))

    # (a) la regla
    for y, bd, col, nom in ((1.0, np.arange(n_ch + 1.0), AZUL, 'ideal'),
                            (0.0, bordes, NARAN, 'real')):
        ax0.hlines(y, 0, n_ch, color=col, lw=1.6)
        ax0.vlines(bd, y - 0.25, y + 0.25, color=col, lw=1.4)
        ax0.text(-0.3, y, nom, ha='right', va='center', color=col,
                 fontweight='bold')
        for i in (i_max, i_min):
            ax0.fill_between([bd[i], bd[i + 1]], y - 0.23, y + 0.23,
                             color=ROJO, alpha=0.22, lw=0)
    for i in (i_max, i_min):
        ax0.annotate('', (bordes[i], -0.5), (bordes[i + 1], -0.5),
                     arrowprops=dict(arrowstyle='<|-|>', color=ROJO, lw=1.2,
                                     mutation_scale=8))
        ax0.text(centros[i], -0.75, f'{100 * dnl[i]:+.0f} %', ha='center',
                 va='top', color=ROJO, fontsize=9, fontweight='bold')
    ax0.set_xlim(-1.3, n_ch + 0.3)
    ax0.set_ylim(-1.3, 1.4)
    ax0.set_xticks([])
    ax0.set_yticks([])
    ax0.grid(False)
    for lado in ax0.spines:
        ax0.spines[lado].set_visible(False)
    _panel(ax0, '(a)')

    # (b) sliding pulser
    cuentas = 1000 * w
    ax1.bar(np.arange(n_ch) + 0.5, cuentas, width=0.86, color=NARAN, lw=0,
            label='medido')
    ax1.axhline(1000, color=AZUL, lw=1.6, ls='--', label='ideal')
    ax1.set_xlim(0, n_ch)
    ax1.set_ylim(0, 1000 * w.max() * 1.2)
    ax1.set_xlabel('Canal')
    ax1.set_ylabel('Cuentas')
    ax1.legend(loc='upper right', ncol=2)
    _panel(ax1, '(b)')
    _limpiar(ax1)

    # (c) el pico deformado
    idx = np.arange(n_ch) + 0.5
    area = 20000.0
    ideal_cnt = area * np.diff(_cdf(np.arange(n_ch + 1.0), n_ch / 2, 1.7))
    real_cnt = area * np.diff(_cdf(bordes, n_ch / 2, 1.7))
    ax2.step(idx, ideal_cnt, where='mid', color=AZUL, lw=1.8,
             label='canales parejos')
    ax2.step(idx, real_cnt, where='mid', color=NARAN, lw=1.8,
             label='regla despareja')
    ax2.fill_between(idx, real_cnt, ideal_cnt, step='mid', color=NARAN,
                     alpha=0.18, lw=0)
    ax2.set_xlim(0, n_ch)
    ax2.set_xlabel('Canal')
    ax2.set_ylabel('Cuentas')
    ax2.legend(loc='upper right')
    _panel(ax2, '(c)')
    _limpiar(ax2)

    m = ideal_cnt > 0.20 * ideal_cnt.max()
    fig.tight_layout()
    fig.savefig(os.path.join(out, '03_dnl_esquema.png'))
    plt.close(fig)
    return dict(dnl_max=100 * dnl[i_max], dnl_min=100 * dnl[i_min],
                peor=100 * np.max(np.abs(real_cnt[m] / ideal_cnt[m] - 1)),
                dcent=abs((real_cnt * idx).sum() / real_cnt.sum()
                          - (ideal_cnt * idx).sum() / ideal_cnt.sum()))


# =============================================================================
# 4. Las tres métricas, una al lado de la otra
# =============================================================================
def fig_tres_metricas(out, seed=3):
    rng = np.random.default_rng(seed)
    n_ch, c, s, area = 40, 20.0, 2.2, 20000.0
    bordes_id = np.arange(n_ch + 1, dtype=float)
    centros_id = 0.5 * (bordes_id[1:] + bordes_id[:-1])
    ref = area * np.diff(_cdf(bordes_id, c, s))

    w = 1.0 + 0.35 * rng.uniform(-1, 1, n_ch)
    w *= n_ch / w.sum()
    bd = np.concatenate(([0.0], np.cumsum(w)))

    casos = [('INL',  area * np.diff(_cdf(bordes_id, c + 6.0, s))),
             ('DNL',  area * np.diff(_cdf(bd, c, s))),
             ('FWHM', area * np.diff(_cdf(bordes_id, c, s * 2.6)))]

    fig, axs = plt.subplots(1, 3, figsize=(9.6, 3.4), sharey=True)
    for ax, (nombre, y) in zip(axs, casos):
        ax.step(centros_id, ref, where='mid', color=TINTA2, lw=1.2, ls='--',
                label='ideal')
        ax.step(centros_id, y, where='mid', color=NARAN, lw=1.8, label='medido')
        ax.fill_between(centros_id, y, step='mid', color=NARAN, alpha=0.16, lw=0)
        ax.set_title(nombre, loc='left', fontweight='bold', pad=6)
        ax.set_xlabel('Canal')
        ax.set_xlim(6, 36)
        ax.set_ylim(0, 1.25 * ref.max())
        _limpiar(ax)
    axs[0].set_ylabel('Cuentas')
    axs[0].legend(loc='upper right')
    fig.tight_layout()
    fig.savefig(os.path.join(out, '04_tres_metricas.png'))
    plt.close(fig)


# =============================================================================
# 5. El bineado
# =============================================================================
def fig_bineado(d, out, h_max=5):
    spec = np.load(os.path.join(d, 'single_peak.npz'))['spec'].astype(float)
    sw = np.load(os.path.join(d, 'sweep_amplitude.npz'))
    a, _ = np.polyfit(sw['amps'], sw['centroids'], 1)
    n = int(spec.sum())

    filas = []
    for hs in range(h_max + 1):
        k = 1 << hs
        reb = spec[:len(spec) // k * k].reshape(-1, k).sum(1)
        pk = int(np.argmax(reb))
        w = max(6, int(48 / k))
        f = mu.gauss_fit_peak(reb, max(0, pk - w), pk + w)
        filas.append(dict(hs=hs, k=k, reb=reb, cent=f['centroid'] * k,
                          sigma=f['sigma'] * k, fwhm=f['fwhm'] * k,
                          res=f['resolution_pct'],
                          nbins=int(f['bins_poblados'])))
    f0 = filas[0]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.8, 4.2))

    nz = np.nonzero(spec)[0]
    lo, hi = nz.min() - 26, nz.max() + 26
    for fila, col in zip(filas[:5], RAMPA):
        k = fila['k']
        idx = np.arange(len(fila['reb'])) * k + k / 2.0
        m = (idx >= lo) & (idx <= hi)
        ax1.step(idx[m], fila['reb'][m] / k, where='mid', color=col, lw=1.7,
                 label=f"h_shift = {fila['hs']}")
    ax1.set_xlim(lo, hi)
    ax1.set_xlabel('Canal equivalente con h_shift = 0')
    ax1.set_ylabel('Cuentas por canal')
    ax1.legend(loc='upper right')
    _panel(ax1, '(a)')
    _limpiar(ax1)

    hs = np.array([f['hs'] for f in filas], dtype=float)
    res = np.array([f['res'] for f in filas])
    k = 2.0 ** hs
    piso = 100 * FWHM_K * (k / np.sqrt(12)) / f0['cent']

    ax2.plot(hs, res, 'o-', ms=5, lw=1.6, color=AZUL, label='medida')
    ax2.axhline(f0['res'], color=TINTA2, lw=1.2, ls='--', label='verdadera')
    ax2.plot(hs, piso, 's--', ms=4, lw=1.3, color=ROJO,
             label='piso del bin')
    ax2.set_xlabel('h_shift')
    ax2.set_ylabel('Resolución [% del centroide]')
    ax2.set_xticks(hs)
    ax2.set_xlim(-0.3, h_max + 0.3)
    ax2.legend(loc='upper left')
    _panel(ax2, '(b)')
    _limpiar(ax2)

    fig.tight_layout()
    fig.savefig(os.path.join(out, '05_bineado.png'))
    plt.close(fig)
    return dict(filas=filas, n=n, a=a,
                uv=1e6 / mu.ADC_CNT_PER_V, mv=1e3 / a)


# =============================================================================
# 6. Dónde termina el MCA y empieza el generador
# =============================================================================
def fig_limites_estimulo(d, out):
    sr = np.load(os.path.join(d, 'sweep_rate.npz'))
    r_in, r_out, cent, wid = sr['r_in'], sr['r_out'], sr['centroids'], sr['widths']
    ok = np.isfinite(cent) & (r_out > 0)
    const = ok & np.isclose(wid, 2e-6)
    varia = ok & ~np.isclose(wid, 2e-6)
    r_max = r_in[ok].max()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.8, 4.2))

    lim = np.array([r_in[ok].min() * 0.7, r_in[ok].max() * 2.2])
    ax1.plot(lim, lim, ls='--', lw=1.2, color=TINTA2, label='ideal')
    ax1.plot(r_in[ok], r_out[ok], 'o', ms=5.5, color=AZUL, label='medido')
    ax1.axvline(r_max, color=ROJO, lw=1.3, label='techo del generador')
    ax1.axvspan(r_max, lim[1], color=ROJO, alpha=0.08, lw=0)
    ax1.set_xscale('log')
    ax1.set_yscale('log')
    ax1.set_xlim(*lim)
    ax1.set_xlabel('Tasa incidente [cps]')
    ax1.set_ylabel('Tasa registrada [cps]')
    ax1.legend(loc='upper left')
    _panel(ax1, '(a)')
    _limpiar(ax1)

    base = cent[const][0]
    ax2.plot(r_in[const], 100 * (cent[const] / base - 1), 'o-', ms=5.5, lw=1.5,
             color=AZUL, label='estímulo constante')
    ax2.plot(r_in[varia], 100 * (cent[varia] / base - 1), 'x', ms=8, mew=1.6,
             color=ROJO, label='ancho de pulso cambiado')
    ax2.set_xscale('log')
    ax2.set_xlabel('Tasa incidente [cps]')
    ax2.set_ylabel('Corrimiento del centroide [%]')
    ax2.legend(loc='upper left')
    _panel(ax2, '(b)')
    _limpiar(ax2)

    fig.tight_layout()
    fig.savefig(os.path.join(out, '06_limites_estimulo.png'))
    plt.close(fig)
    return dict(r_max=r_max,
                d_const=100 * (cent[const].max() / cent[const].min() - 1),
                d_todo=100 * (cent[ok].max() / cent[ok].min() - 1),
                n_const=int(const.sum()), n_tasas=int(ok.sum()),
                w_min=wid[varia].min() * 1e6)


# =============================================================================
def _mil(n):
    return f'{int(n):,}'.replace(',', ' ')


_ITEM = re.compile(r'^(\s*)(·|\([a-z]\))\s+')


def _reflow(txt, ancho=79):
    """Re-arma los renglones: las sustituciones dejan cortes arbitrarios."""
    fuera = []
    for bruto in txt.split('\n\n'):
        lineas = [l for l in bruto.split('\n') if l.strip()]
        if not lineas:
            continue
        cabecera = []
        if len(lineas) > 1 and lineas[1].strip() and set(lineas[1].strip()) <= set('-='):
            cabecera, lineas = lineas[:2], lineas[2:]
        cuerpo = ''
        if all(l.startswith('      ') for l in lineas) and lineas:
            cuerpo = '\n'.join(lineas)                            # tabla
        elif any(_ITEM.match(l) for l in lineas):                  # lista
            partes, actual = [], None
            for l in lineas:
                if _ITEM.match(l):
                    if actual:
                        partes.append(actual)
                    actual = l.rstrip()
                elif actual is not None:
                    actual += ' ' + l.strip()
                else:
                    partes.append(l.strip())
            if actual:
                partes.append(actual)
            cuerpo = '\n'.join(
                textwrap.fill(x, ancho,
                              subsequent_indent=' ' * len(_ITEM.match(x).group(0)))
                if _ITEM.match(x) else textwrap.fill(x, ancho) for x in partes)
        elif lineas:
            cuerpo = textwrap.fill(' '.join(l.strip() for l in lineas), ancho)
        bloque = '\n'.join(cabecera + ([cuerpo] if cuerpo else []))
        fuera.append(('\n' + bloque) if cabecera and fuera else bloque)
    return '\n\n'.join(fuera) + '\n'


def escribir_epigrafes(out, r1, r2, r3, r5, r6):
    f = {x['hs']: x for x in r5['filas']}
    tabla = '\n'.join(
        f"      h_shift = {h}   bin = {f[h]['k']:2d} canales   "
        f"{f[h]['nbins']:2d} canales en el pico   "
        f"resolución {f[h]['res']:.3f} %" for h in sorted(f))

    txt = f"""EPÍGRAFES DE LAS FIGURAS
========================

Los gráficos van sin texto adentro; todo lo que hay que decir está acá. Este
archivo lo escribe `figuras_resolucion.py` con los números recalculados de los
datos, así que no puede desincronizarse de las figuras.

Datos medidos: 2ª campaña, software/datos/mca_20260528_001034/

Montaje: Red Pitaya STEMlab 125-14, Rigol DG4162 por USB en IN1, forma arbitraria
de detector de 2 us de FWHM. Calibración medida: {r1['a']:.1f} canales/Vpp y
{r1['b']:.1f} canales de offset.


FIGURA 1 — 01_pico_unico.png
----------------------------
Espectro de un pulser de amplitud FIJA (0.5 Vpp, 2 us de FWHM a 2 kHz, 10 s de
adquisición): {_mil(r1['n'])} pulsos idénticos. Idealmente todos caerían en UN canal;
lo que se obtiene son {r1['nbins']} canales poblados, con el centroide en
{r1['centroide']:.2f} en vez del canal {r1['ideal']:.1f} que predice la recta de
calibración.

  · FWHM = {r1['fwhm']:.2f} canales = {r1['fwhm'] / r1['a'] * 1e3:.2f} mV, o sea
    una resolución del {r1['res']:.3f} %. Como el estímulo no tiene dispersión
    propia, ese ancho es enteramente instrumental: ruido de la cadena,
    digitización y jitter del estimador de amplitud. Es el piso del sistema y la
    única de las tres métricas que NO se compensa por software.
  · INL local = {r1['inl']:.1f} canales = {r1['inl'] / r1['a'] * 1e3:.1f} mV, o
    sea {abs(r1['inl']) / r1['fwhm']:.1f} veces el ancho del propio pico. La INL
    no ensancha: mueve.

La incerteza estadística del centroide es sigma/sqrt(N) = {r1['err']:.3f} canales,
{abs(r1['inl']) / r1['err']:.0f} veces más chica que el desvío: lo que se ve no es
ruido de la medición.


FIGURA 2 — 02_linealidad_inl.png
--------------------------------
Amplitud determinada por el MCA contra la amplitud de consigna del generador,
20 amplitudes entre 0.1 y 1.0 Vpp con ~{_mil(r2['n_pto'])} pulsos por punto (4 s a
2 kHz), medidas dos veces: subiendo y bajando. El canal se llevó a volts con la
propia calibración, así que el ajuste lineal es la identidad.

Arriba: las barras de error son ±FWHM/2 ≈ ±{r2['fwhm_med'] / 2 / r2['a'] * 1e3:.2f} mV
y no llegan a verse — a la escala de la calibración el pico es más angosto que el
marcador.

Abajo: el residuo del ajuste, que es donde vive la INL. Llega a
{r2['resid_max']:+.1f} canales = {r2['resid_max_mv']:+.1f} mV, o sea
{r2['en_fwhm']:.1f} veces el ancho del pico, contra una incerteza estadística del
centroide de ±{r2['err_mv']:.3f} mV. La INL vale {r2['inl_pct']:.2f} % del rango
barrido ({r2['fs']:.0f} canales).

Las dos pasadas coinciden con correlación {r2['corr']:.5f}: el desvío es
SISTEMÁTICO, y por lo tanto compensable con un ajuste polinómico o una tabla de
correcciones.

LÍMITE DEL SISTEMA DE EXCITACIÓN: esa INL es la del MCA MÁS la exactitud de
amplitud del DG4162. Que las dos pasadas coincidan prueba que el desvío se
repite, no de quién es; separarlos pide un patrón de tensión trazable. Aplicar la
corrección a ciegas inyectaría el error del generador al medir un detector real.


FIGURA 3 — 03_dnl_esquema.png   (ESQUEMA, datos sintéticos)
-----------------------------------------------------------
La DNL es la variación del ANCHO de cada canal respecto del promedio. Está
exagerada a ±30 % para que se vea; la spec típica es <±1 %.

  (a) Las dos reglas empiezan y terminan en el mismo lugar —la INL es cero— pero
      las marcas están desparejas: un canal mide {r3['dnl_max']:+.0f} % y otro
      {r3['dnl_min']:+.0f} % respecto del promedio.
  (b) Cómo se mide: con amplitud uniformemente distribuida (sliding pulser) todos
      los canales deberían recibir la misma cuenta, así que lo que reciben es
      proporcional a su ancho y la desviación relativa ES la DNL.
  (c) Qué le hace a un pico: el mismo pico gaussiano, con la energía perfectamente
      calibrada, sale con hasta {r3['peor']:.0f} % de diferencia en un canal del
      cuerpo del pico y el centroide corrido {r3['dcent']:.2f} canales. Es
      estructura que no está en la señal; cuando la DNL es periódica (típico de
      los ADC, en los límites de bit) aparece como un rizado regular, y en el peor
      caso como picos falsos.

Dos advertencias: la DNL del binado DIGITAL es cero por construcción —el bin es
un desplazamiento a la derecha, todos los canales miden lo mismo—, así que la que
se mide es la del ADC y la del estimador de amplitud. Y todavía no está medida:
pide amplitud continua, y este firmware del DG4162 no tiene modulación por SCPI.


FIGURA 4 — 04_tres_metricas.png   (ESQUEMA, datos sintéticos)
-------------------------------------------------------------
El mismo pico verdadero (línea de trazos) visto con cada defecto por separado.
Las tres métricas son independientes y arruinan cosas distintas:

  · INL  — la regla está mal graduada: el pico está donde no va, y se identifica
           mal el isótopo. La forma queda intacta.
  · DNL  — las marcas están desparejas: el pico se deforma, con área y centroide
           sesgados, aunque la energía esté bien calibrada.
  · FWHM — la regla está borrosa: el pico se ensancha y dos líneas cercanas dejan
           de separarse.

Un espectro con INL alta se ve perfectamente limpio y aun así miente la energía.


FIGURA 5 — 05_bineado.png
-------------------------
El pico medido de la figura 1 ({_mil(r5['n'])} pulsos) rebinado por software
exactamente como lo haría el hardware: suma de 2^h_shift canales contiguos.

  (a) El mismo pico con h_shift de 0 a 4.
  (b) La resolución que se mide en cada caso, contra el piso de cuantización del
      bin (ancho/raíz de 12):

{tabla}

Con 4 o más canales por FWHM la medición sobrevive; por debajo de 3, el ancho que
se mide es el del bin y no el del sistema.

h_shift sólo puede EMPEORAR: con la muestra de pico y h_shift = 0 un canal ya es
exactamente una cuenta del ADC ({r5['uv']:.0f} uV a la entrada, {r5['mv']:.3f} mV
de consigna del generador), así que no hay nada que ver entre canales y hacer zoom
sobre el gráfico no agrega información. Más canales por volt sólo se consiguen con
ganancia real: amp_src = 1 (integral de carga) y q_shift más chico.


FIGURA 6 — 06_limites_estimulo.png
----------------------------------
Barrido de tasa, {r6['n_tasas']} puntos de 2 s cada uno. Separa lo que limita el
MCA de lo que limita el generador.

  (a) Throughput: la tasa registrada sigue a la incidente sin perder un evento
      hasta {r6['r_max'] / 1e3:.0f} kcps. La curva no se dobla: lo que se terminó
      fue el rango del DG4162, así que a la derecha de la línea roja no hay "no
      medido" sino "no medible con este estímulo". El techo del MCA no se conoce.
  (b) Corrimiento del centroide con la tasa. `set_pulse_periodic` exige un ancho
      menor a T/2, así que por encima de 72 kcps el generador ACORTA el pulso
      (hasta {r6['w_min']:.2f} us): esos puntos, en rojo, no son comparables con el
      resto. El barrido entero da +{r6['d_todo']:.2f} %, pero está confundido con
      el ancho; con estímulo constante —los {r6['n_const']} puntos azules, en un
      rango de tasa de x36— el corrimiento real es +{r6['d_const']:.2f} %, y ése es
      el número que hay que citar.


FIGURA 7 — 07_cadena_mca.mp4   (animación, datos sintéticos)
------------------------------------------------------------
Cómo un pulso se convierte en una cuenta del espectro, en las tres etapas a la
vez: la señal con pulsos de distinta altura y el umbral dibujado; el bloque
pulse_feature, que por cada pulso emite UN número —su amplitud— que viaja hasta
el módulo histograma; y el espectro, donde la barra del canal amp >> h_shift sube
una cuenta y parpadea. Los pulsos que no cruzan el umbral no producen nada.

Arranca en tiempo real del gráfico para que se vea el mecanismo pulso a pulso y
después acelera hasta x8 para acumular 232 cuentas y dibujar dos picos. Los
pulsos, el ruido de línea de base y las dos líneas de energía son sintéticos: es
una ilustración del camino de datos, no una medición.
"""
    destino = os.path.join(out, 'epigrafes.txt')
    with open(destino, 'w') as fh:
        fh.write(_reflow(txt))
    return destino


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--datos', default=DATOS_DEF)
    ap.add_argument('--out', default=_AQUI)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    r1 = fig_pico_unico(args.datos, args.out)
    r2 = fig_linealidad(args.datos, args.out)
    r3 = fig_dnl(args.out)
    fig_tres_metricas(args.out)
    r5 = fig_bineado(args.datos, args.out)
    r6 = fig_limites_estimulo(args.datos, args.out)
    ep = escribir_epigrafes(args.out, r1, r2, r3, r5, r6)

    print(f"01  centroide {r1['centroide']:.2f}  ideal {r1['ideal']:.2f}  "
          f"INL {r1['inl']:+.2f}  FWHM {r1['fwhm']:.2f}  N={r1['n']}")
    print(f"02  {r2['a']:.1f} canales/Vpp  offset {r2['b']:.1f}  "
          f"INL {r2['inl_pct']:.2f} % FS  correlación {r2['corr']:.5f}")
    print('05  ' + '  '.join(f"h{x['hs']}:{x['res']:.3f}%({x['nbins']}b)"
                             for x in r5['filas']))
    print(f"06  techo {r6['r_max'] / 1e3:.0f} kcps  {r6['d_const']:.2f} % vs "
          f"{r6['d_todo']:.2f} %")
    print(f'figuras y {os.path.basename(ep)} en {os.path.abspath(args.out)}')


if __name__ == '__main__':
    main()
