#!/usr/bin/env python3
"""Cronograma del tiempo muerto: el mismo tren de pulsos con una y con dos ranuras.

Lee tm_cronograma.csv, que escribe tb_tm_cronograma.sv corriendo DOS mca_top
(una ranura y dos) con la misma entrada y los mismos disparos, y escribe
tm_cronograma.tex en el estilo comun de las figuras TikZ. Despues lo compila a
.pdf y .svg.

Todo lo que se dibuja sale del CSV: el estado de cada ranura, los casilleros
(dt_*), los periodos muertos (`bloqueado`/`dead_len` de mca_top) y el resumen
de la derecha, que son los registros descontados a su valor en la fila 0. Si cambia
el RTL, cambia la figura sin tocar este script.

    python3 tm_cronograma.py          # con el CSV versionado
    python3 tm_cronograma.py --sim    # re-simula antes (vlog/vsim en el PATH)
"""
import argparse
import csv
import shutil
import subprocess
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MCA = AQUI.parents[3]                      # prj/MCA
MODULO = MCA / "modulos" / "mca"
CSV = AQUI / "tm_cronograma.csv"
TEX = AQUI / "tm_cronograma.tex"
TB = AQUI / "tb_tm_cronograma.sv"

DX = 0.064            # cm por ciclo
SX = 1.9 / 420        # cm por cuenta, carril de la senal

# Estado de una ranura: nombre, color
RANURA = {1: ("midiendo", "verde!55"), 2: ("publica", "amarillo")}
# Casilleros del teselado: nombre en la figura, color
CASILLEROS = {
    "win":  ("t\\_win",  "verde!55"),
    "div":  ("t\\_div",  "amarillo"),
    "vivo": ("livetime", "white"),
}
LETRAS = "ABCDEFGH"


def simular():
    rtl = [MODULO / l.strip() for l in (MODULO / "files.f").read_text().splitlines()
           if l.strip() and not l.startswith("#")]
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["vlib", "work"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["vlog", "-sv", "-quiet", "-work", "work", *map(str, rtl), str(TB)],
                       cwd=tmp, check=True)
        subprocess.run(["vsim", "-c", "-quiet", "-do", "run -all; quit -f",
                        "work.tb_tm_cronograma", f"+CSV={CSV}"],
                       cwd=tmp, check=True, capture_output=True)
    print(f"escrito {CSV.name}")


def leer():
    with CSV.open() as f:
        return [{k: int(v) for k, v in r.items()} for r in csv.DictReader(f)]


def casillero(r, u):
    if r[f"{u}_win"]:
        return "win"
    if r[f"{u}_div"]:
        return "div"
    return "vivo"


def tramos(filas, clave):
    """[(valor, primer ciclo, ultimo ciclo)] de las rachas de clave(fila)."""
    out = []
    for r in filas:
        v = clave(r)
        if out and out[-1][0] == v:
            out[-1][2] = r["n"]
        else:
            out.append([v, r["n"], r["n"]])
    return out


def x(n):
    return n * DX


def arribos(filas, u):
    """Ciclos con disparo y a que casillero fue: el contador que se movio."""
    out = []
    for i, r in enumerate(filas[:-1]):
        s = filas[i + 1]
        for k, txt in (("open", "abrió"), ("lact", "perdido: todas midiendo"),
                       ("lbusy", "perdido: esperando publicar")):
            if s[f"{u}_{k}"] != r[f"{u}_{k}"]:
                out.append((r["n"], k, txt))
    return out


