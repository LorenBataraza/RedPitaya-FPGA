#!/usr/bin/env python3
"""Qué gana el timestamp con un CFD digital, para `../../timestamp_cfd.md`.

Monte Carlo del instante de arribo estimado por cinco métodos, sobre el mismo
modelo de pulso y el mismo ruido que el resto de la documentación del MCA:

  - forma: subida exponencial (t_r 10-90 %) por cola exponencial
    (tau = 1650 ns), la de `../ventana/figuras_ventana.py`;
  - ruido blanco por muestra sigma_w = 4.47 cuentas, el medido
    (`fuentes_de_jitter.md` §4);
  - muestreo a 125 MS/s con la FASE de arribo al azar dentro de la muestra;
  - umbral de nivel thr = 100 cuentas, el de las campañas.

Los cinco estimadores:

  led          lo que hace hoy el RTL: el índice de la primera muestra >= thr.
  led_interp   interpolación lineal del cruce entre las dos muestras que lo
               encierran.
  led_corr     led_interp menos la curva de walk w(A), evaluada en la amplitud
               MEDIDA del mismo evento (la muestra de pico). Es la corrección
               por software de `ventana_de_medicion.md` §5.
  cfd          y[n] = f·x[n] − x[n−D]; la primera muestra negativa después del
               armado (el cruce de thr).
  cfd_interp   lo mismo con interpolación lineal del cruce por cero.

Dos formas: subida de 100 ns (el pulso del generador, ~12 muestras de flanco)
y de 20 ns (un detector rápido, 2.5 muestras). f y D del CFD salen del barrido
de la figura 04, no de una elección a ojo.

Sin prosa adentro de las figuras; los epígrafes los escribe este script.

    python3 figuras_cfd.py [--out DIR] [--rapido]
"""

import argparse
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, '..', '..', '..', 'figuras'))
from estilo import (SUP, TINTA2, MUDO, AZUL, NARAN, VERDE, MORADO,  # noqa: E402
                    RAMPA, limpiar, panel, escribir_epigrafes)

TS = 8.0                    # ns por muestra
SIGMA_W = 4.47              # cuentas rms por muestra (fuentes_de_jitter §4)
THR = 100                   # cfg_thr
TAU_D = 1650.0              # ns, la cola de figuras_ventana.py
A_MIN, A_MAX = 150.0, 8192.0

# Las dos formas y el CFD elegido para cada una (figura 04)
FORMAS = {100.0: dict(f=0.25, D=8), 20.0: dict(f=0.5, D=3)}

METODOS = (('led',        'LED (RTL actual)',          TINTA2, '-'),
           ('led_interp', 'LED + interpolación',       NARAN,  '-'),
           ('led_corr',   'LED + interp. + corr. walk', VERDE, '-'),
           ('cfd',        'CFD',                       MORADO, '--'),
           ('cfd_interp', 'CFD + interpolación',       AZUL,   '-'))

EPIGRAFES = []


def eje_log_legible(ax, eje='y', ticks=(0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5, 10)):
    """Ticks de una escala log con números comunes, no potencias de 10."""
    e = ax.yaxis if eje == 'y' else ax.xaxis
    e.set_major_locator(FixedLocator(ticks))
    e.set_minor_locator(NullLocator())
    e.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'))


def guardar(fig, out, nombre, nota):
    fig.savefig(os.path.join(out, nombre), bbox_inches='tight')
    plt.close(fig)
    EPIGRAFES.append({'archivo': nombre, 'nota': nota})
    print(' ', nombre)


# =============================================================================
# Modelo
# =============================================================================

def forma(t, tr):
    """Pulso normalizado al pico. Misma forma que figuras_ventana.py."""
    a = tr / np.log(9.0)
    tt = np.clip(t, 0.0, None)
    y = (1.0 - np.exp(-tt / a)) * np.exp(-tt / TAU_D)
    tp = a * np.log(1.0 + TAU_D / a)
    pico = (1.0 - np.exp(-tp / a)) * np.exp(-tp / TAU_D)
    return np.where(t > 0.0, y / pico, 0.0)


def simular(A, tr, rng, nw=96, pre=20, sigma=SIGMA_W):
    """Eventos (filas) con amplitud A (escalar o vector) y fase al azar."""
    A = np.atleast_1d(np.asarray(A, float))
    t0 = (pre + rng.uniform(0.0, 1.0, len(A))) * TS
    t = np.arange(nw) * TS
    x = A[:, None] * forma(t[None, :] - t0[:, None], tr)
    if sigma:
        x = x + rng.normal(0.0, sigma, x.shape)
    return x, t0


