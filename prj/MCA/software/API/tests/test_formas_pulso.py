#!/usr/bin/env python3
"""Tests de las familias de forma de Knoll. Corren en la PC, sin instrumento.

El barrido de INL vs forma (`testbench_mca.sweep_formas_inl`) descansa entero
sobre una hipotesis: que entre familia y familia lo UNICO que cambia es la
forma del pulso. Si el FWHM, la frecuencia de repeticion o la tasa de muestreo
del ARB se corren de una familia a la otra, la comparacion no mide robustez
frente a la forma sino frente a esas otras variables, y no hay manera de darse
cuenta mirando los datos medidos.

Asi que eso es lo que se verifica aca, sobre la onda REAL que sale del
constructor y no sobre los numeros que reporta `info`:

  1. el FWHM medido coincide con el pedido, para las seis familias;
  2. con n_pulses=1 la frecuencia y la tasa de muestreo son identicas entre
     familias (el invariante del barrido);
  3. la forma es apta para load_arb (normalizada, sin escalon al repetir);
  4. el factor de forma sale en el orden analitico esperado -- es la pendiente
     que despues tiene que aparecer en el grafico pico-vs-carga, asi que si
     esta mal aca el grafico medido no se puede interpretar;
  5. las guardas levantan ValueError en vez de devolver una forma degenerada.

    python3 test_formas_pulso.py
"""
import os
import sys

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import rigol_dg4162 as rg

FAILS = []

WIDTH_S = 2e-6
RATE_HZ = 2e3
FAMILIAS = ('cr', 'cr_rc', 'cr_rc4', 'triangular', 'trapezoidal', 'bipolar')


