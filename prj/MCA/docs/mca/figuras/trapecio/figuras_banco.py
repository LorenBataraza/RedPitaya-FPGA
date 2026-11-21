#!/usr/bin/env python3
"""Las figuras del banco de trapecios.

- banco_formas_anatomia: qué son k, m y la ventana, en una forma.
- banco_formas_par: un par de pulsos medido con cada forma, y cuál se publica.
- banco_formas_regla: la regla que elige la forma, con el uso medido en la placa.
- banco_uso: cómo los disparos vecinos deciden la forma de cada pulso de un tren.
- banco_ranuras: cómo usa las ranuras el banco: un trapecio por forma para toda la
  señal, cada ranura suma una ventana de cada uno durante su compuerta, y queda
  ocupada hasta que se publica, use la forma que use.

Todo sale de monte-carlo/replica_mca2.py, el golden model que coincide con el RTL: el
trapecio de cada forma, el instante del disparo con polo-cero, dónde cae cada ventana,
la ranura que toma cada disparo y la forma que elige el publicador. Con pulsos sin
ruido, τ = 243 muestras y 1.6 muestras de subida, y el banco de `mca_banco_config`.

banco_formas_anatomia y banco_formas_regla son del banco de 4 formas que se midió en la
placa (antes del recorte del 2026-11-09). banco_formas_par, banco_uso, banco_ranuras y
banco_meseta_ranura son del de hoy: 3 ranuras y 3 formas.

Lo único medido en la placa es el uso de cada forma a 1 Mcps
(docs/mca/pruebas_banco_trapecios.md §6).

    python3 figuras_banco.py                   # todas
    python3 figuras_banco.py banco_ranuras     # sólo las nombradas
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
from API.mca import BANCO_PZ, BANCO_PZ_4, mca_banco_config    # noqa: E402
# La anatomía y la regla son del banco de 4 formas que se midió en la placa (anterior al
# recorte del 2026-11-09), con la barra de la placa al lado. El par, el uso, las ranuras y
# la meseta son del banco de hoy (BANCO_PZ: 3 formas) con las 3 ranuras de los tops.

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


def configuracion(formas=BANCO_PZ_4, n_acc=4):
    kw = mca_banco_config(MQ, pre_dly=PRE, formas=formas)
    disp = r.disparo_pz_para(r.forma_preamp(tau=TAU, tr10=TR10), MQ)
    disp.pop('pre_dly')
    return r.cfg(n_acc=n_acc, baseline=0, **disp, **kw)


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
         f"{{\\textbf{{Una forma por dentro}} \\quad {{\\scriptsize la 2: "
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
         "{\\textbf{La regla} \\quad {\\scriptsize gana la primera que cumple}};"]
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
    nf = int(cf['n_formas'])
    cuantas = {3: "las tres", 4: "las cuatro"}.get(nf, f"las {nf}")
    L = [f"\\node[titulo, anchor=west] at ({ox - 2.05:.3f},{oy + 0.72:.3f}) "
         f"{{\\textbf{{Un par a $\\Delta t = {DT_EJEMPLO}$: la ranura de A mide {cuantas} y publica una}} "
         "\\quad {\\scriptsize \\texttt{F\\_DTNEXT} dice cuál}};"]
    y = oy
    for f in range(nf):
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


# ------------------------------------------------- la figura del uso (banco_uso)
# Un tren de seis pulsos que pasa por las tres formas y por el marcado, con 3 ranuras:
# P1 solo (64/48), P2 con un vecino a 60 (32/24), P3 y P4 cerca (8/8), y P5 y P6 a 10
# muestras (marcados). El hueco de 140 antes de P5 deja libres las tres ranuras: con
# menos, P6 no encuentra ranura libre.
GAPS_EJ = (150, 60, 30, 140, 10)
NUMEROS = {5: "cinco", 6: "seis", 7: "siete", 8: "ocho"}
AMPS_EJ = (1000, 700, 900, 600, 800, 500)


def tren_ejemplo(cf):
    pies = np.concatenate([[120], 120 + np.cumsum(GAPS_EJ)]).astype(int)
    n = int(pies[-1]) + 300
    x = sum(pulso(a, int(p), n) for a, p in zip(AMPS_EJ, pies))
    m = r.medir(x, cf)
    assert len(m['trig']) == len(pies) and (m['estado'] == r.ABRE).all(), m['estado']
    assert len(m['eventos']['feat']) == len(pies)
    return x, m


def vecinos(cf, ox, oy):
    """El tren de ejemplo: cada pulso, las formas del banco y los disparos vecinos."""
    x, m = tren_ejemplo(cf)
    trig, ev = m['trig'], m['eventos']['feat']
    nf = int(cf['n_formas'])
    formas = [forma_kw(cf, f) for f in range(nf)]
    col = [COLOR_K[q['k']] for q in formas]       # el color sigue a la forma
    desde = int(trig[0]) - formas[0]['antes'] - 12
    hasta = int(trig[-1]) + formas[0]['despues'] + 12
    dx = 13.5 / (hasta - desde)
    X = lambda i: ox + (i - desde) * dx           # noqa: E731
    L = [f"\\node[titulo, anchor=west] at ({ox - 0.75:.3f},{oy + 0.87:.3f}) "
         f"{{\\textbf{{Un tren de {NUMEROS.get(len(trig), len(trig))} pulsos: cada uno mira dónde caen "
         "los disparos vecinos}};"]
    # La leyenda: los tres estados de una barra, cada uno a continuación del anterior,
    # y abajo qué abarca una barra
    ly = oy + 0.37
    L.append(f"\\coordinate (c0) at ({ox:.3f},{ly:.3f});")
    L.append("\\fill[f1] ([yshift=-0.05cm]c0) rectangle ++(0.4,0.1);")
    L.append("\\node[nodo, anchor=west] (l0) at ([xshift=0.45cm]c0) "
             "{la elegida: la de más arriba sin otro disparo adentro};")
    L.append("\\path (l0.east) ++(0.4,0) coordinate (c1);")
    L.append("\\fill[f1, opacity=0.2] ([yshift=-0.05cm]c1) rectangle ++(0.4,0.1);")
    L.append("\\draw[rojo!70!black, line width=0.7pt] ([xshift=0.15cm, yshift=-0.07cm]c1) -- ++(0.1,0.14) "
             "([xshift=0.15cm, yshift=0.07cm]c1) -- ++(0.1,-0.14);")
    L.append("\\node[nodo, anchor=west] (l1) at ([xshift=0.45cm]c1) {un vecino adentro ($\\times$): no sirve};")
    L.append("\\path (l1.east) ++(0.4,0) coordinate (c2);")
    L.append("\\draw[f1, line width=0.6pt] ([yshift=-0.05cm]c2) rectangle ++(0.4,0.1);")
    L.append("\\node[nodo, anchor=west] (l2) at ([xshift=0.45cm]c2) {entra, pero promedia menos};")
    L.append(f"\\node[nodo, anchor=west] at ({ox - 0.03:.3f},{ly - 0.25:.3f}) "
             "{cada barra: de $t - $antes a $t + $después};")
    # La señal, con los disparos
    s_alto, s_top = 1.1, oy - 0.2
    s_bot = s_top - s_alto
    esc = s_alto / float(x[desde:hasta + 1].max())
    L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{s_bot:.3f}) -- ({X(hasta):.3f},{s_bot:.3f});")
    L.append(curva(x[desde:hasta + 1], X(desde), s_bot, dx, esc, "black!55, line width=0.7pt"))
    L.append(f"\\node[nodo, anchor=east, align=right] at ({X(desde) - 0.1:.3f},{s_bot + 0.5 * s_alto:.3f}) "
             "{entrada\\\\[-1pt]y disparos};")
    for j, t in enumerate(trig):
        cerca_sig = j + 1 < len(trig) and trig[j + 1] - t < 25
        cerca_ant = j > 0 and t - trig[j - 1] < 25
        ancla = "south east" if cerca_sig else ("south west" if cerca_ant else "south")
        L.append(f"\\node[nodo, anchor={ancla}, text=black] at ({X(t):.3f},{s_top + 0.02:.3f}) {{P{j + 1}}};")
    # Las ranuras: una fila de barras por pulso, una por forma
    paso_b, alto_b, paso_f = 0.15, 0.1, 0.8
    y0 = s_bot - 0.3
    y_fin = y0 - (len(trig) - 1) * paso_f - (nf - 1) * paso_b - alto_b
    for t in trig:
        L.insert(1, f"\\draw[black!15, line width=0.4pt] ({X(t):.3f},{s_top:.3f}) -- ({X(t):.3f},{y_fin:.3f});")
    for i, t in enumerate(trig):
        dtp, dtn, fe = int(ev[i, r.F_DTPREV]), int(ev[i, r.F_DTNEXT]), int(ev[i, r.F_FORMA])
        if i:
            assert dtp == trig[i] - trig[i - 1], (i, dtp)
        sirve = [q['antes'] <= dtp and q['despues'] <= dtn for q in formas]
        assert fe == next((f for f in range(nf) if sirve[f]), r.MARCADO), (i, fe, sirve)
        yb = y0 - i * paso_f
        for f, q in enumerate(formas):
            y = yb - f * paso_b
            a, b = X(t - q['antes']), X(t + q['despues'])
            if f == fe:
                L.append(f"\\fill[{col[f]}] ({a:.3f},{y - alto_b:.3f}) rectangle ({b:.3f},{y:.3f});")
            elif fe == r.MARCADO or f < fe:
                L.append(f"\\fill[{col[f]}, opacity=0.2] ({a:.3f},{y - alto_b:.3f}) rectangle ({b:.3f},{y:.3f});")
                for v in ((t - dtp) if q['antes'] > dtp else None, (t + dtn) if q['despues'] > dtn else None):
                    if v is not None:
                        L.append(f"\\draw[rojo!70!black, line width=0.7pt] ({X(v) - 0.05:.3f},{y - alto_b - 0.02:.3f}) "
                                 f"-- ++(0.1,{alto_b + 0.04:.3f}) ({X(v) - 0.05:.3f},{y + 0.02:.3f}) "
                                 f"-- ++(0.1,{-alto_b - 0.04:.3f});")
            else:
                L.append(f"\\draw[{col[f]}, line width=0.6pt] ({a:.3f},{y - alto_b:.3f}) rectangle ({b:.3f},{y:.3f});")
        y_med = yb - (nf - 1) / 2 * paso_b - alto_b / 2
        L.append(f"\\draw[black, line width=0.9pt] ({X(t):.3f},{yb + 0.05:.3f}) -- ({X(t):.3f},{yb - (nf - 1) * paso_b - alto_b - 0.05:.3f});")
        L.append(f"\\node[font=\\scriptsize, anchor=east] at ({X(desde) - 0.1:.3f},{y_med:.3f}) {{P{i + 1}}};")
    # Las formas, al lado de la primera fila; la escala, abajo
    for f, q in enumerate(formas):
        y = y0 - f * paso_b - alto_b / 2
        L.append(f"\\node[nodo, anchor=east, text=black!60] at ({X(trig[0] - q['antes']) - 0.06:.3f},{y:.3f}) "
                 f"{{{q['k']}/{q['m']}}};")
    L.append(f"\\draw[|-|, line width=0.5pt] ({X(desde):.3f},{y_fin - 0.25:.3f}) -- ++({100 * dx:.3f},0) "
             f"node[midway, below, nodo] {{100 muestras = 0.8\\,$\\mu$s}};")
    return L, y_fin - 0.25


def figura_uso():
    cf = configuracion(BANCO_PZ, n_acc=3)
    return vecinos(cf, 0.0, 0.0)[0]


# ------------------------------------------- las ranuras y el banco (banco_ranuras)
# Un tren que pasa por todo lo que le puede pasar a un pulso con 3 ranuras y 3 formas:
# P1 solo (64/48), P2 con un vecino a 60 (32/24), P3 y P4 cerca (8/8), P5 sin ranura
# libre (las tres ocupadas), y P6 y P7 a 10 muestras (marcados, pero con ranura). P1 y
# P2 están a 140: P2 encuentra libre la ranura 0, que P1 ya publicó.
GAPS_RAN = (140, 60, 30, 25, 80, 10)
AMPS_RAN = (1000, 700, 900, 600, 800, 500, 700)
COLOR_K = {64: "f0", 32: "f1", 16: "f2", 8: "f3"}    # el color sigue a la forma, no al índice
ESPERADO_RAN = ((0, 0), (0, 1), (1, 2), (2, 2), (None, None), (0, r.MARCADO), (1, r.MARCADO))


def ranuras(cf, ox, oy):
    """El tren, los tres trapecios del banco y lo que hace cada ranura con ellos."""
    pies = np.concatenate([[60], 60 + np.cumsum(GAPS_RAN)]).astype(int)
    n = int(pies[-1]) + 400
    x = sum(pulso(a, int(p), n) for a, p in zip(AMPS_RAN, pies))
    m = r.medir(x, cf)
    trig, estado, ev = m['trig'], m['estado'], m['ev']
    assert len(trig) == len(pies), trig
    formas = [forma_kw(cf, f) for f in range(int(cf['n_formas']))]
    nf, nh, g_l = len(formas), int(cf['n_acc']), int(cf['gate_long'])
    D = PRE + r.LAT_MCA                     # la ranura del ciclo t ve la muestra t - D

    # Por disparo: la ranura, la forma, y los tramos abierta / cerrada en muestras
    fila = {}
    for j, i in enumerate(ev['i']):
        t = int(trig[i])
        s0 = t - D
        assert s0 == int(ev['s0'][j])
        cierre = t + g_l + 1                 # C: procesa la muestra g_l y cierra
        libre = int(ev['emite'][j]) + 1      # el publicador terminó con ella
        fila[i] = dict(s0=s0, ranura=int(ev['ranura'][j]), forma=int(ev['forma'][j]),
                       cierra=cierre - D, libre=libre - D)
    for i, (ran, fe) in enumerate(ESPERADO_RAN):
        if ran is None:
            assert estado[i] != r.ABRE and i not in fila, (i, estado[i])
        else:
            assert fila[i]['ranura'] == ran and fila[i]['forma'] == fe, (i, fila[i])

    desde = int(trig[0]) - D - 25
    hasta = max(v['libre'] for v in fila.values()) + 15
    ancho = 15.6
    dx = ancho / (hasta - desde)
    X = lambda i: ox + (i - desde) * dx           # noqa: E731
    L = [f"\\node[titulo, anchor=west] at ({ox - 1.55:.3f},{oy + 0.62:.3f}) "
         "{\\textbf{Cómo usa las ranuras el banco} \\quad {\\scriptsize un trapecio por forma "
         "para toda la señal; cada ranura suma una ventana de cada uno y publica una}};"]

    # La leyenda
    ly, lx = oy + 0.12, ox
    for f, q in enumerate(formas):
        L.append(f"\\fill[{COLOR_K[q['k']]}] ({lx:.3f},{ly - 0.06:.3f}) rectangle ++(0.3,0.12);")
        L.append(f"\\node[nodo, anchor=west] at ({lx + 0.33:.3f},{ly:.3f}) {{{q['k']}/{q['m']}}};")
        lx += 1.25
    lx += 0.2
    L.append(f"\\fill[f1!22] ({lx:.3f},{ly - 0.06:.3f}) rectangle ++(0.3,0.12);")
    L.append(f"\\node[nodo, anchor=west] at ({lx + 0.33:.3f},{ly:.3f}) "
             "{ventana sumada, no publicada};")
    lx += 3.9
    L.append(f"\\filldraw[fill=black!5, draw=black!45, line width=0.4pt] ({lx:.3f},{ly - 0.08:.3f}) "
             "rectangle ++(0.5,0.16);")
    L.append(f"\\node[nodo, anchor=west] at ({lx + 0.55:.3f},{ly:.3f}) "
             f"{{abierta: la compuerta, {g_l} muestras}};")
    lx += 4.15
    L.append(f"\\fill[black!45] ({lx:.3f},{ly - 0.08:.3f}) rectangle ++(0.5,0.16);")
    L.append(f"\\node[nodo, anchor=west] at ({lx + 0.55:.3f},{ly:.3f}) "
             f"{{cerrada: espera y publica ({r.SERV} ciclos)}};")

    rot = lambda y, txt: L.append(                # noqa: E731
        f"\\node[font=\\scriptsize, anchor=east, align=right] at ({ox - 0.12:.3f},{y:.3f}) {{{txt}}};")

    # 1. La entrada, con los disparos
    s_alto, s_top = 0.95, oy - 0.25
    s_bot = s_top - s_alto
    esc = s_alto / float(x[desde:hasta + 1].max())
    L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{s_bot:.3f}) -- ({X(hasta):.3f},{s_bot:.3f});")
    L.append(curva(x[desde:hasta + 1], X(desde), s_bot, dx, esc, "black!60, line width=0.7pt"))
    rot(s_bot + s_alto / 2, "entrada")
    for i, p in enumerate(pies):
        cerca = i + 1 < len(pies) and pies[i + 1] - p < 30
        ancla = "south east" if cerca else "south"
        L.append(f"\\node[nodo, anchor={ancla}, text=black] at ({X(int(trig[i]) - D):.3f},{s_top + 0.02:.3f}) "
                 f"{{P{i + 1}}};")

    # 2. Los trapecios del banco, uno por forma, con las ventanas que leen las ranuras
    t_alto, t_paso = 0.5, 0.62
    y_t0 = s_bot - 0.3
    # Cada trapecio, en unidades de amplitud: su ganancia con un pulso de 1000 solo
    xg = pulso(1000, 50, 400)
    tg = int(r.flancos_trig(xg, cf)[0])
    T = []
    for q in formas:
        _, a, b = ventana(tg, q)
        T.append(trapecio(x, q) / (trapecio(xg, q)[a:b].mean() / 1000.0))
    esc_t = t_alto / max(float(Tf[desde:hasta + 1].max()) for Tf in T)
    for f, q in enumerate(formas):
        yb = y_t0 - f * t_paso - t_alto
        col = COLOR_K[q['k']]
        for i, v in fila.items():
            a = v['s0'] + q['off']
            b = a + (1 << q['lw'])
            tono = col if v['forma'] == f else f"{col}!22"
            L.append(f"\\fill[{tono}] ({X(a):.3f},{yb:.3f}) rectangle ({X(b):.3f},{yb + t_alto:.3f});")
        L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{yb:.3f}) -- ({X(hasta):.3f},{yb:.3f});")
        L.append(curva(T[f][desde:hasta + 1], X(desde), yb, dx, esc_t, "line width=0.8pt"))
        rot(yb + t_alto / 2, f"trapecio {q['k']}/{q['m']}")
    y_r0 = y_t0 - (nf - 1) * t_paso - t_alto - 0.45

    # 3. Las ranuras: la compuerta abierta, con una franja por forma, y la espera cerrada
    r_alto, r_paso = 0.5, 0.78
    sub = r_alto / nf
    for k in range(nh):
        yb = y_r0 - k * r_paso - r_alto
        rot(yb + r_alto / 2, f"ranura {k}")
        L.append(f"\\draw[black!25, line width=0.4pt] ({X(desde):.3f},{yb:.3f}) -- ({X(hasta):.3f},{yb:.3f});")
        for i, v in sorted(fila.items()):
            if v['ranura'] != k:
                continue
            a, c, e = v['s0'], v['cierra'], v['libre']
            L.append(f"\\filldraw[fill=black!5, draw=black!45, line width=0.4pt] ({X(a):.3f},{yb:.3f}) "
                     f"rectangle ({X(c):.3f},{yb + r_alto:.3f});")
            L.append(f"\\fill[black!45] ({X(c):.3f},{yb:.3f}) rectangle ({X(e):.3f},{yb + r_alto:.3f});")
            for f, q in enumerate(formas):
                wa = a + q['off']
                wb = wa + (1 << q['lw'])
                y1 = yb + r_alto - f * sub
                tono = COLOR_K[q['k']] + ("" if v['forma'] == f else "!22")
                L.append(f"\\fill[{tono}] ({X(wa):.3f},{y1 - sub:.3f}) "
                         f"rectangle ({X(wb):.3f},{y1:.3f});")
            if v['forma'] == r.MARCADO:
                res = "marcado"
            else:
                res = f"{formas[v['forma']]['k']}/{formas[v['forma']]['m']}"
            L.append(f"\\node[nodo, anchor=south west, text=black] at ({X(a):.3f},{yb + r_alto:.3f}) "
                     f"{{P{i + 1} $\\to$ {res}}};")
    y_fin_r = y_r0 - (nh - 1) * r_paso - r_alto

    # 4. Los que no encontraron ranura
    y_p = y_fin_r - 0.32
    rot(y_p, "sin ranura")
    for i in range(len(trig)):
        if estado[i] == r.ABRE:
            continue
        xp = X(int(trig[i]) - D)
        L.append(f"\\draw[rojo!70!black, line width=0.9pt] ({xp - 0.07:.3f},{y_p - 0.07:.3f}) -- ++(0.14,0.14) "
                 f"({xp - 0.07:.3f},{y_p + 0.07:.3f}) -- ++(0.14,-0.14);")
        L.append(f"\\node[nodo, anchor=west, text=rojo!60!black] at ({xp + 0.1:.3f},{y_p:.3f}) "
                 f"{{P{i + 1}: las {nh} ranuras ocupadas, se pierde}};")

    # 5. Cuántas ranuras hay ocupadas, muestra a muestra
    o_alto = 0.75
    y_o = y_p - 0.35 - o_alto
    occ = np.zeros(hasta - desde + 2, np.int64)
    for v in fila.values():
        occ[v['s0'] + 1 - desde] += 1
        occ[v['libre'] - desde] -= 1
    occ = np.cumsum(occ)[:hasta - desde + 1]
    esc_o = o_alto / nh
    for lv in range(1, nh + 1):
        L.append(f"\\draw[black!12, line width=0.4pt] ({X(desde):.3f},{y_o + lv * esc_o:.3f}) -- "
                 f"({X(hasta):.3f},{y_o + lv * esc_o:.3f});")
        L.append(f"\\node[nodo, anchor=west, inner sep=1pt] at ({X(hasta) + 0.03:.3f},{y_o + lv * esc_o:.3f}) {{{lv}}};")
    pts = []
    for j, v in enumerate(occ):
        if j == 0 or v != occ[j - 1]:
            if j:
                pts.append((X(desde + j), y_o + occ[j - 1] * esc_o))
            pts.append((X(desde + j), y_o + v * esc_o))
    pts.append((X(hasta), y_o + occ[-1] * esc_o))
    L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{y_o:.3f}) -- ({X(hasta):.3f},{y_o:.3f});")
    L.append("\\draw[line width=0.9pt] " + " -- ".join(f"({a:.3f},{b:.3f})" for a, b in pts) + ";")
    rot(y_o + o_alto / 2, "ranuras\\\\[-1pt]ocupadas")

    # Las líneas de los disparos, de arriba abajo, detrás de todo
    for i in range(len(trig)):
        xp = X(int(trig[i]) - D)
        L.insert(1, f"\\draw[black!15, line width=0.4pt] ({xp:.3f},{s_top:.3f}) -- ({xp:.3f},{y_o:.3f});")
    L.append(f"\\draw[|-|, line width=0.5pt] ({X(desde):.3f},{y_o - 0.3:.3f}) -- ++({100 * dx:.3f},0) "
             f"node[midway, below, nodo] {{100 muestras = 0.8\\,$\\mu$s}};")
    return L


# --------------------------------------- la meseta de una ranura (banco_meseta_ranura)
# Un par a 60 muestras con el banco de hoy (3 formas): la 64/48 no alcanza (su
# después es 96), la 32/24 sí, y la 8/8 también pero promedia menos.
DT_RANURA = 60


def meseta_ranura(cf, ox, oy):
    """La ranura de A suma las tres ventanas a la vez y elige la forma al cerrar."""
    xa = pulso(1000, T0)
    xb = pulso(600, T0 + DT_RANURA)
    xs = xa + xb
    m = r.medir(xs, cf)
    t_a = int(m['trig'][0])
    feat = m['eventos']['feat']
    elegida, dtn = int(feat[0, r.F_FORMA]), int(feat[0, r.F_DTNEXT])
    assert dtn == DT_RANURA, dtn
    formas = [forma_kw(cf, f) for f in range(int(cf['n_formas']))]
    D = PRE + r.LAT_MCA                      # la ranura del ciclo t ve la muestra t - D
    s0 = t_a - D                             # la muestra con que abre la ranura de A
    cierre = s0 + int(cf['gate_long'])
    desde, hasta = s0 - 6, s0 + 178
    dx, alto, sep = 0.064, 0.98, 0.30
    X = lambda i: ox + (i - s0) * dx          # noqa: E731
    L = [f"\\node[titulo, anchor=west] at ({X(desde) - 1.75:.3f},{oy + 0.95:.3f}) "
         "{\\textbf{Una ranura suma las tres mesetas y elige al cerrar}};"]

    # La entrada, con los dos disparos vistos desde la ranura de A
    y = oy - alto
    esc_x = alto / 1500.0
    L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{y:.3f}) -- ({X(hasta):.3f},{y:.3f});")
    i0, i1 = desde, hasta + 1
    L.append(curva(xs[i0:i1], X(i0), y, dx, esc_x, "line width=0.8pt"))
    L.append(f"\\node[anchor=east, font=\\scriptsize] at ({X(desde) - 0.08:.3f},{y + alto * 0.42:.3f}) {{entrada}};")
    marcas = ((s0, "disparo de A: abre"), (s0 + dtn, f"disparo de B: \\texttt{{F\\_DTNEXT}} = {dtn}"))
    for xm, txt in marcas:
        L.append(f"\\draw[-{{Stealth[length=1.6mm]}}, amarillo!35!black, line width=0.9pt] "
                 f"({X(xm):.3f},{oy + 0.32:.3f}) -- ({X(xm):.3f},{y + alto * 0.98:.3f});")
        L.append(f"\\node[nodo, anchor=south west, black] at ({X(xm) - 0.05:.3f},{oy + 0.3:.3f}) {{{txt}}};")

    # Una fila por forma: la salida común del trapecio y la ventana que suma la ranura
    for f, q in enumerate(formas):
        Ta, Tb, Ts = trapecio(xa, q), trapecio(xb, q), trapecio(xs, q)
        _, a, b = ventana(t_a, q)
        gan = Ta[a:b].mean() / 1000.0
        y -= alto + sep
        esc = alto / 1700.0
        col = COLOR_K[q['k']]
        L.append(f"\\draw[black!40, line width=0.4pt] ({X(desde):.3f},{y:.3f}) -- ({X(hasta):.3f},{y:.3f});")
        L.append(f"\\fill[{col}, opacity=0.5] ({X(a):.3f},{y:.3f}) rectangle ({X(b):.3f},{y + alto * 0.98:.3f});")
        L.append(curva(Ts[i0:i1] / gan, X(i0), y, dx, esc, "black!25, line width=2.2pt"))
        L.append(curva(Ta[i0:i1] / gan, X(i0), y, dx, esc, "line width=0.8pt"))
        L.append(curva(Tb[i0:i1] / gan, X(i0), y, dx, esc, "azul!85!black, line width=0.8pt, dashed"))
        L.append(f"\\node[anchor=east, font=\\scriptsize, align=right] at ({X(desde) - 0.08:.3f},{y + alto * 0.42:.3f}) "
                 f"{{forma {f}\\\\[-1pt]{{\\tiny {q['k']}/{q['m']}}}}};")
        L.append(f"\\node[nodo, anchor=west, black] at ({X(b) + 0.03:.3f},{y + alto * 0.8:.3f}) {{$S_{f}$}};")
        cumple = q['despues'] <= dtn
        signo = "\\leq" if cumple else ">"
        if f == elegida:
            est = "\\textbf{publicada}"
        elif cumple:
            est = "cumple, promedia menos"
        else:
            est = "no cumple"
        L.append(f"\\node[nodo, anchor=west, align=left, black] at ({X(hasta) + 0.12:.3f},{y + alto * 0.42:.3f}) "
                 f"{{después$_{f} = {q['despues']} {signo} {dtn}$\\\\[-1pt]{est}}};")

    # La compuerta y el cierre, donde se elige
    y_top = oy + 0.05
    L.insert(1, f"\\draw[black!55, line width=0.6pt, dashed] ({X(cierre):.3f},{y_top + 0.62:.3f}) -- ({X(cierre):.3f},{y:.3f});")
    L.insert(1, f"\\draw[black!15, line width=0.4pt] ({X(s0):.3f},{y_top:.3f}) -- ({X(s0):.3f},{y:.3f});")
    L.append(f"\\node[nodo, anchor=south west, black] at ({X(cierre) + 0.04:.3f},{oy + 0.3:.3f}) "
             "{cierre: se elige la forma};")

    # El eje, en muestras desde la apertura
    for v in range(0, 171, 20):
        L.append(f"\\draw[black!45] ({X(s0 + v):.3f},{y:.3f}) -- ++(0,-0.05) node[below, nodo, inner sep=1pt] {{{v}}};")
    L.append(f"\\node[nodo, anchor=north] at ({(X(desde) + X(hasta)) / 2:.3f},{y - 0.3:.3f}) "
             "{muestras desde la apertura de la ranura de A};")

    # La leyenda
    lx, ly = X(s0 + 118), oy + 0.85
    L.append(f"\\draw[black!25, line width=2.2pt] ({lx:.3f},{ly:.3f}) -- ++(0.42,0) node[right, nodo, black] {{salida}};")
    L.append(f"\\draw[line width=0.8pt] ({lx + 1.35:.3f},{ly:.3f}) -- ++(0.42,0) node[right, nodo, black] {{A}};")
    L.append(f"\\draw[azul!85!black, line width=0.8pt, dashed] ({lx + 2.3:.3f},{ly:.3f}) -- ++(0.42,0) "
             "node[right, nodo, black] {B};")
    return L, elegida


def figura_meseta_ranura():
    L, elegida = meseta_ranura(configuracion(BANCO_PZ, n_acc=3), 0.0, 0.0)
    assert elegida == 1, f'con dt = {DT_RANURA} tenía que elegir la forma 1 y eligió {elegida}'
    return L


def figura_anatomia():
    L, _ = anatomia(configuracion(), 0.0, 0.0)
    return L


def figura_par():
    L, elegida = par(configuracion(BANCO_PZ, n_acc=3), 0.0, 0.0)
    assert elegida == 2, f'con dt = {DT_EJEMPLO} tenía que elegir la forma 2 y eligió {elegida}'
    return L


def figura_regla():
    return regla(configuracion(), 0.0, 0.0)


def figura_ranuras():
    return ranuras(configuracion(BANCO_PZ, n_acc=3), 0.0, 0.0)


FIGURAS = {
    "banco_formas_anatomia": figura_anatomia,
    "banco_formas_par": figura_par,
    "banco_formas_regla": figura_regla,
    "banco_uso": figura_uso,
    "banco_ranuras": figura_ranuras,
    "banco_meseta_ranura": figura_meseta_ranura,
}


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
    nombres = sys.argv[1:] or list(FIGURAS)
    malas = set(nombres) - set(FIGURAS)
    if malas:
        sys.exit(f"no conozco {sorted(malas)}; hay {list(FIGURAS)}")
    for nombre in nombres:
        escribir(nombre, FIGURAS[nombre]())
