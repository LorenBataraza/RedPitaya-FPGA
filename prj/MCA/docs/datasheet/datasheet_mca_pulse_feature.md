# Datasheet — `mca_pulse_feature`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/mca_pulse_feature.md.
     Regenerar:  make -C modulos/mca/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `mca_pulse_feature` |
| Archivo | [`mca_pulse_feature.sv`](../../modulos/mca/rtl/mca_pulse_feature.sv) |
| Parámetros | 12 |
| Puertos | 59 (27 in / 32 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mca_pulse_feature](figuras/mca_pulse_feature_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`mca_pulse_feature.sv`](../../modulos/mca/rtl/mca_pulse_feature.sv)):

> mca_pulse_feature — segmentador de pulsos y extractor de características
>
> Recibe la muestra ya calibrada/filtrada y, por cada pulso detectado, emite
> UN registro de evento coherente {amp, psd} que alimenta a todos los motores
> de histograma. Que salga de un único registro es lo que garantiza que el
> espectro 1D y el mapa 2D cuenten exactamente los mismos pulsos.
>
> PARTICION: este modulo es solo cableado
> El extractor esta repartido en submodulos, uno por etapa de la vista general
> (docs/mca/vista_general_mca.md), de modo que cada decision Dn vive en un solo
> bloque:
>
>   mca_baseline la linea de base: seguidor IIR o base fija (D3)
>   mca_window   el nucleo: la muestra relativa a la base, quien abre (D4),
>                quien cierra (D5), el re-armado (D6), los acumuladores, la
>                ventana de amplitud (D7) y la contabilidad del tiempo muerto
>   mca_publish  la FIFO, el arbitro, los dos mca_div_restore y el armado del
>                bus de features (D8)
>
> Los puertos y los parametros son los mismos que cuando era un solo modulo,
> asi que mca_top, los testbenches y las assertions no se enteraron. Y el
> comportamiento es BIT-IDENTICO: lo verifica tb_mca_pulse_feature_eq contra
> la copia congelada sim/mca_pulse_feature_ref.v, en todas las salidas y en
> todos los ciclos.
>
> DONDE VAN LAS FRONTERAS lo decide el timing, no la prolijidad. El bitstream
> se sintetiza con -flatten_hierarchy none, asi que cada puerto es una barrera
> de optimizacion, y el camino critico (dat -> umbrales -> abrir/cerrar ->
> acumuladores) cerro con 6 ps. Las fronteras estan donde lo que cruza sale de
> un registro o entra directo a un pin de primitiva; por eso segmentacion y
> acumuladores comparten modulo.
>
> EL RE-ARMADO SE PROBO AFUERA y volvio. `armed` sale de un registro, pero abrir
> lo consume en el mismo flanco (y le gana al re-armado por nivel), asi que el
> modulo de afuera necesita el flanco de apertura como puerto. Con
> -flatten_hierarchy none Vivado arma una LUT dedicada a ese puerto y las cargas
> internas de la apertura pasan a colgar de ella: medido en la OOC, q_tot y
> q_tail cayeron a -0.131 ns y t_peak, d_min/d_max, win_id y gate_2nd perdieron
> 576 ps cada uno. No hay forma de no exportar ese flanco sin cambiar el
> comportamiento.
>
> FASE 2: las tres politicas, todas seleccionables por registro
> Las tres conviven en el MISMO bitstream y arrancan en el comportamiento
> historico, porque comparar dos politicas sobre los mismos pulsos es lo unico
> que decide entre ellas con datos (es el mismo argumento de cfg_amp_src).
>
> (1) QUIEN ABRE: cfg_trig_src. 0 = el Schmitt interno (como siempre),
>     1 = un TRIGGER EXTERNO (el trigger_event del multitrigger), 2 = cualquiera
>     de los dos. Detalle, y la advertencia de que el modo 1 no sirve para
>     espectrometria sin linea de retardo, en la cabecera de mca_window.
>
> (2) COMO SE RE-ARMA: cfg_rearm_mode. 0 = por NIVEL (la senal tiene que bajar
>     de thr_lo), 1 = por CONTADOR (cfg_rearm_dly muestras despues del cierre,
>     pase lo que pase con la senal).
>
>     ESTA ES LA PALANCA DEL TIEMPO MUERTO, y es la unica grande. Con re-armado
>     por nivel el modulo es PARALIZABLE: cada pulso que monta sobre la cola del
>     anterior extiende el bloqueo, y tau = 5.9 us. Con re-armado por contador es
>     NO PARALIZABLE y tau = 3.2 us determinista. En perdida de eventos con
>     arribos Poisson: 45.9 % -> 24.2 % a 100 kcps. El doble buffer de (3), en
>     comparacion, vale 0.7 pp.
>
>     Su contrapartida tambien esta medida y es seria: el re-armado por contador
>     SOBRE-CUENTA, porque trocea un apilamiento en pedazos del largo de la
>     compuerta y registra cada pedazo como un evento. La mitigacion no es volver
>     al nivel, es rechazar por FORMA (F_INVW / F_LEN): el ancho inverso rechaza
>     el 99.1 % de los apilados donde PSD rechaza el 0 % en modo compuerta. Los
>     contadores de la Fase 1 son los que permiten verificarlo.
>
> (3) COMO SE PUBLICA: cfg_pub_mode. 0 = BLOQUEANTE (la ventana no puede reabrir
>     hasta que los divisores terminan: st se queda en S_DIV, como siempre),
>     1 = FIFO de PUB_K lugares con id de ventana.
>
>     Lo que compra la FIFO es que la ventana cierre y REABRA sin esperar la
>     publicacion. Con UN solo juego de acumuladores desacopla la publicacion,
>     no las ventanas: K=2 alcanza, y para ventanas realmente solapadas habria
>     que duplicar acumuladores, que es otro costo.
>
>     Y EL DESBORDE DE LA FIFO ES TIEMPO MUERTO: sale en dt_pub_o y entra al
>     teselado como un casillero propio. Si no se contara, el tiempo muerto
>     oculto que la Fase 1 saco a la luz se habria mudado del Schmitt al arbitro
>     en vez de desaparecer.
>
> COMPATIBILIDAD. Con los tres registros en 0 el modulo es BIT-IDENTICO al de la
> Fase 1, incluido el largo exacto de S_DIV: por eso el cierre arranca los
> divisores desde los registros vivos cuando el publicador esta libre (ver
> `arranque_directo`) y S_DIV sale con `pub_done` y no con la FIFO vacia. Un
> ciclo de diferencia ahi no cambiaria nada fisico, pero romperia la identidad
> deadtime_cnt == t_win + t_div que la Fase 1 dejo como assertion.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/mca_pulse_feature.md, no aca. -->

