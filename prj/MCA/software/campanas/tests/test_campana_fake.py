#!/usr/bin/env python3
"""Cada experimento de testbench_mca corre de punta a punta contra el MCA2 simulado.

Sin placa no se puede saber si un experimento MIDE bien, pero sí que usa bien
la API: que cada llamada al MCA y al disparo exista con esos argumentos, que
cada clave de contador que lee esté, que guarde su .npz y que `plot_all` lo
grafique. Es lo que atrapa un port a medias del MCA1 al MCA2 (un `thr` que ya
no existe, un `h_shift` que nadie guarda), que de otro modo saltaría recién en
la placa, a mitad de una campaña.

Los sustitutos son los del servidor en `--fake` (`API/mca_remote.py`):
`FakeMCA` (el modelo de registros del MCA2, corriendo el código de C de
libmca), `FakeOsc` y `FakeMtRegion` para el disparo. El generador es un doble
que acepta todo y rechaza la modulación AM, para que la DNL vaya por la
recarga del ARB. Los tiempos son cortos: los números no significan nada.

    python3 -m pytest campanas/tests/test_campana_fake.py -q
"""

import os
import sys
import time

import numpy as np
import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(_AQUI))

import testbench_mca as tb                                   # noqa: E402

FakeMCA = pytest.importorskip('API.mca_remote').FakeMCA
from API.mca_remote import FakeMtRegion, FakeOsc             # noqa: E402


class GenFalso:
    """Acepta cualquier comando; la modulación AM la rechaza, como el DG4162."""

    id = 'RIGOL falso'

    def __getattr__(self, nombre):
        return lambda *a, **k: None

    def query(self, q):
        return '0'

    def set_am_noise(self, *a, **k):
        raise RuntimeError('este firmware no tiene AM por ruido')

    def clear_errors(self):
        return []


# Cada experimento con parámetros que lo hacen corto pero recorren sus ramas.
CORTOS = {
    'single_peak': dict(seconds=0.05),
    'sweep_amplitude': dict(amps=[0.2, 0.5, 0.8], seconds=0.05),
    'formas_inl': dict(familias=('cr_rc', 'cr'), amps=[0.3, 0.6, 0.9], seconds=0.05),
    'dnl': dict(seconds=0.2, reload_s=0.05, mode='auto'),
    'compare_estimators': dict(widths_s=(1e-6, 2e-6), seconds=0.05),
    # FakeMCA dispara a su propia tasa, no a la del generador: pidiendo ésa,
    # la guarda de `cross` da los puntos por válidos y se recorre el análisis.
    'sweep_rate': dict(rates=[2e4, 2e4, 2e4], seconds=0.2, n_accs=(4,)),
    'sweep_rate_poisson': dict(rates=[2e4, 1e5], seconds=0.2, chunk_s=0.1,
                               n_accs=(1, 4)),
    'pulse_pair': dict(gaps_s=[1e-6, 1e-5], seconds=0.05, n_accs=(1, 4)),
    'sweep_threshold': dict(thrs=[100, 600, 2000], seconds=0.05, seconds_ruido=0.05),
    'psd_fom': dict(seconds=0.1),
    'baseline_k': dict(ks=(9, 12), seconds=0.05),
    'cross_check': dict(seconds=0.05),
    'sweep_gate': dict(largas=[256, 384], seconds=0.05),
    'sweep_gate_espectro': dict(amps=[0.3, 0.9], largas=(256, 384), seconds=0.05),
}
# Lo que cada uno guarda (los que no guardan nada si no hay eventos, aparte).
NPZ = {'single_peak': 'single_peak', 'sweep_amplitude': 'sweep_amplitude',
       'formas_inl': 'formas_inl', 'compare_estimators': 'compare_estimators',
       'sweep_rate': 'sweep_rate', 'sweep_rate_poisson': 'sweep_rate_poisson',
       'pulse_pair': 'pulse_pair', 'sweep_threshold': 'sweep_threshold',
       'psd_fom': 'psd_fom', 'baseline_k': 'sweep_baseline_k',
       'cross_check': 'cross_check', 'sweep_gate': 'sweep_gate',
       'sweep_gate_espectro': 'sweep_gate_espectro'}


@pytest.fixture(scope='module')
def banco(tmp_path_factory):
    out = tmp_path_factory.mktemp('campana')
    try:
        mca = FakeMCA(h_aw=13, h2_aw=7, psd_aw=6, rate_hz=2e4, centro=3000.0,
                      sigma=20.0)
    except OSError as e:                                     # libmca sin compilar
        pytest.skip(f'FakeMCA necesita libmca: {e}')
    osc = FakeOsc()
    tb._HW.update(osc=osc, mtr=FakeMtRegion(osc=osc), ch=0, disparo=dict(tb.DISPARO))
    tb.restaurar_disparo()
    # Las esperas de la campaña (asentar el generador, la línea de base a mitad
    # de corrida) no hacen falta contra el simulado; la adquisición de C sí
    # espera lo que se le pide.
    dormir = time.sleep
    tb.time.sleep = lambda s: dormir(min(s, 0.02))
    yield mca, GenFalso(), str(out)
    tb.time.sleep = dormir
    mca.close()


# Los de la tabla de la CLI más los que se llaman sólo desde los run_*.
FUNCIONES = {**tb.TESTS, 'sweep_rate_poisson': tb.sweep_rate_poisson}


def test_la_tabla_de_tests_esta_completa():
    assert set(CORTOS) == set(FUNCIONES), sorted(set(FUNCIONES) ^ set(CORTOS))


@pytest.mark.parametrize('nombre', list(CORTOS))
def test_el_experimento_corre_y_guarda(banco, nombre):
    mca, gen, out = banco
    FUNCIONES[nombre](mca, gen, ch=1, outdir=out, **CORTOS[nombre])
    if nombre in NPZ:
        p = os.path.join(out, f'{NPZ[nombre]}.npz')
        assert os.path.isfile(p), f'{nombre} no guardó {p}'
        d = np.load(p)
        assert str(d['mapa']) == 'MCA2'
    # el disparo vuelve siempre al de la campaña
    assert tb._HW['disparo'] == tb.DISPARO


def test_plot_all_grafica_lo_medido(banco):
    _, _, out = banco
    tb.plot_all(out)
    pngs = {f for f in os.listdir(out) if f.endswith('.png')}
    for esperado in ('single_peak.png', 'throughput.png', 'poisson_loss.png',
                     'pulse_pair.png', 'sweep_gate.png', 'gate_espectro.png'):
        assert esperado in pngs, f'falta {esperado}: {sorted(pngs)}'


def test_escala_de_canales_de_los_dos_mapas():
    """cuentas_por_canal lee un .npz del MCA1 (h_shift) y uno del MCA2 (zoom)."""
    class Npz(dict):
        @property
        def files(self):
            return list(self)
    viejo = Npz(h_shift=np.array(1))
    nuevo = Npz(mapa=np.array('MCA2'), h_aw=np.array(13), zoom_1d=np.array([0, 0]))
    assert tb.cuentas_por_canal(viejo, 'pico') == 2.0
    assert tb.cuentas_por_canal(viejo, 'carga', 5) == 32.0
    assert tb.cuentas_por_canal(nuevo, 'pico') == 2.0        # 8 de feature, 4 por cuenta
    assert tb.cuentas_por_canal(nuevo, 'carga', 5) == 8.0 * 32


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
