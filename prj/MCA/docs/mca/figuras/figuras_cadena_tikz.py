#!/usr/bin/env python3
"""La figura 7 estática, en el estilo común de las figuras TikZ.

  07a_senal.tex       una ventana de la señal con el umbral y la segmentación
  07b_cadena.tex      el camino de datos, el tren de registros de evento y la tabla
  07c_histograma.tex  el espectro como barras apiladas: una capa por tramo de la
                      acumulación, así que la evolución se lee en un solo gráfico

Cada .tex se compila a .pdf y .svg. Salen de la MISMA simulación que los videos
de `animacion_cadena_mca.py` y que `07_cadena.png` --`simular()` con la semilla y
los cuadros por omisión, y la ventana que elige `elegir_ventana()`--, así que los
pulsos, las amplitudes y el espectro final son los mismos en todas.

El color es el de la función, como en el panorama del MCA: azul la señal
(preprocesamiento), amarillo la ventana abierta (segmentación), verde la
amplitud medida (estadísticos del pulso) y naranja lo que llega al histograma
(publicación). Las capas de 07c son una rampa secuencial del naranja, oscura la
primera: la más chica es la que más tiene que verse.

Los epígrafes no van adentro: están en `epigrafes.txt` (los escribe
`figuras_resolucion.py`).

    python3 figuras_cadena_tikz.py [--frames 700]
"""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from animacion_cadena_mca import DT_TRAZA, UMBRAL, H_SHIFT, N_CANALES, simular
from figuras_cadena_estatica import THR_LO, HITOS, elegir_ventana, cuadro_con

AQUI = Path(__file__).resolve().parent

PREAMBULO = r"""%% %(desc)s. GENERADO por figuras_cadena_tikz.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{booktabs}
\usepackage[none]{hyphenat}
\input{../../figuras/estilo_tikz.tex}
%% rampa secuencial del naranja de la paleta, para las capas de 07c: oscura la
%% primera (validada: pares vecinos distinguibles también con daltonismo)
\definecolor{acum1}{RGB}{143,67,16}
\definecolor{acum2}{RGB}{217,112,42}
\definecolor{acum3}{RGB}{244,174,110}
\tikzset{
  eje/.style     = {black!60, line width=0.5pt},
  guia/.style    = {black!12, line width=0.4pt},
  tick/.style    = {font=\scriptsize, inner sep=1.5pt, black!75},
  titeje/.style  = {font=\scriptsize, inner sep=1pt},
  traza/.style   = {azul!75!black, line width=0.7pt, line join=round},
  thr/.style     = {rojo!70!black, line width=0.8pt, dashed},
  thrlo/.style   = {rojo!70!black, line width=0.8pt, densely dotted},
  pico/.style    = {circle, draw=black, line width=0.4pt, fill=verde,
                    inner sep=0pt, minimum size=1.9mm},
  perdido/.style = {circle, draw=black!50, line width=0.6pt, fill=white,
                    inner sep=0pt, minimum size=1.7mm},
  est/.style     = {bloque=verde!55, param={verde!55}{verde!20}},
  publog/.style  = {etapa=naranja!30},
  ficha/.style   = {draw=black, line width=0.5pt, fill=white, rounded corners=1.5pt,
                    font=\scriptsize\ttfamily, inner sep=2pt, minimum width=0.85cm,
                    minimum height=0.42cm},
}
%% una entrada de leyenda suelta: #1 posición, #2 la marca, #3 el texto
%% amp >> h_shift: el {} corta la ligadura >> -> comilla de la T1
\newcommand{\shr}[1]{\texttt{amp~>{}>~#1}}
\newcommand{\entrada}[3]{\node[anchor=west, font=\scriptsize] at (#1) {#2\hspace{1.5mm}#3};}
\begin{document}
\begin{tikzpicture}[fondo]
%(cuerpo)s
\end{tikzpicture}
\end{document}
"""


def f(v):
    return f"{v:.3f}"


# =============================================================================
# 07a -- la señal
# =============================================================================
W_A, H_A = 14.0, 5.0             # cm del área de datos
YMIN_A, YMAX_A = -380.0, 3000.0  # cuentas: abajo queda el renglón de los #n


