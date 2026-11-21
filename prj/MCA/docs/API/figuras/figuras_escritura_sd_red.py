#!/usr/bin/env python3
"""La escritura de archivos de las dos maneras, en la placa: la sesión que guarda en
la SD (etapa C) contra el ring por red (etapa D), en el estilo de bench_escribir.

  bench_sd_red.tex   (a) cuántos eventos por segundo pasan con el ring saturado, por
                     ventana, y el techo de TCP solo; (b) lo mismo en MB/s

Son DATOS MEDIDOS. software/datos/ no está en git, así que los números van acá, con
la corrida de donde salen:

  - SD: software/datos/etapas_sd_largo_2026-11-17/*/etapas_ring.json
    (bitstream c1875919, periódico, unos 22 s por punto y 300-400 MB), contando el
    `sync` del final: es lo que baja a la tarjeta, el guardado persistente. Un
    solo punto por ventana, así que no hay rango. Los puntos cortos de la campaña del
    2026-11-12 (placa_etapas_20261112/etapa_C_sd, 1-4 s) no van: caben en el page
    cache y miden la RAM;
  - red: software/datos/etapas_red_2026-11-17b/ y etapas_red_2026-11-17c/
    etapas_ring.json, la etapa D (guarda los ring_*.bin en la PC, convierte a .npz y
    verifica), bitstream del ring c1875919, libmca 0.12.0, PC cableada a 1 Gb/s;
  - TCP solo: `make bench-tcp-placa`, 2026-11-17, 1 GiB en 21.3 s.

En la red, cada valor es la mediana de lo que pasa en los puntos con DROP_FULL (el ring lleno,
la etapa saturada), en los dos modos del generador, y el rango es el mínimo y el
máximo de esos puntos. Los bytes por evento son los del slot sin el relleno: 32 de
cabecera y 2 bytes por muestra de cada uno de los dos canales.

No hay un panel de la PC: lo que cuesta escribir los archivos está en bench_escribir.
Los epígrafes no van adentro: están en <figura>.txt.

    python3 figuras_escritura_sd_red.py            # escribe el .tex y lo compila
    python3 figuras_escritura_sd_red.py --sin-compilar
"""
import argparse

from figuras_bench_escritura import (AQUI, a_pdf_svg, compilar, f, marco_log, barra)

VENTANAS = (32, 256, 1024)                          # muestras por canal
NOMBRE_V = {32: '8+24', 256: '16+240', 1024: '32+992'}
BYTES = {w: 32 + 4 * w for w in VENTANAS}           # por evento

# kev/s: (mediana, mínimo, máximo) con el ring saturado
PASA = {
    'sd':  {32: (87.25, 87.25, 87.25), 256: (9.76, 9.76, 9.76), 1024: (3.66, 3.66, 3.66)},
    'red': {32: (304.2, 202.3, 308.0), 256: (32.1, 31.9, 32.4), 1024: (8.2, 8.1, 11.2)},
}
TCP_MB_S = 50.38

METODOS = (('sd', 'fsd', 'la sesión en la placa, a la SD (22 s y \\texttt{sync})'),
           ('red', 'fred', 'el ring por red, a la PC'))

W, H, SEP = 6.0, 4.2, 1.6
LO, HI = 1.0, 1e3                                   # kev/s
MB_MAX = 60.0
B, G = 0.55, 0.08


def bigote(l, x, y_lo, y_hi):
    l.append(f'\\draw[black!75, line width=0.5pt] ({f(x)},{f(y_lo)}) -- ({f(x)},{f(y_hi)}) '
             f'({f(x - 0.07)},{f(y_lo)}) -- ++(0.14,0) ({f(x - 0.07)},{f(y_hi)}) -- ++(0.14,0);')


