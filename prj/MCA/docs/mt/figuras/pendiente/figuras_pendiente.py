#!/usr/bin/env python3
"""Figuras del procesamiento digital del disparo por pendiente (mt_slope_trig).

Las figuras 01 a 03 son el equivalente digital de los esquemas de Knoll
(cap. 16-17), donde la forma conformada sale como SUPERPOSICIÓN de copias
retardadas del mismo pulso. Las 05 a 07 ponen el filtro sobre pulsos de
detector y lo comparan contra el disparo de nivel.

Nada se dibuja a mano. Todas las curvas salen del modelo de referencia
`modulos/mt/modelos/python_model/mt_slope_model.py`, que hace la MISMA
recursión que el RTL (y el script verifica que coincide con la convolución
directa). Los disparos salen del mismo Schmitt, con su arranque silencioso.

Misma regla que el resto de las figuras del repo: sin prosa adentro, solo
ejes, leyenda y marcas. Lo que hay que decir va en `epigrafes.txt`, que
escribe este mismo script.

    python3 figuras_pendiente.py [--out DIR] [--rapido]
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
from matplotlib.ticker import MultipleLocator

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, '..', '..', '..', 'figuras'))
sys.path.insert(0, os.path.join(_AQUI, '..', '..', '..', '..', 'modulos', 'mt',
                                'modelos', 'python_model'))

from estilo import (SUP, TINTA, TINTA2, MUDO, AZUL, NARAN, RAMPA,  # noqa: E402
                    VERDE, MORADO, limpiar, panel, escribir_epigrafes)
import mt_slope_model as M                                          # noqa: E402

FS_MHZ = 125.0                  # adc_clk
TS_US = 1.0 / FS_MHZ            # una muestra, en µs

# Parámetros de los esquemas (chicos, para que se cuenten las muestras)
L_E, G_E = 4, 3

# Parámetros "de placa" para los pulsos de detector
L_P, G_P = 8, 4
SIGMA = 3                       # ruido del ADC, cuentas (medido: ~2.8)
TAU_R = 0.020                   # subida, µs
TAU_D = 1.14                    # cola, µs (la de figuras_trigger.py)
THR_NIVEL, HYST_NIVEL = 100, 40 # disparo de nivel, cuentas
LLD = 100                       # el umbral de pendiente equivale a 100 cuentas

EPIGRAFES = []


def guardar(fig, out, nombre, nota):
    fig.savefig(os.path.join(out, nombre), bbox_inches='tight')
    plt.close(fig)
    EPIGRAFES.append({'archivo': nombre, 'nota': nota})
    print(' ', nombre)


def verificar_modelo():
    """La recursión del RTL tiene que ser la convolución directa."""
    rng = np.random.default_rng(0)
    for L, G in ((1, 0), (4, 3), (8, 4), (16, 31)):
        x = rng.integers(-8192, 8192, 3000)
        assert np.array_equal(M.trapezoidal_rapido(x, L, G),
                              M.trapezoidal_directo(x, L, G)), (L, G)


# =============================================================================
# Pulsos de detector
# =============================================================================

def forma(u, tau_r=TAU_R):
    """Doble exponencial normalizada al pico; u en µs desde el arranque."""
    tp = tau_r * TAU_D / (TAU_D - tau_r) * np.log(TAU_D / tau_r)
    pico = np.exp(-tp / TAU_D) - np.exp(-tp / tau_r)
    with np.errstate(over='ignore'):
        y = np.exp(-u / TAU_D) - np.exp(-u / tau_r)
    return np.where(u > 0, y / pico, 0.0)


def senal(t, pulsos, base=0.0, sigma=SIGMA, rng=None, tau_r=TAU_R):
    """Muestras enteras: suma de pulsos (t0, A) + base + ruido."""
    y = np.full_like(t, base, dtype=float)
    for t0, A in pulsos:
        y += A * forma(t - t0, tau_r)
    if sigma and rng is not None:
        y += rng.normal(0.0, sigma, len(t))
    return np.round(y).astype(np.int64)


def umbral_pendiente(L, G, amplitud=LLD):
    """thr tal que un pulso de `amplitud` cuentas llega justo al umbral."""
    t = np.arange(0, 6.0, TS_US)
    s = M.trapezoidal_rapido(senal(t, [(1.0, amplitud)], sigma=0), L, G)
    return int(s.max())


# =============================================================================
# 01. Respuesta impulsiva y en frecuencia
# =============================================================================

def fig_respuesta(out):
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.2),
                               gridspec_kw={'width_ratios': [1, 1.25]})
    h = M.respuesta_impulsiva(L_E, G_E)
    k = np.arange(len(h))
    for kk, v in zip(k, h):
        c = AZUL if v > 0 else (NARAN if v < 0 else MUDO)
        a.plot([kk, kk], [0, v], color=c, lw=2)
        a.plot(kk, v, 'o', color=c, ms=7, mec=SUP, mew=1.5)
    a.axhline(0, color=MUDO, lw=0.8)
    a.set_xlabel('k (muestras)')
    a.set_ylabel('h[k]')
    a.set_xticks(k)
    a.set_ylim(-1.4, 1.4)
    panel(a, '(a)')
    limpiar(a)

    f = np.linspace(0, 0.5, 2001)                 # en unidades de fs
    for (L, G), c in zip(((1, 3), (4, 3), (8, 4), (16, 0)),
                         (RAMPA[0], RAMPA[1], RAMPA[3], VERDE)):
        hh = M.respuesta_impulsiva(L, G)
        H = np.abs(np.exp(-2j * np.pi * np.outer(f, np.arange(len(hh)))) @ hh)
        b.plot(f * FS_MHZ, H / L, color=c, lw=2, label=f'L={L}, G={G}')
    b.set_xlabel('frecuencia (MHz)')
    b.set_ylabel('|H(f)| / L')
    b.set_xlim(0, FS_MHZ / 2)
    b.legend(loc='upper right', fontsize=9)
    panel(b, '(b)')
    limpiar(b)
    fig.tight_layout()
    guardar(fig, out, '01_respuesta_impulsiva.png', f"""
