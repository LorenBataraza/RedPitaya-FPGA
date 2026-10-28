# Datasheet — `event_window_capture`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/event_window_capture.md.
     Regenerar:  make -C modulos/event_ring/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `event_window_capture` |
| Archivo | [`event_window_capture.sv`](../../modulos/event_ring/rtl/event_window_capture.sv) |
| Parámetros | 6 |
| Puertos | 22 (12 in / 10 out) |


![Interfaz de event_window_capture](figuras/event_window_capture_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`event_window_capture.sv`](../../modulos/event_ring/rtl/event_window_capture.sv)):

> event_window_capture — extrae una ventana (pre + post) por trigger y la emite
> como stream de muestras de 16 b.
>
> Reemplaza el rol de rp_bram_sm en el camino de eventos. La diferencia
> estructural: rp_bram_sm CONGELA un buffer de 16384 muestras y no puede
> capturar de nuevo hasta que el PS re-arma (K=1, ~252 us de tiempo muerto).
> Acá la ventana se copia a un stream aguas abajo y el bloque vuelve a estar
> listo en pre+post ciclos (~256 ns con S=32), sin intervencion del PS.
>
> UNA SOLA MEMORIA. El pre-trigger vive en un buffer circular que se escribe
> siempre; la lectura de la ventana sale del MISMO buffer, arrancando `pre`
> muestras atras del trigger. El puntero de lectura queda rezagado y, como se
> consume 1 muestra/ciclo y se produce <=1 muestra/ciclo, el rezago nunca
> crece: alcanza al productor y despues va en lock-step durante el post.
> Por eso la profundidad sólo tiene que cubrir `pre`, no `pre+post`.
>
> DOS CAUSAS DE PERDIDA, contadas por separado porque son diagnosticos
> distintos (ver docs/mt/):
>   drop_busy_o  el trigger cayo mientras se drenaba la ventana anterior.
>                Es el tiempo muerto INTRINSECO del PL: pre+post ciclos.
>   drop_full_o  aguas abajo no acepto el evento (stage llena, o sin creditos
>                de DDR porque el PS no drena). Es tiempo muerto del CONSUMIDOR.
>
> El handshake de aceptacion es en el SOF: si el consumidor no puede recibir la
> ventana entera en el momento del trigger, el evento se descarta ENTERO. Nunca
> se emite media ventana — un evento parcial en el ring seria indistinguible de
> uno bueno del lado del PS.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/event_window_capture.md, no aca. -->

**Qué hace.** Por cada trigger extrae una **ventana** de muestras —`pre` antes
y `post` desde el disparo— y la emite como un stream de 16 bits hacia
[`event_stage_fifo`](datasheet_event_stage_fifo.md). Es la primera etapa del
[`event_ring_top`](datasheet_event_ring_top.md) y lo que reemplaza el rol de
`rp_bram_sm` en el camino de eventos.

**La diferencia con el camino del scope es estructural, no de tamaño.**
`rp_bram_sm` **congela** un buffer de 16384 muestras y no puede volver a
capturar hasta que el PS lo re-arma: son ~**252 µs** de tiempo muerto por
evento. Acá la ventana se copia a un stream aguas abajo y el bloque vuelve a
estar listo en `pre+post` ciclos —~**256 ns**— sin que el PS intervenga. Eso es
lo que convierte el osciloscopio en un adquisidor de eventos.

**Una sola memoria para el pre y el post.** El pre-trigger vive en un buffer
circular que se escribe siempre, y la lectura de la ventana sale del **mismo**
buffer, arrancando `pre` muestras atrás del trigger. El puntero de lectura
queda rezagado y, como se consume una muestra por ciclo y se produce a lo sumo
una, el rezago **nunca crece**: alcanza al productor y después va en lock-step
durante el post. Por eso la profundidad sólo tiene que cubrir `pre`, no
`pre+post`.

