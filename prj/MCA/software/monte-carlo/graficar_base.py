#!/usr/bin/env python3
"""Figuras del estudio del seguidor de línea de base, desde el resumen.json.

    python3 monte-carlo/graficar_base.py [directorio]     # por defecto, la corrida más reciente
"""
import glob
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                              # noqa: E402

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
import pileup as pu                                          # noqa: E402
import linea_base as lb                                      # noqa: E402

SUP    = '#fcfcfb'
TINTA  = '#0b0b0b'
TINTA2 = '#52514e'
MUDO   = '#898781'
GRILLA = '#e1e0d9'
AZUL   = '#2a78d6'   # seguidor
NARAN  = '#eb6834'   # base fija
ROJO   = '#d03b3b'   # lo medido en placa
VERDE  = '#2e8b57'

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})


def _limpiar(ax):
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def _guardar(fig, out, nombre):
    fig.savefig(os.path.join(out, nombre), dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'  {nombre}')


def _serie(res, bl_auto, campo):
    f = [r for r in res['tasa'] if r['bl_auto'] == bl_auto]
    return (np.array([r['tasa'] for r in f]),
            np.array([r[campo] for r in f], dtype=float))


# =============================================================================
def fig_deriva(res, out):
    """La figura que dirime la hipótesis: corrimiento de centroide contra tasa."""
    # Dos paneles: el rango completo aplasta la ventana de la campaña, que es
    # justo donde se dirime la hipótesis (todo pasa entre 0 y +1.3 %), y a la
    # inversa el zoom esconde el derrumbe del seguidor a 300 kcps, que es un
    # modo de falla real. Se muestran los dos.
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.8))
    series = ((False, NARAN, 'base fija (cfg_bl_auto = 0)'),
              (True, AZUL, f'seguidor IIR (bl_k = {res["bl_k"]})'))

    for ax in (a1, a2):
        for auto, col, et in series:
            t, c = _serie(res, auto, 'centroide')
            ax.plot(t / 1e3, 100 * (c - c[0]) / c[0], 'o-', color=col, ms=4,
                    lw=1.5, label=et)
        ax.axhline(res['deriva_medida_pct'], color=ROJO, lw=1.3, ls='--')
        ax.axhline(0, color=MUDO, lw=0.8)
        ax.axvspan(res['tasa_baja'] / 1e3, res['tasa_alta'] / 1e3,
                   color=MUDO, alpha=.10, lw=0)
        ax.set_xscale('log')
        ax.set_xlabel('tasa incidente [kcps]')
        ax.set_ylabel('corrimiento de centroide [%]')
        _limpiar(ax)

    a1.set_title('rango completo', loc='left', color=TINTA2)
    a1.legend(loc='lower left', fontsize=8.5)
    a1.text(0.98, res['deriva_medida_pct'], ' placa: +1.28 % ',
            transform=a1.get_yaxis_transform(), ha='right', va='bottom',
            color=ROJO, fontsize=8)

    # zoom a la ventana de la campaña
    a2.set_xlim(res['tasa_baja'] / 1e3 * 0.8, res['tasa_alta'] / 1e3 * 1.25)
    a2.set_ylim(-0.15, 1.45)
    a2.set_title('zoom: la ventana de la campaña (×36)', loc='left',
                 color=TINTA2)
    a2.text(res['tasa_baja'] / 1e3, res['deriva_medida_pct'],
            ' medido en placa, +1.28 % ', ha='left', va='top', color=ROJO,
            fontsize=8.5)
    a2.annotate('', xy=(res['tasa_alta'] / 1e3, res['deriva_medida_pct']),
                xytext=(res['tasa_alta'] / 1e3,
                        100 * (_serie(res, True, 'centroide')[1][5] /
                               _serie(res, True, 'centroide')[1][0] - 1)),
                arrowprops=dict(arrowstyle='<->', color=TINTA2, lw=1.1))
    a2.text(res['tasa_alta'] / 1e3 * 0.97, 0.68,
            'lo que NINGUNO\nde los dos explica', ha='right', va='center',
            color=TINTA2, fontsize=8.5)

    fig.suptitle('El seguidor contra la deriva de centroide',
                 x=0.008, ha='left', fontsize=10.5, color=TINTA2)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _guardar(fig, out, 'deriva_centroide.png')


