"""Campaña de validación del MCA. Guarda todo lo crudo en --outdir.

ORDEN IMPORTANTE: `sweep_baseline_k` va PRIMERO. La constante del seguidor de
línea de base depende de cuánto dura el pulso, y con el estímulo nuevo
(tb.PULSE_WIDTH_S, ~2 us en vez de los ~240 us de la campaña anterior) el bl_k
utilizable cambia. Medirlo después sería calibrar con un valor que ya se usó.
"""
import json, os, sys, time
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
import numpy as np
import testbench_mca as tb
import mca_utils as mu

outdir = sys.argv[1]
os.makedirs(outdir, exist_ok=True)
res = {}

mca, gen, info = tb.connect()
res['info'] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in info.items()}
try:
    # 1) Constante de la linea de base para ESTE ancho de pulso. Todo lo demas
    #    usa el bl_k que salga de aca.
    r = tb.sweep_baseline_k(mca, gen, ch=1, ks=(3, 6, 9, 12, 15, 18),
                            seconds=1.0, outdir=outdir)
    res['sweep_baseline_k'] = {'ks': [int(x) for x in r['ks']],
                               'total': [int(x) for x in r['total']],
                               'k_min': r['k_min']}
    if r['k_min'] is not None:
        # Dos pasos por encima del minimo: el minimo es el borde donde el
        # seguidor empieza a comerse el pulso, no un punto de trabajo.
        tb.DEFAULT_CFG['bl_k'] = min(int(r['k_min']) + 2, 15)
        print(f"\n>>> bl_k de trabajo: {tb.DEFAULT_CFG['bl_k']} "
              f"(mínimo utilizable {r['k_min']})")

    r = tb.test_single_peak(mca, gen, ch=1, seconds=10.0, outdir=outdir)
    res['single_peak'] = {k: float(v) for k, v in r['fit'].items()
                          if isinstance(v, (int, float))}
    res['single_peak']['counters'] = {k: float(v) for k, v in r['counters'].items()}

    r = tb.cross_check_counts(mca, gen, ch=1, seconds=5.0, rate_hz=2000.0,
                              outdir=outdir)
    res['cross_check'] = {'expected': float(r['expected']),
                          'error_pct': float(r['error_pct']),
                          'counted': float(r['counters']['total'])}

    # q_shift=None -> se auto-escala por punto (ver compare_estimators).
    r = tb.compare_estimators(mca, gen, ch=1, seconds=5.0,
                              widths_s=(0.5e-6, 1e-6, 2e-6, 4e-6),
                              outdir=outdir)
    res['compare_estimators'] = {k: [float(x) for x in v] for k, v in r.items()}
finally:
    gen.output(1, False); gen.close(); mca.close()

res['meta'] = {'fecha': time.strftime('%Y-%m-%d %H:%M:%S'),
               'placa': '10.73.28.27',
               'generador': 'Rigol DG4162 ARB -> IN1',
               'bitstream': 'mca_red_pitaya.bit.bin',
               'pulse_width_s': tb.PULSE_WIDTH_S,
               'cfg': dict(tb.DEFAULT_CFG)}
with open(os.path.join(outdir, 'resumen.json'), 'w') as f:
    json.dump(res, f, indent=2, ensure_ascii=False)
print(f'\n=== resumen en {outdir}/resumen.json ===')
tb.plot_all(outdir)
