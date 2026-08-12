#!/usr/bin/env python3
"""Smoke test del MCA sobre hardware real.

Se corre EN LA PITAYA, con `mca_red_pitaya.bit.bin` ya cargado. No necesita
generador: valida el bus, los registros, el borrado y los relojes. La validación
del camino de datos (que hace falta señal) va en testbench_mca.py.

Es el equivalente en hardware de tb_mca_top.sv: lo que allá se verifica con un
BFM, acá se verifica contra el bus real, incluido el CDC que la simulación no
modela.

    python3 test_mca_hw.py
"""

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mca_utils as mu


_pass = 0
_fail = 0


def check(name, cond, detail=''):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f'  PASS  {name}')
    else:
        _fail += 1
        print(f'  FAIL  {name}' + (f'   [{detail}]' if detail else ''))


def main():
    print('=' * 62)
    print('Smoke test del MCA en hardware')
    print('=' * 62)

    # ---------------------------------------------------------------- 1
    print('\n[1] Identificación')
    try:
        m = mu.MCA.open()
    except mu.MCANotPresent as e:
        print(f'  FALLO: {e}')
        return 1
    info = m.identify(verbose=False)
    check('magic = 0x4D434131', info['magic'] == mu.MAGIC, hex(info['magic']))
    check('espectro 1D presente', info['hist_h'])
    check('mapa 2D presente', info['hist_h_psd'])
    check('H_AW = 14 (16384 canales)', m.h_aw == 14, f'H_AW={m.h_aw}')
    check('H2_AW = 7, PSD_AW = 6', (m.h2_aw, m.psd_aw) == (7, 6),
          f'{m.h2_aw},{m.psd_aw}')

    # ---------------------------------------------------------------- 2
    print('\n[2] Escritura y relectura de registros')
    pruebas = [
        ('cfg_thr',      mu.R_THR,      321,   0x3FFF),
        ('cfg_hyst',     mu.R_HYST,     77,    0x3FFF),
        ('cfg_baseline', mu.R_BASELINE, 55,    0x3FFF),
        ('cfg_maxlen',   mu.R_MAXLEN,   777,   0xFFFF),
        ('cfg_tail_dly', mu.R_TAIL_DLY, 9,     0xFFFF),
        ('cfg_amp_min',  mu.R_AMP_MIN,  11,    0xFFFF),
        ('cfg_amp_max',  mu.R_AMP_MAX,  4321,  0xFFFF),
        ('cfg_h_shift',  mu.R_H_SHIFT,  3,     0x1F),
        ('cfg_h2_shift', mu.R_H2_SHIFT, 5,     0x1F),
        ('cfg_dec',      mu.R_DEC,      7,     0xFFFF),
    ]
    for nombre, off, val, mask in pruebas:
        m.w32(off, val)
        got = m.r32(off) & mask
        check(f'{nombre} escribe/relee', got == (val & mask), f'lei {got}')

    # ---------------------------------------------------------------- 3
    # El test importante: TODA dirección del slot tiene que responder. Un
    # esclavo que no hace ack deja el CDC del slot trabado (ver
    # docs/bus_sistema_redpitaya.md §7.1); acá se verifica contra el bus real.
    print('\n[3] Barrido de direcciones (ninguna puede colgar el bus)')
    t0 = time.time()
    n = 0
    for off in list(range(0, 0x100, 4)) + list(range(0x100, 0x200, 4)):
        m.r32(off); n += 1
    for off in range(mu.APERTURE_H, mu.APERTURE_H + 0x400, 4):
        m.r32(off); n += 1
    for off in range(mu.APERTURE_2D, mu.APERTURE_2D + 0x400, 4):
        m.r32(off); n += 1
    # más allá del tamaño real de cada apertura, y zonas no mapeadas
    for off in (0x0FFFC, 0x1FFFC, 0x2FFFC, 0x00300, 0x00800, 0x0F000):
        m.r32(off); n += 1
    dt = time.time() - t0
    check(f'{n} lecturas sin colgarse', True)
    print(f'        {1e6*dt/n:.1f} us por acceso  ({dt:.2f} s en total)')

    # ---------------------------------------------------------------- 4
    print('\n[4] Borrado')
    m.stop()
    m.w32(mu.R_H_SHIFT, 0)
    t0 = time.time()
    m.clear()
    t_clear = time.time() - t0
    check('clear termina y clear_busy baja', True)
    print(f'        el barrido tardó {1e3*t_clear:.1f} ms')

    spec = m.spectrum()
    check('espectro entero en cero tras el borrado', not spec.any(),
          f'{int((spec != 0).sum())} bins != 0')
    m2d = m.map2d()
    check('mapa 2D entero en cero', not m2d.any(),
          f'{int((m2d != 0).sum())} celdas != 0')
    check('forma del mapa 2D = (128, 64)', m2d.shape == (128, 64), str(m2d.shape))

    c = m.counters()
    check('contadores en cero tras el borrado',
          all(c[k] == 0 for k in ('total', 'accepted', 'rej_amp', 'rej_psd',
                                  'pileup', 'dropped')), str(c))

    # ---------------------------------------------------------------- 5
    print('\n[5] Relojes de adquisición')
    m.clear()
    m.start()
    time.sleep(0.5)
    c1 = m.counters()
    time.sleep(0.5)
    m.stop()
    # Los tres relojes se leen en accesos SEPARADOS. Con la adquisición
    # corriendo, realtime se muestrea ~10 us antes que livetime y la identidad
    # no cierra: hay que parar primero para tener una foto coherente.
    c2 = m.counters()
    dr = c2['realtime_s'] - c1['realtime_s']
    check('realtime avanza ~0.5 s en 0.5 s', 0.4 < dr < 0.7, f'{dr:.4f} s')
    check('livetime + deadtime = realtime (con run=0)',
          abs((c2['livetime_s'] + c2['deadtime_s']) - c2['realtime_s']) < 1e-9,
          f"lt={c2['livetime_s']:.6f} dt={c2['deadtime_s']:.6f} rt={c2['realtime_s']:.6f}")
    check('realtime medido coincide con el reloj del sistema',
          abs(c2['realtime_s'] - 1.0) < 0.05, f"{c2['realtime_s']:.4f} s vs 1.0 s")

    m.stop()
    c3 = m.counters()
    time.sleep(0.3)
    c4 = m.counters()
    check('con run=0 el realtime NO avanza',
          abs(c4['realtime_s'] - c3['realtime_s']) < 1e-6,
          f"{c4['realtime_s'] - c3['realtime_s']:.6f} s")

    # ---------------------------------------------------------------- 6
    print('\n[6] Selección de canal y estado')
    m.w32(mu.R_CTRL, 1 << 8)
    check('chan_sel = IN2', m.channel == 1)
    m.w32(mu.R_CTRL, 0)
    check('chan_sel = IN1', m.channel == 0)
    st = m.r32(mu.R_STATUS)
    check('clear_busy bajo en reposo', not (st & 1), hex(st))

    print('\n[7] Línea de base seguida (entrada al aire)')
    m.configure(thr=200, hyst=80, bl_auto=True, bl_k=6, tail_dly=8)
    m.clear(); m.start(); time.sleep(0.5)
    ev = m.last_event()
    m.stop()
    print(f"        baseline_now = {ev['baseline']}  (cuentas del ADC)")
    check('la línea de base converge a un valor razonable',
          -2000 < ev['baseline'] < 2000, str(ev['baseline']))

    m.close()

    print('\n' + '=' * 62)
    print(f'RESULTADO: {_pass} PASS, {_fail} FAIL')
    print('=' * 62)
    return 0 if _fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
