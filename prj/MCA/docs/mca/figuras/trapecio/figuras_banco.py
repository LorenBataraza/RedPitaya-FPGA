#!/usr/bin/env python3
"""La figura del banco de trapecios: qué son k, m y la ventana, y cómo se elige la forma.

Todo sale de monte-carlo/replica_mca2.py, el golden model que coincide con el RTL: el
trapecio de cada forma, el instante del disparo con polo-cero, dónde cae cada ventana y
la forma que elige el publicador. Con pulsos sin ruido, de 1000 y 600 cuentas, τ = 243
muestras y 1.6 muestras de subida, y el banco de `mca_banco_config`.

Lo único medido en la placa es el uso de cada forma a 1 Mcps
(docs/mca/pruebas_banco_trapecios.md §6).

    python3 figuras_banco.py
"""
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
SW = AQUI.parents[3] / "software"
sys.path.insert(0, str(SW))
sys.path.insert(0, str(SW / "monte-carlo"))
import replica_mca2 as r                                     # noqa: E402
from API.mca import BANCO_PZ, mca_banco_config               # noqa: E402
from API.multitrigger import pz_ganancia                     # noqa: E402

TAU, TR10, N, T0 = 243.0, 1.6, 420, 40
MQ = round(16.0 / (math.exp(1.0 / TAU) - 1.0))
PRE = 16
USO_1MCPS = (254.2, 271.0, 192.8, 138.3, 97.8)      # k/s, RTL en la placa: formas 0..3 y marcados
DT_EJEMPLO = 40

# Una rampa de un solo tono: las formas están ordenadas, de la de menos ruido a la más
# corta. Validada con validate_palette.js --ordinal.
RAMPA = ("104281", "256abf", "5598e7", "86b6ef")
GRIS_MARCADO = "c9c9c5"

PLANTILLA = r"""%% %s. GENERADO por figuras_banco.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../../figuras/estilo_tikz.tex}
""" + "".join(rf"\definecolor{{f{i}}}{{HTML}}{{{c.upper()}}}" + "\n" for i, c in enumerate(RAMPA)) + \
    rf"\definecolor{{fm}}{{HTML}}{{{GRIS_MARCADO.upper()}}}" + r"""
\begin{document}
\begin{tikzpicture}[fondo]
%s
\end{tikzpicture}
\end{document}
"""


# ----------------------------------------------------------------- el modelo
def pulso(a, t0, n=N):
    f = r.forma_preamp(tau=TAU, tr10=TR10, n=n)
    x = np.zeros(n)
    x[t0:] = a * f[:n - t0]
    return np.round(x).astype(np.int64)


def configuracion():
    kw = mca_banco_config(MQ, pre_dly=PRE)
    disp = r.disparo_pz_para(r.forma_preamp(tau=TAU, tr10=TR10), MQ)
    disp.pop('pre_dly')
    return r.cfg(n_acc=4, baseline=0, **disp, **kw)


def forma_kw(cf, f):
    pref = 'trap_' if f == 0 else f'forma{f}_'
    return {n: int(cf[pref + n]) for n in ('k', 'm', 'off', 'lw', 'sh', 'antes', 'despues')}


def trapecio(x, q):
    return r.trapecio(x, q['k'], q['m'], MQ, q['sh'])


def ventana(t_trig, q):
    """Las muestras del trapecio que promedia la ranura abierta por ese disparo."""
    s0 = int(t_trig) - PRE - r.LAT_MCA
    return s0, s0 + q['off'], s0 + q['off'] + (1 << q['lw'])


# -------------------------------------------------------------------- dibujo
def curva(y, x0, y0, dx, esc, estilo):
    pts = " ".join(f"({x0 + i * dx:.3f},{y0 + v * esc:.3f})" for i, v in enumerate(y))
    return f"\\draw[{estilo}] plot coordinates {{{pts}}};"


def cota(xa, xb, y, texto, lado="above"):
    return (f"\\draw[<->, line width=0.5pt] ({xa:.3f},{y:.3f}) -- ({xb:.3f},{y:.3f}) "
            f"node[midway, {lado}, nodo, black] {{{texto}}};")


