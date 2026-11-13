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
| Parámetros | 17 |
| Puertos | 59 (29 in / 30 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mca_pulse_feature](figuras/mca_pulse_feature_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`mca_pulse_feature.sv`](../../modulos/mca/rtl/mca_pulse_feature.sv)):

> mca_pulse_feature — segmentador de pulsos y extractor de características
>
> Recibe la muestra ya calibrada/filtrada (y retrasada por mca_delay) y, por
> cada pulso que dispara el multitrigger, emite UN registro de evento coherente
> que alimenta a todos los motores de histograma. Que salga de un único
> registro es lo que garantiza que el espectro 1D y el mapa 2D cuenten
> exactamente los mismos pulsos.
>
> PARTICION: este modulo es solo cableado
>   mca_baseline la linea de base: seguidor IIR o base fija (D3)
>   mca_window   el nucleo: la muestra relativa a la base, el disparo, el
>                asignador de ranuras, las N_ACC ranuras (mca_slot) con sus
>                acumuladores y la ventana de amplitud (D7), el conformado
>                trapezoidal (mca_trap) y la contabilidad del tiempo muerto
>   mca_publish  la cola de ranuras cerradas, los dos mca_div_restore y el
>                armado del bus de features
>
> DONDE VAN LAS FRONTERAS lo decide el timing: el bitstream se sintetiza con
> -flatten_hierarchy none, asi que cada puerto es una barrera de optimizacion.
> Todo lo que cruza sale de un registro: la base (de mca_baseline), la muestra
> saturada (xc_q, adentro de mca_window, antes de repartirse a las ranuras) y
> los resultados de las ranuras.
>
> VARIAS VENTANAS A LA VEZ
> La ventana la abre SOLO el trigger externo (el multitrigger, con su disparo
> por pendiente): el Schmitt interno se saco porque no ve un pulso montado
> sobre la cola de otro. Con eso dejaron de existir quien abre (D4), quien
> cierra (D5: siempre compuerta fija), el re-armado (D6: lo hace el
> multitrigger) y el modo de publicacion (D8: lo reemplaza cfg_n_acc).
>
> cfg_n_acc elige cuantas ranuras se usan, de 1 a N_ACC. Con 1, una ranura que
> cierra espera a los divisores antes de poder reabrir: es la publicacion
> bloqueante de antes. Con mas, un disparo que llega con una ventana abierta
> abre otra, y la perdida de eventos pasa de ser de primer orden en la tasa a
> ~rho^N/N! (modelo M/D/N/N). Lo que se mide sobre otro pulso viene
> contaminado: se MARCA en el bus de features (F_DTPREV, F_DTNEXT, F_SOLAPE) y
> lo deciden el discriminador o el software.
>
> La CORRECCION es el conformado trapezoidal (mca_trap, D13): cancela el polo
> de la cola, asi que cada pulso sale como un trapecio que vuelve a cero en
> 2k+m muestras, y cada ranura promedia su meseta en F_TRAP. Dos pulsos
> separados k+m o mas miden limpio aunque se pisen en la entrada; F_DTPREV y
> F_DTNEXT dicen cuales son.
>
> Con el BANCO (N_FORMAS trapecios, de la forma mas larga a la mas corta) cada
> ranura suma la meseta de todas, y al publicar se elige la mas larga que el
> vecino permite, por dt_prev y dt_next contra los umbrales de cada forma; la
> elegida sale en F_FORMA. Ver mca_publish y docs/mca/pruebas_banco_trapecios.md.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/mca_pulse_feature.md, no aca. -->

**Qué hace.** Es el extractor de características: por cada disparo abre una
ventana en una ranura libre, acumula las características del pulso y publica un
evento coherente con 16 features. Que salga de un único registro es lo que
garantiza que el espectro 1D y el mapa 2D cuenten exactamente los mismos pulsos.
Mide varios pulsos a la vez: tiene `N_ACC` ranuras y `cfg_n_acc` elige cuántas
se usan.

