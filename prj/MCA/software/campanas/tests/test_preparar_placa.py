#!/usr/bin/env python3
"""`preparar_placa.verificar` contra el MCA2 y el MCA1, sin placa.

Lo que se prueba es la detección, no la placa: que la verificación distinga el
MCA2 del MCA1. Importa porque el modo de falla es silencioso: `mca_top.sv`
ignora las escrituras a direcciones no mapeadas sin dar error, así que contra
el bitstream equivocado una campaña corre entera y devuelve números plausibles
que no tienen nada que ver con lo que se pidió.

Los dos mapas se simulan con lo que hace el RTL de verdad: el MCA2 descarta las
escrituras a los offsets reservados y los lee en cero; el MCA1 los retiene, y
descarta en cambio las de los registros del MCA2 (ranuras, trapecio).

Uso:
    python3 test_preparar_placa.py
"""
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.join(_RAIZ, 'API', 'tests'))
sys.path.insert(0, os.path.dirname(_AQUI))

import API.mca as A                                   # noqa: E402
from gen_compat_baseline import FakeMmap              # noqa: E402
import preparar_placa as pp                           # noqa: E402

FALLAS = []

RESERVADOS = {off for _, off in pp.RESERVADOS}
SOLO_MCA2 = {A.R_N_ACC, A.R_PRE_DLY, A.R_TRAP_KM, A.R_TRAP_MQ, A.R_TRAP_MED}


def check(nombre, ok, detalle=''):
    print(f'  [{"PASS" if ok else "FAIL"}] {nombre}' + (f'  {detalle}' if detalle else ''))
    if not ok:
        FALLAS.append(nombre)
    return ok


class MmapMCA2(FakeMmap):
    """Como el RTL del MCA2: los offsets reservados no retienen nada."""

    def __setitem__(self, k, v):
        if isinstance(k, slice) and k.start in RESERVADOS:
            return
        super().__setitem__(k, v)


class MmapMCA2SinTrapecio(MmapMCA2):
    """El MCA2 de la fase A: sin el trapecio, sus registros no existen."""

    def __setitem__(self, k, v):
        if isinstance(k, slice) and k.start in (A.R_TRAP_KM, A.R_TRAP_MQ,
                                                 A.R_TRAP_MED):
            return
        super().__setitem__(k, v)


class MmapMCA1(FakeMmap):
    """Como el RTL del MCA1: retiene el umbral y compañía, y los registros del
    MCA2 no existen (se descartan y leen cero)."""

    def __setitem__(self, k, v):
        if isinstance(k, slice) and k.start in SOLO_MCA2:
            return
        super().__setitem__(k, v)


def _handle(clase, magic, h_aw):
    m = clase(A.MCA_SIZE)
    m.poke(A.R_MAGIC, magic)
    m.poke(A.R_CAPS, A.CAP_HIST_H | A.CAP_HIST_H_PSD)
    m.poke(A.R_WIDTHS, (8 << 16) | (8 << 8) | h_aw)
    if issubclass(clase, MmapMCA2):
        m.poke(A.R_N_ACC_MAX, 4)
    caps = A.CAP_HIST_H | A.CAP_HIST_H_PSD
    return m, A.MCA(m, -1, caps, h_aw, 8, 8)


def test_mca2_pasa():
    print('\n== MCA2: todo verde ==')
    m, mca = _handle(MmapMCA2, A.MAGIC, 13)
    filas, info = pp.verificar(mca)
    malas = [n for n, ok, _ in filas if not ok]
    check('ninguna comprobación falla', not malas, str(malas))
    check('detectó las ranuras', info['n_acc_max'] == 4)
    check('detectó el eje de 8192', info['n_channels'] == 8192)
    check('verificó todos los registros',
          len(filas) == 5 + len(pp.ESCRIBIBLES) + len(pp.RESERVADOS)
          + len(pp.SOLO_LECTURA), f'{len(filas)} comprobaciones')


def test_mca2_sin_trapecio_pasa():
    print('\n== MCA2 sin trapecio (fase A): sus registros no aplican ==')
    m, mca = _handle(MmapMCA2SinTrapecio, A.MAGIC, 13)
    filas, info = pp.verificar(mca)
    malas = [n for n, ok, _ in filas if not ok]
    check('ninguna comprobación falla', not malas, str(malas))
    check('y lo dice', any('no aplica' in d for n, _, d in filas
                           if n.startswith('R_TRAP')))


def test_mca1_se_detecta():
    print('\n== MCA1: tiene que fallar, y decir por qué ==')
    m, mca = _handle(MmapMCA1, A.MAGIC_MCA1, 13)
    filas, info = pp.verificar(mca)
    d = {n: (ok, det) for n, ok, det in filas}

    check('el magic falla y dice que es el MCA1',
          not d['magic MCA2'][0] and 'MCA1' in d['magic MCA2'][1],
          d['magic MCA2'][1])
    check('sin ranuras', not d['ranuras (N_ACC)'][0])
    reservados = [n for n, ok, _ in filas if n.startswith('reservado') and not ok]
    check('los reservados retienen: no es el MCA2',
          len(reservados) == len(pp.RESERVADOS),
          f'{len(reservados)} de {len(pp.RESERVADOS)}')
    # Las ranuras no retienen; el trapecio, como CAPS no lo trae, no aplica.
    nuevos = sorted(n for n, ok, _ in filas if 'escribible' in n and not ok)
    check('las ranuras no retienen',
          nuevos == ['R_N_ACC escribible', 'R_PRE_DLY escribible'], str(nuevos))


def test_la_sonda_restaura_y_no_ensucia():
    print('\n== la sonda deja los registros como estaban ==')
    m, mca = _handle(MmapMCA2, A.MAGIC, 13)
    previos = {off: 0xBEEF & mask for _, off, mask in pp.ESCRIBIBLES}
    for off, v in previos.items():
        mca.w32(off, v)
    pp.verificar(mca)
    malos = [f'{off:#05x}' for off, v in previos.items() if mca.r32(off) != v]
    check('cada registro volvió a su valor previo', not malos, str(malos))


def test_tiene_features_no_escribe():
    print('\n== tiene_features no escribe nada (en el MCA2 lo dice el magic) ==')
    m, mca = _handle(MmapMCA2, A.MAGIC, 13)
    n0 = len(m.writes)
    check('contesta que sí', mca.tiene_features() is True)
    check('sin escribir ni una vez', len(m.writes) == n0,
          f'{len(m.writes) - n0} escrituras')


if __name__ == '__main__':
    print('detección de bitstream (MCA2 vs MCA1), sin placa')
    test_mca2_pasa()
    test_mca2_sin_trapecio_pasa()
    test_mca1_se_detecta()
    test_la_sonda_restaura_y_no_ensucia()
    test_tiene_features_no_escribe()
    print('\nRESULT:', 'PASS' if not FALLAS else f'FAIL ({len(FALLAS)}): {FALLAS}')
    sys.exit(1 if FALLAS else 0)
