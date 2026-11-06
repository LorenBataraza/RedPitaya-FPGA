#!/usr/bin/env python3
"""Monte-Carlo: qué le hace la forma del pulso a la amplitud de pico, y dónde.

Corre en la PC, sin placa.

LA PREGUNTA
-----------
La figura 17.24 de Nicholson (Knoll, cap. 17) ordena los conformadores por su
S/N relativo al cusp infinito: triangular .930, CR-RC^4 .858, CR-RC .736,
(CR)^2-RC .709. La intuición dice que conformar PROMEDIA el ruido, así que ¿de
qué S/N se pierde? De ninguna contra "no conformar": la figura compara
conformadores entre sí, cada uno en su constante de tiempo de mínimo ruido, y
contra el filtro óptimo. Y lo hace con el ruido inyectado ANTES del
conformador, que es el caso del preamplificador y no el de nuestra cadena.

POR QUÉ DOS EXPERIMENTOS
------------------------
  A. RUIDO ANTES DEL CONFORMADOR (Nicholson). La salida del preamp es un
     escalón más ruido serie (blanco) y ruido paralelo (integral de blanco). El
     conformador es un filtro lineal cuya respuesta al escalón es la forma del
     catálogo. La varianza en el pico es

         sigma^2(tau) = a*A1/tau + b*A2*tau,  A1 = int s'(u)^2 du, A2 = int s(u)^2 du

     con un mínimo en tau* = sqrt(a*A1/(b*A2)) que vale 2*sqrt(a*b*A1*A2). El
     cusp e^{-|u|} tiene A1 = A2 = 1, así que el S/N relativo al cusp es
     (A1*A2)^(-1/4). Para CR-RC eso da (e^4/16)^(-1/4) = 0.736: el número de la
     figura. El Monte-Carlo verifica la fórmula sorteando el ruido y filtrando.

  B. RUIDO EN EL ADC (nuestra cadena). El pulso ya llega conformado; el ruido
     que medimos es el del ADC, blanco a 125 MSPS, sigma = 2.8 cuentas. Acá la
     forma actúa por otros dos caminos: cuántas muestras caen en el ápice (el
     estimador `max` de N gaussianas se sesga hacia arriba como sqrt(2 ln N)) y
     la fase de muestreo por la pendiente en el ápice (un ápice puntiagudo se
     muestrea a U[0, Ts) del máximo). Se simulan las mismas familias, con el
     mismo FWHM y la misma altura, con el ruido y la fase por separado, por
     tres estimadores: el `pico` del RTL, un boxcar y el filtro adaptado.

El resultado que importa es que el ORDEN SE INVIERTE: el trapecio es el peor
de todos en A (techo plano = más A2 por el mismo A1) y el mejor en B (techo
plano = no ve la fase). Y que con un filtro adaptado digital vuelve la lógica
de A —el filtro adaptado al ruido es el óptimo— pero con el ADC como espectro:
como es blanco, la sigma queda fijada por la energía del pulso, sum(s_n^2), y
a FWHM fijo eso vale lo mismo para todas las familias. La forma deja de
importar.

    python3 conformado.py                    # los dos experimentos (~1 min)
    python3 conformado.py --solo adc --n 20000
    python3 conformado.py --amplitud 1000 --sigma 5 --out DIR
"""
import argparse
import json
import os
import sys
import time

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
import replica_mca2 as r2                                    # noqa: E402
import rigol_dg4162 as rg                                    # noqa: E402

# --- paleta (la misma del resto del estudio) ---------------------------------
SUP    = '#fcfcfb'
TINTA  = '#0b0b0b'
TINTA2 = '#52514e'
MUDO   = '#898781'
GRILLA = '#e1e0d9'

plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})


# =============================================================================
# Catálogo: las seis de Knoll más el cusp, que es la referencia de Nicholson
# =============================================================================

U0_CUSP = 8.0


def forma_cusp(u, u0=U0_CUSP):
    """Cusp e^{-|u-u0|}: el filtro óptimo para ruido serie + paralelo.

    Es infinito por los dos lados; acá se lo trunca en u=0 (e^{-8} = 3e-4 del
    pico) para que entre en la convención causal del catálogo. Sólo se usa en
    este estudio, por eso no está en `FORMAS_KNOLL`.
    """
    u = np.asarray(u, dtype=float)
    return np.where(u < 0, 0.0, np.exp(-np.abs(u - u0)))


