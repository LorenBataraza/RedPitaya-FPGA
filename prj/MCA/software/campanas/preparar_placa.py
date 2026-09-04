#!/usr/bin/env python3
"""Deja la placa lista para medir, y VERIFICA que lo esté. Corre en la Pitaya.

El problema que resuelve: el bitstream del bus de features conserva el magic
"MCA1" del anterior, y `mca_top.sv` **ignora en silencio las escrituras a
direcciones no mapeadas**. Contra el bitstream viejo, entonces, `configure(
sel_1d=..., zoom_1d=..., discr=...)` no falla — escribe al vacío. La campaña
sale entera, con números plausibles, sin relación con lo que se pidió. No hay
forma de darse cuenta después mirando los datos.

Así que antes de gastar una sesión de laboratorio hay que contestar tres cosas,
y esta herramienta las contesta en un segundo:

  1. ¿está cargado el bitstream que creo que está cargado?
  2. ¿el eje tiene los 8192 canales nuevos (y no los 16384 viejos)?
  3. ¿los registros nuevos retienen lo que se les escribe, uno por uno?

Uso, en la Pitaya::

    python3 campanas/preparar_placa.py            # sólo verifica
    python3 campanas/preparar_placa.py --cargar   # programa la PL y verifica

Desde la PC, todo junto (copia el bitstream, sincroniza y verifica)::

    make -C software placa-preparar
"""
import argparse
import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

from API.mca import (                                            # noqa: E402
    MCA, R_HIST_SEL, R_ZOOM_1D, R_ZOOM_2DX, R_ZOOM_2DY,
    R_DISCR_CTRL, R_DISCR_MIN, R_DISCR_MAX, R_HIST_CTRL,
    R_HIST_STATUS, R_CNT_REJ_DISCR, R_CNT_FULL_SUPP,
)

BITSTREAM = '/root/mca_red_pitaya.bit.bin'

# Registros nuevos que tienen que retener lo escrito, con una máscara: el RTL
# devuelve sólo los bits que implementa, así que comparar la palabra entera
# daría un falso negativo. La máscara es el contrato publicado en
# docs/mca/register_map_mca.md.
ESCRIBIBLES = [
    ('R_HIST_SEL',   R_HIST_SEL,   0x00000FFF),   # {sel_2dy, sel_2dx, sel_1d}
    ('R_ZOOM_1D',    R_ZOOM_1D,    0x0000FF0F),   # {k[15:8], z[3:0]}
    ('R_ZOOM_2DX',   R_ZOOM_2DX,   0x0000FF0F),
    ('R_ZOOM_2DY',   R_ZOOM_2DY,   0x0000FF0F),
    ('R_DISCR_CTRL', R_DISCR_CTRL, 0x000000F3),   # {sel[7:4], externo, enable}
    ('R_DISCR_MIN',  R_DISCR_MIN,  0x0000FFFF),
    ('R_DISCR_MAX',  R_DISCR_MAX,  0x0000FFFF),
    ('R_HIST_CTRL',  R_HIST_CTRL,  0x00000001),   # keep_counter_if_full
]

# Registros nuevos de sólo lectura: no se verifica su valor (depende de lo
# medido), sí que la dirección esté decodificada y no sea basura.
SOLO_LECTURA = [
    ('R_HIST_STATUS',   R_HIST_STATUS,   0x00000003),
    ('R_CNT_REJ_DISCR', R_CNT_REJ_DISCR, 0xFFFFFFFF),
    ('R_CNT_FULL_SUPP', R_CNT_FULL_SUPP, 0xFFFFFFFF),
]

H_AW_ESPERADO = 13          # 8192 canales: el eje nuevo


