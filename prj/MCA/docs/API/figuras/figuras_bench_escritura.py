#!/usr/bin/env python3
"""Los benchmarks del escritor, en el estilo común de las figuras TikZ.

  bench_escribir.tex      cuántos eventos por segundo aguanta el escritor solo, por
                           formato y largo de ventana, sin y con compresión: en la PC
                           y en la placa
  bench_leer.tex           lo que cuesta leer una corrida de 20 archivos, de tres
                           maneras, en la PC y en la placa
  bench_lector.tex         con la adquisición corriendo: (a) un lote solo y con un
                           lector compitiendo por el GIL, (b) la mayor demora del
                           lector y (c) la pérdida contra la tasa, con el lector en
                           Python y en C

Cada .tex se compila a .pdf y .svg. Son DATOS MEDIDOS, no esquemas:

  - la PC de `bench_escribir` y `bench_leer` sale del JSON de
    `make bench-formatos` (software/datos/bench_formatos/pc_20261108.json);
  - la placa, de las tablas de docs/API/arquitectura_adquisicion_software.md
    («El formato del archivo» y «Con la adquisición corriendo»): las corridas en la
    placa del 2026-11-07 y 2026-11-08 no dejaron el JSON en el repo. Si se vuelven a
    medir, se cambian acá abajo, en PLACA_*.

Sin pgfplots: Python escribe TikZ crudo, como docs/mca/figuras/figuras_cadena_tikz.py.
El color es el del formato, el mismo en las tres figuras (.npz azul, LH5 naranja,
validados para daltonismo), y la forma lo repite donde hay marcas (círculo y
cuadrado). La compresión va rayada, y «solo» contra «con lector» va claro contra
lleno. Los epígrafes no van adentro: están en <figura>.txt.

    python3 figuras_bench_escritura.py            # escribe los .tex y los compila
    python3 figuras_bench_escritura.py --sin-compilar
"""
import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
JSON_PC = AQUI.parents[2] / 'software' / 'datos' / 'bench_formatos' / 'pc_20261108.json'

VENTANAS = (32, 256, 2048)
LOTE = {32: 4096, 256: 4096, 2048: 1024}          # eventos por lote, por ventana

# ----------------------------------------------------------------- la placa ---
# arquitectura_adquisicion_software.md, «En la placa» (2026-11-08,
# make bench-formatos-remoto): escribir un lote [ms] y leer la corrida de 20
# archivos [ms].
PLACA_ESCRIBIR_MS = {
    ('npz', False): {32: 22, 256: 108, 2048: 202},
    ('lh5', False): {32: 86, 256: 151, 2048: 218},
    ('npz', True):  {32: 498, 256: 3180, 2048: 6280},
    ('lh5', True):  {32: 264, 256: 1300, 2048: 2550},
}
PLACA_LEER_MS = {
    'todo':     {'npz': {32: 685, 256: 1800, 2048: 3860},
                 'lh5': {32: 625, 256: 1420, 2048: 2150}},
    'columnas': {'npz': {32: 270, 256: 260, 2048: 239},
                 'lh5': {32: 231, 256: 231, 2048: 228}},
    'pocos':    {'npz': {32: 317, 256: 1430, 2048: 2730},
                 'lh5': {32: 308, 256: 339, 2048: 352}},
}
# «Con la adquisición corriendo» (bench_escritura.py): 4096 eventos × 2 canales ×
# 32 muestras. [solo, con un lector compitiendo por el GIL, mayor demora del lector]
# en ms. La PC con h5py 3.16; la placa (2026-11-07) con h5py 3.6.0.
LECTOR_MS = {
    'PC':    {'npz': (0.7, 37, 1.6), 'lh5': (2.4, 143, 1.8)},
    'placa': {'npz': (46, 97, 3.1),  'lh5': (107, 255, 11.2)},
}
SWITCH_MS = 1.0             # sys.setswitchinterval de la sesión
# run_poisson_loss.py, misma semilla y mismo tren: pérdida [%] contra ρ, con
# τ = 252.7 µs (el del lector de Python). Con Python, `.npz` es la media de las dos
# corridas (difieren hasta 1.1 pp); con C, 2026-11-08.
RHO = (0.1, 0.5, 1.0, 2.0)
PERDIDA = {
    ('py', 'npz'): tuple((a + b) / 2 for a, b in zip((0.0, 29.7, 47.6, 67.1),
                                                     (0.0, 30.5, 46.5, 67.5))),
    ('py', 'lh5'): (0.1, 30.9, 48.4, 69.5),
    ('c', 'npz'):  (1.7, 7.4, 9.2, 15.6),
    ('c', 'lh5'):  (1.6, 7.2, 9.4, 15.6),
}
TAU_US = 252.7