**El evento se acepta o se descarta entero, y se decide en el SOF.** El
handshake con el consumidor ocurre en el ciclo del trigger: si la ventana
completa no entra, el evento se descarta completo. Nunca se emite media
ventana, porque un evento parcial en el ring sería **indistinguible de uno
bueno** del lado del PS.

**Las dos causas de pérdida se cuentan por separado** porque son diagnósticos
distintos: `drop_busy` es el trigger que cayó mientras se drenaba la ventana
anterior —el tiempo muerto **intrínseco** del PL, `pre+post` ciclos— y
`drop_full` es que aguas abajo no aceptó —la stage llena, o sin créditos de DDR
porque el PS no drena: tiempo muerto del **consumidor**—. Confundirlos llevaría
a agrandar el buffer cuando el problema es el software, o al revés.

> **El trigger se toma por FLANCO, y eso costó un bug en la placa.**
> `mt_trig_src` registra `adc_trig` como un **nivel**, y el estrobo
> de escritura que llega por el `sys_bus_cdc` puede durar más de un ciclo de
> `adc_clk`: cada trigger por software producía **dos** eventos, uno capturado
> y uno contado como `drop_busy`. Depender del ancho del pulso de un módulo que
> no controlamos es frágil; el flanco no.

La ventana tal como sale, con sus tiempos medidos, está en
[`event_ring_a_ventana.png`](../event_ring/figuras/transacciones/event_ring_a_ventana.png);
el diseño completo del camino, en
[`logica_de_captura_y_axi.md`](../event_ring/logica_de_captura_y_axi.md).
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `DW` | `integer` | `14` | ancho de la muestra del ADC |
| `N_CH` | `integer` | `2` | canales capturados por evento |
| `SW` | `integer` | `16` | ancho de la muestra en el stream (sign-ext) |
| `PRE_AW` | `integer` | `9` | buffer circular de pre-trigger: 2^PRE_AW |
| `S_AW` | `integer` | `11` | ancho de los contadores de muestras |
| `TS_W` | `integer` | `64` | ancho del timestamp |


#### Puertos

##### Reloj y reset

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `clk_i` | in | 1 | — |
| `rstn_i` | in | 1 | — |


##### Control

run_i mantiene vivo el pre-buffer y el drenaje de la ventana en vuelo. accept_trig_i habilita ACEPTAR triggers nuevos. Estan separados a proposito: en la parada ordenada (DRAINING) se baja accept_trig_i pero se deja run_i, asi el evento en vuelo termina en vez de quedar truncado a mitad de ventana.

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `run_i` | in | 1 | clk_i |  |
| `accept_trig_i` | in | 1 | clk_i |  |
| `pre_i` | in | 11 `[S_AW-1:0]` | clk_i | muestras antes del trigger |
| `post_i` | in | 11 `[S_AW-1:0]` | clk_i | muestras desde el trigger (incl.) |


##### Muestras (ya decimadas)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `dat_i` | in | 28 `[N_CH*DW-1:0]` | clk_i |  |
| `dv_i` | in | 1 | clk_i | muestra valida este ciclo |


##### Trigger

trig_i se toma por FLANCO, no por nivel. mt_trig_src registra `adc_trig <= trig_comb` (un NIVEL), y el strobe de escritura que llega por el sys_bus_cdc puede durar mas de un ciclo de adc_clk: en la placa, cada trigger por software producia DOS eventos (uno capturado y uno contado como drop_busy). Depender del ancho del pulso de un modulo que no controlamos es fragil; el flanco no.

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `trig_i` | in | 1 | clk_i |  |
| `snapshot_i` | in | 17 | clk_i | que fuente disparo |
| `ts_i` | in | 64 `[TS_W-1:0]` | clk_i | reloj libre de adquisicion |


##### Stream de salida