**Es cableado.** El trabajo está en `mca_baseline` (la base, **D3**),
`mca_window` (el disparo, el asignador, las ranuras y la contabilidad, **D8**),
`mca_slot` (cada ranura, con la ventana de amplitud de **D7**) y `mca_publish`
(la cola y los divisores). Las fronteras están donde lo que cruza sale de un
registro, porque el sintetizador no aplana jerarquía. Ver la
[vista general](../mca/vista_general_mca.md) §2.
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
| `N_ACC` | `integer` | `4` → **`3`** (del TOP) | ranuras de medicion |
| `PUB_IDW` | `integer` | `16` | bits del id de ventana |
| `NA_W` | `integer` | `3` | bits de cfg_n_acc |
| `N_FORMAS` | `integer` | `4` → **`3`** (del TOP) | trapecios del banco; 0: sin trapecio (F_TRAP vale cero) |
| `TDAW` | `integer` | `10` | log2 de la profundidad de sus lineas de retardo |
| `TMW` | `integer` | `20` | bits de su constante polo-cero |
| `OC_W` | `integer` | `$clog2(N_ACC + 1)` = `2` |  |
| `NF` | `integer` | `(N_FORMAS < 1) ? 1 : N_FORMAS` |  |


Los marcados **(del TOP)** son los valores con los que el diseño se construye de verdad (`GENERICS` del `work/Makefile`); los anchos de esta página están resueltos con ésos, no con los defaults del RTL.


#### Puertos

##### Reloj y reset

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `clk_i` | in | 1 | — |
| `rstn_i` | in | 1 | — |


##### Muestras de entrada (calibradas, filtradas, decimadas y retrasadas)

| Puerto | Dir | Bits | Signo | Dominio |
|---|---|---|---|---|
| `dat_i` | in | 14 `[DW-1:0]` | signed | clk_i |
| `val_i` | in | 1 |  | clk_i |


##### Configuración

| Puerto | Dir | Bits | Signo | Dominio | Descripción |
|---|---|---|---|---|---|
| `cfg_run_i` | in | 1 |  | clk_i |  |
| `veto_i` | in | 1 |  | clk_i | VETO externo (nivel): no se abren ventanas nuevas mientras vale 1. Las que estan abiertas terminan normal, y el seguidor de linea de base SIGUE corriendo -- a diferencia de cfg_run=0 --, porque la base deriva igual durante el veto. Viene del trigger_shield del multitrigger (dst = mca). |
| `cnt_clr_i` | in | 1 |  | clk_i | pulso: pone a cero los contadores |
| `cfg_baseline_i` | in | 14 `[DW-1:0]` | signed | clk_i | base fija si cfg_bl_auto=0 |
| `cfg_bl_auto_i` | in | 1 |  | clk_i |  |
| `cfg_bl_k_i` | in | 4 `[BL_KW-1:0]` |  | clk_i | alfa = 2^-k |
| `cfg_bl_holdoff_i` | in | 16 `[LEN_W-1:0]` |  | clk_i |  |
| `cfg_gate_short_i` | in | 16 `[LEN_W-1:0]` |  | clk_i | compuerta corta (cola), en muestras |
| `cfg_gate_long_i` | in | 16 `[LEN_W-1:0]` |  | clk_i | compuerta larga (ventana), en muestras |
| `cfg_amp_min_i` | in | 16 `[AMP_W-1:0]` |  | clk_i |  |
| `cfg_amp_max_i` | in | 16 `[AMP_W-1:0]` |  | clk_i |  |
| `cfg_amp_src_i` | in | 1 |  | clk_i | 0=pico, 1=integral |
| `cfg_q_shift_i` | in | 5 |  | clk_i |  |
| `cfg_n_acc_i` | in | 3 `[NA_W-1:0]` |  | clk_i | ranuras habilitadas, 1..N_ACC |
| `trig_i` | in | 1 |  | clk_i | Trigger externo, el UNICO que abre ventanas. Se toma por FLANCO. |