def fig_sd_red():
    l = [r'\definecolor{fsd}{HTML}{D9702A}', r'\definecolor{fred}{HTML}{3F8FD2}']
    paso = W / len(VENTANAS)
    ancho_grupo = len(METODOS) * B + G

    def ejes_x(x0):
        for i, w in enumerate(VENTANAS):
            xc = x0 + paso * (i + 0.5)
            l.append(f'\\node[tick, anchor=north] at ({f(xc)},-0.06) {{{NOMBRE_V[w]}}};')
            l.append(f'\\node[tick, anchor=north, black!55, font=\\tiny] at '
                     f'({f(xc)},-0.36) {{{BYTES[w]:,} B/evento}};'
                     .replace(f'{BYTES[w]:,}', f'{BYTES[w]:,}'.replace(',', '\\,')))
        l.append(f'\\node[titeje, anchor=north] at ({f(x0 + W / 2)},-0.72) '
                 '{ventana: muestras antes + después del disparo};')

    # (a) eventos por segundo, logarítmico
    Y = marco_log(l, 0.0, W, H, LO, HI)
    l.append(f'\\node[parte] at (0,{f(H + 0.25)}) {{(a)\\enspace eventos por segundo}};')
    for i, w in enumerate(VENTANAS):
        xg = paso * (i + 0.5) - ancho_grupo / 2
        for j, (m, color, _) in enumerate(METODOS):
            med, lo, hi = PASA[m][w]
            x = xg + j * (B + G)
            barra(l, f'barra={color}', x, B, Y(med))
            if hi > lo:
                bigote(l, x + B / 2, Y(lo), Y(hi))
        tcp = TCP_MB_S * 1e3 / BYTES[w]             # kev/s
        l.append(f'\\draw[ref] ({f(xg - 0.12)},{f(Y(tcp))}) -- '
                 f'({f(xg + ancho_grupo + 0.12)},{f(Y(tcp))});')
    ejes_x(0.0)
    l.append(f'\\node[titeje, rotate=90, anchor=south] at (-0.95,{f(H / 2)}) '
             '{eventos por segundo que pasan [kev/s]};')

    # (b) MB/s, lineal
    x0 = W + SEP
    for v in range(0, int(MB_MAX) + 1, 10):
        y = v / MB_MAX * H
        l.append(f'\\draw[guia] ({f(x0)},{f(y)}) -- ({f(x0 + W)},{f(y)});')
        l.append(f'\\draw[eje] ({f(x0)},{f(y)}) -- ++(-0.07,0) node[tick, left] {{{v}}};')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0)},{f(H)});')
    l.append(f'\\draw[eje] ({f(x0)},0) -- ({f(x0 + W)},0);')
    l.append(f'\\node[parte] at ({f(x0)},{f(H + 0.25)}) {{(b)\\enspace bytes por segundo}};')
    MB = lambda v: v / MB_MAX * H                   # noqa: E731
    for i, w in enumerate(VENTANAS):
        xg = x0 + paso * (i + 0.5) - ancho_grupo / 2
        for j, (m, color, _) in enumerate(METODOS):
            med, lo, hi = (v * BYTES[w] / 1e3 for v in PASA[m][w])
            x = xg + j * (B + G)
            barra(l, f'barra={color}', x, B, MB(med))
            if hi > lo:
                bigote(l, x + B / 2, MB(lo), MB(hi))
            l.append(f'\\node[valor, anchor=south] at ({f(x + B / 2)},{f(MB(hi) + 0.03)}) '
                     f'{{{med:.0f}}};')
    yt = MB(TCP_MB_S)
    l.append(f'\\draw[ref] ({f(x0)},{f(yt)}) -- ({f(x0 + W)},{f(yt)});')
    l.append(f'\\node[tick, anchor=south east, black!65] at ({f(x0 + W)},{f(yt)}) '
             '{TCP solo, 50 MB/s};')
    ejes_x(x0)
    l.append(f'\\node[titeje, rotate=90, anchor=south] at ({f(x0 - 0.6)},{f(H / 2)}) '
             '{MB/s que pasan};')

    # leyenda
    y, x = -1.45, -0.4
    for m, color, nombre in METODOS:
        l.append(f'\\path[barra={color}] ({f(x)},{f(y - 0.12)}) rectangle ++(0.4,0.26);')
        l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
                 f'{{{nombre}}};')
        x += 6.2 if color == 'fsd' else 4.0
    l.append(f'\\draw[ref] ({f(x)},{f(y)}) -- ++(0.4,0);')
    l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
             '{el techo de TCP solo};')
    x += 3.4
    bigote(l, x + 0.2, y - 0.13, y + 0.13)
    l.append(f'\\node[anchor=west, font=\\scriptsize] at ({f(x + 0.45)},{f(y)}) '
             '{mínimo y máximo};')
    return l


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--sin-compilar', action='store_true')
    a = p.parse_args()
    tex = compilar('bench_sd_red', fig_sd_red(),
                   'La SD contra la red: lo que pasa con el ring saturado')
    print('escrito', tex.name)
    if not a.sin_compilar:
        a_pdf_svg(tex)


if __name__ == '__main__':
    main()