def _cruce(y0, y1, n1):
    """Interpolación lineal: dónde cruza cero la recta entre (n1−1, y0), (n1, y1)."""
    return (n1 - 1 + y0 / (y0 - y1)) * TS


def estimar(x, tr, curva_walk=None):
    """Los cinco tiempos de arribo, en ns, y la máscara de eventos válidos."""
    n, nw = x.shape
    i = np.arange(n)
    m = x >= THR
    nL = m.argmax(1)
    ok = m.any(1) & (nL > 0)
    t = {'led': nL * TS,
         'led_interp': _cruce(x[i, nL - 1] - THR, x[i, nL] - THR, nL)}

    if curva_walk is not None:
        A_med = x.max(1)                          # la muestra de pico
        la, w = curva_walk
        t['led_corr'] = t['led_interp'] - np.interp(np.log(A_med), la, w)

    f, D = FORMAS[tr]['f'], FORMAS[tr]['D']
    y = f * x
    y[:, D:] -= x[:, :-D]
    idx = np.arange(nw)[None, :]
    c = (idx > nL[:, None]) & (y < 0) & (np.roll(y, 1, axis=1) >= 0)
    nz = c.argmax(1)
    ok &= c.any(1)
    t['cfd'] = nz * TS
    t['cfd_interp'] = _cruce(y[i, nz - 1], y[i, nz], nz)
    return t, ok


def curva_walk(tr, rng):
    """w(A) = sesgo medio de led_interp sin ruido, promediado en la fase.

    Es la curva que se calibraría con el pulser deslizante.
    """
    As = np.geomspace(A_MIN * 0.8, A_MAX * 1.2, 60)
    w = []
    for A in As:
        x, t0 = simular(np.full(400, A), tr, rng, sigma=0)
        t, ok = estimar(x, tr)
        w.append(np.mean((t['led_interp'] - t0)[ok]))
    return np.log(As), np.array(w)


def barrido(tr, rng, n_ev, amps):
    """Sesgo y sigma de cada método contra la amplitud."""
    cw = curva_walk(tr, rng)
    res = {k: {'sesgo': [], 'sigma': []} for k, *_ in METODOS}
    for A in amps:
        x, t0 = simular(np.full(n_ev, A), tr, rng)
        t, ok = estimar(x, tr, cw)
        for k in res:
            e = (t[k] - t0)[ok]
            res[k]['sesgo'].append(e.mean())
            res[k]['sigma'].append(e.std())
    for k in res:
        for q in res[k]:
            res[k][q] = np.array(res[k][q])
    return res, cw


def coincidencias(tr, rng, n_par, cw):
    """Δt entre dos canales simultáneos con amplitudes independientes.

    Las amplitudes son log-uniformes entre A_MIN y A_MAX: un espectro ancho,
    que es donde el walk pesa.
    """
    dts = {}
    eventos = []
    for _ in range(2):
        A = np.exp(rng.uniform(np.log(A_MIN), np.log(A_MAX), n_par))
        x, t0 = simular(A, tr, rng)
        t, ok = estimar(x, tr, cw)
        eventos.append((t, t0, ok))
    (ta, t0a, oka), (tb, t0b, okb) = eventos
    ok = oka & okb
    for k, *_ in METODOS:
        dts[k] = ((ta[k] - t0a) - (tb[k] - t0b))[ok]
    return dts


def fwhm(v, paso=0.05):
    """FWHM del histograma (sirve para distribuciones no gaussianas)."""
    v = v - np.median(v)
    lim = max(4 * v.std(), 5 * paso)
    h, b = np.histogram(v, bins=np.arange(-lim, lim + paso, paso))
    h = np.convolve(h, np.ones(3) / 3, 'same')
    arriba = np.where(h >= h.max() / 2)[0]
    return (arriba[-1] - arriba[0] + 1) * paso


# =============================================================================
# 01. El principio
# =============================================================================