# (clave, etiqueta, S/N relativo según Nicholson —None si la figura no lo da—, color)
FAMILIAS = [
    ('cusp',        'cusp',        1.000, '#0b0b0b'),
    ('triangular',  'triangular',  0.930, '#2a78d6'),
    ('trapezoidal', 'trapezoidal', None,  '#2e8b57'),
    ('cr_rc4',      'CR-RC⁴',      0.858, '#c9a227'),
    ('cr_rc',       'CR-RC',       0.736, '#eb6834'),
    ('cr',          'CR',          None,  '#d03b3b'),
    ('bipolar',     '(CR)²-RC',    0.709, '#7a5bbd'),
]
CALLABLES = dict(rg.FORMAS_KNOLL, cusp=forma_cusp)

ESTIMADORES = ('pico', 'boxcar', 'adaptado')
COLOR_EST = {'pico': '#d03b3b', 'boxcar': '#c9a227', 'adaptado': '#2a78d6'}
M_BOXCAR = 4                    # media móvil de 2*M+1 = 9 muestras (72 ns)


def _sondeo_largo(f, du=1.0 / 256, u_max=48.0, piso=1e-5):
    """La forma en una grilla fina, normalizada al pico y cortada donde la cola
    cae bajo `piso`. Más larga que `rg._sondeo` porque CR-RC^4 y el cusp
    todavía tienen cola en u=16."""
    u = np.arange(0.0, u_max, du)
    y = np.asarray(f(u), dtype=float)
    y = y / float(np.abs(y).max())
    # se corta después de la ÚLTIMA muestra que supera el piso, no en la
    # primera que baja de él: la bipolar cruza por cero y sigue
    n = min(int(np.flatnonzero(np.abs(y) >= piso)[-1]) + 2, y.size)
    return u[:n], y[:n]


# =============================================================================
# A. Ruido antes del conformador: los índices de forma y el codo de ruido
# =============================================================================

def indices_forma(f):
    """(A1, A2): integrales de s'^2 y de s^2 con s normalizada al pico.

    A1 pesa el ruido serie (cae con tau), A2 el paralelo (crece con tau). La
    figura de merito del conformador es (A1*A2)^(-1/4) relativa al cusp.
    """
    u, y = _sondeo_largo(f)
    du = float(u[1] - u[0])
    a1 = float((np.diff(y) ** 2).sum() / du)
    a2 = float((y ** 2).sum() * du)
    return a1, a2


def sn_relativo(a1, a2):
    return float((a1 * a2) ** -0.25)


def sigma_teorica(tau, a1, a2, a=1.0, b=1.0):
    tau = np.asarray(tau, dtype=float)
    return np.sqrt(a * a1 / tau + b * a2 * tau)


def mc_nicholson(f, taus, n, rng, a=1.0, b=1.0, pts_por_tau=64, tanda=500):
    """sigma en el pico, sorteando el ruido y pasándolo por el conformador.

    La salida es y = s * dv, con dv la DERIVADA de la entrada: un delta de
    señal más el ruido serie derivado más el paralelo (que derivado es blanco).
    Como el filtro es lineal y el ruido estacionario, la muestra del pico es un
    funcional lineal del ruido y se calcula directo, sin convolver toda la
    traza:

        y_pico = sum_j (s_{j+1} - s_j) * xi_j  +  sum_j s_j * eta_j
        xi ~ N(0, a/dt)  (ruido serie muestreado)     eta ~ N(0, b*dt)  (incrementos del paralelo)

    La grilla es relativa a tau (`pts_por_tau` puntos por unidad de escala)
    para que el costo no crezca con tau. Devuelve sigma(tau), un valor por tau.
    """
    u, s = _sondeo_largo(f)
    # remuestreo a la grilla del MC: pts_por_tau puntos por unidad de u
    du = 1.0 / float(pts_por_tau)
    ug = np.arange(0.0, float(u[-1]), du)
    sg = np.interp(ug, u, s)
    ds = np.diff(sg)
    out = np.empty(len(taus))
    for k, tau in enumerate(taus):
        dt = float(tau) * du                       # paso temporal real
        acc = np.empty(int(n))
        for i0 in range(0, int(n), int(tanda)):
            m = min(int(tanda), int(n) - i0)
            xi = rng.normal(0.0, np.sqrt(a / dt), (m, ds.size))
            eta = rng.normal(0.0, np.sqrt(b * dt), (m, sg.size))
            acc[i0:i0 + m] = xi @ ds + eta @ sg
        out[k] = acc.std()
    return out