def verificar(mca, h_aw_esperado=H_AW_ESPERADO):
    """Corre las comprobaciones sobre un handle ya abierto.

    Separado del `main` a propósito: así se puede ejercitar sin placa, contra
    un mmap falso, que es lo que hace campanas/tests/test_preparar_placa.py.

    Devuelve (lista de (nombre, ok, detalle), info).
    """
    r = []
    info = mca.identify(verbose=False)

    r.append(('magic MCA1', info['magic'] == 0x4D434131,
              f"{info['magic']:#010x}"))
    r.append(('bus de features presente', bool(info['features']),
              'sí' if info['features'] else
              'NO: el bitstream es el viejo, cargá mca_red_pitaya.bit.bin'))
    r.append((f'eje de {1 << h_aw_esperado} canales',
              info['h_aw'] == h_aw_esperado,
              f"h_aw = {info['h_aw']} ({info['n_channels']} canales)"))
    r.append(('espectro 1D habilitado', info['hist_h'], ''))
    r.append(('mapa 2D habilitado', info['hist_h_psd'],
              f"{info['map2d_shape'][0]} x {info['map2d_shape'][1]}"))

    # Cada registro nuevo, uno por uno. El patrón se enmascara con lo que el
    # RTL implementa; se prueban dos complementarios para que un bus que
    # devuelve siempre el mismo valor no pase.
    for nombre, off, mascara in ESCRIBIBLES:
        previo = mca.r32(off)
        ok, detalle = True, 'retiene'
        try:
            for patron in (0xA5A5A5A5, 0x5A5A5A5A):
                esperado = patron & mascara
                mca.w32(off, esperado)
                leido = mca.r32(off) & mascara
                if leido != esperado:
                    ok = False
                    detalle = (f'escribí {esperado:#010x}, leí {leido:#010x} '
                               f'(off {off:#05x})')
                    break
        finally:
            mca.w32(off, previo)
        r.append((f'{nombre} escribible', ok, detalle))

    for nombre, off, mascara in SOLO_LECTURA:
        v = mca.r32(off)
        # Un registro de sólo lectura no puede tener bits fuera de su máscara.
        # Si los tiene, la dirección no está decodificada como se cree.
        ok = (v & ~mascara & 0xFFFFFFFF) == 0
        r.append((f'{nombre} decodificado', ok, f'{v:#010x}'))

    return r, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cargar', action='store_true',
                    help='programar la PL con el bitstream antes de verificar')
    ap.add_argument('--bitstream', default=BITSTREAM)
    ap.add_argument('--h-aw', type=int, default=H_AW_ESPERADO,
                    help='canales esperados, como exponente (13 = 8192)')
    args = ap.parse_args(argv)

    if args.cargar:
        # Import acá y no arriba: fpga.py toca /sys y sólo tiene sentido en la
        # placa, así que importarlo siempre rompería el test offline.
        from API.fpga import load_bitstream
        print(f'programando la PL con {args.bitstream} ...')
        load_bitstream(args.bitstream, verbose=True)
        print('  PL programada')

    try:
        mca = MCA.open()
    except Exception as e:
        print(f'\nNO se pudo abrir el MCA: {e}')
        print('  ¿está cargado el bitstream?  '
              f'/opt/redpitaya/bin/fpgautil -b {args.bitstream}')
        return 2

    try:
        filas, info = verificar(mca, args.h_aw)
    finally:
        mca.close()

    print('\n=== estado de la placa ===')
    ancho = max(len(n) for n, _, _ in filas)
    for nombre, ok, detalle in filas:
        print(f'  [{"OK  " if ok else "FALLA"}] {nombre:<{ancho}}'
              + (f'   {detalle}' if detalle else ''))

    malas = [n for n, ok, _ in filas if not ok]
    if malas:
        print(f'\nLA PLACA NO ESTÁ LISTA: {len(malas)} comprobación(es) fallaron.')
        print('  ' + ', '.join(malas))
        return 1

    print(f'\nPLACA LISTA. Eje de {info["n_channels"]} canales, bus de features '
          f'presente, {len(ESCRIBIBLES)} registros nuevos verificados.')
    print('\nsiguiente paso — el experimento de deriva (tasa vs tiempo):')
    print('  make campana-deriva OUT=datos/deriva_$(date +%Y%m%d_%H%M%S)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
