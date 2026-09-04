"""Campana de INL vs familia de forma de pulso.

Mide la misma curva de linealidad con las formas de amplificador de conformado
de Knoll (CR, CR-RC, CR-RC^4, triangular, trapezoidal, bipolar), todas con el
mismo FWHM y la misma altura de pico, y con los dos estimadores de amplitud del
MCA (pico e integral de carga).

Lo que sale de aca:

  - cuanto cambia la ganancia al cambiar la forma (robustez de la determinacion
    de amplitud);
  - cuanto del residuo de INL es COMUN a todas las formas -- o sea del generador
    y de la INL estatica del ADC -- y cuanto es DIFERENCIAL, que es la unica
    parte atribuible a la cadena de medicion;
  - el grafico pico-vs-carga, que compara dos estimadores internos del MISMO
    pulso y por lo tanto no depende de la exactitud del generador.

Corre EN LA PITAYA, con mca_red_pitaya.bit cargado y el Rigol por USB en IN1.
OJO: sin un kernel de Jupyter vivo (dos procesos sobre /dev/mem dan SIGBUS).

    python3 campanas/run_formas.py datos/formas_$(date +%Y%m%d_%H%M%S)
    python3 campanas/run_formas.py datos/... --amps 20 --seconds 4    # cotejo exacto
                                                             # con la campana
                                                             # publicada

Dura ~20 min con los valores por default (6 familias x 2 estimadores x 12
amplitudes x 2 pasadas). Con --amps 20 --seconds 4, ~45 min.
"""
import argparse
import json
import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
import numpy as np
import testbench_mca as tb


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('outdir', help='donde guardar .npz, .png y el resumen')
    ap.add_argument('--amps', type=int, default=12,
                    help='cuantas amplitudes entre 0.1 y 1.0 Vpp (default 12). '
                         'La campana publicada uso 20: la INL en %% FS depende '
                         'de cuantos puntos hay, asi que para cotejar contra '
                         'el 1.13 %% hay que usar 20.')
    ap.add_argument('--seconds', type=float, default=3.0,
                    help='segundos de adquisicion por punto (default 3)')
    ap.add_argument('--rate', type=float, default=2e3, help='tasa de pulsos [Hz]')
    ap.add_argument('--width', type=float, default=2e-6,
                    help='FWHM del pulso [s], el MISMO para todas las familias')
    ap.add_argument('--familias', default=None,
                    help='lista separada por comas; default: todas '
                         f'({",".join(tb.FAMILIAS_KNOLL)})')
    ap.add_argument('--estimadores', default='pico,carga')
    ap.add_argument('--sin-vuelta', action='store_true',
                    help='una sola pasada por familia (la mitad de tiempo, pero '
                         'sin el piso de ruido con el que se decide si el '
                         'diferencial entre formas es significativo)')
    ap.add_argument('--channel', type=int, default=0, help='0=IN1, 1=IN2')
    ap.add_argument('--gen-ch', type=int, default=1, help='canal del Rigol')
    ap.add_argument('--plot-only', action='store_true',
                    help='re-analizar y re-graficar un outdir ya medido (sin HW)')
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    npz = os.path.join(args.outdir, 'formas_inl.npz')

    if not args.plot_only:
        familias = (tb.FAMILIAS_KNOLL if args.familias is None
                    else tuple(s.strip() for s in args.familias.split(',')))
        mca, gen, _ = tb.connect(args.channel)
        try:
            tb.sweep_formas_inl(
                mca, gen, ch=args.gen_ch, familias=familias,
                amps=np.linspace(0.1, 1.0, args.amps), seconds=args.seconds,
                rate_hz=args.rate, width_s=args.width,
                estimadores=tuple(s.strip() for s in args.estimadores.split(',')),
                ida_y_vuelta=not args.sin_vuelta, outdir=args.outdir,
                channel=args.channel)
        finally:
            gen.output(args.gen_ch, False)
            gen.close()
            mca.close()

    if not os.path.exists(npz):
        print(f'no hay {npz}: no se puede analizar', file=sys.stderr)
        return 1

    res = tb.analizar_formas(npz)
    _informe(res)

    dest = os.path.join(args.outdir, 'resumen_formas.json')
    with open(dest, 'w') as f:
        json.dump(res, f, indent=2, ensure_ascii=False, default=float)
    tb.plot_all(args.outdir)
    print(f'\n=== guardado en {dest} ===')
    return 0


def _informe(res):
    """Imprime lo que hay que mirar, en el orden en el que hay que mirarlo."""
    for est, r in res['por_estimador'].items():
        print(f'\n=========== estimador de {est} ===========')
        if 'error' in r:
            print(f'  {r["error"]}')
            continue
        ref = r['familias'][0]
        print(f'  {"familia":13s} {"gan.rel":>8s} {"INL %FS":>8s} {"INL mV":>8s} '
              f'{"dif mV":>8s} {"piso mV":>8s} {"FWHM ch":>8s}')
        for f in r['familias']:
            print(f'  {f:13s} {r["ganancia_relativa"][f]:8.4f} '
                  f'{r["inl_pct_fs"][f]:8.2f} {r["inl_mv"][f]:8.2f} '
                  f'{r["diferencial_por_familia_mv"][f]:8.2f} '
                  f'{r["piso_ida_vuelta_mv"][f]:8.3f} '
                  f'{r["fwhm_medio_ch"][f]:8.1f}')
        print(f'  (ganancia relativa a {ref}, corregida por el desplazamiento '
              f'de binning)')
        print(f'  residuo comun {r["residuo_comun_max_mv"]:.2f} mV   '
              f'diferencial maximo {r["residuo_diferencial_max_mv"]:.2f} mV   '
              f'correlacion minima entre familias '
              f'{r["correlacion_min_entre_familias"]:+.3f}')
        print(f'  piso efectivo {r["piso_efectivo_mv"]:.2f} mV '
              f'({r["piso_lo_impone"]}) -> el diferencial lo supera '
              f'{r["diferencial_sobre_piso"]:.1f}x')
        print(f'  => {r["veredicto"]}')

    if 'deriva_replica_mv' in res:
        print(f'\n  control nulo (replica de cierre de la familia de '
              f'referencia): {res["deriva_replica_mv"]:.2f} mV de deriva, '
              f'ganancia {res["ganancia_replica_pct"]:+.2f} %')
        print('  Si esta deriva es del orden del diferencial entre familias, el '
              'diferencial\n  es deriva termica y NO se puede atribuir a la forma.')

    pv = res.get('pico_vs_carga')
    if pv:
        print('\n=========== pico vs carga (no depende del generador) ===========')
        print(f'  {"familia":13s} {"pend.rel":>9s} {"factor rel":>11s} {"error":>8s}')
        for f, p in pv['pendiente_relativa'].items():
            ffr = pv['factor_forma_relativo'].get(f)
            err = 100 * (p / ffr - 1) if ffr else float('nan')
            print(f'  {f:13s} {p:9.4f} {ffr:11.4f} {err:7.2f}%')
        print('  La pendiente relativa medida tiene que reproducir el factor de '
              'forma\n  relativo, que sale de la geometria del pulso y no de '
              'ninguna medicion.\n  Si no coinciden, el eje de carga esta mal '
              'escalado.')


if __name__ == '__main__':
    sys.exit(main())