def fig_senal(sim, t0, t1, eventos):
    sx = W_A / (t1 - t0)
    sy = H_A / (YMAX_A - YMIN_A)
    X = lambda t: (t - t0) * sx                               # noqa: E731
    Y = lambda a: (a - YMIN_A) * sy                           # noqa: E731
    acep = [e for e in eventos if e['ok']]
    l = []

    # --- los dos estados de pulse_feature, que entre los dos cubren el eje -----
    activas = [(e['disparo'], e['cierre']) for e in acep]
    reposo, cursor = [], t0
    for ta, tb in activas:
        if ta > cursor:
            reposo.append((cursor, ta))
        cursor = tb
    if cursor < t1:
        reposo.append((cursor, t1))
    for ta, tb in reposo:
        l.append(f"\\fill[grisr!65] ({f(X(ta))},0) rectangle ({f(X(tb))},{f(H_A)});")
    for ta, tb in activas:
        l.append(f"\\fill[amarillo] ({f(X(ta))},0) rectangle ({f(X(min(tb, t1)))},{f(H_A)});")

    # --- grilla y ejes ----------------------------------------------------------
    for a in range(0, int(YMAX_A) + 1, 1000):
        l.append(f"\\draw[guia] (0,{f(Y(a))}) -- ({f(W_A)},{f(Y(a))});")
        l.append(f"\\draw[eje] (0,{f(Y(a))}) -- ++(-0.08,0) node[tick, left] {{{a}}};")
    l.append(f"\\draw[eje] (0,0) -- (0,{f(H_A)});")
    l.append(f"\\draw[eje] (0,0) -- ({f(W_A)},0);")
    for t in range(int(np.ceil(t0 / 5.0)) * 5, int(t1) + 1, 5):
        l.append(f"\\draw[eje] ({f(X(t))},0) -- ++(0,-0.08) node[tick, below] {{{t}}};")
    l.append(f"\\node[titeje, anchor=north] at ({f(W_A / 2)},-0.48) {{tiempo [$\\mu$s]}};")
    l.append(f"\\node[titeje, rotate=90, anchor=south] at (-0.75,{f(H_A / 2)}) "
             "{amplitud sobre la base [ADU]};")

    # --- umbral y re-armado, rotulados a la derecha -------------------------------
    l.append(f"\\draw[thr] (0,{f(Y(UMBRAL))}) -- ({f(W_A)},{f(Y(UMBRAL))});")
    l.append(f"\\draw[thrlo] (0,{f(Y(THR_LO))}) -- ({f(W_A)},{f(Y(THR_LO))});")
    l.append(f"\\node[titeje, anchor=south west] at ({f(W_A + 0.08)},{f(Y(UMBRAL) - 0.03)}) "
             "{\\texttt{thr}: abre};")
    l.append(f"\\node[titeje, anchor=north west] at ({f(W_A + 0.08)},{f(Y(THR_LO) + 0.03)}) "
             "{\\texttt{thr} $-$ \\texttt{hyst}: cierra y re-arma};")

    # --- la traza -------------------------------------------------------------------
    i0, i1 = int(t0 / DT_TRAZA), int(t1 / DT_TRAZA) + 1
    pts = " ".join(f"({f(X(t))},{f(Y(a))})"
                   for t, a in zip(sim['grid'][i0:i1], sim['traza'][i0:i1])
                   if t0 <= t <= t1)
    l.append(f"\\draw[traza] plot coordinates {{{pts}}};")

    # --- lo que mide el módulo, y el número de cada pulso al pie -------------------
    for ev in eventos:
        x, y = X(ev['t']), Y(ev['amp'])
        if ev['ok']:
            l.append(f"\\node[pico] at ({f(x)},{f(y)}) {{}};")
            l.append(f"\\node[font=\\scriptsize\\bfseries, anchor=south, inner sep=2pt] "
                     f"at ({f(x)},{f(y + 0.08)}) {{{ev['amp']:.0f}}};")
            pie = f"\\#{ev['n']}"
        else:
            l.append(f"\\node[perdido] at ({f(x)},{f(y)}) {{}};")
            pie = f"\\#{ev['n']}\\;\\textit{{no cuenta}}"
        # el rechazado no tiene banda: su rótulo arranca en el pulso y no
        # se mete en la ventana del anterior
        lado = "" if ev['ok'] else ", anchor=west"
        dx = 0 if ev['ok'] else -0.15
        l.append(f"\\node[font=\\scriptsize, black!70, inner sep=1pt{lado}] "
                 f"at ({f(x + dx)},{f(Y(-200))}) {{{pie}}};")

    # --- leyenda ---------------------------------------------------------------------
    yl = -1.15
    l.append(f"\\entrada{{0.0,{yl}}}{{\\tikz\\draw[fill=amarillo, line width=0.4pt] "
             "(0,0) rectangle (4mm,3mm);}{ventana abierta: dispara en \\texttt{thr}, "
             "cierra en \\texttt{thr} $-$ \\texttt{hyst}}")
    l.append(f"\\entrada{{7.6,{yl}}}{{\\tikz\\draw[fill=grisr!65, line width=0.4pt] "
             "(0,0) rectangle (4mm,3mm);}{reposo: se re-arma y sigue la línea de base}")
    l.append(f"\\entrada{{0.0,{yl - 0.45}}}{{\\tikz\\node[pico] {{}};}}"
             "{amplitud medida: la muestra de pico}")
    l.append(f"\\entrada{{7.6,{yl - 0.45}}}{{\\tikz\\node[perdido] {{}};}}"
             "{no cruza \\texttt{thr}: no abre ventana}")
    return "\n".join(l)


