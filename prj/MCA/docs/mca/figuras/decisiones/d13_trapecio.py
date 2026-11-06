#!/usr/bin/env python3
"""D13: el conformado trapezoidal separa dos pulsos que se pisan en la entrada.

Calcula las curvas con el modelo de referencia del RTL (estimadores.trapecio,
el mismo contra el que tb_mca_trap compara bit a bit) y escribe d13_trapecio.tex
en el estilo comun de las figuras TikZ. Despues lo compila a .pdf y .svg.

Los numeros son los de la seccion 10 de tb_mca_top: pulsos exponenciales de
tau = 50 muestras, trapecio de k = 32, m = 16, M exacto, ventana de la meseta
[36, 44) desde el pie y sh = 12. Un pulso de A = 1000 da F_TRAP = 6313.

    python3 d13_trapecio.py
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

TEX = AQUI / "d13_trapecio.tex"

TAU, K, M_MESETA = 50.0, 32, 16
MQ = round(16.0 / (math.exp(1.0 / TAU) - 1.0))        # 792
SH, OFF, LW = 12, 36, 3
T0, N = 20, 300                                        # pie del primero, largo
A1, A2 = 1000.0, 600.0

DX = 0.042            # cm por muestra
ALTO = 1.9            # cm por panel


def pulso(a, t0):
    t = np.arange(N) - t0
    return np.where(t >= 0, a * np.exp(-np.maximum(t, 0) / TAU), 0.0)


def conformar(x):
    """Lo que entrega mca_trap: 16 * trapecio, corrido sh, en enteros."""
    x = np.round(x).astype(np.int64)
    s = np.round(trapecio(x, K, M_MESETA, MQ / 16.0) * 16.0).astype(np.int64)
    return s >> SH


def curva(y, y0, escala, estilo):
    pts = " ".join(f"({i * DX:.3f},{y0 + v * escala:.3f})" for i, v in enumerate(y))
    return f"\\draw[{estilo}] plot coordinates {{{pts}}};"


def banda(a, b, y0, color, texto=None):
    """La ventana de la meseta de una ranura: [a, b) en muestras."""
    l = [f"\\fill[{color}, opacity=0.55] ({a * DX:.3f},{y0:.3f}) rectangle "
         f"({b * DX:.3f},{y0 + 0.88 * ALTO:.3f});"]
    if texto:
        l.append(f"\\node[nodo, anchor=south] at ({(a + b) / 2 * DX:.3f},{y0 + ALTO:.3f}) {{{texto}}};")
    return l


def ejes(y0, rotulo):
    return [f"\\draw[black!45, line width=0.4pt] (0,{y0:.3f}) -- ({N * DX:.3f},{y0:.3f});",
            f"\\node[anchor=east, font=\\scriptsize, align=right] at (-0.15,{y0 + ALTO / 2:.3f}) "
            f"{{{rotulo}}};"]


def panel_trapecio(y0, dt, limpio):
    x1, x2 = pulso(A1, T0), pulso(A2, T0 + dt)
    s1, s2, s = conformar(x1), conformar(x2), conformar(x1 + x2)
    esc = ALTO * 0.85 / 6313.0
    color = "verde" if limpio else "rojo"
    l = ejes(y0, f"trapecio\\\\[-1pt]{{\\tiny $\\Delta t = {dt}$}}")
    l += banda(T0 + OFF, T0 + OFF + (1 << LW), y0, color)
    l += banda(T0 + dt + OFF, T0 + dt + OFF + (1 << LW), y0, color)
    l.append(curva(s1, y0, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(s2, y0, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(s, y0, esc, "line width=0.9pt"))
    # lo que mide cada ranura: el promedio de la salida sobre su ventana, y lo
    # mismo con cada pulso solo
    def medida(y, t):
        return int(np.floor(y[t + OFF:t + OFF + (1 << LW)].sum() / (1 << LW)))
    m1, m2 = medida(s, T0), medida(s, T0 + dt)
    r1, r2 = medida(s1, T0), medida(s2, T0 + dt)
    xt = (N - 4) * DX
    l.append(f"\\node[anchor=north east, font=\\scriptsize, align=right] at ({xt:.3f},{y0 + ALTO:.3f}) "
             f"{{\\texttt{{F\\_TRAP}}: {m1} y {m2}\\\\[-1pt]"
             f"{{\\tiny cada uno solo: {r1} y {r2}}}}};")
    return l, s


def figura():
    l = [f"\\node[titulo] at (-2.0,{3 * ALTO + 1.75:.3f}) "
         "{\\textbf{D13 · El trapecio separa dos pulsos que se pisan en la entrada}};"]

    # --- entrada ----------------------------------------------------------
    y0 = 2 * ALTO + 1.0
    x1, x2 = pulso(A1, T0), pulso(A2, T0 + 60)
    esc = ALTO * 0.85 / 1300.0
    l += ejes(y0, "entrada\\\\[-1pt]{\\tiny $x = $ dat $-$ base}")
    l.append(curva(x1, y0, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(x2, y0, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(x1 + x2, y0, esc, "line width=0.9pt"))
    pico2 = (x1 + x2)[T0 + 60]
    l.append(f"\\node[nodo, anchor=west] at ({(T0 + 62) * DX:.3f},{y0 + pico2 * esc:.3f}) "
             f"{{pico del segundo: {pico2:.0f}, no {A2:.0f}}};")
    l.append(f"\\node[nodo, anchor=south west] at ({(T0 + 2) * DX:.3f},{y0 + A1 * esc:.3f}) "
             f"{{$A = {A1:.0f}$, $\\tau = {TAU:.0f}$}};")
    l.append(f"\\draw[<->, line width=0.5pt] ({T0 * DX:.3f},{y0 - 0.18:.3f}) -- "
             f"({(T0 + 60) * DX:.3f},{y0 - 0.18:.3f}) node[midway, below, nodo] {{$\\Delta t = 60$}};")

    # --- trapecios ----------------------------------------------------------
    y1 = ALTO + 0.5
    lp, s = panel_trapecio(y1, 60, True)
    l += lp
    # cotas de k y m sobre el primer trapecio
    esc_t = ALTO * 0.85 / 6313.0
    yk = y1 + 6313 * esc_t + 0.12
    l.append(f"\\draw[<->, line width=0.5pt] ({T0 * DX:.3f},{yk:.3f}) -- ({(T0 + K) * DX:.3f},{yk:.3f}) "
             f"node[midway, above, nodo] {{$k$}};")
    l.append(f"\\draw[<->, line width=0.5pt] ({(T0 + K) * DX:.3f},{yk:.3f}) -- "
             f"({(T0 + K + M_MESETA) * DX:.3f},{yk:.3f}) node[midway, above, nodo] {{$m$}};")
    l.append(f"\\node[nodo, anchor=north, text=verde!50!black] at ({(T0 + OFF + 4) * DX:.3f},{y1 - 0.02:.3f}) "
             "{ventana de la ranura};")

    lp, _ = panel_trapecio(0.0, 30, False)
    l += lp

    # eje de muestras
    l.append(f"\\foreach \\n in {{0, 50, ..., {N}}} \\draw[black!45] (\\n*{DX},0) -- ++(0,-0.06) "
             "node[below, nodo] {\\n};")
    l.append(f"\\node[nodo, anchor=north] at ({N / 2 * DX:.3f},-0.32) {{muestras}};")

    # --- la recursion, a la derecha -----------------------------------------
    xb = N * DX + 2.4
    yb = 3 * ALTO + 0.7
    paso = 0.8
    cajas = [
        ("dd", "doble diferencia\\\\[-1pt]{\\tiny $d = x - x_{-k} - x_{-l} + x_{-k-l}$}"),
        ("p", "$p \\mathrel{+}= d$"),
        ("r", "$r = 16\\,p + M_q\\, d$\\\\[-1pt]{\\tiny polo-cero, un DSP48}"),
        ("s", "$s \\mathrel{+}= r$"),
        ("sh", "$s \\gg$ sh, saturada"),
        ("ran", "cada ranura promedia\\\\[-1pt]$[\\mathrm{off}, \\mathrm{off} + 2^{lw})$"),
    ]
    for i, (n, t) in enumerate(cajas):
        estilo = "captura" if n == "ran" else "datos"
        l.append(f"\\node[{estilo}, text width=3.3cm, align=center, minimum height=0.55cm, "
                 f"font=\\scriptsize] ({n}) at ({xb:.3f},{yb - i * paso:.3f}) {{{t}}};")
        if i:
            l.append(f"\\draw[flujo] ({cajas[i - 1][0]}.south) -- ({n}.north);")
    l.append(f"\\draw[flujo] ({xb:.3f},{yb + 0.75:.3f}) node[above, sen] {{x}} -- (dd.north);")
    l.append(f"\\draw[flujo] (ran.south) -- ++(0,-0.3) node[below, sen] {{F\\_TRAP}};")
    l.append(f"\\node[draw=black, line width=0.8pt, rounded corners=3pt, fill=white, inner sep=4pt, "
             f"align=center, font=\\scriptsize] at ({xb:.3f},{0.45:.3f}) "
             "{$\\Delta t \\ge k + m$: los dos miden limpio\\\\"
             "$\\Delta t < k + m$: se contaminan\\\\[2pt]"
             "{\\tiny $M = 1/(e^{1/\\tau} - 1)$, altura $16\\,A\\,k\\,(1+M)$}};")
    return l


PLANTILLA = r"""%% D13: el conformado trapezoidal. GENERADO por d13_trapecio.py: no editar a mano.
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


def compilar():
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                        f"-output-directory={tmp}", TEX.name],
                       cwd=AQUI, check=True, capture_output=True)
        pdf = AQUI / "d13_trapecio.pdf"
        shutil.copy(Path(tmp) / "d13_trapecio.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print("escrito d13_trapecio.pdf y .svg")


def main():
    TEX.write_text(PLANTILLA % "\n".join(figura()))
    print(f"escrito {TEX.name}")
    compilar()


if __name__ == "__main__":
    main()
