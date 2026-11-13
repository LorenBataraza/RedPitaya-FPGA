#!/usr/bin/env python3
"""El osciloscopio sobre hardware real: C contra Python, en los mismos registros.

Se corre EN LA PITAYA, con el bitstream del MCA cargado y el `.so` nuevo. No necesita
generador: la captura es por software. Abre las dos implementaciones sobre el slot 1 y
exige que lean lo mismo, y que lo que escribe C lo lea Python. Después congela un buffer y
compara la lectura de la BRAM de C con la de Python, palabra por palabra.

Deja la configuración, las máscaras y el shield como estaban, y el scope reseteado y
desarmado. No corre si el MCA está adquiriendo: cambia su disparo.

    python3 API/tests/placa/test_osciloscope_hw.py
"""

import os
import sys
import time

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import numpy as np                                                  # noqa: E402

import API.osciloscope as A                                         # noqa: E402
import API.ref_py.osciloscope2 as R                                 # noqa: E402

_pass = 0
_fail = 0

CANALES = (0, 1)


def check(name, cond, detail=''):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f'  PASS  {name}')
    else:
        _fail += 1
        print(f'  FAIL  {name}' + (f'   [{detail}]' if detail else ''))


def _restaurar(hr, foto):
    """Con la referencia: si C escribiera mal, esto sigue dejando lo que había."""
    R.osciloscope_configure(hr, **foto)


def probar(hc, hr):
    """libmca (`hc`) contra la referencia (`hr`), sobre los mismos registros."""
    foto = R.osciloscope_get_config(hr)
    print('\n[1] Lectura: lo mismo en C y en Python')
    for nombre, c, py in (
            ('geometría', hc.geometria(), hr.geometria()),
            ('n_buf', hc.n_buf, hr.n_buf),
            ('config', A.osciloscope_get_config(hc), foto),
            ('claves del estado', list(A.osciloscope_get_status(hc)),
             list(R.osciloscope_get_status(hr)))):
        check(nombre, c == py, f'{c} != {py}')
    for ch in CANALES:
        for fn in ('get_thr', 'get_decim', 'get_delay', 'get_hysteresis', 'get_calibration',
                   'get_wp_trig'):
            c = getattr(A, f'osciloscope_{fn}')(hc, ch)
            py = getattr(R, f'osciloscope_{fn}')(hr, ch)
            check(f'{fn} canal {ch}', c == py, f'{c} != {py}')
    for fn in ('get_avg', 'get_deb_len', 'get_filter_bypass'):
        c, py = getattr(A, f'osciloscope_{fn}')(hc), getattr(R, f'osciloscope_{fn}')(hr)
        check(fn, c == py, f'{c} != {py}')
    wp = A.osciloscope_get_wp_cur(hc)
    check('wp_cur dentro del anillo', 0 <= wp < hc.n_buf, str(wp))

    print('\n[2] Escritura: lo que escribe C lo lee Python')
    try:
        for ch in CANALES:
            A.osciloscope_set_thr(hc, -0.5, ch)
            check(f'umbral canal {ch}', R.osciloscope_get_thr(hr, ch) == -0.5)
            A.osciloscope_set_decim(hc, 8, ch)
            check(f'decimación canal {ch}', R.osciloscope_get_decim(hr, ch) == 8)
            A.osciloscope_set_delay(hc, 100 + ch, ch)
            check(f'delay canal {ch}', R.osciloscope_get_delay(hr, ch) == 100 + ch)
            A.osciloscope_set_hysteresis(hc, 0.25, ch)
            check(f'histéresis canal {ch}', R.osciloscope_get_hysteresis(hr, ch) == 0.25)
            A.osciloscope_set_calibration(hc, offset=7 + ch, gain=0x4000 + ch, ch=ch)
            check(f'calibración canal {ch}', R.osciloscope_get_calibration(hr, ch)
                  == {'offset': 7 + ch, 'gain': 0x4000 + ch})
        A.osciloscope_set_thr(hc, 0.125)
        check('umbral de los dos', (R.osciloscope_get_thr(hr, 0), R.osciloscope_get_thr(hr, 1))
              == (0.125, 0.125))
        A.osciloscope_set_deb_len(hc, 1000)
        check('deb_len', R.osciloscope_get_deb_len(hr) == 1000)
        A.osciloscope_set_filter_bypass(hc, 0x3)
        check('filter_bypass', R.osciloscope_get_filter_bypass(hr) == 0x3)
        A.osciloscope_configure(hc, avg_en_ch0=1, avg_en_ch1=1, thr_ch1=-250)
        c = R.osciloscope_get_config(hr)
        check('configure', (c['avg_en_ch0'], c['avg_en_ch1'], c['thr_ch1']) == (1, 1, -250), str(c))
        check('get_config de los dos lados', A.osciloscope_get_config(hc) == c)

        print('\n[3] Lo que se rechaza no se escribe')
        antes = R.osciloscope_get_config(hr)
        for op, que in ((lambda: A.osciloscope_set_decim(hc, 7), 'decim 7'),
                        (lambda: A.osciloscope_set_thr(hc, 0.5, 2), 'canal 2'),
                        (lambda: hc.acq_base(decim=7), 'acq_base con decim 7')):
            try:
                op()
                check(que, False)
            except ValueError:
                check(que, R.osciloscope_get_config(hr) == antes)
    finally:
        _restaurar(hr, foto)
    check('todo quedó como estaba', R.osciloscope_get_config(hr) == foto)


