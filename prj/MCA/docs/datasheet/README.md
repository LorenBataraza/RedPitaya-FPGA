# Datasheets de los módulos RTL

Una página por **top de RTL**, generada por [`modulos/mk/datasheet.py`](../../modulos/mk/datasheet.py) a partir del código: interfaces, mapa de registros, dominios de reloj, Fmax, las figuras de transacciones y de ondas, y el plan de verificación cosechado de los testbenches.

Lo que está entre marcas `<!-- AUTO:x -->` se **reescribe en cada corrida**; todo lo demás es prosa a mano y no se toca.

**La §1.1 «Qué hace» no se escribe en la página: se escribe en [`prosa/`](prosa/).** Hay un archivo por top, el generador lo crea vacío la primera vez y después **no lo toca nunca más**; en cada corrida lo copia dentro del bloque `AUTO:prosa`. Así la página es derivable entera —se puede borrar y regenerar sin perder una línea— y lo escrito a mano vive en un archivo que ningún generador escribe. Los enlaces se escriben **relativos al archivo de prosa** —así renderiza bien y el chequeo de enlaces del repo lo puede verificar— y se recalculan solos al copiarlos a la página.

```bash
make -C modulos/<módulo>/work datasheet        # todos los tops del módulo
make -C modulos/mca/work datasheet DS_TOPS="mca_hist mca_top"
make -C modulos/<módulo>/work datasheet-check  # falla si quedó vieja (CI)
```

`DS_TOPS` es a los datasheets lo que `TBS` a los testbenches: la lista de tops que tienen página. Vacía —que es lo normal— quiere decir **todos los de `files.f`**.

Los diagramas de interfaz están en [`figuras/`](figuras/). Usan la paleta de las figuras TikZ de [`osc/figuras/`](../osc/figuras/) (`PALETA` en el generador): el encabezado lleva el color de la región —azul `osc`, amarillo `mt`, verde `mca`, naranja `event_ring`, gris `comun`—, el bus de sistema (esclavo) va en rojo y el AXI maestro hacia DDR en naranja. Las figuras de **transacciones** y de **ondas** se quedan en `docs/<módulo>/figuras/`, donde las escribe el script de cada módulo; a estas páginas llegan por ruta relativa.

La columna «Qué es» se copia de la cabecera del RTL. Un `—` quiere decir que ese archivo **no tiene cabecera**, que es en sí mismo el dato.

---

## `comun` — región de TOP (slot 6)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`integration_cfg`](datasheet_integration_cfg.md) | `rtl/integration_cfg.sv` | región de TOP (integración): esclavo del bus de sistema |
| [`dsp_tap_mux`](datasheet_dsp_tap_mux.md) | `rtl/dsp_tap_mux.sv` | elige de qué punto de la cadena DSP toma un consumidor |
| [`mca_trap`](datasheet_mca_trap.md) | `rtl/mca_trap.sv` | conformado trapezoidal de Jordanov-Knoll, en enteros exactos: el banco del MCA (`F_TRAP`) y el disparo con polo-cero del multitrigger |

## `osc` — región del osciloscopio (slot 1)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`osc_cfg`](datasheet_osc_cfg.md) | `rtl/osc_cfg.sv` | región de OSC: esclavo del bus de sistema (slot 1, 0x4010_0000) |
| [`osc_filter`](datasheet_osc_filter.md) | `rtl/osc_filter.v` | — |
| [`rp_scope_mt_com`](datasheet_rp_scope_mt_com.md) | `rtl/rp_scope_mt_com.sv` | datapath del scope: `rp_scope_com` + `mt_top`, integra las tres regiones |
| [`mt_rp_scope_cfg`](datasheet_mt_rp_scope_cfg.md) | `rtl/mt_rp_scope_cfg.sv` | mapa de registros legacy, referencia del TB diferencial contra `osc_cfg` |

