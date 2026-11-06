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

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
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
    print('Smoke test del MCA2 en hardware')
    print('=' * 62)

    # ---------------------------------------------------------------- 1
    print('\n[1] Identificación')
    try:
        # mca_open, no MCA.open: respeta $MCA_IMPL ('c' por defecto, 'py' la
        # referencia Python del MCA2), así el mismo smoke test valida las dos.
        m = mu.mca_open()
    except mu.MCANotPresent as e:
        print(f'  FALLO: {e}')
        return 1
    print(f'  implementación: {getattr(m, "impl", "py")}')
    info = m.identify(verbose=False)
    check('magic = 0x4D434132 ("MCA2")', info['magic'] == mu.MAGIC,
          hex(info['magic']))
    check('ranuras: N_ACC entre 1 y 7', 1 <= info['n_acc_max'] <= 7,
          str(info['n_acc_max']))
    check('espectro 1D presente', info['hist_h'])
    check('mapa 2D presente', info['hist_h_psd'])
    # H_AW=13 desde el bitstream del bus de features; antes era 14. NO es un
    # invariante del diseño sino una decision medida (9.2-10.3 bits efectivos y
    # el criterio de 4-10 canales/FWHM justifican 3800-9500 canales, no 16384),
    # y libera 8 de los 16 RAMB36 del espectro. Se afirma el valor igual, en vez
    # de leerlo del propio registro, porque un smoke test que acepta cualquier
    # geometria no detectaria un bitstream equivocado -- que es justo lo que
    # este test tiene que atrapar.
    check('H_AW = 13 (8192 canales)', m.h_aw == 13,
          f'H_AW={m.h_aw}' + (' <- bitstream VIEJO' if m.h_aw == 14 else ''))
    check('H2_AW = 7, PSD_AW = 6', (m.h2_aw, m.psd_aw) == (7, 6),
          f'{m.h2_aw},{m.psd_aw}')
    check('bus de features presente (zoom, discriminador)', info['features'],
          'sí' if info['features'] else 'NO: el bitstream es el anterior')

    # ---------------------------------------------------------------- 2
    print('\n[2] Escritura y relectura de registros')
    pruebas = [
        ('cfg_baseline', mu.R_BASELINE, 55,    0x3FFF),
        ('cfg_amp_min',  mu.R_AMP_MIN,  11,    0xFFFF),
        ('cfg_amp_max',  mu.R_AMP_MAX,  4321,  0xFFFF),
        ('cfg_dec',      mu.R_DEC,      7,     0xFFFF),
        ('cfg_gate_len', mu.R_GATE_LEN, (300 << 16) | 40, 0xFFFFFFFF),
        ('cfg_n_acc',    mu.R_N_ACC,    3,     0x7),
        ('cfg_pre_dly',  mu.R_PRE_DLY,  42,    0x7F),
    ]
    # El trapecio sólo si el bitstream lo trae: sin él sus registros no existen.
    if info['trap']:
        pruebas += [('cfg_trap_km', mu.R_TRAP_KM, (16 << 16) | 32, 0x03FF03FF),
                    ('cfg_trap_mq', mu.R_TRAP_MQ, 3885, 0xFFFFF)]
    for nombre, off, val, mask in pruebas:
        m.w32(off, val)
        got = m.r32(off) & mask
        check(f'{nombre} escribe/relee', got == (val & mask), f'lei {got}')
    # Los offsets que el MCA2 dejó reservados (eran thr, hyst, maxlen,
    # tail_dly, gate_mode y las políticas) se escriben sin efecto y leen 0.
    for off in (0x014, 0x018, 0x028, 0x02C, 0x048, 0x104, 0x108):
        m.w32(off, 0x5A5A)
        check(f'reservado {off:#05x} lee 0', m.r32(off) == 0, hex(m.r32(off)))
    m.configure()                       # deja la config en un estado conocido

    # ---------------------------------------------------------------- 3
    # El test importante: TODA dirección del slot tiene que responder. Un
    # esclavo que no hace ack deja el CDC del slot trabado (ver
    # docs/TOP/bus_sistema_redpitaya.md §7.1); acá se verifica contra el bus real.
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
    # La identidad es con deadtime_real (t_win + t_div + t_rearm) y vetotime,
    # no con deadtime_s: el primer rearmado ya suma un ciclo a t_rearm aunque no
    # entre ningún evento (docs/mca/tiempo_muerto.md).
    resto = (c2['livetime_s'] + c2['deadtime_real_s'] + c2['vetotime_s']
             - c2['realtime_s'])
    check('livetime + deadtime_real + vetotime = realtime (con run=0)',
          abs(resto) < 1e-9,
          f"lt={c2['livetime_s']:.9f} dtr={c2['deadtime_real_s']:.9f} "
          f"veto={c2['vetotime_s']:.9f} rt={c2['realtime_s']:.9f}")
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
    m.configure(bl_auto=True, bl_k=6)
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
