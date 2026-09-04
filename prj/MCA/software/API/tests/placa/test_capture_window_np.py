#!/usr/bin/env python3
"""Correctness de capture_window_np (camino rp_AcqGetDataPosV, arreglado).

Congela el buffer con un SW trigger y compara la ventana leida por
`MultiTriggerScope.capture_window_np` (PosV) contra la MISMA ventana recortada
del buffer completo leido con `rp_AcqGetOldestDataV` (el metodo que ya andaba).
Falla si difieren o si PosV devuelve ceros (el bug del RP_BTS silencioso).

Uso (en la Pitaya, con el bitstream multitrigger cargado):
    python3 test_capture_window_np.py
"""
import sys, os
import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import rp
from multitrigger_utils import MultiTriggerScope, N_BUF

PRE, POST = 2000, 2000


def main():
    rp.rp_Init()
    sc = MultiTriggerScope.open()
    fails = 0
    try:
        sc.acq_capture_sw(thr=0.5)                       # congela el buffer (SW trigger)

        n = PRE + POST

        # --- ventana via capture_window_np (PosV, lo que estamos validando) ---
        data, ref = sc.capture_window_np(pre=PRE, post=POST, at_trigger=True)
        w_posv = data[rp.RP_CH_1]

        # --- misma ventana via rp_AcqGetDataV EN LA MISMA POSICION ABSOLUTA ---
        # (por la API rp, sin mapeo manual; DataV(pos,size) == DataPosV(pos,pos+size-1))
        start_abs = (ref - PRE) % N_BUF
        fb = rp.fBuffer(n); rp.rp_AcqGetDataV(rp.RP_CH_1, start_abs, n, fb)
        w_ref = np.fromiter((fb[i] for i in range(n)), dtype=np.float32, count=n)

        def check(name, cond, extra=''):
            nonlocal fails
            print(f'  [{"PASS" if cond else "FAIL"}] {name}{("  "+extra) if extra else ""}')
            if not cond:
                fails += 1

        print(f'ref(wp_trig)={ref}  start_abs={start_abs}  n={n}')
        check('capture_window_np NO devuelve ceros',
              np.count_nonzero(w_posv) > 0,
              f'(nonzero={int(np.count_nonzero(w_posv))})')
        check('len correcto', len(w_posv) == n, f'({len(w_posv)})')
        maxdiff = float(np.max(np.abs(w_posv - w_ref)))
        check('PosV == DataV(misma posicion)', maxdiff < 1e-6, f'(max|diff|={maxdiff:.2g} V)')

        # --- read_buffers (ahora _fb_to_np/frombuffer) == lectura via fromiter ---
        d1, _ = sc.read_buffers()
        fbr = rp.fBuffer(N_BUF); rp.rp_AcqGetOldestDataV(rp.RP_CH_1, N_BUF, fbr)
        ref_fi = np.fromiter((fbr[i] for i in range(N_BUF)), dtype=np.float32, count=N_BUF)
        rb_max = float(np.max(np.abs(d1.astype(np.float32) - ref_fi)))
        check('read_buffers (frombuffer) == fromiter', rb_max < 1e-6, f'(max|diff|={rb_max:.2g} V)')

        print('\nRESULT:', 'PASS' if fails == 0 else f'FAIL ({fails})')
    finally:
        sc.disarm(); sc.close(); rp.rp_Release()
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