def experimento_nicholson(n, rng, taus=None, verbose=True):
    taus = np.logspace(np.log10(0.2), np.log10(5.0), 15) if taus is None else taus
    filas = []
    for clave, etiqueta, nich, _ in FAMILIAS:
        a1, a2 = indices_forma(CALLABLES[clave])
        tau_opt = float(np.sqrt(a1 / a2))
        sig_mc = mc_nicholson(CALLABLES[clave], taus, n, rng)
        sig_teo = sigma_teorica(taus, a1, a2)
        sig_mc_opt = float(mc_nicholson(CALLABLES[clave], [tau_opt], n, rng)[0])
        sn_teo = sn_relativo(a1, a2)
        # sigma_min del cusp es 2^0.5 (a=b=1, A1=A2=1); el S/N relativo por MC
        # es el cociente de sigmas mínimos
        sn_mc = float(np.sqrt(2.0) / sig_mc_opt)
        filas.append(dict(familia=clave, etiqueta=etiqueta, A1=a1, A2=a2,
                          tau_opt=tau_opt, sn_teo=sn_teo, sn_mc=sn_mc,
                          sn_nicholson=nich, sigma_mc=sig_mc.tolist(),
                          sigma_teo=sig_teo.tolist()))
    if verbose:
        print(f'  {"familia":<12} {"A1":>7} {"A2":>7} {"tau*":>6} '
              f'{"S/N teo":>8} {"S/N MC":>7} {"Nicholson":>10} {"dif":>7}')
        for r in filas:
            nich = f'{r["sn_nicholson"]:10.3f}' if r['sn_nicholson'] else f'{"—":>10}'
            dif = (f'{r["sn_teo"] - r["sn_nicholson"]:+7.3f}'
                   if r['sn_nicholson'] else f'{"":>7}')
            print(f'  {r["etiqueta"]:<12} {r["A1"]:7.3f} {r["A2"]:7.3f} '
                  f'{r["tau_opt"]:6.3f} {r["sn_teo"]:8.3f} {r["sn_mc"]:7.3f} '
                  f'{nich} {dif}')
    return dict(taus=taus.tolist(), filas=filas)


# =============================================================================
# B. Ruido en el ADC: fase de muestreo, estimador y familia
# =============================================================================

def geometria(clave, fwhm_s=pu.FWHM_S):
    """Escala (muestras por unidad de u), largo y pico continuo de una familia."""
    f = CALLABLES[clave]
    _, info = pu.forma_knoll(f, fwhm_s=fwhm_s)
    u, y = _sondeo_largo(f)
    yy = np.asarray(f(u), dtype=float)
    u_pico = float(u[int(np.argmax(yy))])
    # corrimiento que deja el ápice continuo SOBRE una muestra con fase 0: si
    # no, "fase 0" significaría otra cosa para cada familia (el cusp pica en
    # u=8, que no cae en un entero de la grilla del ADC)
    off = float((u_pico * info['escala']) % 1.0)
    return dict(f=f, escala=info['escala'], n=info['n'], off=off,
                pico=float(yy.max()), fwhm_pts=info['fwhm_pts'])


def u_de_muestra(g, k, fase=0.0):
    """Coordenada `u` de la forma en la muestra `k` del ADC, con la fase dada."""
    return (np.asarray(k, dtype=float) + g['off'] - float(fase)) / float(g['escala'])


def plantilla_fase(g, fase):
    """La forma muestreada por el ADC con la fase `fase` (en muestras, [0,1)).

    Fase 0 es "una muestra cae exactamente sobre el ápice continuo"; la fase
    corre las muestras hacia la derecha. Normalizada por el pico CONTINUO, no
    por el máximo muestreado: la verdad del experimento tiene que ser
    exactamente la amplitud pedida, y con un ápice puntiagudo el máximo
    muestreado queda por debajo.
    """
    n = int(g['n']) + 1
    u = u_de_muestra(g, np.arange(n), fase)
    return np.asarray(g['f'](u), dtype=float) / float(g['pico'])


def muestras_en_apice(g, frac=0.99):
    return int((plantilla_fase(g, 0.0) >= frac).sum())


