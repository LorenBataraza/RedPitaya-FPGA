#!/usr/bin/env python3
"""Las figuras de separacion_trapezoidal.md: el trapecio etapa por etapa y la separacion.

Calcula todo con la misma recursion que mca_trap, en enteros (y comprueba que
coincide con estimadores.trapecio, el modelo contra el que tb_mca_trap compara
bit a bit), y escribe dos figuras en el estilo comun de las figuras TikZ:

  trap_etapas      un pulso solo, registro por registro del RTL: x, d, 16p y
                   Mq*d (las colas que se cancelan), r y la salida
  trap_separacion  dos pulsos: los trapecios de cada uno con la ventana de cada
                   ranura, a dt = 60 y a dt = 30, y el error de F_TRAP contra dt

Los numeros son los de tb_mca_top y d13_trapecio.py: tau = 50 muestras, k = 32,
m = 16, Mq = 792, ventana [36, 44) y sh = 12.

    python3 figuras_separacion.py
"""
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
MCA = AQUI.parents[3]                      # prj/MCA
sys.path.insert(0, str(MCA / "software"))
from API.modelo_rtl.estimadores import trapecio      # noqa: E402

TAU, K, M_MESETA = 50.0, 32, 16
L = K + M_MESETA
MQ = round(16.0 / (math.exp(1.0 / TAU) - 1.0))        # 792
SH, OFF, LW = 12, 36, 3
W = 1 << LW
A1, A2 = 1000, 600


# ----------------------------------------------------------------- el modelo
def pulso(a, t0, n):
    """Exponencial redondeada a enteros, como llega del ADC."""
    t = np.arange(n) - t0
    return np.round(np.where(t >= 0, a * np.exp(-np.maximum(t, 0) / TAU), 0.0)).astype(np.int64)


def retrasar(v, j):
    o = np.zeros_like(v)
    o[j:] = v[:v.size - j]
    return o


def mca_trap(x, mq=MQ):
    """Las senales de mca_trap: d (etapa 3), p (4), r (5) y s (6); t = s >>> sh (7-8)."""
    d = x - retrasar(x, K) - retrasar(x, L) + retrasar(x, K + L)
    p = np.cumsum(d)
    r = 16 * p + mq * d
    s = np.cumsum(r)
    ref = np.round(trapecio(x, K, M_MESETA, mq / 16.0) * 16.0).astype(np.int64)
    assert np.array_equal(s, ref), "la recursion no coincide con estimadores.trapecio"
    return {"x": x, "d": d, "p16": 16 * p, "md": mq * d, "r": r, "t": s >> SH}


def f_trap(t, pie):
    """F_TRAP de la ranura que abrio en `pie`: el promedio de t en [off, off + 2^lw)."""
    return int(np.floor(t[pie + OFF:pie + OFF + W].sum() / W))


# -------------------------------------------------------------------- dibujo
def curva(y, x0, y0, dx, esc, estilo):
    pts = " ".join(f"({x0 + i * dx:.3f},{y0 + v * esc:.3f})" for i, v in enumerate(y))
    return f"\\draw[{estilo}] plot coordinates {{{pts}}};"


def eje(x0, x1, y0, rotulo):
    return [f"\\draw[black!40, line width=0.4pt] ({x0:.3f},{y0:.3f}) -- ({x1:.3f},{y0:.3f});",
            f"\\node[anchor=east, font=\\scriptsize, align=right] at ({x0 - 0.12:.3f},{y0:.3f}) "
            f"{{{rotulo}}};"]


def cota(xa, xb, y, texto, lado="above"):
    return (f"\\draw[<->, line width=0.5pt] ({xa:.3f},{y:.3f}) -- ({xb:.3f},{y:.3f}) "
            f"node[midway, {lado}, nodo, black] {{{texto}}};")


