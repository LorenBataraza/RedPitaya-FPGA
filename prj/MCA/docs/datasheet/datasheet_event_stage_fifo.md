# Datasheet — `event_stage_fifo`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     Regenerar:  make -C modulos/event_ring/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `event_stage_fifo` |
| Archivo | [`event_stage_fifo.sv`](../../modulos/event_ring/rtl/event_stage_fifo.sv) |
| Parámetros | 5 |
| Puertos | 21 (13 in / 8 out) |


![Interfaz de event_stage_fifo](figuras/event_stage_fifo_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`event_stage_fifo.sv`](../../modulos/event_ring/rtl/event_stage_fifo.sv)):

> event_stage_fifo — buffer elastico entre la captura de ventana y el writer AXI.
>
> POR QUE EXISTE. La captura produce muestras al ritmo del ADC y no se puede
> frenar (las muestras del post-trigger llegan cuando llegan). El writer, en
> cambio, se frena: espera creditos de DDR y espera al axi_wr_fifo. Sin un
> buffer en el medio, cualquier hipo del writer corrompe la ventana en vuelo.
> Con E eventos de capacidad, la captura puede empezar el evento N+1 mientras
> el writer todavia drena el N.
>
> GARANTIA DE EVENTO ENTERO. `s_accept_o` es la respuesta a "¿entra una ventana
> COMPLETA?" y se consulta en el ciclo del trigger, antes de aceptar nada. Si
> da 0 el evento se descarta entero aguas arriba. Nunca se guarda media
> ventana: un evento parcial en el ring seria indistinguible de uno bueno del
> lado del PS.
>
> Dos colas en paralelo: una de muestras (BRAM) y una de metadatos (E entradas,
> registros). El writer las consume desacopladas — primero lee el metadato para
> armar la cabecera, despues drena las muestras.
<!-- /AUTO:resumen -->

<!-- A mano: qué problema resuelve el bloque, cómo encaja en la cadena y las
     dos o tres decisiones de diseño que explican por qué está hecho así. -->

**Qué hace.** TODO

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `SW` | `integer` | `16` | ancho de muestra |
| `S_AW` | `integer` | `11` | ancho del contador de muestras/canal |
| `TS_W` | `integer` | `64` |  |
| `DATA_AW` | `integer` | `12` | cola de muestras: 2^DATA_AW palabras |
| `E` | `integer` | `4` | eventos simultaneos en vuelo |


#### Puertos

##### Señales

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `clk_i` | in | 1 | — |  |
| `rstn_i` | in | 1 | — |  |
| `flush_i` | in | 1 | clk_i | vacia todo (parada de adquisicion) |
| `win_len_i` | in | 14 `[S_AW+2:0]` | clk_i | longitud de ventana en MUESTRAS TOTALES (pre+post)*N_CH, para el chequeo de espacio en el SOF |


##### Escritura (desde event_window_capture)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `s_accept_o` | out | 1 | clk_i | ¿entra una ventana completa? |
| `s_val_i` | in | 1 | clk_i |  |
| `s_sof_i` | in | 1 | clk_i |  |
| `s_eof_i` | in | 1 | clk_i |  |
| `s_dat_i` | in | 16 `[SW-1:0]` | clk_i |  |
| `s_ts_i` | in | 64 `[TS_W-1:0]` | clk_i | valido con s_sof_i |
| `s_snap_i` | in | 17 | clk_i | valido con s_sof_i |
| `s_nsamp_i` | in | 11 `[S_AW-1:0]` | clk_i | valido con s_sof_i |


##### Lectura (hacia event_slot_writer)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `m_meta_val_o` | out | 1 | clk_i | hay al menos un evento COMPLETO |
| `m_ts_o` | out | 64 `[TS_W-1:0]` | clk_i |  |
| `m_snap_o` | out | 17 | clk_i |  |
| `m_nsamp_o` | out | 11 `[S_AW-1:0]` | clk_i |  |
| `m_meta_rd_i` | in | 1 | clk_i | pop del metadato (fin del evento) |
| `m_dat_o` | out | 16 `[SW-1:0]` | clk_i |  |
| `m_dat_rd_i` | in | 1 | clk_i | pop de una muestra |


