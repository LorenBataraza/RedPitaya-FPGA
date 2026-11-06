#!/usr/bin/env python3
"""D13 por dentro: como el trapecio recupera un pulso montado sobre la cola de otro.

Calcula las senales con la misma recursion que mca_trap (en enteros, y
comprueba que s es 16 * estimadores.trapecio, el modelo contra el que
tb_mca_trap compara bit a bit) y escribe d13_recuperacion.tex en el estilo
comun de las figuras TikZ. Despues lo compila a .pdf y .svg.

La escena es la de d13_trapecio.py y la seccion 10 de tb_mca_top: pulsos
exponenciales de tau = 50 muestras, A = 1000 y B = 600 separados 60, trapecio
de k = 32, m = 16, Mq = 792, ventana de la meseta [36, 44) desde el pie y
sh = 12. Los paneles son la entrada, el escalon que deja el polo-cero, r (la
derivada del trapecio, que es una senal del RTL), la salida, y la salida con M
un 5 % bajo.

    python3 d13_recuperacion.py
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

TEX = AQUI / "d13_recuperacion.tex"

TAU, K, M_MESETA = 50.0, 32, 16
L = K + M_MESETA
MQ = round(16.0 / (math.exp(1.0 / TAU) - 1.0))        # 792
SH, OFF, LW = 12, 36, 3
T0, DT, N = 20, 60, 300                                # pie de A, separacion, largo
A1, A2 = 1000.0, 600.0
MAL = 0.95                                             # M un 5 % bajo

DX = 0.042            # cm por muestra
ALTO = 1.45           # cm por panel
SEP = 0.55            # cm entre paneles


def pulso(a, t0):
    t = np.arange(N) - t0
    return np.where(t >= 0, a * np.exp(-np.maximum(t, 0) / TAU), 0.0)


def retrasar(v, j):
    o = np.zeros_like(v)
    o[j:] = v[:v.size - j]
    return o


def cadena(x, mq=MQ):
    """Las senales de mca_trap, en enteros: d, p, r y s (sin el corrimiento)."""
    x = np.round(x).astype(np.int64)
    d = x - retrasar(x, K) - retrasar(x, L) + retrasar(x, K + L)
    p = np.cumsum(d)
    r = 16 * p + mq * d
    return {"x": x, "d": d, "p": p, "r": r, "s": np.cumsum(r),
            "u": 16 * np.cumsum(x) + mq * x}          # el escalon: NO es del RTL


def medida(s, t):
    """F_TRAP de la ranura que abrio en t: el promedio de s >> sh en su ventana."""
    y = s >> SH
    return int(np.floor(y[t + OFF:t + OFF + (1 << LW)].sum() / (1 << LW)))


# --------------------------------------------------------------------- dibujo
def curva(y, y0, escala, estilo):
    pts = " ".join(f"({i * DX:.3f},{y0 + v * escala:.3f})" for i, v in enumerate(y))
    return f"\\draw[{estilo}] plot coordinates {{{pts}}};"


def eje(y0, rotulo):
    return [f"\\draw[black!45, line width=0.4pt] (0,{y0:.3f}) -- ({N * DX:.3f},{y0:.3f});",
            f"\\node[anchor=east, font=\\scriptsize, align=right] at (-0.15,{y0:.3f}) "
            f"{{{rotulo}}};"]


def solos_y_suma(f, y0, esc, clave):
    """Cada pulso solo en gris punteado y la suma en negro."""
    a, b, ab = cadena(pulso(A1, T0)), cadena(pulso(A2, T0 + DT)), cadena(f)
    return [curva(a[clave], y0, esc, "black!40, dashed, line width=0.5pt"),
            curva(b[clave], y0, esc, "black!40, dashed, line width=0.5pt"),
            curva(ab[clave], y0, esc, "line width=0.9pt")]


def banda(t, y0, color):
    a, b = t + OFF, t + OFF + (1 << LW)
    return (f"\\fill[{color}, opacity=0.55] ({a * DX:.3f},{y0:.3f}) rectangle "
            f"({b * DX:.3f},{y0 + 0.9 * ALTO:.3f});")


def cota(xa, xb, y, texto, lado="above"):
    return (f"\\draw[<->, line width=0.5pt] ({xa * DX:.3f},{y:.3f}) -- ({xb * DX:.3f},{y:.3f}) "
            f"node[midway, {lado}, nodo] {{{texto}}};")


def figura():
    entrada = pulso(A1, T0) + pulso(A2, T0 + DT)
    c = cadena(entrada)
    ref = np.round(trapecio(c["x"], K, M_MESETA, MQ / 16.0) * 16.0).astype(np.int64)
    assert np.array_equal(c["s"], ref), "la recursion no coincide con estimadores.trapecio"
    solo_a, solo_b = cadena(pulso(A1, T0)), cadena(pulso(A2, T0 + DT))
    mal = cadena(entrada, round(MQ * MAL))
    mal_b = cadena(pulso(A2, T0 + DT), round(MQ * MAL))

    tb = T0 + DT
    l = [f"\\node[titulo] at (-2.6,{0.95:.3f}) "
         "{\\textbf{D13 por dentro · Cómo el trapecio recupera un pulso montado sobre otro}};"]
    y = -ALTO * 0.15

    # --- 1. la entrada -----------------------------------------------------
    y -= ALTO
    esc = ALTO * 0.9 / 1300.0
    l += eje(y, "entrada\\\\[-1pt]{\\tiny $x$}")
    l += solos_y_suma(entrada, y, esc, "x")
    pico_b = c["x"][tb]
    l.append(f"\\node[nodo, anchor=west] at ({(tb + 3) * DX:.3f},{y + pico_b * esc:.3f}) "
             f"{{B mide {pico_b} y no {A2:.0f}: está sobre la cola de A}};")
    l.append(f"\\node[nodo, anchor=south west] at ({(T0 + 2) * DX:.3f},{y + A1 * esc:.3f}) "
             f"{{A}};")
    l.append(f"\\node[nodo, anchor=south east] at ({(tb - 1) * DX:.3f},{y + pico_b * esc:.3f}) "
             f"{{B}};")
    l.append(f"\\node[nodo, anchor=south] at ({215 * DX:.3f},{y + 0.3:.3f}) "
             f"{{las colas duran unas $5\\tau = {5 * TAU:.0f}$ muestras}};")
    y_entrada = y

    # --- 2. el escalon del polo-cero ----------------------------------------
    y -= ALTO + SEP
    esc = ALTO * 0.9 / c["u"].max()
    l += eje(y, "polo-cero\\\\[-1pt]{\\tiny $16\\,\\Sigma x + M_q\\,x$}")
    l.append(curva(c["u"], y, esc, "line width=0.9pt"))
    ha = solo_a["u"][T0 + 5]
    l.append(f"\\node[nodo, anchor=north west] at ({(T0 + 3) * DX:.3f},{y + ha * esc - 0.03:.3f}) "
             f"{{escalón de A: $16\\,A(1+M)$}};")
    l.append(f"\\node[nodo, anchor=south west] at ({(tb + 3) * DX:.3f},{y + c['u'][tb + 5] * esc:.3f}) "
             f"{{+ el de B, y nada más: la cola ya no está}};")
    l.append(f"\\node[nodo, anchor=south east, black!55] at ({(N - 2) * DX:.3f},{y + 0.05:.3f}) "
             f"{{equivalente: el RTL no lo calcula (crece sin límite)}};")

    # --- 3. r: la derivada del trapecio -------------------------------------
    # r tiene signo: el eje va a media altura y la parte negativa baja de el
    y -= 0.5 * ALTO + SEP + 0.2
    yz = y
    esc = ALTO * 0.45 / np.abs(c["r"]).max()
    l += eje(yz, "$r = 16\\,p + M_q\\,d$\\\\[-1pt]{\\tiny la doble diferencia del escalón}")
    l += solos_y_suma(entrada, yz, esc, "r")
    hr = solo_a["r"][T0 + 2] * esc
    l.append(cota(T0, T0 + K, yz + hr + 0.12, "$k$"))
    l.append(cota(T0 + K, T0 + L, yz + 0.12, "$m$"))
    l.append(cota(T0 + L, T0 + L + K, yz - hr - 0.12, "$k$", "below"))
    l.append(cota(T0, T0 + 2 * K + M_MESETA, yz - hr - 0.48, "lo de A dura $2k+m$ y se termina",
                  "below"))
    l.append(f"\\node[nodo, anchor=west] at ({(tb + K + 2) * DX:.3f},{yz + 0.5 * hr:.3f}) "
             f"{{lo de B}};")
    y -= 0.45 * ALTO + 0.6

    # --- 4. s: el trapecio ------------------------------------------------------
    y -= ALTO + SEP
    esc = ALTO * 0.85 / (solo_a["s"] >> SH).max()
    l += eje(y, "trapecio\\\\[-1pt]{\\tiny $s \\gg$ sh}")
    l.append(banda(T0, y, "verde"))
    l.append(banda(tb, y, "verde"))
    a_s, b_s, ab_s = (solo_a["s"] >> SH), (solo_b["s"] >> SH), (c["s"] >> SH)
    l.append(curva(a_s, y, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(b_s, y, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(ab_s, y, esc, "line width=0.9pt"))
    m1, m2 = medida(c["s"], T0), medida(c["s"], tb)
    r1, r2 = medida(solo_a["s"], T0), medida(solo_b["s"], tb)
    l.append(f"\\node[nodo, anchor=north east] at ({(N - 4) * DX:.3f},{y + ALTO:.3f}) "
             f"{{\\texttt{{F\\_TRAP}}: {m1} y {m2}, cada uno solo: {r1} y {r2}}};")
    l.append(f"\\node[nodo, anchor=north, text=verde!50!black] at "
             f"({(tb + OFF + 4) * DX:.3f},{y - 0.02:.3f}) {{ventana de la ranura de B}};")
    l.append(f"\\draw[->, line width=0.5pt] ({(T0 + 2 * K + M_MESETA + 14) * DX:.3f},{y + 0.55:.3f}) "
             f"node[right, nodo] {{A ya volvió a cero}} -- ({(T0 + 2 * K + M_MESETA + 1) * DX:.3f},{y + 0.04:.3f});")

    # --- 5. con M mal ajustado ----------------------------------------------
    y -= ALTO + SEP
    l += eje(y, f"$M$ un {round((1 - MAL) * 100)}\\,\\% bajo\\\\[-1pt]{{\\tiny $s \\gg$ sh}}")
    l.append(banda(T0, y, "rojo"))
    l.append(banda(tb, y, "rojo"))
    mal_a = cadena(pulso(A1, T0), round(MQ * MAL))
    l.append(curva(mal_a["s"] >> SH, y, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(mal_b["s"] >> SH, y, esc, "black!40, dashed, line width=0.5pt"))
    l.append(curva(mal["s"] >> SH, y, esc, "line width=0.9pt"))
    e2, e2s = medida(mal["s"], tb), medida(mal_b["s"], tb)
    cola = int((mal_a["s"] >> SH)[T0 + 2 * K + M_MESETA + 5])
    l.append(f"\\node[nodo, anchor=north east] at ({(N - 4) * DX:.3f},{y + ALTO:.3f}) "
             f"{{B mide {e2} y solo {e2s}: {100 * (e2 / e2s - 1):+.1f}\\,\\%}};")
    l.append(f"\\draw[->, line width=0.5pt] ({170 * DX:.3f},{y + 0.7:.3f}) "
             f"node[right, nodo, align=left] {{A deja una cola de {cola} cuentas\\\\"
             f"({100 * cola / r1:.0f}\\,\\% de su altura), y B se monta encima}} -- "
             f"({(T0 + 2 * K + M_MESETA + 8) * DX:.3f},{y + cola * esc + 0.05:.3f});")

    # eje de muestras
    l.append(f"\\foreach \\n in {{0, 50, ..., {N}}} \\draw[black!45] (\\n*{DX},{y:.3f}) -- "
             f"++(0,-0.06) node[below, nodo] {{\\n}};")
    l.append(f"\\node[nodo, anchor=north] at ({N / 2 * DX:.3f},{y - 0.32:.3f}) {{muestras}};")

    # guias en los pies de A y B
    for t in (T0, tb):
        l.insert(1, f"\\draw[black!15, line width=0.4pt] ({t * DX:.3f},{y_entrada + ALTO:.3f}) -- "
                    f"({t * DX:.3f},{y:.3f});")

    # --- el razonamiento, a la derecha --------------------------------------
    xb = N * DX + 0.6
    l.append(f"\\node[anchor=north west, draw=black!40, rounded corners=2pt, inner sep=5pt, "
             f"text width=5.6cm, align=left, font=\\scriptsize] at ({xb:.3f},{-0.1:.3f}) {{"
             "\\textbf{En el RTL} la cuenta es $d \\to p \\to r \\to s$: la doble "
             "diferencia $d = x - x_{-k} - x_{-l} + x_{-k-l}$ va primero, y así $p$ y $s$ "
             "quedan acotados.\\\\[4pt]"
             "\\textbf{Para leerla}, como todo es lineal, $r$ es también la doble "
             "diferencia del escalón $16\\,\\Sigma x + M_q\\,x$, y la recuperación son dos pasos:"
             "\\\\[3pt]"
             "\\textbf{1.} El polo-cero convierte cada exponencial en un escalón, si "
             "$M = 1/(e^{1/\\tau} - 1)$. La cola de A deja de existir: B le suma su escalón "
             "y nada más.\\\\[3pt]"
             "\\textbf{2.} La doble diferencia de un escalón dura $2k+m$ muestras: $k$ "
             "arriba, $m$ en cero, $k$ abajo. Integrada da el trapecio, que vuelve a "
             "cero ahí.\\\\[4pt]"
             "\\textbf{Por eso} B mide limpio si $\\Delta t \\ge k+m$: su meseta empieza "
             "en $\\Delta t + k \\ge 2k+m$, cuando lo de A ya terminó. Acá "
             f"$\\Delta t = {DT} \\ge {K + M_MESETA}$.\\\\[4pt]"
             "\\textbf{Si $M$ no cancela el polo}, el escalón no es plano y el trapecio "
             "deja una cola: el segundo pulso se mide sobre ella. Es lo que corrige el "
             "barrido de $M$ en placa ($M_\\mathrm{opt} = 242.8$ contra 249.5 nominal)."
             "};")
    return l


PLANTILLA = r"""%% D13 por dentro: la recuperacion. GENERADO por d13_recuperacion.py: no editar a mano.
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
        pdf = AQUI / "d13_recuperacion.pdf"
        shutil.copy(Path(tmp) / "d13_recuperacion.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print("escrito d13_recuperacion.pdf y .svg")


def main():
    TEX.write_text(PLANTILLA % "\n".join(figura()))
    print(f"escrito {TEX.name}")
    compilar()


if __name__ == "__main__":
    main()