**Qué hace.** Es **el bloque central del MCA**: recibe el flujo de muestras ya
calibrado y, por cada pulso que detecta, emite **un** registro de evento
coherente con todas sus características —pico, integral, cocientes de forma,
largo, tiempo de subida—. Que salga de un único registro es lo que garantiza
que el espectro 1D y el mapa 2D cuenten **exactamente los mismos pulsos**; si
cada histograma se armara su propio evento, un corte podría afectar a uno y no
al otro y las dos vistas dejarían de ser comparables.

Su vida completa, muestra por muestra y con los números de cada etapa medidos
sobre la simulación, está en
[`mca_pulso_vida.svg`](../mca/figuras/ondas/mca_pulso_vida.svg).

**Hoy es solo cableado.** El trabajo está en tres submódulos:
[`mca_baseline`](datasheet_mca_baseline.md) (la línea de base),
[`mca_window`](datasheet_mca_window.md) (la ventana, los acumuladores y la
contabilidad de tiempo muerto) y [`mca_publish`](datasheet_mca_publish.md)
(la FIFO, los divisores y el bus de features). Los puertos son los de siempre, y
el comportamiento es bit-idéntico al del módulo único: lo verifica
`tb_mca_pulse_feature_eq` contra la copia congelada `sim/mca_pulse_feature_ref.v`.
Dónde van las fronteras lo decidió el timing; el detalle está en
[`decisiones_diseno_mca.md`](../mca/decisiones_diseno_mca.md) §6.