##### El banco de trapecios (mca_trap): NF formas, aplanadas, y la eleccion

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `trap_clr_i` | in | 1 | clk_i | pulso: reinicia su estado |
| `cfg_trap_k_i` | in | `[NF*TDAW-1:0]` | clk_i | subida, >= 1 |
| `cfg_trap_l_i` | in | `[NF*TDAW-1:0]` | clk_i | subida + meseta |
| `cfg_trap_mq_i` | in | 20 `[TMW-1:0]` | clk_i | polo-cero, M * 16 (comun) |
| `cfg_trap_sh_i` | in | `[NF*6-1:0]` | clk_i | escala de F_TRAP |
| `cfg_trap_off_i` | in | `[NF*LEN_W-1:0]` | clk_i | inicio de la meseta, desde la apertura |
| `cfg_trap_lw_i` | in | `[NF*3-1:0]` | clk_i | largo de la meseta: 2^lw |
| `cfg_trap_antes_i` | in | `[NF*LEN_W-1:0]` | clk_i | umbral de dt_prev de cada forma |
| `cfg_trap_despues_i` | in | `[NF*LEN_W-1:0]` | clk_i | umbral de dt_next de cada forma |
| `cfg_n_formas_i` | in | 3 | clk_i | formas habilitadas (0 = 1) |


##### Evento de salida (pulso de 1 ciclo)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `ev_valid_o` | out | 1 | clk_i |  |
| `ev_amp_o` | out | 16 `[AMP_W-1:0]` | clk_i |  |
| `ev_psd_o` | out | 6 `[PSD_AW-1:0]` | clk_i |  |
| `ev_psd_ok_o` | out | 1 | clk_i | 0 => no histogramear el 2D |
| `ev_feat_o` | out | 256 `[NFEAT*AMP_W-1:0]` | clk_i | Bus de features: NFEAT ranuras de AMP_W bits, todas del MISMO evento. |


##### Estado y contadores

| Puerto | Dir | Bits | Signo | Dominio | Descripción |
|---|---|---|---|---|---|
| `baseline_o` | out | 14 `[DW-1:0]` | signed | clk_i |  |
| `baseline_stale_o` | out | 1 |  | clk_i |  |
| `cnt_total_o` | out | 32 |  | clk_i | ventanas cerradas |
| `cnt_accepted_o` | out | 32 |  | clk_i |  |
| `cnt_rej_amp_o` | out | 32 |  | clk_i | fuera de [min,max] |
| `cnt_rej_psd_o` | out | 32 |  | clk_i | q_tot=0 o q_tail>=q_tot |
| `cnt_pileup_o` | out | 32 |  | clk_i | cerradas con marca de solape |
| `cnt_lost_busy_o` | out | 32 |  | clk_i | sin ranura, alguna esperando publicar |
| `last_qtot_o` | out | 32 `[QW-1:0]` |  | clk_i |  |
| `last_qtail_o` | out | 32 `[QW-1:0]` |  | clk_i |  |
| `busy_o` | out | 1 |  | clk_i | alguna ranura ocupada |


##### Casilleros de tiempo muerto: disjuntos, y su union es "no puede abrir"

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `dt_win_o` | out | 1 | clk_i | sin ranura libre, todas midiendo |
| `dt_div_o` | out | 1 | clk_i | sin ranura libre, alguna esperando publicar |
| `puede_abrir_o` | out | 1 | clk_i |  |
| `n_ocup_o` | out | 2 `[OC_W-1:0]` | clk_i | ranuras ocupadas ahora |


##### Atribucion de arribos: cada disparo va a UN casillero

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `arribo_o` | out | 1 | clk_i | disparo en esta muestra, con run |
| `cnt_cross_o` | out | 32 | clk_i | todos los arribos |
| `cnt_open_o` | out | 32 | clk_i | ...que abrieron ranura |
| `cnt_lost_active_o` | out | 32 | clk_i | ...sin ranura libre, todas midiendo |
| `cnt_lost_veto_o` | out | 32 | clk_i | ...bajo veto |
| `cnt_win_o` | out | 32 | clk_i | ventanas abiertas |


