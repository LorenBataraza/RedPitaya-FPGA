# Figuras: multitrigger a nivel de transacción

La transacción de este módulo es **una captura**: un cruce de umbral que sobrevive al enmascarado y al escudo congela la ventana, y hasta que el PS no la lee y re-arma no entra ninguna más. Lo que las figuras miden es cuántos disparos se pierden en ese lazo.

Las genera [`transacciones_mt.py`](transacciones_mt.py):

```bash
cd prj/MCA/docs/mt/figuras/transacciones
python3 transacciones_mt.py
python3 transacciones_mt.py --extraer
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`mt_a_disparos.png`](mt_a_disparos.png) | Qué entra: 14 períodos del generador a 2000 Hz y cuáles sobreviven al lazo de lectura | medidos |
| [`mt_b_camino.png`](mt_b_camino.png) | Qué viaja: de la máscara de fuentes a la ventana congelada, y el lazo de re-armado | esquema |
| [`mt_c_eficiencia.png`](mt_c_eficiencia.png) | Qué sale: la eficiencia medida, y el histograma de k que la explica | medidos |
| [`mt_transaccion.png`](mt_transaccion.png) | **Las tres juntas**: la que conviene poner si en el informe entra una sola | medidos + esquema |

Los epígrafes están en [`epigrafes.txt`](epigrafes.txt), que escribe el mismo script para que no puedan desincronizarse.

**La figura se valida sola.** No usa la columna `efficiency` que el barrido guardó: la recalcula como `1/⟨k⟩` desde los tiempos de llegada, donde `k = dt/T` son los períodos del generador que pasan entre dos capturas. Las dos coinciden con un error máximo de 0.0002.

**Ojo con qué tiempo muerto es.** El que se mide acá es el del lazo de lectura K=1 por GP0 —el que [`event_ring`](../../../event_ring/) viene a sacar—, no el veto de `trigger_shield`. Los cronogramas ciclo a ciclo del veto y del holdoff están en [`../ondas/`](../ondas/).