##### Diagnostico

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `lvl_o` | out | 13 `[DATA_AW:0]` | clk_i | ocupacion de la cola de muestras |
| `ev_lvl_o` | out | 3 `[$clog2(E+1)-1:0]` | clk_i | eventos en vuelo |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
No hay un mapa de registros para este módulo en `docs/event_ring/`. Si es un esclavo del bus de sistema, falta escribirlo; si no lo es, esta sección no aplica.
<!-- /AUTO:regmap -->

### 1.4 Clock domains

<!-- AUTO:clocks -->
| Puerto | Qué es | Polaridad |
|---|---|---|
| `clk_i` | reloj |  |
| `rstn_i` | reset | activo-bajo |


**Un solo dominio.** Todos los puertos de datos y de control son síncronos a `clk_i`: no hay cruce de dominio dentro de este módulo.
<!-- /AUTO:clocks -->

<!-- A mano: si hay más de un reloj, cuál es el cruce, con qué se sincroniza y
     qué se asume de la relación de frecuencias. Si hay uno solo, borrar. -->

### 1.5 Frecuencia máxima de trabajo

<!-- AUTO:timing -->
Sin datos de síntesis todavía. Correr:

```bash
make -C modulos/event_ring/work syn
make -C modulos/event_ring/work sweep-all
```

y volver a generar esta página.
<!-- /AUTO:timing -->

<!-- A mano: qué hay en el camino crítico y qué se haría para romperlo si
     hubiera que subir la frecuencia. -->

### 1.6 Waveforms

<!-- AUTO:ondas -->
_Sin figuras de ondas._ Se generan con un script en `docs/event_ring/figuras/ondas/`, que saca las ondas de un VCD de los testbenches del módulo; el patrón está en [`docs/figuras/ondas.py`](../figuras/ondas.py).
<!-- /AUTO:ondas -->

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/event_ring/figuras/ondas/ondas_event_ring.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/event_ring/work wave TB=<tb>   # mirar en Questa
       make -C modulos/event_ring/work vcd  TB=<tb>   # VCD exportable -->

### 1.7 Verificación realizada

<!-- AUTO:verificacion -->
Todo corre en batch y se chequea el `RESULT: PASS` del testbench; las ondas quedan en `work/waves/<tb>.wlf`.

```bash
make -C modulos/event_ring/work            # los 4 testbenches
make -C modulos/event_ring/work cov        # + cobertura
make -C modulos/event_ring/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_event_window_capture`](../../modulos/event_ring/sim/tb_event_window_capture.sv) | `event_window_capture` | 7 | 25 | vectores a mano |  |
| [`tb_event_stage_fifo`](../../modulos/event_ring/sim/tb_event_stage_fifo.sv) | `event_stage_fifo` | — | 26 | vectores a mano | **sí** |
| [`tb_event_slot_writer`](../../modulos/event_ring/sim/tb_event_slot_writer.sv) | `event_slot_writer` | 9 | 32 | vectores a mano |  |
| [`tb_event_ring_top`](../../modulos/event_ring/sim/tb_event_ring_top.sv) | `event_ring_top` | — | 39 | vectores a mano |  |


**122 casos con nombre** en 4 testbenches (16 escenas). La lista completa, caso por caso, está en el plan de verificación.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_event_ring.sv`](../../modulos/event_ring/sim/sva/bind_event_ring.sv)
- [`event_ring_top_sva.sv`](../../modulos/event_ring/sim/sva/event_ring_top_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`event_ring/sim/VERIFICACION.md`](../../modulos/event_ring/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