def etapas():
    n, t0, dx, alto = 200, 10, 0.055, 1.25
    c = mca_trap(pulso(A1, t0, n))
    X = lambda i: (t0 + i) * dx                 # noqa: E731  muestra desde el pie -> cm
    x1 = n * dx
    L_ = ["\\node[titulo] at (-2.7,1.0) {\\textbf{Un pulso a través de \\texttt{mca\\_trap}} "
          "\\quad {\\scriptsize registro por registro}};"]
    y = 0.0

    # 1. la entrada
    y -= alto
    L_ += eje(0, x1, y, "entrada\\\\[-1pt]{\\tiny\\ttfamily x\\_q}")
    L_.append(curva(c["x"], 0, y, dx, alto * 0.85 / A1, "line width=0.9pt"))
    L_.append(f"\\node[nodo, anchor=west] at ({X(60):.3f},{y + 0.42:.3f}) "
              f"{{$A\\,e^{{-n/\\tau}}$: la cola dura cientos de muestras}};")

    # 2. la doble diferencia
    y -= alto * 0.6 + 0.45
    esc = alto * 0.5 / np.abs(c["d"]).max()
    L_ += eje(0, x1, y, "etapa 3\\\\[-1pt]{\\tiny\\ttfamily d3}")
    L_.append(curva(c["d"], 0, y, dx, esc, "line width=0.9pt"))
    for j, txt in ((0, "$+x$"), (K, "$-x_{-k}$"), (L, "$-x_{-l}$"), (K + L, "$+x_{-k-l}$")):
        L_.append(f"\\node[nodo, anchor=south] at ({X(j):.3f},{y + alto * 0.52:.3f}) {{{txt}}};")
    L_.append(f"\\node[nodo, anchor=west, align=left] at ({X(K + L + 12):.3f},{y + 0.25:.3f}) "
              "{cuatro copias del pulso: la cola\\\\sigue (más chica, pero sigue)};")

    # 3. 16p y Mq*d
    y -= alto * 1.05 + 0.45
    esc = alto * 0.5 / max(np.abs(c["p16"]).max(), np.abs(c["md"]).max())
    L_ += eje(0, x1, y, "etapas 4 y 5\\\\[-1pt]{\\tiny\\ttfamily 16·p4 \\textnormal{y} Mq·d4}")
    L_.append(curva(c["md"], 0, y, dx, esc, "azul!85!black, line width=0.8pt"))
    L_.append(curva(c["p16"], 0, y, dx, esc, "line width=0.9pt"))
    j = 2 * K + M_MESETA + 25
    L_.append(f"\\node[nodo, anchor=north, text=black] at ({X(j + 20):.3f},{y + c['p16'][t0 + j] * esc - 0.06:.3f}) "
              f"{{$16p$: termina con una cola \\textbf{{negativa}}}};")
    L_.append(f"\\node[nodo, anchor=south, text=azul!70!black] at ({X(j + 20):.3f},{y + c['md'][t0 + j] * esc + 0.06:.3f}) "
              f"{{$M_q\\,d$: la misma cola, \\textbf{{positiva}}}};")
    L_.append(f"\\node[nodo, anchor=south west, text=azul!70!black] at ({X(2):.3f},{y + alto * 0.45:.3f}) "
              f"{{$M_q\\,d$}};")
    jn = 2 * K + M_MESETA + 5
    L_.append(f"\\node[nodo, anchor=north east, align=right, black] at ({x1:.3f},{y - 0.5:.3f}) "
              f"{{a {jn} muestras del pie: $16p = {c['p16'][t0 + jn]:+d}$, "
              f"$M_q\\,d = {c['md'][t0 + jn]:+d}$,\\\\suman $r = {c['r'][t0 + jn]:+d}$ "
              f"(lo que queda es el redondeo de la entrada)}};")

    # 4. r
    y -= alto * 1.05 + 0.5
    esc = alto * 0.5 / np.abs(c["r"]).max()
    L_ += eje(0, x1, y, "etapa 5\\\\[-1pt]{\\tiny\\ttfamily r5 = 16·p4 + Mq·d4}")
    L_.append(curva(c["r"], 0, y, dx, esc, "line width=0.9pt"))
    hr = c["r"][t0 + 2] * esc
    L_.append(cota(X(0), X(K), y + hr + 0.13, "$k$"))
    L_.append(cota(X(K), X(L), y + 0.13, "$m$"))
    L_.append(cota(X(L), X(L + K), y - hr - 0.13, "$k$", "below"))
    L_.append(f"\\node[nodo, anchor=west, align=left] at ({X(L + K + 12):.3f},{y + 0.2:.3f}) "
              "{las colas se cancelaron: $r$ es \\textbf{cero}\\\\desde $2k+m$ muestras después del pie};")

    # 5. la salida
    y -= alto * 0.5 + 0.55 + alto
    esc = alto * 0.85 / c["t"].max()
    L_ += eje(0, x1, y, "etapas 6 a 8\\\\[-1pt]{\\tiny\\ttfamily t8 = (s6 >>> sh)}")
    L_.append(f"\\fill[verde, opacity=0.55] ({X(OFF):.3f},{y:.3f}) rectangle "
              f"({X(OFF + W):.3f},{y + alto * 0.9:.3f});")
    L_.append(curva(c["t"], 0, y, dx, esc, "line width=0.9pt"))
    h = c["t"].max() * esc
    L_.append(cota(X(0), X(2 * K + M_MESETA), y - 0.2, "vuelve a cero en $2k+m$", "below"))
    L_.append(f"\\node[nodo, anchor=west] at ({X(2 * K + M_MESETA + 4):.3f},{y + h * 0.6:.3f}) "
              f"{{altura $16\\,A\\,k\\,(1+M) \\gg$ sh $= {c['t'].max()}$}};")
    L_.append(f"\\node[nodo, anchor=south, text=verde!50!black] at ({X(OFF + W / 2):.3f},{y + alto * 0.9:.3f}) "
              f"{{ventana: \\texttt{{F\\_TRAP}} $= {f_trap(c['t'], t0)}$}};")

    # eje de muestras, desde el pie
    L_.append(f"\\foreach \\n in {{0, 40, ..., {n - t0 - 30}}} \\draw[black!45] ({{({t0} + \\n)*{dx}}},{y - 0.75:.3f}) "
              f"-- ++(0,-0.06) node[below, nodo] {{\\n}};")
    L_.append(f"\\draw[black!45] (0,{y - 0.75:.3f}) -- ({x1:.3f},{y - 0.75:.3f});")
    L_.append(f"\\node[nodo, anchor=north] at ({x1 / 2:.3f},{y - 1.05:.3f}) {{muestras desde el pie}};")
    for j in (0, K, L, K + L):
        L_.insert(1, f"\\draw[black!12, line width=0.4pt] ({X(j):.3f},{-0.1:.3f}) -- ({X(j):.3f},{y - 0.75:.3f});")
    return L_


