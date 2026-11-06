#!/usr/bin/env python3
"""Deja la placa lista para medir, y VERIFICA que lo esté. Corre en la Pitaya.

El problema que resuelve: `mca_top.sv` **ignora en silencio las escrituras a
direcciones no mapeadas** y las lee en cero. Contra un bitstream que no es el
que se cree, `configure(...)` no falla — escribe al vacío, y la campaña sale
entera, con números plausibles, sin relación con lo que se pidió.

Así que antes de gastar una sesión de laboratorio hay que contestar cuatro
cosas, y esta herramienta las contesta en un segundo:

  1. ¿está cargado el MCA2 (las ranuras), y no el MCA1?
  2. ¿el eje tiene los 8192 canales?
  3. ¿los registros del MCA2 retienen lo que se les escribe, uno por uno?
  4. ¿los offsets que el MCA2 dejó reservados (el umbral, la histéresis,
     maxlen, ...) leen cero? En el MCA1 retienen: es la diferencia que se ve.

Uso, en la Pitaya::

    python3 campanas/preparar_placa.py            # sólo verifica
    python3 campanas/preparar_placa.py --cargar   # programa la PL y verifica

Desde la PC, todo junto (copia el bitstream, sincroniza y verifica)::

    make -C software verificar-placa-bitstream
"""
import argparse
import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

from API.mca import (                                            # noqa: E402
    MAGIC, MAGIC_MCA1, MCA, R_HIST_SEL, R_ZOOM_1D, R_ZOOM_2DX, R_ZOOM_2DY,
    R_DISCR_CTRL, R_DISCR_MIN, R_DISCR_MAX, R_HIST_CTRL,
    R_HIST_STATUS, R_CNT_REJ_DISCR, R_CNT_FULL_SUPP,
    R_N_ACC, R_PRE_DLY, R_TRAP_KM, R_TRAP_MQ, R_TRAP_MED, R_N_ACC_MAX,
    R_PUB_STATE,
)

BITSTREAM = '/root/mca_red_pitaya.bit.bin'

# Registros que tienen que retener lo escrito, con una máscara: el RTL devuelve
# sólo los bits que implementa, así que comparar la palabra entera daría un
# falso negativo. La máscara es el contrato publicado en
# docs/mca/register_map_mca.md. Escribir el trapecio reinicia su estado, que es
# inofensivo con el MCA parado; todo se restaura.
ESCRIBIBLES = [
    ('R_HIST_SEL',   R_HIST_SEL,   0x00000FFF),   # {sel_2dy, sel_2dx, sel_1d}
    ('R_ZOOM_1D',    R_ZOOM_1D,    0x0000FF0F),   # {k[15:8], z[3:0]}
    ('R_ZOOM_2DX',   R_ZOOM_2DX,   0x0000FF0F),
    ('R_ZOOM_2DY',   R_ZOOM_2DY,   0x0000FF0F),
    ('R_DISCR_CTRL', R_DISCR_CTRL, 0x000000F3),   # {sel[7:4], externo, enable}
    ('R_DISCR_MIN',  R_DISCR_MIN,  0x0000FFFF),
    ('R_DISCR_MAX',  R_DISCR_MAX,  0x0000FFFF),
    ('R_HIST_CTRL',  R_HIST_CTRL,  0x00000001),   # keep_counter_if_full
    ('R_N_ACC',      R_N_ACC,      0x00000007),   # ranuras habilitadas
    ('R_PRE_DLY',    R_PRE_DLY,    0x0000007F),   # retardo de la muestra
    ('R_TRAP_KM',    R_TRAP_KM,    0x03FF03FF),   # {m[25:16], k[9:0]}
    ('R_TRAP_MQ',    R_TRAP_MQ,    0x000FFFFF),   # M*16
    ('R_TRAP_MED',   R_TRAP_MED,   0x3F07FFFF),   # {sh, lw, off}
]

# Los offsets que el MCA2 dejó reservados: se escriben sin efecto y leen cero.
# En el MCA1 eran el umbral, la histéresis, maxlen, tail_dly, el modo de
# compuerta y las políticas, y retenían lo escrito.
RESERVADOS = [
    ('0x014 (era thr)',      0x014), ('0x018 (era hyst)',     0x018),
    ('0x028 (era maxlen)',   0x028), ('0x02C (era tail_dly)', 0x02C),
    ('0x048 (era gate_mode)', 0x048), ('0x104 (era win_pol)', 0x104),
    ('0x108 (era rearm_dly)', 0x108),
]

