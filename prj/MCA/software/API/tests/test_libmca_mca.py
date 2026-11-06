#!/usr/bin/env python3
"""El binding del MCA sobre libmca: tablas, tipos y los handles que no son /dev/mem.

`test_libmca_equivalencia.py` prueba que C hace lo mismo que Python. Esto
prueba lo que conecta los dos lados y que una equivalencia no ve:

    - que el mapa de registros y la tabla de campos de C (mca_regs.h) son los
      de API/mca.py, uno por uno: divergir sería escribir un campo en el
      registro de otro
    - que los nombres de feature son los mismos
    - que FakeMCA corre la lógica de C contra su modelo Python
    - que una excepción del modelo sale intacta a través de C
    - que `MCA(None, ...)` sin r32/w32 propios es un error y no una recursión

    python -m pytest API/tests/test_libmca_mca.py -q
"""

import ctypes
import time

import numpy as np
import pytest

from API import _libmca

if not _libmca.disponible():
    pytest.skip(f'libmca no está compilada ({_libmca.motivo()}): make -C libmca',
                allow_module_level=True)

import API.mca as A                                                 # noqa: E402
from API.mca_remote import FakeMCA                                  # noqa: E402

LIB = A._cargar()

# Los campos cuyo setter de Python era `1 if v else 0`: en C son BANDERA.
BANDERAS = {'bl_auto', 'amp_src', 'gate_mode', 'channel', 'rearm_mode',
            'pub_mode', 'discr_en', 'discr_ext', 'keep_if_full'}


def test_tabla_de_campos_es_campos():
    n = LIB.mca_field_count()
    c = [LIB.mca_field_info(i).contents for i in range(n)]
    assert [f.nombre.decode() for f in c] == list(A._CAMPOS), \
        'mismo conjunto Y mismo orden: es el orden de mca_get_config'
    for f in c:
        nombre = f.nombre.decode()
        assert (f.offset, f.shift, f.mascara) == A._CAMPOS[nombre], nombre
        assert bool(f.bandera) == (nombre in BANDERAS), nombre
    assert not LIB.mca_field_info(n)


def test_mapa_de_registros_es_el_de_python():
    regs = {LIB.mca_reg_info(i).contents.nombre.decode():
            LIB.mca_reg_info(i).contents.offset
            for i in range(LIB.mca_reg_count())}
    py = {n: getattr(A, n) for n in dir(A)
          if n.startswith('R_') and isinstance(getattr(A, n), int)}
    assert regs == py


def test_features_son_las_mismas():
    for nombre, idx in A.FEATURES.items():
        i = ctypes.c_int32()
        assert LIB.mca_feature_from_name(nombre.encode(), ctypes.byref(i)) == 0
        assert i.value == idx
        assert LIB.mca_feature_name(idx).decode() == nombre
    assert LIB.mca_feature_name(len(A.FEATURES)) is None


def test_structs_miden_lo_mismo():
    for tipo, py in (('mca_config_t', A._Config), ('mca_counters_t', A._Counters),
                     ('mca_info_t', A._Info), ('mca_last_event_t', A._LastEvent)):
        assert LIB.mca_sizeof(tipo.encode()) == ctypes.sizeof(py), tipo


def test_config_default_es_la_firma_de_configure():
    # mca_config_default (C) y los defaults de MCA.configure (Python) son la
    # misma lista escrita dos veces: que no se desincronicen.
    c = A._Config()
    LIB.mca_config_default(ctypes.byref(c))
    import inspect
    p = inspect.signature(A.MCA.configure).parameters
    for nombre in ('baseline', 'bl_k', 'bl_holdoff', 'amp_min', 'amp_max',
                   'q_shift', 'dec', 'gate_short', 'gate_long', 'n_acc',
                   'pre_dly', 'trap_k', 'trap_m', 'trap_mq', 'trap_off',
                   'trap_lw', 'trap_sh'):
        assert getattr(c, nombre) == p[nombre].default, nombre
    for nombre in ('bl_auto', 'amp_src', 'channel', 'verify', 'keep_if_full'):
        assert bool(getattr(c, nombre)) == bool(p[nombre].default), nombre
    # Y la de la referencia del MCA2 es la misma firma.
    import API.ref_py.mca2 as R
    assert inspect.signature(R.MCA.configure) == inspect.signature(A.MCA.configure)
    assert c.sel_1d == c.sel_2dx == c.sel_2dy == A._F_DEFAULT
    assert c.discr_en == 0


def test_fake_mca_corre_la_logica_de_c():
    f = FakeMCA(rate_hz=20000.0)
    try:
        assert f.impl == 'fake' and f._via == 'c' and f._c
        A.mca_configure(f, n_acc=4, amp_min=0)
        A.mca_start(f)
        time.sleep(0.05)
        A.mca_stop(f)
        hist = A.mca_read_histogram(f)
        cnt = A.mca_read_counters(f)
        assert hist.dtype == np.uint32 and hist.sum() > 0
        assert cnt['total'] >= cnt['accepted'] == hist.sum()
        assert A.mca_read_map2d(f).shape == (1 << f.h2_aw, 1 << f.psd_aw)
        # El clear pasa por C y llega al modelo (bit autolimpiante de R_CTRL).
        A.mca_clear(f)
        assert A.mca_read_histogram(f).sum() == 0
        assert A.mca_get_metadata(f)['api_impl'] == 'fake'
    finally:
        f.close()


def test_excepcion_del_modelo_sale_intacta():
    class Roto(FakeMCA):
        def r32(self, off):
            if off == A.R_N_ACC:
                raise ConnectionError('se cayó el modelo')
            return super().r32(off)

    h = Roto()
    try:
        with pytest.raises(ConnectionError, match='se cayó'):
            A.mca_get_n_acc(h)
        # Y no queda pegada: lo próximo anda.
        assert A.mca_get_pre_dly(h) == 11
    finally:
        h.close()


def test_mca_none_sin_r32_propio_es_error():
    with pytest.raises(TypeError, match='redefina'):
        A.MCA(None, -1, 1, 14, 7, 6)


def test_mca_sobre_buffer_valida_rango():
    m = bytearray(A.MCA_SIZE)
    h = A.MCA(m, -1, A.CAP_HIST_H, 14, 7, 6)
    with pytest.raises(ValueError):
        h.r32(A.MCA_SIZE)
    with pytest.raises(ValueError, match='alineado'):
        h.r32(2)
    with pytest.raises(RuntimeError, match='motor 2D'):
        A.mca_read_map2d(h)
    h.close()
    h.close()                                   # idempotente


def test_libmca_version_en_el_handle():
    h = A.MCA(bytearray(A.MCA_SIZE), -1, 1, 14, 7, 6)
    assert h.libmca_version == _libmca.version()
    assert A.mca_get_metadata(h)['libmca_version'] == _libmca.version()
    h.close()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
