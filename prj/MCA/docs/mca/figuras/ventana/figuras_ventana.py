#!/usr/bin/env python3
"""Figuras de las dos metodologías de ventana de medición, para
`../../ventana_de_medicion.md`.

La ventana es lo que convierte un flujo de muestras en *un* evento: cuándo
empieza a integrar, cuándo deja de integrar, y qué parte de eso es la cola.
Hay dos reglas de cierre en el RTL (`cfg_gate_mode` en
[`mca_pulse_feature.sv`](../../../../modulos/mca/rtl/mca_pulse_feature.sv)) y
las figuras muestran las dos sobre la misma forma de pulso, con los mismos
registros, para que la comparación sea de la regla y no del estímulo.

Misma convención que [`../figuras_resolucion.py`](../figuras_resolucion.py):
sin texto adentro, sólo ejes, leyenda y las marcas imprescindibles. Paleta y
rcParams se importan de ahí. Son **esquemas**: la forma del pulso es el modelo
de subida y cola exponenciales, con los parámetros elegidos para reproducir el
largo de ventana medido en la placa (779 muestras en modo histéresis). Los
únicos números medidos que aparecen son los que cita el documento, y están en
los epígrafes, no dentro de los gráficos.

  01_ventana_histeresis.png
      (a) El pulso con `cfg_thr` y `cfg_thr − cfg_hyst`, la ventana que abre
          en el cruce de subida y cierra en el cruce de bajada, el pico, el
          arranque de la cola a `t_pico + cfg_tail_dly` y dónde estaría
          `cfg_maxlen`.
      (b) El cronograma de la FSM: los dos comparadores, `armed`, `S_ACTIVE`,
          `in_tail` y `close_hyst`, con la misma escala de tiempo que (a).

  02_ventana_fija.png
      (a) El mismo pulso con `cfg_gate_mode = 1`: cierre a `cfg_gate_long`
          muestras del disparo y cola desde `cfg_gate_short`, las dos medidas
          desde el DISPARO. Al cerrar, el pulso sigue arriba de `thr_lo`, que
          es por lo que la regla ingenua de apilamiento —"si al cerrar sigue
          alto, está apilado"— marcaría el 100 % de los eventos limpios.
      (b) El apilamiento que la regla real SÍ marca: primer pulso chico, la
          cola baja de `thr_lo` dentro de la compuerta y el segundo vuelve a
          cruzar `cfg_thr`.
      (c) El que NO marca: primer pulso de la línea, el segundo monta sobre
          una cola que nunca bajó de `thr_lo`, así que `gate_2nd` queda en 0.
      (d) El cronograma de `gate_rearm` y `gate_2nd` de los dos casos.

  03_quien_decide_el_cierre.png
      (a) |dV/dt| a lo largo del pulso, con la pendiente en el cruce de
          apertura y en el de cierre: tres órdenes de magnitud de diferencia,
          y el mismo σ_v del ADC se traduce en σ_t muy distinto.
      (b) Monte Carlo del instante de cierre con ruido blanco del ADC: en
          modo 0 es una distribución de varias muestras de ancho; en modo 1
          es una delta.
      (c) El histograma de `Q_total` que sale de ese Monte Carlo para los dos
          modos, con la resolución en %.

  04_amplitude_walk.png
      (a) Tres amplitudes con el mismo instante de arribo: el cruce de un
          umbral fijo se adelanta al crecer la amplitud.
      (b) El corrimiento del cruce contra la amplitud, la estimación de
          rampa lineal `t_r·thr/(0.8·A)` —que para una subida exponencial
          es una cota superior—, el σ_t del ruido y el Ts/2 del muestreo:
          el walk es sistemático y domina sobre los dos.
      (c) Qué le hace al MCA: en modo 0 el largo de la ventana crece con el
          logaritmo de la amplitud, así que `Q/pico` no es constante; en
          modo 1 el largo no depende de la amplitud.

  05_walk_tres_pulsos.png
      (a) Las tres ondas ENTERAS, del arribo al cierre, con el instante en
          que el sistema declara cada evento y con el Δt entre los cierres,
          que a esta escala se mide en µs.
      (b) El zoom sobre el flanco, con la grilla de muestreo del ADC: el Δt
          entre los disparos, que se mide en ns y son 4.9 muestras para todo
          el rango de amplitudes.

    python3 figuras_ventana.py [--out DIR]
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_AQUI))

from figuras_resolucion import (TINTA, TINTA2, MUDO, GRILLA,   # noqa: E402
                                AZUL, NARAN, ROJO, RAMPA,
                                _limpiar, _panel)

VERDE = '#3a9a5c'          # la compuerta fija, cuando compite contra histéresis

# --- la plataforma ----------------------------------------------------------
TS = 8.0                   # ns por muestra, 125 MSPS
SIGMA_V = 2.8              # cuentas rms, ruido ADC + front-end medido

# --- los registros, con los defaults de mca_top.sv -------------------------
THR = 100                  # cfg_thr
HYST = 50                  # cfg_hyst  -> thr_lo = 50
THR_LO = THR - HYST
MAXLEN = 1024              # cfg_maxlen (sólo actúa en modo 0)
TAIL_DLY = 4               # cfg_tail_dly
GATE_SHORT = 32            # cfg_gate_short
GATE_LONG = 384            # cfg_gate_long

# --- la forma del pulso ----------------------------------------------------
# Subida exponencial de tiempo 10-90 % = T_R y cola exponencial TAU_D. TAU_D
# está elegido para que el cierre por histéresis caiga en las ~779 muestras
# medidas en la placa con A = 1920 cuentas (ver apilamiento.md §3).
T_R = 100.0                # ns, 10-90 %
TAU_D = 1650.0             # ns
A_REF = 1920.0             # cuentas, la amplitud de la campaña


def _tau_subida(t_r):
    """Constante de la subida exponencial para un 10-90 % dado."""
    return t_r / np.log(9.0)


def forma(t_ns, t_r=T_R, tau=TAU_D):
    """Forma unitaria (pico = 1) en función del tiempo en ns desde el arribo."""
    a = _tau_subida(t_r)
    y = np.where(t_ns > 0.0,
                 (1.0 - np.exp(-np.clip(t_ns, 0, None) / a))
                 * np.exp(-np.clip(t_ns, 0, None) / tau),
                 0.0)
    return y / _pico(t_r, tau)


def dforma(t_ns, t_r=T_R, tau=TAU_D):
    """Derivada de `forma`, analítica, en unidades de 1/ns."""
    a = _tau_subida(t_r)
    tt = np.clip(t_ns, 0, None)
    d = (np.exp(-tt / a) / a - (1.0 - np.exp(-tt / a)) / tau) * np.exp(-tt / tau)
    return np.where(t_ns > 0.0, d, 0.0) / _pico(t_r, tau)


_PICO_CACHE = {}


def _pico(t_r, tau):
    """Máximo de la forma sin normalizar, cacheado."""
    k = (t_r, tau)
    if k not in _PICO_CACHE:
        a = _tau_subida(t_r)
        t = np.linspace(0.0, 20.0 * a, 200001)
        _PICO_CACHE[k] = float(((1.0 - np.exp(-t / a)) * np.exp(-t / tau)).max())
    return _PICO_CACHE[k]


def t_pico(t_r=T_R, tau=TAU_D):
    """Instante del máximo, en ns desde el arribo. Analítico."""
    a = _tau_subida(t_r)
    return a * np.log(1.0 + tau / a)


def cruces(amp, nivel_hi=THR, nivel_lo=THR_LO, t_r=T_R, tau=TAU_D):
    """(t_subida, t_bajada) en ns: cruce de nivel_hi subiendo y de nivel_lo
    bajando, sobre la forma continua. Interpolación lineal en una malla fina."""
    t = np.linspace(0.0, 30.0 * tau, 400001)
    y = amp * forma(t, t_r, tau)
    tp = t_pico(t_r, tau)
    sube = t <= tp
    baja = t >= tp
    t_hi = np.interp(nivel_hi, y[sube], t[sube])
    t_lo = np.interp(-nivel_lo, -y[baja], t[baja])
    return t_hi, t_lo


def largo_histeresis(amp, **kw):
    """Largo de la ventana de modo 0, en muestras, sin ruido."""
    t_hi, t_lo = cruces(amp, **kw)
    return (t_lo - t_hi) / TS


# =============================================================================
# Utilidades de dibujo
# =============================================================================

def _eje_muestras(ax, lo, hi, origen='el disparo'):
    """Eje x en muestras, con un eje gemelo arriba en µs."""
    ax.set_xlim(lo, hi)
    sec = ax.secondary_xaxis('top', functions=(lambda s: s * TS / 1e3,
                                               lambda u: u * 1e3 / TS))
    sec.set_xlabel(f'µs desde {origen}')
    return sec


def _fila(ax, y0, t, v, color, alto=0.62):
    """Una señal digital del cronograma, en la fila y0."""
    ax.step(t, y0 + alto * np.asarray(v, float), where='post',
            color=color, lw=1.3)


def _cronograma(ax, nombres, t, señales, colores):
    """Dibuja len(nombres) filas digitales de abajo hacia arriba."""
    for i, (v, c) in enumerate(zip(señales, colores)):
        y0 = len(nombres) - 1 - i
        ax.axhline(y0, color=GRILLA, lw=0.6, zorder=0)
        _fila(ax, y0, t, v, c)
    ax.set_yticks(np.arange(len(nombres))[::-1])
    ax.set_yticklabels(nombres, fontsize=8.5, color=TINTA2,
                       fontfamily='monospace')
    ax.set_ylim(-0.4, len(nombres) - 0.2)
    ax.grid(False)
    _limpiar(ax)


# =============================================================================
# 1. La ventana por histéresis
# =============================================================================
def fig_histeresis(out):
    n0, n1 = -120, 1120
    t = np.arange(n0, n1, 0.25)                       # muestras
    y = A_REF * forma(t * TS)

    t_hi, t_lo = cruces(A_REF)
    s_hi, s_lo = t_hi / TS, t_lo / TS                 # en muestras
    s_pk = t_pico() / TS
    s_cola = s_pk + TAIL_DLY

    fig, (ax, axc) = plt.subplots(2, 1, figsize=(7.8, 5.8), sharex=True,
                                  layout='constrained',
                                  gridspec_kw={'height_ratios': [2.3, 1.25]})

    # --- (a) la señal y la ventana
    ax.axvspan(s_hi, s_lo, color=AZUL, alpha=0.10, lw=0,
               label='ventana abierta ($Q_{tot}$)')
    ax.fill_between(t, 0, y, where=(t >= s_cola) & (t <= s_lo),
                    facecolor='none', edgecolor=NARAN, hatch='///',
                    lw=0.0, label='cola ($Q_{cola}$)')
    ax.plot(t, y, color=AZUL, lw=1.5, label='pulso (línea de base restada)')
    ax.axhline(THR, color=TINTA2, lw=1.1, ls='--', label='cfg_thr')
    ax.axhline(THR_LO, color=ROJO, lw=1.1, ls=':',
               label='cfg_thr − cfg_hyst')
    ax.axvline(MAXLEN, color=MUDO, lw=1.1, ls='-.', label='cfg_maxlen')
    ax.plot([s_hi, s_lo], [THR, THR_LO], 'o', ms=5.5, color=ROJO, zorder=6,
            label='apertura / cierre')
    ax.axvline(s_pk, color=TINTA2, lw=0.9, ls=':', zorder=1)

    ax.add_patch(FancyArrowPatch((s_hi, 0.80 * A_REF), (s_lo, 0.80 * A_REF),
                                 arrowstyle='<|-|>', mutation_scale=9, lw=1.3,
                                 color=TINTA, shrinkA=0, shrinkB=0, zorder=6))
    ax.annotate(f'F_LEN = {s_lo - s_hi:.0f}', ((s_hi + s_lo) / 2, 0.82 * A_REF),
                ha='center', va='bottom', color=TINTA, fontweight='bold')

    ax.set_ylabel('Cuentas sobre la base')
    ax.set_ylim(-0.06 * A_REF, 1.12 * A_REF)
    ax.legend(loc='center right', fontsize=8.5)
    _limpiar(ax)
    _panel(ax, 'a')
    _eje_muestras(ax, n0, n1)

    # --- (b) el cronograma de la FSM
    td = np.arange(n0, n1, 1.0)
    yd = A_REF * forma(td * TS)
    c_hi = (yd >= THR).astype(float)
    c_lo = (yd < THR_LO).astype(float)
    activo = ((td >= s_hi) & (td < s_lo)).astype(float)
    armado = np.ones_like(td)
    armado[(td >= s_hi) & (td < s_lo)] = 0.0          # se limpia al abrir
    cola = ((td >= s_cola) & (td < s_lo)).astype(float)
    cierre = ((td >= s_lo) & (td < s_lo + 1)).astype(float)

    _cronograma(axc,
                ['x >= thr_hi', 'x < thr_lo', 'armed', 'S_ACTIVE',
                 'in_tail', 'close_hyst'],
                td, [c_hi, c_lo, armado, activo, cola, cierre],
                [TINTA2, ROJO, MUDO, AZUL, NARAN, ROJO])
    axc.set_xlabel('Muestras (Ts = 8 ns)')
    _panel(axc, 'b')

    fig.savefig(os.path.join(out, '01_ventana_histeresis.png'))
    plt.close(fig)
    return s_lo - s_hi


# =============================================================================
# 2. La ventana de compuertas fijas
# =============================================================================
def _flags_modo1(td, yd):
    """Réplica de gate_rearm / gate_2nd / gate_pileup sobre una señal muestreada
    ya referida al disparo (td en muestras, 0 = primera muestra >= thr_hi)."""
    rearm = np.zeros_like(td)
    seg = np.zeros_like(td)
    pile = np.zeros_like(td)
    r = s = False
    for i, (n, x) in enumerate(zip(td, yd)):
        if 0 <= n < GATE_LONG:
            if x < THR_LO:
                r = True
            elif r and x >= THR:
                s = True
        rearm[i] = 1.0 if (r and 0 <= n < GATE_LONG) else 0.0
        seg[i] = 1.0 if (s and 0 <= n < GATE_LONG) else 0.0
        pile[i] = 1.0 if (s and GATE_LONG <= n < GATE_LONG + 1) else 0.0
    return rearm, seg, pile


def _caso_dos_pulsos(td, a1, a2, s2):
    """Dos pulsos de amplitudes a1 y a2 separados s2 muestras, con el DISPARO
    del primero —el cruce de cfg_thr, no el arribo— en td = 0."""
    d = cruces(a1)[0] / TS
    return a1 * forma((td + d) * TS) + a2 * forma((td + d - s2) * TS)


def fig_fija(out):
    n0, n1 = -60, 560
    t = np.arange(n0, n1, 0.25)
    td = np.arange(n0, n1, 1.0)

    fig = plt.figure(figsize=(7.8, 9.4), layout='constrained')
    gs = fig.add_gridspec(4, 1, height_ratios=[2.0, 1.7, 1.7, 1.35])
    ax_a = fig.add_subplot(gs[0])
    ax_b = fig.add_subplot(gs[1])
    ax_c = fig.add_subplot(gs[2], sharex=ax_b)
    ax_d = fig.add_subplot(gs[3], sharex=ax_b)

    # --- (a) un pulso solo: las dos compuertas
    y = A_REF * forma(t * TS)
    ax_a.axvspan(0, GATE_SHORT, color=AZUL, alpha=0.12, lw=0,
                 label='hasta cfg_gate_short')
    ax_a.axvspan(GATE_SHORT, GATE_LONG, color=NARAN, alpha=0.13, lw=0,
                 label='cola, hasta cfg_gate_long')
    ax_a.plot(t, y, color=AZUL, lw=1.5)
    ax_a.axhline(THR, color=TINTA2, lw=1.1, ls='--', label='cfg_thr')
    ax_a.axhline(THR_LO, color=ROJO, lw=1.1, ls=':', label='cfg_thr − cfg_hyst')
    ax_a.plot([0], [THR], 'o', ms=5.5, color=ROJO, zorder=6,
              label='disparo')
    y_cierre = float(A_REF * forma(np.array([GATE_LONG * TS]))[0])
    ax_a.plot([GATE_LONG], [y_cierre], 'o', ms=5.5, color=VERDE, zorder=6,
              label='cierre, fijo desde el disparo')

    ax_a.add_patch(FancyArrowPatch((GATE_LONG, y_cierre), (GATE_LONG, THR_LO),
                                   arrowstyle='<|-|>', mutation_scale=8, lw=1.2,
                                   color=ROJO, shrinkA=0, shrinkB=0, zorder=6))
    ax_a.annotate(f'al cerrar le faltan '
                  f'{largo_histeresis(A_REF) - GATE_LONG:.0f} muestras\n'
                  'para bajar de thr_lo',
                  (GATE_LONG, y_cierre), xytext=(-20, 42),
                  textcoords='offset points', fontsize=8.5, color=ROJO,
                  ha='right', va='center')

    ax_a.set_ylabel('Cuentas')
    ax_a.set_xlim(n0, n1)
    ax_a.set_ylim(-0.06 * A_REF, 1.14 * A_REF)
    ax_a.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_a)
    _panel(ax_a, 'a')
    _eje_muestras(ax_a, n0, n1)

    # --- (b) apilamiento que SÍ marca: primer pulso chico
    a1b, a2b, s2b = 200.0, 900.0, 330.0
    yb = _caso_dos_pulsos(t, a1b, a2b, s2b)
    ydb = _caso_dos_pulsos(td, a1b, a2b, s2b)
    rearm_b, seg_b, _ = _flags_modo1(td, ydb)

    # --- (c) apilamiento que NO marca: primer pulso de la línea
    a1c, a2c, s2c = A_REF, 0.75 * A_REF, 250.0
    yc = _caso_dos_pulsos(t, a1c, a2c, s2c)
    ydc = _caso_dos_pulsos(td, a1c, a2c, s2c)
    rearm_c, seg_c, _ = _flags_modo1(td, ydc)

    for ax, letra, yy, yd, rr, ss, lab in (
            (ax_b, 'b', yb, ydb, rearm_b, seg_b, 'gate_2nd = 1 → apilado'),
            (ax_c, 'c', yc, ydc, rearm_c, seg_c, 'gate_2nd = 0 → se histogramea')):
        ax.axvspan(0, GATE_LONG, color=NARAN, alpha=0.10, lw=0)
        ax.plot(t, yy, color=AZUL, lw=1.5, label=lab)
        ax.axhline(THR, color=TINTA2, lw=1.1, ls='--')
        ax.axhline(THR_LO, color=ROJO, lw=1.1, ls=':')
        if rr.any():
            i = int(np.argmax(rr > 0))
            ax.plot([td[i]], [yd[i]], 'o', ms=5.5, color=VERDE, zorder=6,
                    label='bajó de thr_lo (gate_rearm)')
        if ss.any():
            i = int(np.argmax(ss > 0))
            ax.plot([td[i]], [yd[i]], 'o', ms=5.5, color=ROJO, zorder=6,
                    label='volvió a cruzar cfg_thr (gate_2nd)')
        ax.set_ylabel('Cuentas')
        top = 1.30 * max(yy.max(), THR)
        ax.set_ylim(-0.06 * top, 1.14 * top)
        ax.legend(loc='upper right', fontsize=8.5)
        _limpiar(ax)
        _panel(ax, letra)

    # --- (d) los flags de los dos casos
    _cronograma(ax_d,
                ['gate_rearm (b)', 'gate_2nd (b)',
                 'gate_rearm (c)', 'gate_2nd (c)'],
                td, [rearm_b, seg_b, rearm_c, seg_c],
                [VERDE, ROJO, VERDE, ROJO])
    ax_d.axvspan(0, GATE_LONG, color=NARAN, alpha=0.10, lw=0, zorder=0)
    ax_d.set_xlabel('Muestras desde el disparo (Ts = 8 ns)')
    ax_d.set_xlim(n0, n1)
    _panel(ax_d, 'd')

    fig.savefig(os.path.join(out, '02_ventana_fija.png'))
    plt.close(fig)
    return (a1b, a2b, s2b, bool(seg_b.any())), (a1c, a2c, s2c, bool(seg_c.any()))


# =============================================================================
# 3. Quién decide el cierre: Monte Carlo con el ruido del ADC
# =============================================================================
def monte_carlo(n_ev=4000, semilla=20261003):
    """Para cada evento: muestrea el pulso con fase al azar y ruido blanco,
    y cierra por histéresis y por compuerta fija. Devuelve el índice de cierre
    y Q_total de cada modo, en muestras y cuentas."""
    rng = np.random.default_rng(semilla)
    n = 1400
    t_hi, _ = cruces(A_REF)
    idx = np.arange(n)

    cierre0 = np.empty(n_ev)
    q0 = np.empty(n_ev)
    cierre1 = np.empty(n_ev)
    q1 = np.empty(n_ev)

    for k in range(n_ev):
        # fase de muestreo uniforme en un Ts, pulso arrancando en -t_hi
        fase = rng.uniform(0.0, TS)
        y = A_REF * forma(idx * TS + fase - t_hi) \
            + rng.normal(0.0, SIGMA_V, n)
        xc = np.clip(y, 0.0, None)

        disp = int(np.argmax(y >= THR))              # primera muestra >= thr_hi
        pk = disp + int(np.argmax(y[disp:disp + 400]))
        baja = np.nonzero(y[pk:] < THR_LO)[0]
        fin0 = pk + int(baja[0]) if baja.size else n - 1
        fin1 = min(disp + GATE_LONG, n - 1)

        cierre0[k] = fin0 - disp
        cierre1[k] = fin1 - disp
        q0[k] = xc[disp:fin0].sum()
        q1[k] = xc[disp:fin1].sum()

    return cierre0, q0, cierre1, q1


def fig_cierre(out, mc):
    cierre0, q0, cierre1, q1 = mc
    fig = plt.figure(figsize=(7.8, 6.2), layout='constrained')
    gs = fig.add_gridspec(2, 2)
    ax_a = fig.add_subplot(gs[0, :])
    ax_b = fig.add_subplot(gs[1, 0])
    ax_c = fig.add_subplot(gs[1, 1])

    # --- (a) la pendiente a lo largo del pulso
    t_hi, t_lo = cruces(A_REF)
    s = np.logspace(np.log10(0.02), np.log10(1100), 6000)
    dy = np.abs(np.gradient(A_REF * forma(s * TS), s * TS))   # cuentas/ns
    ax_a.loglog(s, dy, color=AZUL, lw=1.5, label='|dV/dt| del pulso')
    for sx, col, lab in ((t_hi / TS, TINTA2, 'apertura (flanco)'),
                         (t_lo / TS, ROJO, 'cierre por histéresis')):
        p = float(np.interp(sx, s, dy))
        ax_a.plot([sx], [p], 'o', ms=6, color=col, zorder=6,
                  label=f'{lab}: σ_t = {SIGMA_V / p:.2g} ns')
    ax_a.axvline(t_pico() / TS, color=TINTA2, lw=0.9, ls=':', zorder=1,
                 label='pico (dV/dt = 0)')
    ax_a.set_xlabel('Muestras desde el arribo')
    ax_a.set_ylabel('|dV/dt| [cuentas/ns]')
    ax_a.set_ylim(1e-3, 2e2)
    ax_a.legend(loc='lower left', fontsize=8.5)
    _limpiar(ax_a)
    _panel(ax_a, 'a')

    # --- (b) el instante de cierre
    ax_b.hist(cierre0, bins=40, color=ROJO, alpha=0.85, lw=0,
              label=f'modo 0: σ = {cierre0.std():.1f} muestras')
    ax_b.axvline(cierre1.mean(), color=VERDE, lw=2.0,
                 label='modo 1: σ = 0')
    ax_b.set_xlabel('Largo de la ventana [muestras]')
    ax_b.set_ylabel('Eventos')
    ax_b.legend(loc='upper left', fontsize=8.5)
    _limpiar(ax_b)
    _panel(ax_b, 'b')

    # --- (c) Q_total
    for q, col, lab in ((q0, ROJO, 'modo 0 (histéresis)'),
                        (q1, VERDE, 'modo 1 (compuerta fija)')):
        r = 100.0 * q.std() / q.mean()
        ax_c.hist(q / q.mean(), bins=60, histtype='step', lw=1.6, color=col,
                  label=f'{lab}: {r:.3f} %')
    ax_c.set_xlabel('$Q_{tot}$ / media')
    ax_c.set_ylabel('Eventos')
    ax_c.set_ylim(top=1.45 * ax_c.get_ylim()[1])
    ax_c.legend(loc='upper left', fontsize=8.5)
    _limpiar(ax_c)
    _panel(ax_c, 'c')

    fig.savefig(os.path.join(out, '03_quien_decide_el_cierre.png'))
    plt.close(fig)


# =============================================================================
# 4. Amplitude walk
# =============================================================================
def fig_walk(out):
    fig = plt.figure(figsize=(7.8, 6.4), layout='constrained')
    gs = fig.add_gridspec(2, 2)
    ax_a = fig.add_subplot(gs[0, :])
    ax_b = fig.add_subplot(gs[1, 0])
    ax_c = fig.add_subplot(gs[1, 1])

    # --- (a) tres amplitudes, mismo arribo
    amps = [150.0, 400.0, 1600.0]
    t = np.linspace(-2.0, 60.0, 3000)                # ns desde el arribo
    for a, col in zip(amps, (RAMPA[0], RAMPA[2], RAMPA[4])):
        y = a * forma(t)
        ax_a.plot(t, y, color=col, lw=1.6, label=f'A = {a:.0f} cuentas')
        t_hi, _ = cruces(a)
        ax_a.plot([t_hi], [THR], 'o', ms=6, color=col, zorder=6)
        ax_a.plot([t_hi, t_hi], [0, THR], color=col, lw=0.8, ls=':')
    ax_a.axhline(THR, color=TINTA2, lw=1.1, ls='--', label='cfg_thr')
    t_chico, _ = cruces(amps[0])
    t_grande, _ = cruces(amps[-1])
    ax_a.add_patch(FancyArrowPatch((t_grande, 0.45 * THR), (t_chico, 0.45 * THR),
                                   arrowstyle='<|-|>', mutation_scale=9, lw=1.3,
                                   color=ROJO, shrinkA=0, shrinkB=0, zorder=7))
    ax_a.annotate(f'walk = {t_chico - t_grande:.0f} ns',
                  ((t_chico + t_grande) / 2, 0.42 * THR), ha='center',
                  va='top', color=ROJO, fontweight='bold')
    ax_a.set_xlabel('ns desde el arribo')
    ax_a.set_ylabel('Cuentas')
    ax_a.set_ylim(0, 2.6 * THR)
    ax_a.set_xlim(-2, 60)
    ax_a.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax_a)
    _panel(ax_a, 'a')

    # --- (b) el corrimiento contra la amplitud
    a = np.logspace(np.log10(1.15 * THR), np.log10(8000.0), 400)
    tc = np.array([cruces(ai)[0] for ai in a])
    ax_b.loglog(a, tc, color=AZUL, lw=1.6, label='walk (modelo exacto)')
    ax_b.loglog(a, T_R * THR / (0.8 * a), color=NARAN, lw=1.3, ls='--',
                label=r'$t_r\,thr/(0.8A)$, rampa lineal')
    # el ruido en el flanco: sigma_v dividido la pendiente EN SU PROPIO cruce
    pend = a * dforma(tc)
    ax_b.loglog(a, SIGMA_V / np.abs(pend), color=ROJO, lw=1.3, ls=':',
                label='σ_t del ruido')
    ax_b.axhline(TS / 2, color=MUDO, lw=1.2, ls='-.', label='Ts/2')
    ax_b.set_xlabel('Amplitud [cuentas]')
    ax_b.set_ylabel('ns')
    ax_b.legend(loc='lower left', fontsize=8.0)
    _limpiar(ax_b)
    _panel(ax_b, 'b')

    # --- (c) qué le hace a la ventana del modo 0
    a2 = np.logspace(np.log10(200.0), np.log10(8000.0), 160)
    largo = np.array([largo_histeresis(ai) for ai in a2])
    ax_c.semilogx(a2, largo, color=ROJO, lw=1.6, label='modo 0: F_LEN(A)')
    ax_c.axhline(GATE_LONG, color=VERDE, lw=1.6, label='modo 1: cfg_gate_long')
    ax_c.set_xlabel('Amplitud [cuentas]')
    ax_c.set_ylabel('Largo de ventana [muestras]')
    _limpiar(ax_c)
    _panel(ax_c, 'c')

    ax_q = ax_c.twinx()
    q_pico = np.array([_q_pico(ai) for ai in a2])
    q_pico = q_pico / q_pico[0]
    ax_q.semilogx(a2, q_pico, color=TINTA, lw=1.3, ls='--',
                  label='$Q_{tot}$/pico, normalizado')
    ax_q.set_ylabel('$Q_{tot}$/pico (norm.)', color=TINTA)
    ax_q.grid(False)
    h1, l1 = ax_c.get_legend_handles_labels()
    h2, l2 = ax_q.get_legend_handles_labels()
    ax_c.legend(h1 + h2, l1 + l2, loc='lower right', fontsize=8.0)

    fig.savefig(os.path.join(out, '04_amplitude_walk.png'))
    plt.close(fig)
    return a2, largo, q_pico


def _q_pico(amp):
    """Q_total/pico de la ventana de modo 0, sin ruido: el cociente que el
    discriminador de forma usa como eje, y que NO es constante."""
    t_hi, t_lo = cruces(amp)
    t = np.arange(t_hi, t_lo, TS)
    return (amp * forma(t)).sum() / amp


# =============================================================================
# 5. Los tres pulsos enteros, y el Δt entre sus disparos
# =============================================================================
AMPS_WALK = (150.0, 400.0, 1600.0)


def fig_tres_pulsos(out, amps=AMPS_WALK):
    """Las tres ondas completas, de la línea de base al cierre, con el Δt entre
    los instantes en que el sistema declara el evento. El walk vive en ns y los
    pulsos en µs: por eso hace falta el zoom."""
    t_hi = np.array([cruces(a)[0] for a in amps])          # ns, disparo
    t_lo = np.array([cruces(a)[1] for a in amps])          # ns, cierre modo 0
    s_hi, s_lo = t_hi / TS, t_lo / TS                      # en muestras

    n0, n1 = -60.0, 1.06 * s_lo.max()
    t = np.linspace(n0, n1, 8000)
    cols = (RAMPA[0], RAMPA[2], RAMPA[4])

    fig, (ax, axz) = plt.subplots(2, 1, figsize=(7.8, 7.0),
                                  layout='constrained',
                                  gridspec_kw={'height_ratios': [1.0, 1.0]})

    # --- (a) las tres ondas enteras, de la base al cierre
    for a, col in zip(amps, cols):
        ax.plot(t, a * forma(t * TS), color=col, lw=1.6,
                label=f'A = {a:.0f} cuentas')
    ax.axhline(THR, color=TINTA2, lw=1.1, ls='--', label='cfg_thr')
    ax.axhline(THR_LO, color=ROJO, lw=1.1, ls=':', label='cfg_thr − cfg_hyst')
    for sh, sl, col in zip(s_hi, s_lo, cols):
        ax.plot([sh], [THR], 'o', ms=6, color=col, zorder=7)
        ax.plot([sl], [THR_LO], 'o', ms=6, mfc='none', mew=1.6, color=col,
                zorder=7)
    ax.plot([], [], 'o', ms=6, color=MUDO, label='disparo (evento declarado)')
    ax.plot([], [], 'o', ms=6, mfc='none', mew=1.6, color=MUDO,
            label='cierre por histéresis')
    ax.axvspan(-0.6, 1.25 * s_hi.max(), color=ROJO, alpha=0.16, lw=0,
               label='el zoom de (b)')

    # el Δt del CIERRE, que en la misma figura se mide en µs
    y_c = 0.42 * max(amps)
    ax.add_patch(FancyArrowPatch((s_lo[0], y_c), (s_lo[-1], y_c),
                                 arrowstyle='<|-|>', mutation_scale=9, lw=1.3,
                                 color=ROJO, shrinkA=0, shrinkB=0, zorder=7))
    ax.annotate(f'Δt cierre = {(t_lo[-1] - t_lo[0]) / 1e3:.2f} µs',
                ((s_lo[0] + s_lo[-1]) / 2, y_c), xytext=(0, 6),
                textcoords='offset points', ha='center', va='bottom',
                color=ROJO, fontweight='bold')

    ax.set_xlabel('Muestras (Ts = 8 ns)')
    ax.set_ylabel('Cuentas sobre la base')
    ax.set_xlim(n0, n1)
    ax.set_ylim(-0.03 * max(amps), 1.16 * max(amps))
    ax.legend(loc='upper right', fontsize=8.5)
    _limpiar(ax)
    _panel(ax, 'a')
    _eje_muestras(ax, n0, n1, origen='el arribo')

    # --- (b) el zoom: el Δt de los DISPAROS, cinco muestras para todo el rango
    z0, z1 = -0.6, 1.25 * s_hi.max()
    tz = np.linspace(z0, z1, 3000)
    for n in range(int(np.ceil(z0)), int(z1) + 1):           # la grilla del ADC
        axz.axvline(n, color=GRILLA, lw=0.8, zorder=0)
    for a, col in zip(amps, cols):
        axz.plot(tz, a * forma(tz * TS), color=col, lw=1.8,
                 label=f'A = {a:.0f} cuentas')
    axz.axhline(THR, color=TINTA2, lw=1.1, ls='--')
    for sh, col in zip(s_hi, cols):
        axz.plot([sh], [THR], 'o', ms=6.5, color=col, zorder=7)
        axz.plot([sh, sh], [0, THR], color=col, lw=0.9, ls=':')

    for (i, j), frac in (((2, 1), 0.74), ((1, 0), 0.44)):
        y = frac * THR
        axz.add_patch(FancyArrowPatch((s_hi[i], y), (s_hi[j], y),
                                      arrowstyle='<|-|>', mutation_scale=8,
                                      lw=1.3, color=ROJO, shrinkA=0, shrinkB=0,
                                      zorder=7))
        axz.annotate(f'{t_hi[j] - t_hi[i]:.1f} ns',
                     ((s_hi[i] + s_hi[j]) / 2, y), xytext=(0, 4),
                     textcoords='offset points', ha='center', va='bottom',
                     fontsize=9, color=ROJO)
    y_d = 1.56 * THR
    axz.add_patch(FancyArrowPatch((s_hi[-1], y_d), (s_hi[0], y_d),
                                  arrowstyle='<|-|>', mutation_scale=9, lw=1.4,
                                  color=ROJO, shrinkA=0, shrinkB=0, zorder=7))
    axz.annotate(f'Δt disparo = {t_hi[0] - t_hi[-1]:.1f} ns = '
                 f'{(t_hi[0] - t_hi[-1]) / TS:.1f} muestras',
                 ((s_hi[0] + s_hi[-1]) / 2, y_d), xytext=(0, 6),
                 textcoords='offset points', ha='center', va='bottom',
                 color=ROJO, fontweight='bold')

    axz.set_xlim(z0, z1)
    axz.set_ylim(0, 2.15 * THR)
    axz.set_xlabel('Muestras desde el arribo (grilla = instantes del ADC)')
    axz.set_ylabel('Cuentas sobre la base')
    axz.legend(loc='upper left', fontsize=8.5)
    axz.grid(False)
    _limpiar(axz)
    _panel(axz, 'b')

    fig.savefig(os.path.join(out, '05_walk_tres_pulsos.png'))
    plt.close(fig)
    return amps, t_hi, t_lo


# =============================================================================
# Los números que cita el documento
# =============================================================================
def tabla(mc, walk, casos, tres):
    cierre0, q0, cierre1, q1 = mc
    a2, largo, q_pico = walk
    t_hi, t_lo = cruces(A_REF)

    print()
    print(f'forma del esquema: t_r = {T_R:.0f} ns (10-90 %), '
          f'tau_d = {TAU_D:.0f} ns, A = {A_REF:.0f} cuentas')
    print(f'  t_pico       {t_pico():8.1f} ns  ({t_pico()/TS:6.1f} muestras)')
    print(f'  cruce thr_hi {t_hi:8.1f} ns')
    print(f'  cruce thr_lo {t_lo:8.1f} ns')
    print(f'  F_LEN modo 0 {(t_lo-t_hi)/TS:8.1f} muestras '
          f'(medido en placa: 779)')
    print(f'  F_LEN modo 1 {GATE_LONG:8d} muestras')

    print()
    print(f'Monte Carlo, {cierre0.size} eventos, sólo ruido blanco '
          f'sigma_v = {SIGMA_V} cuentas')
    print('  modo                largo [muestras]      Q_tot      res [%]')
    for nom, c, q in (('0 histéresis', cierre0, q0),
                      ('1 compuerta ', cierre1, q1)):
        print(f'  {nom}   {c.mean():8.1f} ± {c.std():4.1f}   '
              f'{q.mean():10.0f}   {100*q.std()/q.mean():8.3f}')
    print('  medido sobre 7054 pulsos reales: 0.528 % y 0.149 %')
    print('  (la diferencia la pone el error de línea de base por el largo')
    print('   variable de la ventana, que el Monte Carlo no incluye)')

    print()
    print('apilamiento en modo 1: gate_2nd exige bajar de thr_lo DENTRO de la')
    print(f'compuerta ({GATE_LONG} muestras)')
    for nom, (a1, a2, s2, marcado) in zip(('b', 'c'), casos):
        print(f'  caso {nom}: A1 = {a1:6.0f}, A2 = {a2:6.0f}, dt = {s2:5.0f} '
              f'muestras; la cola de A1 cruza thr_lo en '
              f'{largo_histeresis(a1):4.0f}  ->  '
              f'{"MARCA" if marcado else "NO MARCA"}')

    print()
    print('walk del cruce de umbral y largo de ventana contra amplitud')
    print('   A [cuentas]   t_cruce [ns]   F_LEN [muestras]   Q/pico norm.')
    for ai in (200.0, 400.0, 800.0, 1920.0, 4000.0, 8000.0):
        tc = cruces(ai)[0]
        print(f'   {ai:9.0f}   {tc:12.1f}   {largo_histeresis(ai):16.0f}'
              f'   {_q_pico(ai)/_q_pico(200.0):13.3f}')
    amps, t_hi, t_lo = tres
    print()
    print('los tres pulsos de la figura 5, mismo instante de arribo')
    print('   A [cuentas]   disparo [ns]   cierre modo 0 [muestras]')
    for a, th, tl in zip(amps, t_hi, t_lo):
        print(f'   {a:9.0f}   {th:12.1f}   {tl/TS:22.0f}')
    print(f'  Delta t entre disparos: {t_hi[0]-t_hi[-1]:.1f} ns '
          f'({(t_hi[0]-t_hi[-1])/TS:.1f} muestras)')
    print(f'  Delta t entre cierres:  {(t_lo[-1]-t_lo[0])/1e3:.2f} us '
          f'({(t_lo[-1]-t_lo[0])/TS:.0f} muestras)')

    deriva = 100.0 * (q_pico[-1] / q_pico[0] - 1.0)
    print(f'  deriva de Q/pico de punta a punta del esquema: {deriva:.0f} %'
          '  (medida: 21 %)')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI, help='dónde dejar los PNG')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(f'figuras en {os.path.relpath(a.out)}:')
    fig_histeresis(a.out)
    print('  01_ventana_histeresis.png')
    casos = fig_fija(a.out)
    print('  02_ventana_fija.png')
    mc = monte_carlo()
    fig_cierre(a.out, mc)
    print('  03_quien_decide_el_cierre.png')
    walk = fig_walk(a.out)
    print('  04_amplitude_walk.png')
    tres = fig_tres_pulsos(a.out)
    print('  05_walk_tres_pulsos.png')
    tabla(mc, walk, casos, tres)


if __name__ == '__main__':
    main()