def anatomia(cf, ox, oy):
    """(a) Una forma, por dentro: la 16/12."""
    q = forma_kw(cf, 2)
    x = pulso(1000, T0)
    t = int(r.flancos_trig(x, cf)[0])
    T = trapecio(x, q)
    s0, a, b = ventana(t, q)
    gan = T[a:b].mean() / 1000.0
    y_t = T / gan
    desde, hasta = T0 - 10, T0 + 62
    dx, alto = 0.105, 2.45
    esc = alto / 1100.0
    X = lambda i: ox + (i - desde) * dx          # noqa: E731
    L = [f"\\node[titulo, anchor=west] at ({ox - 0.1:.3f},{oy + alto + 0.72:.3f}) "
         f"{{\\textbf{{a) Una forma por dentro}} \\quad {{\\scriptsize la 2: "
         f"{q['k']}/{q['m']}, ventana de {1 << q['lw']}}}}};"]
    k, m = q['k'], q['m']
    # La meseta, de fondo; la ventana encima
    L.append(f"\\fill[f3!25] ({X(T0 + k):.3f},{oy:.3f}) rectangle ({X(T0 + k + m):.3f},{oy + alto:.3f});")
    L.append(f"\\fill[verde, opacity=0.75] ({X(a):.3f},{oy:.3f}) rectangle ({X(b):.3f},{oy + alto * 0.95:.3f});")
    L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{oy:.3f}) -- ({X(hasta):.3f},{oy:.3f});")
    i0, i1 = desde, hasta + 1
    L.append(curva(x[i0:i1], X(i0), oy, dx, esc, "black!45, line width=0.7pt"))
    L.append(curva(y_t[i0:i1], X(i0), oy, dx, esc, "line width=1.1pt"))
    L.append(f"\\node[nodo, anchor=west, text=black!60] at ({X(T0 + 34):.3f},{oy + alto * 0.93:.3f}) "
             "{entrada: pulso con cola};")
    L.append(f"\\node[nodo, anchor=west] at ({X(T0 + 2 * k + m + 1):.3f},{oy + 0.45:.3f}) "
             "{salida: vuelve a cero};")
    # Las cotas
    h = oy + alto * 0.93 * 0.5
    L.append(cota(X(T0), X(T0 + k), h, "$k$: sube"))
    L.append(cota(X(T0 + k + m), X(T0 + 2 * k + m), h, "$k$: baja"))
    L.append(cota(X(T0 + k), X(T0 + k + m), oy + 0.28, "$m$: meseta"))
    L.append(cota(X(T0), X(T0 + 2 * k + m), oy - 0.32, f"dura $2k + m = {2 * k + m}$", "below"))
    L.append(f"\\node[nodo, anchor=south, text=verde!40!black] at ({(X(a) + X(b)) / 2:.3f},{oy + alto * 0.95:.3f}) "
             "{\\textbf{ventana}: \\texttt{F\\_TRAP}};")
    # La ranura: abre, dispara, off
    yr = oy - 0.98
    L.append(f"\\draw[black!45] ({X(s0):.3f},{oy:.3f}) -- ({X(s0):.3f},{yr:.3f});")
    L.append(f"\\draw[black!45] ({X(t):.3f},{oy:.3f}) -- ({X(t):.3f},{yr - 0.42:.3f});")
    L.append(f"\\draw[black!45] ({X(a):.3f},{oy:.3f}) -- ({X(a):.3f},{yr:.3f});")
    L.append(cota(X(s0), X(a), yr, f"off $= {q['off']}$", "below"))
    L.append(f"\\node[nodo, anchor=east] at ({X(s0) - 0.03:.3f},{yr:.3f}) {{abre la ranura}};")
    L.append(f"\\node[nodo, anchor=west] at ({X(t) + 0.03:.3f},{yr - 0.42:.3f}) {{\\texttt{{trig\\_i}}}};")
    return L, X(hasta)


