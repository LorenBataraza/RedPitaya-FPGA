"""`campanas/run_fidelidad_osc.py` sin placa: `medir --simulada` arma las capturas que
daría una placa sin errores, y `analizar` tiene que dar FIEL; cada error que se le
inyecta a una captura (una palabra, una marca de tiempo, una muestra de IN1) tiene que
dar NO FIEL, diciendo dónde. En los dos modos, digital (bit a bit contra el modelo) y
analógico (contra el canal de juguete medido).
"""
import json
import os
import shutil
import sys

import numpy as np
import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(_AQUI))                  # campanas/

import run_fidelidad_osc as F                                        # noqa: E402

# El pre-disparo de la BRAM tiene que tomar el arranque del generador (el primer pulso
# llega hasta 1099 ciclos después): así el FIR del canal no se queda sin historia.
CHICO = ['--n-ring', '300', '--pre-bram', '1500', '--post-bram', '900']


def _medir(d, *extra):
    assert F.main(['medir', str(d), '--simulada', *CHICO, *extra]) == 0


def _analizar(d):
    rc = F.main(['analizar', str(d)])
    with open(d / 'analisis.json') as f:
        return rc, json.load(f)


def _copia(origen, destino):
    shutil.copytree(origen, destino)
    return destino


def _tocar(d, archivo, clave, cambio):
    """Reescribe un arreglo de un .npz con `cambio(arreglo)`."""
    p = d / archivo
    z = dict(np.load(p))
    z[clave] = cambio(z[clave].copy())
    np.savez_compressed(p, **z)


@pytest.fixture(scope='module')
def digital(tmp_path_factory):
    d = tmp_path_factory.mktemp('digital')
    _medir(d)
    return d


@pytest.fixture(scope='module')
def analogico(tmp_path_factory):
    d = tmp_path_factory.mktemp('analogico')
    _medir(d, '--modo', 'analogico')
    return d


# -----------------------------------------------------------------------------
# El modo digital: bit a bit
# -----------------------------------------------------------------------------

def test_las_capturas_ideales_son_fieles(digital, tmp_path):
    rc, r = _analizar(_copia(digital, tmp_path / 'd'))
    assert rc == 0 and r['veredicto'] == 'fiel'
    g = r['ring']
    assert g['muestras_distintas'] == 0 and g['marcas_fuera'] == 0
    assert g['cuenta_cierra'] and g['drop_busy_igual'] and g['marcas_iguales_al_modelo']
    assert g['muestras'] > 0 and g['saturadas'] > 0 and g['negativas'] > 0
    assert r['bram_d_constante'] and len(r['bram']) == 4
    assert all(b['muestras_distintas'] == 0 for b in r['bram'])
    assert all(b['ceros_antes_del_arranque'] > 0 for b in r['bram'])


def test_una_palabra_mal_en_el_ring(digital, tmp_path):
    d = _copia(digital, tmp_path / 'd')

    def romper(w):
        w[7, 100] += 300
        return w
    _tocar(d, 'ring.npz', 'wave', romper)
    rc, r = _analizar(d)
    g = r['ring']
    assert rc == 1 and r['veredicto'] == 'NO FIEL'
    assert g['muestras_distintas'] == 1 and g['ventanas_con_error'] == 1
    assert g['primer_error']['ventana'] == 7 and g['primer_error']['muestra'] == 100


def test_una_marca_de_tiempo_corrida(digital, tmp_path):
    d = _copia(digital, tmp_path / 'd')

    def correr(ts):
        ts[5] += 1
        return ts
    _tocar(d, 'ring.npz', 'ts_hw', correr)
    rc, r = _analizar(d)
    assert rc == 1 and r['ring']['marcas_fuera'] == 1


def test_un_bit_mal_en_la_bram(digital, tmp_path):
    d = _copia(digital, tmp_path / 'd')

    def romper(b):
        b[500] ^= 1
        return b
    _tocar(d, 'bram_2.npz', 'buf', romper)
    rc, r = _analizar(d)
    assert rc == 1
    malos = [b for b in r['bram'] if b['muestras_distintas']]
    assert [b['nombre'] for b in malos] == ['poisson'] and malos[0]['muestras_distintas'] == 1
    assert malos[0]['primer_error']['muestra'] == 500


def test_un_buffer_corrido_cambia_la_posicion_del_disparo(digital, tmp_path):
    d = _copia(digital, tmp_path / 'd')
    _tocar(d, 'bram_0.npz', 'buf', lambda b: np.roll(b, 3))
    rc, r = _analizar(d)
    assert rc == 1 and not r['bram_d_constante']


# -----------------------------------------------------------------------------
# El modo analógico: contra el canal medido
# -----------------------------------------------------------------------------

def test_analogico_ideal_es_fiel(analogico, tmp_path):
    rc, r = _analizar(_copia(analogico, tmp_path / 'a'))
    assert rc == 0 and r['veredicto'] == 'fiel' and r['canal_problema'] is None
    assert r['canal']['ganancia'] == pytest.approx(0.97, rel=0.02)   # el de juguete
    assert r['ring']['residuo']['fuera'] == 0 and r['ring']['marcas_fuera'] == 0
    for b in r['bram']:
        assert b['muestras_distintas'] == 0                          # el lazo, bit a bit
        assert b['analogico']['fuera'] == 0


def test_analogico_ve_una_muestra_mal_de_in1(analogico, tmp_path):
    d = _copia(analogico, tmp_path / 'a')

    def romper(y):
        y[600] += 300
        return y
    _tocar(d, 'bram_0.npz', 'y0', romper)
    rc, r = _analizar(d)
    assert rc == 1 and r['bram'][0]['analogico']['fuera'] >= 1
    assert all(b['analogico']['fuera'] == 0 for b in r['bram'][1:])


def test_analogico_ve_una_palabra_mal_en_el_ring(analogico, tmp_path):
    d = _copia(analogico, tmp_path / 'a')

    def romper(w):
        w[20, 200] += 300
        return w
    _tocar(d, 'ring.npz', 'wave', romper)
    rc, r = _analizar(d)
    assert rc == 1 and r['ring']['veredicto'] == 'NO FIEL'
    assert r['ring']['ventanas_con_error'] == 1


def test_analogico_sin_coaxial_no_es_fiel(tmp_path):
    _medir(tmp_path, '--modo', 'analogico', '--rutas', 'bram', '--canal-sim', 'ganancia=0')
    rc, r = _analizar(tmp_path)
    assert rc == 1 and 'coaxial' in r['canal_problema']


# -----------------------------------------------------------------------------
# Las cuentas
# -----------------------------------------------------------------------------

def test_disparos_asg_y_la_captura_ocupada():
    assert F.disparos_asg([0, 1, 2, 3, 10, 12, 13]).tolist() == [0, 3, 10, 13]
    assert F.aceptados_captura([0, 5, 10, 20, 21], 10).tolist() == [0, 10, 20]