def _boxcar_max(m, k=M_BOXCAR):
    """Máximo de la media móvil de 2k+1 muestras, por fila."""
    c = np.cumsum(np.pad(m, ((0, 0), (1, 0))), axis=1)
    w = 2 * k + 1
    return ((c[:, w:] - c[:, :-w]) / float(w)).max(axis=1)


def _adaptado(m, s0, lags=range(-3, 4)):
    """Filtro adaptado: correlación con la plantilla de fase 0, máximo sobre
    los lags enteros cercanos. Normalizado para que un pulso sin ruido y sin
    fase devuelva la amplitud exacta."""
    n = s0.size
    e = float((s0 ** 2).sum())
    mejor = np.full(m.shape[0], -np.inf)
    for l in lags:
        a, b = max(0, l), min(m.shape[1], n + l)
        v = m[:, a:b] @ s0[a - l:b - l] / e
        np.maximum(mejor, v, out=mejor)
    return mejor


def simular_adc(g, n, rng, amplitud, sigma, fase=True, lead=256, trail=512):
    """n pulsos aislados, cada uno con su fase, por la réplica del MCA2.

    Devuelve dict estimador -> array de n amplitudes estimadas. `pico` es el
    del RTL (`replica_mca2`); `boxcar` y `adaptado` se calculan sobre la
    misma matriz de muestras, así que los tres ven el MISMO ruido.
    """
    n = int(n)
    fases = rng.random(n) if fase else np.zeros(n)
    largo = int(g['n']) + 1
    M = np.stack([float(amplitud) * plantilla_fase(g, ph) for ph in fases])
    if sigma > 0:
        M += rng.normal(0.0, float(sigma), M.shape)
    np.rint(M, out=M)
    np.clip(M, -pu.SAT_ADC - 1, pu.SAT_ADC, out=M)

    # una traza con los pulsos en ranuras, como `pu.render_aislados`
    paso = largo + int(trail)
    ruido_base = rng.normal(0.0, float(sigma), lead + n * paso) if sigma > 0 \
        else np.zeros(lead + n * paso)
    dat = np.rint(ruido_base)
    loc = lead + paso * np.arange(n, dtype=np.int64)
    for k in range(n):
        dat[loc[k]:loc[k] + largo] = M[k]
    # El MCA2: una ranura y el disparo por pendiente de la forma. La compuerta
    # tiene que alcanzar el ápice (el de la cúspide está en la muestra 1442: la
    # ventana por histéresis del MCA1 lo seguía, una compuerta de 384 no), y la
    # ventana abre antes del pulso, así que el apareo es por el disparo.
    s0 = plantilla_fase(g, 0.0)
    c = r2.cfg(n_acc=1, gate_long=max(384, int(np.argmax(s0)) + 144),
               **r2.disparo_para(s0))
    ev, _ = r2.eventos_mc(dat.astype(np.int64), c)
    ok = ev['cerrado']
    slot = np.searchsorted(loc, ev['i_par'][ok], side='right') - 1
    pico = np.full(n, np.nan)
    # primer evento de cada ranura (con A >> thr hay exactamente uno)
    _, primero = np.unique(slot, return_index=True)
    pico[slot[primero]] = ev['pico'][ok][primero]

    return dict(pico=pico, boxcar=_boxcar_max(M), adaptado=_adaptado(M, s0))


def _resumen(est, amplitud):
    v = est[np.isfinite(est)]
    return dict(sesgo=float(v.mean() - amplitud), sigma=float(v.std()),
                n=int(v.size))


