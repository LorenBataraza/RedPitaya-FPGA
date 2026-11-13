#!/usr/bin/env python3
"""El nivel 2 de libmca visto desde Python: `API/_libmca.py` y su `Bus`.

Cubre lo que el binding agrega sobre los tests de C (`make -C libmca test`):

    - que el .so carga y declara sus firmas
    - el backend por callbacks con funciones de Python, que es por donde
      FakeMCA se enchufa a la lógica de C
    - que una excepción lanzada adentro de un callback vuelve a salir, intacta,
      del lado de Python (y no como un acceso "exitoso" con basura)
    - la traducción de cada código de error a la excepción de la API de Python
    - el backend devmem sobre un fichero común: mmap, página y rango

Necesita el .so de esta máquina (`make -C libmca`); sin él, se saltea.

    python -m pytest API/tests/test_libmca_bus.py -q
"""

import os
import tempfile

import numpy as np
import pytest

from API import _libmca as L

if not L.disponible():
    pytest.skip(f'libmca no está compilada ({L.motivo()}): make -C libmca',
                allow_module_level=True)


class Modelo:
    """64 registros y un contador de accesos, como lo vería un backend."""

    def __init__(self):
        self.reg = np.zeros(64, dtype=np.uint32)
        self.accesos = []

    def r32(self, off):
        self.accesos.append(('r', off))
        return int(self.reg[off >> 2])

    def w32(self, off, val):
        self.accesos.append(('w', off, val))
        self.reg[off >> 2] = val

    def read_words(self, off, n):
        self.accesos.append(('b', off, n))
        return self.reg[off >> 2:(off >> 2) + n]


def test_version_y_build():
    assert L.version().count('.') == 2
    assert 'fno-tree-vectorize' in L.build()


def test_callbacks_r32_w32():
    m = Modelo()
    with L.Bus.callbacks(m.r32, m.w32, size=4 * 64) as b:
        b.w32(0x10, 0xDEADBEEF)
        assert b.r32(0x10) == 0xDEADBEEF
        assert m.accesos == [('w', 0x10, 0xDEADBEEF), ('r', 0x10)]
        assert b.size == 256


def test_callbacks_bloque_sin_y_con_read_words():
    m = Modelo()
    m.reg[2:6] = [2, 3, 4, 5]
    with L.Bus.callbacks(m.r32, m.w32) as b:
        assert b.read_words(0x08, 4).tolist() == [2, 3, 4, 5]
        assert [a[0] for a in m.accesos] == ['r'] * 4      # n lecturas sueltas
    m.accesos.clear()
    with L.Bus.callbacks(m.r32, m.w32, m.read_words) as b:
        w = b.read_words(0x08, 4)
        assert w.dtype == np.uint32 and w.tolist() == [2, 3, 4, 5]
        assert m.accesos == [('b', 0x08, 4)]                # UNA llamada


def test_sondear_lee_el_mismo_registro_n_veces():
    """Un registro que avanza solo, como wp_cur: sondear lo lee n veces, siempre en
    el mismo offset, aunque haya un read_words propio (que es para bloques)."""
    m = Modelo()
    cuenta = iter(range(100, 200))

    def r32(off):
        m.accesos.append(('r', off))
        return next(cuenta)

    with L.Bus.callbacks(r32, m.w32, m.read_words, size=4 * 64) as b:
        v = b.sondear(0x18, 6)
        assert v.dtype == np.uint32 and v.tolist() == [100, 101, 102, 103, 104, 105]
        assert m.accesos == [('r', 0x18)] * 6
        with pytest.raises(ValueError, match='alineado'):
            b.sondear(0x19, 2)
        assert b.sondear(0x18, 0).size == 0


def test_validacion_es_del_bus_y_no_llega_al_backend():
    m = Modelo()
    with L.Bus.callbacks(m.r32, m.w32, size=4 * 64) as b:
        with pytest.raises(ValueError, match='alineado'):
            b.r32(0x11)
        with pytest.raises(ValueError, match='fuera de la region'):
            b.w32(0x100, 1)
        with pytest.raises(ValueError, match='fuera de la region'):
            b.read_words(0xF8, 4)
    assert m.accesos == []


def test_excepcion_en_callback_sale_intacta():
    class Roto(Exception):
        pass

    def r32(off):
        raise Roto(f'el socket se cayó leyendo {off:#x}')

    with L.Bus.callbacks(r32, lambda off, v: None) as b:
        with pytest.raises(Roto, match='0x40'):
            b.r32(0x40)
        # La excepción no queda pegada: el próximo error es el que corresponde.
        with pytest.raises(ValueError):
            b.r32(0x41)


def test_check_traduce_codigos():
    L.check(L.MCA_OK)
    with pytest.raises(TimeoutError):
        L.check(L.MCA_ETIMEOUT)
    with pytest.raises(L.LibMCAError) as e:
        L.check(L.MCA_ENOSYS, 'zoom')
    assert e.value.rc == L.MCA_ENOSYS and 'zoom' in str(e.value)

    class NoEsta(RuntimeError):
        pass
    with pytest.raises(NoEsta):
        L.check(L.MCA_ENOTPRESENT, excepciones={L.MCA_ENOTPRESENT: NoEsta})


def test_fichero_mmap_pagina_y_rango():
    pag = os.sysconf('SC_PAGESIZE')
    with tempfile.NamedTemporaryFile() as f:
        f.truncate(3 * pag)
        f.seek(pag // 2)
        f.write((0x4D434131).to_bytes(4, 'little'))         # "MCA1"
        f.flush()
        with L.Bus.archivo(f.name, pag // 2, pag) as b:
            assert b.r32(0) == 0x4D434131
            b.w32(8, 7)
            assert b.read_words(0, 3).tolist() == [0x4D434131, 0, 7]
            with pytest.raises(ValueError):
                b.r32(pag)
        f.seek(pag // 2 + 8)
        assert int.from_bytes(f.read(4), 'little') == 7      # llegó al fichero


def test_sin_permiso_es_oserror_con_errno():
    with pytest.raises(FileNotFoundError):
        L.Bus.archivo('/no/existe', 0, 4096)


def test_bus_cerrado():
    m = Modelo()
    b = L.Bus.callbacks(m.r32, m.w32)
    b.close()
    b.close()                                   # idempotente
    with pytest.raises(ValueError, match='cerrado'):
        b.r32(0)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