**Tres decisiones que explican su forma.**

**1 · Hay dos modos de cerrar la ventana, y la diferencia se mide.** Con
histéresis el largo lo decide dónde la cola cruza el umbral, que es la parte
más chata del pulso: lo decide el ruido. Con compuertas fijas el largo es
`cfg_gate_long` y no depende de la señal. Sobre **7054 pulsos reales**, offline,
la resolución de la integral pasa de **0.528 % a 0.149 %**
(`software/API/modelo_rtl/estimadores.py`). Los dos modos conviven en el mismo
bitstream porque comparar dos políticas sobre los **mismos** pulsos es lo único
que decide entre ellas con datos.

**2 · La amplitud es seleccionable, y eso ES el experimento.** `cfg_amp_src = 0`
toma la muestra de pico —ruido de una sola muestra, y el muestreo casi nunca
cae en el máximo real: ensancha el fotopico—; `= 1` toma la integral de carga,
donde el ruido blanco promedia como σ/√N y el jitter de muestreo no entra.
Poder alternar entre las dos en el mismo bitstream es lo que permite **medir**
la contribución del jitter en vez de estimarla
([`fuentes_de_jitter.md`](../mca/fuentes_de_jitter.md)).

**3 · El tiempo muerto se mide por casilleros, no por `busy`.** `busy_o` **no**
es la condición de bloqueo del módulo, y usarlo como tal es lo que hacía que el
reloj de tiempo muerto de [`mca_top`](datasheet_mca_top.md) mintiera: la
condición real exige `armed`, que es de **nivel**, así que mientras la cola del
último pulso siga arriba el módulo está en `S_IDLE` —`busy_o` bajo— pero **no
puede abrir**. Ese tiempo no entraba en ningún contador. Por eso salen los
cuatro casilleros `dt_win` / `dt_div` / `dt_rearm` / `puede_abrir`, mutuamente
excluyentes, más los contadores de atribución que mandan **cada** cruce de
umbral a exactamente un casillero. El desarrollo está en
[`tiempo_muerto.md`](../mca/tiempo_muerto.md).

**Los detalles que parecen menores y no lo son.** El seguidor de línea de base
usa un acumulador ancho porque con la forma ingenua el incremento se cuantiza a
cero y el seguidor se congela; se descongela `cfg_bl_holdoff` muestras
**después** del pulso para no agarrar el undershoot de la cola. El pico se
compara con `>` estricto, porque con `>=` el instante de pico se correría hasta
el final de una meseta con ruido y el tiempo de subida saldría arbitrariamente
largo. Cada muestra se satura a ≥ 0 antes de acumular, porque si no una cola con
undershoot resta de `q_tot` mientras `q_tail` sigue sumando y se llega a
`q_tail > q_tot`, que rompe la premisa del divisor.

El apilamiento —ventana que llega a `cfg_maxlen`— se **cuenta** en
`cnt_pileup` pero **no se histogramea**: su integral y su pico están
contaminados por el segundo pulso. Se ve cerrarse en
[`mca_apilamiento.svg`](../mca/figuras/ondas/mca_apilamiento.svg) y el
tratamiento completo está en [`apilamiento.md`](../mca/apilamiento.md).

