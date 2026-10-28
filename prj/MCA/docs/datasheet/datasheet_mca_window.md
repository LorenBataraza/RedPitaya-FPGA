# Datasheet — `mca_window`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/mca_window.md.
     Regenerar:  make -C modulos/mca/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `mca_window` |
| Archivo | [`mca_window.sv`](../../modulos/mca/rtl/mca_window.sv) |
| Parámetros | 8 |
| Puertos | 58 (26 in / 32 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mca_window](figuras/mca_window_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`mca_window.sv`](../../modulos/mca/rtl/mca_window.sv)):

> mca_window — el nucleo de la ventana: segmentacion, acumuladores y
> contabilidad del tiempo muerto
>
> Es la parte de mca_pulse_feature que NO se puede partir mas. El camino
> critico de todo el bitstream nace aca y muere aca:
>
>     dat_i -> x = dat - base -> umbrales -> abrir/cerrar -> q_tot, q_tail,
>     peak, t_peak, d_min/d_max  (y la WE de la FIFO de mca_publish)
>
> El build cerro con +0.006 ns en q_tot_reg/R, y el sintetizador corre con
> -flatten_hierarchy none: cada frontera de modulo es una barrera de
> optimizacion. Una frontera en medio de ese cono le agrega un nivel de LUT y
> el timing no cierra. Por eso segmentacion y acumuladores viven juntos, y lo
> que sale de aca hacia los vecinos sale de registros o va directo a pines de
> primitiva.
>
> Decisiones de la vista general (docs/mca/vista_general_mca.md) que viven aca:
>   D4 quien abre   (cfg_trig_src)
>   D5 quien cierra (cfg_gate_mode)
>   D6 como se re-arma (cfg_rearm_mode): se probo como modulo propio y volvio
>      aca, porque necesita el flanco de apertura como puerto y eso le agrega
>      un nivel de LUT a todo el cono (ver la cabecera de mca_pulse_feature)
>   D7 el estimador de la ventana de amplitud (cfg_amp_src)
>
> SEGMENTACIÓN. Schmitt igual que rp_adc_trig.v, para que los umbrales del
> MCA y del scope sean comparables. Abre al cruzar cfg_thr hacia arriba, con
> re-armado previo por debajo de cfg_thr-cfg_hyst. Para CERRAR hay dos modos,
> seleccionables por cfg_gate_mode:
>
>   0 = HISTÉRESIS: cierra al bajar de cfg_thr-cfg_hyst, o al llegar a
>       cfg_maxlen (esto último cuenta como APILAMIENTO).
>   1 = COMPUERTAS FIJAS: cierra a cfg_gate_long muestras del disparo, y la
>       cola arranca en cfg_gate_short. Es el método de comparación de carga.
>
> El motivo del modo 1: con histéresis el largo de la ventana lo decide dónde
> la cola cruza el umbral, que es la parte más chata del pulso, así que lo
> decide el ruido. Medido offline sobre 7054 pulsos reales, la resolución de la
> integral pasa de 0.528 % (histéresis) a 0.149 % (compuerta fija). Ver
> software/API/modelo_rtl/estimadores.py.
>
> Los eventos marcados como apilamiento se cuentan pero NO se histogramean,
> porque su integral y su pico están contaminados por el segundo pulso.
>
> AMPLITUD. Seleccionable por cfg_amp_src:
>   0 = muestra de pico   -> ruido de UNA muestra, y el muestreo casi nunca
>                            cae en el máximo real: ensancha el fotopico.
>   1 = integral de carga -> el ruido blanco promedia como sigma/sqrt(N) y
>                            es inmune al jitter de muestreo. Es lo que hace
>                            cualquier MCA digital serio, y lo que justifica
>                            un eje de 16384 canales.
> Poder alternar entre ambos en el mismo bitstream ES el experimento que mide
> la contribución de jitter de muestreo.
>
> PICO con comparación ESTRICTA (>): en un techo plano con ruido gana la
> PRIMERA ocurrencia del máximo. Con >= el instante de pico se correría hasta
> el final de la meseta y el tiempo de subida saldría arbitrariamente largo.
>
> CARGA. Cada muestra se satura a >= 0 antes de acumular. Sin eso, una cola
> con undershoot resta de q_tot mientras q_tail (en la parte plana) sigue
> sumando, y se llega a q_tail > q_total, que rompe la premisa del divisor.
>
> TIEMPO MUERTO. `busy_o` NO es la condicion de bloqueo del modulo, y usarlo
> como tal es lo que hacia que el reloj de tiempo muerto de mca_top mintiera.
> La condicion real es el complemento de `open_pulse`, que exige `armed` -- una
> condicion de NIVEL: no se re-arma hasta que la senal baja de thr_lo. Mientras
> la cola del ultimo pulso siga arriba, st == S_IDLE (asi que `busy_o` esta
> bajo) pero el modulo NO PUEDE ABRIR. Ese tiempo no entraba en ningun
> contador. Por eso ademas de `busy_o` salen los cuatro casilleros dt_* y los
> contadores de atribucion de arribos; ver las dos secciones del cuerpo.
>
> QUIEN ABRE: cfg_trig_src. 0 = el Schmitt interno (como siempre),
> 1 = un TRIGGER EXTERNO (el trigger_event del multitrigger), 2 = cualquiera
> de los dos. El trigger se toma por FLANCO y nunca por nivel: un trigger
> por software dura ~5 ciclos de bus y por nivel abriria varias ventanas
> (es el bug que event_window_capture.sv:58-64 ya documenta en la placa).
>
> ADVERTENCIA QUE NO SE PUEDE TAPAR: el trigger externo llega con latencia
> respecto de la muestra que lo causo, asi que la ventana arranca unas
> muestras TARDE y se pierde el flanco de subida -- la integral y el pico
> salen truncados. Para que el modo 1 sirva para medir energia hace falta la
> linea de retardo de muestras de la Fase 3 (muestreo doble correlacionado),
> que es justamente donde el plan la puso. Sin ella, el modo 1 sirve para
> coincidencia y para tener una base de tiempo comun, NO para espectrometria.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/mca_window.md, no aca. -->