def experimento_adc(n, rng, amplitud, sigma, verbose=True):
    filas = []
    for clave, etiqueta, _, _ in FAMILIAS:
        g = geometria(clave)
        fila = dict(familia=clave, etiqueta=etiqueta,
                    n_apice=muestras_en_apice(g), fwhm_pts=g['fwhm_pts'],
                    largo=int(g['n']))
        corridas = dict(total=simular_adc(g, n, rng, amplitud, sigma, fase=True),
                        fase=simular_adc(g, n, rng, amplitud, 0.0, fase=True),
                        ruido=simular_adc(g, n, rng, amplitud, sigma, fase=False))
        for e in ESTIMADORES:
            r = {c: _resumen(corridas[c][e], amplitud) for c in corridas}
            fila[e] = dict(sesgo=r['total']['sesgo'], sigma=r['total']['sigma'],
                           sigma_fase=r['fase']['sigma'],
                           sigma_ruido=r['ruido']['sigma'],
                           fwhm_pct=100.0 * 2.355 * r['total']['sigma'] / amplitud)
        filas.append(fila)

    if verbose:
        print(f'  amplitud {amplitud:.0f} cuentas, sigma ADC {sigma:.1f}, '
              f'{n} realizaciones por corrida, FWHM {pu.FWHM_S*1e6:.0f} µs\n')
        cab = f'  {"familia":<12} {"ápice":>5} '
        for e in ESTIMADORES:
            cab += f'│ {e:^30} '
        print(cab)
        print(f'  {"":<12} {"[n]":>5} ' + ''.join(
            f'│ {"sesgo":>6} {"σ":>6} {"σ_fase":>6} {"σ_rui":>6} {"FWHM%":>4}'
            for _ in ESTIMADORES))
        for r in filas:
            linea = f'  {r["etiqueta"]:<12} {r["n_apice"]:5d} '
            for e in ESTIMADORES:
                d = r[e]
                linea += (f'│ {d["sesgo"]:+6.2f} {d["sigma"]:6.2f} '
                          f'{d["sigma_fase"]:6.2f} {d["sigma_ruido"]:6.2f} '
                          f'{d["fwhm_pct"]:4.2f}')
            print(linea)
        print('\n  (sesgo y σ en cuentas; σ_fase: sin ruido, sólo fase y '
              'cuantización; σ_rui: con ruido y fase 0)')
        # chequeo de cuadratura, para el estimador del RTL
        print('  cuadratura σ² ≈ σ_fase² + σ_rui² (pico): ' + ', '.join(
            f'{r["etiqueta"]} {np.hypot(r["pico"]["sigma_fase"], r["pico"]["sigma_ruido"]) / max(r["pico"]["sigma"], 1e-9):.2f}'
            for r in filas))
    return dict(amplitud=amplitud, sigma=sigma, n=n, filas=filas)


# =============================================================================
# Figuras
# =============================================================================

def _limpiar(ax):
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)


