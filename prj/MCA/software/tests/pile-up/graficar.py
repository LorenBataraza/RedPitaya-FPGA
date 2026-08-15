#!/usr/bin/env python3
"""Figuras del Monte-Carlo de apilamiento, desde los .npz que dejó montecarlo.py.

Corre en la PC y NO vuelve a simular: todo sale de los archivos guardados, así
que rehacer una figura cuesta segundos y no minutos. Es el mismo reparto que usa
`testbench_mca.plot_all`.

    python3 graficar.py [directorio]      # por defecto, la corrida más reciente
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
import pileup as pu                                          # noqa: E402

# --- paleta (la misma de docs/mca/figuras/figuras_resolucion.py) -------------
SUP    = '#fcfcfb'
TINTA  = '#0b0b0b'
TINTA2 = '#52514e'
MUDO   = '#898781'
GRILLA = '#e1e0d9'
AZUL   = '#2a78d6'   # la verdad / la referencia
NARAN  = '#eb6834'   # lo medido, deformado
ROJO   = '#d03b3b'   # lo que se está señalando
VERDE  = '#2e8b57'   # lo recuperado por el corte
RAMPA  = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281']

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})

MODO = {0: 'histéresis', 1: 'compuertas fijas'}
RAZON = {'q_pico': 'Q/pico', 'psd': 'Q_cola/Q_tot (en HW)'}


def _limpiar(ax):
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def _guardar(fig, out, nombre):
    p = os.path.join(out, nombre)
    fig.savefig(p, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'  {nombre}')


def _suavizar(h, f=8):
    """Reagrupa para que las figuras muestren forma y no ruido de Poisson."""
    return pu.rebin(h, f), f


# =============================================================================
def fig_espectros(d, res, out):
    """Los tres espectros superpuestos: qué le hace el apilamiento al histograma."""
    combos = res['combinaciones']
    fig, axes = plt.subplots(len(combos) // 2 if len(combos) > 2 else 1,
                             2 if len(combos) > 1 else 1,
                             figsize=(11, 3.6 * max(1, len(combos) // 2)),
                             squeeze=False)
    axes = axes.ravel()

    for ax, c in zip(axes, combos):
        z = np.load(os.path.join(d, f'{c["espectro"]}_modo{c["modo"]}.npz'))
        tasas = z['tasas']
        roi = res['espectros'][c['espectro']]
        # la tasa más alta que todavía deja estadística para ver la forma
        it = int(np.argmin(np.abs(tasas - 1e5)))

        h_ver, h_ref, h_med = z['h_ver'], z['h_ref'], z['h_med'][it]
        g_ver, f = _suavizar(h_ver)
        g_ref, _ = _suavizar(h_ref)
        g_med, _ = _suavizar(h_med)
        x = (np.arange(g_ver.size) + 0.5) * f

        # normalizados al número de eventos generados: comparables entre sí
        ax.step(x, g_ver / h_ver.sum(), where='mid', color=MUDO, lw=1.0,
                label='verdad (fuente)')
        ax.step(x, g_ref / h_ver.sum(), where='mid', color=AZUL, lw=1.3,
                label='referencia (tasa cero)')
        ax.step(x, g_med / h_ver.sum(), where='mid', color=NARAN, lw=1.3,
                label=f'medido a {tasas[it]/1e3:.0f} kcps')
        ax.axvline(roi['tope'], color=ROJO, lw=1.0, ls=':')
        ax.set_yscale('log')
        ax.set_xlim(0, min(2.6 * roi['tope'], z['h_ver'].size))
        ax.set_ylim(1e-6, None)
        ax.set_xlabel('canal (= cuentas de amplitud verdadera)')
        ax.set_ylabel('fracción por canal')
        ax.set_title(f'{c["espectro"]} — modo {c["modo"]} ({MODO[c["modo"]]})',
                     loc='left', color=TINTA2)
        _limpiar(ax)
        ax.legend(loc='upper right', fontsize=8)

    fig.tight_layout()
    _guardar(fig, out, 'espectros.png')


def fig_distorsion(d, res, out):
    """Las métricas de distorsión contra la tasa, con el modelo de tiempo muerto."""
    combos = res['combinaciones']
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))

    for i, c in enumerate(combos):
        roi = res['espectros'][c['espectro']]
        p = roi['picos'][0]
        tasas = np.array([f['tasa'] for f in c['filas']])
        col = RAMPA[i % len(RAMPA)] if c['modo'] == 0 else None
        col = [AZUL, NARAN, '#7a5bbd', '#2e8b57'][i % 4]
        et = f'{c["espectro"]} m{c["modo"]}'

        area = np.array([f[f'm{p}']['area_rel'] for f in c['filas']])
        cont = np.array([f[f'm{p}']['continuo'] for f in c['filas']])
        l1   = np.array([f[f'm{p}']['l1'] for f in c['filas']])
        thru = np.array([f['n_det'] / f['n_gen'] for f in c['filas']])

        # Dos pérdidas distintas, y la diferencia entre ellas ES el apilamiento:
        #   - el THROUGHPUT (línea fina) pierde por tiempo muerto y nada más, y
        #     por eso sigue al modelo paralizable;
        #   - el FOTOPICO (línea gruesa) pierde eso MÁS los eventos que el
        #     apilamiento se llevó fuera del pico. Comparar el fotopico contra el
        #     modelo de tiempo muerto sería mezclar las dos cosas.
        axes[0].plot(tasas / 1e3, thru, '-', color=col, lw=0.9, alpha=.55)
        axes[0].plot(tasas / 1e3, area, 'o-', color=col, ms=3.5, lw=1.6, label=et)
        axes[1].plot(tasas / 1e3, 100 * cont, 'o-', color=col, ms=3.5, lw=1.3,
                     label=et)
        axes[2].plot(tasas / 1e3, l1, 'o-', color=col, ms=3.5, lw=1.3, label=et)

        # modelo paralizable con la ventana medida: m/n = exp(-lambda*L0)
        if i < 2:
            L0 = c['L0'] / pu.FS_HZ
            axes[0].plot(tasas / 1e3, np.exp(-tasas * L0), ls='--', lw=1.0,
                         color=MUDO,
                         label='exp(-λL₀) paralizable' if i == 0 else None)

    for ax, t, yl in ((axes[0], 'fotopico (grueso) contra throughput (fino)',
                       'fracción de lo incidente'),
                      (axes[1], 'continuo por encima del tope', '% de las cuentas'),
                      (axes[2], 'deformación global', 'distancia L1')):
        ax.set_xscale('log')
        ax.set_xlabel('tasa incidente [kcps]')
        ax.set_ylabel(yl)
        ax.set_title(t, loc='left', color=TINTA2)
        _limpiar(ax)
    axes[0].legend(fontsize=7.5, loc='lower left')
    fig.tight_layout()
    _guardar(fig, out, 'distorsion_vs_tasa.png')


def fig_mapa(d, res, out):
    """Amplitud contra factor de forma: dónde se separan limpios y apilados."""
    combos = res['combinaciones']
    fig, axes = plt.subplots(len(combos), 2, figsize=(10.5, 3.3 * len(combos)),
                             squeeze=False)

    for fila, c in zip(axes, combos):
        z = np.load(os.path.join(d, f'{c["espectro"]}_modo{c["modo"]}.npz'))
        if 'mapa_amp' not in z:
            continue
        amp = z['mapa_amp'].astype(float)
        n_arr = z['mapa_n_arr']
        cal = z['cal']
        a_true = (amp - cal[1]) / cal[0]           # eje en amplitud verdadera

        for ax, rz in zip(fila, res['razones']):
            r = z[f'mapa_r_{rz}'].astype(float)
            lim = n_arr <= 1
            ax.scatter(a_true[lim], r[lim], s=1.2, alpha=.18, color=AZUL,
                       linewidths=0, label='limpio (1 pulso)')
            ax.scatter(a_true[~lim], r[~lim], s=1.2, alpha=.30, color=ROJO,
                       linewidths=0, label='apilado (>1 pulso)')

            ce, me, si = z[f'locus_{rz}']
            ce_t = (ce - cal[1]) / cal[0]
            ax.plot(ce_t, me, color=TINTA, lw=1.2, label='lugar geométrico')
            ax.plot(ce_t, me + 3 * si, color=TINTA, lw=1.0, ls='--',
                    label='banda k=3')

            fin = np.isfinite(r)
            if fin.any():
                ax.set_ylim(np.nanpercentile(r[fin], 0.5),
                            np.nanpercentile(r[fin], 99.5))
            ax.set_xlim(0, np.percentile(a_true, 99.8))
            ax.set_xlabel('amplitud verdadera equivalente [cuentas]')
            ax.set_ylabel(RAZON[rz])
            ax.set_title(f'{c["espectro"]} m{c["modo"]} — {RAZON[rz]}',
                         loc='left', color=TINTA2, fontsize=9)
            _limpiar(ax)
    axes[0][0].legend(fontsize=7, loc='upper left', markerscale=6)
    fig.tight_layout()
    _guardar(fig, out, 'mapa_forma.png')


def fig_corte(d, res, out):
    """El espectro antes y después del corte, contra la referencia."""
    combos = res['combinaciones']
    ks = res['ks']
    ik = int(np.argmin(np.abs(np.array(ks) - 3.0)))
    fig, axes = plt.subplots(len(combos) // 2 if len(combos) > 2 else 1,
                             2 if len(combos) > 1 else 1,
                             figsize=(11, 3.6 * max(1, len(combos) // 2)),
                             squeeze=False)
    axes = axes.ravel()

    for ax, c in zip(axes, combos):
        z = np.load(os.path.join(d, f'{c["espectro"]}_modo{c["modo"]}.npz'))
        tasas = z['tasas']
        roi = res['espectros'][c['espectro']]
        it = int(np.argmin(np.abs(tasas - 1e5)))
        ir = res['razones'].index('q_pico')

        h_ref, h_med = z['h_ref'], z['h_med'][it]
        h_cut = z['h_cortes'][it, ir, ik]
        n = h_ref.sum()
        for h, col, et in ((h_ref, AZUL, 'referencia (tasa cero)'),
                           (h_med, NARAN, f'medido a {tasas[it]/1e3:.0f} kcps'),
                           (h_cut, VERDE, f'medido + corte Q/pico k={ks[ik]:g}')):
            g, f = _suavizar(h)
            ax.step((np.arange(g.size) + .5) * f, g / n, where='mid',
                    color=col, lw=1.3, label=et)
        ax.axvline(roi['tope'], color=ROJO, lw=1.0, ls=':')
        ax.set_yscale('log')
        ax.set_xlim(0, min(2.6 * roi['tope'], h_ref.size))
        ax.set_ylim(1e-6, None)
        ax.set_xlabel('canal')
        ax.set_ylabel('fracción por canal')
        ax.set_title(f'{c["espectro"]} — modo {c["modo"]} ({MODO[c["modo"]]})',
                     loc='left', color=TINTA2)
        _limpiar(ax)
        ax.legend(loc='upper right', fontsize=8)
    fig.tight_layout()
    _guardar(fig, out, 'corte.png')


def fig_compromiso(d, res, out):
    """Eficiencia contra rechazo: lo que cuesta cada punto de corrección."""
    combos = res['combinaciones']
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))

    for i, c in enumerate(combos):
        roi = res['espectros'][c['espectro']]
        p = roi['picos'][0]
        tasas = np.array([f['tasa'] for f in c['filas']])
        it = int(np.argmin(np.abs(tasas - 1e5)))
        fila = c['filas'][it]
        col = [AZUL, NARAN, '#7a5bbd', '#2e8b57'][i % 4]

        for rz, ls, mk in (('q_pico', '-', 'o'), ('psd', '--', 's')):
            sub = [x for x in fila['cortes'] if x['razon'] == rz]
            ef = np.array([x['eficiencia'] for x in sub])
            re = np.array([x['rechazo'] for x in sub])
            l1 = np.array([x[f'm{p}']['l1'] for x in sub])
            et = f'{c["espectro"]} m{c["modo"]} {RAZON[rz]}'
            axes[0].plot(100 * re, 100 * ef, ls, marker=mk, color=col, ms=3.5,
                         lw=1.2, label=et)
            axes[1].plot([x['k'] for x in sub], l1, ls, marker=mk, color=col,
                         ms=3.5, lw=1.2, label=et)
        axes[1].axhline(fila[f'm{p}']['l1'], color=col, lw=0.8, ls=':')

    axes[0].set_xlabel('apilados rechazados [%]')
    axes[0].set_ylabel('limpios conservados [%]')
    axes[0].set_title('lo que cuesta rechazar', loc='left', color=TINTA2)
    axes[1].set_xlabel('ancho de la banda, k [sigmas]')
    axes[1].set_ylabel('distancia L1 al espectro de referencia')
    axes[1].set_title('deformación que queda (punteado: sin corte)',
                      loc='left', color=TINTA2)
    for ax in axes:
        _limpiar(ax)
    axes[0].legend(fontsize=7, loc='lower left')
    fig.tight_layout()
    _guardar(fig, out, 'compromiso.png')


def main():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        cands = sorted(glob.glob(os.path.join(_AQUI, '..', '..', 'datos',
                                              'pileup_*')))
        if not cands:
            raise SystemExit('no hay corridas pileup_* en software/datos/')
        d = cands[-1]

    with open(os.path.join(d, 'resumen.json')) as f:
        res = json.load(f)
    print(f'=== {os.path.relpath(d)} ===')
    print(f'{res["n_eventos"]} eventos por punto, '
          f'{len(res["tasas"])} tasas, {len(res["combinaciones"])} combinaciones')

    for fn in (fig_espectros, fig_distorsion, fig_mapa, fig_corte,
               fig_compromiso):
        try:
            fn(d, res, d)
        except Exception as e:                      # una figura mala no tira el resto
            print(f'  [ERROR] {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\nfiguras en {d}')


if __name__ == '__main__':
    main()