def separacion():
    n, t0, dx, alto = 170, 8, 0.06, 1.35
    X = lambda i: (t0 + i) * dx                 # noqa: E731
    x1 = n * dx
    ta = mca_trap(pulso(A1, t0, n))["t"]
    L_ = ["\\node[titulo] at (-2.7,1.0) {\\textbf{Dos pulsos, una salida, dos ventanas} "
          "\\quad {\\scriptsize cada ranura promedia la salida común en su propia ventana}};"]
    y = 0.0
    esc = alto * 0.85 / ta.max()

    for dt in (60, 30):
        tb = mca_trap(pulso(A2, t0 + dt, n))["t"]
        suma = mca_trap(pulso(A1, t0, n) + pulso(A2, t0 + dt, n))["t"]
        a_ok = dt >= OFF + W
        b_ok = dt + OFF >= 2 * K + M_MESETA - 1
        y -= alto + 1.15
        L_ += eje(0, x1, y, f"$\\Delta t = {dt}$")
        L_.append(f"\\fill[{'verde' if a_ok else 'rojo'}, opacity=0.5] ({X(OFF):.3f},{y:.3f}) "
                  f"rectangle ({X(OFF + W):.3f},{y + alto * 0.92:.3f});")
        L_.append(f"\\fill[{'verde' if b_ok else 'rojo'}, opacity=0.5] ({X(dt + OFF):.3f},{y:.3f}) "
                  f"rectangle ({X(dt + OFF + W):.3f},{y + alto * 0.92:.3f});")
        L_.append(curva(suma, 0, y, dx, esc, "black!35, line width=2.2pt"))
        L_.append(curva(ta, 0, y, dx, esc, "line width=0.8pt"))
        L_.append(curva(tb, 0, y, dx, esc, "azul!85!black, line width=0.8pt, dashed"))
        L_.append(f"\\node[nodo, anchor=south, black] at ({X(OFF + W / 2):.3f},{y + alto * 0.92:.3f}) "
                  f"{{ranura de A}};")
        L_.append(f"\\node[nodo, anchor=south, text=azul!70!black] at ({X(dt + OFF + W / 2):.3f},"
                  f"{y + alto * 0.92:.3f}) {{ranura de B}};")
        fa, fb = f_trap(suma, t0), f_trap(suma, t0 + dt)
        ra, rb = f_trap(ta, t0), f_trap(tb, t0 + dt)
        L_.append(f"\\node[nodo, anchor=north east, align=right, black] at ({x1:.3f},{y + alto:.3f}) "
                  f"{{A: {fa} (solo {ra}, {100 * (fa / ra - 1):+.1f}\\,\\%)\\\\"
                  f"B: {fb} (solo {rb}, {100 * (fb / rb - 1):+.1f}\\,\\%)}};")
        # las dos condiciones, con flechas
        yc = y - 0.22
        L_.append(f"\\draw[|-|, line width=0.5pt] ({X(0):.3f},{yc:.3f}) -- ({X(2 * K + M_MESETA - 1):.3f},{yc:.3f}) "
                  f"node[pos=0.25, below, nodo] {{A dura $2k+m$}};")
        L_.append(f"\\draw[->, line width=0.5pt, azul!80!black] ({X(dt):.3f},{yc - 0.42:.3f}) -- "
                  f"({X(dt):.3f},{y - 0.02:.3f});")
        L_.append(f"\\node[nodo, anchor=north, text=azul!70!black] at ({X(dt):.3f},{yc - 0.42:.3f}) "
                  f"{{pie de B}};")

    # el error contra dt
    y -= alto + 1.6
    dts = list(range(10, 81))
    ea, eb = [], []
    a_solo = f_trap(ta, t0)
    for dt in dts:
        tb = mca_trap(pulso(A2, t0 + dt, n))["t"]
        suma = mca_trap(pulso(A1, t0, n) + pulso(A2, t0 + dt, n))["t"]
        ea.append(100 * (f_trap(suma, t0) / a_solo - 1))
        eb.append(100 * (f_trap(suma, t0 + dt) / f_trap(tb, t0 + dt) - 1))
    tope = 60.0
    ex = lambda d: (d - 10) * (x1 / 70)         # noqa: E731
    ey = lambda e: y + min(e, tope) / tope * alto * 1.3   # noqa: E731
    L_.append(f"\\draw[black!45] (0,{y:.3f}) -- ({x1:.3f},{y:.3f});")
    L_.append(f"\\draw[black!45] (0,{y:.3f}) -- (0,{ey(tope):.3f});")
    for e in (0, 20, 40, 60):
        L_.append(f"\\node[nodo, anchor=east] at (-0.05,{ey(e):.3f}) {{{e}\\,\\%}};")
        L_.append(f"\\draw[black!10] (0,{ey(e):.3f}) -- ({x1:.3f},{ey(e):.3f});")
    for d in range(10, 81, 10):
        L_.append(f"\\draw[black!45] ({ex(d):.3f},{y:.3f}) -- ++(0,-0.06) node[below, nodo] {{{d}}};")
    L_.append(f"\\node[nodo, anchor=north] at ({x1 / 2:.3f},{y - 0.3:.3f}) {{$\\Delta t$, muestras entre los pies}};")
    L_.append(f"\\node[anchor=east, font=\\scriptsize, align=right] at (-0.75,{ey(tope / 2):.3f}) "
              f"{{error de\\\\\\texttt{{F\\_TRAP}}}};")
    for dl, txt, lado in ((OFF + W, f"$\\mathrm{{off}} + 2^{{lw}} = {OFF + W}$", "south east"),
                          (K + M_MESETA, f"$k+m = {K + M_MESETA}$", "south west")):
        L_.append(f"\\draw[black!50, dashed] ({ex(dl):.3f},{y:.3f}) -- ({ex(dl):.3f},{ey(tope):.3f});")
        L_.append(f"\\node[nodo, anchor={lado}, black] at ({ex(dl):.3f},{ey(tope):.3f}) {{{txt}}};")
    pa = " ".join(f"({ex(d):.3f},{ey(e):.3f})" for d, e in zip(dts, ea))
    pb = " ".join(f"({ex(d):.3f},{ey(e):.3f})" for d, e in zip(dts, eb))
    L_.append(f"\\draw[line width=0.9pt] plot coordinates {{{pa}}};")
    L_.append(f"\\draw[azul!85!black, line width=0.9pt, dashed] plot coordinates {{{pb}}};")
    L_.append(f"\\draw[line width=0.9pt] ({ex(55):.3f},{ey(42):.3f}) -- ++(0.5,0) "
              f"node[right, nodo, black] {{A, el primero}};")
    L_.append(f"\\draw[azul!85!black, line width=0.9pt, dashed] ({ex(55):.3f},{ey(32):.3f}) -- ++(0.5,0) "
              f"node[right, nodo, text=azul!70!black] {{B, el segundo (recortado a 60\\,\\%)}};")
    return L_


PLANTILLA = r"""%% %s. GENERADO por figuras_separacion.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../../figuras/estilo_tikz.tex}
\begin{document}
\begin{tikzpicture}[fondo]
%s
\end{tikzpicture}
\end{document}
"""


def escribir(nombre, lineas):
    tex = AQUI / f"{nombre}.tex"
    tex.write_text(PLANTILLA % (nombre, "\n".join(lineas)))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                        f"-output-directory={tmp}", tex.name],
                       cwd=AQUI, check=True, capture_output=True)
        pdf = AQUI / f"{nombre}.pdf"
        shutil.copy(Path(tmp) / f"{nombre}.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print(f"escrito {nombre}.tex, .pdf y .svg")


def main():
    escribir("trap_etapas", etapas())
    escribir("trap_separacion", separacion())


if __name__ == "__main__":
    main()
