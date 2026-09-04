"""Resto de la campana: amplitud, umbral, par-pulso, tasa."""
import json, os, sys, time
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
import numpy as np
import testbench_mca as tb

outdir = sys.argv[1]; os.makedirs(outdir, exist_ok=True)
res = {}
mca, gen, _ = tb.connect()
try:
    r = tb.sweep_amplitude(mca, gen, ch=1, seconds=3.0, outdir=outdir)
    res['sweep_amplitude'] = {'gain': float(r['gain']), 'offset': float(r['offset']),
                              'inl_pct_fs': float(r['inl_pct_fs'])}

    r = tb.test_pulse_pair(mca, gen, ch=1, seconds=3.0, outdir=outdir)
    if r:
        res['pulse_pair'] = {'tau_pair_us': float(r['tau_pair_s'])*1e6
                             if np.isfinite(r['tau_pair_s']) else None,
                             'n_ref_cps': float(r['n_ref'])}

    # Hasta ~800 kcps: con 100 kcps el MCA seguia al generador exacto, o sea que
    # el techo estaba mas arriba y no se habia alcanzado.
    r = tb.sweep_rate(mca, gen, ch=1, seconds=3.0, outdir=outdir)
    res['sweep_rate'] = {'techo_cps': float(r['techo_cps']),
                         'rate_techo_hz': float(r['rate_techo_hz']),
                         'saturo': bool(r['saturo'])}
    if r['deadtime']:
        res['sweep_rate'].update({k: float(v) for k, v in r['deadtime'].items()
                                  if isinstance(v, (int, float))})
        res['sweep_rate']['best'] = r['deadtime']['best']
finally:
    gen.output(1, False)
    try: gen.disable_burst(1)
    except Exception: pass
    gen.close(); mca.close()

with open(os.path.join(outdir, 'resumen_resto.json'), 'w') as f:
    json.dump(res, f, indent=2, ensure_ascii=False)
print(f'\n=== guardado en {outdir}/resumen_resto.json ===')