> **El bloque que el formal no paga.** Acumuladores anchos sobre ventanas de
> miles de ciclos: la profundidad de BMC mata el intento, y la propiedad
> interesante necesita el modelo de referencia que ya existe. Es el único de la
> lista con veredicto **no** en
> [`verificacion_formal.md`](../verificacion_formal.md).
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `DW` | `integer` | `14` | ancho de muestra (con signo) |
| `QW` | `integer` | `32` | ancho de los acumuladores de carga |
| `AMP_W` | `integer` | `16` | ancho de la amplitud emitida |
| `PSD_AW` | `integer` | `6` | bits del EJE de factor de forma (mapa 2D) |
| `DIV_W` | `integer` | `16` | bits de COCIENTE de los divisores |
| `NFEAT` | `integer` | `16` | ranuras del bus de features |
| `LEN_W` | `integer` | `16` | ancho de los contadores de longitud |
| `BL_KW` | `integer` | `4` | bits del exponente k del seguidor IIR |
| `EN_PSD` | `integer` | `1` | 0: no instancia los divisores |
| `PUB_K` | `integer` | `2` |  |
| `PUB_IDW` | `integer` | `16` | bits del id de ventana |
| `PUB_AW` | `integer` | `(PUB_K <= 2) ? 1 : $clog2(PUB_K)` |  |


#### Puertos

##### Reloj y reset

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `clk_i` | in | 1 | — |
| `rstn_i` | in | 1 | — |


##### Muestras de entrada (ya calibradas/filtradas/decimadas)

| Puerto | Dir | Bits | Signo | Dominio |
|---|---|---|---|---|
| `dat_i` | in | 14 `[DW-1:0]` | signed | clk_i |
| `val_i` | in | 1 |  | clk_i |


##### Configuración

| Puerto | Dir | Bits | Signo | Dominio | Descripción |
|---|---|---|---|---|---|
| `cfg_run_i` | in | 1 |  | clk_i |  |
| `veto_i` | in | 1 |  | clk_i | VETO externo (nivel): no se abren pulsos nuevos mientras vale 1. El pulso en curso termina normal, y el seguidor de linea de base SIGUE corriendo -- a diferencia de cfg_run=0 --, porque la base deriva igual durante el veto y si se congelara arrancaria desfasada al liberarse. Viene del trigger_shield del multitrigger (dst = mca). |
| `cnt_clr_i` | in | 1 |  | clk_i | pulso: pone a cero los contadores |
| `cfg_thr_i` | in | 14 `[DW-1:0]` | signed | clk_i | umbral sobre la línea de base |
| `cfg_hyst_i` | in | 14 `[DW-1:0]` |  | clk_i | histéresis (positiva) |
| `cfg_baseline_i` | in | 14 `[DW-1:0]` | signed | clk_i | base fija si cfg_bl_auto=0 |
| `cfg_bl_auto_i` | in | 1 |  | clk_i |  |
| `cfg_bl_k_i` | in | 4 `[BL_KW-1:0]` |  | clk_i | alfa = 2^-k |
| `cfg_bl_holdoff_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |  |
| `cfg_maxlen_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |  |
| `cfg_tail_dly_i` | in | 16 `[LEN_W-1:0]` |  | clk_i | >= 1 |


##### Modo de ventana (ver cabecera, SEGMENTACION)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `cfg_gate_mode_i` | in | 1 | clk_i | 0=histeresis, 1=compuertas fijas |
| `cfg_gate_short_i` | in | 16 `[LEN_W-1:0]` | clk_i | compuerta corta, en muestras |
| `cfg_gate_long_i` | in | 16 `[LEN_W-1:0]` | clk_i | compuerta larga, en muestras |
| `cfg_amp_min_i` | in | 16 `[AMP_W-1:0]` | clk_i |  |
| `cfg_amp_max_i` | in | 16 `[AMP_W-1:0]` | clk_i |  |
| `cfg_amp_src_i` | in | 1 | clk_i | 0=pico, 1=integral |
| `cfg_q_shift_i` | in | 5 | clk_i |  |


##### FASE 2: apertura, re-armado y publicacion (ver cabecera)

Trigger externo. Se toma por FLANCO; `trig_pend` lo sostiene hasta la muestra valida siguiente para que la decimacion no se lo coma.

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `trig_i` | in | 1 | clk_i |  |
| `cfg_trig_src_i` | in | 2 | clk_i | 0=interno, 1=externo, 2=ambos |
| `cfg_rearm_mode_i` | in | 1 | clk_i | 0=nivel(thr_lo), 1=contador |
| `cfg_rearm_dly_i` | in | 16 `[LEN_W-1:0]` | clk_i | holdoff de re-armado |
| `cfg_pub_mode_i` | in | 1 | clk_i | 0=bloqueante, 1=FIFO |