def niveles(arr, ciclos_por_letra=1.45):
    """El nivel de cada rotulo de arribo, 0 el mas cercano a la marca.

    El rotulo sale a la derecha de su marca, y la linea que baja de una marca
    posterior lo cruzaria si el rotulo quedara mas arriba que el nivel al que
    ella baja. Se asignan de atras para adelante: cada rotulo va debajo de las
    lineas que caen sobre su largo, y de los rotulos del mismo nivel con que
    se pisaria."""
    out = [0] * len(arr)
    fin = [n + 2 + len(txt) * ciclos_por_letra for n, _, txt in arr]
    for i in range(len(arr) - 1, -1, -1):
        nivel = 0
        for j in range(i + 1, len(arr)):
            if arr[j][0] <= fin[i]:
                nivel = max(nivel, out[j] + 1)
        out[i] = nivel
    return out


def franja(L, filas, y, alto, clave, colores, rotulo=None, min_txt=18):
    for v, a, b in tramos(filas, clave):
        if v not in colores:
            continue
        nombre, color = colores[v]
        L.append(f"\\draw[fill={color}, line width=0.4pt] ({x(a):.3f},{y:.2f}) rectangle "
                 f"({x(b + 1):.3f},{y + alto:.2f});")
        if b - a + 1 >= min_txt:
            L.append(f"\\node[nodo, black] at ({x((a + b + 1) / 2):.3f},{y + alto / 2:.2f}) "
                     f"{{{nombre}}};")
    ult = filas[-1]["n"] + 1
    L.append(f"\\draw[black!30, line width=0.3pt] (0,{y:.2f}) rectangle ({x(ult):.2f},{y + alto:.2f});")
    if rotulo:
        L.append(f"\\node[carril] at (0,{y + alto / 2:.2f}) {{{rotulo}}};")


def modo(filas, u, titulo, y0, n_ranuras):
    """Un bloque de carriles para una instancia. Devuelve (lineas, y siguiente)."""
    L = []
    L.append(f"\\node[anchor=south west, font=\\small\\bfseries, inner sep=0pt] "
             f"at (-2.2,{y0 + 0.15:.2f}) {{{titulo}}};")
    y = y0 - 0.2

    # una franja por ranura
    alto = 0.36
    for k in range(n_ranuras):
        y -= alto + 0.06
        franja(L, filas, y, alto, lambda r, k=k: r[f"{u}_s{k}"], RANURA,
               rotulo=f"ranura {k}")
    y_ult_ranura = y

    # el casillero de cada ciclo
    y -= 0.5
    alto = 0.4
    franja(L, filas, y, alto, lambda r: casillero(r, u),
           {c: CASILLEROS[c] for c in CASILLEROS}, rotulo="casillero", min_txt=14)
    y_cas = y

    # los arribos y a donde fueron: el rotulo cuelga de la marca, en el nivel
    # que deja niveles()
    arr = arribos(filas, u)
    for (n, k, txt), nivel in zip(arr, niveles(arr)):
        yt = y_cas - 0.3 - 0.17 * nivel
        L.append(f"\\fill ({x(n + 0.5):.3f},{y_cas - 0.04:.2f}) -- ++(-0.09,-0.16) "
                 f"-- ++(0.18,0) -- cycle;")
        L.append(f"\\draw[black!50, line width=0.3pt] ({x(n + 0.5):.3f},{y_cas - 0.2:.2f}) -- "
                 f"({x(n + 0.5):.3f},{yt:.2f}) -- ++(0.08,0);")
        L.append(f"\\node[nodo, black, anchor=west] at ({x(n + 0.5) + 0.08:.3f},{yt:.2f}) "
                 f"{{{txt}}};")
    y -= 0.95

    # el tiempo muerto: los tramos de `bloqueado` en rojo, y adentro el largo
    # que guarda dead_len al terminar el periodo
    alto = 0.4
    y -= alto
    ult = filas[-1]["n"] + 1
    L.append(f"\\draw[black!30, line width=0.3pt] (0,{y:.2f}) rectangle ({x(ult):.2f},{y + alto:.2f});")
    hay = False
    for v, a, b in tramos(filas, lambda r: r[f"{u}_bloq"]):
        if not v or b + 1 >= len(filas):
            continue
        hay = True
        largo = filas[b + 1][f"{u}_dlen"]          # dead_len sostenido al cerrar
        assert largo == b - a + 1, (u, a, b, largo)
        ext = filas[b + 1][f"{u}_ext"] != filas[a][f"{u}_ext"]
        L.append(f"\\draw[fill=rojo, line width=0.4pt] ({x(a):.3f},{y:.2f}) rectangle "
                 f"({x(b + 1):.3f},{y + alto:.2f});")
        etq = f"$L = {largo}$" + ("\\,{\\tiny · con arribo}" if ext else "")
        L.append(f"\\node[font=\\scriptsize, inner sep=0pt] at "
                 f"({x((a + b + 1) / 2):.3f},{y + alto / 2:.2f}) {{{etq}}};")
    if not hay:
        L.append(f"\\node[nodo, anchor=west] at (0.1,{y + alto / 2:.2f}) "
                 f"{{nunca se ocuparon todas: no hay tiempo muerto}};")
    L.append(f"\\node[carril] at (0,{y + alto / 2:.2f}) {{tiempo muerto}};")
    return L, y - 0.75


