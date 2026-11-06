#!/usr/bin/env python3
"""Cuanto cuesta cada ranura: la sintesis OOC de mca_top con N_ACC = 1..7.

Con --sintetizar corre las siete sintesis (Vivado 2021.2, la misma
modulos/mk/syn_ooc.tcl de `make syn`, con los parametros del top y N_ACC
encima), de a dos por la memoria (~3 GB cada una), y escribe
recursos_ranuras.csv con lo que cuesta cada bloque segun el reporte
jerarquico. Sin el flag usa el CSV versionado. Despues dibuja
recursos_ranuras.tex en el estilo comun de las figuras TikZ y lo compila a
.pdf y .svg.

N_ACC llega a 7 porque cfg_n_acc tiene 3 bits (NA_W en mca_top).

    python3 recursos_ranuras.py                 # con el CSV versionado
    python3 recursos_ranuras.py --sintetizar    # ~5 minutos
"""
import argparse
import csv
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MCA = AQUI.parents[3]                      # prj/MCA
MODULOS = MCA / "modulos"
MOD_DIR = MODULOS / "mca"
CSV = AQUI / "recursos_ranuras.csv"
TEX = AQUI / "recursos_ranuras.tex"

VIVADO = "/tools/Xilinx/Vivado/2021.2/settings64.sh"
GEN = "H_AW=13 H2_AW=7 PSD_AW=6"           # los de i_mca en mca_red_pitaya_top
NS = range(1, 8)
DISPOSITIVO = {"lut": 17600, "ff": 35200}   # xc7z010

CAMPOS = ["n", "lut", "ff", "lut_slot", "ff_slot", "lut_alr", "ff_alr", "lut_dly", "ff_dly",
          "ramb36", "ramb18", "dsp", "wns", "niveles", "destino"]


# ------------------------------------------------------------------ sintesis
def fila(txt, inst):
    """(Total LUTs, FFs, RAMB36, RAMB18, DSP) de una instancia del reporte jerarquico."""
    for l in txt.splitlines():
        c = [x.strip() for x in l.split("|")]
        if len(c) > 10 and c[1] == inst:
            return int(c[3]), int(c[7]), int(c[8]), int(c[9]), int(c[10])
    raise KeyError(inst)


def leer_corrida(d, n):
    t = (d / "util_hier.rpt").read_text()
    m = dict(l.split("=", 1) for l in (d / "metrics.txt").read_text().splitlines() if "=" in l)
    tot = fila(t, "mca_top")
    sl = [fila(t, f"g_slot[{k}].i_slot") for k in range(n)]
    # alrededor de las ranuras: el asignador (mca_window sin sus hijos), el
    # publicador y lo propio de mca_top (contabilidad, t_ocup, registros)
    alr = [fila(t, i) for i in ("(i_win)", "i_pub", "(mca_top)")]
    dly = fila(t, "i_dly")
    return {"n": n, "lut": tot[0], "ff": tot[1],
            "lut_slot": sum(s[0] for s in sl), "ff_slot": sum(s[1] for s in sl),
            "lut_alr": sum(a[0] for a in alr), "ff_alr": sum(a[1] for a in alr),
            "lut_dly": dly[0], "ff_dly": dly[1],
            "ramb36": tot[2], "ramb18": tot[3], "dsp": tot[4],
            "wns": float(m["wns_ns"]), "niveles": int(m["logic_levels"]),
            "destino": m["endpoint"]}