def regla(cf, ox, oy):
    """(c) La regla: dónde gana cada forma."""
    esc = 0.03
    tope = 120
    Xp = lambda v: ox + min(v, tope) * esc        # noqa: E731
    Yn = lambda v: oy + min(v, tope) * esc        # noqa: E731
    L = [f"\\node[titulo, anchor=west] at ({ox - 0.75:.3f},{oy + tope * esc + 0.42:.3f}) "
         "{\\textbf{c) La regla} \\quad {\\scriptsize gana la primera que cumple}};"]
    L.append(f"\\fill[fm] ({Xp(0):.3f},{Yn(0):.3f}) rectangle ({Xp(tope):.3f},{Yn(tope):.3f});")
    formas = [forma_kw(cf, f) for f in range(4)]
    for f in (3, 2, 1, 0):
        q = formas[f]
        L.append(f"\\fill[f{f}] ({Xp(q['antes']):.3f},{Yn(q['despues']):.3f}) rectangle "
                 f"({Xp(tope):.3f},{Yn(tope):.3f});")
        L.append(f"\\draw[white, line width=1pt] ({Xp(q['antes']):.3f},{Yn(tope):.3f}) -- "
                 f"({Xp(q['antes']):.3f},{Yn(q['despues']):.3f}) -- ({Xp(tope):.3f},{Yn(q['despues']):.3f});")
    # Un rótulo en cada región
    for f, (vx, vy, txt) in enumerate(((108, 108, "0"), (73, 72, "1"), (37.5, 35, "2"), (20.5, 18.5, "3"))):
        col = "white" if f <= 1 else "black"
        L.append(f"\\node[font=\\scriptsize\\bfseries, text={col}] at ({Xp(vx):.3f},{Yn(vy):.3f}) {{{txt}}};")
    L.append(f"\\node[nodo] at ({Xp(7):.3f},{Yn(6):.3f}) {{m}};")
    # Los ejes: las marcas son los umbrales
    for q in formas:
        L.append(f"\\draw[black!45] ({Xp(q['antes']):.3f},{oy:.3f}) -- ++(0,-0.05) "
                 f"node[below, nodo, inner sep=1pt] {{{q['antes']}}};")
        L.append(f"\\draw[black!45] ({ox:.3f},{Yn(q['despues']):.3f}) -- ++(-0.05,0) "
                 f"node[left, nodo, inner sep=1pt] {{{q['despues']}}};")
    L.append(f"\\node[nodo, anchor=north] at ({Xp(tope / 2):.3f},{oy - 0.3:.3f}) "
             "{\\texttt{F\\_DTPREV}: al vecino de antes};")
    L.append(f"\\node[nodo, rotate=90, anchor=south] at ({ox - 0.42:.3f},{Yn(tope / 2):.3f}) "
             "{\\texttt{F\\_DTNEXT}: al de después};")
    # Los dos pulsos del ejemplo
    for (vx, vy, nombre, ancla) in ((tope - 3, DT_EJEMPLO, "A", "east"), (DT_EJEMPLO, tope - 3, "B", "north")):
        L.append(f"\\fill[white] ({Xp(vx):.3f},{Yn(vy):.3f}) circle (0.075);")
        L.append(f"\\fill[black] ({Xp(vx):.3f},{Yn(vy):.3f}) circle (0.05);")
    L.append(f"\\node[nodo, text=white, anchor=east] at ({Xp(tope - 5):.3f},{Yn(DT_EJEMPLO):.3f}) {{A}};")
    L.append(f"\\node[nodo, text=white, anchor=north] at ({Xp(DT_EJEMPLO):.3f},{Yn(tope - 5):.3f}) {{B}};")
    # La leyenda, con el uso medido
    lx, ly = ox + tope * esc + 0.25, oy + tope * esc
    total = sum(USO_1MCPS)
    L.append(f"\\node[nodo, anchor=north west, align=left] at ({lx - 0.05:.3f},{ly + 0.08:.3f}) "
             "{\\textbf{forma}\\quad uso a 1\\,Mcps};")
    for f in range(5):
        y_l = ly - 0.52 - f * 0.34
        col = f"f{f}" if f < 4 else "fm"
        L.append(f"\\fill[{col}] ({lx:.3f},{y_l - 0.1:.3f}) rectangle ({lx + 0.2:.3f},{y_l + 0.1:.3f});")
        if f < 4:
            q = formas[f]
            txt = f"{f}: {q['k']}/{q['m']}"
        else:
            txt = "m: marcado"
        L.append(f"\\node[nodo, anchor=west] at ({lx + 0.22:.3f},{y_l:.3f}) "
                 f"{{{txt}, {100 * USO_1MCPS[f] / total:.0f}\\,\\%}};")
    return L


