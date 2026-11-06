#!/usr/bin/env python3
"""Las figuras de ranuras_y_recuperacion.md: para que sirven las ranuras con el
trapecio, y como recuperar los pulsos que el trapecio no separa.

  trap_ranuras      pulsos buenos por segundo contra la tasa, con 1 a 4 ranuras,
                    con la compuerta de hoy (384) y con la que alcanza para el
                    trapecio (104)
  trap_recuperacion el error de cada metodo contra dt (con el modelo exacto y
                    con los errores de la placa) y los pulsos buenos contra la
                    tasa

Todo lo calcula recuperacion_modelo.py; aca solo se dibuja. Unos segundos.

    python3 figuras_recuperacion.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

import recuperacion_modelo as rm
from figuras_mejora import Ejes

AQUI = Path(__file__).resolve().parent
TASAS = [10, 20, 30, 50, 70, 100, 150, 200, 300, 500, 700, 1000]
N_ARRIBOS = 40000

ESTILO_N = {1: "rojo!75!black, line width=0.8pt, dash pattern=on 1.5pt off 1.5pt",
            2: "black, line width=0.8pt, dashed",
            3: "verde!55!black, line width=0.9pt",
            4: "azul!85!black, line width=1.4pt"}
METODOS = [   # clave, nombre, estilo
    ("trap64", "trapecio de hoy ($k$ = 64)", "azul!85!black, line width=1.4pt"),
    ("adaptivo", "banco adaptativo ($k$ = 64, 32, 16, 8)", "verde!55!black, line width=1.4pt"),
    ("desc_trap", "descomposición de \\texttt{F\\_TRAP}", "rojo!75!black, line width=0.9pt, dash pattern=on 1.5pt off 1.5pt"),
    ("desc_int", "descomposición de la integral", "black, line width=0.9pt, dashed"),
]


def tasa_buenos(tasa, n_acc, g, umbr, dmin, rng, cache={}):
    """kcps de pulsos buenos con cada metodo, para una tasa, n_acc y compuerta."""
    clave = (tasa, n_acc, g)
    if clave in cache:
        return cache[clave]
    if tasa not in cache:
        cache[tasa] = rm.arribos(tasa, N_ARRIBOS, rng)
    t = cache[tasa]
    seg = (t[-1] - t[0]) / (rm.FS * 1e6)
    med = rm.ranuras(t, n_acc, g) if n_acc else np.ones(len(t), bool)
    up, un = umbr[rm.F64]
    r = {"trap64": rm.buenos(t, med, up, un).sum(),
         "adaptivo": rm.buenos_adaptivo(t, med, umbr).sum(),
         "desc_trap": rm.buenos_descomp(t, med, up, un, dmin).sum()}
    cache[clave] = {k: v / seg / 1e3 for k, v in r.items()}
    return cache[clave]


def rotulo(e, x, y, texto, color, ancla="west"):
    return (f"\\node[nodo, anchor={ancla}, text={color}, fill=white, inner sep=1pt] at "
            f"({e.X(x):.3f},{e.Y(y):.3f}) {{{texto}}};")


def fig_ranuras(umbr, rng):
    L = ["\\node[titulo] at (-1.4,5.25) {\\textbf{Para qué sirve una ranura más, con el trapecio} \\quad "
         "{\\scriptsize pulsos que miden bien (\\texttt{F\\_TRAP}, error $<$ 1\\,\\%) contra la tasa de entrada}};"]
    for i, (g, titulo) in enumerate(((384, "con la compuerta de hoy: 384 muestras"),
                                     (104, "con la compuerta justa para el trapecio: 104"))):
        x0 = 8.0 * i
        e = Ejes(x0, 0.0, 6.2, 4.2, (10, 1000), (0, 300), xlog=True, ylog=False)
        L.append(f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at "
                 f"({x0:.3f},{4.35:.3f}) {{{titulo}}};")
        L += e.marco([10, 20, 50, 100, 200, 500, 1000], [0, 100, 200, 300],
                     "tasa de entrada, kcps", "pulsos buenos, kcps")
        ideal = [tasa_buenos(r, 0, g, umbr, 30, rng)["trap64"] for r in TASAS]
        L.append(e.curva(TASAS, ideal, "black!35, line width=2.4pt"))
        L.append(rotulo(e, 700, ideal[-2] + 22, "ranuras infinitas", "black!55", "east"))
        for n in (1, 2, 3, 4):
            ys = [tasa_buenos(r, n, g, umbr, 30, rng)["trap64"] for r in TASAS]
            L.append(e.curva(TASAS, ys, ESTILO_N[n]))
        # la tabla de lo capturado
        filas = ["& \\textbf{100 kcps} & \\textbf{500 kcps}\\\\[1pt]"]
        for n in (1, 2, 3, 4):
            v = [tasa_buenos(r, n, g, umbr, 30, rng)["trap64"] / tasa_buenos(r, 0, g, umbr, 30, rng)["trap64"]
                 for r in (100, 500)]
            filas.append(f"$N$ = {n} & {100 * v[0]:.1f}\\,\\% & {100 * v[1]:.1f}\\,\\%\\\\")
        L.append(f"\\node[anchor=north west, font=\\tiny, draw=black!30, fill=white, rounded corners=1pt, "
                 f"inner sep=2pt] at ({e.X(11):.3f},{e.Y(292):.3f}) {{\\begin{{tabular}}{{@{{}}l@{{\\hspace{{4pt}}}}"
                 f"r@{{\\hspace{{4pt}}}}r@{{}}}}{''.join(filas)}\\end{{tabular}}}};")
    items = ", ".join(f"{c}/{t}" for t, c in
                      (("$N$ = 1", "rojo!75!black"), ("$N$ = 2", "black"),
                       ("$N$ = 3", "verde!55!black"), ("$N$ = 4", "azul!85!black"),
                       ("tantas como hagan falta", "black!35")))
    L.append(f"\\leyenda{{-0.6,-1.0}}{{{items}}}")
    L.append("  {Simulación de un tren Poisson pasado por las ranuras y el publicador del RTL "
             "(la ranura queda ocupada la compuerta más 18 ciclos). Un pulso es bueno si se midió y "
             "no tiene vecinos a menos de 91 muestras antes ni 92 después, se hayan medido o no. "
             "La tabla es la fracción de los buenos posibles que encontró ranura.}")
    return L


def fig_recuperacion(umbr, rng):
    L = ["\\node[titulo] at (-1.4,5.25) {\\textbf{Recuperar los pulsos que el trapecio no separa} \\quad "
         "{\\scriptsize el peor de los dos pulsos de un par (A = 1000, B = 600), ruido de 4 cuentas}};"]
    dts = [2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30, 35, 40, 45, 50, 60, 70, 80, 90, 95,
           100, 120, 150, 200]
    exacto = rm.error_pares(dts, umbr, rng=rng)
    # con el dt de los disparos errado en una muestra: el walk del disparo cambia
    # con la amplitud y el pie cae entre muestras. La tau no se mira aca porque se
    # calibra en la placa para todos los metodos (el barrido de M)
    real = rm.error_pares(dts, umbr, rng=rng, dt_err=1)
    paneles = ((exacto, "con el $\\Delta t$ exacto"),
               (real, "con el $\\Delta t$ de los disparos errado en una muestra"))
    for i, (err, titulo) in enumerate(paneles):
        x0 = 8.0 * i
        e = Ejes(x0, 0.0, 6.2, 4.2, (2, 200), (0.05, 300))
        L.append(f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at "
                 f"({x0:.3f},{4.35:.3f}) {{{titulo}}};")
        L += e.marco([2, 5, 10, 20, 50, 100, 200], [0.1, 1, 10, 100], "$\\Delta t$, muestras",
                     "error RMS del peor", fmt_y=lambda v: f"{v:g}\\,\\%")
        L.append(f"\\draw[black!45, dashed] ({x0:.3f},{e.Y(rm.CRITERIO):.3f}) -- "
                 f"({x0 + e.ancho:.3f},{e.Y(rm.CRITERIO):.3f});")
        for clave, _, estilo in METODOS:
            peor = np.maximum(err[clave][0], err[clave][1])
            L.append(e.curva(dts, peor, estilo))
    # la tasa
    e = Ejes(0.0, -6.2, 6.2, 4.0, (10, 1000), (0, 900), xlog=True, ylog=False)
    L.append(f"\\node[anchor=south west, font=\\scriptsize\\bfseries, inner sep=0pt] at (0,{-6.2 + 4.15:.3f}) "
             f"{{pulsos buenos contra la tasa (compuerta de 104)}};")
    L += e.marco([10, 20, 50, 100, 200, 500, 1000], [0, 300, 600, 900],
                 "tasa de entrada, kcps", "pulsos buenos, kcps")
    L.append(e.curva([10, 1000], [10, 1000], "black!20, line width=0.6pt"))
    L.append(rotulo(e, 760, 790, "todos", "black!45", "east"))
    dmin = rm.dt_minimo(dts, np.maximum(exacto["desc_trap"][0], exacto["desc_trap"][1]))
    for clave, nombre, estilo in METODOS[:3]:
        for n, extra in ((4, ""), (2, ", dash pattern=on 4pt off 2pt") if clave == "adaptivo" else (None, None)):
            if n is None:
                continue
            ys = [tasa_buenos(r, n, 104, umbr, dmin, rng)[clave] for r in TASAS]
            L.append(e.curva(TASAS, ys, estilo + extra))
    a4 = tasa_buenos(1000, 4, 104, umbr, dmin, rng)
    a2 = tasa_buenos(1000, 2, 104, umbr, dmin, rng)
    L.append(rotulo(e, 1000, a4["adaptivo"] + 40, f"banco, $N$ = 4", "verde!45!black", "east"))
    L.append(rotulo(e, 1000, a2["adaptivo"] - 50, f"banco, $N$ = 2", "verde!45!black", "east"))
    L.append(rotulo(e, 1000, a4["desc_trap"] + 45, "descomp. \\texttt{F\\_TRAP}", "rojo!65!black", "east"))
    L.append(rotulo(e, 1000, a4["trap64"] - 45, "trapecio de hoy", "azul!75!black", "east"))
    # leyenda de metodos a la derecha
    filas = []
    for clave, nombre, estilo in METODOS:
        filas.append(f"\\draw[{estilo}] (0,{-0.42 * len(filas):.2f}) -- ++(0.7,0) "
                     f"node[right, font=\\scriptsize, black] {{{nombre}}};")
    L.append("\\begin{scope}[shift={(8.2,-2.6)}]" + " ".join(filas) + "\\end{scope}")
    L.append(f"\\node[anchor=north west, font=\\scriptsize, text width=6.2cm, align=left] at (8.0,-4.6) "
             f"{{El banco no necesita conocer $\\Delta t$ con precisión (solo elige qué trapecio usar) y "
             f"la descomposición sí: con una muestra de error en $\\Delta t$ se va a varios por ciento. "
             f"Abajo, la descomposición de \\texttt{{F\\_TRAP}} se cuenta desde $\\Delta t$ = {dmin}, "
             f"lo que vale solo con el $\\Delta t$ exacto: es una cota optimista.}};")
    return L


PLANTILLA = r"""%% %s. GENERADO por figuras_recuperacion.py: no editar a mano.
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
    rng = np.random.default_rng(11)
    umbr = {f: rm.umbrales(f) for f in rm.FORMAS}
    for f in rm.FORMAS:
        print(f"k = {f.k:2d}, m = {f.m:2d}: libres antes {umbr[f][0]}, despues {umbr[f][1]}")
    escribir("trap_ranuras", fig_ranuras(umbr, rng))
    escribir("trap_recuperacion", fig_recuperacion(umbr, rng))


if __name__ == "__main__":
    main()
