#!/usr/bin/env python3
"""Una rafaga por el event_ring, a escala: escribe ../ring_tiempos.tex.

Sale de eventos_rafaga.txt, la traza de tb_ring_medir.sv: los cambios de estado reales
del RTL, nada dibujado a mano. Ventana 8 + 24, slot de 512 B, AXI ideal, con creditos.

    python3 figura_tiempos.py
    cd .. && pdflatex ring_tiempos.tex && pdftocairo -svg ring_tiempos.pdf ring_tiempos.svg
"""
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SX = 0.0135                      # cm por ciclo
FILA = dict(trig=0.0, cap=-1.25, stg=-2.85, wrt=-4.3, com=-5.2)
W_HDR, W_DATA, W_PAD, W_FOOT, W_DONE, W_IDLE = 1, 2, 3, 4, 5, 0


def leer():
    ev = []
    for lin in (AQUI / 'eventos_rafaga.txt').read_text().splitlines():
        p = lin.split()
        ev.append((int(p[0]), p[1], int(p[2]) if len(p) > 2 else None))
    return ev


def main():
    ev = leer()
    t0 = ev[0][0]
    fin = ev[-1][0] - t0
    x = lambda t: (t - t0) * SX

    trig = [t for t, k, _ in ev if k == 'trig']
    busy = [t for t, k, _ in ev if k == 'busy']
    full = [t for t, k, _ in ev if k == 'full']

    # a que trigger corresponde cada perdida: el ultimo que llego antes del pulso
    def de(tp):
        return max(t for t in trig if t <= tp)
    t_busy, t_full = {de(t) for t in busy}, {de(t) for t in full}

    drenajes, ini = [], None
    for t, k, v in ev:
        if k == 'cap' and v == 1:
            ini = t
        elif k == 'cap' and v == 2:
            drenajes.append((ini, t))

    slots, tramo, est = [], [], None
    t_est = None
    for t, k, v in ev:
        if k != 'wrt':
            continue
        if est not in (None, W_IDLE):
            tramo.append((est, t_est, t))
        est, t_est = v, t
        if v == W_IDLE:
            slots.append(tramo)
            tramo = []

    niveles, nivel, t_niv = [], 0, t0
    for t, k, v in ev:
        if k == 'lvl':
            niveles.append((t_niv, t, nivel))
            nivel, t_niv = v, t
    niveles.append((t_niv, ev[-1][0], nivel))
    commits = [(t, v) for t, k, v in ev if k == 'wr_slot']

    per_cap = drenajes[0][1] - drenajes[0][0] + 1
    per_wrt = commits[1][0] - commits[0][0]

    o = [r"""% ring_tiempos. GENERADO por tiempos/figura_tiempos.py: no editar a mano.
\documentclass[border=0pt,tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[none]{hyphenat}
\input{../../figuras/estilo_tikz.tex}
\begin{document}
\begin{tikzpicture}[fondo]
\tikzset{fila/.style={anchor=east, font=\scriptsize, align=right, inner sep=2pt},
         nota/.style={font=\scriptsize, black!75, align=left, inner sep=1pt},
         perdida/.style={font=\scriptsize\ttfamily\bfseries, text=rojo!60!black, inner sep=1pt},
         seqn/.style={font=\fontsize{5.6}{6.6}\selectfont\ttfamily, inner sep=0pt}}
"""]
    # rotulos de las filas
    o.append(rf"\node[fila] at (-0.25,{FILA['trig'] + 0.25}) {{\texttt{{trig\_i}}}};")
    o.append(rf"\node[fila] at (-0.25,{FILA['cap'] + 0.2}) {{\texttt{{event\_window\_capture}}\\ ventana}};")
    o.append(rf"\node[fila] at (-0.25,{FILA['stg'] + 0.3}) {{\texttt{{event\_stage\_fifo}}\\ eventos completos}};")
    o.append(rf"\node[fila] at (-0.25,{FILA['wrt'] + 0.2}) {{\texttt{{event\_slot\_writer}}\\ slot}};")
    o.append(rf"\node[fila] at (-0.25,{FILA['com'] + 0.14}) {{\texttt{{wr\_slot}}}};")

    # guias verticales desde cada trigger
    for t in trig:
        col = 'rojo!60!black' if t in t_busy | t_full else 'black!55'
        o.append(rf"\draw[{col}, line width=0.35pt, densely dotted] ({x(t):.3f},{FILA['trig']:.2f}) -- ({x(t):.3f},{FILA['stg']:.2f});")

    # triggers
    for i, t in enumerate(trig):
        perdido = t in t_busy | t_full
        col = 'rojo!60!black' if perdido else 'black'
        o.append(rf"\draw[->, {col}, line width=0.9pt] ({x(t):.3f},{FILA['trig'] + 0.5:.2f}) -- ({x(t):.3f},{FILA['trig']:.2f});")
    t1 = sorted(t_busy)[0]
    o.append(rf"\node[perdida, anchor=south] at ({x(t1):.3f},{FILA['trig'] + 0.52:.2f}) {{drop\_busy}};")
    for t in sorted(t_full):
        o.append(rf"\node[perdida, anchor=south] at ({x(t):.3f},{FILA['trig'] + 0.52:.2f}) {{drop\_full}};")
    o.append(rf"\node[nota, anchor=west] at ({x(trig[-1]) + 0.35:.3f},{FILA['trig'] + 0.25:.2f}) {{un trigger cada {trig[3] - trig[2]} ciclos: la captura\\ da abasto, el writer no}};")

    # captura
    for i, (a, b) in enumerate(drenajes):
        o.append(rf"\draw[fill=verde!55, line width=0.5pt] ({x(a):.3f},{FILA['cap']:.2f}) rectangle ({x(b):.3f},{FILA['cap'] + 0.42:.2f});")
        o.append(rf"\node[seqn] at ({(x(a) + x(b)) / 2:.3f},{FILA['cap'] + 0.21:.2f}) {{seq {i}}};")
    a, b = drenajes[0]
    o.append(rf"\draw[<->, line width=0.45pt] ({x(a):.3f},{FILA['cap'] - 0.14:.2f}) -- ({x(b):.3f},{FILA['cap'] - 0.14:.2f}) node[midway, below, font=\scriptsize, inner sep=1.5pt] {{{per_cap} ciclos}};")

    # stage: nivel en escalones
    alto = 0.17
    base = FILA['stg']
    pts = []
    for a, b, n in niveles:
        pts += [(x(a), base + n * alto), (x(b), base + n * alto)]
    cam = ' -- '.join(f'({p:.3f},{q:.3f})' for p, q in pts)
    o.append(rf"\fill[verde!20] ({x(t0):.3f},{base:.3f}) -- {cam} -- ({x(ev[-1][0]):.3f},{base:.3f}) -- cycle;")
    o.append(rf"\draw[line width=0.7pt] {cam};")
    o.append(rf"\draw[black!40, line width=0.4pt] ({x(t0):.3f},{base:.3f}) -- ({x(ev[-1][0]):.3f},{base:.3f});")
    o.append(rf"\draw[black!60, densely dashed, line width=0.45pt] ({x(t0):.3f},{base + 4 * alto:.3f}) -- ({x(ev[-1][0]):.3f},{base + 4 * alto:.3f}) node[right, font=\scriptsize, inner sep=2pt] {{$E = 4$}};")
    for a, b, n in niveles:
        if n and (b - a) * SX > 0.5:
            o.append(rf"\node[seqn] at ({(x(a) + x(b)) / 2:.3f},{base + n * alto - 0.09:.3f}) {{{n}}};")

    # writer: los tramos de cada slot
    color = {W_HDR: 'naranja!45!black', W_DATA: 'naranja!70', W_PAD: 'grisr', W_FOOT: 'black', W_DONE: 'black'}
    for i, tramo in enumerate(slots):
        for e, a, b in tramo:
            o.append(rf"\fill[{color[e]}] ({x(a):.3f},{FILA['wrt']:.2f}) rectangle ({x(b):.3f},{FILA['wrt'] + 0.42:.2f});")
        a, b = tramo[0][1], tramo[-1][2]
        o.append(rf"\draw[line width=0.5pt] ({x(a):.3f},{FILA['wrt']:.2f}) rectangle ({x(b):.3f},{FILA['wrt'] + 0.42:.2f});")
        o.append(rf"\node[seqn] at ({(x(a) + x(b)) / 2:.3f},{FILA['wrt'] + 0.21:.2f}) {{seq {i}}};")
    a, b = slots[-1][0][1], slots[-1][-1][2]
    o.append(rf"\draw[<->, line width=0.45pt] ({x(a):.3f},{FILA['wrt'] + 0.57:.2f}) -- ({x(a + per_wrt):.3f},{FILA['wrt'] + 0.57:.2f}) node[midway, above, font=\scriptsize, inner sep=1.5pt] {{{per_wrt} ciclos por slot}};")

    # commit: wr_slot sube con el footer
    for t, v in commits:
        o.append(rf"\draw[line width=0.6pt] ({x(t):.3f},{FILA['wrt']:.2f}) -- ({x(t):.3f},{FILA['com'] + 0.26:.2f});")
        o.append(rf"\node[font=\scriptsize\ttfamily, inner sep=1pt] at ({x(t):.3f},{FILA['com'] + 0.14:.2f}) {{{v}}};")

    # eje
    y = FILA['com'] - 0.2
    o.append(rf"\draw[black!60, line width=0.5pt] ({x(t0):.3f},{y:.2f}) -- ({fin * SX:.3f},{y:.2f});")
    for c in range(0, fin + 1, 200):
        o.append(rf"\draw[black!60, line width=0.5pt] ({c * SX:.3f},{y:.2f}) -- ({c * SX:.3f},{y - 0.07:.2f});")
        o.append(rf"\node[font=\scriptsize, black!70, anchor=north, inner sep=2pt] at ({c * SX:.3f},{y - 0.07:.2f}) {{{c}}};")
    o.append(rf"\node[font=\scriptsize, black!70, anchor=west, inner sep=2pt] at ({fin * SX + 0.12:.3f},{y - 0.2:.2f}) {{ciclos (8 ns)}};")

    # leyenda del writer
    ly = y - 0.75
    lx = -2.2
    for col, txt, dx in (('naranja!45!black', 'cabecera (4)', 2.05), ('naranja!70', 'muestras (4 ciclos por palabra)', 4.5),
                         ('grisr', 'relleno', 1.45), ('black', 'footer: el commit', 2.6)):
        o.append(rf"\fill[{col}] ({lx:.2f},{ly - 0.09:.2f}) rectangle ({lx + 0.35:.2f},{ly + 0.09:.2f});")
        o.append(rf"\draw[line width=0.4pt] ({lx:.2f},{ly - 0.09:.2f}) rectangle ({lx + 0.35:.2f},{ly + 0.09:.2f});")
        o.append(rf"\node[font=\scriptsize, anchor=west, inner sep=2pt] at ({lx + 0.38:.2f},{ly:.2f}) {{{txt}}};")
        lx += dx + 0.4
    o.append(rf"\node[anchor=north west, font=\scriptsize, black!70, text width=19.2cm, align=left, inner sep=0pt] at (-2.2,{ly - 0.28:.2f}) "
             r"{Traza de la simulación del RTL (\texttt{tiempos/tb\_ring\_medir.sv}): ventana 8 + 24, dos canales, slot de 512 B, "
             rf"AXI ideal y con créditos. Cada trigger perdido queda contado: {len(drenajes)} + {len(busy)} + {len(full)} = {len(trig)}.}};")
    o.append(r"\end{tikzpicture}")
    o.append(r"\end{document}")
    (AQUI.parent / 'ring_tiempos.tex').write_text('\n'.join(o) + '\n')
    print('captura', per_cap, 'writer', per_wrt, 'triggers', len(trig), 'capturados', len(drenajes),
          'busy', len(busy), 'full', len(full), 'slots', len(slots))


if __name__ == '__main__':
    main()