(a) Respuesta impulsiva del trapezoidal rápido con L={L_E}, G={G_E}: L
coeficientes +1, G ceros y L coeficientes −1. Es todo el filtro: s[n] es la
suma de x pesada con esta ventana. Los coeficientes suman cero, y eso es lo
que hace que una continua dé s = 0.

(b) Módulo de la respuesta en frecuencia, normalizado por L (la ganancia para
un escalón). Todas las configuraciones tienen un cero en f = 0: el filtro es
un PASABANDA, no un pasabajos. L corre el pico hacia frecuencias más bajas y
lo hace más angosto (menos ruido), G desplaza el lóbulo. L=1, G=3 es la
diferencia de 4 muestras, x[n]−x[n−4]: deja pasar casi todo el ruido de alta
frecuencia, y por eso el trapezoidal promedia L muestras de cada lado.
""")


# =============================================================================
# 02. El trapecio como superposición de copias del mismo pulso (Knoll)
# =============================================================================

def fig_superposicion(out):
    L, G, A = L_E, G_E, 1
    n = np.arange(-3, 2 * L + G + 6)
    x = (n >= 0).astype(np.int64) * A
    xr = (n >= L + G).astype(np.int64) * A
    d = x - xr
    s = M.trapezoidal_rapido(x, L, G)            # el modelo, no a mano

    fig, ax = plt.subplots(4, 1, figsize=(8.0, 8.6), sharex=True,
                           gridspec_kw={'height_ratios': [1, 1, 1.9, 1.7]})
    w = 0.78

    a = ax[0]
    a.step(n, x, where='post', color=AZUL, lw=2, label='x[n]')
    a.step(n, -xr, where='post', color=NARAN, lw=2, label='−x[n−(L+G)]')
    a.axhline(0, color=MUDO, lw=0.8)
    a.set_ylim(-1.5, 1.5)
    a.legend(loc='lower left', ncol=2, fontsize=9)
    panel(a, '(a)')

    a = ax[1]
    a.bar(n, d, width=w, color=AZUL, edgecolor=SUP, linewidth=2)
    a.axhline(0, color=MUDO, lw=0.8)
    a.set_ylim(-0.2, 1.4)
    a.set_ylabel('d[n]')
    panel(a, '(b)')

    a = ax[2]
    paso = 1.5
    for i in range(L):
        di = np.roll(d, i)
        di[:i] = 0
        a.bar(n, di, width=w, bottom=i * paso, color=RAMPA[i],
              edgecolor=SUP, linewidth=2)
        a.axhline(i * paso, color=MUDO, lw=0.6)
    a.set_yticks([i * paso for i in range(L)])
    a.set_yticklabels([f'd[n−{i}]' if i else 'd[n]' for i in range(L)])
    a.set_ylim(-0.3, (L - 1) * paso + 1.4)
    a.grid(axis='y', visible=False)
    panel(a, '(c)')

    a = ax[3]
    base = np.zeros(len(n))
    for i in range(L):
        di = np.roll(d, i)
        di[:i] = 0
        a.bar(n, di, width=w, bottom=base, color=RAMPA[i],
              edgecolor=SUP, linewidth=2, label=f'd[n−{i}]' if i else 'd[n]')
        base += di
    a.plot(n, s, 'o', color=TINTA, ms=5, label='s[n] (modelo del RTL)')
    a.axhline(L * A, color=MUDO, lw=1, ls='--')
    a.set_ylim(0, L * A + 1.3)
    a.set_ylabel('s[n]')
    a.set_xlabel('n (muestras desde el escalón)')
    a.legend(loc='upper right', ncol=3, fontsize=8.5)
    panel(a, '(d)')

    assert np.array_equal(base.astype(np.int64), s)
    for a in ax:
        limpiar(a)
    ax[-1].xaxis.set_major_locator(MultipleLocator(2))
    fig.tight_layout()
    guardar(fig, out, '02_superposicion_escalon.png', f"""