PREAMBULO = r"""%% %(desc)s. GENERADO por figuras_bench_escritura.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../figuras/estilo_tikz.tex}
%% el color del formato, el mismo en las tres figuras (validado: ΔE 22.8 con
%% protanopía, contraste >= 3:1 sobre blanco)
\definecolor{fnpz}{HTML}{3F8FD2}
\definecolor{flh5}{HTML}{D9702A}
%% lo que no es un formato, en la leyenda: rayado, claro, lleno
\colorlet{neutro}{black!60}
\tikzset{
  eje/.style    = {black!60, line width=0.5pt},
  guia/.style   = {black!12, line width=0.4pt},
  tick/.style   = {font=\scriptsize, inner sep=1.5pt, black!75},
  titeje/.style = {font=\scriptsize, inner sep=1pt},
  parte/.style  = {anchor=south west, font=\small\bfseries, inner sep=0pt},
  barra/.style  = {fill=#1, draw=none},
  clara/.style  = {fill=#1!28, draw=#1, line width=0.4pt},
  valor/.style  = {font=\tiny, inner sep=1pt, black!80},
  ref/.style    = {black!55, line width=0.5pt, dash pattern=on 2pt off 1.5pt},
  serie/.style  = {#1, line width=0.9pt, line join=round},
}
\begin{document}
\begin{tikzpicture}[fondo]
%(cuerpo)s
\end{tikzpicture}
\end{document}
"""

COLOR = {'npz': 'fnpz', 'lh5': 'flh5'}
NOMBRE = {'npz': r'\texttt{.npz}', 'lh5': 'LH5'}


def f(v):
    return f'{v:.3f}'


def eje_log(lo, hi, alto):
    a, b = math.log10(lo), math.log10(hi)
    return lambda v: (math.log10(v) - a) / (b - a) * alto


def decadas(lo, hi):
    k = round(math.log10(lo))
    while 10 ** k <= hi * 1.0001:
        yield 10 ** k
        k += 1


def num(v):
    """Un número de tick sin ceros de más: 0.1, 1, 10, 10 000."""
    if v < 1:
        return f'{v:g}'
    return f'{int(v):,}'.replace(',', '\\,')


def marco_log(l, x0, ancho, alto, lo, hi, rotulo=num, etiquetas=True):
    """Guías y eje de un panel con el eje y logarítmico. Devuelve Y(v)."""
    Y = eje_log(lo, hi, alto)
    for v in decadas(lo, hi):
        y = Y(v)
        l.append(f'\\draw[guia] ({f(x0)},{f(y)}) -- ({f(x0 + ancho)},{f(y)});')
        tick = f' node[tick, left] {{{rotulo(v)}}}' if etiquetas else ''
        l.append(f'\\draw[eje] ({f(x0)},{f(y)}) -- ++(-0.07,0){tick};')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0)},{f(alto)});')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0 + ancho)},0);')
    return Y


RAYA = 0.075                                # cm entre rayas, en horizontal


def barra(l, estilo, x, ancho, alto, y0=0.0):
    """Una barra desde y0. `rayada=<color>` son rayas a 45° recortadas a la barra,
    a mano: el `pattern` de TikZ pdftocairo lo pasa al SVG como miles de recortes."""
    if alto <= 0:
        return
    rect = f'({f(x)},{f(y0)}) rectangle ({f(x + ancho)},{f(y0 + alto)})'
    if not estilo.startswith('rayada='):
        l.append(f'\\path[{estilo}] {rect};')
        return
    color = estilo.split('=', 1)[1]
    l.append(f'\\begin{{scope}}\\clip {rect};')
    t = -alto
    rayas = []
    while t < ancho:
        rayas.append(f'({f(x + t)},{f(y0)}) -- ++({f(alto + RAYA)},{f(alto + RAYA)})')
        t += RAYA * 1.414
    l.append(f'\\draw[{color}, line width=0.7pt] ' + ' '.join(rayas) + ';')
    l.append('\\end{scope}')
    l.append(f'\\draw[{color}, line width=0.4pt] {rect};')


