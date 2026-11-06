#!/usr/bin/env python3
"""Compara corridas de `bench_impl.py`.

Con un directorio, las implementaciones entre sí, dentro de esa corrida:

    python3 API/bench/comparar_bench.py datos/bench_impl_20261029_120000

    operación               py µs      c µs  c_puro µs     py/c  c/c_puro
    api.spectrum         110213.4    3912.0     3850.1     28.2      1.02

Con dos, cada implementación contra sí misma entre la corrida A y la B (antes
y después de un cambio, o entre dos bitstreams). El factor es A/B: mayor que
1 quiere decir que B es más rápida.

    python3 API/bench/comparar_bench.py DIR_A DIR_B

Si los entornos difieren en algo que cambia los tiempos (la máquina, la
compilación de libmca, la geometría del MCA, el governor de la CPU), se avisa
arriba de la tabla: la comparación puede seguir siendo útil, pero no es la
misma medición.
"""

import json
import os
import sys

IMPLS = ('py', 'c', 'c_puro', 'remoto')

# Lo que, si cambia entre A y B, hace que la diferencia de tiempos no sea sólo
# del código.
CLAVES_ENTORNO = ('machine', 'fake', 'medio', 'libmca_build', 'mca_magic',
                  'mca_widths', 'mca_caps', 'cpu_governor', 'python', 'numpy')


def cargar(directorio):
    with open(os.path.join(directorio, 'resumen.json')) as f:
        r = json.load(f)
    # `medio` es posterior a las primeras corridas: sin él, fue sobre la PL
    # (o sobre FakeMCA, que ya decía `fake`).
    e = r['entorno']
    e.setdefault('medio', 'fake' if e.get('fake') else 'pl')
    return r


def _med(r, op, impl):
    st = r['ops'].get(op, {}).get(impl)
    return None if st is None else st['mediana_us']


def _num(v, ancho=11):
    return f'{"—":>{ancho}s}' if v is None else f'{v:{ancho}.1f}'


def _factor(a, b, ancho=9):
    if a is None or b is None or b == 0:
        return f'{"—":>{ancho}s}'
    return f'{a / b:{ancho}.2f}'


def una(r, titulo=''):
    e = r['entorno']
    print(f'{titulo}{e.get("fecha")}  commit {e.get("commit")}  '
          f'{e.get("machine")}  libmca {e.get("libmca_version")}'
          + ('  [FAKE: los tiempos no son de la placa]' if e.get('fake') else '')
          + ('  [SHM: sin bus, sólo el costo de cada implementación]'
             if e.get('medio') == 'shm' else '')
          + (f'  [REMOTO: desde la PC contra {e.get("host")}]'
             if e.get('medio') == 'remoto' else ''))
    if e.get('medio') == 'remoto':
        print(f'{"operación":22s}{"remoto µs":>11s}')
        for op in sorted(r['ops']):
            print(f'{op:22s}{_num(_med(r, op, "remoto"))}')
    else:
        print(f'{"operación":22s}{"py µs":>11s}{"c µs":>11s}{"c_puro µs":>11s}'
              f'{"py/c":>9s}{"c/c_puro":>9s}')
        for op in sorted(r['ops']):
            py, c, pu = (_med(r, op, i) for i in IMPLS[:3])
            print(f'{op:22s}{_num(py)}{_num(c)}{_num(pu)}{_factor(py, c)}'
                  f'{_factor(c, pu)}')
    for k, v in r.get('no_disponible', {}).items():
        print(f'  no disponible: {k}: {v}')
    for k, v in r.get('igualdad', {}).items():
        if isinstance(v, dict) and not v.get('iguales'):
            print(f'  ATENCIÓN: {k} distinto entre implementaciones')


def dos(a, b):
    ea, eb = a['entorno'], b['entorno']
    distintas = [k for k in CLAVES_ENTORNO if ea.get(k) != eb.get(k)]
    print(f'A: {ea.get("fecha")}  commit {ea.get("commit")}')
    print(f'B: {eb.get("fecha")}  commit {eb.get("commit")}')
    for k in distintas:
        print(f'  aviso: {k} distinto: A={ea.get(k)!r}  B={eb.get(k)!r}')
    print(f'{"operación":22s}{"impl":>8s}{"A µs":>11s}{"B µs":>11s}{"A/B":>9s}')
    for op in sorted(set(a['ops']) | set(b['ops'])):
        for impl in IMPLS:
            va, vb = _med(a, op, impl), _med(b, op, impl)
            if va is None and vb is None:
                continue
            print(f'{op:22s}{impl:>8s}{_num(va)}{_num(vb)}{_factor(va, vb)}')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 1:
        una(cargar(argv[0]))
    elif len(argv) == 2:
        dos(cargar(argv[0]), cargar(argv[1]))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
