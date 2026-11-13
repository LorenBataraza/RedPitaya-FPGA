# Datasheet — `mca_discriminator`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/mca_discriminator.md.
     Regenerar:  make -C modulos/mca/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `mca_discriminator` |
| Archivo | [`mca_discriminator.sv`](../../modulos/mca/rtl/mca_discriminator.sv) |
| Parámetros | 2 |
| Puertos | 7 (6 in / 1 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mca_discriminator](figuras/mca_discriminator_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`mca_discriminator.sv`](../../modulos/mca/rtl/mca_discriminator.sv)):

> mca_discriminator — acepta o rechaza un evento por el valor de UNA feature.
>
> Antes esto eran dos lineas sueltas adentro de la FSM del extractor
> (`amp_ok`): una condicion, feature FIJA (la amplitud seleccionada), y solo
> intervalo interno. Aca pasa a ser un bloque con selector, y el intervalo
> puede ser interno [min,max] o su complemento.
>
> VA DESPUES DE LOS DIVISORES, no antes. Es lo que permite que el selector
> alcance tambien a las features de FORMA, que no existen hasta que el divisor
> termina. Y esa es justamente la que importa: medido por Monte-Carlo sobre el
> espectro de una linea a 100 kcps, un corte por ANCHO (Pico/Q_total) rechaza
> el 99.1 % de los apilados y baja el continuo sobre el fotopico de 32.4 % a
> 0.8 %, sin perder un solo evento limpio. El eje de forma que ya estaba en el
> hardware (Q_cola/Q_total) rechaza el 29.6 % en modo histeresis y EXACTAMENTE
> NADA en modo compuerta. Ver software/monte-carlo/.
>
> El costo de estar despues del divisor es que todo evento paga su latencia
> antes de poder ser rechazado. Son DIV_W ciclos = 128 ns contra una ventana de
> 3.07 us: el 4 %.
>
> EL CORTE HAY QUE CALIBRARLO CONTRA LA AMPLITUD. `Pico/Q_total` NO es
> constante: en modo histeresis la ventana cierra cuando la cola cruza el
> umbral, o sea que su largo crece con el logaritmo de la amplitud, y el
> cociente deriva ~21 % de punta a punta del rango. Un umbral fijo cortaria los
> pulsos limpios chicos y dejaria pasar los apilados grandes. La calibracion se
> hace con un pulser DESLIZANTE y no con el espectro fuente: con una linea
> monoenergetica el lugar geometrico queda definido en un punado de canales y el
> corte terminaria rechazando por caer fuera del rango calibrado y no por tener
> la forma mal — un corte en amplitud disfrazado de corte en forma, que da un
> resultado espectacular y falso.
>
> INTERVALO VACIO: con min > max el conjunto interno es vacio por definicion,
> asi que `interno` rechaza TODO y `externo` acepta todo. No es un caso de
> error, es la respuesta correcta a lo que se pidio, y esta fijado por un test
> para que nadie lo "arregle" despues.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/mca_discriminator.md, no aca. -->

**Qué hace.** Decide si un evento **entra o no entra** al histograma, mirando
**una** feature del bus de evento contra un intervalo. No mira muestras: mira
el evento ya cerrado, con todas sus características calculadas, y su veredicto
alcanza al evento completo.

Antes esto eran dos líneas sueltas dentro de la FSM del extractor (`amp_ok`):
una condición, feature **fija** —la amplitud— e intervalo siempre interno. Acá
es un bloque con selector, y el intervalo puede ser **interno** `[min, max]` o
su complemento.

**Va después de los divisores, y ahí está todo el punto.** Ponerlo antes
costaría nada y serviría para la mitad: las features de **forma** no existen
hasta que el divisor termina, y son justamente las que importan. Medido por
Monte-Carlo sobre el espectro de una línea a 100 kcps
(`software/monte-carlo/`):

| Corte | Qué rechaza | Efecto sobre el continuo bajo el fotopico |
|---|---|---|
| por **ancho** (`Pico/Q_total`) | **99.1 %** de los apilados, sin perder un solo evento limpio | 32.4 % → **0.8 %** |
| por `Q_cola/Q_total`, modo histéresis | 29.6 % | — |
| por `Q_cola/Q_total`, modo compuerta | **exactamente nada** | — |

El precio de estar después del divisor es que todo evento paga su latencia
antes de poder ser rechazado: `DIV_W` ciclos = **128 ns** contra una ventana de
3.07 µs, el **4 %**.