m_val_o/m_dat_o: una muestra de 16 b por ciclo, canales INTERCALADOS: ch0[k], ch1[k], ch0[k+1], ch1[k+1], ... El consumidor recibe (pre+post)*N_CH muestras entre sof y eof inclusive.

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `m_sof_o` | out | 1 | clk_i | coincide con la primera m_val_o |
| `m_eof_o` | out | 1 | clk_i | coincide con la ultima m_val_o |
| `m_val_o` | out | 1 | clk_i |  |
| `m_dat_o` | out | 16 `[SW-1:0]` | clk_i |  |
| `m_accept_i` | in | 1 | clk_i | Aceptacion: se muestrea SOLO en el ciclo del trigger. 1 = hay lugar para la ventana completa. |
| `m_ts_o` | out | 64 `[TS_W-1:0]` | clk_i | Metadatos del evento, validos junto con m_sof_o. |
| `m_snap_o` | out | 17 | clk_i |  |
| `m_nsamp_o` | out | 11 `[S_AW-1:0]` | clk_i | pre+post, muestras POR CANAL |


##### Diagnostico

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `drop_busy_o` | out | 1 | clk_i | pulso |
| `drop_full_o` | out | 1 | clk_i | pulso |
| `busy_o` | out | 1 | clk_i |  |
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

### 1.6 Transacciones

<!-- AUTO:transacciones -->
**LA VENTANA QUE CONGELA EL TRIGGER**

![LA VENTANA QUE CONGELA EL TRIGGER](../event_ring/figuras/transacciones/event_ring_a_ventana.png)

Que entra al modulo. Un evento es una ventana de 512 muestras por canal --32 antes del disparo y 480 despues, 4.10 us en total a 125 MSPS-- congelada en el instante en que el canal 0 cruza el umbral de 1229 cuentas (0.15 V a 8192 cuentas/V). El cruce de subida cae en la muestra 31 y el pre-buffer mide 32: la figura no dibuja esa coincidencia, la MIDE sobre el dato, y es lo que confirma que la ventana esta alineada con el disparo. El pico llega 69 muestras despues del cruce, con 2420 cuentas. La banda gris de la izquierda es la historia que el pre-buffer ya tenia guardada cuando el trigger llego: sin ella el flanco de subida no estaria en el archivo.

_Origen: campaña e2e, `software/datos/e2e_20260528_013404/principal/chunk_000000.npz`, evento 1._

**UNA VENTANA, UN SLOT**

![UNA VENTANA, UN SLOT](../event_ring/figuras/transacciones/event_ring_b_slot.png)

Que viaja. La ventana cruza tres bloques --captura, cola elastica de 4 eventos en vuelo y serializador-- y sale por AXI HP0 como exactamente 512 palabras de 64 b, en orden de direccion creciente para que el generador lineal del axi_wr_fifo las coloque sin saltos. La tabla son las palabras de este evento concreto, no un ejemplo: cabecera de 32 B, 2048 B de muestras, 2008 B de relleno y 8 B de footer. El relleno existe porque el slot tiene que ser potencia de dos para que la direccion salga de un shift, asi que de los 4096 B del slot solo 50 % son muestras. El FOOTER vale {~seq, seq} y es la MARCA DE COMMIT: como todas las escrituras salen por un unico master con un unico ID, AXI garantiza que se observan en orden, asi que si el footer esta bien formado todo lo anterior ya llego a DDR. Por eso el PS no necesita leer ningun registro por GP0 para saber que hay un evento nuevo. Los rangos de bits exactos de cada campo estan en la cabecera de `event_slot_writer.sv`; aca va el valor, que es lo que la figura puede mostrar y el RTL no.

_Origen: layout de `event_slot_writer.sv`, verificado con `software/API/modelo_rtl/ring_format.py`._

**EL RING EN DDR**

![EL RING EN DDR](../event_ring/figuras/transacciones/event_ring_c_ring.png)