El trapecio como superposición de copias del mismo pulso, el equivalente
digital de los esquemas de Knoll. L={L_E}, G={G_E}, escalón de alto 1.

(a) El escalón x[n] y una copia invertida y retardada L+G muestras.

(b) Su suma d[n] = x[n] − x[n−(L+G)]: un pulso rectangular de L+G muestras.
Ya rechaza la continua: lejos del escalón, x y su copia se cancelan.

(c) L copias de ese rectángulo, cada una retardada una muestra más.

(d) Apiladas, las L copias forman el trapecio: sube durante L muestras (va
entrando una copia por muestra), se queda en L·A durante G+1 muestras (están
todas) y baja durante L (van saliendo). La línea punteada es L·A. Los puntos
negros son s[n] calculado por la recursión del RTL, y coinciden con la pila
muestra a muestra (el script lo verifica). Es la misma cuenta que
s[n] = Σ x[n−i] − Σ x[n−L−G−i], reordenada.
""")


# =============================================================================
# 03. Cómo lo calcula el hardware: cuatro copias con signo y un acumulador
# =============================================================================

def fig_recursion(out):
    L, G, A = L_E, G_E, 1
    n = np.arange(-3, 2 * L + G + 6)
    x = (n >= 0).astype(np.int64) * A
    d = M.incremento(x, L, G)
    s = M.trapezoidal_rapido(x, L, G)

    fig, ax = plt.subplots(3, 1, figsize=(8.0, 7.2), sharex=True,
                           gridspec_kw={'height_ratios': [2.0, 1.1, 1.3]})
    a = ax[0]
    copias = ((0, +1, AZUL, 'x[n]'),
              (L, -1, NARAN, 'x[n−L]'),
              (L + G, -1, VERDE, 'x[n−L−G]'),
              (2 * L + G, +1, MORADO, 'x[n−2L−G]'))
    paso = 2.6
    for fila, (ret, signo, c, nombre) in enumerate(copias):
        y0 = (len(copias) - 1 - fila) * paso
        xi = (n >= ret).astype(int) * signo
        a.step(n, y0 + xi, where='post', color=c, lw=2)
        a.axhline(y0, color=MUDO, lw=0.6)
    a.set_yticks([(len(copias) - 1 - f) * paso for f in range(len(copias))])
    a.set_yticklabels([('+' if sg > 0 else '−') + nm
                       for _, sg, _, nm in copias])
    a.set_ylim(-1.4, (len(copias) - 1) * paso + 1.4)
    a.grid(axis='y', visible=False)
    panel(a, '(a)')

    a = ax[1]
    a.bar(n, np.where(d > 0, d, 0), width=0.78, color=AZUL,
          edgecolor=SUP, linewidth=2)
    a.bar(n, np.where(d < 0, d, 0), width=0.78, color=NARAN,
          edgecolor=SUP, linewidth=2)
    a.axhline(0, color=MUDO, lw=0.8)
    a.set_ylim(-1.4, 1.4)
    a.set_ylabel('d[n]')
    panel(a, '(b)')

    a = ax[2]
    a.bar(n, s, width=0.78, color=RAMPA[2], edgecolor=SUP, linewidth=2)
    a.axhline(L * A, color=MUDO, lw=1, ls='--')
    a.set_ylim(0, L * A + 1)
    a.set_ylabel('s[n] = Σ d')
    a.set_xlabel('n (muestras desde el escalón)')
    panel(a, '(c)')
    for a in ax:
        limpiar(a)
    ax[-1].xaxis.set_major_locator(MultipleLocator(2))
    fig.tight_layout()
    guardar(fig, out, '03_recursion_rtl.png', f"""
