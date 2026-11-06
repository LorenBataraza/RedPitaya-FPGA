import json, os, sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import numpy as np, testbench_mca as tb
outdir = sys.argv[1]; res = {}
mca, gen, _ = tb.connect()
try:
    r = tb.sweep_threshold(mca, gen, ch=1, seconds=2.0, amp_vpp=0.5, outdir=outdir)
    if r:
        res['sweep_threshold'] = {'umbral_pendiente': float(r['umbral_efectivo'])
                                  if np.isfinite(r['umbral_efectivo']) else None}

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

    # DNL: en el MCA1 h_shift=4 comprimía a ~125 canales para juntar ~10^4
    # cuentas/canal en 60 s. El MCA2 no tiene h_shift (el zoom sólo amplía),
    # así que la DNL se mide sobre los 8192 canales y hace falta más tiempo
    # para la misma estadística: test_dnl avisa cuánto.
    # mode='auto' intenta modulacion AM y cae a recargar el ARB si el firmware
    # la rechaza; sin una de las dos el espectro son lineas discretas.
    r = tb.test_dnl(mca, gen, ch=1, seconds=60.0, rate_hz=50e3,
                    mode='auto', outdir=outdir)
    if 'dnl' in r:
        res['dnl'] = {'modo': r['modo'],
                      'max_pct': float(r['dnl']['dnl_max_pct']),
                      'rms_pct': float(r['dnl']['dnl_rms_pct']),
                      'mean_counts': float(r['dnl']['mean_counts'])}
    elif 'error' in r:
        res['dnl'] = {'modo': r['modo'], 'invalida': r['error']}
finally:
    tb.desconectar(mca, gen)
with open(os.path.join(outdir, 'resumen_resto2.json'), 'w') as f:
    json.dump(res, f, indent=2, ensure_ascii=False)
print(f"\n=== guardado en {outdir}/resumen_resto2.json ===")