**Qué hace.** Es el núcleo del extractor: resta la base, abre y cierra la
ventana, re-arma el detector, corre los acumuladores (pico, $Q_\mathrm{tot}$,
$Q_\mathrm{cola}$, largo, tiempo de subida), evalúa la ventana de amplitud y
reparte cada ciclo y cada cruce de umbral en los casilleros de tiempo muerto.
Viven acá cuatro decisiones de la
[vista general](../mca/vista_general_mca.md): quién abre (**D4**), quién
cierra (**D5**), cómo se re-arma (**D6**) y qué amplitud mira la ventana (**D7**).

**Por qué es un módulo tan grande.** Por acá pasa el camino crítico de todo el
bitstream, `dat → x → umbrales → abrir/cerrar → acumuladores`, y el
sintetizador corre con `-flatten_hierarchy none`. Una frontera en medio de ese
cono le suma un nivel de LUT. El re-armado se probó como módulo aparte y
volvió: abrir consume el armado en el mismo flanco, el flanco de apertura tenía
que salir como puerto, y eso solo costó 576 ps en todo el cono. Lo que sale hacia
[`mca_publish`](datasheet_mca_publish.md) sale de registros, o va directo a la
WE de la FIFO.

**Dos ajustes de mapeo, documentados en el RTL.** Las sumas de $Q_\mathrm{tot}$ y
$Q_\mathrm{cola}$ llevan `keep`, y $Q_\mathrm{cola}$ se escribe como valor
siguiente en todos los ciclos. Sin eso, al separar la publicación Vivado plegó la
apertura dentro del sumador y `q_tot` cayó a −0.148 ns en la OOC. La lógica es la
misma: lo verifica `tb_mca_pulse_feature_eq` contra la copia congelada del
módulo original.
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `DW` | `integer` | `14` | ancho de muestra (con signo) |
| `QW` | `integer` | `32` | ancho de los acumuladores de carga |
| `AMP_W` | `integer` | `16` | ancho de la amplitud emitida |
| `LEN_W` | `integer` | `16` | ancho de los contadores de longitud |
| `EN_PSD` | `integer` | `1` | 0: sin divisores, el evento sale al cerrar |
| `PUB_K` | `integer` | `2` | lugares de la FIFO de publicacion |
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


##### Configuración (ver mca_pulse_feature)