La misma síntesis vista como la hace el hardware, que no suma L copias sino
que usa la forma recursiva
s[n] = s[n−1] + (x[n] − x[n−L]) − (x[n−L−G] − x[n−2L−G]).
L={L_E}, G={G_E}, escalón de alto 1.

(a) Las cuatro copias del escalón que entran al sumador, con su signo: la
entrada y las tres tomas de las líneas de retardo (x[n−L], x[n−L−G],
x[n−2L−G]).

(b) Su suma, el incremento d[n]: un rectángulo de +1 de L muestras, G
muestras en cero y un rectángulo de −1 de L muestras. Es la derivada del
trapecio.

(c) El acumulador integra d[n] y devuelve el trapecio de la figura 02. La
cantidad de operaciones no depende de L: son tres restas y un acumulador
(más tres líneas de retardo, que sí crecen con L), contra 2L sumas de la
forma directa. Y como todo es entero y la
suma de d es exactamente cero, el acumulador vuelve a 0 sin deriva.
""")


# =============================================================================
# 04. Diagrama de bloques del datapath de mt_slope_trig
# =============================================================================

def _caja(ax, x, y, w, h, texto, fc='#eef4fc', ec=AZUL):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle='round,pad=0.02,rounding_size=0.06',
                                fc=fc, ec=ec, lw=1.4))
    ax.text(x, y, texto, ha='center', va='center', fontsize=11, color=TINTA)


def _suma(ax, x, y, r=0.22):
    ax.add_patch(Circle((x, y), r, fc=SUP, ec=TINTA2, lw=1.4))
    ax.text(x, y, 'Σ', ha='center', va='center', fontsize=12, color=TINTA)


def _flecha(ax, p0, p1, signo=None, dx=0.0, dy=0.0):
    ax.annotate('', xy=p1, xytext=p0,
                arrowprops=dict(arrowstyle='-|>', color=TINTA2, lw=1.3,
                                shrinkA=0, shrinkB=0, mutation_scale=11))
    if signo:
        ax.text(p1[0] + dx, p1[1] + dy, signo, fontsize=11, color=TINTA2,
                ha='center', va='center')


def _linea(ax, pts):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=TINTA2, lw=1.3, solid_capstyle='butt')


def _punto(ax, x, y):
    ax.plot(x, y, 'o', color=TINTA2, ms=4.5)


def fig_bloques(out):
    fig, ax = plt.subplots(figsize=(9.4, 4.6))
    ax.set_xlim(0, 9.4)
    ax.set_ylim(0, 4.6)
    ax.set_aspect('equal')
    ax.axis('off')

    # --- fila de arriba: las tres líneas de retardo ---------------------------
    yt = 4.0
    ax.text(0.05, yt, 'x[n]', ha='left', va='center', fontsize=11)
    _linea(ax, [(0.6, yt), (1.05, yt)])
    tomas = []                                   # (x, signo, nombre)
    xn = 1.05
    for i, (t, nom) in enumerate((('$z^{-L}$', '$x_a$'), ('$z^{-G}$', '$x_b$'),
                                  ('$z^{-L}$', '$x_c$'))):
        if i == 0:
            tomas.append((xn, '+', ''))
        xc = xn + 1.0
        _flecha(ax, (xn, yt), (xc - 0.5, yt))
        _caja(ax, xc, yt, 1.0, 0.56, t)
        xn = xc + 1.05
        _linea(ax, [(xc + 0.5, yt), (xn, yt)])
        tomas.append((xn, '+' if i == 2 else '−', nom))

    # --- sumador de las cuatro tomas -----------------------------------------
    ys0, ys1 = 2.45, 2.95                        # abajo y arriba del sumador
    x_izq, x_der = tomas[0][0] - 0.45, tomas[-1][0] + 0.45
    ax.add_patch(FancyBboxPatch((x_izq, ys0), x_der - x_izq, ys1 - ys0,
                                boxstyle='round,pad=0.02,rounding_size=0.06',
                                fc=SUP, ec=TINTA2, lw=1.4))
    ax.text(x_der - 0.25, (ys0 + ys1) / 2, 'Σ', ha='center', va='center',
            fontsize=12, color=TINTA)
    for x, sg, nom in tomas:
        _punto(ax, x, yt)
        _flecha(ax, (x, yt), (x, ys1))
        ax.text(x - 0.17, ys1 + 0.2, sg, ha='center', va='center',
                fontsize=12, color=TINTA2)
        if nom:
            ax.text(x + 0.1, yt + 0.3, nom, ha='left', fontsize=10,
                    color=TINTA2)

    # --- acumulador ----------------------------------------------------------
    ya = 1.35
    xd = tomas[1][0] + 0.5                       # salida del sumador
    xa = xd + 1.5
    _linea(ax, [(xd, ys0), (xd, ya)])
    _flecha(ax, (xd, ya), (xa - 0.25, ya))
    ax.text(xd + 0.1, (ys0 + ya) / 2, 'd[n]', ha='left', va='center',
            fontsize=10, color=TINTA2)
    ax.add_patch(Circle((xa, ya), 0.25, fc=SUP, ec=TINTA2, lw=1.4))
    ax.text(xa, ya, 'Σ', ha='center', va='center', fontsize=12, color=TINTA)
    xo = xa + 0.85
    _linea(ax, [(xa + 0.25, ya), (xo, ya)])
    _punto(ax, xo, ya)
    yz = 0.45
    _caja(ax, xa, yz, 0.8, 0.5, '$z^{-1}$')
    _linea(ax, [(xo, ya), (xo, yz), (xa + 0.4, yz)])
    _linea(ax, [(xa - 0.4, yz), (xa - 0.75, yz), (xa - 0.75, ya - 0.45)])
    _flecha(ax, (xa - 0.75, ya - 0.45), (xa - 0.18, ya - 0.18))

    # --- Schmitt simétrico ----------------------------------------------------
    xs = xo + 1.45
    ax.text((xa + xo) / 2 + 0.2, ya + 0.22, 's[n]', ha='center', fontsize=10,
            color=TINTA2)
    _flecha(ax, (xo, ya), (xs - 0.62, ya))
    _linea(ax, [(xo + 0.3, ya), (xo + 0.3, yz)])
    _punto(ax, xo + 0.3, ya)
    _flecha(ax, (xo + 0.3, yz), (xs - 0.62, yz))
    _caja(ax, xs, ya, 1.24, 0.5, r'$s \geq thr$', fc='#fdf0ea', ec=NARAN)
    _caja(ax, xs, yz, 1.24, 0.5, r'$s \leq -thr$', fc='#fdf0ea', ec=NARAN)
    for y, nom in ((ya, 'p'), (yz, 'n')):
        _flecha(ax, (xs + 0.62, y), (xs + 1.1, y))
        ax.text(xs + 1.18, y, nom, va='center', fontsize=11)

    guardar(fig, out, '04_bloques_rtl.png', """
