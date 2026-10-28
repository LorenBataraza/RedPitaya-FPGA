# Figuras: event_ring a nivel de transacción

La transacción de este módulo es **un evento**: la ventana que el trigger congela, serializada a exactamente un slot de DDR y publicada con un footer que es la marca de commit. Las cuatro figuras contestan qué entra, qué viaja y qué sale.

Las genera [`transacciones_event_ring.py`](transacciones_event_ring.py):

```bash
cd prj/MCA/docs/event_ring/figuras/transacciones
python3 transacciones_event_ring.py
python3 transacciones_event_ring.py --extraer   # rehacer datos_e2e.npz
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`event_ring_a_ventana.png`](event_ring_a_ventana.png) | Qué entra: la ventana capturada, muestra a muestra, con el pre-trigger sombreado | medidos |
| [`event_ring_b_slot.png`](event_ring_b_slot.png) | Qué viaja: la cadena de captura y las palabras de 64 b que componen el slot | medidos + layout del RTL |
| [`event_ring_c_ring.png`](event_ring_c_ring.png) | Qué sale: los slots del ring, los dos punteros y los créditos ocupados | esquema |
| [`event_ring_transaccion.png`](event_ring_transaccion.png) | **Las tres juntas**: la que conviene poner si en el informe entra una sola | medidos + esquema |

Los epígrafes están en [`epigrafes.txt`](epigrafes.txt), que escribe el mismo script para que no puedan desincronizarse.

**De dónde salen los números.** La ventana es una captura real de la campaña e2e, recortada a tres eventos en [`datos_e2e.npz`](datos_e2e.npz) (12 kB) para que la figura se regenere sin los 14 MB del chunk original, que además no está versionado. El slot se arma con el layout de [`event_slot_writer.sv`](../../../../modulos/event_ring/rtl/event_slot_writer.sv) y después se decodifica con `ring_format.decode_slot()`, el **mismo decodificador que usa el lector de producción**, verificando que las muestras vuelven bit a bit. Si el layout del RTL y el del software se separan, el script falla en vez de dibujar un slot que no existe.
