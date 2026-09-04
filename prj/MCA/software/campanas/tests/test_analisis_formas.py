#!/usr/bin/env python3
"""Tests de `testbench_mca.analizar_formas()`. Corren en la PC, sin instrumento.

El analizador toma una campaña de INL vs familia de forma y separa lo que es
COMÚN a todas las familias —el generador y la INL estática del ADC— de lo
DIFERENCIAL, que es la única parte atribuible a que cambió la forma del pulso.
Acá se le dan campañas SINTÉTICAS con un diferencial conocido y se comprueba
que lo recupere, y que con diferencial cero diga que la INL no depende de la
forma en vez de encontrar estructura en el ruido.

Vivían dentro de `API/tests/test_formas_pulso.py`, pero su sujeto no es
`API/rigol_dg4162` sino el analizador de campañas. Estar allá los hacía pasar
de prestado: sólo funcionaban si otro test había puesto `campanas/` en
`sys.path` antes, así que `pytest API/tests` a secas los rompía.

    python3 test_analisis_formas.py
"""
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(_AQUI))   # campanas/, donde vive testbench_mca

import rigol_dg4162 as rg                                      # noqa: E402
import testbench_mca as tb                                     # noqa: E402

FAILS = []

WIDTH_S = 2e-6
RATE_HZ = 2e3
FAMILIAS = ('cr', 'cr_rc', 'cr_rc4', 'triangular', 'trapezoidal', 'bipolar')