| Puerto | Dir | Bits | Signo | Dominio |
|---|---|---|---|---|
| `cfg_run_i` | in | 1 |  | clk_i |
| `veto_i` | in | 1 |  | clk_i |
| `cnt_clr_i` | in | 1 |  | clk_i |
| `cfg_thr_i` | in | 14 `[DW-1:0]` | signed | clk_i |
| `cfg_hyst_i` | in | 14 `[DW-1:0]` |  | clk_i |
| `cfg_maxlen_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |
| `cfg_tail_dly_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |
| `cfg_gate_mode_i` | in | 1 |  | clk_i |
| `cfg_gate_short_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |
| `cfg_gate_long_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |
| `cfg_amp_min_i` | in | 16 `[AMP_W-1:0]` |  | clk_i |
| `cfg_amp_max_i` | in | 16 `[AMP_W-1:0]` |  | clk_i |
| `cfg_amp_src_i` | in | 1 |  | clk_i |
| `cfg_q_shift_i` | in | 5 |  | clk_i |
| `trig_i` | in | 1 |  | clk_i |
| `cfg_trig_src_i` | in | 2 |  | clk_i |
| `cfg_rearm_mode_i` | in | 1 |  | clk_i |
| `cfg_rearm_dly_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |
| `cfg_pub_mode_i` | in | 1 |  | clk_i |


##### Hacia mca_publish: la ventana que cierra ACEPTADA y sus valores

Todos salen de registros (o de logica sobre registros), en el ciclo de cierre: son los que la FIFO guarda.

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `acepta_o` | out | 1 | clk_i |
| `amp_sel_o` | out | 16 `[AMP_W-1:0]` | clk_i |
| `amp_int_o` | out | 16 `[AMP_W-1:0]` | clk_i |
| `peak_o` | out | 14 `[DW-1:0]` | clk_i |
| `len_o` | out | 16 `[LEN_W-1:0]` | clk_i |
| `t_peak_o` | out | 16 `[LEN_W-1:0]` | clk_i |
| `q_tot_o` | out | 32 `[QW-1:0]` | clk_i |
| `q_tail_o` | out | 32 `[QW-1:0]` | clk_i |
| `win_id_o` | out | 16 `[PUB_IDW-1:0]` | clk_i |


##### Desde mca_publish

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `pub_occ_i` | in | `[PUB_AW:0]` | clk_i | ocupacion de la FIFO (registro) |
| `pub_done_i` | in | 1 | clk_i | el publicador termina en este ciclo |


##### Estado y contadores

--- linea de base (mca_baseline): la base entra registrada, y la ventana le dice cuando seguir ---

| Puerto | Dir | Bits | Signo | Dominio | Descripción |
|---|---|---|---|---|---|
| `baseline_i` | in | 14 `[DW-1:0]` | signed | clk_i |  |
| `bl_track_o` | out | 1 |  | clk_i | reposo y sin abrir en este flanco |
| `cierra_o` | out | 1 |  | clk_i | la ventana cierra en este flanco |
| `bl_stale_set_o` | out | 1 |  | clk_i | pulso abierto sin muestras |
| `cnt_total_o` | out | 32 |  | clk_i | pulsos cerrados |
| `cnt_rej_amp_o` | out | 32 |  | clk_i | fuera de [min,max] |
| `cnt_pileup_o` | out | 32 |  | clk_i | cerrado por maxlen |
| `cnt_lost_busy_o` | out | 32 |  | clk_i | pulso perdido con el divisor ocupado |
| `last_qtot_o` | out | 32 `[QW-1:0]` |  | clk_i |  |
| `last_qtail_o` | out | 32 `[QW-1:0]` |  | clk_i |  |
| `busy_o` | out | 1 |  | clk_i | pulso activo o divisor ocupado |


##### Casilleros de tiempo muerto

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
| `cnt_cross_o` | out | 32 | clk_i |  |
| `cnt_open_o` | out | 32 | clk_i |  |
| `cnt_lost_rearm_o` | out | 32 | clk_i |  |
| `cnt_lost_active_o` | out | 32 | clk_i |  |
| `cnt_lost_veto_o` | out | 32 | clk_i |  |
| `cnt_lost_notrig_o` | out | 32 | clk_i |  |
| `cnt_win_o` | out | 32 | clk_i |  |
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
El `metrics.txt` del módulo es de `mca_top`, no de `mca_window`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
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
| [`tb_mca_pulse_feature`](../../modulos/mca/sim/tb_mca_pulse_feature.sv) | `mca_pulse_feature` | 17 | 161 | vectores a mano |  |
| [`tb_mca_pulse_feature_eq`](../../modulos/mca/sim/tb_mca_pulse_feature_eq.sv) | `mca_pulse_feature_eq` | — | — | RTL de referencia `mca_pulse_feature_ref.v` instanciado al lado del DUT |  |
| [`tb_mca_top`](../../modulos/mca/sim/tb_mca_top.sv) | `mca_top` | 9 | 82 | vectores a mano |  |


**328 casos con nombre** en 7 testbenches (52 escenas). La lista completa, caso por caso, está en el plan de verificación.

> **`mca_window` no tiene testbench propio.** Ningún `TBS` del `work/Makefile` lo instancia como DUT: lo que se verifica de este módulo es lo que arrastre el TB de otro. Es deuda de verificación, no una omisión de esta página.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`mca_top_sva.sv`](../../modulos/mca/sim/sva/mca_top_sva.sv) — 64 propiedades

Plan de verificación, casos cubiertos y deuda: [`mca/sim/VERIFICACION.md`](../../modulos/mca/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