def compilar(nombre, cuerpo, desc):
    tex = AQUI / f'{nombre}.tex'
    tex.write_text(PREAMBULO % dict(desc=desc, cuerpo='\n'.join(cuerpo)), encoding='utf-8')
    return tex


# =============================================================================
# bench_escribir: lo que aguanta el escritor solo
# =============================================================================
W_E, H_E, SEP_E = 6.4, 4.4, 1.5
LO_E, HI_E = 0.1, 1e4                       # kev/s
B_E, G_E = 0.34, 0.06                      # ancho de barra y hueco entre barras


def fig_escribir(pc):
    l = []
    variantes = (('npz', False), ('lh5', False), ('npz', True), ('lh5', True))
    paneles = (('(a)\\enspace en la PC', 0.0,
                {v: {w: LOTE[w] / pc[v][w]['escribir_ms'] for w in VENTANAS}
                 for v in variantes}),
               ('(b)\\enspace en la placa', W_E + SEP_E,
                {v: {w: LOTE[w] / PLACA_ESCRIBIR_MS[v][w] for w in VENTANAS}
                 for v in variantes}))
    paso = W_E / len(VENTANAS)
    ancho_grupo = len(variantes) * B_E + (len(variantes) - 1) * G_E
    for titulo, x0, kev in paneles:
        Y = marco_log(l, x0, W_E, H_E, LO_E, HI_E, etiquetas=(x0 == 0.0))
        l.append(f'\\node[parte] at ({f(x0)},{f(H_E + 0.25)}) {{{titulo}}};')
        for i, w in enumerate(VENTANAS):
            xg = x0 + paso * (i + 0.5) - ancho_grupo / 2
            for j, (fmt, comp) in enumerate(variantes):
                estilo = f'rayada={COLOR[fmt]}' if comp else f'barra={COLOR[fmt]}'
                barra(l, estilo, xg + j * (B_E + G_E), B_E, Y(kev[(fmt, comp)][w]))
            xc = x0 + paso * (i + 0.5)
            l.append(f'\\node[tick, anchor=north] at ({f(xc)},-0.06) {{{w}}};')
            l.append(f'\\node[tick, anchor=north, black!55, font=\\tiny] at '
                     f'({f(xc)},-0.36) {{{LOTE[w]} por lote}};')
        l.append(f'\\node[titeje, anchor=north] at ({f(x0 + W_E / 2)},-0.72) '
                 '{muestras por canal en la ventana};')
    l.append(f'\\node[titeje, rotate=90, anchor=south] at (-1.2,{f(H_E / 2)}) '
             '{eventos por segundo, escribiendo solo [kev/s]};')
    # leyenda
    y = -1.45
    x = -0.4
    for fmt in ('npz', 'lh5'):
        l.append(f'\\path[barra={COLOR[fmt]}] ({f(x)},{f(y - 0.12)}) rectangle ++(0.4,0.26);')
        l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
                 f'{{{NOMBRE[fmt]}}};')
        x += 1.75
    barra(l, 'rayada=neutro', x, 0.4, 0.26, y0=y - 0.12)
    l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
             '{comprimido (\\texttt{savez\\_compressed}, gzip por dataset)};')
    return l


# =============================================================================
# bench_leer: leer una corrida de 20 archivos
# =============================================================================
W_L, H_L, SEP_LX, SEP_LY = 4.2, 2.7, 0.75, 1.25
LO_L, HI_L = 1.0, 1e4                       # ms
B_L, G_L = 0.42, 0.06
MODOS = (('todo', 'la corrida entera'),
         ('columnas', r'sólo \texttt{t\_ns}, \texttt{snap}, \texttt{gap}'),
         ('pocos', '10 eventos por archivo'))


def rot_ms(v):
    return {1: '1 ms', 10: '10 ms', 100: '0.1 s', 1000: '1 s', 10000: '10 s'}[int(v)]


