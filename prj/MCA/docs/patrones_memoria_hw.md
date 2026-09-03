# Patrones de memoria en hardware digital

Catálogo de los patrones de elemento de memoria que aparecen en diseño RTL,
organizados por **qué desacoplan** — porque de eso, y no del tipo de memoria,
sale el criterio de dimensionamiento.

Este documento existe por una razón práctica: justificar el tamaño de los
buffers internos de este proyecto. La conclusión que lo ordena todo es que
**"¿de qué tamaño hago el buffer?" no tiene una sola respuesta**: tiene cuatro,
y cuál aplica depende de qué está desacoplando la memoria. Confundirlas lleva a
dimensionar con teoría de colas algo que en realidad es una cuenta determinista,
o al revés — a poner un número arbitrario donde hacía falta un modelo.

Cada patrón lleva **dónde está instanciado en este repo**, para que sirva
también de mapa del propio diseño.

Documentos hermanos:

| Documento | Qué contiene |
|---|---|
| [`mca/decisiones_diseno_mca.md`](mca/decisiones_diseno_mca.md) | el **por qué** del MCA |
| [`multitrigger/arquitectura_adquisicion_software.md`](multitrigger/arquitectura_adquisicion_software.md) | el presupuesto de latencia y el techo medido |
| [`multitrigger/orden_arm_trigger_captura.md`](multitrigger/orden_arm_trigger_captura.md) | la FSM de captura K=1 y su race |
| [`event_ring/diseno_y_register_map.md`](event_ring/diseno_y_register_map.md) | el ring de slots que reemplaza al K=1 |
| [`bus_sistema_redpitaya.md`](bus_sistema_redpitaya.md) | el bus y su CDC por slot |

---

## 1. La tesis: el patrón fija el criterio

| Grupo | Qué desacopla | Cómo se dimensiona | Cómo falla |
|---|---|---|---|
| **1. Tiempo** | dos caminos de distinta latencia | **determinista y exacto** — no hay probabilidad | no falla: si el tamaño es correcto, es correcto siempre |
| **2. Tasa** | productor y consumidor con ritmos distintos | teoría de colas (ρ, `K ≈ log P / log ρ`) o cobertura de peor caso | desborde → pérdida o contrapresión |
| **3. Coherencia** | el instante de lectura del de escritura | atomicidad — **la capacidad es irrelevante** | dato rasgado (*torn read*) |
| **4. Hazard RMW** | la latencia de la RAM de la tasa de acceso | profundidad del pipeline de la memoria | cuenta perdida, silenciosa |

La pregunta que hay que hacerse antes de elegir un número es siempre la misma:

> **¿El bloqueo que este buffer absorbe tiene cota superior?**
>
> - **Sí** → dimensionamiento determinista: `K = cota`. Pérdida **cero**, sin
>   nueves ni probabilidades.
> - **No** → ningún `K` finito garantiza nada. Hay que modelar la cola *y*
>   contar la pérdida para poder corregirla.

---

## 2. Grupo 1 — Memoria como tiempo

Nunca se llena y nunca pierde. El tamaño sale de una resta de latencias.

