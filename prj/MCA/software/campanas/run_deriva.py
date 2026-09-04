#!/usr/bin/env python3
"""El experimento de deriva: ¿el centroide se mueve con la TASA o con el TIEMPO?

Es la medición más barata que queda de la lista de §17.3 de
`resultados_validacion_hw.md`, y la más decisiva: el 92 % del corrimiento medido
(+1.28 % sobre ×36 de tasa) sigue sin explicación con toda la cadena digital
modelada, y `sweep_rate` nunca pudo distinguir las dos causas porque **barría en
un solo sentido**: "más tasa" y "más tarde" eran la misma columna.

La pasada de vuelta rompe ese confundimiento. Cada tasa se mide dos veces, en
`t_ida` y `t_vuelta`, y la histéresis se regresa contra la separación temporal
entre las dos visitas — que vale casi cero en el punto de retorno y un barrido
entero en la tasa más baja. Ver el docstring de `testbench_mca.sweep_rate`.

Lo que decide el resultado:

  - **REPRODUCIBLE EN TASA** → el corrimiento es real y función de la tasa. El
    sospechoso pasa a ser el generador o el frente analógico (§17.3, puntos 2
    y 3), porque la cadena digital ya está descartada.
  - **DERIVA TEMPORAL** → el +1.28 % es en buena parte un artefacto del orden
    del barrido, hay que corregir el número publicado, y la especificación de
    estabilidad del documento de límites cambia de sujeto.

Uso, en la Pitaya::

    python3 campanas/run_deriva.py datos/deriva_20260904
    make campana-deriva OUT=datos/deriva_20260904

Antes: `python3 campanas/preparar_placa.py`, que verifica que el bitstream
cargado sea el correcto (el magic no distingue los dos, ver ahí).
"""
import json
import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import numpy as np                                   # noqa: E402
import testbench_mca as tb                           # noqa: E402

# Tiempo por punto. Más largo que los 3 s de `run_resto` a propósito: el brazo
# de palanca del experimento es la duración total de la campaña (la separación
# entre la ida y la vuelta de cada tasa), así que acortar los puntos debilita
# justo lo que se quiere medir. Con 16 tasas y 5 s son ~3 min por barrido.
SEGUNDOS = 5.0


def main(argv=None):
    outdir = (argv or sys.argv[1:])[0] if (argv or sys.argv[1:]) else 'datos/deriva'
    os.makedirs(outdir, exist_ok=True)

    mca, gen, info = tb.connect()
    try:
        # Guarda dura: contra el bitstream viejo las escrituras a los registros
        # nuevos se ignoran EN SILENCIO y la campaña saldría plausible y falsa.
        mca.exigir_features()
        print(f'  eje de {info["n_channels"]} canales '
              f'(los centroides NO son comparables con los de 16384)')

        res = tb.sweep_rate(mca, gen, ch=1, seconds=SEGUNDOS,
                            ida_y_vuelta=True, outdir=outdir)
    finally:
        gen.output(1, False)
        try:
            gen.disable_burst(1)
        except Exception:
            pass
        gen.close()
        mca.close()

    d = res['deriva'] or {}
    resumen = {
        'n_canales': int(info['n_channels']),
        'segundos_por_punto': SEGUNDOS,
        'corrimiento_pct_crudo': _f(res.get('centroid_shift_pct')),
        'corrimiento_pct_sin_deriva': _f(res.get('centroid_shift_pct_sin_deriva')),
        'deriva_canales_por_hora': _f(d.get('pendiente_can_s'), 3600.0),
        'deriva_pct_por_hora': _f(d.get('deriva_pct_hora')),
        'ordenada_canales': _f(d.get('ordenada_can')),
        'r_pearson': _f(d.get('r_pearson')),
        'sigma_residual_canales': _f(d.get('sigma_resid_can')),
        'veredicto': d.get('veredicto'),
        'techo_cps': _f(res.get('techo_cps')),
        'saturo': bool(res.get('saturo', False)),
    }
    if res.get('deadtime'):
        resumen['tau_us'] = _f(res['deadtime'].get('tau_nonparalyzable_s'), 1e6)
        resumen['mejor_ajuste'] = res['deadtime'].get('best')

    path = os.path.join(outdir, 'resumen_deriva.json')
    with open(path, 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)

    print('\n' + '=' * 70)
    print('VEREDICTO:', resumen['veredicto'])
    print(f"  corrimiento con la tasa, crudo      {resumen['corrimiento_pct_crudo']}")
    print(f"  descontando la deriva temporal      {resumen['corrimiento_pct_sin_deriva']}")
    print(f"  deriva temporal                     "
          f"{resumen['deriva_canales_por_hora']} canales/hora")
    print(f'\nguardado en {path}')
    print(f"figura: {os.path.join(outdir, 'deriva_tasa_tiempo.png')}")
    print('\nqué hacer con esto:')
    print('  - REPRODUCIBLE EN TASA -> el efecto es real; el sospechoso pasa a')
    print('    ser el generador (pulser de referencia digital) o el frente')
    print('    analógico. §17.3 puntos 2 y 3.')
    print('  - DERIVA TEMPORAL -> hay que corregir el +1.28 % publicado y')
    print('    revisar §17 y el documento de límites, que lo citan como')
    print('    corrimiento con la TASA.')
    return 0


def _f(v, escala=1.0):
    """float() tolerante: None y NaN salen como None, que es JSON válido."""
    if v is None:
        return None
    v = float(v) * escala
    return None if not np.isfinite(v) else v


if __name__ == '__main__':
    sys.exit(main())
