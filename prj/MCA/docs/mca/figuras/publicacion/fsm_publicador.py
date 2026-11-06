#!/usr/bin/env python3
"""La maquina de estados del publicador (mca_publish) y un cronograma de dos eventos.

Arriba, la FSM tal como esta en el RTL: dos estados, la cola de indices y lo
que hace cada transicion. Abajo, el cronograma ciclo a ciclo que vuelca
tb_fsm_publicador.sv: dos ranuras que cierran separadas por 8 ciclos, la
primera con la cola vacia (arranque directo) y la segunda con el publicador
ocupado, que espera en la cola. Escribe fsm_publicador.tex en el estilo comun
de las figuras TikZ y lo compila a .pdf y .svg.

    python3 fsm_publicador.py          # con el CSV versionado
    python3 fsm_publicador.py --sim    # re-simula antes (vlog/vsim en el PATH)
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
CSV = AQUI / "fsm_publicador.csv"
TEX = AQUI / "fsm_publicador.tex"
TB = AQUI / "tb_fsm_publicador.sv"

N0, N1 = 4, 70        # ciclos que se dibujan
DX = 0.2              # cm por ciclo
ALTO = 0.3            # alto de una senal
PASO = 0.46           # de un renglon al siguiente

RANURA = {1: ("midiendo", "verde!55"), 2: ("cerrada", "amarillo")}


def simular():
    rtl = [MODULO / l.strip() for l in (MODULO / "files.f").read_text().splitlines()
           if l.strip() and not l.startswith("#")]
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["vlib", "work"], cwd=tmp, check=True, capture_output=True)
        subprocess.run(["vlog", "-sv", "-quiet", "-work", "work", *map(str, rtl), str(TB)],
                       cwd=tmp, check=True)
        subprocess.run(["vsim", "-c", "-quiet", "-do", "run -all; quit -f",
                        "work.tb_fsm_publicador", f"+CSV={CSV}"],
                       cwd=tmp, check=True, capture_output=True)
    print(f"escrito {CSV.name}")


def leer():
    with CSV.open() as f:
        return [{k: int(v) for k, v in r.items()} for r in csv.DictReader(f)
                if N0 <= int(r["n"]) < N1]


def x(n):
    return (n - N0) * DX


def tramos(filas, clave):
    out = []
    for r in filas:
        v = clave(r)
        if out and out[-1][0] == v:
            out[-1][2] = r["n"]
        else:
            out.append([v, r["n"], r["n"]])
    return out


def primero(filas, clave):
    return next(r["n"] for r in filas if clave(r))


def digital(L, filas, y, nombre, clave):
    pts = []
    for r in filas:
        h = y + (ALTO if clave(r) else 0.0)
        pts += [f"({x(r['n']):.2f},{h:.2f})", f"({x(r['n'] + 1):.2f},{h:.2f})"]
    L.append(f"\\draw[line width=0.7pt] {' -- '.join(pts)};")
    L.append(f"\\node[carril] at ({x(N0):.2f},{y + ALTO / 2:.2f}) {{{nombre}}};")


def bus(L, filas, y, nombre, clave, texto, color=lambda v: "white", min_txt=2):
    for v, a, b in tramos(filas, clave):
        if v is None:
            L.append(f"\\draw[black!45, line width=0.4pt] ({x(a):.2f},{y + ALTO / 2:.2f}) -- "
                     f"({x(b + 1):.2f},{y + ALTO / 2:.2f});")
            continue
        L.append(f"\\draw[fill={color(v)}, line width=0.5pt] ({x(a):.2f},{y:.2f}) rectangle "
                 f"({x(b + 1):.2f},{y + ALTO:.2f});")
        if b - a + 1 >= min_txt:
            L.append(f"\\node[nodo, black] at ({x((a + b + 1) / 2):.2f},{y + ALTO / 2:.2f}) "
                     f"{{{texto(v, b - a + 1)}}};")
    L.append(f"\\node[carril] at ({x(N0):.2f},{y + ALTO / 2:.2f}) {{{nombre}}};")


def cota(L, a, b, y, texto, lado="below"):
    L.append(f"\\draw[<->, line width=0.5pt] ({x(a):.2f},{y:.2f}) -- ({x(b):.2f},{y:.2f}) "
             f"node[midway, {lado}, nodo, black] {{{texto}}};")


def cronograma(filas, y0):
    L = []
    y = y0
    rows = []

    def renglon():
        nonlocal y
        y -= PASO
        rows.append(y)
        return y

    digital(L, filas, renglon(), "trig\\_i", lambda r: r["trig"])
    for k in (0, 1):
        bus(L, filas, renglon(), f"ranura {k}",
            lambda r, k=k: r[f"s{k}"] or None,
            lambda v, n: f"{RANURA[v][0]} ({n})", lambda v: RANURA[v][1])
    y_ran1 = y
    digital(L, filas, renglon(), "acepta[0]", lambda r: r["acepta0"])
    digital(L, filas, renglon(), "acepta[1]", lambda r: r["acepta1"])
    bus(L, filas, renglon(), "cola: n\\_cola", lambda r: r["n_cola"] or None,
        lambda v, n: str(v), lambda v: "grisr")
    y -= 0.25                             # lugar para los rotulos del arranque
    bus(L, filas, renglon(), "pst", lambda r: r["pst"],
        lambda v, n: "DIV" if v else "IDLE", lambda v: "azul!30" if v else "white", min_txt=4)
    y_pst = y
    bus(L, filas, renglon(), "cur", lambda r: r["cur"] if r["pst"] else None,
        lambda v, n: str(v), lambda v: "azul!12")
    digital(L, filas, renglon(), "div\\_start", lambda r: r["div_start"])
    digital(L, filas, renglon(), "divisor ocupado", lambda r: r["busy"])
    y_busy = y
    digital(L, filas, renglon(), "div\\_valid", lambda r: r["div_valid"])
    digital(L, filas, renglon(), "libera[0]", lambda r: r["libera0"])
    digital(L, filas, renglon(), "libera[1]", lambda r: r["libera1"])
    digital(L, filas, renglon(), "ev\\_valid", lambda r: r["ev_valid"])
    # el bus sostiene el ultimo evento: el de la ranura que estaba en `cur` el
    # ciclo anterior a ev_valid
    cur_de = {r["n"] + 1: r["cur"] for r in filas}
    evs = [(r["n"], cur_de[r["n"]]) for r in filas if r["ev_valid"]]

    def evento(r):
        prev = [k for n, k in evs if n <= r["n"]]
        return prev[-1] if prev else None
    bus(L, filas, renglon(), "ev\\_feat", evento,
        lambda v, n: f"ranura {v}", lambda v: "rojo!25")
    bus(L, filas, renglon(), "casillero", lambda r: 1 if r["dt_div"] else None,
        lambda v, n: f"t\\_div ({n})", lambda v: "amarillo")
    y_fin = y

    # guias verticales cada 5 ciclos y eje
    for n in range(N0 - N0 % 5 + 5, N1, 5):
        L.insert(0, f"\\draw[black!10, line width=0.3pt] ({x(n):.2f},{y0 - 0.1:.2f}) -- "
                    f"({x(n):.2f},{y_fin - 0.15:.2f});")
    L.append(f"\\draw[black!60] ({x(N0):.2f},{y_fin - 0.15:.2f}) -- ({x(N1):.2f},{y_fin - 0.15:.2f});")
    for n in range(N0 - N0 % 5 + 5, N1, 5):
        L.append(f"\\draw[black!60] ({x(n):.2f},{y_fin - 0.15:.2f}) -- ++(0,-0.07) "
                 f"node[below, nodo] {{{n}}};")
    L.append(f"\\node[nodo, anchor=north east] at ({x(N1):.2f},{y_fin - 0.45:.2f}) "
             f"{{ciclos de adc\\_clk}};")

    # anotaciones: las saca del CSV
    a0 = primero(filas, lambda r: r["acepta0"])
    l0 = primero(filas, lambda r: r["libera0"])
    a1 = primero(filas, lambda r: r["acepta1"])
    l1 = primero(filas, lambda r: r["libera1"])
    s1 = primero(filas, lambda r: r["div_start"] and r["cur"] == 1)
    ocup = [r["n"] for r in filas if r["busy"]]
    cota(L, ocup[0], ocup[0] + 16, y_busy - 0.05, "16 iteraciones")
    L.append(f"\\node[nodo, anchor=south, fill=white, inner sep=1pt] at ({x(a0 + 1.5):.2f},"
             f"{y_pst + ALTO + 0.02:.2f}) {{arranque directo}};")
    L.append(f"\\node[nodo, anchor=south west, fill=white, inner sep=1pt] at ({x(l0 + 1):.2f},"
             f"{y_pst + ALTO + 0.02:.2f}) {{un ciclo en IDLE: toma la cabeza}};")
    L.append(f"\\node[nodo, anchor=west, align=left] at ({x(N1) + 0.15:.2f},{rows[1] + ALTO / 2:.2f}) "
             f"{{cerrada {l0 - a0} ciclos:\\\\la publicación}};")
    L.append(f"\\node[nodo, anchor=west, align=left] at ({x(N1) + 0.15:.2f},{rows[2] + ALTO / 2:.2f}) "
             f"{{cerrada {l1 - a1} ciclos: {s1 - a1 - 1}\\\\en la cola y 18 publicando}};")
    return L, y_fin - 0.9


# --------------------------------------------------------------------- la FSM
FSM = r"""
\node[estado, fill=white] (idle) at (0,0) {\textbf{IDLE}\\[1pt] espera};
\node[estado, fill=azul!30] (div) at (7.4,0) {\textbf{DIV}\\[1pt] los dos divisores\\iteran};
\draw[flujo] (idle.north east) to[out=25, in=155] node[above, align=center, font=\scriptsize]
  {\texttt{!vacia || hay\_cierre}\\[1pt]
   {\scriptsize\itshape $\to$ div\_start $\leftarrow$ 1;\ \ cur $\leftarrow$ vacia ? la que cierra : la cabeza}}
  (div.north west);