def sintetizar():
    srcs = " ".join(str(MOD_DIR / l.strip()) for l in (MOD_DIR / "files.f").read_text().splitlines()
                    if l.strip() and not l.startswith("#"))
    filas = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def lanzar(n):
            d = tmp / f"n{n}"
            (d / "tmp").mkdir(parents=True)
            env = dict(os.environ, MODULE="mca", SYN_TOP="mca_top", MOD_DIR=str(MOD_DIR),
                       SYN_SRCS=srcs, PERIOD_NS="8.0", SYN_GEN=f"{GEN} N_ACC={n}", OUT_DIR=str(d))
            cmd = (f"source {VIVADO} && vivado -nojournal -mode batch "
                   f"-source {MODULOS / 'mk' / 'syn_ooc.tcl'} -log {d / 'syn.log'} -tempDir {d / 'tmp'}")
            return subprocess.Popen(["bash", "-c", cmd], cwd=d, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        ns = list(NS)
        for i in range(0, len(ns), 2):
            ps = [(n, lanzar(n)) for n in ns[i:i + 2]]
            for n, p in ps:
                if p.wait() != 0:
                    raise SystemExit(f"fallo la sintesis con N_ACC={n}: ver {tmp}/n{n}/syn.log")
                filas.append(leer_corrida(tmp / f"n{n}", n))
                print(f"N_ACC={n}: {filas[-1]['lut']} LUT, {filas[-1]['ff']} FF, "
                      f"WNS {filas[-1]['wns']:+.3f} ns")
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"escrito {CSV.name}")


def leer():
    with CSV.open() as f:
        out = []
        for r in csv.DictReader(f):
            out.append({k: (r[k] if k == "destino" else float(r[k]) if k == "wns" else int(r[k]))
                        for k in CAMPOS})
        return out


# ------------------------------------------------------------------- dibujo
ANCHO_B = 0.52        # cm, ancho de una barra
PASO_B = 0.82         # cm, de una barra a la siguiente
ALTO_P = 4.2          # cm, alto del panel

SEGMENTOS = [         # de abajo hacia arriba: clave, color, nombre
    ("fijo", "grisr", "el resto: no depende de N"),
    # sin comas: \leyenda separa las entradas por coma
    ("alr", "azul!45", "alrededor: asignador + publicador + contabilidad"),
    ("slot", "amarillo", "las ranuras: \\texttt{mca\\_slot} $\\times$ N"),
]


def panel(filas, rec, x0, titulo, tope, paso_eje):
    L = []
    esc = ALTO_P / tope
    ancho = len(filas) * PASO_B + 0.3
    L.append(f"\\node[anchor=south west, font=\\scriptsize\\bfseries] at ({x0:.2f},{ALTO_P + 0.25:.2f}) "
             f"{{{titulo}}};")
    for v in range(0, tope + 1, paso_eje):
        y = v * esc
        L.append(f"\\draw[black!12, line width=0.3pt] ({x0:.2f},{y:.3f}) -- ({x0 + ancho:.2f},{y:.3f});")
        L.append(f"\\node[nodo, anchor=east] at ({x0 - 0.05:.2f},{y:.3f}) {{{v}}};")
    L.append(f"\\draw[black!60, line width=0.5pt] ({x0:.2f},0) -- ({x0 + ancho:.2f},0);")
    for i, r in enumerate(filas):
        xa = x0 + 0.25 + i * PASO_B
        partes = {"slot": r[f"{rec}_slot"], "alr": r[f"{rec}_alr"]}
        partes["fijo"] = r[rec] - partes["slot"] - partes["alr"]
        y = 0.0
        for clave, color, _ in SEGMENTOS:
            h = partes[clave] * esc
            L.append(f"\\draw[fill={color}, draw=white, line width=0.6pt] ({xa:.3f},{y:.3f}) "
                     f"rectangle ({xa + ANCHO_B:.3f},{y + h:.3f});")
            y += h
        pct = 100.0 * r[rec] / DISPOSITIVO[rec]
        L.append(f"\\node[nodo, black, anchor=south, align=center] at ({xa + ANCHO_B / 2:.3f},{y:.3f}) "
                 f"{{{r[rec]}\\\\[-1pt]{pct:.0f}\\,\\%}};")
        L.append(f"\\node[font=\\scriptsize, anchor=north] at ({xa + ANCHO_B / 2:.3f},-0.05) {{{r['n']}}};")
    L.append(f"\\node[font=\\scriptsize, anchor=north] at ({x0 + ancho / 2:.2f},-0.4) "
             f"{{\\texttt{{N\\_ACC}}}};")
    # la pendiente: lo que agrega cada ranura, ajustado sobre las siete
    n = [r["n"] for r in filas]
    t = [r[rec] for r in filas]
    mn, mt = sum(n) / len(n), sum(t) / len(t)
    pend = sum((a - mn) * (b - mt) for a, b in zip(n, t)) / sum((a - mn) ** 2 for a in n)
    por_slot = filas[-1][f"{rec}_slot"] / filas[-1]["n"]
    L.append(f"\\node[nodo, black, anchor=north west, align=left, fill=white, inner sep=2pt] at "
             f"({x0 + 0.3:.2f},{ALTO_P + 0.05:.2f}) "
             f"{{+{pend:.0f} por ranura en total\\\\{por_slot:.0f} de la ranura misma}};")
    return L, x0 + ancho


