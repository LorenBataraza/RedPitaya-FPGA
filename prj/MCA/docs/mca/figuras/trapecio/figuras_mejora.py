#!/usr/bin/env python3
"""Cuanto mejora el trapecio segun la separacion: el error de cada estimador contra dt.

Con parametros de la placa (cola de 2 us = 250 muestras a 125 MS/s, k = 64,
m = 48, compuerta de 384 muestras, ventana de la meseta [80, 96) y ruido
blanco de 4 cuentas por muestra) compara cuatro maneras de medir la amplitud de
un pulso que tiene otro cerca:

  pico              el maximo de la ventana (F_PEAK)
  integral          la suma de la ventana (F_INT)
  trapecio          el promedio de la meseta (F_TRAP), con la misma recursion
                    entera que mca_trap
  integral - cola   la integral menos la cola del pulso anterior extrapolada:
                    el nivel justo antes del pie (P = 16 muestras, ajustado a
                    la caida) por e^(-j/tau), sumado sobre la ventana. NO esta
                    en el RTL: es la propuesta de "una linea de base por
                    ranura" para compararla

Escribe trap_mejora.tex en el estilo comun de las figuras TikZ y lo compila a
.pdf y .svg. Tarda unos segundos (Monte Carlo de 300 realizaciones por punto).

    python3 figuras_mejora.py
"""
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
TEX = AQUI / "trap_mejora.tex"

FS = 125.0                      # MS/s
TAU = 250.0                     # 2 us
K, M_MESETA = 64, 48
L = K + M_MESETA
MQ = round(16.0 / (math.exp(1.0 / TAU) - 1.0))        # 3992
SH = round(math.log2(16 * K * (1 + MQ / 16.0) / 8))    # 15: amplitud A -> ~8A
G = 384                         # compuerta larga
OFF, LW = 80, 4
W = 1 << LW
P = 16                          # muestras antes del pie para estimar la cola
SIGMA = 4.0                     # ruido blanco por muestra, en cuentas
A1, A2 = 1000, 600
R = 300                         # realizaciones por punto
CRITERIO = 1.0                  # %: lo que cuenta como "mide bien" en el panel de tasa

rng = np.random.default_rng(2026)
J = np.arange(1, P + 1)
EJ = np.exp(J / TAU)
COLA = np.exp(-np.arange(G) / TAU)

ESTIMADORES = [   # clave, nombre, estilo de linea
    ("pico", "pico", "rojo!75!black, line width=0.8pt, dash pattern=on 1.5pt off 1.5pt"),
    ("integral", "integral", "black, line width=0.8pt, dashed"),
    ("int_c", "integral $-$ cola", "verde!55!black, line width=1.0pt"),
    ("trap", "trapecio", "azul!85!black, line width=1.6pt"),
]


# ------------------------------------------------------------------ modelo
def pulso(a, t0, n):
    t = np.arange(n) - t0
    return np.round(np.where(t >= 0, a * np.exp(-np.maximum(t, 0) / TAU), 0.0)).astype(np.int64)


def retrasar(v, j):
    o = np.zeros_like(v)
    o[..., j:] = v[..., :v.shape[-1] - j]
    return o


def trapecio(x):
    d = x - retrasar(x, K) - retrasar(x, L) + retrasar(x, K + L)
    p = np.cumsum(d, -1)
    return np.cumsum(16 * p + MQ * d, -1) >> SH


def estimar(x, t):
    """Los cuatro estimadores de la ranura que abre en la muestra t (x: [..., n])."""
    w = x[..., t:t + G]
    xc = np.maximum(w, 0)                                   # la ranura satura a >= 0
    y0 = (x[..., t - J] * EJ).sum(-1) / (EJ * EJ).sum()     # nivel de la cola en el pie
    return {"pico": xc.max(-1).astype(float), "integral": xc.sum(-1).astype(float),
            "trap": trapecio(x)[..., t + OFF:t + OFF + W].sum(-1) / W,
            "int_c": (w - y0[..., None] * COLA).sum(-1)}


