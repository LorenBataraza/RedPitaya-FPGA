#!/usr/bin/env python3
"""API nueva de `API/mca.py`: accesores por campo y capa de guardado.

`test_compat_api.py` cubre que la superficie VIEJA no cambió; esto cubre lo que
el refactor AÑADIÓ, que no tiene baseline contra el que compararse:

    - los `mca_get_*` / `mca_set_*` por campo, y en particular el
      read-modify-write de los registros que empaquetan varios campos
    - `mca_get_metadata()`
    - el round-trip de los tres formatos de guardado

Corre en la PC, sin placa: usa el `FakeMmap` de `gen_compat_baseline`.

    python API/tests/test_api_mca.py
    python -m pytest API/tests/test_api_mca.py -q
"""

import os
import sys
import tempfile

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)

from gen_compat_baseline import FakeMmap                           # noqa: E402
import API.mca as A                                                # noqa: E402


def _handle():
    """Un MCA sobre memoria falsa, con magic/caps/widths precargados."""
    m = FakeMmap(A.MCA_SIZE)
    m.poke(A.R_MAGIC, A.MAGIC)
    m.poke(A.R_CAPS, A.CAP_HIST_H | A.CAP_HIST_H_PSD)
    m.poke(A.R_WIDTHS, (8 << 16) | (8 << 8) | 14)      # psd_aw, h2_aw, h_aw
    return m, A.MCA(m, -1, A.CAP_HIST_H | A.CAP_HIST_H_PSD, 14, 8, 8)


# Registros que empaquetan varios campos, con el layout que publica el RTL
# (mca_top.sv:340,346,351). Es el caso que el read-modify-write tiene que
# respetar: escribir `bl_k` sin borrar `bl_holdoff`.
EMPAQUETADOS = [
    ('R_BL_CTRL',  [('bl_holdoff', 0xBEEF), ('bl_k', 13), ('bl_auto', 1)]),
    ('R_AMP_SRC',  [('q_shift', 0x15), ('amp_src', 1)]),
    ('R_GATE_LEN', [('gate_long', 0x1234), ('gate_short', 0x5678)]),
]


def test_rmw_no_pisa_campos_vecinos():
    """Poner un campo de un registro compartido no debe borrar los otros.

    Sin read-modify-write, `mca_set_bl_k(h, 13)` escribiría la palabra entera y
    dejaría `bl_holdoff` en cero — en la placa eso cambia el comportamiento del
    seguidor de línea de base sin que nada falle ni avise.
    """
    for nombre, campos in EMPAQUETADOS:
        _, h = _handle()
        for campo, valor in campos:            # cada uno por separado, en orden
            getattr(A, f'mca_set_{campo}')(h, valor)
        for campo, valor in campos:            # y todos siguen en pie
            got = int(getattr(A, f'mca_get_{campo}')(h))
            assert got == valor, (
                f'{nombre}: tras escribir los {len(campos)} campos, {campo} '
                f'vale {got} y debería valer {valor} — el RMW pisó un vecino')


def test_set_channel_preserva_run():
    """`channel` es el bit 8 de R_CTRL y `run` el bit 0: comparten registro."""
    _, h = _handle()
    A.mca_start(h)
    assert A.mca_get_running(h)
    A.mca_set_channel(h, 1)
    assert A.mca_get_running(h), 'set_channel apagó la acumulación'
    assert A.mca_get_channel(h) == 1


def test_start_stop_clear():
    _, h = _handle()
    assert not A.mca_get_running(h)
    A.mca_start(h)
    assert A.mca_get_running(h)
    A.mca_stop(h)
    assert not A.mca_get_running(h)
    A.mca_clear(h)                    # con STATUS=0 el clear_busy sale enseguida


def test_get_config_cubre_todos_los_campos():
    _, h = _handle()
    cfg = A.mca_get_config(h)
    assert set(cfg) == set(A._CAMPOS), 'mca_get_config no devuelve todos los campos'


def test_metadata_lleva_config_contadores_y_geometria():
    _, h = _handle()
    A.mca_set_thr(h, 317)
    meta = A.mca_get_metadata(h)
    for clave in ('schema_version', 'thr', 'gate_long', 'h_aw', 'total',
                  'livetime_s', 'n_channels', 'adc_cnt_per_V', 't_wall'):
        assert clave in meta, f'falta {clave!r} en la metadata'
    assert meta['thr'] == 317
    assert meta['n_channels'] == 1 << 14


def test_roundtrip_de_los_tres_formatos():
    """El formato es una decisión de almacenamiento: los tres tienen que
    devolver el mismo histograma y la misma metadata."""
    _, h = _handle()
    A.mca_set_thr(h, 317)
    A.mca_set_gate_long(h, 400)
    meta = A.mca_get_metadata(h)
    hist = (np.arange(256, dtype=np.uint32) * 7) % 1000

    with tempfile.TemporaryDirectory() as d:
        escritores = (('csv',  A.mca_write_file_histogram),
                      ('npz',  A.mca_save_file_binary),
                      ('json', A.mca_save_file_json))
        for ext, escribir in escritores:
            ruta = os.path.join(d, 'espectro.' + ext)
            escribir(hist, ruta, meta=meta)
            leido, meta2 = A.mca_load_file(ruta)

            assert np.array_equal(leido, hist), f'{ext}: el histograma no vuelve igual'
            for clave in ('thr', 'gate_long', 'schema_version', 'n_channels'):
                assert int(meta2[clave]) == int(meta[clave]), (
                    f'{ext}: la metadata {clave!r} volvió como {meta2[clave]!r}')


def test_load_file_rechaza_formato_desconocido():
    try:
        A.mca_load_file('/tmp/no_existe.bin')
    except ValueError as e:
        assert '.bin' in str(e)
    else:
        raise AssertionError('mca_load_file aceptó una extensión desconocida')


def main():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f'  ok    {fn.__name__}')
        except Exception as e:
            fallos += 1
            print(f'  FALLO {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\n{len(pruebas) - fallos}/{len(pruebas)} pruebas OK')
    return 1 if fallos else 0


if __name__ == '__main__':
    raise SystemExit(main())