> **El corte hay que calibrarlo contra la amplitud, y con un pulser
> deslizante.** `Pico/Q_total` **no** es constante: en modo histéresis la
> ventana cierra cuando la cola cruza el umbral, o sea que su largo crece con
> el logaritmo de la amplitud y el cociente deriva **~21 %** de punta a punta
> del rango. Un umbral fijo cortaría los pulsos limpios chicos y dejaría pasar
> los apilados grandes. Y la calibración **no** se hace con el espectro fuente:
> con una línea monoenergética el lugar geométrico queda definido en un puñado
> de canales, y el corte terminaría rechazando por caer fuera del rango
> calibrado en vez de por tener la forma mal — un corte en amplitud disfrazado
> de corte en forma, que da un resultado espectacular y falso.

**Intervalo vacío.** Con `min > max` el conjunto interno es vacío por
definición, así que `interno` rechaza **todo** y `externo` acepta todo. No es
un caso de error: es la respuesta correcta a lo que se pidió, y está fijado por
un test para que nadie lo «arregle» después.

Un detalle de implementación que ya mordió una vez: la selección de feature es
un *part-select* indexado y **no** una función. Dentro de un `assign` continuo
una función no queda sensible a lo que lee del alcance exterior, y el mux se
quedaría clavado en el valor de reset. Pasó en `mca_top`.
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `FW` | `integer` | `16` | ancho de una feature |
| `NFEAT` | `integer` | `16` | ranuras del bus |


#### Puertos

##### Señales

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `ev_feat_i` | in | 256 `[NFEAT*FW-1:0]` | sin reloj |  |
| `cfg_en_i` | in | 1 | sin reloj | 0 = pasa todo (default) |
| `cfg_sel_i` | in | 4 | sin reloj | que feature mira (indices F_* ) |
| `cfg_out_i` | in | 1 | sin reloj | 0 = interno [min,max], 1 = externo |
| `cfg_min_i` | in | 16 `[FW-1:0]` | sin reloj |  |
| `cfg_max_i` | in | 16 `[FW-1:0]` | sin reloj |  |
| `accept_o` | out | 1 | sin reloj |  |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
Mapas de registros de la región:

- [`register_map_mca.md`](../mca/register_map_mca.md)

Contrato del bus: [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) · Mapa de slots: [`register_map_top.md`](../TOP/register_map_top.md)
<!-- /AUTO:regmap -->

### 1.4 Clock domains

<!-- AUTO:clocks -->
_(nada)_


**Combinacional:** el módulo no tiene puerto de reloj.
<!-- /AUTO:clocks -->

<!-- A mano: si hay más de un reloj, cuál es el cruce, con qué se sincroniza y
     qué se asume de la relación de frecuencias. Si hay uno solo, borrar. -->

### 1.5 Frecuencia máxima de trabajo

<!-- AUTO:timing -->
El `metrics.txt` del módulo es de `mca_top`, no de `mca_discriminator`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
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
| [`tb_mca_discriminator`](../../modulos/mca/sim/tb_mca_discriminator.sv) | `mca_discriminator` | 7 | 21 | vectores a mano | **sí** |
| [`tb_mca_trap`](../../modulos/mca/sim/tb_mca_trap.sv) | `mca_trap` | — | — | vectores a mano |  |
| [`tb_mca_multi`](../../modulos/mca/sim/tb_mca_multi.sv) | `mca_multi` | — | — | vectores a mano |  |
| [`tb_mca_pulse_feature_evt`](../../modulos/mca/sim/tb_mca_pulse_feature_evt.sv) | `mca_pulse_feature_evt` | — | — | RTL de referencia `mca_pulse_feature_ref.v` instanciado al lado del DUT |  |
| [`tb_mca_top`](../../modulos/mca/sim/tb_mca_top.sv) | `mca_top` | 11 | 131 | vectores a mano |  |


**216 casos con nombre** en 8 testbenches (37 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_mca_discriminator`](../../modulos/mca/sim/tb_mca_discriminator.sv): 1) Deshabilitado pasa TODO, sin importar min/max ni, 2) Intervalo INTERNO [min,max], bordes INCLUIDOS, 3) Intervalo EXTERNO, 4) El SELECTOR elige de verdad. Con la misma ventan, 5) INTERVALO VACIO (min > max). No es un error, 6) Ventana degenerada de UN valor (min == max), 7) Los extremos del rango sin signo, que es el cont.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`mca_top_sva.sv`](../../modulos/mca/sim/sva/mca_top_sva.sv) — 74 propiedades

Plan de verificación, casos cubiertos y deuda: [`mca/sim/VERIFICACION.md`](../../modulos/mca/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