# Registros de sólo lectura: no se verifica su valor (depende de lo medido),
# sí que la dirección esté decodificada y no sea basura.
SOLO_LECTURA = [
    ('R_HIST_STATUS',   R_HIST_STATUS,   0x00000003),
    ('R_CNT_REJ_DISCR', R_CNT_REJ_DISCR, 0xFFFFFFFF),
    ('R_CNT_FULL_SUPP', R_CNT_FULL_SUPP, 0xFFFFFFFF),
    ('R_PUB_STATE',     R_PUB_STATE,     0xFFFF0F0F),
]

H_AW_ESPERADO = 13          # 8192 canales


def verificar(mca, h_aw_esperado=H_AW_ESPERADO):
    """Corre las comprobaciones sobre un handle ya abierto.

    Separado del `main` a propósito: así se puede ejercitar sin placa, contra
    un mmap falso, que es lo que hace campanas/tests/test_preparar_placa.py.

    Devuelve (lista de (nombre, ok, detalle), info).
    """
    r = []
    info = mca.identify(verbose=False)

    magic = info['magic']
    r.append(('magic MCA2', magic == MAGIC,
              f'{magic:#010x}' + ('  <- es el MCA1: cargá el bitstream de las '
                                  'ranuras' if magic == MAGIC_MCA1 else '')))
    n_max = mca.r32(R_N_ACC_MAX)
    r.append(('ranuras (N_ACC)', 1 <= n_max <= 7, f'{n_max}'))
    r.append((f'eje de {1 << h_aw_esperado} canales',
              info['h_aw'] == h_aw_esperado,
              f"h_aw = {info['h_aw']} ({info['n_channels']} canales)"))
    r.append(('espectro 1D habilitado', info['hist_h'], ''))
    r.append(('mapa 2D habilitado', info['hist_h_psd'],
              f"{info['map2d_shape'][0]} x {info['map2d_shape'][1]}"))

    # Cada registro, uno por uno. El patrón se enmascara con lo que el RTL
    # implementa; se prueban dos complementarios para que un bus que devuelve
    # siempre el mismo valor no pase.
    for nombre, off, mascara in ESCRIBIBLES:
        if nombre.startswith('R_TRAP') and not info.get('trap'):
            # Sin el trapecio (CAPS bit 2) sus registros no existen: leen cero.
            r.append((f'{nombre} escribible', True, 'sin trapecio: no aplica'))
            continue
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

    for nombre, off in RESERVADOS:
        previo = mca.r32(off)
        try:
            mca.w32(off, 0x5A5A)
            leido = mca.r32(off)
        finally:
            mca.w32(off, previo)
        r.append((f'reservado {nombre}', leido == 0,
                  'lee 0' if leido == 0 else
                  f'retiene {leido:#x}: el mapa no es el MCA2'))

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
    ap.add_argument('--forzar-parte', action='store_true',
                    help='programar aunque el bitstream sea de otro Zynq '
                         '(deja el FPGA manager trabado: no hay razón buena)')
    args = ap.parse_args(argv)

    if args.cargar:
        # Import acá y no arriba: fpga.py toca /sys y sólo tiene sentido en la
        # placa, así que importarlo siempre rompería el test offline.
        from API.fpga import (load_bitstream, modelo_de_placa, parte_declarada)
        parte, modelo = parte_declarada(args.bitstream), modelo_de_placa()
        print(f'programando la PL con {args.bitstream} ...')
        print(f'  bitstream para {parte or "parte desconocida"} · '
              f'placa {modelo or "modelo desconocido"}')
        try:
            load_bitstream(args.bitstream, verbose=True,
                           forzar_parte=args.forzar_parte)
        except RuntimeError as e:
            # Sin traceback: esto es una herramienta de línea de comandos y el
            # usuario necesita saber QUÉ hacer, no dónde se levantó la
            # excepción. Y no se programó nada, que es lo importante.
            print(f'\n{e}')
            print('\n  La PL quedó COMO ESTABA — no se escribió nada.')
            print(f'  Necesitás un bitstream compilado para tu placa ({modelo}).')
            return 3
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

    print(f'\nPLACA LISTA. MCA2 con {info["n_acc_max"]} ranuras, eje de '
          f'{info["n_channels"]} canales, trapecio '
          f'{"sí" if info.get("trap") else "no"}, {len(ESCRIBIBLES)} registros '
          f'y {len(RESERVADOS)} reservados verificados.')
    print('\nsiguiente paso — armar el disparo, sin el cual el MCA2 no mide:')
    print('  la pestaña Espectro de mcamon, o API.multitrigger.multitrigger_armar_mca')
    print('  (las campañas de caracterización hablan todavía el MCA1)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
