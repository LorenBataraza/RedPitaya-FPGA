#!/usr/bin/env python3
"""Tests del estimulo y del analisis del MCA. Corren en la PC, sin instrumento.

Cubren las dos mitades que se pueden verificar sin hardware, que son justo las
dos que produjeron mediciones invalidas en la campana:

  1. los constructores de forma de onda: que el ancho del pulso EN SEGUNDOS y
     la tasa EN Hz sean los pedidos, una vez aplicada la forma a `freq_hz`;
  2. `mca_utils.dnl()`: que rechace un espectro de lineas discretas en vez de
     devolver un porcentaje, y que mida contra la envolvente local.

La campana se corrio con pulsos de ~240 us creyendo que eran de microsegundos,
porque nadie habia comprobado que `detector_pulse(128, ...)` + `set_arb(freq=2
kHz)` da 3.9 us POR PUNTO. Y la DNL reporto 467 % sobre un espectro con 40
canales vacios, que no es una DNL sino un estimulo que no barre.

    python3 test_wave_builders.py
"""
import os
import sys

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import rigol_dg4162 as rg
import mca_utils as mu

FAILS = []


def check(name, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {name}{("  " + extra) if extra else ""}')
    if not cond:
        FAILS.append(name)


def measure(wave, freq_hz, info):
    """Mide sobre la forma devuelta, sin usar los numeros que reporta `info`.

    dt sale de la definicion del instrumento: la forma COMPLETA se estira sobre
    1/freq_hz, o sea dt = 1/(len(wave)*freq_hz). Todo lo demas se deriva de ahi.
    """
    w  = np.asarray(wave, dtype=float)
    dt = 1.0 / (w.size * freq_hz)

    # pulsos: cruces por la mitad del pico
    half = 0.5 * w.max()
    over = w >= half
    rises = np.flatnonzero(np.diff(over.astype(np.int8)) > 0) + 1
    if over[0]:
        rises = np.r_[0, rises]
    n_pulsos = rises.size

    # FWHM del primer pulso completo, sobre su propio slot
    slot = w.size // max(n_pulsos, 1)
    fwhm_s = rg._fwhm_pts(w[:slot]) * dt

    # tasa: pulsos por segundo = n_pulsos * freq
    rate = n_pulsos * freq_hz
    return dict(dt_s=dt, n_pulsos=n_pulsos, fwhm_s=fwhm_s, rate_hz=rate,
                srate=1.0 / dt, dur_s=w.size * dt)


# --------------------------------------------------------------- 1

def test_ancho_y_tasa():
    print('\n[1] el ancho en segundos y la tasa son los pedidos')
    casos = [
        (2e-6,   2e3),
        (1e-6,   2e3),
        (500e-9, 5e3),
        (2e-6,   20e3),
        (5e-6,   1e3),
    ]
    for width_s, rate_hz in casos:
        wave, freq, info = rg.pulse_train_wave(width_s, rate_hz)
        m = measure(wave, freq, info)
        e_w = abs(m['fwhm_s'] - width_s) / width_s
        e_r = abs(m['rate_hz'] - rate_hz) / rate_hz
        check(f'w={width_s*1e6:g} us @ {rate_hz:g} Hz: FWHM medido '
              f'{m["fwhm_s"]*1e6:.3f} us', e_w < 0.15, f'(error {100*e_w:.1f}%)')
        check(f'w={width_s*1e6:g} us @ {rate_hz:g} Hz: tasa medida '
              f'{m["rate_hz"]:.0f} Hz', e_r < 1e-6, f'(error {100*e_r:.3f}%)')
        check(f'w={width_s*1e6:g} us @ {rate_hz:g} Hz: srate <= 500 MSa/s',
              m['srate'] <= rg.ARB_MAX_SRATE * 1.000001,
              f'({m["srate"]/1e6:.1f} MSa/s)')
        check(f'w={width_s*1e6:g} us @ {rate_hz:g} Hz: entra en memoria',
              wave.size <= rg.ARB_MAX_POINTS, f'({wave.size} pts)')
        check(f'w={width_s*1e6:g} us @ {rate_hz:g} Hz: info coincide con lo medido',
              abs(info['dt_s'] - m['dt_s']) < 1e-15
              and info['n_pulses'] == m['n_pulsos'],
              f'(info n={info["n_pulses"]} vs medido {m["n_pulsos"]})')


# --------------------------------------------------------------- 2

def test_contra_el_metodo_viejo():
    print('\n[2] el metodo viejo daba pulsos de cientos de us (la causa raiz)')
    # detector_pulse(128) aplicado a 2 kHz: 128 puntos estirados sobre 500 us
    wave = rg.detector_pulse(128, t_rise=4, tau=16, amplitude=1.0)
    dt = 1.0 / (wave.size * 2e3)
    fwhm_viejo = rg._fwhm_pts(wave) * dt
    # duracion hasta el 1% del pico: es lo que ve el segmentador del MCA, y lo
    # que decide si el evento cierra por maxlen. El FWHM subestima bastante.
    dur_viejo = float(np.flatnonzero(wave >= 0.01 * wave.max())[-1] + 1) * dt
    check('estimulo viejo: FWHM de decenas de us', fwhm_viejo > 50e-6,
          f'({fwhm_viejo*1e6:.0f} us)')
    check('estimulo viejo: duracion al 1% de cientos de us', dur_viejo > 200e-6,
          f'({dur_viejo*1e6:.0f} us = {dur_viejo*125e6:.0f} muestras a 125 MSPS)')

    wave_n, freq, info = rg.pulse_train_wave(2e-6, 2e3)
    fwhm_nuevo = info['fwhm_pts'] * info['dt_s']
    dur_nuevo = float(np.flatnonzero(wave_n >= 0.01 * wave_n.max())[-1] + 1) * info['dt_s']
    check('el nuevo da microsegundos', fwhm_nuevo < 5e-6,
          f'({fwhm_nuevo*1e6:.2f} us)')
    check('la duracion completa tambien baja a microsegundos', dur_nuevo < 20e-6,
          f'({dur_nuevo*1e6:.1f} us = {dur_nuevo*125e6:.0f} muestras)')
    check('la mejora en duracion es de >1 orden de magnitud',
          dur_viejo / dur_nuevo > 20, f'(x{dur_viejo/dur_nuevo:.0f})')


# --------------------------------------------------------------- 3

def test_amplitud_variable():
    print('\n[3] sliding pulser: amplitudes distintas y continuas')
    # 50 kHz: duty = 0.1, entran decenas de pulsos por forma. A 2 kHz entraria
    # UNO (duty 0.4%) y la funcion levanta ValueError, ver test 5.
    wave, freq, info = rg.pulse_train_wave(2e-6, 50e3, amp_range=(0.2, 1.0),
                                           seed=1)
    slot = info['slot_pts']
    picos = np.array([wave[k*slot:(k+1)*slot].max()
                      for k in range(info['n_pulses'])])
    check('hay varios pulsos por forma', info['n_pulses'] >= 4,
          f'({info["n_pulses"]})')
    check('los picos son todos distintos', np.unique(picos).size == picos.size)
    check('los picos cubren el rango pedido',
          picos.min() < 0.45 and picos.max() > 0.75,
          f'({picos.min():.2f} a {picos.max():.2f})')

    # semillas distintas -> amplitudes distintas (es lo que hace util recargar)
    w2, _, _ = rg.pulse_train_wave(2e-6, 50e3, amp_range=(0.2, 1.0), seed=2)
    check('otra semilla da otras amplitudes', not np.allclose(wave, w2))


# --------------------------------------------------------------- 4

def test_dos_poblaciones():
    print('\n[4] dos poblaciones: misma amplitud, colas distintas')
    wave, freq, info = rg.pulse_train_wave(2e-6, 50e3, tau_choices=(1.0, 3.0),
                                           seed=3)
    slot   = info['slot_pts']
    pulsos = [wave[k*slot:(k+1)*slot] for k in range(info['n_pulses'])]
    picos  = np.array([p.max() for p in pulsos])
    # Fraccion de la carga en la cola: es EL observable del eje de forma. La
    # ventana arranca en 2 FWHM, o sea pasado el pico, como el cfg_tail_dly del
    # MCA; tomar slot//4 caeria mucho despues del pulso y daria ~0 siempre.
    t0 = int(2 * info['fwhm_pts'])
    q_frac = np.array([p[t0:].sum() / max(p.sum(), 1e-12) for p in pulsos])
    check('todos los pulsos tienen la MISMA amplitud',
          np.allclose(picos, picos[0], rtol=1e-9),
          f'({picos.min():.3f}-{picos.max():.3f})')
    check('hay dos poblaciones separadas en la cola',
          np.unique(np.round(q_frac, 4)).size == 2,
          f'(q_cola/q_tot: {sorted(set(np.round(q_frac,3)))})')
    check('la separacion entre poblaciones es apreciable',
          (q_frac.max() - q_frac.min()) > 0.1,
          f'({q_frac.min():.3f} vs {q_frac.max():.3f})')

    # combinado: amplitud Y cola varian -> es lo que pide la FOM vs energia
    w2, _, i2 = rg.pulse_train_wave(2e-6, 50e3, amp_range=(0.3, 1.0),
                                    tau_choices=(1.0, 3.0), seed=4)
    slot2 = i2['slot_pts']
    p2 = np.array([w2[k*slot2:(k+1)*slot2].max() for k in range(i2['n_pulses'])])
    check('con amp_range+tau_choices varian las dos cosas',
          np.unique(p2).size > 1, f'({np.unique(p2).size} amplitudes distintas)')


# --------------------------------------------------------------- 5

def test_errores_explicitos():
    print('\n[5] las combinaciones imposibles fallan con mensaje, no en silencio')
    def falla(nombre, fn, frag):
        try:
            fn()
        except ValueError as e:
            check(nombre, frag in str(e), f'({str(e)[:70]}...)')
        else:
            check(nombre, False, '(no levanto ValueError)')

    falla('duty >= 0.5 -> se solapan',
          lambda: rg.pulse_train_wave(1e-3, 1e3), 'solapan')
    falla('flanco de menos de 4 puntos',
          lambda: rg.pulse_train_wave(1e-9, 1e3), 'flanco')
    falla('tasa fuera del alcance del ARB',
          lambda: rg.pulse_train_wave(1e-9, 1e8), 'flanco')
    falla('width_s negativo',
          lambda: rg.pulse_train_wave(-1e-6, 1e3), 'positivos')
    # EL caso que invalido la DNL de la campana: pedir amplitud variable con un
    # solo pulso por forma da un valor unico repetido para siempre.
    falla('amp_range con un solo pulso por forma',
          lambda: rg.pulse_train_wave(2e-6, 2e3, amp_range=(0.2, 1.0)),
          'un valor único repetido')
    falla('tau_choices con un solo pulso por forma',
          lambda: rg.pulse_train_wave(2e-6, 2e3, tau_choices=(1.0, 3.0)),
          'un valor único repetido')

    # tasa alta pero valida: tiene que ENTRAR, no fallar
    try:
        _, _, info = rg.pulse_train_wave(2e-6, 100e3)
        check('100 kHz con pulsos de 2 us entra', info['srate_sa_s'] <= rg.ARB_MAX_SRATE,
              f'({info["n_pulses"]} pulsos, {info["srate_sa_s"]/1e6:.0f} MSa/s)')
    except ValueError as e:
        check('100 kHz con pulsos de 2 us entra', False, f'({e})')


# --------------------------------------------------------------- 6

def test_normalizacion():
    print('\n[6] la forma es apta para load_arb')
    wave, _, _ = rg.pulse_train_wave(2e-6, 2e3)
    check('valores en [-1, 1]', wave.min() >= -1.0 and wave.max() <= 1.0,
          f'({wave.min():.3f} a {wave.max():.3f})')
    check('arranca y termina cerca de cero (sin escalon al repetir)',
          abs(wave[0]) < 0.05 and abs(wave[-1]) < 0.05,
          f'({wave[0]:.4f}, {wave[-1]:.4f})')
    check('sin NaN ni inf', np.all(np.isfinite(wave)))


# --------------------------------------------------------------- 7

def test_dnl_rechaza_lineas_discretas():
    print('\n[7] dnl(): un espectro de lineas discretas NO da un porcentaje')
    rng = np.random.default_rng(0)

    # El caso real: 128 amplitudes repetidas -> canales poblados con huecos.
    spec = np.zeros(512)
    spec[np.arange(50, 450, 3)] = rng.poisson(7000, len(np.arange(50, 450, 3)))
    try:
        mu.dnl(spec, 50, 450)
        check('espectro con huecos -> ValueError', False, '(devolvio un numero)')
    except ValueError as e:
        check('espectro con huecos -> ValueError', 'no tienen NINGUNA' in str(e),
              f'({str(e)[:60]}...)')
    # con strict=False se puede forzar, pero avisando cuantos hay
    d = mu.dnl(spec, 50, 450, strict=False)
    check('strict=False igual reporta cuantos canales vacios hay',
          d['n_empty'] > 100, f'({d["n_empty"]} vacios)')


def test_dnl_envolvente():
    print('\n[8] dnl(): la envolvente local separa forma de estimulo de DNL')
    rng = np.random.default_rng(1)
    n = 1024
    x = np.arange(n)

    # Estimulo NO plano (gaussiano ancho, como el ruido de una modulacion AM)
    # con una DNL real inyectada: un patron periodico de +-3%.
    env  = 50000 * np.exp(-0.5 * ((x - n/2) / (n/3))**2)
    dnl_real = 0.03 * np.sign(np.sin(2 * np.pi * x / 16))
    spec = env * (1 + dnl_real)

    d_glob  = mu.dnl(spec, 100, 900, smooth=None)
    d_local = mu.dnl(spec, 100, 900, smooth=64)
    check('contra la media global la envolvente se cuenta como DNL',
          d_glob['dnl_rms_pct'] > 3 * d_local['dnl_rms_pct'],
          f'(global {d_glob["dnl_rms_pct"]:.1f}% vs local '
          f'{d_local["dnl_rms_pct"]:.2f}% = x{d_glob["dnl_rms_pct"]/d_local["dnl_rms_pct"]:.1f})')
    check('contra la envolvente local se recupera la DNL real (~3%)',
          2.0 < d_local['dnl_rms_pct'] < 4.5,
          f'(rms {d_local["dnl_rms_pct"]:.2f}%, inyectada 3.00%)')

    # Espectro plano CON la misma DNL: las dos formas tienen que coincidir.
    spec2 = 50000 * (1 + dnl_real)
    d2g = mu.dnl(spec2, 100, 900, smooth=None)
    d2l = mu.dnl(spec2, 100, 900, smooth=64)
    check('con estimulo plano las dos referencias coinciden',
          abs(d2g['dnl_rms_pct'] - d2l['dnl_rms_pct']) < 0.5,
          f'(global {d2g["dnl_rms_pct"]:.2f}% vs local {d2l["dnl_rms_pct"]:.2f}%)')

    # Poisson puro (sin DNL): lo que salga es el piso estadistico, 1/sqrt(N).
    spec3 = rng.poisson(10000, n).astype(float)
    d3 = mu.dnl(spec3, 100, 900, smooth=64)
    check('espectro Poisson puro -> DNL ~ el piso 1/sqrt(N) = 1%',
          0.5 < d3['dnl_rms_pct'] < 1.6, f'({d3["dnl_rms_pct"]:.2f}%)')


def main():
    test_ancho_y_tasa()
    test_contra_el_metodo_viejo()
    test_amplitud_variable()
    test_dos_poblaciones()
    test_errores_explicitos()
    test_normalizacion()
    test_dnl_rechaza_lineas_discretas()
    test_dnl_envolvente()
    print('\nRESULT:', 'PASS' if not FAILS else f'FAIL ({len(FAILS)}): {FAILS}')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