##### Evento de salida (pulso de 1 ciclo)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `ev_valid_o` | out | 1 | clk_i |  |
| `ev_amp_o` | out | 16 `[AMP_W-1:0]` | clk_i |  |
| `ev_psd_o` | out | 6 `[PSD_AW-1:0]` | clk_i |  |
| `ev_psd_ok_o` | out | 1 | clk_i | 0 => no histogramear el 2D |
| `ev_feat_o` | out | 256 `[NFEAT*AMP_W-1:0]` | clk_i | Bus de features: NFEAT ranuras de AMP_W bits, todas del MISMO evento. Se arma a la salida de S_DIV, no al cerrar, porque los cocientes valen DIV_W ciclos mas tarde que el resto (ver F_ del cuerpo). |


##### Estado y contadores

| Puerto | Dir | Bits | Signo | Dominio | Descripción |
|---|---|---|---|---|---|
| `baseline_o` | out | 14 `[DW-1:0]` | signed | clk_i |  |
| `baseline_stale_o` | out | 1 |  | clk_i |  |
| `cnt_total_o` | out | 32 |  | clk_i | pulsos cerrados |
| `cnt_accepted_o` | out | 32 |  | clk_i |  |
| `cnt_rej_amp_o` | out | 32 |  | clk_i | fuera de [min,max] |
| `cnt_rej_psd_o` | out | 32 |  | clk_i | q_tot=0 o q_tail>=q_tot |
| `cnt_pileup_o` | out | 32 |  | clk_i | cerrado por maxlen |
| `cnt_lost_busy_o` | out | 32 |  | clk_i | pulso perdido con el divisor ocupado |
| `last_qtot_o` | out | 32 `[QW-1:0]` |  | clk_i |  |
| `last_qtail_o` | out | 32 `[QW-1:0]` |  | clk_i |  |
| `busy_o` | out | 1 |  | clk_i | pulso activo o divisor ocupado |


##### Casilleros de tiempo muerto (ver "TIEMPO MUERTO" del cuerpo)

Mutuamente excluyentes. Su union es exactamente "no puede abrir", salvo los terminos cfg_run/veto que los pone mca_top porque son suyos.

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `dt_win_o` | out | 1 | clk_i | ventana abierta |
| `dt_div_o` | out | 1 | clk_i | bloqueado por la publicacion |
| `dt_rearm_o` | out | 1 | clk_i | libre pero sin re-armar |
| `puede_abrir_o` | out | 1 | clk_i |  |


##### Atribucion de arribos: cada cruce de thr_hi va a UN casillero

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `arribo_o` | out | 1 | clk_i | flanco de thr_hi, 1 ciclo |
| `cnt_cross_o` | out | 32 | clk_i | todos los cruces de thr_hi |
| `cnt_open_o` | out | 32 | clk_i | ...que abrieron ventana |
| `cnt_lost_rearm_o` | out | 32 | clk_i | ...perdidos esperando el re-armado |
| `cnt_lost_active_o` | out | 32 | clk_i | ...llegados dentro de la ventana |
| `cnt_lost_veto_o` | out | 32 | clk_i | ...llegados bajo veto |
| `cnt_lost_notrig_o` | out | 32 | clk_i | FASE 2. Con apertura por trigger externo un cruce puede encontrar al modulo libre y NO abrir (porque no vino trigger), y una ventana puede abrir SIN cruce (trigger sobre un pulso bajo umbral, o por software). Son dos hechos distintos y necesitan dos contadores distintos: — cruce libre, sin disparo habilitado |
| `cnt_win_o` | out | 32 | clk_i | ventanas ABIERTAS (venga o no de un cruce) |


##### FASE 2: estado del arbitro de publicacion