El datapath de mt_slope_trig. Arriba, las tres líneas de retardo en cascada
(L, G y L muestras), que en el FPGA son SRL con una toma dinámica cada una:
x_a = x[n−L], x_b = x[n−L−G], x_c = x[n−2L−G]. Cuando G = 0 la línea del
medio se puentea (x_b = x_a).

El primer Σ arma el incremento d[n] con los signos +, −, −, +; el segundo
es el acumulador (Σ con z⁻¹ en el lazo), cuya salida es s[n]. A la derecha,
el Schmitt simétrico: p dispara con s ≥ thr y n con s ≤ −thr, cada uno
re-arma al volver más allá de thr−hyst.

Lo que el esquema no muestra: el contador de llenado, que hace que una toma
más vieja que el último re-arranque lea 0, y el registro entre cada etapa
(5 ciclos de pipeline en total).
""")


# =============================================================================
# 05. Línea de base: nivel contra pendiente
# =============================================================================

def fig_linea_base(out):
    rng = np.random.default_rng(5)
    t = np.arange(0, 10.0, TS_US)
    pulsos = [(1.0, 80), (4.0, 130), (7.0, 400)]
    ruido = rng.normal(0.0, SIGMA, len(t))
    thr = umbral_pendiente(L_P, G_P)
    hyst = thr // 3

    fig, (a, b) = plt.subplots(2, 1, figsize=(8.6, 6.0), sharex=True)
    for base, c, ls, mfc, ms in ((0, AZUL, '-', AZUL, 8),
                                 (-50, NARAN, '--', 'none', 12)):
        x = np.round(sum(A * forma(t - t0) for t0, A in pulsos)
                     + base + ruido).astype(np.int64)
        s = M.trapezoidal_rapido(x, L_P, G_P)
        i_niv = M.schmitt_nivel(x, THR_NIVEL, HYST_NIVEL)
        i_p, _ = M.schmitt_pendiente(s, L_P, G_P, thr, hyst)
        a.plot(t, x, color=c, lw=1.2, ls=ls, label=f'línea de base {base}')
        a.plot(t[i_niv], x[i_niv], 'o', ms=ms, mfc=mfc,
               mec=SUP if mfc != 'none' else c, mew=1.5)
        b.plot(t, s, color=c, lw=1.2, ls=ls, label=f'línea de base {base}')
        b.plot(t[i_p], s[i_p], 'o', ms=ms, mfc=mfc,
               mec=SUP if mfc != 'none' else c, mew=1.5)
    a.axhline(THR_NIVEL, color=MUDO, lw=1, ls=':')
    a.set_ylabel('x[n] (cuentas)')
    a.legend(loc='upper left', fontsize=9)
    panel(a, '(a)')
    for v in (thr, -thr):
        b.axhline(v, color=MUDO, lw=1, ls=':')
    b.set_ylabel('s[n]')
    b.set_xlabel('t (µs)')
    panel(b, '(b)')
    for ax in (a, b):
        limpiar(ax)
    fig.tight_layout()
    guardar(fig, out, '05_linea_base.png', f"""