def error_rms(dts, a1, a2, n=2800, t0=200, ruido=True):
    """Error relativo (%) de A y de B contra dt: RMS con ruido, o el sesgo sin ruido."""
    xa = pulso(a1, t0, n)
    ref_a = {k: v.item() for k, v in estimar(xa[None], t0).items()}
    ea = {k: [] for k in ref_a}
    eb = {k: [] for k in ref_a}
    for dt in dts:
        xb = pulso(a2, t0 + dt, n)
        ref_b = {k: v.item() for k, v in estimar(xb[None], t0 + dt).items()}
        x = (xa + xb)[None]
        if ruido:
            x = x + np.round(rng.normal(0, SIGMA, (R, n))).astype(np.int64)
        va, vb = estimar(x, t0), estimar(x, t0 + dt)
        for k in ref_a:
            ea[k].append(100 * np.sqrt(np.mean((va[k] - ref_a[k]) ** 2)) / ref_a[k])
            eb[k].append(100 * np.sqrt(np.mean((vb[k] - ref_b[k]) ** 2)) / ref_b[k])
    return ea, eb


def umbral(dts, err):
    """El primer dt desde el que el error queda siempre por debajo del criterio."""
    for i, d in enumerate(dts):
        if all(e < CRITERIO for e in err[i:]):
            return d
    return None


# ------------------------------------------------------------------ dibujo
class Ejes:
    def __init__(self, x0, y0, ancho, alto, xr, yr, xlog=True, ylog=True):
        self.x0, self.y0, self.ancho, self.alto = x0, y0, ancho, alto
        self.xr, self.yr, self.xlog, self.ylog = xr, yr, xlog, ylog

    def _f(self, v, r, log, largo):
        if log:
            v = min(max(v, r[0]), r[1])
            return largo * (math.log10(v) - math.log10(r[0])) / (math.log10(r[1]) - math.log10(r[0]))
        v = min(max(v, r[0]), r[1])
        return largo * (v - r[0]) / (r[1] - r[0])

    def X(self, v):
        return self.x0 + self._f(v, self.xr, self.xlog, self.ancho)

    def Y(self, v):
        return self.y0 + self._f(v, self.yr, self.ylog, self.alto)

    def marco(self, xt, yt, xlab, ylab, fmt_y=lambda v: f"{v:g}"):
        L = [f"\\draw[black!50, line width=0.4pt] ({self.x0:.3f},{self.y0:.3f}) rectangle "
             f"({self.x0 + self.ancho:.3f},{self.y0 + self.alto:.3f});"]
        for v in yt:
            L.append(f"\\draw[black!10] ({self.x0:.3f},{self.Y(v):.3f}) -- ({self.x0 + self.ancho:.3f},{self.Y(v):.3f});")
            L.append(f"\\node[nodo, anchor=east] at ({self.x0 - 0.04:.3f},{self.Y(v):.3f}) {{{fmt_y(v)}}};")
        for v in xt:
            L.append(f"\\draw[black!10] ({self.X(v):.3f},{self.y0:.3f}) -- ({self.X(v):.3f},{self.y0 + self.alto:.3f});")
            L.append(f"\\node[nodo, anchor=north] at ({self.X(v):.3f},{self.y0 - 0.04:.3f}) {{{v:g}}};")
        L.append(f"\\node[nodo, anchor=north] at ({self.x0 + self.ancho / 2:.3f},{self.y0 - 0.32:.3f}) {{{xlab}}};")
        L.append(f"\\node[font=\\scriptsize, anchor=south, rotate=90] at ({self.x0 - 0.62:.3f},"
                 f"{self.y0 + self.alto / 2:.3f}) {{{ylab}}};")
        return L

    def curva(self, xs, ys, estilo):
        pts = " ".join(f"({self.X(a):.3f},{self.Y(b):.3f})" for a, b in zip(xs, ys))
        return f"\\draw[{estilo}] plot coordinates {{{pts}}};"


