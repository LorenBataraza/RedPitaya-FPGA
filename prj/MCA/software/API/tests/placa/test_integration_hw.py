#!/usr/bin/env python3
"""La región de TOP sobre hardware real: C contra Python, en los mismos registros.

Se corre EN LA PITAYA, con el bitstream del MCA cargado y el `.so` nuevo. No
necesita generador. Abre los dos handles sobre el slot 6 y exige que lean lo
mismo, y que lo que escribe uno lo lea el otro.

Toca el ruteo: pasa cada consumidor por todos los taps y lo deja como estaba. Por
eso no corre si el MCA está adquiriendo. `run`, `clear` y `soft_reset` son seguros:
en `mca_red_pitaya_top` no llegan a ningún consumidor.

    python3 API/tests/placa/test_integration_hw.py
"""

import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import API.integration as A                                         # noqa: E402
import API.ref_py.integration as R                                  # noqa: E402

_pass = 0
_fail = 0

CONSUMIDORES = ('osc', 'mtrg', 'mca', 'ring')
TAPS = (A.TAP_ADC, A.TAP_DEC_IN, A.TAP_BRAM_IN, A.TAP_NATIVE)


def check(name, cond, detail=''):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f'  PASS  {name}')
    else:
        _fail += 1
        print(f'  FAIL  {name}' + (f'   [{detail}]' if detail else ''))


def probar(hc, hr):
    """`hc` es el handle de libmca y `hr` el de la referencia, sobre lo mismo."""
    print('\n[1] Lo que publica el bitstream')
    info = hc.identify(verbose=False)
    check('magic = 0x494E5447 ("INTG")', info['magic'] == A.MAGIC, hex(info['magic']))
    check('identify igual en C y en Python', info == hr.identify(verbose=False))
    print(f'  git {info["gith"]}, versión {info["version"]}')
    for nombre, c, py in (('modules', hc.modules(), hr.modules()),
                          ('slots', hc.slots(), hr.slots()),
                          ('caps', hc.caps(), hr.caps()),
                          ('routes', hc.routes(), hr.routes()),
                          ('status', hc.status(), hr.status())):
        check(f'{nombre} igual en C y en Python', c == py, f'{c} != {py}')
    mods = hc.modules()
    check('trae el osciloscopio, el multitrigger y el MCA',
          mods['osc'] and mods['mtrg'] and mods['mca'], str(mods))
    s = hc.slots()
    check('slots del top del MCA: osc 1, mtrg 3, top 6, mca 7',
          (s['osc'], s['mtrg'], s['top'], s['mca']) == (1, 3, 6, 7), str(s))
    check('base del multitrigger', hc.base('mtrg') == 0x4030_0000, hex(hc.base('mtrg')))
    check('base del MCA', hc.base('mca') == 0x4070_0000, hex(hc.base('mca')))
    st = hc.status()
    check('PLL enganchado y ADC fuera de reset', st['pll_locked'] and st['adc_rstn'], str(st))

    print('\n[2] Ruteo: lo que escribe uno lo lee el otro')
    antes = hc.routes()
    try:
        for c in CONSUMIDORES:
            for tap in TAPS:
                for en in (False, True):
                    hc.set_route(c, tap, en)            # relee: falla si no latchea
                    r = hr.get_route(c)
                    if (r['tap'], r['enable']) != (tap, en) or r != hc.get_route(c):
                        check(f'{c} tap={tap} en={en}', False, str(r))
            hr.set_route(c, A.TAP_ADC, True)
            check(f'{c}: todos los taps, y de Python a C',
                  hc.get_route(c)['tap'] == A.TAP_ADC)
        try:
            hc.set_route('mca', 9)
            check('un tap inválido se rechaza', False)
        except ValueError:
            check('un tap inválido se rechaza', True)
        hc.reset_routes()
        r = hr.routes()
        check('reset_routes: los cuatro a nativo y habilitados',
              all(x['tap'] == A.TAP_NATIVE and x['enable'] for x in r.values()), str(r))
    finally:
        # Como estaba, sin relectura: un fallo acá no tapa el de arriba.
        for c, r in antes.items():
            hc.set_route(c, r['tap'], r['enable'], verify=False)
    check('el ruteo quedó como estaba', hr.routes() == antes)

    print('\n[3] Control global')
    run = hc.get_run()
    try:
        for on in (True, False):
            hc.set_run(on)
            check(f'run={on} en C, lo lee Python', hr.get_run() is on)
            hc.clear()
            hc.soft_reset()
            check(f'clear y soft_reset conservan run={on}',
                  hr.get_run() is on and hc.get_run() is on)
            check('los pulsos se autolimpian', hc.r32(A.R_CTRL) == (A.CTRL_RUN if on else 0),
                  hex(hc.r32(A.R_CTRL)))
    finally:
        hc.set_run(run)


def main():
    print('=' * 62)
    print('La región de TOP en hardware: C contra Python')
    print('=' * 62)
    try:
        hr = R.Integration.open()
    except R.IntegrationNotPresent as e:
        print(f'  sin región de TOP: {e}')
        return 1
    from API import _libmca
    if not _libmca.disponible():
        print(f'  libmca no carga: {_libmca.motivo()}')
        return 1
    from API.mca import MCANotPresent, mca_get_running, mca_open
    try:
        with mca_open() as m:
            if mca_get_running(m):
                print('  el MCA está adquiriendo y esto cambia su ruteo: pararlo antes.')
                return 2
    except MCANotPresent as e:
        print(f'  sin MCA en este bitstream: {e}')
    hc = A.Integration.open()
    try:
        probar(hc, hr)
        print('\n[4] slot_base')
        check('slot_base lee el mapa', A.slot_base('mca', 0) == hc.base('mca'))
        check('slot_base de lo que no tiene slot da el default',
              A.slot_base('nope', 0x77) == 0x77)
    finally:
        hc.close()
        hr.close()
    print(f'\n{_pass} pasan, {_fail} fallan')
    return 1 if _fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
