#!/usr/bin/env python3
"""Tiempo de relanzamiento con dos fuentes en la máscara OR: qué mide trig_arm.

Escribe relanzamiento_or.tex en el estilo común de las figuras TikZ y lo compila
a .pdf y .svg. Tres escenas con las mismas dos fuentes A y B habilitadas:

  (a) A y B miran la misma señal y todo pulso cruza los dos umbrales:
      trig_arm = a_A | a_B es exacto.
  (b) B mira otro canal, sin pulsos: B siempre armada, trig_arm = 1, y el pulso
      que llega con A desarmada se pierde contado como livetime.
  (c) B mira la misma señal con un umbral más alto: con A desarmada, el pulso
      grande entra por B y el chico se pierde contado como livetime.

No es una simulación del RTL: es la ecuación del Schmitt de mt_slope_trig y
mt_pz_trig aplicada muestra a muestra a una salida de filtro idealizada (un
trapecio por pulso, corto en A como el polo-cero y largo en B como la
pendiente), sin latencias. Lo que se dibuja sale del cálculo:

  s[n] = 1 si y[n] >= thr, 0 si y[n] < thr - hyst, s[n-1] si no;  a = !s
  trig_arm = a_A | a_B                         (la máscara tiene las dos)
  pulso visto por i  <=>  está en el canal de i y su altura cruza thr_i
  detectado          <=>  alguna fuente que lo ve está armada al llegar (n0 - 1)
  casillero          =    t_rearm si trig_arm = 0 al llegar, livetime si no

y se comprueba contra los flancos de s: cada pulso detectado tiene que hacer
disparar a alguna fuente, y uno perdido a ninguna.

    python3 figuras_relanzamiento.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
NOMBRE = "relanzamiento_or"
TEX = AQUI / f"{NOMBRE}.tex"

N = 96              # muestras por escena
DX = 0.140          # cm por muestra
SY = 1.10           # cm por unidad de y
DIG = 0.30          # alto de un carril digital
GAP = 0.14          # entre carriles

# Forma idealizada de la salida del filtro de cada fuente: subida, meseta
FORMA = {"A": (3, 2), "B": (6, 3)}


def trapecio(n0, alto, sub, mes):
    y = [0.0] * N
    for o in range(2 * sub + mes):
        n = n0 + o
        if n >= N:
            break
        if o < sub:
            v = (o + 1) / sub
        elif o < sub + mes:
            v = 1.0
        else:
            v = 1.0 - (o - sub - mes + 1) / sub
        y[n] = alto * v
    return y


def schmitt(y, thr, hyst):
    s, out = 0, []
    for v in y:
        if v >= thr:
            s = 1
        elif v < thr - hyst:
            s = 0
        out.append(s)
    return out


# Escenas: pulsos (muestra, altura, canal) y, por fuente, canal y umbrales
ESCENAS = [
    dict(titulo="(a) A y B ven todos los pulsos",
         pulsos=[(10, 1.0, 1), (22, 0.9, 1), (27, 0.8, 1), (70, 1.0, 1)],
         fuentes={"A": (1, 0.25, 0.15), "B": (1, 0.25, 0.15)}),
    dict(titulo="(b) B en otro canal",
         pulsos=[(10, 1.0, 1), (15, 0.8, 1), (62, 1.0, 1)],
         fuentes={"A": (1, 0.25, 0.15), "B": (2, 0.25, 0.15)}),
    dict(titulo="(c) B con el umbral más alto",
         pulsos=[(10, 0.3, 1), (15, 0.3, 1), (55, 0.3, 1), (59, 1.0, 1)],
         fuentes={"A": (1, 0.20, 0.12), "B": (1, 0.70, 0.30)}),
]


def calcular(e):
    r = {}
    for f, (ch, thr, hyst) in e["fuentes"].items():
        sub, mes = FORMA[f]
        y = [0.0] * N
        for n0, alto, c in e["pulsos"]:
            if c == ch:
                y = [a + b for a, b in zip(y, trapecio(n0, alto, sub, mes))]
        s = schmitt(y, thr, hyst)
        r[f] = dict(y=y, s=s, a=[1 - v for v in s], thr=thr, hyst=hyst, ch=ch)
    arm = [max(r[f]["a"][n] for f in r) for n in range(N)]

    res = []
    for j, (n0, alto, c) in enumerate(e["pulsos"]):
        # el estado justo antes de que el pulso llegue: en n0 ya lo ve
        por = [f for f in r if r[f]["ch"] == c and alto >= r[f]["thr"] and r[f]["a"][n0 - 1]]
        cas = "t_rearm" if not arm[n0 - 1] else "livetime"
        # comprobación contra los flancos de s: entre este pulso y el siguiente
        fin = e["pulsos"][j + 1][0] if j + 1 < len(e["pulsos"]) else N
        dispara = [f for f in r if any(r[f]["s"][n] and not r[f]["s"][n - 1]
                                       for n in range(max(n0, 1), fin))]
        assert bool(por) == bool(dispara), (e["titulo"], n0, por, dispara)
        res.append((n0, por, cas))
    return r, arm, res


def x(n):
    return n * DX


def digital(L, v, y, color_bajo):
    """Forma de onda de un bit: alto = 1. Los tramos en 0, con relleno."""
    n = 0
    while n < N:
        m = n
        while m < N and v[m] == v[n]:
            m += 1
        if not v[n] and color_bajo:
            L.append(f"\\fill[{color_bajo}] ({x(n):.3f},{y:.3f}) rectangle "
                     f"({x(m):.3f},{y + DIG:.3f});")
        n = m
    pts = []
    for n in range(N):
        yy = y + DIG * v[n]
        if pts and v[n] != v[n - 1]:
            pts.append(f"({x(n):.3f},{y + DIG * v[n - 1]:.3f})")
        pts.append(f"({x(n):.3f},{yy:.3f})")
    pts.append(f"({x(N):.3f},{y + DIG * v[-1]:.3f})")
    L.append(f"\\draw[line width=0.7pt] " + " -- ".join(pts) + ";")


def analogico(L, f, d, y):
    """y_i con sus dos umbrales; y es la base del carril."""
    alto = max(1.0, max(d["y"])) * SY      # un apilamiento puede pasar de 1
    L.append(f"\\draw[black!25] (0,{y:.3f}) -- ({x(N):.3f},{y:.3f});")
    for nivel, estilo, txt, ancla in (
            (d["thr"], "dashed, black!65", f"$\\theta_{f}$", "south west"),
            (d["thr"] - d["hyst"], "dotted, black!65", f"$\\theta_{f} - h_{f}$", "north west")):
        yy = y + nivel * SY
        L.append(f"\\draw[{estilo}, line width=0.5pt] (0,{yy:.3f}) -- ({x(N):.3f},{yy:.3f});")
        L.append(f"\\node[font=\\scriptsize, anchor={ancla}, inner sep=1pt] at "
                 f"({x(N) + 0.05:.3f},{yy:.3f}) {{{txt}}};")
    pts = " -- ".join(f"({x(n) + DX / 2:.3f},{y + v * SY:.3f})" for n, v in enumerate(d["y"]))
    L.append(f"\\draw[line width=0.8pt, azul!80!black] {pts};")
    L.append(f"\\node[carril] at (0,{y + alto / 2:.3f}) {{$y_{f}$ · IN{d['ch']}}};")
    return alto


TAGS = {
    "detectado": "fill=verde!55",
    "t_rearm":   "fill=rojo",
    "livetime":  "fill=white, draw=rojo!80!black, dashed, line width=0.6pt",
}


def escena(e, y0):
    r, arm, res = calcular(e)
    L = [f"\\node[anchor=south west, font=\\small\\bfseries, inner sep=0pt] "
         f"at (-2.3,{y0:.2f}) {{{e['titulo']}}};"]
    y = y0 - 0.25
    ytop = y

    for f in ("A", "B"):
        alto = max(1.0, max(r[f]["y"])) * SY
        analogico(L, f, r[f], y - alto)
        y -= alto + GAP
        y -= DIG
        digital(L, r[f]["a"], y, "amarillo")
        L.append(f"\\node[carril] at (0,{y + DIG / 2:.3f}) {{$a_{f}$}};")
        y -= GAP + 0.08

    y -= DIG + 0.04
    digital(L, arm, y, "rojo")
    L.append(f"\\node[carril] at (0,{y + DIG / 2:.3f}) {{\\texttt{{trig\\_arm}}}};")
    yarm = y

    # las llegadas: una línea por pulso, con su número arriba
    for j, (n0, _, _) in enumerate(e["pulsos"]):
        L.insert(1, f"\\draw[black!18, line width=0.4pt] ({x(n0):.3f},{ytop + 0.05:.3f}) -- "
                    f"({x(n0):.3f},{yarm - 0.12:.3f});")
        L.append(f"\\node[font=\\scriptsize\\bfseries, above, inner sep=1pt] at "
                 f"({x(n0):.3f},{ytop + 0.03:.3f}) {{{j + 1}}};")

    # qué pasó con cada pulso, colgando de su línea. El rótulo sale a la
    # derecha y la línea de un pulso posterior lo cruzaría si quedara más
    # arriba: se asignan de atrás para adelante, cada uno debajo de las líneas
    # que caen sobre su largo.
    y = yarm - 0.12
    tags = []
    for n0, por, cas in res:
        if por:
            tags.append((n0, f"detectado por {' y '.join(por)}", TAGS["detectado"]))
        else:
            tags.append((n0, f"perdido · en {cas.replace('_', chr(92) + '_')}", TAGS[cas]))
    fin = [x(n0) + 0.13 * len(txt.replace(chr(92), '')) + 0.2 for n0, txt, _ in tags]
    nivel = [0] * len(tags)
    for i in range(len(tags) - 1, -1, -1):
        for j in range(i + 1, len(tags)):
            if x(tags[j][0]) <= fin[i]:
                nivel[i] = max(nivel[i], nivel[j] + 1)
    for (n0, txt, est), k in zip(tags, nivel):
        yt = y - 0.27 - 0.36 * k
        L.append(f"\\draw[black!50, line width=0.3pt] ({x(n0):.3f},{y:.3f}) -- ({x(n0):.3f},{yt:.3f});")
        L.append(f"\\node[font=\\scriptsize, line width=0.4pt, {est}, anchor=west, "
                 f"inner sep=1.5pt, rounded corners=1pt] at ({x(n0):.3f},{yt:.3f}) {{{txt}}};")
    niveles = max(nivel)
    return L, y - 0.27 - 0.36 * niveles - 0.75


PLANTILLA = r"""%% Tiempo de relanzamiento con dos fuentes en la máscara OR. GENERADO por
%% figuras_relanzamiento.py: no editar a mano.
%% El epígrafe no va en la figura: está en relanzamiento_or.txt.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../figuras/estilo_tikz.tex}
\tikzset{carril/.style={anchor=east, font=\scriptsize, inner sep=2pt, xshift=-3pt}}
\begin{document}
\begin{tikzpicture}[fondo]
%s
\end{tikzpicture}
\end{document}
"""


def figura():
    L, y = [], 0.0
    for e in ESCENAS:
        lin, y = escena(e, y)
        L += lin
    items = ", ".join(f"{c}/{t}" for t, c in
                      (("fuente desarmada", "amarillo"),
                       ("todas desarmadas: \\texttt{t\\_rearm}", "rojo")))
    L.append(f"\\leyenda{{-1.8,{y + 0.3:.2f}}}{{{items}}}{{}}")
    return L


def compilar():
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                        f"-output-directory={tmp}", TEX.name],
                       cwd=AQUI, check=True, capture_output=True)
        pdf = AQUI / f"{NOMBRE}.pdf"
        shutil.copy(Path(tmp) / f"{NOMBRE}.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print(f"escrito {NOMBRE}.pdf y .svg")


def main():
    for e in ESCENAS:
        _, _, res = calcular(e)
        print(e["titulo"], res)
    TEX.write_text(PLANTILLA % "\n".join(figura()))
    print(f"escrito {TEX.name}")
    compilar()


if __name__ == "__main__":
    main()
