#!/usr/bin/env python3
"""`API/bench/bench_impl.py` y `comparar_bench.py` corren de punta a punta.

Contra FakeMCA, en la PC: lo que se prueba es el script (que mide lo que dice,
que el resumen tiene el esquema que lee el comparador, que la igualdad de los
bloques se calcula), no los tiempos, que en la PC no significan nada.

    python -m pytest API/tests/test_bench_impl.py -q
"""

import importlib.util
import json
import os

import numpy as np
import pytest

_BENCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'bench')


def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(
        nombre, os.path.join(_BENCH, nombre + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def corrida(tmp_path_factory):
    out = tmp_path_factory.mktemp('bench')
    bench = _cargar('bench_impl')
    assert bench.main(['--fake', '--presupuesto', '0.005', '--out', str(out)]) == 0
    with open(out / 'resumen.json') as f:
        return out, json.load(f)


def test_resumen_tiene_el_esquema(corrida):
    _, r = corrida
    e = r['entorno']
    assert e['formato'] == 1 and e['fake'] is True
    for clave in ('commit', 'machine', 'python', 'libmca_version', 'mca_caps',
                  'mca_widths', 'gc'):
        assert clave in e
    st = r['ops']['api.get_campo']['py']
    assert set(st) == {'mediana_us', 'p5_us', 'p95_us', 'max_us', 'reps'}
    assert st['reps'] >= 5 and st['p5_us'] <= st['mediana_us'] <= st['max_us']


def test_py_mide_bus_y_api(corrida):
    _, r = corrida
    for op in ('bus.r32', 'bus.w32', 'bus.read_words_h', 'api.spectrum',
               'api.counters', 'api.map2d'):
        assert 'py' in r['ops'][op], op
    # Sin --destructivo no se borra ni se reconfigura nada.
    assert 'api.clear' not in r['ops'] and 'api.configure' not in r['ops']


def test_c_bus_e_igualdad(corrida):
    _, r = corrida
    if 'c' in r['no_disponible']:
        pytest.skip(r['no_disponible']['c'])
    for op in ('bus.r32', 'bus.w32', 'bus.read_words_h'):
        assert 'c' in r['ops'][op], op
    assert r['igualdad']['bus.read_words_h']['iguales'] is True
    assert r['igualdad']['bus.read_words_h']['n'] == 1 << 14


def test_crudos_coinciden_con_el_resumen(corrida):
    out, r = corrida
    crudos = np.load(out / 'resultados.npz')
    us = crudos['py/api.get_campo']
    assert us.size == r['ops']['api.get_campo']['py']['reps']
    assert np.median(us) == pytest.approx(r['ops']['api.get_campo']['py']['mediana_us'])


def test_comparar_una_y_dos(corrida, capsys):
    out, _ = corrida
    comp = _cargar('comparar_bench')
    assert comp.main([str(out)]) == 0
    assert 'api.spectrum' in capsys.readouterr().out
    assert comp.main([str(out), str(out)]) == 0
    salida = capsys.readouterr().out
    assert 'aviso' not in salida                    # mismo entorno: sin avisos
    assert '1.00' in salida


@pytest.fixture(scope='module')
def corrida_shm(tmp_path_factory):
    out = tmp_path_factory.mktemp('bench_shm')
    bench = _cargar('bench_impl')
    assert bench.main(['--shm', '--presupuesto', '0.005', '--out', str(out)]) == 0
    with open(out / 'resumen.json') as f:
        return out, json.load(f)


def test_shm_mide_las_dos_sobre_el_mismo_fichero(corrida_shm):
    """--shm: py por mmap, c por el backend devmem de libmca, sin PL."""
    out, r = corrida_shm
    if 'c' in r['no_disponible']:
        pytest.skip(r['no_disponible']['c'])
    e = r['entorno']
    assert e['medio'] == 'shm' and e['fake'] is False
    assert e['bitstream_programado'] is None and e['mca_widths']['h_aw'] == 13
    for op in ('bus.r32', 'api.get_campo', 'api.counters', 'api.spectrum',
               'api.configure', 'api.clear', 'api.acquire0'):
        assert {'py', 'c'} <= set(r['ops'][op]), op
    assert 'c_puro' in r['no_disponible']
    # las aperturas tienen cuentas: la igualdad compara algo
    for k in ('bus.read_words_h', 'bus.read_words_2d'):
        assert r['igualdad'][k]['iguales'] is True and r['igualdad'][k]['suma'] > 0
    # el fichero se borra
    assert not any(n.startswith('bench_impl_mca_')
                   for n in os.listdir('/dev/shm' if os.path.isdir('/dev/shm')
                                       else '/tmp'))


def test_comparar_avisa_si_cambia_el_medio(corrida, corrida_shm, capsys):
    comp = _cargar('comparar_bench')
    assert comp.main([str(corrida_shm[0])]) == 0
    assert 'SHM' in capsys.readouterr().out
    assert comp.main([str(corrida[0]), str(corrida_shm[0])]) == 0
    assert 'aviso: medio distinto' in capsys.readouterr().out


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