def fig_principio(out):
    tr = 100.0
    f, D = FORMAS[tr]['f'], FORMAS[tr]['D']
    t = np.linspace(-50, 450, 2001)
    amps = (150, 300, 600)
    colores = (RAMPA[0], RAMPA[2], RAMPA[4])

    fig, ax = plt.subplots(3, 1, figsize=(8.2, 8.0), sharex=True)
    a = ax[0]
    for A, c in zip(amps, colores):
        x = A * forma(t, tr)
        a.plot(t, x, color=c, lw=2, label=f'A = {A}')
        tc = t[np.argmax(x >= THR)]
        a.plot(tc, THR, 'o', color=c, ms=8, mec=SUP, mew=1.5)
    a.axhline(THR, color=MUDO, lw=1, ls=':')
    a.set_ylim(-20, 640)
    a.set_ylabel('x(t) (cuentas)')
    a.legend(loc='upper left', fontsize=9)
    panel(a, '(a)')

    a = ax[1]
    A = 400
    x = A * forma(t, tr)
    xd = A * forma(t - D * TS, tr)
    a.plot(t, f * x, color=NARAN, lw=2, label=f'f·x(t), f = {f}')
    a.plot(t, -xd, color=VERDE, lw=2, label=f'−x(t − D), D = {D} muestras')
    a.plot(t, f * x - xd, color=AZUL, lw=2.4, label='y(t), la suma')
    a.axhline(0, color=MUDO, lw=0.8)
    a.set_ylabel('cuentas')
    a.legend(loc='lower left', fontsize=9)
    panel(a, '(b)')

    a = ax[2]
    for A, c in zip(amps, colores):
        y = A * (f * forma(t, tr) - forma(t - D * TS, tr))
        a.plot(t, y, color=c, lw=2, label=f'A = {A}')
        # las muestras de un evento, con su fase
        ns = np.arange(-6, 56) * TS + 3.0
        ys = A * (f * forma(ns, tr) - forma(ns - D * TS, tr))
        a.plot(ns, ys, 'o', color=c, ms=4)
    tz = t[np.argmax((t > 0) & (f * forma(t, tr) - forma(t - D * TS, tr) < 0))]
    a.axvline(tz, color=MUDO, lw=1, ls='--')
    a.axhline(0, color=MUDO, lw=0.8)
    a.set_ylabel('y(t) (cuentas)')
    a.set_xlabel('t desde el arribo (ns)')
    a.set_xlim(-50, 450)
    panel(a, '(c)')
    for a in ax:
        limpiar(a)
    fig.tight_layout()
    guardar(fig, out, '01_cfd_principio.png', f"""
El principio del CFD, sobre el pulso del generador (subida de {tr:.0f} ns
10-90 %, cola de {TAU_D:.0f} ns), sin ruido.

(a) Tres amplitudes que llegan en el MISMO instante. El umbral fijo de
{THR} cuentas (punteada) las cruza en instantes distintos (círculos): ese
corrimiento es el walk del disparo de nivel, y es lo que hoy lleva el
timestamp.

(b) La construcción, para A = 400: la señal atenuada f·x(t) (naranja), la
señal retardada D muestras e invertida (verde), y su suma y(t) (azul). Es
la superposición de dos copias del mismo pulso, como el trapezoidal.

(c) y(t) para las tres amplitudes. Como y es lineal en A, las tres curvas
son la misma escalada, y cruzan cero en el MISMO instante (rayada): el
cruce no depende de la amplitud por construcción. Los puntos son las
muestras de un evento: el cruce cae entre dos de ellas y hay que
interpolarlo para no volver a cuantizar a {TS:.0f} ns.
""")


# =============================================================================
# 02. Walk y jitter contra la amplitud
# =============================================================================

