#!/usr/bin/env python3
"""El banco de trapecios desde la API: la receta, el modelo y los avisos.

Que C y la referencia hagan lo mismo lo prueba `test_libmca_equivalencia.py`.
Acá va lo que importa de cara al usuario:

  - `mca_banco_config` da los registros que usó la etapa `banco_rtl` de
    `test_mca2_placa.py`, y la compuerta que entra (112, no 104);
  - `mca_configure` no deja rastros del banco anterior;
  - lo que el RTL haría en silencio es un error ANTES de escribir;
  - los avisos se pueden leer, y sólo miran las formas en uso;
  - un .so viejo da un mensaje que dice qué hacer.

    python -m pytest API/tests/test_banco_api.py -q
"""

import math
import os
import importlib.util

import pytest

from API import _libmca

if not _libmca.disponible():
    pytest.skip(f'libmca no está compilada ({_libmca.motivo()}): make -C libmca',
                allow_module_level=True)

import API.mca as A                                                 # noqa: E402
from API.mca_remote import FakeMCA                                  # noqa: E402

_PLACA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'placa',
                      'test_mca2_placa.py')


@pytest.fixture()
def h():
    m = FakeMCA(trap=True)
    yield m
    m.close()


def test_la_receta_da_los_registros_de_la_etapa_de_placa():
    """La misma cuenta que `etapa_banco_rtl`, escrita con registros crudos."""
    spec = importlib.util.spec_from_file_location('test_mca2_placa', _PLACA)
    placa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(placa)
    assert A.BANCO_PZ == placa.BANCO_PZ

    mq, pre = 3992, 16
    kw = A.mca_banco_config(mq, pre_dly=pre)
    assert kw['n_formas'] == len(A.BANCO_PZ) == 3 and kw['trap_mq'] == mq and kw['pre_dly'] == pre
    for f, (k, m, lw, c, an, de) in enumerate(placa.BANCO_PZ):
        pref = 'trap_' if f == 0 else f'forma{f}_'
        sh = round(math.log2(16 * k * (1 + mq / 16.0) / 8))
        assert (kw[pref + 'k'], kw[pref + 'm'], kw[pref + 'lw']) == (k, m, lw)
        assert (kw[pref + 'off'], kw[pref + 'sh']) == (c + pre + 2, sh)
        assert (kw[pref + 'antes'], kw[pref + 'despues']) == (an, de)


def test_la_compuerta_de_la_receta_es_la_que_entra(h):
    # memoria del error: con 104 la forma 0 da siempre cero
    assert A.mca_banco_config(3992)['gate_long'] == 112
    assert A.mca_banco_config(3992, pre_dly=24)['gate_long'] == 120
    A.mca_configure(h, n_acc=4, **A.mca_banco_config(3992))
    assert A.mca_get_formas_ok(h) == [True] * len(A.BANCO_PZ) and A.mca_get_umbr_ok(h)
    with pytest.raises(ValueError, match='la ventana termina en 111'):
        A.mca_configure(h, n_acc=4, **A.mca_banco_config(3992, gate_long=104))


def test_la_receta_trae_pre_dly_para_que_no_se_pase_otro(h):
    with pytest.raises(TypeError):
        A.mca_configure(h, pre_dly=20, **A.mca_banco_config(3992))


def test_un_k_que_no_es_potencia_de_2_se_rechaza(h):
    """Por la fórmula, k = 48 queda al 75 % de la altura de k = 64: el pico se
    parte en dos sin ningún otro síntoma."""
    formas = ((64, 48, 4, 69, 97, 96), (48, 24, 3, 29, 49, 48))
    kw = A.mca_banco_config(3992, formas=formas)
    assert kw['trap_sh'] == kw['forma1_sh'] == 15
    with pytest.raises(ValueError, match='parten el pico'):
        A.mca_configure(h, **kw)


def test_configure_deja_el_reset_del_banco(h):
    A.mca_configure(h, n_acc=4, **A.mca_banco_config(3885))
    assert A.mca_get_n_formas(h) == len(A.BANCO_PZ) and A.mca_get_trap_mq(h) == 3885
    A.mca_configure(h)
    c = A.mca_get_config(h)
    assert c['n_formas'] == 1 and c['trap_mq'] == 0
    assert (c['trap_k'], c['trap_m'], c['trap_off'], c['trap_lw'], c['trap_sh']) == (64, 32, 72, 4, 7)
    assert (c['forma1_k'], c['forma2_k'], c['forma3_k']) == (32, 16, 8)
    assert c['trap_antes'] == c['trap_despues'] == c['forma3_despues'] == 0


def test_los_defaults_de_configure_son_el_reset_del_modelo(h):
    """El reset del RTL, tal como lo copió FakeMCA de mca_top.sv."""
    reset = A.mca_get_config(h)
    A.mca_configure(h)
    c = A.mca_get_config(h)
    for n in A._BANCO_RESET:
        assert c[n] == reset[n], n


def test_los_setters_validan(h):
    for nombre, v in (('n_formas', 0), ('n_formas', 5), ('forma1_k', 0), ('forma3_k', 1024)):
        with pytest.raises(ValueError):
            getattr(A, f'mca_set_{nombre}')(h, v)
    A.mca_set_n_formas(h, 4)
    assert A.mca_get_n_formas(h) == 4


def test_los_avisos_solo_miran_las_formas_en_uso(h):
    # con el banco de 4 formas: la placa falsa trae N_FORMAS = 4
    A.mca_configure(h, n_acc=4, **A.mca_banco_config(3992, formas=A.BANCO_PZ_4))
    assert A.mca_get_n_formas_max(h) == 4
    # Con los setters sueltos se puede romper lo que configure no deja: para eso
    # están los avisos.
    A.mca_set_forma2_off(h, 500)
    assert A.mca_get_formas_ok(h) == [True, True, False, True]
    A.mca_set_n_formas(h, 2)
    assert A.mca_get_formas_ok(h) == [True, True]
    A.mca_set_forma1_despues(h, 200)
    assert not A.mca_get_umbr_ok(h)
    A.mca_set_n_formas(h, 1)
    assert A.mca_get_umbr_ok(h)                      # la forma 1 ya no se usa


def test_sin_el_trapecio_no_hay_banco():
    h = FakeMCA()
    assert A.mca_get_n_formas_max(h) == 0
    assert A.mca_identify(h, verbose=False)['n_formas_max'] == 0
    A.mca_configure(h)                               # no falla: no lo toca
    with pytest.raises(ValueError):
        A.mca_configure(h, n_formas=2)
    h.close()
    h = FakeMCA(trap=True)
    assert A.mca_identify(h, verbose=False)['n_formas_max'] == 4
    h.close()


def test_un_so_viejo_dice_que_hacer():
    with pytest.raises(OSError, match='Recompilarla'):
        A._exigir_misma_tabla(len(A._CAMPOS) - 24)
    A._exigir_misma_tabla(len(A._CAMPOS))


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