def fig_leer(pc):
    l = []
    datos_pc = {m: {fmt: {w: pc[(fmt, False)][w][f'{m}_s'] * 1e3 for w in VENTANAS}
                    for fmt in ('npz', 'lh5')} for m, _ in MODOS}
    filas = (('PC', datos_pc), ('placa', PLACA_LEER_MS))
    paso = W_L / len(VENTANAS)
    ancho_grupo = 2 * B_L + G_L
    alto_total = 2 * H_L + SEP_LY
    for r, (fila, datos) in enumerate(filas):
        y0 = alto_total - (r + 1) * H_L - r * SEP_LY
        l.append(f'\\begin{{scope}}[yshift={f(y0)}cm]')
        for c, (modo, titulo) in enumerate(MODOS):
            x0 = c * (W_L + SEP_LX)
            Y = marco_log(l, x0, W_L, H_L, LO_L, HI_L, rotulo=rot_ms,
                          etiquetas=(c == 0))
            if r == 0:
                l.append(f'\\node[parte, font=\\small] at ({f(x0)},{f(H_L + 0.25)}) '
                         f'{{{titulo}}};')
            for i, w in enumerate(VENTANAS):
                xg = x0 + paso * (i + 0.5) - ancho_grupo / 2
                for j, fmt in enumerate(('npz', 'lh5')):
                    barra(l, f'barra={COLOR[fmt]}', xg + j * (B_L + G_L), B_L,
                          Y(datos[modo][fmt][w]))
                l.append(f'\\node[tick, anchor=north] at '
                         f'({f(x0 + paso * (i + 0.5))},-0.06) {{{w}}};')
        l.append(f'\\node[font=\\small\\bfseries, rotate=90, anchor=south] at '
                 f'(-1.05,{f(H_L / 2)}) {{{fila}}};')
        l.append('\\end{scope}')
    l.append(f'\\node[titeje, anchor=north] at ({f(1.5 * W_L + SEP_LX)},-0.42) '
             '{muestras por canal en la ventana};')
    y, x = -1.1, -0.4
    for fmt in ('npz', 'lh5'):
        l.append(f'\\path[barra={COLOR[fmt]}] ({f(x)},{f(y - 0.12)}) rectangle ++(0.4,0.26);')
        l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
                 f'{{{NOMBRE[fmt]}}};')
        x += 1.75
    return l


# =============================================================================
# bench_lector: con la adquisición corriendo
# =============================================================================
H_C = 4.2
W_CA, W_CB, W_CC = 4.2, 2.7, 5.0
X_CB = W_CA + 1.25
X_CC = X_CB + W_CB + 1.45
B_C, G_C = 0.36, 0.05


def marca(l, fmt, x, y, llena):
    """Círculo para .npz, cuadrado para LH5; llena con C, hueca con Python. El anillo
    blanco separa las marcas que se pisan."""
    forma = 'circle, minimum size=2.0mm' if fmt == 'npz' else \
        'rectangle, minimum size=1.8mm'
    relleno = COLOR[fmt] if llena else 'white'
    l.append(f'\\node[{forma}, inner sep=0pt, draw={COLOR[fmt]}, fill={relleno}, '
             f'line width=0.7pt, preaction={{draw=white, line width=2.1pt}}] '
             f'at ({f(x)},{f(y)}) {{}};')