def _palabras(hr, ch, start, n):
    """Lo mismo que hace C, en Python y de a una palabra."""
    base = hr.geometria()['aperturas'][ch]
    n_buf, dw = hr.n_buf, hr.geometria()['dw']
    bit = 1 << (dw - 1)
    fuera = np.empty(n, dtype=np.int16)
    for i in range(n):
        w = hr.r32(base + 4 * ((start + i) & (n_buf - 1))) & ((bit << 1) - 1)
        fuera[i] = (w ^ bit) - bit
    return fuera


def probar_bram(hc, hr):
    """Con el buffer quieto: en la placa, congelado por `captura`."""
    print('\n[4] La BRAM: lo mismo en C que palabra por palabra en Python')
    n_buf = hc.n_buf
    for ch in range(min(hc.geometria()['n_ch'], 2)):
        for start, n, que in ((0, 256, 'el principio'), (n_buf // 2, 300, 'el medio'),
                              (n_buf - 100, 200, 'la vuelta del anillo'), (-8, 32, 'start negativo')):
            c = A.osciloscope_read_bram(hc, ch, start, n)
            py = _palabras(hr, ch, start, n)
            check(f'canal {ch}, {que}', (c == py).all(), f'{c[:6]} != {py[:6]}')
    entero = A.osciloscope_read_bram(hc, 0, 0, n_buf)
    check('el anillo entero se relee igual',
          (A.osciloscope_read_bram(hc, 0, 0, n_buf) == entero).all())
    print(f'    canal 0: de {entero.min()} a {entero.max()} cuentas, media {entero.mean():.1f}')
    try:
        A.osciloscope_read_bram(hc, 0, 0, n_buf + 1)
        check('más que el anillo se rechaza', False)
    except ValueError as e:
        check('más que el anillo se rechaza', 'repetido' in str(e), str(e))


def captura(hc, plazo_s=1.0):
    """Congela un buffer por software, con los comandos en C. El orden es el de
    `acq_capture_sw`: arma ANTES de pulsar el disparo. Devuelve si se congeló."""
    print('\n[5] Captura por software, sin señal')
    n_buf = hc.n_buf
    hc.acq_base(thr=0.5, delay=n_buf // 2)
    hc.mt.set_or_mask(A.BIT_SW, A.BIT_SW)
    hc.w32(A.R_CMD, 0x0000_0101)            # arm ch0+ch1, single-shot
    time.sleep(0.01)
    hc.w32(A.R_SW_TRIG, 0x0000_0101)        # el pulso a los dos canales
    t0 = time.monotonic()
    while A.osciloscope_get_adc_state(hc) & 1:     # adc_we: sigue escribiendo
        if time.monotonic() - t0 > plazo_s:
            check('el buffer se congela', False, f'adc_state={A.osciloscope_get_adc_state(hc):#x}')
            return False
        time.sleep(0.001)
    check('el buffer se congela', True)
    wp = A.osciloscope_get_wp_trig(hc)
    check('wp_trig dentro del anillo', 0 <= wp < n_buf, str(wp))
    print(f'    snapshot: {hc.mt.read_snapshot()}')
    return True


def composiciones(hc, hr):
    print('\n[6] Lo que se compone sobre r32')
    r = hc.verify_bitstream(verbose=False)
    # El sanity mira valores de reset: depende de quién tocó el scope antes (rp_Init cambia
    # la calibración). La huella es de este diseño, y no depende del estado.
    check('verify_bitstream: la huella del multitrigger', r['fingerprint_ok'], str(r['checks']))
    print(f"    sanity (valores de reset): {r['sanity_ok']}")
    check('verify_bitstream, igual en Python',
          r['checks'] == hr.verify_bitstream(verbose=False)['checks'])
    hc.debug_dump()


def main():
    print('=' * 62)
    print('El osciloscopio en hardware: C contra Python')
    print('=' * 62)
    from API import _libmca
    if not _libmca.disponible():
        print(f'  libmca no carga: {_libmca.motivo()}')
        return 1
    from API.mca import MCANotPresent, mca_get_running, mca_open
    try:
        with mca_open() as m:
            if mca_get_running(m):
                print('  el MCA está adquiriendo y esto cambia su disparo: pararlo antes.')
                return 2
    except MCANotPresent as e:
        print(f'  sin MCA en este bitstream: {e}')
    hr = R.Osciloscope.open(size=None)
    hc = A.Osciloscope.open(size=None, impl='c')
    foto = R.osciloscope_get_config(hr)
    mt = hc.mt
    mascaras = (mt.r32(A.R_OR_MASK_CH0), mt.r32(A.R_OR_MASK_CH1))
    shield = mt.r32(A.R_SHIELD_CFG)
    try:
        probar(hc, hr)
        if captura(hc):
            probar_bram(hc, hr)
        composiciones(hc, hr)
    finally:
        A.osciloscope_reset(hc)
        _restaurar(hr, foto)
        mt.w32(A.R_SHIELD_CFG, shield)
        mt.w32(A.R_OR_MASK_CH0, mascaras[0])
        mt.w32(A.R_OR_MASK_CH1, mascaras[1])
        hc.close()
        hr.close()
    print(f'\n{_pass} pasan, {_fail} fallan')
    return 1 if _fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
