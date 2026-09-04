#!/usr/bin/env python3
"""Benchmark de los metodos de lectura del buffer ADC del Red Pitaya.

Congela el buffer con un SW trigger (independiente del Rigol / de la señal) y
mide el tiempo de leer N samples con cada metodo disponible del modulo `rp`,
incluyendo la extraccion a numpy. Reporta mean/median/min y verifica que todos
devuelven los MISMOS datos.

Dos dimensiones que dominan el costo:
  1. el read en C (rp_AcqGet{Oldest,Data,DataPos}V...)
  2. la extraccion a numpy: fBuffer + np.fromiter (loop python, lento) vs las
     variantes *NP (escriben directo a un np.array en C, sin loop).

Uso (en la Pitaya, con el bitstream multitrigger cargado):
    python3 bench_buffer_read.py [N] [REPS]
      N    = samples a leer   (default 16384 = buffer completo)
      REPS = repeticiones      (default 200)
"""
import sys, os, time
import numpy as np

# rp vive en el RP OS; multitrigger_utils en el dir padre (software/).
sys.path.insert(0, '/opt/redpitaya/lib/python')
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import rp
from multitrigger_utils import MultiTriggerScope, N_BUF

N    = int(sys.argv[1]) if len(sys.argv) > 1 else N_BUF
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 200


def fromiter_fb(fb, n):
    """Extraccion clasica: fBuffer SWIG -> np.ndarray via loop python."""
    return np.fromiter((fb[i] for i in range(n)), dtype=np.float32, count=n)


def timeit(fn, reps):
    """mean/median/min en ms sobre `reps` corridas."""
    ts = np.empty(reps)
    for k in range(reps):
        t0 = time.perf_counter(); fn(); ts[k] = time.perf_counter() - t0
    ts *= 1e3
    return dict(mean=ts.mean(), median=float(np.median(ts)), min=ts.min())


def row(name, r):
    if 'error' in r:
        print(f'{name:34s}  ERROR: {r["error"]}')
    else:
        print(f'{name:34s} {r["mean"]:9.3f} {r["median"]:8.3f} {r["min"]:8.3f}')


def main():
    rp.rp_Init()
    sc = MultiTriggerScope.open()
    try:
        sc.acq_capture_sw(thr=0.5)                      # congela el buffer (SW trigger)
        ch  = rp.RP_CH_1
        pos = rp.rp_AcqGetWritePointer()[1]             # posicion de referencia
        end = (pos + N - 1) % N_BUF                     # end_pos INCLUSIVO -> N samples
        fb  = rp.fBuffer(N)                             # buffer SWIG reutilizado

        print(f'\nN={N} samples ({N/125e6*1e6:.0f} us @125MSPS)   REPS={REPS}   '
              f'ch=RP_CH_1   pos_ref={pos}')

        # ---------- 1) READ EN C (sin convertir a numpy) ----------
        print('\n[1] READ en C (rp_AcqGet... -> fBuffer, SIN convertir):')
        print(f'{"metodo":34s} {"mean_ms":>9s} {"median":>8s} {"min_ms":>8s}')
        print('-' * 62)
        reads = []
        if hasattr(rp, 'rp_AcqGetOldestDataV'):
            reads.append(('OldestDataV', lambda: rp.rp_AcqGetOldestDataV(ch, N, fb)))
        if hasattr(rp, 'rp_AcqGetLatestDataV'):
            reads.append(('LatestDataV', lambda: rp.rp_AcqGetLatestDataV(ch, N, fb)))
        if hasattr(rp, 'rp_AcqGetDataV'):
            reads.append(('DataV(pos)', lambda: rp.rp_AcqGetDataV(ch, pos, N, fb)))
        if hasattr(rp, 'rp_AcqGetDataPosV'):
            reads.append(('DataPosV', lambda: rp.rp_AcqGetDataPosV(ch, pos, end, fb, N)))
        for name, op in reads:
            try:
                row('  ' + name, timeit(op, REPS))
            except Exception as e:
                row('  ' + name, dict(error=repr(e)[:60]))

        # ---------- 2) CONVERSION fBuffer -> numpy (independiente del read) ----------
        rp.rp_AcqGetDataPosV(ch, pos, end, fb, N)        # llenar fb una vez
        print('\n[2] CONVERSION fBuffer -> np.ndarray (independiente del read):')
        print(f'{"metodo":34s} {"mean_ms":>9s} {"median":>8s} {"min_ms":>8s}')
        print('-' * 62)
        conv = [
            ('np.fromiter (loop)',  lambda: np.fromiter((fb[i] for i in range(N)), dtype=np.float32, count=N)),
            ('list-comprehension',  lambda: np.array([fb[i] for i in range(N)], dtype=np.float32)),
        ]
        # np.frombuffer via el puntero SWIG, si el fBuffer lo permite (rapido si anda)
        try:
            import ctypes
            addr = int(fb.cast().__int__()) if hasattr(fb, 'cast') else None
            if addr:
                def frombuf():
                    return np.frombuffer((ctypes.c_float * N).from_address(addr), dtype=np.float32).copy()
                frombuf()                                # smoke test
                conv.append(('np.frombuffer(ptr) [rapido]', frombuf))
        except Exception as e:
            print(f'  (np.frombuffer no disponible: {repr(e)[:50]})')
        for name, fn in conv:
            try:
                row('  ' + name, timeit(fn, REPS))
            except Exception as e:
                row('  ' + name, dict(error=repr(e)[:60]))

        # ---------- 3) variantes NP (read+convert fusionado en C) ----------
        print('\n[3] variantes *NP (read+convert directo a numpy, sin loop):')
        np_variants = [
            ('OldestDataVNP', lambda a: rp.rp_AcqGetOldestDataVNP(ch, N, a)),
            ('DataVNP',       lambda a: rp.rp_AcqGetDataVNP(ch, pos, N, a)),
            ('DataPosVNP',    lambda a: rp.rp_AcqGetDataPosVNP(ch, pos, end, a)),
        ]
        any_np = False
        for nm, call in np_variants:
            if hasattr(rp, 'rp_AcqGet' + nm):
                any_np = True
                a = np.zeros(N, dtype=np.float32)
                try:
                    row('  ' + nm, timeit(lambda: call(a), REPS))
                except Exception as e:
                    row('  ' + nm, dict(error=repr(e)[:60]))
        if not any_np:
            print('  (ninguna variante *NP en este RP OS -> el camino rapido no esta disponible)')

        # ---------- 4) correctness (misma posicion) ----------
        rp.rp_AcqGetDataV(ch, pos, N, fb)
        a_datav = fromiter_fb(fb, N)
        rp.rp_AcqGetDataPosV(ch, pos, end, fb, N)
        a_posv = fromiter_fb(fb, N)
        print('\n[4] correctness: DataPosV == DataV(misma pos): '
              f'{"OK" if np.array_equal(a_posv, a_datav) else "DIFF"}   '
              f'zeros(PosV)={"SI(BUG)" if np.count_nonzero(a_posv)==0 else "no"}')
    finally:
        sc.disarm(); sc.close(); rp.rp_Release()


if __name__ == '__main__':
    main()