Que sale. Los slots forman una cola productor/consumidor en DDR: la PL avanza WR_SLOT al terminar de escribir y el PS avanza RD_SLOT al terminar de leer, y los dos son contadores LIBRES de 32 b --la resta cierra en modulo 2^32 aunque hayan dado la vuelta, que es exactamente lo que hace el comparador de creditos del RTL--. En el dibujo hay 4 slots ocupados. El rectangulo verde de cada slot lleno es el footer. La diferencia con el esquema anterior (K=1, tau = 252.7 us) es que aca la PL no espera a nadie: mientras queden creditos sigue capturando, y el tiempo muerto deja de depender de la latencia del lector. Es un esquema: la cantidad de slots del dibujo es ilustrativa, la real sale de RING_SZ / SLOT_SZ.

_Origen: esquema; los créditos salen de `ring_format.credits_used()`._

**LA TRANSACCION COMPLETA**

![LA TRANSACCION COMPLETA](../event_ring/figuras/transacciones/event_ring_transaccion.png)

Las tres preguntas en una imagen: que entra, que viaja y que sale. Es la que va al informe si entra una sola.

_Origen: las tres anteriores, en una figura._

---

Las figuras **recalculan cada número al dibujar** en vez de tomarlo escrito. Las genera [`transacciones_event_ring.py`](../event_ring/figuras/transacciones/transacciones_event_ring.py); de dónde sale el dato de cada una está en la columna «Datos» de [`README.md`](../event_ring/figuras/transacciones/README.md); los epígrafes completos, en [`epigrafes.txt`](../event_ring/figuras/transacciones/epigrafes.txt).
<!-- /AUTO:transacciones -->

### 1.7 Waveforms

<!-- AUTO:ondas -->
_Sin figuras de ondas._ Se generan con un script en `docs/event_ring/figuras/ondas/`, que saca las ondas de un VCD de los testbenches del módulo; el patrón está en [`docs/figuras/ondas.py`](../figuras/ondas.py).
<!-- /AUTO:ondas -->

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/event_ring/figuras/ondas/ondas_event_ring.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/event_ring/work wave TB=<tb>   # mirar en Questa
       make -C modulos/event_ring/work vcd  TB=<tb>   # VCD exportable -->

### 1.8 Verificación realizada

<!-- AUTO:verificacion -->
Todo corre en batch y se chequea el `RESULT: PASS` del testbench; las ondas quedan en `work/waves/<tb>.wlf`.

```bash
make -C modulos/event_ring/work            # los 4 testbenches
make -C modulos/event_ring/work cov        # + cobertura
make -C modulos/event_ring/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_event_window_capture`](../../modulos/event_ring/sim/tb_event_window_capture.sv) | `event_window_capture` | 7 | 25 | vectores a mano | **sí** |
| [`tb_event_stage_fifo`](../../modulos/event_ring/sim/tb_event_stage_fifo.sv) | `event_stage_fifo` | — | 26 | vectores a mano |  |
| [`tb_event_slot_writer`](../../modulos/event_ring/sim/tb_event_slot_writer.sv) | `event_slot_writer` | 9 | 32 | vectores a mano |  |
| [`tb_event_ring_top`](../../modulos/event_ring/sim/tb_event_ring_top.sv) | `event_ring_top` | — | 39 | vectores a mano |  |


**122 casos con nombre** en 4 testbenches (16 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_event_window_capture`](../../modulos/event_ring/sim/tb_event_window_capture.sv): 1) cantidad exacta de muestras emitidas = (pre+post, 2) sof/eof en la primera y ultima muestra, una sola, 3) ALINEACION, 4) intercalado de canales ch0,ch1,ch0,ch1, 5) drop_busy, 6) drop_full, 7) pre=0 (captura solo post) y ventana impar (no mu.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_event_ring.sv`](../../modulos/event_ring/sim/sva/bind_event_ring.sv)
- [`event_ring_top_sva.sv`](../../modulos/event_ring/sim/sva/event_ring_top_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`event_ring/sim/VERIFICACION.md`](../../modulos/event_ring/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