def fig_mecanismo(res, out):
    """La base que el seguidor alcanza a seguir, y cuánto tiempo está congelado."""
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    t, b = _serie(res, True, 'base_media')
    ax.plot(t / 1e3, b, 'o-', color=AZUL, ms=4, lw=1.5,
            label='base seguida (cuentas)')
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('tasa incidente [kcps]')
    ax.set_ylabel('línea de base seguida [cuentas]')
    _limpiar(ax)

    ax2 = ax.twinx()
    _, fc = _serie(res, True, 'frac_congelada')
    ax2.plot(t / 1e3, 100 * fc, 's--', color=NARAN, ms=3.5, lw=1.2,
             label='tiempo congelado (%)')
    ax2.set_ylabel('tiempo con el IIR congelado [%]', color=NARAN)
    ax2.tick_params(axis='y', colors=NARAN)
    ax2.grid(False)
    for lado in ('top',):
        ax2.spines[lado].set_visible(False)

    l1, e1 = ax.get_legend_handles_labels()
    l2, e2 = ax2.get_legend_handles_labels()
    ax.legend(l1 + l2, e1 + e2, loc='upper left', fontsize=9)
    ax.set_title('El mecanismo: el pedestal sube y el seguidor se congela',
                 loc='left', color=TINTA2)
    fig.tight_layout()
    _guardar(fig, out, 'mecanismo_base.png')


def fig_trazas(res, out):
    """Trazas en volts, con la base seguida dibujada encima."""
    forma, _ = pu.forma_referencia()
    V = pu.ADC_CNT_PER_V
    us = 1e6 / pu.FS_HZ
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.4))

    # Los dos paneles son la MISMA ventana de tiempo a tasa alta. Arriba, la
    # señal a su escala; abajo, la misma traza con el eje y en la escala de la
    # BASE, que es 50 veces más chica: a la escala de los pulsos la linea de
    # base es una raya sobre el cero y no se ve nada de lo que hace.
    rng = np.random.default_rng(3)
    tasa = res['tasa_alta']
    amps = pu.sortear_amplitudes(400, 'linea', rng, centro=res['a_linea'],
                                 res_pct=res['res_pct'])
    t_idx = pu.arribos_poisson(400, tasa, rng=rng)
    dat, o = pu.render(t_idx, amps, forma, rng=rng, trail=lb.TRAIL)
    ev = pu.segmentar_base(dat, bl_auto=True, bl_k=res['bl_k'], bl_holdoff=64,
                           traza_base=True, bl_acc0=0, **pu.CFG_MODO0)
    x = np.arange(dat.size) * us

    # una ventana de ~150 us bien adentro, donde el IIR ya convergió
    i0 = dat.size // 2
    sel = slice(i0, min(i0 + int(150 / us), dat.size))
    cong = ev['congelada'][sel]
    xs = x[sel]

    for ax, zoom in zip(axes, (False, True)):
        ax.plot(xs, dat[sel] / V * 1e3, color=TINTA, lw=0.7, label='señal')
        ax.plot(xs, ev['base'][sel] / V * 1e3, color=ROJO, lw=1.8,
                label='línea de base seguida', zorder=5)
        ax.axhline(pu.CFG_MODO0['thr'] / V * 1e3, color=MUDO, lw=0.9, ls=':')

        # sombrear los tramos donde el IIR está congelado
        bordes = np.flatnonzero(np.diff(cong.astype(int)))
        tramos = np.concatenate(([0], bordes + 1, [cong.size]))
        for a, b in zip(tramos[:-1], tramos[1:]):
            if cong[a]:
                ax.axvspan(xs[a], xs[min(b, cong.size - 1)], color=MUDO,
                           alpha=.16, lw=0)

        ax.set_xlabel('tiempo [\u00b5s]')
        ax.set_ylabel('tensi\u00f3n [mV]')
        _limpiar(ax)
        if zoom:
            b = ev['base'][sel] / V * 1e3
            m, sd = float(b.mean()), float(b.std())
            ax.set_ylim(m - 4 * (sd + 0.02), m + 6 * (sd + 0.02))
            ax.set_title('la misma traza, con el eje y en la escala de la BASE '
                         '(sombreado: el IIR congelado)',
                         loc='left', color=TINTA2, fontsize=9.5)
        else:
            ax.set_title(f'{tasa/1e3:.0f} kcps \u2014 base media '
                         f'{ev["base"][sel].mean():.1f} cuentas, IIR congelado '
                         f'el {100*cong.mean():.0f} % del tiempo',
                         loc='left', color=TINTA2, fontsize=9.5)
            ax.legend(fontsize=8, loc='upper right')

    fig.tight_layout()
    _guardar(fig, out, 'trazas_base.png')


