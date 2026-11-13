#!/usr/bin/env python3
"""El multitrigger sobre hardware real: C contra Python, en los mismos registros.

Se corre EN LA PITAYA, con el bitstream del MCA cargado y el `.so` nuevo. No necesita
generador. Abre las dos fachadas con las dos implementaciones sobre el slot 3 y exige
que lean lo mismo, y que lo que escribe C lo lea Python. Después arma y desarma el
disparo del MCA con la API, que es lo único que ve el `we_keep` del RTL.

Deja las máscaras, el shield y los dos disparos como estaban, y el scope desarmado. No
corre si el MCA está adquiriendo: cambia el disparo. Las escrituras de la máscara no
disparan nada: las fuentes están apagadas, y los umbrales se prueban con `en=False`
antes de habilitarlos.

    python3 API/tests/placa/test_multitrigger_hw.py
"""

import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import API.multitrigger as A                                        # noqa: E402
import API.ref_py.multitrigger2 as R                                # noqa: E402

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


def _foto(r):
    return {'mascaras': [r.get_or_mask(c) for c in range(4)],
            'shield': r.get_shield(),
            'pendiente': [r.get_slope(c) for c in range(4)],
            'polo_cero': [r.get_pz(c) for c in range(4)] if r.has_pz() else None}


def _restaurar(hc_mt, hc_r, foto):
    for c, s in enumerate(foto['pendiente']):
        # Sin validar: lo que había puede tener hyst >= thr con la fuente apagada.
        hc_r.w32(A.R3_SLOPE_CFG + 4 * c, 0)
        hc_r.w32(A.R3_SLOPE_THR + 4 * c, s['thr'])
        hc_r.w32(A.R3_SLOPE_HYST + 4 * c, s['hyst'])
        hc_r.w32(A.R3_SLOPE_CFG + 4 * c, (int(s['en']) << 31) | (s['G'] << 8) | s['L'])
    for c, p in enumerate(foto['polo_cero'] or ()):
        hc_r.w32(A.R3_PZ_CFG + 4 * c, 0)
        hc_r.w32(A.R3_PZ_THR + 4 * c, p['thr'])
        hc_r.w32(A.R3_PZ_HYST + 4 * c, p['hyst'])
        hc_r.w32(A.R3_PZ_MQ + 4 * c, p['mq'])
        hc_r.w32(A.R3_PZ_CFG + 4 * c, (int(p['en']) << 31) | (p['sh'] << 24)
                 | (p['m'] << 8) | p['k'])
    hc_r.set_shield(**foto['shield'])
    for c, m in enumerate(foto['mascaras']):
        hc_r.set_or_mask(c, m)