def panel_error(e, x0, y0, dts, err, titulo, rotulos, marcas):
    L = [f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at "
         f"({x0:.3f},{y0 + e.alto + 0.42:.3f}) {{{titulo}}};"]
    L += e.marco([10, 20, 50, 100, 200, 500, 1000, 2000], [0.1, 1, 10, 100],
                 "$\\Delta t$, muestras", "error RMS de la amplitud",
                 fmt_y=lambda v: f"{v:g}\\,\\%")
    # eje de arriba en microsegundos
    for us in (0.1, 0.2, 0.5, 1, 2, 5, 10):
        xm = e.X(us * FS)
        L.append(f"\\draw[black!50] ({xm:.3f},{y0 + e.alto:.3f}) -- ++(0,0.05) node[above, nodo] {{{us:g}}};")
    L.append(f"\\node[nodo, anchor=west] at ({x0 + e.ancho + 0.02:.3f},{y0 + e.alto + 0.12:.3f}) {{µs}};")
    L.append(f"\\draw[black!45, dashed] ({x0:.3f},{e.Y(CRITERIO):.3f}) -- ({x0 + e.ancho:.3f},{e.Y(CRITERIO):.3f});")
    for xm, txt in marcas:
        L.append(f"\\draw[azul!60!black, line width=0.4pt, dotted] ({e.X(xm):.3f},{y0:.3f}) -- "
                 f"({e.X(xm):.3f},{y0 + e.alto:.3f});")
        L.append(f"\\node[nodo, anchor=south west, text=azul!60!black, rotate=90] at "
                 f"({e.X(xm) + 0.02:.3f},{y0 + 0.05:.3f}) {{{txt}}};")
    for clave, _, estilo in ESTIMADORES:
        if clave in err:
            L.append(e.curva(dts, err[clave], estilo))
    for clave, (xd, yd, ancla) in rotulos.items():
        nombre, estilo = next((n, s) for k, n, s in ESTIMADORES if k == clave)
        color = estilo.split(",")[0]
        L.append(f"\\node[nodo, anchor={ancla}, text={color}, fill=white, inner sep=1pt] at "
                 f"({e.X(xd):.3f},{e.Y(yd):.3f}) {{{nombre}}};")
    return L