def fig_lector():
    l = []
    # --------------------------------------------- (a) un lote, solo y con lector
    Y = marco_log(l, 0.0, W_CA, H_C, 0.1, 1000.0, rotulo=lambda v: num(v))
    l.append(f'\\node[parte] at (0,{f(H_C + 0.25)}) {{(a)\\enspace un lote}};')
    l.append(f'\\node[titeje, rotate=90, anchor=south] at (-0.75,{f(H_C / 2)}) '
             '{tiempo de escribir un lote [ms]};')
    paso = W_CA / 2
    ancho_grupo = 4 * B_C + 3 * G_C
    for i, maq in enumerate(('PC', 'placa')):
        xg = paso * (i + 0.5) - ancho_grupo / 2
        k = 0
        for fmt in ('npz', 'lh5'):
            solo, con, _ = LECTOR_MS[maq][fmt]
            barra(l, f'clara={COLOR[fmt]}', xg + k * (B_C + G_C), B_C, Y(solo))
            k += 1
            barra(l, f'barra={COLOR[fmt]}', xg + k * (B_C + G_C), B_C, Y(con))
            k += 1
        l.append(f'\\node[tick, anchor=north] at ({f(paso * (i + 0.5))},-0.06) {{{maq}}};')

    # --------------------------------------------- (b) la mayor demora del lector
    x0 = X_CB
    alto_max = 12.0
    Yb = lambda v: v / alto_max * H_C                       # noqa: E731
    for v in range(0, 13, 3):
        l.append(f'\\draw[guia] ({f(x0)},{f(Yb(v))}) -- ({f(x0 + W_CB)},{f(Yb(v))});')
        l.append(f'\\draw[eje] ({f(x0)},{f(Yb(v))}) -- ++(-0.07,0) node[tick, left] {{{v}}};')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0)},{f(H_C)});')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0 + W_CB)},0);')
    l.append(f'\\node[parte] at ({f(x0)},{f(H_C + 0.25)}) {{(b)\\enspace el lector}};')
    l.append(f'\\node[titeje, rotate=90, anchor=south] at ({f(x0 - 0.55)},{f(H_C / 2)}) '
             '{mayor demora del lector [ms]};')
    paso = W_CB / 2
    ancho_grupo = 2 * B_C + G_C
    for i, maq in enumerate(('PC', 'placa')):
        xg = x0 + paso * (i + 0.5) - ancho_grupo / 2
        for j, fmt in enumerate(('npz', 'lh5')):
            v = LECTOR_MS[maq][fmt][2]
            xb = xg + j * (B_C + G_C)
            barra(l, f'barra={COLOR[fmt]}', xb, B_C, Yb(v))
            l.append(f'\\node[valor, anchor=south] at ({f(xb + B_C / 2)},{f(Yb(v))}) '
                     f'{{{v:g}}};')
        l.append(f'\\node[tick, anchor=north] at ({f(x0 + paso * (i + 0.5))},-0.06) {{{maq}}};')
    l.append(f'\\draw[ref] ({f(x0)},{f(Yb(SWITCH_MS))}) -- ({f(x0 + W_CB)},{f(Yb(SWITCH_MS))});')

    # --------------------------------------------- (c) la pérdida contra la tasa
    x0 = X_CC
    rho_max, p_max = 2.0, 80.0
    X = lambda r: x0 + r / rho_max * W_CC                  # noqa: E731
    Yc = lambda p: p / p_max * H_C                         # noqa: E731
    for p in range(0, 81, 20):
        l.append(f'\\draw[guia] ({f(x0)},{f(Yc(p))}) -- ({f(x0 + W_CC)},{f(Yc(p))});')
        l.append(f'\\draw[eje] ({f(x0)},{f(Yc(p))}) -- ++(-0.07,0) node[tick, left] {{{p}}};')
    for r in (0, 0.5, 1, 1.5, 2):
        l.append(f'\\draw[eje] ({f(X(r))},0) -- ++(0,-0.07) node[tick, below] {{{r:g}}};')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0)},{f(H_C)});')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0 + W_CC)},0);')
    l.append(f'\\node[parte] at ({f(x0)},{f(H_C + 0.25)}) {{(c)\\enspace la pérdida}};')
    l.append(f'\\node[titeje, rotate=90, anchor=south] at ({f(x0 - 0.6)},{f(H_C / 2)}) '
             '{eventos perdidos [\\%]};')
    l.append(f'\\node[titeje, anchor=north] at ({f(x0 + W_CC / 2)},-0.42) '
             f'{{$\\rho$ = tasa $\\cdot\\,\\tau$, con $\\tau$ = {TAU_US} $\\mu$s}};')
    # el modelo: Poisson no paralizable, ρ / (1 + ρ)
    pts = ' '.join(f'({f(X(r))},{f(Yc(100 * r / (1 + r)))})'
                   for r in (k * rho_max / 80 for k in range(81)))
    l.append(f'\\draw[black!45, line width=0.8pt] plot coordinates {{{pts}}};')
    l.append(f'\\node[font=\\scriptsize, black!65, anchor=east, inner sep=1pt] '
             f'at ({f(X(0.27))},{f(Yc(25))}) {{Poisson}};')
    for lector, trazo in (('py', 'dash pattern=on 2.5pt off 1.5pt'), ('c', 'solid')):
        for fmt in ('npz', 'lh5'):
            pts = ' -- '.join(f'({f(X(r))},{f(Yc(p))})'
                              for r, p in zip(RHO, PERDIDA[(lector, fmt)]))
            l.append(f'\\draw[serie={COLOR[fmt]}, {trazo}] {pts};')
    for lector in ('py', 'c'):
        for fmt in ('npz', 'lh5'):
            for r, p in zip(RHO, PERDIDA[(lector, fmt)]):
                marca(l, fmt, X(r), Yc(p), llena=(lector == 'c'))
    l.append(f'\\node[font=\\scriptsize, anchor=west] at ({f(X(2.0) + 0.15)},{f(Yc(68.3))}) '
             '{lector en Python};')
    l.append(f'\\node[font=\\scriptsize, anchor=west] at ({f(X(2.0) + 0.15)},{f(Yc(15.6))}) '
             '{lector en C};')

    # --------------------------------------------- leyenda
    y = -1.25
    x = -0.4
    for fmt in ('npz', 'lh5'):
        l.append(f'\\path[barra={COLOR[fmt]}] ({f(x)},{f(y - 0.12)}) rectangle ++(0.4,0.26);')
        l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
                 f'{{{NOMBRE[fmt]}}};')
        x += 1.6
    l.append(f'\\path[clara=neutro] ({f(x)},{f(y - 0.12)}) rectangle ++(0.4,0.26);')
    l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) {{solo}};')
    x += 1.25
    l.append(f'\\path[barra=neutro] ({f(x)},{f(y - 0.12)}) rectangle ++(0.4,0.26);')
    l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
             '{con un lector compitiendo por el GIL};')
    x = X_CC
    marca(l, 'npz', x + 0.1, y, llena=False)
    marca(l, 'lh5', x + 0.4, y, llena=False)
    l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.6)},{f(y)}) {{Python}};')
    x += 1.95
    marca(l, 'npz', x + 0.1, y, llena=True)
    marca(l, 'lh5', x + 0.4, y, llena=True)
    l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.6)},{f(y)}) {{C}};')
    # la línea de referencia de (b), en un segundo renglón
    y -= 0.5
    l.append(f'\\draw[ref] (-0.4,{f(y)}) -- ++(0.4,0);')
    l.append(f'\\node[anchor=west, font=\\scriptsize] at (0.05,{f(y)}) '
             f'{{intervalo de cambio del GIL de la sesión ({SWITCH_MS:g} ms)}};')
    return l