def resumen(filas, u):
    """Los registros al final de la escena, descontados a la fila 0."""
    f0, f1 = filas[0], filas[-1]
    d = {k: f1[f"{u}_{k}"] - f0[f"{u}_{k}"] for k in
         ("tw", "td", "tl", "rt", "per", "ext", "open", "lact", "lbusy", "pile",
          "o0", "o1", "o2", "o3", "o4")}
    assert d["o3"] == d["o4"] == 0, d                         # habilitadas: dos
    assert d["tw"] + d["td"] + d["tl"] == d["rt"], d          # teselado sin veto
    assert sum(d[f"o{j}"] for j in range(5)) == d["rt"], d   # ocupacion
    d["maxl"] = f1[f"{u}_maxl"]
    d["ev"] = sum(r[f"{u}_ev"] for r in filas)
    return d


def tabla(filas, x0, y0):
    d0, d1 = resumen(filas, "u0"), resumen(filas, "u1")
    renglones = [
        ("t\\_win", "tw"), ("t\\_div", "td"), ("livetime", "tl"), None,
        ("t\\_ocup[0]", "o0"), ("t\\_ocup[1]", "o1"), ("t\\_ocup[2]", "o2"), None,
        ("cnt\\_open", "open"), ("cnt\\_lost\\_active", "lact"),
        ("cnt\\_lost\\_busy", "lbusy"),
        ("eventos", "ev"), ("cnt\\_pileup", "pile"), None,
        ("cnt\\_dead\\_periods", "per"), ("max\\_dead\\_len", "maxl"),
    ]
    cuerpo = ["& \\textbf{1 ranura} & \\textbf{2 ranuras}\\\\[1pt]"]
    for r in renglones:
        if r is None:
            cuerpo.append("[3pt]")
            continue
        etq, k = r
        nombre = etq if k == "ev" else f"\\texttt{{{etq}}}"
        cuerpo.append(f"{nombre} & {d0[k]} & {d1[k]}\\\\")
    return (f"\\node[anchor=west, font=\\scriptsize, draw=black!40, rounded corners=2pt, "
            f"inner sep=4pt] at ({x0:.2f},{y0:.2f}) "
            f"{{\\begin{{tabular}}{{@{{}}l@{{\\hspace{{8pt}}}}r@{{\\hspace{{8pt}}}}r@{{}}}}"
            f"{''.join(cuerpo)}\\end{{tabular}}}};")