# =============================================================================
# 07b -- el camino de datos
# =============================================================================
def fig_cadena(eventos):
    acep = [e for e in eventos if e['ok']]
    l = []

    l.append(r"\node[est, text width=3.0cm] (pf) at (0,0) {\blk{mca\_pulse\_feature}{}"
             r"\nodepart{two}abre una ventana al\\ cruzar \texttt{thr} y mide\\ la amplitud};")
    l.append(r"\node[publog, text width=2.7cm] (hi) at (12.0,0) {\etq{histograma}"
             r"{suma 1 en el canal\\ \shr{%d}}};" % H_SHIFT)
    l.append(r"\draw[flujo] ($(pf.west)+(-1.4,0)$) -- node[sen, above, font=\scriptsize] "
             r"{señal} (pf.west);")
    l.append(r"\draw[flujo] (hi.east) -- node[sen, above, font=\scriptsize] {espectro} "
             r"++(1.4,0);")

    # el tren: el primero que salió va adelante, cerca del histograma
    x_ini, x_fin = 2.65, 9.75
    l.append(f"\\draw[flujo] (pf.east) -- (hi.west);")
    xs = np.linspace(x_fin - 0.55, x_ini + 0.55, len(acep))
    for x, ev in zip(xs, acep):
        l.append(f"\\node[ficha] at ({f(x)},0) {{{ev['amp']:.0f}}};")
        l.append(f"\\node[font=\\scriptsize, black!70, anchor=north, inner sep=1pt] "
                 f"at ({f(x)},-0.27) {{\\#{ev['n']}}};")
    l.append(f"\\node[font=\\scriptsize, anchor=south] at ({f((x_ini + x_fin) / 2)},0.32) "
             "{un registro de evento por pulso, en orden de cierre};")

    # la tabla: los mismos pulsos como los ve el histograma
    filas = []
    for ev in eventos:
        if ev['ok']:
            filas.append(f"\\#{ev['n']} & {ev['t']:.1f} & \\textbf{{{ev['amp']:.0f}}} & "
                         f"\\textbf{{{ev['canal']}}}\\\\")
        else:
            filas.append(f"\\color{{black!50}}\\#{ev['n']} & \\color{{black!50}}{ev['t']:.1f} & "
                         f"\\color{{black!50}}{ev['amp']:.0f} & "
                         f"\\color{{black!50}}\\textit{{rechazado: amp < thr}}\\\\")
    tabla = ("\\begin{tabular}{@{}l@{\\hspace{1.0cm}}r@{\\hspace{1.0cm}}r"
             "@{\\hspace{1.0cm}}r@{}}\\toprule "
             "\\textbf{pulso} & \\textbf{$t$ [$\\mu$s]} & \\textbf{amp [ADU]} & "
             f"\\textbf{{canal = \\shr{{{H_SHIFT}}}}}\\\\\\midrule "
             + " ".join(filas) + "\\bottomrule\\end{tabular}")
    l.append(f"\\node[anchor=north, font=\\scriptsize, inner sep=0pt] at (6.0,-1.15) "
             f"{{{tabla}}};")
    return "\n".join(l)


# =============================================================================
# 07c -- el espectro, apilado por tramo de la acumulación
# =============================================================================
W_C, H_C = 14.0, 5.0
YMAX_C = 36


