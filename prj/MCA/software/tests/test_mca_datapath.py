#!/usr/bin/env python3
"""Validación del camino de datos del MCA con señal real del Rigol.

Se corre EN LA PITAYA, con `mca_red_pitaya.bit.bin` cargado y la salida CH1 del
DG4162 conectada a IN1.

Es la prueba que cierra el lazo: pulsos reales -> segmentador -> histogramas.
Si `cnt_total` sigue a la tasa del generador y el espectro tiene un pico
único, todo el camino está validado.
"""

import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mca_utils as mu
import rigol_dg4162 as rg


def main():
    rate = 2000.0
    seconds = 1.0

    m = mu.MCA.open()
    m.identify(verbose=False)
    g = rg.RigolDG4162.usb()
    print(f'generador: {g.id.strip()}')

    wave = rg.detector_pulse(128, t_rise=4, tau=16, amplitude=1.0)
    g.load_arb(wave, ch=1)
    g.set_arb(ch=1, freq_hz=rate, amp_vpp=0.6, offset_v=0.0)
    g.output(1, True)
    time.sleep(0.5)

    # Primero, con la base automática, ver dónde cae la señal.
    m.configure(thr=100, hyst=40, bl_auto=True, bl_k=6, bl_holdoff=64,
                maxlen=1024, tail_dly=8, amp_src=0, h_shift=0, h2_shift=7, dec=1)
    m.clear()
    m.start()
    time.sleep(seconds)
    m.stop()

    c = m.counters()
    ev = m.last_event()
    tasa = c['total'] / max(c['realtime_s'], 1e-9)

    print()
    print(f"  linea de base seguida : {ev['baseline']} cuentas")
    print(f"  ultimo evento         : amp={ev['amp']}  q_tot={ev['q_tot']}  "
          f"q_tail={ev['q_tail']}  psd={ev['psd']}")
    print(f"  cnt_total             : {c['total']}")
    print(f"  cnt_accepted          : {c['accepted']}")
    print(f"  tasa medida           : {tasa:.0f} cps   (generador: {rate:.0f} Hz)")
    print(f"  error de conteo       : {100*(tasa-rate)/rate:+.2f} %")
    print(f"  rechazos              : amp={c['rej_amp']} psd={c['rej_psd']} "
          f"pileup={c['pileup']} dropped={c['dropped']}")
    print(f"  tiempos               : real={c['realtime_s']:.4f} "
          f"live={c['livetime_s']:.4f} dead={c['deadtime_s']:.6f} s")
    if c['total']:
        print(f"  tiempo muerto/evento  : "
              f"{1e9*c['deadtime_s']/c['total']:.0f} ns")

    spec = m.spectrum()
    nz = np.nonzero(spec)[0]
    print()
    print(f"  espectro: {int(spec.sum())} cuentas en {len(nz)} bins")
    if len(nz):
        pk = int(np.argmax(spec))
        print(f"  pico en el canal {pk} con {int(spec[pk])} cuentas")
        print(f"  rango poblado    : [{int(nz[0])}, {int(nz[-1])}]")
        lo, hi = max(0, pk - 400), min(len(spec), pk + 400)
        try:
            f = mu.gauss_fit_peak(spec, lo, hi)
            print(f"  ajuste gaussiano : centroide {f['centroid']:.1f}  "
                  f"FWHM {f['fwhm']:.2f}  resolucion {f['resolution_pct']:.2f} %")
        except ValueError as e:
            print(f"  (no se pudo ajustar: {e})")

    if m.caps & mu.CAP_HIST_H_PSD:
        m2d = m.map2d()
        tot2d = int(m2d.sum())
        print()
        print(f"  mapa 2D: {tot2d} cuentas")
        if tot2d:
            i, j = np.unravel_index(int(m2d.argmax()), m2d.shape)
            print(f"  celda maxima en (amplitud={i}, forma={j}) con "
                  f"{int(m2d[i, j])} cuentas")
            proj = m2d.sum(axis=0)
            nzp = np.nonzero(proj)[0]
            print(f"  eje de forma poblado en [{int(nzp[0])}, {int(nzp[-1])}] "
                  f"de {m2d.shape[1]} bins")

    g.output(1, False)
    g.close()
    m.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
