#!/usr/bin/env python3
"""Barrido: tiempo de lectura con rp_AcqGetDataPosV segun la LONGITUD de la ventana.

Congela el buffer con un SW trigger y, para varios N, mide (REPS c/u):
  - read en C          : rp_AcqGetDataPosV(ch, start, end, fb, N)
  - convert fromiter   : fBuffer -> np.ndarray via loop python (lento)
  - convert frombuffer : np.frombuffer del puntero SWIG (rapido)
Guarda los resultados en un .npz y (si hay matplotlib) un PNG tiempo-vs-N.

Uso (en la Pitaya, bitstream multitrigger cargado):
    python3 bench_read_vs_length.py [REPS]
"""
import sys, os, time
import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import rp
from multitrigger_utils import MultiTriggerScope, N_BUF

REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
NS   = [128, 256, 512, 1024, 2048, 4096, 8192, 16384]
HERE = os.path.dirname(os.path.abspath(__file__))


def timeit(fn, reps):
    ts = np.empty(reps)
    for k in range(reps):
        t0 = time.perf_counter(); fn(); ts[k] = time.perf_counter() - t0
    return float(np.median(ts) * 1e3)   # ms (mediana, robusta a jitter)


def main():
    rp.rp_Init()
    sc = MultiTriggerScope.open()
    read_ms, fromiter_ms, frombuffer_ms = [], [], []
    try:
        sc.acq_capture_sw(thr=0.5)
        ch  = rp.RP_CH_1
        pos = rp.rp_AcqGetWritePointer()[1]
        import ctypes

        print(f'REPS={REPS}  ch=RP_CH_1  pos={pos}')
        print(f'{"N":>7s} {"read_C_ms":>10s} {"fromiter_ms":>12s} {"frombuf_ms":>11s}')
        print('-' * 44)
        for N in NS:
            end = (pos + N - 1) % N_BUF
            fb  = rp.fBuffer(N)

            def do_read():
                rp.rp_AcqGetDataPosV(ch, pos, end, fb, N)
            rp.rp_AcqGetDataPosV(ch, pos, end, fb, N)      # llenar una vez
            addr = int(fb.cast().__int__())

            def c_fromiter():
                return np.fromiter((fb[i] for i in range(N)), dtype=np.float32, count=N)

            def c_frombuffer():
                return np.frombuffer((ctypes.c_float * N).from_address(addr),
                                     dtype=np.float32).copy()

            r  = timeit(do_read,     REPS)
            fi = timeit(c_fromiter,  REPS)
            fbf = timeit(c_frombuffer, REPS)
            read_ms.append(r); fromiter_ms.append(fi); frombuffer_ms.append(fbf)
            print(f'{N:7d} {r:10.4f} {fi:12.4f} {fbf:11.4f}')

        Ns = np.array(NS)
        out = os.path.join(HERE, 'bench_read_vs_length.npz')
        np.savez(out, N=Ns, read_ms=read_ms, fromiter_ms=fromiter_ms,
                 frombuffer_ms=frombuffer_ms, reps=REPS)
        print('datos:', out)

        try:                                               # PNG si hay matplotlib
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            r  = np.array(read_ms); fi = np.array(fromiter_ms); fbf = np.array(frombuffer_ms)
            fig, ax = plt.subplots(figsize=(9, 5.5))
            ax.loglog(Ns, r,        'o-', label='read C (DataPosV)')
            ax.loglog(Ns, fi,       's-', label='convert fromiter (loop)')
            ax.loglog(Ns, fbf,      '^-', label='convert frombuffer (ptr)')
            ax.loglog(Ns, r + fi,   'x--', label='total read+fromiter')
            ax.loglog(Ns, r + fbf,  'd--', label='total read+frombuffer')
            ax.set_xlabel('longitud de ventana N (samples)')
            ax.set_ylabel('tiempo (ms, mediana)')
            ax.set_title(f'rp_AcqGetDataPosV: tiempo vs longitud de ventana (REPS={REPS})')
            ax.grid(True, which='both', alpha=0.3); ax.legend()
            png = os.path.join(HERE, 'bench_read_vs_length.png')
            fig.tight_layout(); fig.savefig(png, dpi=120)
            print('grafico:', png)
        except Exception as e:
            print('sin PNG (graficar desde el .npz):', repr(e)[:60])
    finally:
        sc.disarm(); sc.close(); rp.rp_Release()


if __name__ == '__main__':
    main()