def fig_walk_jitter(out, resultados, amps):
    fig, ax = plt.subplots(2, 2, figsize=(10.4, 7.4), sharex=True)
    for fila, tr in enumerate(FORMAS):
        res = resultados[tr][0]
        a, b = ax[fila]
        for k, nombre, c, ls in METODOS:
            ses = res[k]['sesgo'] - res[k]['sesgo'][-1]
            a.plot(amps, ses, ls, color=c, lw=2, marker='o', ms=5, mec=SUP,
                   label=nombre)
            b.plot(amps, res[k]['sigma'], ls, color=c, lw=2, marker='o',
                   ms=5, mec=SUP, label=nombre)
        b.axhline(TS / np.sqrt(12), color=MUDO, lw=1, ls=':')
        a.axhline(0, color=MUDO, lw=0.8)
        for z in (a, b):
            z.set_xscale('log')
            limpiar(z)
        b.set_yscale('log')
        eje_log_legible(b)
        a.set_ylabel(f'walk (ns), subida {tr:.0f} ns')
        b.set_ylabel(f'σ_t (ns), subida {tr:.0f} ns')
        panel(a, '(a)' if fila == 0 else '(c)')
        panel(b, '(b)' if fila == 0 else '(d)')
    for z in ax[1]:
        z.set_xlabel('amplitud (cuentas)')
    h, l = ax[0][1].get_legend_handles_labels()
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.legend(h, l, loc='lower center', ncol=3, fontsize=9)
    guardar(fig, out, '02_walk_jitter.png', f"""
Los cinco estimadores contra la amplitud, {resultados['n_ev']} eventos por
punto, ruido σ = {SIGMA_W} cuentas por muestra y fase de arribo al azar.
Arriba, subida de 100 ns (CFD f = {FORMAS[100.0]['f']}, D =
{FORMAS[100.0]['D']}); abajo, subida de 20 ns (f = {FORMAS[20.0]['f']}, D =
{FORMAS[20.0]['D']}).

(a), (c) Walk: el sesgo medio del instante estimado, relativo al del pulso
más grande (una latencia constante no importa; lo que importa es que cambie
con A). El disparo de nivel, con o sin interpolación, se atrasa decenas de
ns para los pulsos chicos. La corrección por software lo lleva a cero
salvo cerca del umbral, donde la amplitud medida ya es ruidosa. El CFD no
tiene walk: queda en cero en todo el rango.

(b), (d) Jitter: la dispersión del instante. La punteada es Ts/√12 =
{TS / np.sqrt(12):.2f} ns, la cuantización del RTL actual, que es exactamente
lo que da el LED sin interpolar. La interpolación del LED funciona en la
primera década sobre el umbral pero EMPEORA para pulsos grandes: el umbral
cae en el quiebre donde arranca el pulso y la recta entre dos muestras no lo
sigue. El CFD interpolado cae como σ_w/pendiente en todo el rango, hasta
decenas de ps.
""")


# =============================================================================
# 03. Coincidencias
# =============================================================================

def fig_coincidencias(out, coinc, tabla_c):
    fig, ax = plt.subplots(1, 2, figsize=(10.4, 3.8))
    for a, tr, letra in zip(ax, FORMAS, ('(a)', '(b)')):
        dts = coinc[tr]
        bins = np.arange(-80, 80.01, 0.5)
        for k, nombre, c, ls in METODOS:
            if k == 'cfd':
                continue
            v = dts[k] - np.median(dts[k])
            a.hist(v, bins=bins, histtype='step', color=c, lw=1.8, ls=ls,
                   density=True, label=nombre)
        a.set_yscale('log')
        a.set_xlim(-60, 60) if tr == 100.0 else a.set_xlim(-25, 25)
        a.set_ylim(1e-4, 5)
        a.set_xlabel('Δt entre canales (ns)')
        a.set_ylabel(f'densidad, subida {tr:.0f} ns')
        panel(a, letra)
        limpiar(a)
    ax[0].legend(loc='upper left', fontsize=8.5)
    fig.tight_layout()
    lineas = '\n'.join(
        f'| {nombre} | {tabla_c[100.0][k][0]:.2f} | {tabla_c[100.0][k][1]:.2f}'
        f' | {tabla_c[20.0][k][0]:.2f} | {tabla_c[20.0][k][1]:.2f} |'
        for k, nombre, *_ in METODOS)
    guardar(fig, out, '03_coincidencias.png', f"""
El caso de uso: dos canales reciben pulsos SIMULTÁNEOS con amplitudes
independientes, log-uniformes entre {A_MIN:.0f} y {A_MAX:.0f} cuentas, y se mide
Δt = t_a − t_b. Lo ideal es una delta en cero. Histogramas normalizados, en
escala log, centrados en la mediana. (a) subida de 100 ns, (b) de 20 ns.

El disparo de nivel da una distribución ancha y de colas largas: el walk de
cada canal se resta y queda un ancho del orden del walk total. Con la
corrección por software se angosta mucho, pero conserva colas de los eventos
cerca del umbral. El CFD interpolado queda por debajo de 1 ns de FWHM.

FWHM y σ de Δt, en ns:

| método | FWHM (100 ns) | σ (100 ns) | FWHM (20 ns) | σ (20 ns) |
{lineas}
""")


# =============================================================================
# 04. Elección de f y D
# =============================================================================