# =============================================================================
def leer_pc():
    d = json.loads(JSON_PC.read_text())
    out = {}
    for fila in d['filas']:
        fmt, _, comp = fila['variante'].partition('+')
        out.setdefault((fmt, bool(comp)), {})[fila['muestras']] = fila
    return out


def a_pdf_svg(tex):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error',
                        f'-output-directory={tmp}', tex.name], cwd=AQUI, check=True,
                       stdout=subprocess.DEVNULL)
        pdf = Path(tmp) / f'{tex.stem}.pdf'
        shutil.copy(pdf, AQUI / pdf.name)
    subprocess.run(['pdftocairo', '-svg', f'{tex.stem}.pdf', f'{tex.stem}.svg'],
                   cwd=AQUI, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--sin-compilar', action='store_true')
    args = ap.parse_args()
    pc = leer_pc()
    texs = [
        compilar('bench_escribir', fig_escribir(pc),
                 'Lo que aguanta el escritor solo, por formato y ventana'),
        compilar('bench_leer', fig_leer(pc),
                 'Leer una corrida de 20 archivos, de tres maneras'),
        compilar('bench_lector', fig_lector(),
                 'El escritor con la adquisición corriendo'),
    ]
    if not args.sin_compilar:
        for tex in texs:
            a_pdf_svg(tex)
            print(f'{tex.stem}: .tex, .pdf y .svg')


if __name__ == '__main__':
    main()