## `mt` — región del multitrigger (slot 3)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`mt_trig_src`](datasheet_mt_trig_src.md) | `rtl/mt_trig_src.sv` | Selección de fuentes de 8 bits como MÁSCARA OR: |
| [`mt_slope_trig`](datasheet_mt_slope_trig.md) | `rtl/mt_slope_trig.sv` | disparo por pendiente: trapezoidal rápido + Schmitt, fuentes 17–24 de la máscara |
| [`mt_pz_trig`](datasheet_mt_pz_trig.md) | `rtl/mt_pz_trig.sv` | disparo con polo-cero: trapecio corto (`mca_trap`) + Schmitt, fuentes 25–28 de la máscara |
| [`trigger_shield`](datasheet_trigger_shield.md) | `rtl/trigger_shield.sv` | Módulo que toma configuración como parámetros. |
| [`mt_event_logic`](datasheet_mt_event_logic.md) | `rtl/mt_event_logic.v` | Este módulo tiene la tarea de dar la salida de eventos. |
| [`mt_cfg`](datasheet_mt_cfg.md) | `rtl/mt_cfg.sv` | región de MULTITRIGGER: esclavo del bus de sistema |
| [`mt_top`](datasheet_mt_top.md) | `rtl/mt_top.sv` | **top del módulo**: el multitrigger entero, que instancia todo lo de arriba |

## `mca` — cadena de análisis de altura de pulso (slot 7)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`mca_div_restore`](datasheet_mca_div_restore.md) | `rtl/mca_div_restore.sv` | divisor restaurador para el factor de forma (PSD) |
| [`mca_hist`](datasheet_mca_hist.md) | `rtl/mca_hist.sv` | motor de histograma genérico (una implementación, N instancias) |
| [`mca_zoom`](datasheet_mca_zoom.md) | `rtl/mca_zoom.sv` | de una feature de FW bits al bin de un eje de AW bits, con zoom |
| [`mca_discriminator`](datasheet_mca_discriminator.md) | `rtl/mca_discriminator.sv` | acepta o rechaza un evento por el valor de UNA feature. |
| [`mca_delay`](datasheet_mca_delay.md) | `rtl/mca_delay.sv` | línea de retardo de muestras, para alinear la ventana con `trig_i` |
| [`mca_baseline`](datasheet_mca_baseline.md) | `rtl/mca_baseline.sv` | línea de base del extractor: seguidor IIR o base fija |
| [`mca_slot`](datasheet_mca_slot.md) | `rtl/mca_slot.sv` | una ranura de medición: un juego entero de acumuladores |
| [`mca_window`](datasheet_mca_window.md) | `rtl/mca_window.sv` | el núcleo: el disparo, el asignador de ranuras y la contabilidad del tiempo muerto |
| [`mca_publish`](datasheet_mca_publish.md) | `rtl/mca_publish.sv` | publicación del evento: cola de ranuras, divisores de forma y bus de features |
| [`mca_pulse_feature`](datasheet_mca_pulse_feature.md) | `rtl/mca_pulse_feature.sv` | segmentador de pulsos y extractor de características (cableado de los anteriores) |
| [`mca_top`](datasheet_mca_top.md) | `rtl/mca_top.sv` | analizador multicanal: esclavo del bus de sistema (slot 7) |

## `event_ring` — ring de slots de evento en DDR (slot 2)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`event_window_capture`](datasheet_event_window_capture.md) | `rtl/event_window_capture.sv` | extrae una ventana (pre + post) por trigger y la emite |
| [`event_stage_fifo`](datasheet_event_stage_fifo.md) | `rtl/event_stage_fifo.sv` | buffer elastico entre la captura de ventana y el writer AXI. |
| [`event_slot_writer`](datasheet_event_slot_writer.md) | `rtl/event_slot_writer.sv` | serializa un evento a un slot del ring en DDR. |
| [`event_ring_top`](datasheet_event_ring_top.md) | `rtl/event_ring_top.sv` | ring de slots de evento en DDR. Esclavo del bus de sistema. |

---

**23 páginas, las 23 con su §1.1 escrita** en [`prosa/`](prosa/): qué resuelve el bloque, cómo encaja en la cadena y las decisiones que explican su forma. Lo que sigue en `TODO` es el **esquema de laboratorio** de §1.8, que necesita los datos del banco real y no se puede derivar de nada.

Tres cosas que las páginas no dicen por sí solas:

- **`mt_rp_scope_cfg` no se instancia en ningún top.** Se mantiene como referencia del mapa viejo; el camino vivo es `mt_cfg` (slot 3) más `osc_cfg` (slot 1).
- **La sección de Fmax sale de `syn/outputs/metrics.txt`**, así que conviene regenerar *después* de `make syn` o `make sweep-all`. Si no hay datos de síntesis, la página lo dice y deja el comando.
- **Los cinco `sim/sva/*_sva.sv` están vacíos**: tienen el `bind` y un `// TODO:`, pero ninguna propiedad. Qué conviene escribir primero está en [`verificacion_formal.md`](../verificacion_formal.md).