def figura():
    dts = [int(v) for v in np.unique(np.round(np.logspace(1, math.log10(2000), 46)))]
    ea, eb = error_rms(dts, A1, A2)
    # el panel de tasa usa vecinos de la misma amplitud y el sesgo sin ruido, en
    # una grilla de a una muestra: los umbrales salen exactos
    fino = list(range(1, 2001))
    sa, sb = error_rms(fino, 1000, 1000, ruido=False)
    u_prev = {k: umbral(fino, sb[k]) for k in sb}
    u_next = {k: umbral(fino, sa[k]) for k in sa}

    L = ["\\node[titulo] at (-1.4,6.45) {\\textbf{Cuánto mejora según la separación} \\quad "
         "{\\scriptsize cola de 2\\,µs, $k$ = 64, $m$ = 48, compuerta de 384, ruido de 4 cuentas por muestra}};"]
    eB = Ejes(0.0, 1.0, 6.2, 4.2, (10, 2000), (0.05, 300))
    eA = Ejes(8.0, 1.0, 6.2, 4.2, (10, 2000), (0.05, 300))
    L += panel_error(eB, 0.0, 1.0, dts, eb, f"B, el segundo ({A2}, sobre la cola de A = {A1})",
                     {"pico": (25, 180, "south west"), "int_c": (25, 0.24, "south west"),
                      "trap": (300, 0.17, "south west"), "integral": (900, 6, "south west")},
                     [(2 * K + M_MESETA - 1 - OFF, "trapecio limpio")])
    L += panel_error(eA, 8.0, 1.0, dts, ea, f"A, el primero ({A1}, con B = {A2} adentro de su ventana)",
                     {"pico": (25, 30, "north east"), "integral": (200, 75, "south"),
                      "trap": (120, 0.12, "south west")},
                     [(OFF + W, "trapecio limpio"), (G, "fin de la compuerta")])

    # --- la tasa ------------------------------------------------------------
    eT = Ejes(0.0, -5.0, 6.2, 3.6, (5, 2000), (0, 100), xlog=True, ylog=False)
    L.append(f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at (0,{-5.0 + 3.6 + 0.18:.3f}) "
             f"{{Qué fracción de los eventos mide bien (error $<$ {CRITERIO:g}\\,\\%) con arribos Poisson}};")
    L += eT.marco([5, 10, 20, 50, 100, 200, 500, 1000, 2000], [0, 25, 50, 75, 100],
                  "tasa, kcps", "eventos limpios", fmt_y=lambda v: f"{v:g}\\,\\%")
    tasas = np.logspace(math.log10(5), math.log10(2000), 80)
    filas = []
    for clave, nombre, estilo in ESTIMADORES:
        u = u_prev[clave] + u_next[clave]
        ys = [100 * math.exp(-t * 1e3 / (FS * 1e6) * u) for t in tasas]
        L.append(eT.curva(tasas, ys, estilo))
        filas.append((nombre, u_prev[clave], u_next[clave], u, 100 * math.exp(-100e3 / (FS * 1e6) * u)))
    L.append(f"\\draw[black!45, dashed] ({eT.X(100):.3f},{eT.y0:.3f}) -- ({eT.X(100):.3f},{eT.y0 + eT.alto:.3f});")
    # un rotulo por valor: los que dan lo mismo comparten curva y rotulo
    por_u = {}
    for nombre, up, un, u, f100 in filas:
        por_u.setdefault(round(f100), []).append((nombre, f100))
    for u, grupo in por_u.items():
        nombre = " y ".join(n for n, _ in grupo)
        clave, _, estilo = next(e for e in ESTIMADORES if e[1] == grupo[-1][0])
        color = estilo.split(",")[0]
        L.append(f"\\node[nodo, anchor=west, text={color}, fill=white, inner sep=1pt] at "
                 f"({eT.X(100) + 0.05:.3f},{eT.Y(grupo[0][1]):.3f}) {{{nombre}: {grupo[0][1]:.0f}\\,\\%}};")
    # la tabla de los umbrales
    cuerpo = ["& \\textbf{anterior} & \\textbf{siguiente} & \\textbf{suma}\\\\[1pt]"]
    for nombre, up, un, u, _ in filas:
        cuerpo.append(f"{nombre} & {up} & {un} & {u}\\\\")
    L.append(f"\\node[anchor=north west, font=\\scriptsize, draw=black!40, rounded corners=2pt, inner sep=4pt] "
             f"at (8.0,{-5.0 + 3.6 + 0.3:.3f}) {{\\begin{{tabular}}{{@{{}}l@{{\\hspace{{6pt}}}}r@{{\\hspace{{6pt}}}}r"
             f"@{{\\hspace{{6pt}}}}r@{{}}}}{''.join(cuerpo)}\\end{{tabular}}}};")
    # Lo que explica la tabla va en el epígrafe (trap_mejora.txt), no en la figura.
    return L, filas


PLANTILLA = r"""%% Cuanto mejora el trapecio. GENERADO por figuras_mejora.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath}
\usepackage[none]{hyphenat}
\input{../../../figuras/estilo_tikz.tex}
\begin{document}
\begin{tikzpicture}[fondo]
%s
\end{tikzpicture}
\end{document}
"""


def main():
    lineas, filas = figura()
    TEX.write_text(PLANTILLA % "\n".join(lineas))
    for nombre, up, un, u, f100 in filas:
        print(f"{nombre:18s} anterior {up:5d}  siguiente {un:5d}  suma {u:5d}  limpios a 100 kcps {f100:5.1f} %")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                        f"-output-directory={tmp}", TEX.name],
                       cwd=AQUI, check=True, capture_output=True)
        pdf = AQUI / "trap_mejora.pdf"
        shutil.copy(Path(tmp) / "trap_mejora.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print("escrito trap_mejora.tex, .pdf y .svg")


if __name__ == "__main__":
    main()
