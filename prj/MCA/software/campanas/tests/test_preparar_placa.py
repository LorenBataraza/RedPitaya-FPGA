#!/usr/bin/env python3
"""`preparar_placa.verificar` contra los DOS bitstreams, sin placa.

Lo que se prueba es la detección, no la placa: que la verificación distinga el
bitstream nuevo del viejo. Importa porque el modo de falla es silencioso — el
magic es "MCA1" en los dos y `mca_top.sv` ignora las escrituras a direcciones no
mapeadas sin dar error, así que contra el bitstream viejo una campaña con
`sel_1d`/`zoom`/`discr` corre entera y devuelve números plausibles que no tienen
nada que ver con lo que se pidió.

El MCA viejo se simula con lo que hace el RTL de verdad: las escrituras a
`0x090` y para arriba se descartan, y esas direcciones leen cero (el `default`
del decodificador).

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

# Primera dirección del bloque nuevo. Todo lo de acá para arriba (salvo las
# aperturas de histograma) no existe en el bitstream viejo.
PRIMERA_NUEVA = 0x090


def check(nombre, ok, detalle=''):
    print(f'  [{"PASS" if ok else "FAIL"}] {nombre}' + (f'  {detalle}' if detalle else ''))
    if not ok:
        FALLAS.append(nombre)
    return ok


class MmapViejo(FakeMmap):
    """Como el RTL anterior: descarta escrituras al bloque nuevo, lee cero."""

    def __setitem__(self, k, v):
        if isinstance(k, slice) and PRIMERA_NUEVA <= k.start < 0x10000:
            return                      # el decodificador viejo las ignora
        super().__setitem__(k, v)


def _handle(clase, h_aw):
    m = clase(A.MCA_SIZE)
    m.poke(A.R_MAGIC, A.MAGIC)
    m.poke(A.R_CAPS, A.CAP_HIST_H | A.CAP_HIST_H_PSD)
    m.poke(A.R_WIDTHS, (8 << 16) | (8 << 8) | h_aw)
    caps = A.CAP_HIST_H | A.CAP_HIST_H_PSD
    return m, A.MCA(m, -1, caps, h_aw, 8, 8)


def test_bitstream_nuevo_pasa():
    print('\n== bitstream NUEVO: todo verde ==')
    m, mca = _handle(FakeMmap, 13)
    filas, info = pp.verificar(mca)
    malas = [n for n, ok, _ in filas if not ok]
    check('ninguna comprobación falla', not malas, str(malas))
    check('detectó el bus de features', info['features'] is True)
    check('detectó el eje de 8192', info['n_channels'] == 8192)
    check('verificó todos los registros nuevos',
          len(filas) == 5 + len(pp.ESCRIBIBLES) + len(pp.SOLO_LECTURA),
          f'{len(filas)} comprobaciones')


def test_bitstream_viejo_se_detecta():
    print('\n== bitstream VIEJO: tiene que fallar, y decir por qué ==')
    m, mca = _handle(MmapViejo, 14)
    filas, info = pp.verificar(mca)
    d = {n: (ok, det) for n, ok, det in filas}

    check('NO reporta bus de features', info['features'] is False)
    check('la comprobación del bus de features falla',
          not d['bus de features presente'][0])
    check('y explica qué hacer',
          'viejo' in d['bus de features presente'][1].lower(),
          d['bus de features presente'][1])
    check('detecta que el eje sigue en 16384',
          not d['eje de 8192 canales'][0], d['eje de 8192 canales'][1])
    check('el magic NO alcanza para distinguirlos (por eso hace falta esto)',
          d['magic MCA1'][0] is True)

    fallados = [n for n, ok, _ in filas if not ok and 'escribible' in n]
    check('todos los registros nuevos dan como no escribibles',
          len(fallados) == len(pp.ESCRIBIBLES),
          f'{len(fallados)} de {len(pp.ESCRIBIBLES)}')


def test_la_sonda_restaura_y_no_ensucia():
    print('\n== la sonda deja los registros como estaban ==')
    m, mca = _handle(FakeMmap, 13)
    previos = {off: 0xBEEF & mask for _, off, mask in pp.ESCRIBIBLES}
    for off, v in previos.items():
        mca.w32(off, v)
    pp.verificar(mca)
    malos = [f'{off:#05x}' for off, v in previos.items() if mca.r32(off) != v]
    check('cada registro volvió a su valor previo', not malos, str(malos))


def test_probe_no_escribe_si_el_discriminador_esta_activo():
    print('\n== con el discriminador activo, la sonda no escribe nada ==')
    m, mca = _handle(FakeMmap, 13)
    mca.w32(A.R_DISCR_CTRL, 0x1)            # enable
    mca.w32(A.R_DISCR_MIN, 0x1234)
    n0 = len(m.writes)
    ok = mca.tiene_features()
    check('contesta que sí', ok is True)
    check('sin escribir ni una vez', len(m.writes) == n0,
          f'{len(m.writes) - n0} escrituras')
    check('y no tocó el umbral del corte', mca.r32(A.R_DISCR_MIN) == 0x1234)


if __name__ == '__main__':
    print('detección de bitstream (viejo vs nuevo), sin placa')
    test_bitstream_nuevo_pasa()
    test_bitstream_viejo_se_detecta()
    test_la_sonda_restaura_y_no_ensucia()
    test_probe_no_escribe_si_el_discriminador_esta_activo()
    print('\nRESULT:', 'PASS' if not FALLAS else f'FAIL ({len(FALLAS)}): {FALLAS}')
    sys.exit(1 if FALLAS else 0)
