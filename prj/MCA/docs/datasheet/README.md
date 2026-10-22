# Datasheets de los módulos RTL

Una página por **top de RTL**, generada por [`modulos/mk/datasheet.py`](../../modulos/mk/datasheet.py) a partir del código: interfaces, mapa de registros, dominios de reloj, Fmax, las figuras de transacciones y de ondas, y el plan de verificación cosechado de los testbenches.

Lo que está entre marcas `<!-- AUTO:x -->` se **reescribe en cada corrida**; todo lo demás es prosa a mano y no se toca.

```bash
make -C modulos/<módulo>/work datasheet        # todos los tops del módulo
make -C modulos/mca/work datasheet DS_TOPS="mca_hist mca_top"
make -C modulos/<módulo>/work datasheet-check  # falla si quedó vieja (CI)
```

`DS_TOPS` es a los datasheets lo que `TBS` a los testbenches: la lista de tops que tienen página. Vacía —que es lo normal— quiere decir **todos los de `files.f`**.

Los diagramas de interfaz están en [`figuras/`](figuras/). Las figuras de **transacciones** y de **ondas** se quedan en `docs/<módulo>/figuras/`, donde las escribe el script de cada módulo; a estas páginas llegan por ruta relativa.

La columna «Qué es» se copia de la cabecera del RTL. Un `—` quiere decir que ese archivo **no tiene cabecera**, que es en sí mismo el dato.

---

## `comun` — región de TOP (slot 6)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`integration_cfg`](datasheet_integration_cfg.md) | `rtl/integration_cfg.sv` | región de TOP (integración): esclavo del bus de sistema |
| [`dsp_tap_mux`](datasheet_dsp_tap_mux.md) ·&nbsp;*sin prosa* | `rtl/dsp_tap_mux.sv` | elige de qué punto de la cadena DSP toma un consumidor |

## `osc` — región del osciloscopio (slot 1)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`osc_cfg`](datasheet_osc_cfg.md) | `rtl/osc_cfg.sv` | región de OSC: esclavo del bus de sistema (slot 1, 0x4010_0000) |
| [`osc_filter`](datasheet_osc_filter.md) ·&nbsp;*sin prosa* | `rtl/osc_filter.v` | — |

## `multitrigger` — región del multitrigger (slot 3)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`multitrigger_trig_src`](datasheet_multitrigger_trig_src.md) ·&nbsp;*sin prosa* | `rtl/multitrigger_trig_src.sv` | Selección de fuentes de 8 bits como MÁSCARA OR: |
| [`trigger_shield`](datasheet_trigger_shield.md) ·&nbsp;*sin prosa* | `rtl/trigger_shield.sv` | Módulo que toma configuración como parámetros. |
| [`multitrigger_event_logic`](datasheet_multitrigger_event_logic.md) ·&nbsp;*sin prosa* | `rtl/multitrigger_event_logic.v` | Este módulo tiene la tarea de dar la salida de eventos. |
| [`multitrigger_cfg`](datasheet_multitrigger_cfg.md) | `rtl/multitrigger_cfg.sv` | región de MULTITRIGGER: esclavo del bus de sistema |
| [`multitrigger_rp_scope_cfg`](datasheet_multitrigger_rp_scope_cfg.md) ·&nbsp;*sin prosa* | `rtl/multitrigger_rp_scope_cfg.sv` | — |
| [`rp_scope_multitrigger_com`](datasheet_rp_scope_multitrigger_com.md) ·&nbsp;*sin prosa* | `rtl/rp_scope_multitrigger_com.sv` | Cada uno de estos tiene como entradas dos canales de datos |

## `mca` — cadena de análisis de altura de pulso (slot 7)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`mca_div_restore`](datasheet_mca_div_restore.md) ·&nbsp;*sin prosa* | `rtl/mca_div_restore.sv` | divisor restaurador para el factor de forma (PSD) |
| [`mca_hist`](datasheet_mca_hist.md) ·&nbsp;*sin prosa* | `rtl/mca_hist.sv` | motor de histograma genérico (una implementación, N instancias) |
| [`mca_zoom`](datasheet_mca_zoom.md) ·&nbsp;*sin prosa* | `rtl/mca_zoom.sv` | de una feature de FW bits al bin de un eje de AW bits, con zoom |
| [`mca_discriminator`](datasheet_mca_discriminator.md) ·&nbsp;*sin prosa* | `rtl/mca_discriminator.sv` | acepta o rechaza un evento por el valor de UNA feature. |
| [`mca_pulse_feature`](datasheet_mca_pulse_feature.md) ·&nbsp;*sin prosa* | `rtl/mca_pulse_feature.sv` | segmentador de pulsos y extractor de características |
| [`mca_top`](datasheet_mca_top.md) | `rtl/mca_top.sv` | analizador multicanal: esclavo del bus de sistema (slot 7) |

## `event_ring` — ring de slots de evento en DDR (slot 2)

| Top | Archivo RTL | Qué es |
|---|---|---|
| [`event_window_capture`](datasheet_event_window_capture.md) ·&nbsp;*sin prosa* | `rtl/event_window_capture.sv` | extrae una ventana (pre + post) por trigger y la emite |
| [`event_stage_fifo`](datasheet_event_stage_fifo.md) ·&nbsp;*sin prosa* | `rtl/event_stage_fifo.sv` | buffer elastico entre la captura de ventana y el writer AXI. |
| [`event_slot_writer`](datasheet_event_slot_writer.md) ·&nbsp;*sin prosa* | `rtl/event_slot_writer.sv` | serializa un evento a un slot del ring en DDR. |
| [`event_ring_top`](datasheet_event_ring_top.md) | `rtl/event_ring_top.sv` | ring de slots de evento en DDR. Esclavo del bus de sistema. |

---

**20 páginas.** Las 5 de los tops de módulo —`integration_cfg`, `osc_cfg`, `multitrigger_cfg`, `mca_top` y `event_ring_top`— tienen escrito a mano **qué resuelve el bloque y por qué está hecho así**; las otras 15 todavía tienen el andamiaje con el `TODO`, así que de esas lo que hay es lo derivable del RTL.

Tres cosas que las páginas no dicen por sí solas:

- **`multitrigger_rp_scope_cfg` no se instancia en ningún top.** Se mantiene como referencia del mapa viejo; el camino vivo es `multitrigger_cfg` (slot 3) más `osc_cfg` (slot 1).
- **La sección de Fmax sale de `syn/outputs/metrics.txt`**, así que conviene regenerar *después* de `make syn` o `make sweep-all`. Si no hay datos de síntesis, la página lo dice y deja el comando.
- **Los cinco `sim/sva/*_sva.sv` están vacíos**: tienen el `bind` y un `// TODO:`, pero ninguna propiedad. Qué conviene escribir primero está en [`verificacion_formal.md`](../verificacion_formal.md).