##### La cola de publicacion

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `pub_occ_o` | out | 2 `[OC_W-1:0]` | clk_i | ranuras esperando publicar |
| `pub_occ_max_o` | out | 2 `[OC_W-1:0]` | clk_i | maximo historico |
| `last_win_id_o` | out | 16 `[PUB_IDW-1:0]` | clk_i | id de la ultima ventana publicada |
| `cnt_trig_o` | out | 32 | clk_i | flancos crudos de trig_i |
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

![(a) LA SENAL: UN PULSO POR EVENTO](../mca/figuras/07a_senal.svg)

Las bandas parten el eje de TIEMPO en estados --ventana abierta, reposo-- y no la senal en eventos. La ventana abre al cruzar `thr` y cierra recien al bajar de `thr - hyst`, que es lo que hace que termine bastante despues del pico.

_Origen: la misma simulacion, panel (a) suelto, en TikZ (`figuras_cadena_tikz.py`)._

**(b) EL CAMINO DE DATOS: UN NUMERO POR PULSO**

![(b) EL CAMINO DE DATOS: UN NUMERO POR PULSO](../mca/figuras/07b_cadena.svg)

`pulse_feature` emite un registro de evento por pulso y el histograma lo convierte en una cuenta. La tabla de abajo son los mismos pulsos como los ve el histograma, incluido el que no cruza el umbral y no produce nada.

_Origen: la misma simulacion, panel (b) suelto, en TikZ (`figuras_cadena_tikz.py`)._

**(c) EL ESPECTRO: UNA CUENTA POR NUMERO**

![(c) EL ESPECTRO: UNA CUENTA POR NUMERO](../mca/figuras/07c_histograma.svg)

El espectro final en barras apiladas: cada capa es un tramo de la acumulacion (las primeras 12 cuentas, de la 13 a la 64 y de la 65 a la 227), asi que el borde de arriba de cada capa es el espectro en ese momento. La capa de abajo son cuentas sueltas; la forma de las dos lineas aparece recien cuando hay estadistica.

_Origen: la misma simulacion, panel (c) suelto, en TikZ (`figuras_cadena_tikz.py`)._

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
make -C modulos/mca/work            # los 8 testbenches
make -C modulos/mca/work cov        # + cobertura
make -C modulos/mca/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_mca_div_restore`](../../modulos/mca/sim/tb_mca_div_restore.sv) | `mca_div_restore` | 6 | 22 | vectores a mano |  |
| [`tb_mca_hist`](../../modulos/mca/sim/tb_mca_hist.sv) | `mca_hist` | 8 | 31 | vectores a mano |  |
| [`tb_mca_zoom`](../../modulos/mca/sim/tb_mca_zoom.sv) | `mca_zoom` | 5 | 11 | vectores a mano |  |
| [`tb_mca_discriminator`](../../modulos/mca/sim/tb_mca_discriminator.sv) | `mca_discriminator` | 7 | 21 | vectores a mano |  |
| [`tb_mca_trap`](../../modulos/mca/sim/tb_mca_trap.sv) | `mca_trap` | — | — | vectores a mano |  |
| [`tb_mca_multi`](../../modulos/mca/sim/tb_mca_multi.sv) | `mca_multi` | — | — | vectores a mano |  |
| [`tb_mca_pulse_feature_evt`](../../modulos/mca/sim/tb_mca_pulse_feature_evt.sv) | `mca_pulse_feature_evt` | — | — | RTL de referencia `mca_pulse_feature_ref.v` instanciado al lado del DUT |  |
| [`tb_mca_top`](../../modulos/mca/sim/tb_mca_top.sv) | `mca_top` | 11 | 131 | vectores a mano |  |


**216 casos con nombre** en 8 testbenches (37 escenas). La lista completa, caso por caso, está en el plan de verificación.

> **`mca_pulse_feature` no tiene testbench propio.** Ningún `TBS` del `work/Makefile` lo instancia como DUT: lo que se verifica de este módulo es lo que arrastre el TB de otro. Es deuda de verificación, no una omisión de esta página.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`mca_top_sva.sv`](../../modulos/mca/sim/sva/mca_top_sva.sv) — 74 propiedades

Plan de verificación, casos cubiertos y deuda: [`mca/sim/VERIFICACION.md`](../../modulos/mca/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
