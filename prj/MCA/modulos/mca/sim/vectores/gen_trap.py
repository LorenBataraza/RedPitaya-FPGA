#!/usr/bin/env python3
"""Vectores de tb_mca_trap, desde el modelo de referencia del trapecio.

La referencia es `estimadores.trapecio` (software/API/modelo_rtl): el RTL de
mca_trap calcula lo mismo multiplicado por 2^MF = 16, con M = Mq/16. Como todo
es entero o multiplo de 1/16 y queda por debajo de 2^53, la cuenta en float64 es
EXACTA y se puede comparar bit a bit.

    python3 gen_trap.py            # reescribe trap_ref.txt al lado de este script

Formato de trap_ref.txt, por caso:

    caso <nombre> <k> <m> <mq> <sh> <n>
    <x> <salida esperada>          (n lineas)

donde la salida es la que mca_trap entrega para esa muestra: s >> sh, con
corrimiento aritmetico y saturada a 18 bits con signo. tb_mca_trap la compara
LAT muestras despues.
"""

import math
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, '..', '..', '..', '..', 'software'))
sys.path.insert(0, RAIZ)

from API.modelo_rtl.estimadores import trapecio      # noqa: E402

TW = 18


def pulsos(n, tau, tasa, amp, ruido, rng):
    """Pulsos exponenciales con subida de una muestra, que se apilan."""
    x = np.zeros(n)
    t = 0
    while True:
        t += int(rng.exponential(1.0 / tasa)) + 1
        if t >= n:
            break
        a = rng.uniform(*amp)
        k = np.arange(n - t)
        x[t:] += a * np.exp(-k / tau)
    x += rng.integers(-ruido, ruido + 1, n)
    return np.clip(np.round(x), -16383, 16383).astype(np.int64)


def salida(x, k, m, mq, sh):
    s = trapecio(x, k, m, mq / 16.0)
    s16 = np.round(s * 16.0)
    assert np.all(np.abs(s16) < 2 ** 52), 'fuera del rango exacto de float64'
    assert np.all(s16 == s * 16.0), 'la cuenta no salio entera'
    s_int = [int(v) for v in s16]
    lo, hi = -(1 << (TW - 1)), (1 << (TW - 1)) - 1
    return [min(max(v >> sh, lo), hi) for v in s_int]


def elegir_sh(x, k, m, mq):
    """El corrimiento que deja la salida en ~16 bits: no satura y no se come
    todos los bits bajos."""
    s = np.abs(trapecio(x, k, m, mq / 16.0) * 16.0).max()
    return max(0, int(math.ceil(math.log2(s + 1))) - 16)


def main():
    rng = np.random.default_rng(2026)
    casos = []

    # 1. polo-cero exacto sobre pulsos con cola tau = 40 que se apilan
    tau = 40.0
    mq = round(16.0 / (math.exp(1.0 / tau) - 1.0))
    x = pulsos(6000, tau, 1 / 150, (100, 3000), 3, rng)
    casos.append(('polo_cero', x, 16, 8, mq, elegir_sh(x, 16, 8, mq)))

    # 2. lineas de retardo hondas: k = 600, l = 1000
    x = pulsos(6000, 300.0, 1 / 900, (200, 2000), 5, rng)
    casos.append(('hondo', x, 600, 400, 4800, elegir_sh(x, 600, 400, 4800)))

    # 3. sin corrimiento: los bits bajos de s, con muestras chicas y negativas
    x = rng.integers(-40, 41, 4000).astype(np.int64)
    casos.append(('exacto', x, 3, 0, 0, 0))

    # 4. M grande y muestras al limite del rango de 15 bits
    x = np.where(rng.random(4000) < 0.01, 16383, rng.integers(-16383, 16384, 4000))
    casos.append(('extremo', x.astype(np.int64), 20, 30, (1 << 20) - 1,
                  elegir_sh(x, 20, 30, (1 << 20) - 1)))

    ruta = os.path.join(AQUI, 'trap_ref.txt')
    with open(ruta, 'w') as fh:
        for nombre, x, k, m, mq, sh in casos:
            y = salida(x, k, m, mq, sh)
            fh.write(f'caso {nombre} {k} {m} {mq} {sh} {len(x)}\n')
            for xi, yi in zip(x, y):
                fh.write(f'{int(xi)} {yi}\n')
            print(f'{nombre:10s} k={k:3d} m={m:3d} mq={mq:7d} sh={sh:2d} '
                  f'{len(x)} muestras, salida en [{min(y)}, {max(y)}]')
    print(f'-> {ruta}')


if __name__ == '__main__':
    main()
