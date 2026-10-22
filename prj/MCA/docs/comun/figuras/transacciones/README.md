# Figuras: dsp_tap_mux a nivel de transacción

Hay **una sola** cadena de acondicionado por canal y cuatro nodos utilizables sobre ella; cada consumidor elige el suyo en runtime con los registros `ROUTE_*`. La transacción de este módulo es **una muestra y su valid**: lo que cambia entre nodos no es sólo el valor, es el ritmo.

Las genera [`transacciones_comun.py`](transacciones_comun.py):

```bash
cd prj/MCA/docs/comun/figuras/transacciones
python3 transacciones_comun.py
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`comun_a_pulso.png`](comun_a_pulso.png) | Qué entra: el pulso medido, una muestra por ciclo y sin estrobo | medidos |
| [`comun_b_taps.png`](comun_b_taps.png) | Qué viaja: la cadena única y los cuatro puntos de donde se puede pinchar | esquema |
| [`comun_c_nodos.png`](comun_c_nodos.png) | Qué sale: el mismo pulso en los cuatro nodos, y el cambio de ritmo | medidos + modelo exacto |
| [`comun_transaccion.png`](comun_transaccion.png) | **Las tres juntas**: la que conviene poner si en el informe entra una sola | medidos + esquema |

Los epígrafes están en [`epigrafes.txt`](epigrafes.txt), que escribe el mismo script para que no puedan desincronizarse.

**Qué es medido y qué es modelo.** El pulso de entrada es medido (la misma captura que usa [event_ring](../../../event_ring/figuras/transacciones/); hay una sola copia del dato en el repo). El diezmado con promediado y el retardo son exactos —promedio de bloque de 8 y corrimiento de 32 ciclos— y se calculan en el script. La calibración se dibuja como etapa pero **no se le inventan coeficientes**: la captura ya pasó por ella, así que los nodos A y B salen iguales.

La versión **estructural** de esto —qué operaciones acumuló la muestra en cada nodo, sin datos encima— está en [`docs/TOP/figuras/`](../../../TOP/figuras/).
