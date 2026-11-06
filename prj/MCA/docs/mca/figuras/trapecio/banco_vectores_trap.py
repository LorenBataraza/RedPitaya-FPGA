#!/usr/bin/env python3
"""Vectores de tb_mca_trap con las formas del banco: el RTL de mca_trap, bit a bit.

tb_mca_trap compara mca_trap contra estimadores.trapecio con los casos de
modulos/mca/sim/vectores/gen_trap.py. Esto arma OTROS casos, con las formas del
banco (64/48, 32/24, 16/12, 8/8 y 8/12, cada una con su sh) y la del inspector
de apilamiento (2/1), pulsos como los de la placa (cola de 250, amplitudes de 100
a 4000 que se apilan, ruido de 4.5 cuentas) y dos M: el nominal y el que se
ajusto en la placa (242.8).

    python3 banco_vectores_trap.py /ruta/trap_banco.txt
    cd prj/MCA/modulos/mca/work && make -s compile
    vsim -c -work questa tb_mca_trap +VEC=/ruta/trap_banco.txt +NCASOS=10 -do "run -all; quit -f"

El TB compara cada caso contra dos instancias (lineas en BRAM y en LUT) y repite
el primero despues de un reset sin clr.
Resultado (2026-11-03): 10 casos, 210 103 comparaciones, 0 errores, PASS.
"""
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(AQUI, '..', '..', '..', '..', 'modulos', 'mca', 'sim',
                                                'vectores')))
sys.path.insert(0, AQUI)
import gen_trap as g                                   # noqa: E402
from recuperacion_modelo import MQ, Forma              # noqa: E402

FORMAS = [Forma(64, 48, 4, 80), Forma(32, 24, 3, 39), Forma(16, 12, 2, 19), Forma(8, 8, 1, 10),
          Forma(8, 12, 1, 10), Forma(2, 1, 0, 0)]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    rng = np.random.default_rng(3)
    casos = []
    for f in FORMAS:
        for nombre, tasa, mq in (('pz_nominal', 1 / 120, MQ), ('pz_placa', 1 / 60, round(242.8 * 16))):
            if f.m in (12, 1) and f.k in (8, 2) and nombre == 'pz_nominal':
                continue
            x = g.pulsos(8000, 250.0, tasa, (100, 4000), 0, rng).astype(float)
            x += np.round(rng.normal(0, 4.5, len(x)))
            x = np.clip(x, -8192, 8191).astype(np.int64)
            casos.append((f'k{f.k}m{f.m}_{nombre}', x, f.k, f.m, mq, f.sh))
    with open(sys.argv[1], 'w') as fh:
        for nombre, x, k, m, mq, sh in casos:
            y = g.salida(x, k, m, mq, sh)
            fh.write(f'caso {nombre} {k} {m} {mq} {sh} {len(x)}\n')
            for xi, yi in zip(x, y):
                fh.write(f'{int(xi)} {yi}\n')
            print(f'{nombre:20s} k={k:3d} m={m:3d} mq={mq} sh={sh:2d} salida [{min(y)}, {max(y)}]')
    print(f'-> {sys.argv[1]}')


if __name__ == '__main__':
    main()