occ_max es el dato que decide si PUB_K alcanza: si llega a PUB_K hubo contrapresion, y los eventos que se perdieron por eso estan en cnt_lost_busy.

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `pub_occ_o` | out | `[PUB_AW:0]` | clk_i | lugares ocupados ahora |
| `pub_occ_max_o` | out | `[PUB_AW:0]` | clk_i | maximo historico |
| `last_win_id_o` | out | 16 `[PUB_IDW-1:0]` | clk_i | id de la ultima ventana publicada |
| `cnt_trig_o` | out | 32 | clk_i | flancos de trigger externo |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
Mapas de registros de la región:

- [`register_map_mca.md`](../mca/register_map_mca.md)

Contrato del bus: [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) · Mapa de slots: [`register_map_top.md`](../TOP/register_map_top.md)
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
El `metrics.txt` del módulo es de `mca_top`, no de `mca_pulse_feature`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
<!-- /AUTO:timing -->

<!-- A mano: qué hay en el camino crítico y qué se haría para romperlo si
     hubiera que subir la frecuencia. -->

### 1.6 Transacciones

<!-- AUTO:transacciones -->
**LA CADENA DE UN EVENTO  -  senal, registro y espectro**

![LA CADENA DE UN EVENTO  -  senal, registro y espectro](../mca/figuras/07_cadena.png)

La transaccion del MCA es UN EVENTO, y la figura la sigue entera: (a) la senal de entrada con el umbral y la ventana que `pulse_feature` abre y cierra, (b) el camino de datos, donde entre los dos bloques no va una flecha pelada sino el tren de amplitudes concretas que viaja --un registro de evento por pulso--, y (c) el espectro que se acumula del otro lado, una cuenta por numero. Los numeros de los tres paneles son los mismos: la amplitud que se mide en (a) es la que viaja en (b) y la que cae en un canal en (c), con el mismo `amp >> h_shift` que hace el RTL. Es la unica figura del proyecto que muestra la cuenta completa de punta a punta.

_Origen: simulacion con semilla fija (`animacion_cadena_mca.py`), los mismos cuadros que los videos._

**(a) LA SENAL: UN PULSO POR EVENTO**

![(a) LA SENAL: UN PULSO POR EVENTO](../mca/figuras/07a_senal.png)

Las bandas parten el eje de TIEMPO en estados --ventana abierta, reposo-- y no la senal en eventos. La ventana abre al cruzar `thr` y cierra recien al bajar de `thr - hyst`, que es lo que hace que termine bastante despues del pico.

_Origen: la misma simulacion, panel (a) suelto._

**(b) EL CAMINO DE DATOS: UN NUMERO POR PULSO**

![(b) EL CAMINO DE DATOS: UN NUMERO POR PULSO](../mca/figuras/07b_cadena.png)

`pulse_feature` emite un registro de evento por pulso y el histograma lo convierte en una cuenta. La tabla de abajo son los mismos pulsos como los ve el histograma, incluido el que no cruza el umbral y no produce nada.

_Origen: la misma simulacion, panel (b) suelto._

**(c) EL ESPECTRO: UNA CUENTA POR NUMERO**

![(c) EL ESPECTRO: UNA CUENTA POR NUMERO](../mca/figuras/07c_histograma.png)

El mismo espectro en tres momentos de la acumulacion (12, 64 y 227 cuentas): la forma aparece recien cuando hay estadistica.

_Origen: la misma simulacion, panel (c) suelto._

---

Las figuras **recalculan cada número al dibujar** en vez de tomarlo escrito.
<!-- /AUTO:transacciones -->

### 1.7 Waveforms

<!-- AUTO:ondas -->
**LA VIDA DE UN PULSO  -  cruce de umbral, ventana, carga acumulada y evento**

![LA VIDA DE UN PULSO  -  cruce de umbral, ventana, carga acumulada y evento](../mca/figuras/ondas/mca_pulso_vida.svg)