def fig_bl_k(res, out):
    """Barrido de bl_k: dónde está el óptimo y dónde se come el pulso."""
    f = res['bl_k_barrido']
    k = np.array([r['bl_k'] for r in f], dtype=float)
    c = np.array([r['centroide'] for r in f], dtype=float)
    b = np.array([r['base_media'] for r in f], dtype=float)
    n = np.array([r['n_det'] for r in f], dtype=float)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.4))
    a1.plot(k, c, 'o-', color=AZUL, ms=4, lw=1.5)
    a1.set_xlabel('bl_k')
    a1.set_ylabel('centroide [canales]')
    a1.set_title(f'centroide a {res["tasa_alta"]/1e3:.0f} kcps', loc='left',
                 color=TINTA2)

    a2.plot(k, b, 'o-', color=AZUL, ms=4, lw=1.5, label='base seguida')
    a2.set_xlabel('bl_k')
    a2.set_ylabel('base seguida [cuentas]')
    a2.set_title('cuánto pedestal alcanza a seguir', loc='left', color=TINTA2)

    # la cota de la regla: tau >= 100 x la duración del pulso
    ancho_muestras = res['forma']['fwhm_pts']
    k_min = np.log2(100 * ancho_muestras)
    for ax in (a1, a2):
        ax.axvline(k_min, color=ROJO, lw=1.1, ls='--')
        ax.text(k_min, ax.get_ylim()[1], f'  τ = 100× el pulso (k={k_min:.1f})',
                ha='left', va='top', color=ROJO, fontsize=8)
        _limpiar(ax)

    a3 = a1.twinx()
    a3.plot(k, n, 's--', color=NARAN, ms=3.5, lw=1.1)
    a3.set_ylabel('eventos detectados', color=NARAN)
    a3.tick_params(axis='y', colors=NARAN)
    a3.grid(False)
    a3.spines['top'].set_visible(False)

    fig.tight_layout()
    _guardar(fig, out, 'barrido_bl_k.png')


def main():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        c = sorted(glob.glob(os.path.join(_RAIZ, 'datos', 'base_*')))
        if not c:
            raise SystemExit('no hay corridas base_* en software/datos/')
        d = c[-1]
    with open(os.path.join(d, 'resumen.json')) as f:
        res = json.load(f)

    print(f'=== {os.path.relpath(d)} ===')
    print(f'{res["n_eventos"]} eventos por punto, bl_k = {res["bl_k"]}')
    for fn in (fig_deriva, fig_mecanismo, fig_trazas, fig_bl_k):
        try:
            fn(res, d)
        except Exception as e:
            print(f'  [ERROR] {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\nfiguras en {d}')


if __name__ == '__main__':
    main()