def probar(hc_mt, hc_r, hr_mt, hr_r):
    """Las dos fachadas de libmca (`hc_*`) y las de la referencia (`hr_*`)."""
    foto = _foto(hr_r)
    print('\n[1] Lectura: lo mismo en C y en Python')
    check('slope y polo-cero anunciados', hc_r.has_slope() == hr_r.has_slope()
          and hc_r.has_pz() == hr_r.has_pz(), f'{hc_r.has_slope()} {hc_r.has_pz()}')
    for nombre, c, py in (
            ('máscaras', [hc_r.get_or_mask(i) for i in range(4)], foto['mascaras']),
            ('máscaras, por la otra fachada', [hc_mt.get_or_mask(i) for i in range(4)],
             foto['mascaras']),
            ('shield', hc_r.get_shield(), foto['shield']),
            ('shield con runtime, sin cnt', {**hc_mt.get_shield(), 'runtime': 0},
             {**hr_mt.get_shield(), 'runtime': 0}),
            ('pendiente', [hc_r.get_slope(i) for i in range(4)], foto['pendiente']),
            ('polo-cero', [hc_r.get_pz(i) for i in range(4)] if hc_r.has_pz() else None,
             foto['polo_cero']),
            ('flags', hc_r.get_flags(), hr_r.get_flags()),
            ('config', A.multitrigger_get_config(hc_mt), R.multitrigger_get_config(hr_mt))):
        check(nombre, c == py, f'{c} != {py}')

    print('\n[2] Escritura: lo que escribe C lo lee Python')
    try:
        for c in CANALES:
            hc_r.disable_slope(c)
            hc_r.set_slope(c, 8, 4, 600, 300, en=False)
            s = hr_r.get_slope(c)
            check(f'pendiente canal {c}', (s['en'], s['L'], s['G'], s['thr'], s['hyst'])
                  == (False, 8, 4, 600, 300), str(s))
            if hc_r.has_pz():
                hc_r.disable_pz(c)
                hc_r.set_pz(c, 2, 1, 3992, 10, 353, 177, en=False)
                p = hr_r.get_pz(c)
                check(f'polo-cero canal {c}', (p['en'], p['k'], p['m'], p['sh'], p['mq'], p['thr'],
                                               p['hyst']) == (False, 2, 1, 10, 3992, 353, 177), str(p))
            hc_r.set_or_mask(c, A.BIT_SLOPE_P0 << c)
            check(f'máscara canal {c}', hr_r.get_or_mask(c) == A.BIT_SLOPE_P0 << c)
        hc_mt.set_or_mask(A.BIT_SLOPE_P0, A.BIT_SLOPE_P1)
        check('las dos máscaras, con relectura',
              (hr_mt.get_or_mask(0), hr_mt.get_or_mask(1)) == (A.BIT_SLOPE_P0, A.BIT_SLOPE_P1))
        hc_r.set_shield(src=1, dst=1, dur=6)
        s = hr_r.get_shield()
        check('shield', (s['src'], s['dst'], s['dur']) == (1, 1, 6), str(s))
        hc_mt.configure_shield_autorearm(0x3, 5)
        s = hr_r.get_shield()
        check('shield autorearm', (s['src'], s['dst'], s['dur']) == (3, 3, 5), str(s))
        A.multitrigger_configure(hc_mt, shield_dur=9, or_mask_ch0=A.BIT_SLOPE_P1, shield_src=1)
        c = R.multitrigger_get_config(hr_mt)
        check('configure', (c['shield_dur'], c['or_mask_ch0'], c['shield_src'], c['shield_dst'])
              == (9, A.BIT_SLOPE_P1, 1, 3), str(c))
        hc_mt.disable_shield()
        check('disable_shield', hr_r.get_shield() == {'dur': 0, 'dst': 0, 'src': 0})

        print('\n[3] Lo que se rechaza no se escribe')
        antes = hr_r.get_slope(0)
        for args, que in (((0, 0, 4, 600, 300), 'L=0'), ((0, 8, 4, 100, 300), 'hyst >= thr'),
                          ((4, 8, 4, 600, 300), 'canal 4')):
            try:
                hc_r.set_slope(*args)
                check(f'set_slope con {que}', False)
            except ValueError:
                check(f'set_slope con {que}', hr_r.get_slope(0) == antes)
    finally:
        _restaurar(hc_mt, hc_r, foto)
    check('todo quedó como estaba', _foto(hr_r) == foto)


def armado(hc_r, osc):
    """El disparo del MCA por la API: es lo único que ve el `we_keep` del RTL."""
    print('\n[4] Armar y desarmar el disparo del MCA')
    fuentes = ['pendiente'] + (['pz'] if hc_r.has_pz() else [])
    for fuente in fuentes:
        A.multitrigger_armar_mca(osc, hc_r, ch=0, fuente=fuente)   # RuntimeError sin we_keep
        est = A.multitrigger_disparo_mca(hc_r, 0)
        check(f'{fuente}: armado, con we_keep', est['armado'] and est['fuente'] == fuente
              and est['we_keep'], str(est))
        A.multitrigger_desarmar_mca(osc, hc_r, ch=0)
        est = A.multitrigger_disparo_mca(hc_r, 0)
        check(f'{fuente}: desarmado', not est['armado'] and not est['we_keep']
              and not est['pendiente']['en'], str(est))


def main():
    print('=' * 62)
    print('El multitrigger en hardware: C contra Python')
    print('=' * 62)
    from API import _libmca
    if not _libmca.disponible():
        print(f'  libmca no carga: {_libmca.motivo()}')
        return 1
    try:
        hr_mt = R.MultiTrigger.open()
    except RuntimeError as e:
        print(f'  sin la región del multitrigger: {e}')
        return 1
    from API.mca import MCANotPresent, mca_get_running, mca_open
    from API.osciloscope import Osciloscope
    try:
        with mca_open() as m:
            if mca_get_running(m):
                print('  el MCA está adquiriendo y esto cambia su disparo: pararlo antes.')
                return 2
    except MCANotPresent as e:
        print(f'  sin MCA en este bitstream: {e}')
    hr_r = R.MtRegion.open()
    hc_mt = A.MultiTrigger.open(impl='c')
    hc_r = A.MtRegion.open(impl='c')
    osc = Osciloscope.open()
    try:
        probar(hc_mt, hc_r, hr_mt, hr_r)
        foto = _foto(hr_r)
        try:
            armado(hc_r, osc)
        finally:
            _restaurar(hc_mt, hc_r, foto)
    finally:
        for h in (hc_mt, hc_r, hr_mt, hr_r, osc):
            h.close()
    print(f'\n{_pass} pasan, {_fail} fallan')
    return 1 if _fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