def figura(filas):
    ult = filas[-1]["n"] + 1
    L = []
    # --- la senal, comun a las dos instancias ---
    L.append(f"\\draw[black!25] (0,0) -- ({x(ult):.2f},0);")
    pts = " -- ".join(f"({x(r['n'] + 0.5):.3f},{max(r['x'], 0) * SX:.3f})" for r in filas)
    L.append(f"\\draw[line width=0.8pt, azul!80!black] {pts};")
    L.append(f"\\node[carril] at (0,{0.9:.2f}) {{x = dat $-$ base}};")
    # los disparos: el pulso de trig, con la letra del pulso
    disparos = [r["n"] for r in filas if r["trig"]]
    for k, n in enumerate(disparos):
        L.append(f"\\draw[->, line width=0.6pt, rojo!80!black] ({x(n + 0.5):.3f},2.25) -- "
                 f"({x(n + 0.5):.3f},1.95);")
        L.append(f"\\node[font=\\scriptsize\\bfseries, above] at ({x(n + 0.5):.3f},2.22) "
                 f"{{{LETRAS[k]}}};")
    L.append(f"\\node[carril] at (0,2.1) {{trig\\_i}};")

    b0, y = modo(filas, "u0", "\\texttt{cfg\\_n\\_acc = 1} · una ranura", -0.55, 1)
    b1, y = modo(filas, "u1", "\\texttt{cfg\\_n\\_acc = 2} · dos ranuras", y - 0.1, 2)
    L += b0 + b1
    L.append(tabla(filas, x(ult) + 0.5, (-0.55 + y) / 2))

    # guias verticales en los disparos
    for n in disparos:
        L.insert(0, f"\\draw[black!18, line width=0.4pt] ({x(n + 0.5):.3f},2.0) -- "
                    f"({x(n + 0.5):.3f},{y + 0.35:.2f});")

    # eje de ciclos
    L.append(f"\\draw[black!60] (0,{y + 0.3:.2f}) -- ({x(ult):.2f},{y + 0.3:.2f});")
    for n in range(0, ult + 1, 25):
        L.append(f"\\draw[black!60] ({x(n):.3f},{y + 0.3:.2f}) -- ++(0,-0.08) "
                 f"node[nodo, below] {{{n}}};")
    L.append(f"\\node[nodo, anchor=north east] at ({x(ult):.2f},{y - 0.05:.2f}) "
             f"{{ciclos de adc\\_clk (8 ns); sin decimar, un ciclo es una muestra}};")

    yl = y - 0.75
    items = ", ".join(f"{c}/{n}" for n, c in
                      (("ranura midiendo; todas midiendo (t\\_win)", "verde!55"),
                       ("cerrada y esperando publicar (t\\_div)", "amarillo"),
                       ("libre; puede abrir (livetime)", "white"),
                       ("tiempo muerto: ninguna libre", "rojo")))
    L.append(f"\\leyenda{{-0.6,{yl:.2f}}}{{{items}}}")
    L.append("  {Simulación de \\texttt{mca\\_top} (\\texttt{tb\\_tm\\_cronograma}): compuertas "
             "8/40, base fija, sin retardo extra, y cada pulso con su disparo (flecha roja). "
             "La ventana ocupa la compuerta más un ciclo, y la publicación 18. El tiempo "
             "muerto es cada tramo sin ranura libre (\\texttt{bloqueado}), y $L$ su largo en "
             "ciclos, el que guarda \\texttt{dead\\_len}. El resumen son los registros al "
             "final de la escena.}")
    return L


PLANTILLA = r"""%% Cronograma del tiempo muerto. GENERADO por tm_cronograma.py desde
%% tm_cronograma.csv: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../../figuras/estilo_tikz.tex}
\tikzset{carril/.style={anchor=east, font=\scriptsize, inner sep=2pt, xshift=-3pt}}
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
        pdf = AQUI / "tm_cronograma.pdf"
        shutil.copy(Path(tmp) / "tm_cronograma.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print("escrito tm_cronograma.pdf y .svg")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim", action="store_true", help="re-simular con Questa antes de dibujar")
    a = ap.parse_args()
    if a.sim:
        simular()
    TEX.write_text(PLANTILLA % "\n".join(figura(leer())))
    print(f"escrito {TEX.name}")
    compilar()


if __name__ == "__main__":
    main()