def fig_parametros(out, rng, n_ev):
    Ds = np.arange(1, 17)
    fs = (0.125, 0.25, 0.5)
    fig, ax = plt.subplots(1, 2, figsize=(10.4, 3.8))
    guardado = {tr: dict(v) for tr, v in FORMAS.items()}
    for a, tr, letra in zip(ax, FORMAS, ('(a)', '(b)')):
        for f, c in zip(fs, (RAMPA[0], RAMPA[2], RAMPA[4])):
            sig, efi = [], []
            for D in Ds:
                FORMAS[tr]['f'], FORMAS[tr]['D'] = f, int(D)
                x, t0 = simular(np.full(n_ev, 400.0), tr, rng)
                t, ok = estimar(x, tr)
                efi.append(ok.mean())
                sig.append((t['cfd_interp'] - t0)[ok].std() if ok.any()
                           else np.nan)
            sig, efi = np.array(sig), np.array(efi)
            bien = efi >= 0.99
            a.plot(Ds[bien], sig[bien], 'o-', color=c, lw=2, ms=6, mec=SUP,
                   label=f'f = {f}')
        g = guardado[tr]
        a.axvline(g['D'], color=MUDO, lw=1, ls='--')
        a.set_yscale('log')
        eje_log_legible(a, ticks=(0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2))
        a.set_xlabel('D (muestras)')
        a.set_ylabel(f'σ_t a A = 400 (ns), subida {tr:.0f} ns')
        a.legend(loc='upper right', fontsize=9)
        panel(a, letra)
        limpiar(a)
    for tr in FORMAS:
        FORMAS[tr].update(guardado[tr])
    fig.tight_layout()
    guardar(fig, out, '04_parametros_cfd.png', f"""
Cómo se eligieron f y D: jitter del CFD interpolado para un pulso de 400
cuentas, contra el retardo D, para tres fracciones que se implementan con
desplazamientos (1/8, 1/4, 1/2). (a) subida de 100 ns, (b) de 20 ns. Los
puntos que faltan a la izquierda son los D con los que el cruce cae ANTES
del armado (el cruce de thr) en más del 1 % de los eventos: el CFD necesita
D lo bastante largo para que el pulso más chico ya esté armado cuando y
cruza cero. La rayada es la elección: f = {FORMAS[100.0]['f']}, D =
{FORMAS[100.0]['D']} para 100 ns; f = {FORMAS[20.0]['f']}, D =
{FORMAS[20.0]['D']} para 20 ns.

Con flanco lento (a), f = 1/2 es la peor: el cruce cae arriba en el flanco,
donde la pendiente ya bajó. 1/8 y 1/4 empatan a esta amplitud, pero 1/8 se
degrada cerca del umbral (con D = 8, 1.6 contra 1.3 ns a A = 150), así que
queda 1/4. Con flanco rápido (b) manda la interpolación: f = 1/2 pone el
cruce en el medio del flanco, donde y es más recta, y el error de la recta
es mínimo.
""")


# =============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=_AQUI)
    ap.add_argument('--rapido', action='store_true')
    a = ap.parse_args()
    rng = np.random.default_rng(20261023)
    n_ev = 600 if a.rapido else 4000
    n_par = 4000 if a.rapido else 40000
    amps = np.geomspace(A_MIN, A_MAX, 14)

    fig_principio(a.out)
    resultados = {'n_ev': n_ev}
    coinc, tabla_c = {}, {}
    for tr in FORMAS:
        res, cw = barrido(tr, rng, n_ev, amps)
        resultados[tr] = (res, cw)
        coinc[tr] = coincidencias(tr, rng, n_par, cw)
        tabla_c[tr] = {k: (fwhm(v), v.std()) for k, v in coinc[tr].items()}
    fig_walk_jitter(a.out, resultados, amps)
    fig_coincidencias(a.out, coinc, tabla_c)
    fig_parametros(a.out, rng, n_ev // 2)

    print('\nwalk (150 -> 8192) y sigma (ns):')
    for tr in FORMAS:
        res = resultados[tr][0]
        print(f'  subida {tr:.0f} ns')
        for k, nombre, *_ in METODOS:
            w = res[k]['sesgo'][0] - res[k]['sesgo'][-1]
            s = res[k]['sigma']
            print(f'    {nombre:<28} walk {w:7.2f}   sigma A=150 {s[0]:5.2f}'
                  f'  A~400 {np.interp(400, amps, s):5.2f}'
                  f'  A~2000 {np.interp(2000, amps, s):5.2f}  A=8192 {s[-1]:5.3f}'
                  f'   coinc FWHM {tabla_c[tr][k][0]:6.2f} sigma {tabla_c[tr][k][1]:6.2f}')

    escribir_epigrafes(
        os.path.join(a.out, 'epigrafes.txt'),
        """Epígrafes de las figuras del timestamp con CFD. Los escribe
        figuras_cfd.py; no editar a mano. Documento: docs/mca/timestamp_cfd.md.""",
        EPIGRAFES)


if __name__ == '__main__':
    main()