def check(name, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {name}{("  " + extra) if extra else ""}')
    if not cond:
        FAILS.append(name)


def construir(familia, **kw):
    return rg.shaped_train_wave(familia, WIDTH_S, RATE_HZ, n_pulses=1, **kw)


# --------------------------------------------------------------- 1

def test_fwhm_pedido():
    print('\n[1] el FWHM medido es el pedido, para las seis familias')
    for fam in FAMILIAS:
        wave, freq, info = construir(fam)
        # dt sale de la definicion del instrumento (la forma completa se estira
        # sobre 1/freq), no del `info`: si `info` mintiera, esto lo detecta.
        dt = 1.0 / (wave.size * freq)
        fwhm_s = rg._fwhm_pts(wave) * dt
        err = abs(fwhm_s - WIDTH_S) / WIDTH_S
        # Tolerancia: un punto del ARB sobre los ~65 que ocupa el FWHM (1.5 %).
        # La triangular es la que mas se aleja, porque su ancho a media altura
        # cae justo en el medio de las rampas y la interpolacion cuantiza.
        check(f'{fam}: FWHM = {fwhm_s*1e6:.3f} us', err < 0.02,
              f'(error {100*err:.2f} %)')


# --------------------------------------------------------------- 2

def test_invariante_del_barrido():
    print('\n[2] con n_pulses=1 solo cambia la FORMA entre familias')
    infos = {f: construir(f)[2] for f in FAMILIAS}

    freqs  = {f: i['freq_hz'] for f, i in infos.items()}
    srates = {f: i['srate_sa_s'] for f, i in infos.items()}
    npts   = {f: i['n_pts'] for f, i in infos.items()}

    check('frecuencia de repeticion identica entre familias',
          len(set(freqs.values())) == 1, f'({set(freqs.values())})')
    check('la frecuencia es la tasa pedida (n_pulses=1)',
          abs(list(freqs.values())[0] - RATE_HZ) < 1e-9)
    check('tasa de muestreo del ARB identica entre familias',
          len(set(srates.values())) == 1,
          f'({list(srates.values())[0]/1e6:.2f} MSa/s)')
    check('misma cantidad de puntos entre familias',
          len(set(npts.values())) == 1, f'({list(npts.values())[0]} pts)')

    # La escala de la forma SI tiene que cambiar: es lo que compensa la
    # geometria distinta de cada familia para dejar el mismo FWHM.
    escalas = {f: round(i['escala_pts'], 3) for f, i in infos.items()}
    check('la escala de cada forma es distinta (es lo que iguala el FWHM)',
          len(set(escalas.values())) == len(FAMILIAS), f'({escalas})')


# --------------------------------------------------------------- 3

def test_apta_para_load_arb():
    print('\n[3] la forma es apta para load_arb')
    for fam in FAMILIAS:
        wave, _, info = construir(fam)
        ok_rango = wave.min() >= -1.0 and wave.max() <= 1.0
        ok_pico  = abs(wave.max() - 1.0) < 1e-9
        # Sin escalon al repetir: la forma cierra donde arranca. Con las
        # bipolares hay que mirar el valor absoluto, porque lo que puede quedar
        # colgando es el lobulo negativo.
        ok_cierre = abs(wave[0]) < 0.02 and abs(wave[-1]) < 0.02
        check(f'{fam}: en [-1,1], pico 1.0, sin escalon',
              ok_rango and ok_pico and ok_cierre and np.all(np.isfinite(wave)),
              f'({wave.min():+.3f} a {wave.max():+.3f}, extremos '
              f'{wave[0]:+.4f}/{wave[-1]:+.4f})')

    # La bipolar tiene que tener lobulo negativo de verdad, y area positiva y
    # negativa iguales (es la definicion de la doble diferenciacion).
    wave, _, info = construir('bipolar')
    check('bipolar: tiene lobulo negativo', wave.min() < -0.1,
          f'(minimo {wave.min():.3f})')
    check('bipolar: area positiva = area negativa',
          abs(info['area_pos_frac'] - 0.5) < 0.01,
          f'(fraccion positiva {info["area_pos_frac"]:.4f})')
    for fam in ('cr', 'cr_rc', 'cr_rc4', 'triangular', 'trapezoidal'):
        _, _, i = construir(fam)
        check(f'{fam}: unipolar (area positiva = 100 %)',
              abs(i['area_pos_frac'] - 1.0) < 1e-6)


# --------------------------------------------------------------- 4

def test_factor_de_forma():
    print('\n[4] el factor de forma sale en el orden analitico esperado')
    ff = {f: construir(f)[2]['factor_forma'] for f in FAMILIAS}
    for f, v in ff.items():
        print(f'      {f:12s} area_positiva/(pico*FWHM) = {v:.4f}')

    # La CR es un exponencial puro: area/pico = escala, FWHM = ln2 * escala,
    # asi que el factor tiende a 1/ln2 = 1.443 cuando el flanco se hace
    # instantaneo. Con el flanco finito de r=0.05 queda algo por debajo.
    check('cr es la de mayor factor de forma (cola larga)',
          ff['cr'] == max(ff.values()), f'({ff["cr"]:.3f})')
    check('cr por debajo del limite 1/ln2 = 1.443',
          ff['cr'] < 1.0 / np.log(2), f'({ff["cr"]:.3f})')
    check('orden cr > cr_rc > cr_rc4 (mas integraciones, mas compacta)',
          ff['cr'] > ff['cr_rc'] > ff['cr_rc4'])

    # Todo trapecio simetrico tiene area = pico * FWHM EXACTAMENTE (la recta de
    # media altura bisecta las dos rampas), y la triangular es el caso limite
    # plano=0. O sea que las dos familias caen sobre la MISMA recta en el
    # grafico pico-vs-carga: es el par de control que aisla el efecto del
    # apice, porque comparten la relacion carga/pico y no comparten nada mas.
    check('triangular: factor de forma = 1 exacto',
          abs(ff['triangular'] - 1.0) < 0.01, f'({ff["triangular"]:.4f})')
    check('trapezoidal: factor de forma = 1 exacto',
          abs(ff['trapezoidal'] - 1.0) < 0.01, f'({ff["trapezoidal"]:.4f})')
    for plano in (0.5, 2.0, 4.0):
        _, _, i = construir('trapezoidal', plano=plano)
        check(f'trapecio con plano={plano}: sigue dando 1 (no depende del techo)',
              abs(i['factor_forma'] - 1.0) < 0.01, f'({i["factor_forma"]:.4f})')


# --------------------------------------------------------------- 5

def test_errores_explicitos():
    print('\n[5] las combinaciones imposibles fallan con mensaje, no en silencio')

    def falla(nombre, fn, frag):
        try:
            fn()
        except (ValueError, KeyError) as e:
            check(nombre, frag in str(e), f'({str(e)[:70]}...)')
        else:
            check(nombre, False, '(no levanto excepcion)')

    falla('familia desconocida',
          lambda: rg.shaped_train_wave('gaussiana', WIDTH_S, RATE_HZ), 'gaussiana')
    falla('duty >= 0.5 -> se solapan',
          lambda: rg.shaped_train_wave('cr_rc', 1e-3, 1e3), 'solapan')
    falla('width_s negativo',
          lambda: rg.shaped_train_wave('cr_rc', -1e-6, 1e3), 'positivos')
    # La CR tiene el flanco mas rapido del catalogo (~9 % del FWHM), asi que es
    # la primera que se queda sin puntos de ARB cuando el pulso se acorta.
    falla('flanco por debajo de MIN_RISE_PTS',
          lambda: rg.shaped_train_wave('cr', 1e-9, 1e3), 'flanco')
    # La CR-RC^4 es la mas larga en relacion a su FWHM (pica en u=4 y todavia
    # decae hasta ~u=14), asi que es la primera en la que la cola no termina
    # antes del periodo siguiente. El umbral esta entre 180 y 200 kHz con
    # pulsos de 2 us: a 180 kHz la cola vale 1.2 % del pico al cerrar, a 200
    # kHz vale 2.9 % y la guarda la rechaza.
    falla('cola sin terminar al cerrar el periodo',
          lambda: rg.shaped_train_wave('cr_rc4', 2e-6, 200e3, n_pulses=1), 'pisar')
    _, _, i180 = rg.shaped_train_wave('cr_rc4', 2e-6, 180e3, n_pulses=1)
    check('justo por debajo del umbral no falla', i180['tail_residual'] < 0.02,
          f'(residual {100*i180["tail_residual"]:.1f} %)')

    # Caso valido que NO tiene que fallar: el barrido completo a la tasa de
    # trabajo. Si esto levanta, el test de hardware no arranca.
    for fam in FAMILIAS:
        try:
            construir(fam)
            check(f'{fam} a {WIDTH_S*1e6:g} us / {RATE_HZ:g} Hz entra', True)
        except ValueError as e:
            check(f'{fam} a {WIDTH_S*1e6:g} us / {RATE_HZ:g} Hz entra', False, f'({e})')


# --------------------------------------------------------------- 6

def test_pulse_train_wave_intacto():
    print('\n[6] el refactor no movio a pulse_train_wave')
    # `shaped_train_wave` y `pulse_train_wave` comparten `_geometria_tren`. La
    # regresion de verdad son API/tests/test_wave_builders.py y test_poisson_wave.py;
    # aca solo se ancla que la geometria que reporta siga siendo la de siempre
    # para el estimulo por default de la campana.
    _, freq, info = rg.pulse_train_wave(2e-6, 2e3)
    check('2 us / 2 kHz: 1 pulso por forma', info['n_pulses'] == 1)
    check('2 us / 2 kHz: freq = 2000 Hz', abs(freq - 2000.0) < 1e-9)
    check('2 us / 2 kHz: 16000 puntos por periodo', info['slot_pts'] == 16000,
          f'({info["slot_pts"]})')
    check('info trae tail_residual', 'tail_residual' in info)
    _, _, i100 = rg.pulse_train_wave(2e-6, 100e3)
    check('100 kHz: entran varios pulsos por forma', i100['n_pulses'] > 1,
          f'({i100["n_pulses"]} pulsos)')


def main():
    test_fwhm_pedido()
    test_invariante_del_barrido()
    test_apta_para_load_arb()
    test_factor_de_forma()
    test_errores_explicitos()
    test_pulse_train_wave_intacto()
    print('\nRESULT:', 'PASS' if not FAILS else f'FAIL ({len(FAILS)}): {FAILS}')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