def fig_histograma(sim):
    cuadros = [cuadro_con(sim, n) for n in HITOS] + [len(sim['estados']) - 1]
    acum = [sim['estados'][c]['cuentas'].astype(int) for c in cuadros]
    totales = [sim['estados'][c]['emitidos'] for c in cuadros]
    capas = [acum[0]] + [b - a for a, b in zip(acum, acum[1:])]
    colores = ["acum1", "acum2", "acum3"]
    assert len(capas) == len(colores)

    dx = W_C / N_CANALES
    sy = H_C / YMAX_C
    ancho = dx * 0.80
    l = []

    for n in range(0, YMAX_C + 1, 10):
        l.append(f"\\draw[guia] (0,{f(n * sy)}) -- ({f(W_C)},{f(n * sy)});")
        l.append(f"\\draw[eje] (0,{f(n * sy)}) -- ++(-0.08,0) node[tick, left] {{{n}}};")

    # las barras: cada capa arriba de la anterior, con un filete blanco entre capas
    for c in range(N_CANALES):
        x0 = c * dx + (dx - ancho) / 2
        base = 0
        for capa, color in zip(capas, colores):
            h = int(capa[c])
            if h == 0:
                continue
            l.append(f"\\fill[{color}] ({f(x0)},{f(base * sy)}) rectangle "
                     f"({f(x0 + ancho)},{f((base + h) * sy)});")
            if base > 0:
                l.append(f"\\draw[white, line width=0.7pt] ({f(x0)},{f(base * sy)}) -- "
                         f"({f(x0 + ancho)},{f(base * sy)});")
            base += h

    # el umbral, en su lugar sobre el eje continuo de amplitud: 300/64 canales
    xu = UMBRAL / (1 << H_SHIFT) * dx
    l.append(f"\\draw[thr] ({f(xu)},0) -- ({f(xu)},{f(H_C)});")
    l.append(f"\\node[titeje, anchor=north west] at ({f(xu + 0.05)},{f(H_C)}) "
             f"{{\\texttt{{thr}} = {UMBRAL}}};")

    l.append(f"\\draw[eje] (0,0) -- (0,{f(H_C)});")
    l.append(f"\\draw[eje] (0,0) -- ({f(W_C)},0);")
    for c in range(0, N_CANALES, 10):
        x = (c + 0.5) * dx
        l.append(f"\\draw[eje] ({f(x)},0) -- ++(0,-0.08) node[tick, below] {{{c}}};")
    l.append(f"\\node[titeje, anchor=north] at ({f(W_C / 2)},-0.48) "
             f"{{canal (\\shr{{{H_SHIFT}}})}};")
    l.append(f"\\node[titeje, rotate=90, anchor=south] at (-0.55,{f(H_C / 2)}) {{cuentas}};")

    # leyenda: qué tramo es cada capa, y el total al cerrarlo
    textos = [f"las primeras {totales[0]} cuentas"]
    textos += [f"de la {a + 1} a la {b}" for a, b in zip(totales, totales[1:])]
    xl = 0.0
    for color, txt in zip(colores, textos):
        l.append(f"\\entrada{{{f(xl)},-1.15}}{{\\tikz\\fill[{color}] (0,0) rectangle "
                 f"(4mm,3mm);}}{{{txt}}}")
        xl += 0.9 + 0.16 * len(txt)
    return "\n".join(l), totales


# =============================================================================
def escribir(nombre, desc, cuerpo):
    tex = AQUI / f"{nombre}.tex"
    tex.write_text(PREAMBULO % {"desc": desc, "cuerpo": cuerpo}, encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                            f"-output-directory={tmp}", tex.name],
                           cwd=AQUI, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"pdflatex falló con {tex.name}:\n{r.stdout[-2500:]}")
        pdf = AQUI / f"{nombre}.pdf"
        shutil.copy(Path(tmp) / f"{nombre}.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))],
                   check=True)
    print(f"  {nombre}.tex, .pdf y .svg")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frames', type=int, default=700,
                    help='los mismos que animacion_cadena_mca.py, para que '
                         'estático y video salgan de la misma simulación')
    args = ap.parse_args()

    sim = simular(args.frames)
    t0, t1, eventos = elegir_ventana(sim)

    escribir("07a_senal", "Figura 7a: la señal, un pulso por evento",
             fig_senal(sim, t0, t1, eventos))
    escribir("07b_cadena", "Figura 7b: el camino de datos, un número por pulso",
             fig_cadena(eventos))
    cuerpo, totales = fig_histograma(sim)
    escribir("07c_histograma", "Figura 7c: el espectro, una cuenta por número",
             cuerpo)
    print(f"ventana [{t0:.1f}, {t1:.1f}] µs; capas de 07c hasta "
          f"{', '.join(str(n) for n in totales)} cuentas")


if __name__ == '__main__':
    main()