El mismo tren de tres pulsos (80, 130 y 400 cuentas, subida {TAU_R*1e3:.0f} ns,
cola {TAU_D} µs, ruido σ = {SIGMA}) sobre dos líneas de base que difieren en
50 cuentas, una deriva exagerada para que se vea. Los círculos son los
disparos que da cada esquema, calculados con el Schmitt del RTL (llenos para
la base 0, huecos para la base −50).

(a) Disparo de nivel, umbral {THR_NIVEL} cuentas (punteada). Con la base en 0
dispara en 130 y 400; con la base en −50, el de 130 queda en 80 y se pierde.
El umbral es absoluto, así que el umbral EFECTIVO sobre la amplitud del
pulso se corrió 50 cuentas.

(b) Trapezoidal rápido, L={L_P}, G={G_P}, umbral ±{thr} (elegido para que un
pulso de {LLD} cuentas llegue justo). Las dos curvas son la MISMA: la
continua se cancela exactamente en enteros, y los disparos caen en las
mismas muestras. El de 80 no dispara en ninguna de las dos, el de 130 en las
dos: el umbral efectivo queda en {LLD} cuentas sobre la base, esté donde esté.
La única diferencia es el transitorio de t ≈ 0: el filtro arranca con
historia en cero y ve la base de −50 como un escalón. Es el arranque
silencioso del RTL: dura 2L+G muestras y no dispara.
""")


# =============================================================================
# 06. Apilamiento
# =============================================================================

def _pares(dt_us, n_rep, thr, hyst, rng, A=1000):
    """Fracción de pares (A, A) separados dt en los que se ven DOS disparos."""
    t = np.arange(0, 2.0 + dt_us + 6.0, TS_US)
    vis_niv = vis_pen = 0
    for _ in range(n_rep):
        t0 = 1.0 + rng.uniform(0, TS_US)
        x = senal(t, [(t0, A), (t0 + dt_us, A)], rng=rng)
        vis_niv += len(M.schmitt_nivel(x, THR_NIVEL, HYST_NIVEL)) >= 2
        s = M.trapezoidal_rapido(x, L_P, G_P)
        vis_pen += len(M.schmitt_pendiente(s, L_P, G_P, thr, hyst)[0]) >= 2
    return vis_niv / n_rep, vis_pen / n_rep


def fig_apilamiento(out, rapido=False):
    rng = np.random.default_rng(7)
    thr = umbral_pendiente(L_P, G_P)
    hyst = thr // 3
    t = np.arange(0, 6.0, TS_US)
    pulsos = [(1.0, 1000), (1.6, 700), (2.4, 900)]
    x = senal(t, pulsos, rng=rng)
    s = M.trapezoidal_rapido(x, L_P, G_P)
    i_niv = M.schmitt_nivel(x, THR_NIVEL, HYST_NIVEL)
    i_p, _ = M.schmitt_pendiente(s, L_P, G_P, thr, hyst)

    fig = plt.figure(figsize=(8.6, 8.4))
    gs = fig.add_gridspec(3, 1, height_ratios=[1, 1, 1.15], hspace=0.45)
    a = fig.add_subplot(gs[0])
    b = fig.add_subplot(gs[1], sharex=a)
    c = fig.add_subplot(gs[2])

    a.plot(t, x, color=AZUL, lw=1.2)
    a.plot(t[i_niv], x[i_niv], 'o', color=AZUL, ms=8, mec=SUP, mew=1.5)
    a.axhline(THR_NIVEL, color=MUDO, lw=1, ls=':')
    a.axhline(THR_NIVEL - HYST_NIVEL, color=MUDO, lw=0.8, ls='--')
    for t0, _ in pulsos:
        a.axvline(t0, color=MUDO, lw=0.6)
    a.set_ylabel('x[n] (cuentas)')
    panel(a, '(a)')

    b.plot(t, s, color=NARAN, lw=1.2)
    b.plot(t[i_p], s[i_p], 'o', color=NARAN, ms=8, mec=SUP, mew=1.5)
    b.axhline(thr, color=MUDO, lw=1, ls=':')
    b.axhline(thr - hyst, color=MUDO, lw=0.8, ls='--')
    for t0, _ in pulsos:
        b.axvline(t0, color=MUDO, lw=0.6)
    b.set_ylabel('s[n]')
    b.set_xlabel('t (µs)')
    panel(b, '(b)')

    dts = np.geomspace(0.02, 10.0, 16 if rapido else 34)
    n_rep = 8 if rapido else 40
    f = np.array([_pares(dt, n_rep, thr, hyst, rng) for dt in dts])
    c.plot(dts, f[:, 0], 'o-', color=AZUL, lw=2, ms=6, mec=SUP,
           label='nivel')
    c.plot(dts, f[:, 1], 'o-', color=NARAN, lw=2, ms=6, mec=SUP,
           label=f'pendiente (L={L_P}, G={G_P})')
    c.axvline((2 * L_P + G_P) * TS_US, color=MUDO, lw=1, ls=':')
    tau_niv = TAU_D * np.log(1000 / (THR_NIVEL - HYST_NIVEL))
    c.axvline(tau_niv, color=MUDO, lw=1, ls='--')
    c.set_xscale('log')
    c.set_xlabel('separación entre los dos pulsos (µs)')
    c.set_ylabel('fracción con 2 disparos')
    c.set_ylim(-0.05, 1.05)
    c.legend(loc='center right', fontsize=9)
    panel(c, '(c)')
    for ax in (a, b, c):
        limpiar(ax)
    guardar(fig, out, '06_apilamiento.png', f"""