Es la figura central del modulo: todo lo que el MCA hace por evento pasa aca. La muestra cruza el umbral, `busy` sube y marca la ventana abierta, las dos cargas se acumulan mientras la ventana dura --q_tot sobre toda la ventana y q_tail desde la segunda muestra, que es lo que hace separable la forma del pulso-- y al cerrar sale `ev_valid` con la amplitud y el bus de features. El pulso es RECTANGULAR a proposito, igual que en el testbench: su ventana es inequivoca, asi que los numeros del epigrafe salen de una multiplicacion y no de reimplementar el DUT.

_Origen: `tb_mca_pulse_feature`, escena 1 (pulso rectangular)._

**APILAMIENTO  -  la ventana llega a maxlen: el pulso se cuenta pero NO se acepta**

![APILAMIENTO  -  la ventana llega a maxlen: el pulso se cuenta pero NO se acepta](../mca/figuras/ondas/mca_apilamiento.svg)

El mismo bloque con `maxlen` chico y un pulso mas largo que eso. La ventana se cierra por limite y el evento cae en `cnt_pileup` sin pasar por `cnt_accepted`: no sale `ev_valid`. Lo que importa es que SI se cuenta en `cnt_total`. Un evento descartado que no se cuenta en ningun lado es tiempo muerto invisible, y sin ese numero no se puede corregir el espectro por eventos perdidos.

_Origen: `tb_mca_pulse_feature`, escena 5 (apilamiento)._

**READ-MODIFY-WRITE AL MISMO BIN  -  la cuenta no se pierde aunque los eventos lleguen pegados**

![READ-MODIFY-WRITE AL MISMO BIN  -  la cuenta no se pierde aunque los eventos lleguen pegados](../mca/figuras/ondas/mca_hist_rmw.svg)

El histograma es una BRAM: incrementar un bin es leerlo, sumarle uno y escribirlo, y eso tarda varios ciclos. Si dos eventos consecutivos caen en el MISMO bin, el segundo leeria el valor viejo --el que todavia no se escribio-- y una de las dos cuentas se perderia. La figura muestra cuatro incrementos seguidos al mismo bin y la lectura posterior dando el total correcto: el bloque puentea la escritura en vuelo. Es el peor caso realista, porque un pico del espectro es justamente muchos eventos al mismo bin.

_Origen: `tb_mca_hist`, escena 3 (forwarding)._

**ACK DE LATENCIA FIJA  -  el barrido de borrado dura miles de ciclos y el bus no se entera**

![ACK DE LATENCIA FIJA  -  el barrido de borrado dura miles de ciclos y el bus no se entera](../mca/figuras/ondas/mca_ack_borrado.svg)

Lo que la cabecera del RTL marca como lo mas importante del modulo. El barrido de borrado recorre 2^H_AW bins y dura miles de ciclos, muchisimo mas que los 32 ciclos de timeout del axi4_slave. Si el ack dependiera de que el motor este libre, una lectura durante el barrido no haria ack nunca, y eso no produce una lectura mala: deja el CDC del slot desincronizado para siempre --reg_do != reg_done-- y ese slot no acepta mas transacciones. El ack sale de un shift register incondicional, asi que llega con la misma latencia este barriendo o no, que es lo que la figura mide.

_Origen: `tb_mca_top`, escena 5 (lectura durante el borrado)._

**FLUJO DE UNA MEDICION  -  mca_top**

![FLUJO DE UNA MEDICION  -  mca_top](../mca/figuras/ondas/mca_flujo.svg)

Es un esquema de la SECUENCIA, no una medicion. La configuracion es una escalera: el bus del PS escribe un registro por vez, y la figura los pone en el orden en que los escribe Mca.configure(). Ese orden importa en un solo punto: cfg_hist_sel va DESPUES de cfg_amp_src, porque escribir cfg_amp_src tambien lo mueve. Un registro que no se escribe conserva lo que tenia (el valor de reset solo despues de cargar el bitstream; ver register_map_mca.md). Despues, las dos cosas que fija: el borrado hay que ESPERARLO --`clear_busy` avisa, y los eventos que llegan mientras barre se descartan y se cuentan en `dropped`--, y los contadores se pueden leer con la medicion corriendo, que es lo que permite supervisar sin frenar. La misma secuencia en software esta en docs/API/guia_de_uso.md; si las dos se contradicen, una de las dos esta mal.