def fig_nicholson(res, out):
    taus = np.array(res['taus'])
    filas = res['filas']
    sig_cusp_min = np.sqrt(2.0)
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13.5, 5.2),
                                 gridspec_kw=dict(width_ratios=(1.35, 1)))
    color = {c: col for c, _, _, col in FAMILIAS}
    tt = np.logspace(np.log10(taus[0]), np.log10(taus[-1]), 200)
    for r in filas:
        c = color[r['familia']]
        ax.plot(tt, sigma_teorica(tt, r['A1'], r['A2']) / sig_cusp_min,
                color=c, lw=1.4, label=r['etiqueta'])
        ax.plot(taus, np.array(r['sigma_mc']) / sig_cusp_min, 'o', color=c,
                ms=3.5, mec=SUP, mew=0.6)
        ax.plot([r['tau_opt']], [1.0 / r['sn_teo']], 'v', color=c, ms=7,
                mec=SUP, mew=0.6)
    ax.set_xscale('log')
    ax.set_yscale('log')
    for eje in (ax.xaxis, ax.yaxis):
        eje.set_major_formatter(matplotlib.ticker.ScalarFormatter())
        eje.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.set_yticks([1, 1.5, 2, 3, 4, 6])
    ax.set_xticks([0.2, 0.5, 1, 2, 5])
    ax.set_xlabel('constante de tiempo τ  (unidades donde a = b = 1)')
    ax.set_ylabel('σ en el pico / σ mínimo del cusp')
    ax.set_title('El codo de ruido: serie ∝ 1/√τ, paralelo ∝ √τ.  Línea: fórmula; '
                 'puntos: Monte-Carlo; ▼ el mínimo', loc='left', color=TINTA2)
    ax.legend(fontsize=8.5, loc='upper center', ncol=7,
              bbox_to_anchor=(0.5, -0.13), columnspacing=1.2)
    _limpiar(ax)

    orden = sorted(filas, key=lambda r: r['sn_teo'])
    y = np.arange(len(orden))
    bx.barh(y, [r['sn_teo'] for r in orden],
            color=[color[r['familia']] for r in orden], alpha=0.35, height=0.62,
            label='fórmula  (A₁A₂)^-¼')
    bx.plot([r['sn_mc'] for r in orden], y, 'o', color=TINTA, ms=5,
            label='Monte-Carlo en τ*')
    con = [(i, r['sn_nicholson']) for i, r in enumerate(orden) if r['sn_nicholson']]
    bx.plot([v for _, v in con], [i for i, _ in con], 'x', color='#d03b3b',
            ms=9, mew=1.8, label='Nicholson, fig. 17.24')
    for i, r in enumerate(orden):
        bx.text(0.02, i, f'{r["sn_teo"]:.3f}', va='center', fontsize=8.5,
                color=TINTA2)
    bx.set_yticks(y)
    bx.set_yticklabels([r['etiqueta'] for r in orden])
    bx.set_xlim(0, 1.08)
    bx.set_xlabel('S/N relativo al cusp')
    bx.set_title('Ruido ANTES del conformador, cada uno en su τ*',
                 loc='left', color=TINTA2)
    bx.legend(fontsize=8.5, loc='lower right')
    bx.grid(axis='y', visible=False)
    _limpiar(bx)

    fig.suptitle('Experimento A — el conformador como filtro del ruido del '
                 'preamplificador (Nicholson)',
                 x=0.008, ha='left', fontsize=10.5, color=TINTA)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    p = os.path.join(out, 'conformado_nicholson.png')
    fig.savefig(p, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return p


def fig_adc(res, out):
    filas = res['filas']
    nf = len(filas)
    fig = plt.figure(figsize=(14.5, 8.6))
    gs = fig.add_gridspec(2, nf, height_ratios=(1, 1.35), hspace=0.42,
                          wspace=0.32)
    color = {c: col for c, _, _, col in FAMILIAS}

    # --- arriba: el ápice, las muestras del ADC y el pico que ve el RTL ------
    # Se dibujan las muestras de UNA fase (0.5) y, para tres fases, la muestra
    # que el RTL toma como pico: en un ápice puntiagudo esa muestra baila con
    # la fase; en uno plano no.
    fases = (0.0, 0.33, 0.66)
    marcas = ('o', 's', '^')
    for j, r in enumerate(filas):
        ax = fig.add_subplot(gs[0, j])
        g = geometria(r['familia'])
        s0 = plantilla_fase(g, 0.0)
        i_pk = int(np.argmax(s0))
        semi = max(5, int(0.07 * g['fwhm_pts']))
        xx = np.linspace(-semi, semi, 400)
        ax.plot(xx, np.asarray(g['f'](u_de_muestra(g, xx + i_pk)), dtype=float)
                / g['pico'], color=color[r['familia']], lw=1.4)
        k = np.arange(i_pk - semi, i_pk + semi + 1)
        s = plantilla_fase(g, 0.5)
        ax.plot(k - i_pk, s[k], '.', color=MUDO, ms=4,
                label='muestras, fase 0.5' if j == 2 else None)
        for ph, mk in zip(fases, marcas):
            s = plantilla_fase(g, ph)
            km = int(np.argmax(s))
            ax.plot([km - i_pk], [s[km]], mk, color=TINTA, ms=6, mec=SUP,
                    mew=0.5, label=f'pico RTL, fase {ph:.2f}' if j == 2 else None)
        ax.axhline(1.0, color=MUDO, lw=0.7, ls=':')
        ax.set_ylim(0.95, 1.008)
        ax.set_xlim(-semi, semi)
        ax.set_title(f'{r["etiqueta"]}\n{r["n_apice"]} muestras ≥ 99 %',
                     loc='left', fontsize=9, color=TINTA2)
        ax.tick_params(labelsize=7.5)
        if j == 0:
            ax.set_ylabel('forma / pico continuo')
        else:
            ax.set_yticklabels([])
        if j == 2:
            ax.legend(fontsize=7, loc='lower right', handletextpad=0.3)
        ax.set_xlabel('muestra − pico', fontsize=8)
        _limpiar(ax)

    # --- abajo: sigma y sesgo por estimador ----------------------------------
    etiquetas = [r['etiqueta'] for r in filas]
    x = np.arange(nf)
    w = 0.26
    paneles = [('sigma', 'σ total [cuentas]'),
               ('sigma_fase', 'σ por fase de muestreo [cuentas]'),
               ('sesgo', 'sesgo [cuentas]')]
    sub = gs[1, :].subgridspec(1, 3, wspace=0.22)
    for p, (clave, titulo) in enumerate(paneles):
        ax = fig.add_subplot(sub[0, p])
        for i, e in enumerate(ESTIMADORES):
            v = [r[e][clave] for r in filas]
            ax.bar(x + (i - 1) * w, v, w * 0.92, color=COLOR_EST[e],
                   label=e if p == 1 else None)
        if clave == 'sesgo':
            ax.axhline(0, color=TINTA2, lw=0.8)
        if clave == 'sigma':
            ax.axhline(res['sigma'], color=MUDO, lw=0.8, ls='--')
            ax.text(nf - 0.55, res['sigma'], f'σ del ADC = {res["sigma"]:.1f}',
                    ha='right', va='bottom', fontsize=8, color=MUDO)
        ax.set_xticks(x)
        ax.set_xticklabels(etiquetas, rotation=28, ha='right', fontsize=8.5)
        ax.set_title(titulo, loc='left', color=TINTA2)
        ax.grid(axis='x', visible=False)
        if p == 1:
            ax.legend(fontsize=8.5, loc='upper right', title='estimador',
                      title_fontsize=8.5)
        _limpiar(ax)

    fig.suptitle(f'Experimento B — ruido EN EL ADC (σ = {res["sigma"]:.1f} '
                 f'cuentas), amplitud {res["amplitud"]:.0f}, FWHM '
                 f'{pu.FWHM_S*1e6:.0f} µs, {res["n"]} realizaciones.  Arriba: '
                 f'el ápice; en negro, la muestra que el RTL toma como pico '
                 f'para tres fases de muestreo', x=0.008, ha='left', fontsize=10.5,
                 color=TINTA)
    p = os.path.join(out, 'conformado_adc.png')
    fig.savefig(p, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return p


# =============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--solo', default='ambos', choices=['nicholson', 'adc', 'ambos'])
    ap.add_argument('--n', type=int, default=4000, help='realizaciones por corrida')
    ap.add_argument('--amplitud', type=float, default=1920.0,
                    help='altura del pulso en cuentas (default: la línea, 1920)')
    ap.add_argument('--sigma', type=float, default=pu.SIGMA_RUIDO,
                    help='sigma del ruido del ADC en cuentas')
    ap.add_argument('--semilla', type=int, default=0)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    out = a.out or os.path.join(_RAIZ, 'datos',
                                time.strftime('conformado_%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)
    resumen = dict(n=a.n, semilla=a.semilla, familias=[f[0] for f in FAMILIAS])
    t0 = time.perf_counter()

    if a.solo in ('nicholson', 'ambos'):
        print('=== A. ruido ANTES del conformador: S/N relativo al cusp ===')
        rng = np.random.default_rng(a.semilla)
        resumen['nicholson'] = experimento_nicholson(a.n, rng)
        p = fig_nicholson(resumen['nicholson'], out)
        print(f'  figura: {os.path.relpath(p)}   [{time.perf_counter()-t0:.0f} s]\n')

    if a.solo in ('adc', 'ambos'):
        print('=== B. ruido EN EL ADC: fase, estimador y familia ===')
        rng = np.random.default_rng(a.semilla + 1)
        resumen['adc'] = experimento_adc(a.n, rng, a.amplitud, a.sigma)
        p = fig_adc(resumen['adc'], out)
        print(f'  figura: {os.path.relpath(p)}   [{time.perf_counter()-t0:.0f} s]\n')

    if 'nicholson' in resumen and 'adc' in resumen:
        print('=== orden de mérito (mejor arriba) ===')
        fa = sorted(resumen['nicholson']['filas'], key=lambda r: -r['sn_teo'])
        fb = sorted(resumen['adc']['filas'], key=lambda r: r['pico']['sigma'])
        fc = sorted(resumen['adc']['filas'], key=lambda r: r['adaptado']['sigma'])
        print(f'  {"A: preamp (S/N)":<24} {"B: ADC, pico del RTL (σ)":<28} '
              f'{"B: ADC, filtro adaptado (σ)":<28}')
        for ra, rb, rc in zip(fa, fb, fc):
            print(f'  {ra["etiqueta"]:<12} {ra["sn_teo"]:<11.3f} '
                  f'{rb["etiqueta"]:<12} {rb["pico"]["sigma"]:<15.2f} '
                  f'{rc["etiqueta"]:<12} {rc["adaptado"]["sigma"]:<15.2f}')

    with open(os.path.join(out, 'resumen.json'), 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=float)
    print(f'\nlisto en {time.perf_counter()-t0:.0f} s -> {os.path.relpath(out)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
