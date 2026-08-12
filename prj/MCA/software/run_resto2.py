import json, os, sys; sys.path.insert(0,".")
import numpy as np, testbench_mca as tb
outdir = sys.argv[1]; res = {}
mca, gen, _ = tb.connect()
try:
    r = tb.sweep_threshold(mca, gen, ch=1, seconds=2.0, amp_vpp=0.5, outdir=outdir)
    res['sweep_threshold'] = {'lld': float(r['lld']) if np.isfinite(r['lld']) else None}

    # PSD: primero misma amplitud (FOM global limpia) y despues amplitud
    # variable (FOM vs energia), que es la que antes daba nan en 3 de 4 rebanadas.
    r = tb.test_psd_fom(mca, gen, ch=1, seconds=20.0, rate_hz=50e3,
                        tau_ratio=3.0, vs_energia=True, outdir=outdir)
    if r:
        res['psd_fom'] = {'fom': float(r['fom'].get('fom', float('nan'))),
                          'por_rebanada': [[int(lo), int(hi),
                                            (float(f) if np.isfinite(f) else None),
                                            float(n)]
                                           for lo, hi, f, n in r['per_slice']]}

    # DNL: h_shift=4 comprime a ~125 canales -> ~10^4 cuentas/canal en 60 s.
    # mode='auto' intenta modulacion AM y cae a recargar el ARB si el firmware
    # la rechaza; sin una de las dos el espectro son lineas discretas.
    r = tb.test_dnl(mca, gen, ch=1, seconds=60.0, rate_hz=50e3, h_shift=4,
                    mode='auto', outdir=outdir)
    if 'dnl' in r:
        res['dnl'] = {'modo': r['modo'],
                      'max_pct': float(r['dnl']['dnl_max_pct']),
                      'rms_pct': float(r['dnl']['dnl_rms_pct']),
                      'mean_counts': float(r['dnl']['mean_counts'])}
    elif 'error' in r:
        res['dnl'] = {'modo': r['modo'], 'invalida': r['error']}
finally:
    gen.output(1, False); gen.close(); mca.close()
with open(os.path.join(outdir, 'resumen_resto2.json'), 'w') as f:
    json.dump(res, f, indent=2, ensure_ascii=False)
print(f"\n=== guardado en {outdir}/resumen_resto2.json ===")