Tres pulsos de 1000, 700 y 900 cuentas a 0.6 µs y 0.8 µs uno del otro
(líneas verticales), con cola de {TAU_D} µs.

(a) Disparo de nivel (umbral {THR_NIVEL}, re-arma bajo
{THR_NIVEL - HYST_NIVEL}, rayada): dispara UNA vez. El segundo y el tercer
pulso llegan con la señal todavía arriba del re-armado, y para el
discriminador de nivel no existen.

(b) Trapezoidal rápido: s responde a la SUBIDA de cada pulso, vuelve a
bajar del re-armado (rayada) mientras la cola decae, y dispara tres veces.
En la cola s es negativo y proporcional a la pendiente de la caída
(L·(L+G)·A/τ): por eso el umbral del canal n tiene que estar por encima de
lo que da la cola del pulso más grande.

(c) Fracción de pares de pulsos iguales (1000 cuentas, fase y ruido al azar,
{n_rep} pares por punto) en los que se ven los dos disparos, contra la
separación. La pendiente separa pares a partir de unas 2L+G muestras
({(2 * L_P + G_P) * TS_US * 1e3:.0f} ns, punteada), que es lo que tarda s en
volver a bajar del re-armado después del primer pulso; el nivel recién cuando
la cola
del primero bajó del re-armado, τ·ln(A/(thr−hyst)) ≈ {tau_niv:.1f} µs
(rayada). Esta es la base de la inspección de apilamiento de los DPP.
""")


# =============================================================================
# 07. Elección de L: ruido y relación señal/ruido
# =============================================================================

def fig_eleccion_L(out):
    rng = np.random.default_rng(11)
    Ls = np.arange(1, 17)
    ruido = np.round(rng.normal(0, SIGMA, 200_000)).astype(np.int64)
    sig_x = ruido.std()
    sig_s = np.array([M.trapezoidal_rapido(ruido, L, G_P)[100:].std()
                      for L in Ls])

    fig, (a, b, c) = plt.subplots(1, 3, figsize=(12.6, 3.6))
    Lf = np.linspace(1, 16, 200)
    a.plot(Lf, np.sqrt(2 * Lf), color=MUDO, lw=1.5, label='√(2L)')
    a.plot(Ls, sig_s / sig_x, 'o', color=AZUL, ms=7, mec=SUP, mew=1.5,
           label='simulado')
    a.set_xlabel('L (muestras)')
    a.set_ylabel('σ_s / σ_x')
    a.legend(loc='upper left', fontsize=9)
    panel(a, '(a)')

    t = np.arange(0, 6.0, TS_US)
    i0 = int(round(1.0 / TS_US))                 # muestra del arranque
    for tr, col in ((0.020, AZUL), (0.100, NARAN)):
        x1 = senal(t, [(1.0, LLD)], sigma=0, tau_r=tr)
        x2 = senal(t, [(1.0, 2 * LLD)], sigma=0, tau_r=tr)
        snr, lat = [], []
        for L, s_ in zip(Ls, sig_s):
            pico = M.trapezoidal_rapido(x1, L, G_P).max()
            snr.append(pico / s_)
            ip, _ = M.schmitt_pendiente(M.trapezoidal_rapido(x2, L, G_P),
                                        L, G_P, int(pico), int(pico) // 3)
            lat.append((ip[0] - i0) * TS_US * 1e3 if len(ip) else np.nan)
        b.plot(Ls, snr, 'o-', color=col, lw=2, ms=6, mec=SUP,
               label=f'subida {tr*1e3:.0f} ns')
        c.plot(Ls, lat, 'o-', color=col, lw=2, ms=6, mec=SUP,
               label=f'subida {tr*1e3:.0f} ns')
    b.set_xlabel('L (muestras)')
    b.set_ylabel(f'pico de s / σ_s  (pulso de {LLD} cuentas)')
    b.legend(loc='upper left', fontsize=9)
    panel(b, '(b)')
    c.set_xlabel('L (muestras)')
    c.set_ylabel('latencia hasta el disparo (ns)')
    c.set_ylim(bottom=0)
    c.legend(loc='upper left', fontsize=9)
    panel(c, '(c)')
    for ax in (a, b, c):
        limpiar(ax)
        ax.xaxis.set_major_locator(MultipleLocator(2))
    fig.tight_layout()
    guardar(fig, out, '07_eleccion_L.png', f"""