\draw[flujo] (div.south west) to[out=-155, in=-25] node[below, align=center, font=\scriptsize]
  {\texttt{div\_valid}\\[1pt]
   {\scriptsize\itshape $\to$ ev\_feat $\leftarrow$ las 16 ranuras, desde \texttt{cur} y los cocientes;}\\
   {\scriptsize\itshape ev\_valid $\leftarrow$ 1;\ \ libera[cur];\ \ sale la cabeza de la cola}}
  (idle.south east);
\draw[flujo] (div.east) to[out=30, in=-30, looseness=5] node[right, font=\scriptsize\ttfamily] {!div\_valid} (div.east);
\draw[flujo] (idle.west) to[out=150, in=210, looseness=5] node[left, font=\scriptsize, align=right]
  {\texttt{vacia \&\&}\\\texttt{!hay\_cierre}} (idle.west);

% la cola
\node[draw=black, line width=0.6pt, fill=grisr, anchor=north west, align=left,
      text width=4.6cm, inner sep=4pt, font=\scriptsize]
  (cola) at (10.6,1.35)
  {\textbf{la cola de índices} (\texttt{N\_ACC} lugares)\\[1pt]
   en orden de cierre. Cada ciclo, a la vez que la FSM: sale la cabeza si se
   publicó, y entran las que cierran (\texttt{acepta}), por índice. Nunca
   desborda: cada ranura está a lo sumo una vez.};
