# Figuras: osc_filter a nivel de transacción

La transacción de este módulo no es un evento ni una ráfaga: es **una muestra por ciclo**, continua y sin handshake que la pueda frenar. Para un filtro lineal, la respuesta al impulso describe el bloque entero, así que eso es lo que muestran las figuras.

Las genera [`transacciones_osc.py`](transacciones_osc.py):

```bash
cd prj/MCA/docs/osc/figuras/transacciones
python3 transacciones_osc.py
python3 transacciones_osc.py --extraer   # desde el VCD de Questa
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`osc_a_impulso.png`](osc_a_impulso.png) | Qué entra: el impulso, el mismo en los dos juegos de coeficientes | simulación (RTL) |
| [`osc_b_cadena.png`](osc_b_cadena.png) | Qué viaja: el flujo AXI-S y los cuatro coeficientes | esquema |
| [`osc_c_respuesta.png`](osc_c_respuesta.png) | Qué sale: las dos respuestas al impulso, con `ref_out` superpuesto | simulación (RTL) |
| [`osc_transaccion.png`](osc_transaccion.png) | **Las tres juntas**: la que conviene poner si en el informe entra una sola | simulación (RTL) |

Los epígrafes están en [`epigrafes.txt`](epigrafes.txt), que escribe el mismo script para que no puedan desincronizarse.

**Qué prueba la figura.** El testbench corre [`osc_filter_ref.v`](../../../../modulos/osc/sim/osc_filter_ref.v) —la copia congelada del filtro anterior al rediseño— en paralelo con el DUT y con el mismo flujo. La figura dibuja las dos salidas y **recalcula** la igualdad al generarse: coinciden en 460 de 460 ciclos.

**Qué no prueba.** La equivalencia está comprobada para estos dos juegos de coeficientes, no para todos. El testbench agrega 12 juegos aleatorios; cubrir el espacio completo con coeficientes simbólicos es el caso que discute [`verificacion_formal.md`](../../../verificacion_formal.md).
