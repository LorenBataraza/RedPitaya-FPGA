# Datasheet — `event_slot_writer`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     Regenerar:  make -C modulos/event_ring/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `event_slot_writer` |
| Archivo | [`event_slot_writer.sv`](../../modulos/event_ring/rtl/event_slot_writer.sv) |
| Parámetros | 5 |
| Puertos | 21 (12 in / 9 out) |


![Interfaz de event_slot_writer](figuras/event_slot_writer_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`event_slot_writer.sv`](../../modulos/event_ring/rtl/event_slot_writer.sv)):

> event_slot_writer — serializa un evento a un slot del ring en DDR.
>
> Emite EXACTAMENTE 2^(slot_shift-3) palabras de 64 b por evento, en orden de
> direccion creciente, para que el generador lineal del axi_wr_fifo las coloque
> sin saltos:
>
>   w0            timestamp[63:0]
>   w1            {flags[7:0], n_ch[7:0], n_samp[15:0], seq[31:0]}
>   w2            {event_id[31:0], 15'b0, snapshot[16:0]}
>   w3            0 (reservado)
>   w4 ..         muestras int16, 4 por palabra, canales intercalados:
>                 [15:0]=ch0[k] [31:16]=ch1[k] [47:32]=ch0[k+1] [63:48]=ch1[k+1]
>   .. relleno    ceros hasta la anteultima palabra
>   ultima        FOOTER {~seq[31:0], seq[31:0]}
>
> COMO SE SABE QUE EL SLOT ESTA COMPLETO — y por que NO hace falta el BRESP.
>
> El plan original decia "incrementar wr_slot recien con el BRESP del ultimo
> burst". Es correcto pero inaplicable: ni axi_wr_fifo ni axi_master exponen el
> canal B (axi_wr_fifo.v solo saca werr/wrdy), asi que no hay forma de
> observarlo sin tocar RTL compartido.
>
> La solucion estandar de descriptor-ring es mejor y ademas mas barata: se
> escribe una MARCA AL FINAL. Todas las escrituras salen por un unico master
> con un unico ID hacia el mismo esclavo, y AXI garantiza que las escrituras
> con el mismo ID se observan en orden. Entonces, si el PS ve el footer del
> slot i con el `seq` esperado, todo lo que esta antes del footer YA esta en
> DDR. El footer es el commit.
>
> Ventaja adicional: el PS no necesita leer NINGUN registro por GP0 para saber
> que hay un evento nuevo. Polea el footer del proximo slot directamente en
> DDR, que es mas rapido que una lectura de registro (2.3 us) y saca el bus GP0
> del lazo caliente por completo. `wr_slot_o` queda como diagnostico.
>
> El footer lleva {~seq, seq}: una lectura rota o vieja se detecta comparando
> las dos mitades, sin depender de que el valor "0" sea especial.
>
> CONTROL DE FLUJO. Sin creditos el writer NO descarta: se frena. La
> contrapresion sube al stage y el descarte ocurre arriba de todo, en la
> captura, donde se puede descartar el evento ENTERO y contarlo. Descartar a
> mitad del slot dejaria basura indistinguible de un evento bueno.
<!-- /AUTO:resumen -->

<!-- A mano: qué problema resuelve el bloque, cómo encaja en la cadena y las
     dos o tres decisiones de diseño que explican por qué está hecho así. -->

**Qué hace.** TODO

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `SW` | `integer` | `16` |  |
| `S_AW` | `integer` | `11` |  |
| `TS_W` | `integer` | `64` |  |
| `N_CH` | `integer` | `2` |  |
| `WCW` | `integer` | `16` | ancho del contador de palabras por slot |


#### Puertos

##### Señales

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `clk_i` | in | 1 | — |  |
| `rstn_i` | in | 1 | — |  |
| `flush_i` | in | 1 | clk_i | flush_i: vacia la FSM y el dato en vuelo (parada de adquisicion). clr_cnt_i: resetea wr_slot_o/seq_o. SEPARADO de flush_i a proposito — wr_slot vive en pareja con el rd_slot que publica el PS, y resetear uno solo deja la resta de creditos en underflow (ocupados ~ 2^32) y el ring descartando todo. Un stop/start NO tiene por que invalidar el ring: los contadores solo se reinician cuando el PS pide clr explicitamente, y ahi el top resetea los DOS al mismo tiempo. |
| `clr_cnt_i` | in | 1 | clk_i |  |


##### Geometria del slot (latcheada por el top con la adquisicion parada)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `slot_shift_i` | in | 5 | clk_i | log2(bytes por slot), >= 6 |


##### Stage

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `s_meta_val_i` | in | 1 | clk_i |  |
| `s_ts_i` | in | 64 `[TS_W-1:0]` | clk_i |  |
| `s_snap_i` | in | 17 | clk_i |  |
| `s_nsamp_i` | in | 11 `[S_AW-1:0]` | clk_i | muestras POR CANAL |
| `s_meta_rd_o` | out | 1 | clk_i |  |
| `s_dat_i` | in | 16 `[SW-1:0]` | clk_i |  |
| `s_dat_rd_o` | out | 1 | clk_i |  |


##### Creditos

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `credit_ok_i` | in | 1 | clk_i | hay al menos un slot libre en DDR |


##### Stream de 64 b hacia el axi_wr_fifo

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `wr_dat_o` | out | 64 | clk_i |
| `wr_val_o` | out | 1 | clk_i |
| `wr_rdy_i` | in | 1 | clk_i |


##### Estado

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `wr_slot_o` | out | 32 | clk_i | contador LIBRE de slots escritos |
| `seq_o` | out | 32 | clk_i | secuencia del proximo evento |
| `no_credit_o` | out | 1 | clk_i | 1 = frenado por falta de creditos |
| `busy_o` | out | 1 | clk_i |  |
| `err_slot_ovf_o` | out | 1 | clk_i | Sticky: la ventana no entra en el slot configurado. Sin este guard, un slot_shift demasiado chico pisa el slot siguiente y el PS lee eventos corruptos sin ninguna indicacion. |
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
| [`tb_event_stage_fifo`](../../modulos/event_ring/sim/tb_event_stage_fifo.sv) | `event_stage_fifo` | — | 26 | vectores a mano |  |
| [`tb_event_slot_writer`](../../modulos/event_ring/sim/tb_event_slot_writer.sv) | `event_slot_writer` | 9 | 32 | vectores a mano | **sí** |
| [`tb_event_ring_top`](../../modulos/event_ring/sim/tb_event_ring_top.sv) | `event_ring_top` | — | 39 | vectores a mano |  |


**122 casos con nombre** en 4 testbenches (16 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_event_slot_writer`](../../modulos/event_ring/sim/tb_event_slot_writer.sv): 1) cantidad exacta de palabras por slot = 2^(slot_s, 2) cabecera, 3) empaquetado 4 muestras/palabra, primera muestra , 4) relleno de ceros entre datos y footer, 5) FOOTER = ultima palabra, y vale {~seq, seq}, 6) IDEMPOTENCIA ANTE CONTRAPRESION, 7) sin creditos el writer SE FRENA (no descarta) y , 8) seq y wr_slot avanzan de a uno por evento, 9) err_slot_ovf con ventana que no entra en el slot.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_event_ring.sv`](../../modulos/event_ring/sim/sva/bind_event_ring.sv)
- [`event_ring_top_sva.sv`](../../modulos/event_ring/sim/sva/event_ring_top_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`event_ring/sim/VERIFICACION.md`](../../modulos/event_ring/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