\node[anchor=north west, text width=4.8cm, align=left, font=\scriptsize\itshape, black!70]
  at ([yshift=-4pt]cola.south west)
  {Los operandos salen de \texttt{cur}, un registro: el divisor los engancha el ciclo
   después de \texttt{div\_start}. Decidir y cargar en el mismo flanco daba
   $-0.734$\,ns (trece niveles).\\[3pt]
   Una ranura cerrada guarda su resultado hasta \texttt{libera}: las ranuras
   \emph{son} la memoria de la cola.};
"""


def figura(filas):
    L = ["\\node[titulo] at (-3.0,2.75) {\\textbf{El publicador} \\quad "
         "{\\scriptsize\\ttfamily mca\\_publish: la FSM y dos eventos ciclo a ciclo}};"]
    L.append("\\begin{scope}[shift={(0.9,0.0)}]")
    L.append(FSM)
    L.append("\\end{scope}")
    cr, y = cronograma(filas, -3.2)
    L += cr
    items = ", ".join(f"{c}/{n}" for n, c in
                      (("ranura midiendo", "verde!55"),
                       ("cerrada: guarda el resultado", "amarillo"),
                       ("publicador en DIV", "azul!30")))
    L.append(f"\\leyenda{{-2.4,{y:.2f}}}{{{items}}}")
    L.append("  {Simulación de \\texttt{mca\\_top} (\\texttt{tb\\_fsm\\_publicador}): dos ranuras, "
             "compuerta de 20 muestras y dos disparos separados por 8. La ranura 0 cierra con la "
             "cola vacía y arranca en el mismo flanco; la 1 cierra con el publicador ocupado y "
             "espera. \\texttt{n\\_cola} incluye a la que se está publicando. Mientras ninguna "
             "está libre, el ciclo va a \\texttt{t\\_div}.}")
    return L


PLANTILLA = r"""%% El publicador. GENERADO por fsm_publicador.py desde fsm_publicador.csv:
%% no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../../figuras/estilo_tikz.tex}
\tikzset{
  carril/.style = {anchor=east, font=\scriptsize, inner sep=2pt, xshift=-3pt},
  estado/.style = {draw=black, line width=0.7pt, rounded corners=9pt, align=center,
                   font=\scriptsize, inner sep=4pt, minimum height=1.0cm, text width=2.2cm},
}
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
        pdf = AQUI / "fsm_publicador.pdf"
        shutil.copy(Path(tmp) / "fsm_publicador.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print("escrito fsm_publicador.pdf y .svg")


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