_Origen: esquema (sin VCD)._

---

Las figuras y sus epígrafes los escribe [`ondas_mca.py`](../mca/figuras/ondas/ondas_mca.py): los tiempos y las latencias se **miden sobre el VCD**, no se escriben a mano, así que no pueden desincronizarse del RTL. Los epígrafes completos, con los números, están en [`epigrafes.txt`](../mca/figuras/ondas/epigrafes.txt).

```bash
python3 docs/mca/figuras/ondas/ondas_mca.py    # regenerar
```
<!-- /AUTO:ondas -->

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/mca/figuras/ondas/ondas_mca.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/mca/work wave TB=<tb>   # mirar en Questa
       make -C modulos/mca/work vcd  TB=<tb>   # VCD exportable -->

### 1.8 Verificación realizada

<!-- AUTO:verificacion -->
Todo corre en batch y se chequea el `RESULT: PASS` del testbench; las ondas quedan en `work/waves/<tb>.wlf`.

```bash
make -C modulos/mca/work            # los 7 testbenches
make -C modulos/mca/work cov        # + cobertura
make -C modulos/mca/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_mca_div_restore`](../../modulos/mca/sim/tb_mca_div_restore.sv) | `mca_div_restore` | 6 | 22 | vectores a mano |  |
| [`tb_mca_hist`](../../modulos/mca/sim/tb_mca_hist.sv) | `mca_hist` | 8 | 31 | vectores a mano |  |
| [`tb_mca_zoom`](../../modulos/mca/sim/tb_mca_zoom.sv) | `mca_zoom` | 5 | 11 | vectores a mano |  |
| [`tb_mca_discriminator`](../../modulos/mca/sim/tb_mca_discriminator.sv) | `mca_discriminator` | 7 | 21 | vectores a mano |  |
| [`tb_mca_pulse_feature`](../../modulos/mca/sim/tb_mca_pulse_feature.sv) | `mca_pulse_feature` | 17 | 161 | vectores a mano | **sí** |
| [`tb_mca_pulse_feature_eq`](../../modulos/mca/sim/tb_mca_pulse_feature_eq.sv) | `mca_pulse_feature_eq` | — | — | RTL de referencia `mca_pulse_feature_ref.v` instanciado al lado del DUT |  |
| [`tb_mca_top`](../../modulos/mca/sim/tb_mca_top.sv) | `mca_top` | 9 | 82 | vectores a mano |  |


**328 casos con nombre** en 7 testbenches (52 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_mca_pulse_feature`](../../modulos/mca/sim/tb_mca_pulse_feature.sv): 1) Pulso rectangular, 2) Estimador de INTEGRAL, 3) Pulso por debajo del umbral, 4) Ventana de aceptación de amplitud, 5) APILAMIENTO, 6) Pulso que NUNCA vuelve a bajar de la histéresis, 7) Línea de base FIJA distinta de cero, 8) Línea de base AUTOMÁTICA, 9) Caso borde PSD, 10) Caso borde PSD, 11) Dos pulsos SEPARADOS (hueco > latencia del divis, 12) cfg_run=0 inhibe la detección, 13) COMPUERTAS DE LARGO FIJO (cfg_gate_mode = 1), 14) TIEMPO MUERTO, 15) FASE 2 — RE-ARMADO POR CONTADOR, 16) FASE 2 — APERTURA POR TRIGGER EXTERNO, 17) FASE 2 — FIFO DE PUBLICACION.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`mca_top_sva.sv`](../../modulos/mca/sim/sva/mca_top_sva.sv) — 64 propiedades

Plan de verificación, casos cubiertos y deuda: [`mca/sim/VERIFICACION.md`](../../modulos/mca/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
