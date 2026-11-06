"""El `check()` de los tests estilo script le tiene que fallar a pytest.

Si el fixture de `software/conftest.py` deja de aplicar, `make verificar` pasa
aunque falle cualquier `check` de cualquier test: este archivo es el que lo ve.
"""

import pytest

FAILS = []


def check(nombre, ok, detalle=''):
    if not ok:
        FAILS.append(nombre)
    return ok


def test_una_comprobacion_fallada_lanza():
    with pytest.raises(AssertionError, match='a propósito — con detalle'):
        check('a propósito', False, 'con detalle')


def test_una_comprobacion_que_pasa_no_lanza_y_devuelve_lo_de_siempre():
    assert check('bien', True) is True
