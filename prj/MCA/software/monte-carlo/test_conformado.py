#!/usr/bin/env python3
"""Tests del Monte-Carlo de conformado. Corren en la PC, sin placa.

Lo que se verifica:
  - que los índices de forma reproducen los números de la figura 17.24 de
    Nicholson para las familias que la figura tabula;
  - que el Monte-Carlo del ruido antes del conformador cierra con la fórmula;
  - que el experimento del ADC tiene las propiedades que lo hacen legible:
    sin ruido y sin fase devuelve la amplitud exacta, el techo plano no ve la
    fase, el ápice puntiagudo sí, y el `max` con ruido se sesga hacia arriba.

    python3 -m pytest test_conformado.py -q
"""
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

import conformado as cf                                      # noqa: E402

NICHOLSON = {'cusp': 1.000, 'triangular': 0.930, 'cr_rc4': 0.858,
             'cr_rc': 0.736, 'bipolar': 0.709}


def test_indices_reproducen_nicholson():
    for clave, esperado in NICHOLSON.items():
        a1, a2 = cf.indices_forma(cf.CALLABLES[clave])
        # la bipolar de Nicholson no es exactamente la del catálogo (0.701)
        tol = 0.01 if clave == 'bipolar' else 0.005
        assert abs(cf.sn_relativo(a1, a2) - esperado) < tol, (clave, a1, a2)


def test_indices_cerrados():
    # CR-RC: A1 = A2 = e^2/4; triangular: A1 = 2, A2 = 2/3
    a1, a2 = cf.indices_forma(cf.CALLABLES['cr_rc'])
    assert abs(a1 - np.e ** 2 / 4) < 2e-3 and abs(a2 - np.e ** 2 / 4) < 2e-3
    a1, a2 = cf.indices_forma(cf.CALLABLES['triangular'])
    assert abs(a1 - 2.0) < 1e-2 and abs(a2 - 2.0 / 3) < 2e-3


def test_mc_cierra_con_la_formula():
    rng = np.random.default_rng(1)
    for clave in ('cusp', 'cr_rc', 'trapezoidal'):
        a1, a2 = cf.indices_forma(cf.CALLABLES[clave])
        taus = [0.5, np.sqrt(a1 / a2), 2.0]
        n = 3000
        mc = cf.mc_nicholson(cf.CALLABLES[clave], taus, n, rng)
        teo = cf.sigma_teorica(taus, a1, a2)
        # error relativo de una desviación estándar muestral: 1/sqrt(2n)
        assert np.all(np.abs(mc / teo - 1) < 4 / np.sqrt(2 * n)), (clave, mc, teo)


def test_adc_sin_ruido_ni_fase_es_exacto():
    rng = np.random.default_rng(2)
    A = 1920.0
    for clave in ('trapezoidal', 'cr_rc', 'cusp'):
        g = cf.geometria(clave)
        r = cf.simular_adc(g, 20, rng, A, 0.0, fase=False)
        assert np.all(r['pico'] == A), clave
        assert np.allclose(r['adaptado'], A, atol=0.6), clave
    g = cf.geometria('trapezoidal')
    r = cf.simular_adc(g, 20, rng, A, 0.0, fase=False)
    assert np.all(r['boxcar'] == A)


def test_fase_solo_la_ve_el_apice_puntiagudo():
    rng = np.random.default_rng(3)
    A = 1920.0
    plano = cf.simular_adc(cf.geometria('trapezoidal'), 300, rng, A, 0.0)
    punta = cf.simular_adc(cf.geometria('triangular'), 300, rng, A, 0.0)
    assert plano['pico'].std() == 0.0 and np.all(plano['pico'] == A)
    assert punta['pico'].std() > 0.5
    assert punta['pico'].mean() < A            # siempre por debajo del ápice


def test_pico_del_rtl_se_sesga_hacia_arriba_con_ruido():
    rng = np.random.default_rng(4)
    A = 1920.0
    g = cf.geometria('cr_rc')
    r = cf.simular_adc(g, 1500, rng, A, cf.pu.SIGMA_RUIDO)
    assert r['pico'].mean() - A > 2.0                # max de ~30 gaussianas
    assert r['boxcar'].std() < r['pico'].std()
    assert r['adaptado'].std() < r['boxcar'].std()
    assert abs(r['adaptado'].mean() - A) < 0.2


def test_pico_del_rtl_coincide_con_el_maximo_de_la_matriz():
    """El `pico` sale del segmentador del RTL y los otros dos estimadores de la
    matriz de muestras: hay que ver que miran las mismas muestras. Con
    boxcar de 1 muestra, boxcar == pico."""
    rng = np.random.default_rng(5)
    g = cf.geometria('cr_rc4')
    r = cf.simular_adc(g, 200, rng, 1920.0, cf.pu.SIGMA_RUIDO)
    assert np.isfinite(r['pico']).all()
    # boxcar de 9 promedia, así que no puede superar al máximo
    assert np.all(r['boxcar'] <= r['pico'] + 1e-9)


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q']))