def check(name, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {name}{("  " + extra) if extra else ""}')
    if not cond:
        FAILS.append(name)


def construir(familia, **kw):
    """Misma forma que usa `API/tests/test_formas_pulso.py`, que es el fichero
    del que salieron estos tests: la campaña sintética tiene que construirse
    con la MISMA onda que verifica aquél, o dejan de hablar de lo mismo."""
    return rg.shaped_train_wave(familia, WIDTH_S, RATE_HZ, n_pulses=1, **kw)




# --------------------------------------------------------------- 7

def _campana_sintetica(dif_por_familia, comun_mv=10.0, ruido_ch=0.15,
                       g_pico=3927.0, seed=3):
    """Arma un .npz como el de sweep_formas_inl, con la respuesta CONOCIDA.

    Se inyecta una no linealidad COMUN a todas las familias (que es lo que
    haria el generador) mas una DIFERENCIAL distinta por familia (que es lo que
    haria la cadena de medicion). El test comprueba que `analizar_formas` las
    separe: es la operacion de la que depende toda la conclusion del barrido, y
    con datos reales no hay forma de saber si esta bien hecha.
    """
    import mca_utils as mu

    rng = np.random.default_rng(seed)
    amps = np.linspace(0.1, 1.0, 12)
    fams = tuple(dif_por_familia)
    d = {'amps': amps, 'familias': np.array(fams),
         'estimadores': np.array(['pico', 'carga']), 'h_shift': np.array(0)}

    for f in fams:
        _, _, info = construir(f)
        ff = info['factor_forma']
        d[f'ok_{f}'] = np.array(True)
        d[f'factor_forma_{f}'] = np.array(ff)
        for est in ('pico', 'carga'):
            if est == 'pico':
                g, qs = g_pico, 0
            else:
                # Q_tot escala con el factor de forma, y el q_shift lo
                # reescala: es justo la combinacion que el analisis tiene que
                # saber deshacer.
                qbruto = g_pico * ff * 250
                qs = int(max(0, np.floor(np.log2(qbruto * amps.max() / 8000))))
                g = qbruto / 2 ** qs
            v = (amps + 1e-3 * comun_mv * np.sin(2 * np.pi * amps)
                 + dif_por_familia[f] * (amps - 0.55) ** 2 / 0.2)
            cen = g * v
            gg, off, resid, inl = mu.energy_calibration(cen, amps)
            _, _, resid2, _ = mu.energy_calibration(
                cen + rng.normal(0, ruido_ch, cen.size), amps)
            d[f'cen_{f}_{est}'] = cen
            d[f'fwhm_{f}_{est}'] = np.full(cen.size, 12.0)
            d[f'resid_{f}_{est}'] = resid
            d[f'resid_vuelta_{f}_{est}'] = resid2
            d[f'gain_{f}_{est}'] = np.array(gg)
            d[f'offset_{f}_{est}'] = np.array(off)
            d[f'inl_{f}_{est}'] = np.array(inl)
            d[f'qshift_{f}_{est}'] = np.array(qs)
    return d


def test_analisis_separa_comun_de_diferencial():
    print('\n[7] analizar_formas separa lo comun de lo diferencial')

    # Desviaciones respecto de la media: cr +0.00325, cr_rc4 -0.00375,
    # cr_rc -0.00075, triangular +0.00025, trapezoidal -0.00025, bipolar +0.00125.
    dif = {'cr_rc': 0.0, 'cr': 0.004, 'cr_rc4': -0.003,
           'triangular': 0.001, 'trapezoidal': 0.0005, 'bipolar': 0.002}
    r = tb.analizar_formas(_campana_sintetica(dif))['por_estimador']['pico']
    got = r['diferencial_por_familia_mv']

    medio = np.mean(list(dif.values()))
    esperado = {f: abs(v - medio) for f, v in dif.items()}
    # Se comparan RELACIONES y no valores absolutos: el ajuste lineal de
    # energy_calibration absorbe parte de la parabola inyectada, asi que la
    # escala global se reduce por un factor comun a todas las familias.
    ref = 'cr'
    for f in dif:
        e = esperado[f] / esperado[ref]
        g = got[f] / got[ref]
        check(f'{f}: diferencial relativo {g:.4f} (esperado {e:.4f})',
              abs(g - e) < 1e-6)

    # Triangular y trapezoidal se inyectaron simetricas respecto de la media:
    # tienen que salir iguales.
    check('desviaciones opuestas dan diferenciales iguales',
          abs(got['triangular'] - got['trapezoidal']) < 1e-9)

    check('el comun recupera la amplitud inyectada (10 mV)',
          8.0 < r['residuo_comun_max_mv'] < 10.5,
          f'({r["residuo_comun_max_mv"]:.2f} mV)')
    check('el diferencial queda por encima del piso de ruido',
          r['residuo_diferencial_max_mv'] > 10 * np.nanmedian(
              list(r['piso_ida_vuelta_mv'].values())))
    check('veredicto: componente dependiente de la forma',
          'depend' in r['veredicto'], f'({r["veredicto"][:60]}...)')


def test_analisis_sin_diferencial():
    print('\n[8] sin diferencial inyectado, el veredicto es "no depende"')

    d = _campana_sintetica({f: 0.0 for f in FAMILIAS}, ruido_ch=0.15)
    r = tb.analizar_formas(d)['por_estimador']['pico']
    check('diferencial ~0', r['residuo_diferencial_max_mv'] < 1e-6,
          f'({r["residuo_diferencial_max_mv"]:.2e} mV)')
    check('correlacion entre familias = 1',
          r['correlacion_min_entre_familias'] > 0.9999)
    check('ganancia relativa = 1 para todas',
          all(abs(v - 1) < 1e-9 for v in r['ganancia_relativa'].values()))
    check('veredicto: la INL no depende de la forma',
          'NO depende' in r['veredicto'], f'({r["veredicto"][:50]}...)')


def test_pico_vs_carga_deshace_el_qshift():
    print('\n[9] el grafico pico-vs-carga recupera el factor de forma')

    # Cada familia se sintetizo con un q_shift distinto (sale del autoescalado).
    # Si el analisis no lo deshiciera, la pendiente medida NO reproduciria el
    # factor de forma y el grafico no diria nada sobre la geometria del pulso.
    pv = tb.analizar_formas(
        _campana_sintetica({f: 0.0 for f in FAMILIAS}))['pico_vs_carga']
    qs = {f: int(_campana_sintetica({f: 0.0 for f in FAMILIAS})[f'qshift_{f}_carga'])
          for f in FAMILIAS}
    check('los q_shift sintetizados NO son todos iguales',
          len(set(qs.values())) > 1, f'({qs})')
    for f in FAMILIAS:
        p, e = pv['pendiente_relativa'][f], pv['factor_forma_relativo'][f]
        check(f'{f}: pendiente relativa {p:.4f} = factor de forma {e:.4f}',
              abs(p / e - 1) < 1e-9)


def main():
    test_analisis_separa_comun_de_diferencial()
    test_analisis_sin_diferencial()
    test_pico_vs_carga_deshace_el_qshift()
    print('\nRESULT:', 'PASS' if not FAILS else f'FAIL ({len(FAILS)}): {FAILS}')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