def par(cf, ox, oy):
    """(b) El mismo par, con cada forma."""
    xa = pulso(1000, T0)
    xb = pulso(600, T0 + DT_EJEMPLO)
    xs = xa + xb
    m = r.medir(xs, cf)
    t_a = int(m['trig'][0])
    elegida = int(m['eventos']['feat'][0, r.F_FORMA])
    desde, hasta = T0 - 8, T0 + 190
    dx, alto, sep = 0.0535, 1.16, 0.34
    esc = alto / 1700.0
    X = lambda i: ox + (i - desde) * dx           # noqa: E731
    L = [f"\\node[titulo, anchor=west] at ({ox - 2.05:.3f},{oy + 0.72:.3f}) "
         f"{{\\textbf{{b) Un par a $\\Delta t = {DT_EJEMPLO}$: la ranura de A mide las cuatro y publica una}} "
         "\\quad {\\scriptsize \\texttt{F\\_DTNEXT} dice cuál}};"]
    y = oy
    for f in range(4):
        q = forma_kw(cf, f)
        Ta, Tb, Ts = trapecio(xa, q), trapecio(xb, q), trapecio(xs, q)
        _, a, b = ventana(t_a, q)
        gan = Ta[a:b].mean() / 1000.0
        err = 100 * (Ts[a:b].mean() / Ta[a:b].mean() - 1)
        y -= alto
        cumple = q['despues'] <= DT_EJEMPLO
        col = "verde" if cumple else "rojo"
        L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{y:.3f}) -- ({X(hasta):.3f},{y:.3f});")
        L.append(f"\\fill[{col}, opacity=0.75] ({X(a):.3f},{y:.3f}) rectangle ({X(b):.3f},{y + alto * 0.98:.3f});")
        i0, i1 = desde, hasta + 1
        L.append(curva(Ts[i0:i1] / gan, X(i0), y, dx, esc, "black!25, line width=2.2pt"))
        L.append(curva(Ta[i0:i1] / gan, X(i0), y, dx, esc, "line width=0.8pt"))
        L.append(curva(Tb[i0:i1] / gan, X(i0), y, dx, esc, "azul!85!black, line width=0.8pt, dashed"))
        L.append(f"\\node[anchor=east, font=\\scriptsize, align=right] at ({X(desde) - 0.08:.3f},{y + alto * 0.42:.3f}) "
                 f"{{forma {f}\\\\[-1pt]{{\\tiny {q['k']}/{q['m']}, ventana {1 << q['lw']}}}}};")
        if f == elegida:
            est = "\\textbf{la elegida}"
        elif cumple:
            est = "entra, pero promedia menos"
        else:
            est = "no: el vecino entra en la ventana"
        signo = "$\\leq$" if cumple else "$>$"
        L.append(f"\\node[nodo, anchor=west, align=left] at ({X(hasta) + 0.1:.3f},{y + alto * 0.42:.3f}) "
                 f"{{después $= {q['despues']}$ {signo} {DT_EJEMPLO}\\\\[-1pt]"
                 f"{est}\\\\[-1pt]error de A: {err:+.1f}\\,\\%}};")
        y -= sep
    # El eje de muestras y los pies
    y += sep
    for v in range(0, 181, 20):
        L.append(f"\\draw[black!45] ({X(T0 + v):.3f},{y:.3f}) -- ++(0,-0.05) node[below, nodo, inner sep=1pt] {{{v}}};")
    L.append(f"\\node[nodo, anchor=north] at ({(X(desde) + X(hasta)) / 2:.3f},{y - 0.3:.3f}) {{muestras desde el pie de A}};")
    for j, nom in ((0, "pie de A"), (DT_EJEMPLO, "pie de B")):
        L.insert(1, f"\\draw[black!15, line width=0.4pt] ({X(T0 + j):.3f},{oy + 0.05:.3f}) -- ({X(T0 + j):.3f},{y:.3f});")
        L.append(f"\\node[nodo, anchor=south] at ({X(T0 + j):.3f},{oy + 0.02:.3f}) {{{nom}}};")
    # La leyenda
    lx = X(T0 + 92)
    ly = oy + 0.16
    L.append(f"\\draw[black!25, line width=2.2pt] ({lx:.3f},{ly:.3f}) -- ++(0.42,0) "
             f"node[right, nodo, black] {{salida}};")
    L.append(f"\\draw[line width=0.8pt] ({lx + 1.35:.3f},{ly:.3f}) -- ++(0.42,0) node[right, nodo, black] {{A}};")
    L.append(f"\\draw[azul!85!black, line width=0.8pt, dashed] ({lx + 2.3:.3f},{ly:.3f}) -- ++(0.42,0) "
             f"node[right, nodo, black] {{B}};")
    return L, elegida


def figura():
    cf = configuracion()
    La, x_fin = anatomia(cf, 0.0, 0.0)
    Lc = regla(cf, x_fin + 1.25, -0.5)
    Lb, elegida = par(cf, 0.0, -2.95)
    assert elegida == 2, f'con dt = {DT_EJEMPLO} tenía que elegir la forma 2 y eligió {elegida}'
    return La + Lc + Lb


def escribir(nombre, lineas):
    tex = AQUI / f"{nombre}.tex"
    tex.write_text(PLANTILLA % (nombre, "\n".join(lineas)))
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                            f"-output-directory={tmp}", tex.name],
                           cwd=AQUI, capture_output=True, text=True)
        if p.returncode:
            sys.exit(p.stdout[-1500:])
        pdf = AQUI / f"{nombre}.pdf"
        shutil.copy(Path(tmp) / f"{nombre}.pdf", pdf)
    subprocess.run(["pdftocairo", "-svg", str(pdf), str(pdf.with_suffix(".svg"))], check=True)
    print(f"escrito {nombre}.tex, .pdf y .svg")


if __name__ == "__main__":
    escribir("banco_formas", figura())