def timing(filas, x0, x1, y):
    L = [f"\\node[anchor=east, font=\\scriptsize] at ({x0 - 0.1:.2f},{y:.2f}) "
         f"{{WNS a 125\\,MHz}};"]
    for i, r in enumerate(filas):
        xa = x0 + 0.25 + i * PASO_B + ANCHO_B / 2
        ok = r["wns"] >= 0
        color = "verde!35" if ok else "rojo!45"
        L.append(f"\\node[draw=black!50, fill={color}, rounded corners=1.5pt, font=\\tiny, "
                 f"minimum width={PASO_B - 0.08:.2f}cm, inner sep=1.5pt] at ({xa:.3f},{y:.2f}) "
                 f"{{{r['wns']:+.3f}}};")
    return L


def figura(filas):
    L = ["\\node[titulo] at (-1.6,5.45) {\\textbf{Cuánto cuesta cada ranura} \\quad "
         "{\\scriptsize\\ttfamily mca\\_top, síntesis OOC con N\\_ACC = 1..7}};"]
    a, xf = panel(filas, "lut", 0.0, "LUT", 10000, 2000)
    b, xf2 = panel(filas, "ff", xf + 1.6, "FF", 10000, 2000)
    L += a + b
    L += timing(filas, 0.0, xf, -1.05)          # el timing es del diseno entero: una vez
    malos = [r for r in filas if r["wns"] < 0]
    if malos:
        peor = min(malos, key=lambda r: r["wns"])
        L.append(f"\\node[nodo, black, anchor=north west, text width={xf2 + 1.0:.1f}cm] at (-1.6,-1.45) "
                 f"{{Cierra hasta N = {min(r['n'] for r in malos) - 1}. El peor, N = {peor['n']}: "
                 f"{peor['wns']:+.3f} ns, {peor['niveles']} niveles, termina en "
                 f"\\texttt{{{peor['destino'].replace('_', chr(92) + '_')}}}.}};")
    items = ", ".join(f"{c}/{n}" for _, c, n in reversed(SEGMENTOS))
    L.append(f"\\leyenda{{-1.2,-2.05}}{{{items}}}")
    f0 = filas[0]
    L.append(f"  {{Sobre la barra, el total y el \\% del xc7z010 (17\\,600 LUT, 35\\,200 FF). "
             f"Las BRAM ({f0['ramb36']} RAMB36 + {f0['ramb18']} RAMB18) y el DSP ({f0['dsp']}) no "
             f"cambian con N: los histogramas y el trapecio son uno solo. LUT son las de "
             f"\\texttt{{report\\_utilization}} (sitios), no las celdas LUT1..LUT6.}}")
    return L


PLANTILLA = r"""%% Costo de las ranuras. GENERADO por recursos_ranuras.py desde
%% recursos_ranuras.csv: no editar a mano.
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
        pdf = AQUI / "recursos_ranuras.pdf"
        shutil.copy(Path(tmp) / "recursos_ranuras.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print("escrito recursos_ranuras.pdf y .svg")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sintetizar", action="store_true",
                    help="correr las siete sintesis antes de dibujar (~5 min)")
    a = ap.parse_args()
    if a.sintetizar:
        sintetizar()
    TEX.write_text(PLANTILLA % "\n".join(figura(leer())))
    print(f"escrito {TEX.name}")
    compilar()


if __name__ == "__main__":
    main()