| Patrón | Para qué | Tamaño | Dónde en el repo |
|---|---|---|---|
| **Línea de retardo** (shift register) | alinear dos caminos de distinta latencia | = diferencia de latencia, exacta | `src_now_d` en [`multitrigger_event_logic.v:137`](../rtl/mine/multitrigger/multitrigger_event_logic.v#L137) |
| **Registros de pipeline** | cortar el camino crítico | 1 por etapa | `a1/a2/a3`, `v1/v2/v3` en [`mca_hist.sv`](../rtl/mine/mca/mca_hist.sv) |
| **Registro de salida sostenido** | mantener el dato hasta que el consumidor lo tome | 1 | `rd_data_r` en [`mca_hist.sv`](../rtl/mine/mca/mca_hist.sv) |
| **Buffer circular de pre-trigger** | mirar *hacia atrás* desde un evento | = ventana pre-trigger máxima | `pre_buf` en [`event_window_capture.sv:101`](../rtl/mine/event_ring/event_window_capture.sv#L101) |
| **Línea de retardo configurable** | delay post-trigger | contador, no memoria | `adc_dly_cnt` en [`rp_bram_sm.v:116`](../../../rtl_250/classic/rp_bram_sm.v#L116) |
| **Line buffer / stencil** | formar una ventana 2D en video | filas del kernel × ancho de fila | *(no usado)* |

### El caso interesante: el buffer circular de pre-trigger

Es el patrón que más se malinterpreta, porque *parece* una cola y no lo es. Un
buffer circular que se escribe siempre **no se llena: sobrescribe**. Su
profundidad no tiene ninguna relación con la tasa de eventos; sólo fija cuánto
podés mirar hacia atrás.

Dos consecuencias que valen para este proyecto:

- La BRAM del scope (`RSZ=14` → 16384 muestras/canal) está dimensionada 512×
  por encima de la ventana que realmente se usa (8+24 = 32 muestras). Lo que
  limitaba la adquisición a un evento a la vez **nunca fue la memoria**, era la
  FSM de freeze de [`rp_bram_sm.v`](../../../rtl_250/classic/rp_bram_sm.v).
- En [`event_window_capture.sv`](../rtl/mine/event_ring/event_window_capture.sv)
  el pre-buffer es de sólo `2^9 = 512` muestras y alcanza para ventanas de
  `pre+post` mucho mayores. El motivo está en la cabecera del módulo: el puntero
  de lectura arranca `pre` muestras atrás y, como se consume 1 muestra/ciclo y
  se produce ≤1 muestra/ciclo, **el rezago nunca crece** — alcanza al productor
  y va en lock-step durante el post. La profundidad sólo tiene que cubrir `pre`,
  no `pre+post`. Esa es la diferencia entre dimensionar por intuición y
  dimensionar por el argumento correcto.

---

## 3. Grupo 2 — Memoria como desacople de tasa

Acá sí se llena, sí se pierde, y hay que modelarla.

| Patrón | Para qué | Tamaño | Dónde en el repo |
|---|---|---|---|
| **Skid buffer** (elástico, K=1) | absorber un bloqueo acotado en **1 ciclo** | K = 1 → pérdida **cero**, determinista | *(ausente — ver §7)* |
| **FIFO síncrona** | desacoplar productor/consumidor | M/D/1/K, o cobertura de ráfaga | `mem`/`wr_ptr`/`rd_ptr` en [`event_stage_fifo.sv:69`](../rtl/mine/event_ring/event_stage_fifo.sv#L69) |
| **FIFO de metadatos paralela** | desacoplar cabecera de payload | E entradas en registros | `meta_ts`/`meta_snap` en [`event_stage_fifo.sv:112`](../rtl/mine/event_ring/event_stage_fifo.sv#L112) |
| **Ring de descriptores en DDR** | cola grande fuera del chip | N_SLOTS × tamaño de slot | [`event_ring_top.sv`](../rtl/mine/event_ring/event_ring_top.sv) |
| **Derandomizador** | absorber la ráfaga de **Poisson** antes de un readout de latencia fija | ocupación de cola vs tiempo muerto | el ring completo |
| **Ping-pong / doble banco** | productor llena A, consumidor vacía B | 2 × ventana | *(ausente — el ring lo generaliza)* |
| **Control por créditos** | frenar al productor antes de desbordar | umbral = latencia del lazo | `occupied = wr_slot - rd_slot` en [`event_ring_top.sv:122`](../rtl/mine/event_ring/event_ring_top.sv#L122) |
| **Cola de batches en software** | desacoplar lector de escritor | profundidad × tamaño de batch | `free_q`/`full_q` en [`reader.py`](../software/mca/reader.py) |

### Las tres reglas que gobiernan este grupo

**Regla 1 — Un buffer nunca compra throughput, compra tolerancia a
fluctuación.** El techo de tasa es `1/τ` del consumidor, y no se mueve con `K`.
Si `ρ = n·τ > 1`, ningún tamaño finito sirve: la pérdida tiende a `1 − 1/ρ` y el
buffer sólo demora el desborde. Para subir el techo hay que bajar `τ`.

**Regla 2 — Con `ρ < 1`, la pérdida cae geométricamente.** Tomando la cota
conservadora M/M/1/K (el servicio determinista M/D/1/K es mejor todavía):

```
P_loss = (1−ρ)·ρ^K / (1 − ρ^(K+1))        de donde        K ≈ log P / log ρ
```

A `ρ = 0.5`: `K=1` → 33 %, `K=4` → 3.2 %, `K=8` → 0.20 %, `K=16` → 3×10⁻⁶.
El rango rentable es `0.5 < ρ < 1`, donde un `K` de una decena convierte una
eficiencia del 67 % en ~100 %.

**Regla 3 — Si el bloqueo está acotado, no hay que modelar nada.** Un
`rd_i` de un ciclo se cubre con `K = 1` y la pérdida pasa a ser exactamente cero.
Es el caso del skid buffer, y es la razón por la que vale la pena clasificar
antes de calcular.

### Contrapresión vs descarte: dónde se decide

Un sistema con pérdida tiene que elegir **dónde** perder, y la respuesta no es
obvia. El criterio que sigue el `event_ring` está en la cabecera de
[`event_slot_writer.sv`](../rtl/mine/event_ring/event_slot_writer.sv):

> Sin créditos el writer **no descarta: se frena**. La contrapresión sube al
> stage y el descarte ocurre arriba de todo, en la captura, donde se puede
> descartar el evento **entero** y contarlo.

La razón es de integridad, no de eficiencia: descartar a mitad de un slot deja
basura indistinguible de un evento bueno del lado del consumidor. De ahí el
handshake de aceptación en el SOF (`s_accept_o` en
[`event_stage_fifo.sv:167`](../rtl/mine/event_ring/event_stage_fifo.sv#L167)),
que responde *"¿entra una ventana completa?"* **antes** de aceptar la primera
muestra.

**Corolario general:** la contrapresión se propaga hasta el único punto donde el
descarte es atómico, y ahí se cuenta. Es el mismo principio que hace que un
evento perdido sea una *normalización* y no una falla.

### Contar la pérdida por causa, no en total

`event_window_capture` separa dos contadores que podrían haber sido uno solo:

| Contador | Causa | Qué diagnostica |
|---|---|---|
| `drop_busy_o` | el trigger cayó mientras se drenaba la ventana anterior | tiempo muerto **intrínseco del PL** (`pre+post` ciclos) |
| `drop_full_o` | aguas abajo no aceptó (stage llena, o sin créditos de DDR) | tiempo muerto del **consumidor** (el PS no drena) |

Son acciones correctivas distintas: el primero se arregla acortando la ventana,
el segundo agrandando el ring o acelerando el software. Un contador agregado no
distingue, y por lo tanto no sirve para decidir.

---

## 4. Grupo 3 — Memoria como coherencia

El problema es la atomicidad, no la capacidad. Un buffer más grande no ayuda.

| Patrón | Problema | Dónde en el repo |
|---|---|---|
| **Registro shadow** | leer un contador de 64 b por un bus de 32 b sin que se rasgue entre las dos mitades | `rt_hi_shadow`/`lt_hi_shadow`/`dt_hi_shadow` en [`mca_top.sv:304`](../rtl/mine/mca/mca_top.sv#L304) |
| **Snapshot / captura de evento** | congelar el estado en el instante exacto del trigger | `trig_snapshot` en [`multitrigger_event_logic.v:138`](../rtl/mine/multitrigger/multitrigger_event_logic.v#L138), `adc_wp_trig` en [`rp_bram_sm.v:91`](../../../rtl_250/classic/rp_bram_sm.v#L91) |
| **Freeze para lectura coherente** | leer una memoria que se está escribiendo a 125 MS/s | `adc_we <= 0` en [`rp_bram_sm.v:67`](../../../rtl_250/classic/rp_bram_sm.v#L67) |
| **Marca de commit al final** (*footer*) | saber que un bloque de DDR está completo sin observar el BRESP | footer `{~seq, seq}` en [`event_slot_writer.sv`](../rtl/mine/event_ring/event_slot_writer.sv) |
| **Config congelada en STOPPED** | que no convivan dos geometrías en el mismo ring | latch de `SLOT_BASE`/`RING_SZ`/`PRE`/`POST` en [`event_ring_top.sv`](../rtl/mine/event_ring/event_ring_top.sv) |

### El footer como patrón general

Vale la pena aislarlo porque es reutilizable y poco conocido fuera del mundo de
los descriptor rings. El problema: el consumidor tiene que saber si un bloque
escrito por DMA ya está completo, sin acceso al canal de respuesta del bus.

La solución: **escribir una marca al final**. Como todas las escrituras salen por
un único master con un único ID hacia el mismo esclavo, AXI garantiza que se
observan en orden; si el footer del slot `i` está, todo lo anterior ya está en
DDR. El footer *es* el commit.

Dos detalles que lo hacen robusto y que se copian tal cual:

- El valor es `{~seq, seq}` — **redundancia complementaria**. Una lectura rota o
  vieja se detecta comparando las dos mitades, sin depender de que el `0` sea un
  valor especial (que no lo es: un slot recién borrado también vale 0).
- El consumidor **polea el footer en DDR**, no un registro por el bus. Eso saca
  el GP0 del lazo caliente por completo: contra los 2.3 µs medidos de una
  lectura de registro, un acceso a DDR cacheado es más barato.

---

## 5. Grupo 4 — Memoria con hazard de lectura-modificación-escritura

| Patrón | Problema | Solución | Dónde |
|---|---|---|---|
| **Acumulador / histograma en BRAM** | dos incrementos al mismo bin dentro de la latencia de la RAM: el segundo lee un valor viejo y la cuenta se pierde | **forwarding / bypass** de 2 etapas | `fwd2`/`fwd3` en [`mca_hist.sv:133-134`](../rtl/mine/mca/mca_hist.sv#L133-L134) |
| **Contador saturante** | overflow silencioso que arruina el espectro | saturar en vez de dar la vuelta | `nxt = (&cur) ? cur : cur + 1` en [`mca_hist.sv`](../rtl/mine/mca/mca_hist.sv) |

El pipeline de incremento de `mca_hist` tiene 3 etapas (dirección → dato →
escritura), así que un incremento al mismo bin puede llegar 1 o 2 ciclos después
de otro y leer un valor obsoleto. Los dos puentes de forwarding cubren
exactamente esas dos distancias; a partir de la distancia 3 la memoria ya está
actualizada.

**Es el mismo patrón que el bypass EX→EX/MEM→EX de un pipeline de CPU.** Si
alguna vez se profundiza el pipeline del histograma, hay que agregar un puente
por cada etapa nueva — es la clase de detalle que no falla en simulación con
eventos espaciados y sí falla en la placa con una fuente intensa.

---

## 6. Handshake y control de flujo

Los patrones de memoria no viven solos: el protocolo que los conecta determina
si hay contrapresión o descarte.

| Patrón | Cuándo | Nota |
|---|---|---|
| **valid sin ready** | el consumidor *nunca* puede frenar | el productor tiene que descartar; es el caso del ADC |
| **valid/ready** (AXI-Stream) | contrapresión de un ciclo | necesita skid buffer para no perder throughput |
| **Créditos** | el consumidor está lejos (DDR, red) | `occupied < n_slots` en [`event_ring_top.sv:123`](../rtl/mine/event_ring/event_ring_top.sv#L123) |
| **Ack de latencia fija** | esclavo de bus simple | *ver abajo* |
| **Sincronizador de 2 flops** | 1 bit entre dominios de reloj | **nunca** para un bus multi-bit |
| **FIFO asíncrona con punteros Gray** | bus multi-bit entre dominios | el `sys_bus_cdc` por slot |
| **Holdoff / monoestable retriggerable** | inhibir durante un tiempo fijo | `cnt`/`active` en [`trigger_shield.sv:31`](../rtl/mine/multitrigger/trigger_shield.sv#L31) |
| **Histéresis (Schmitt)** | evitar re-disparo por ruido | `armed` en [`mca_pulse_feature.sv`](../rtl/mine/mca/mca_pulse_feature.sv) |

### El ack de latencia fija, y por qué importa acá

Tanto [`mca_top.sv`](../rtl/mine/mca/mca_top.sv) como
[`event_ring_top.sv`](../rtl/mine/event_ring/event_ring_top.sv) generan el ack
del bus con un shift register **incondicional**, sin ninguna ruta de ack por
sub-bloque. No es una simplificación: un esclavo que no hace ack no produce sólo
una lectura mala, **deja el CDC del slot desincronizado** y ese slot no acepta
más transacciones (ver [`bus_sistema_redpitaya.md`](bus_sistema_redpitaya.md)
§7.1). Es una falla que se manifiesta como un cuelgue del bus, muy lejos de su
causa.

Regla general: en un esclavo de bus con CDC, **el ack no puede depender de nada
que pueda no ocurrir**.

### Cuándo *no* hace falta CDC

Vale registrarlo porque el instinto lleva a poner sincronizadores de más. En el
`event_ring` hay un solo dominio de reloj: `assign axi_clk = adc_clk_i` en
[`rp_scope_multitrigger_com.sv`](../rtl/mine/multitrigger/rp_scope_multitrigger_com.sv),
y el bus llega ya sincronizado a `adc_clk` por el `sys_bus_cdc` del slot. Captura,
writer y registros comparten reloj: **no hace falta ningún CDC ni codificación
Gray entre `WR_SLOT` y `RD_SLOT`**, a pesar de que son punteros de un ring que
cruzan de un "productor" a un "consumidor". El patrón de ring no implica CDC; lo
implica el reloj.

---

## 7. Caso de estudio: la evolución del camino de eventos de este proyecto

Los cuatro grupos se ven en una sola historia, que además da los números.

### Etapa 1 — K=1 por freeze (`rp_bram_sm`)

La BRAM circular de 16384 muestras es un **patrón de Grupo 1** (línea de
retardo). Pero el mecanismo de acceso — congelar con `adc_we <= 0`, que el PS lea
por GP0, re-armar — la convierte de hecho en una cola de **un solo evento**.

El tiempo muerto es el round-trip del PS, medido por atribución de fases:

```
  read     172.7 µs      rearm  38.0 µs      book  30.8 µs      snap  11.2 µs
  ─────────────────────────────────────────────────────────────────────────
  τ = 252.7 µs      →      techo = 1/τ = 3.96 kev/s   (medido: 3.7 kev/s)
```

Con `K=1` y tiempo muerto no paralizable, la eficiencia frente a una fuente
**periódica** es una escalera, `η = 1/⌈n·τ⌉`, que reproduce el barrido medido
punto por punto (ver
[`multitrigger/arquitectura_adquisicion_software.md`](multitrigger/arquitectura_adquisicion_software.md)).
Frente a una fuente **Poisson** — un detector real — la curva es
`η = 1/(1 + n·τ)`, sensiblemente peor: a 10 kev/s, 28.3 % contra 33.3 %.

> **Salvedad para el informe:** caracterizar con un generador periódico
> **sobreestima** la eficiencia que se va a obtener con una fuente radiactiva.

### Etapa 2 — Ring de slots (`event_ring`)

El `event_ring` reemplaza el freeze por una **cola productor/consumidor de
`N_SLOTS` eventos en DDR**, y en el camino usa los cuatro grupos:

| Bloque | Grupo | Patrón |
|---|---|---|
| `pre_buf` en `event_window_capture` | 1 | circular de pre-trigger, dimensionado por `pre` (no `pre+post`) |
| `event_stage_fifo` | 2 | FIFO elástica, `E=4` eventos en vuelo, 4096 muestras |
| créditos `wr_slot − rd_slot` | 2 | control de flujo hacia DDR |
| footer `{~seq, seq}` | 3 | commit atómico sin BRESP |
| geometría congelada en STOPPED | 3 | config coherente |
| `drop_busy` / `drop_full` | — | pérdida contada **por causa** |

El resultado sobre el tiempo muerto:

| | τ | Techo `1/τ` |
|---|---:|---:|
| K=1 por freeze | 252.7 µs | 3.96 kev/s |
| `event_window_capture` (`pre+post` ciclos, S=32) | ~256 ns | ~3.9 Mev/s |

**Tres órdenes de magnitud, y el PS sale del camino crítico.** Lo que cambió no
fue el tamaño de ninguna memoria — la BRAM del scope siempre estuvo sobrada
512× — sino **qué patrón se usó**: pasar de tratar una línea de retardo como si
fuera una cola, a poner una cola de verdad.

Esa es la moraleja que justifica todo el documento.

### Cómo se dimensiona el ring

Con el PS fuera del lazo, `ρ ≪ 1` y el criterio deja de ser estocástico: pasa a
ser **cobertura del peor caso del consumidor**.

```
N_SLOTS ≥ n_max × T_stall_peor_caso
```

`T_stall` está medido, no supuesto: **5.3 ms de stall del GIL** (la firma de
`sys.getswitchinterval()`, ver
[`multitrigger/arquitectura_adquisicion_software.md`](multitrigger/arquitectura_adquisicion_software.md)).
A 11 kev/s son 58 eventos; con `sys.setswitchinterval(0.001)` bajan a ~11. Un
ring de **128 slots** deja 10× de margen sobre el peor caso medido, y a 32
muestras × 2 canales × 2 B son ~16 kB de DDR: nada.

Es un número defendible porque sale de una medición.

---

## 8. Vocabulario: el mismo patrón tiene cuatro nombres

Es la razón práctica por la que cuesta encontrar bibliografía. El buffer que
absorbe la aleatoriedad de arribo antes de un consumidor de latencia fija se
llama:

| Comunidad | Nombre |
|---|---|
| Ciencias de la computación / redes | *queue*, *buffer* |
| EDA / diseño de circuitos | *elastic buffer*, *latency-insensitive design* |
| FPGA / AXI | *skid buffer*, *FIFO* |
| **Física de altas energías / instrumentación nuclear** | **derandomizer** (*derandomizing buffer*) |

**`derandomizer` es el término que abre la literatura pertinente para este
proyecto.** ATLAS, CMS y LHCb dimensionaron los suyos exactamente con M/D/1/K y
simulación de ocupación, con el mismo objetivo: absorber la ráfaga de Poisson
antes de un readout de latencia fija, contando lo que se pierde. Buscar
*"derandomizer buffer front-end electronics dead time"*.

---

## 9. Recursos

### Empezar por acá (gratis, directo al grano)

1. **Cliff Cummings, Sunburst Design** — sunburst-design.com, PDFs libres.
   *"Simulation and Synthesis Techniques for Asynchronous FIFO Design"*
   (SNUG 2002) es **la** referencia canónica de FIFO asíncrona con punteros
   Gray. Sus papers de CDC son igual de buenos. Si se lee uno solo, ese.
2. **ZipCPU (Dan Gisselquist)** — zipcpu.com. Tutoriales de skid buffers,
   handshaking AXI y verificación formal de FIFOs. El nivel y el tipo de
   problema son exactamente los de este proyecto.
3. **Alex Forencich, `verilog-axis`** (GitHub) — RTL de referencia limpio:
   FIFOs sync/async, skid buffers, adaptadores de ancho.

### Fundamento teórico de los buffers elásticos

4. Carloni, McMillan, Sangiovanni-Vincentelli, *"Theory of Latency-Insensitive
   Design"*, IEEE TCAD, 2001.
5. Cortadella, Kishinevsky, Grundmann, *"SELF: Specification and Design of
   Synchronous Elastic Circuits"*, IEEE TCAD, 2006.

### Libros

6. **Pong P. Chu**, *FPGA Prototyping by SystemVerilog Examples* — práctico,
   con los patrones implementados.
7. **Steve Kilts**, *Advanced FPGA Design* (Wiley) — pipelining, retiming,
   arquitectura de memoria.
8. **Hennessy & Patterson**, *Computer Architecture: A Quantitative Approach* —
   el forwarding, los hazards y la jerarquía de memoria vienen de ahí.
9. **Xilinx UG473**, *7 Series Memory Resources* — qué da realmente el BRAM del
   Zynq: puertos, modos de colisión, `ram_style`.

### Dimensionamiento cuantitativo

10. **Kleinrock**, *Queueing Systems, Vol. 1* — M/D/1/K y compañía.
11. Appenzeller, Keslassy, McKeown, *"Sizing Router Buffers"*, SIGCOMM 2004.
    El mismo problema en redes; además es un modelo de **cómo se argumenta un
    dimensionamiento**: derriba una regla aceptada con un modelo simple y datos.
12. **Knoll**, *Radiation Detection and Measurement*, cap. 4 — tiempo muerto
    paralizable y no paralizable.
13. **Spieler**, *Semiconductor Detector Systems* (Oxford) — el capítulo de
    front-end/DAQ, donde el derandomizador aparece en su hábitat.

---

## 10. Pendientes identificados

Cosas que este mapeo dejó a la vista y todavía no se hicieron:

- **Skid buffer en `mca_hist`.** La colisión de un evento con `rd_i` se descarta
  y se cuenta (`dropped_o`). Pero `rd_i` es un pulso de **un ciclo** — un
  bloqueo acotado — así que un registro de skid la elimina *por completo*, no
  probabilísticamente. Estimación del impacto actual: leyendo 4096 bins con un
  `rd_stb` de 1 ciclo sobre una lectura de ~4 ms, el duty de `rd_i` es ≈0.8 %,
  o sea ~0.8 % de los eventos perdidos durante cada lectura de espectro. Es el
  cambio de mejor relación costo/beneficio del diseño.
- **El barrido fino de la escalera.** Medir la eficiencia alrededor de
  `n = k/τ` (3.96, 7.91, 11.9, 15.8, 19.8 kHz) para confirmar la firma de K=1 no
  paralizable y medir `τ` por la posición de los escalones.
- **Validar M/D/1/K en software.** Limitar artificialmente `free_q` a K = 1, 2,
  4, 8 en [`reader.py`](../software/mca/reader.py) y contrastar la familia de
  curvas medida contra la fórmula. No requiere tocar RTL.