Cómo elegir L (con G = {G_P}).

(a) Ruido a la salida del filtro, relativo al de la entrada, para ruido
blanco simulado (σ = {SIGMA} cuentas, 200 000 muestras). Los puntos caen
sobre √(2L): s suma 2L muestras de ruido independientes.

(b) Relación entre el pico de s para un pulso de {LLD} cuentas y el ruido de
s, para dos tiempos de subida. Con una cola de {TAU_D} µs (unas
{TAU_D / TS_US:.0f} muestras) el pulso es un escalón para cualquier L de
este rango: la señal crece como L y el ruido como √L, así que la relación
crece como √L sin aplanarse. Una subida más lenta cuesta pico cuando L+G es
comparable con la subida, y la diferencia se achica al crecer L.

(c) El costo: muestras desde el arranque de un pulso de {2*LLD} cuentas hasta
el disparo, con el umbral puesto en el pico de un pulso de {LLD} (o sea, el
pulso es el doble del umbral). Crece con L, porque s tarda unas L muestras en
llegar a su pico. No incluye los 5 ciclos (40 ns) de pipeline del RTL.
""")


# =============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI, help='dónde dejar los PNG')
    ap.add_argument('--rapido', action='store_true',
                    help='menos realizaciones en la 06: para iterar el dibujo')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    verificar_modelo()
    fig_respuesta(a.out)
    fig_superposicion(a.out)
    fig_recursion(a.out)
    fig_bloques(a.out)
    fig_linea_base(a.out)
    fig_apilamiento(a.out, a.rapido)
    fig_eleccion_L(a.out)

    escribir_epigrafes(
        os.path.join(a.out, 'epigrafes.txt'),
        """Epígrafes de las figuras del disparo por pendiente (mt_slope_trig).
        Los escribe figuras_pendiente.py; no editar a mano. Documento:
        docs/mt/procesamiento_pendiente.md.""",
        EPIGRAFES,
        pie="""Todas las curvas salen de
        modulos/mt/modelos/python_model/mt_slope_model.py, que hace la misma
        recursión que el RTL; el script verifica que coincide con la
        convolución directa antes de dibujar.""")


if __name__ == '__main__':
    main()
