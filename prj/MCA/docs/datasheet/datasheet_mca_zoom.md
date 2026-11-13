# Datasheet — `mca_zoom`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/mca_zoom.md.
     Regenerar:  make -C modulos/mca/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `mca_zoom` |
| Archivo | [`mca_zoom.sv`](../../modulos/mca/rtl/mca_zoom.sv) |
| Parámetros | 2 |
| Puertos | 4 (3 in / 1 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mca_zoom](figuras/mca_zoom_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`mca_zoom.sv`](../../modulos/mca/rtl/mca_zoom.sv)):

> mca_zoom — de una feature de FW bits al bin de un eje de AW bits, con zoom
> ALINEADO A POTENCIAS DE 2.
>
> La ventana es  [k*2^(FW-z), (k+1)*2^(FW-z))  con z el nivel de zoom y k el
> indice de ventana. Sobre una feature de FW bits eso es puro rebanado:
>
>     dentro de la ventana  <=>  los z bits ALTOS de feat valen k
>     bin                    =   los AW bits siguientes
>
> Ni restador ni multiplicador: un comparador y un corrimiento variable. Es mas
> barato que un offset arbitrario, no mas caro.
>
> POR QUE ALINEADO A POTENCIAS DE 2, y no un offset libre. Con offsets
> arbitrarios dos espectros tomados con ventanas distintas tienen bordes de bin
> que NO coinciden, y combinarlos exige re-samplear —con su jacobiano y el peine
> de DNL que eso introduce (ver docs/mca/limites_resolucion_y_deriva.md §5).
> Alineado, los bins de cada nivel son subdivisiones EXACTAMENTE anidadas de los
> del nivel anterior: un bin de nivel z es la suma ENTERA de dos de nivel z+1.
> Se cosen con aritmetica entera, sin interpolar y sin agregar DNL.
>
> LO QUE EL ZOOM NO HACE: no mejora la resolucion. Solo recupera la perdida por
> binning (Sheppard), que a 8.6 canales/FWHM ya es 0.31 % de sigma. Sirve para
> UBICAR el eje sobre dos picos juntos y para poder usar un histograma mas
> chico, no para inventar precision que la feature no tiene.
>
> FUERA DE LA VENTANA SATURA, no envuelve ni descarta: un evento por encima va
> al ultimo canal y uno por debajo al canal 0. Es el mismo contrato que ya tenia
> el eje sin zoom —un evento nunca puede aparecer en el extremo opuesto— y deja
> los bins de los extremos como indicadores visibles de desborde. Con la deriva
> medida esto importa: a z=3 un corrimiento del 6.45 % mueve el pico un 41 % del
> ancho de la ventana, asi que los extremos avisan.
>
> z SE SATURA a FW-AW: mas alla no quedan bits que rebanar. Y k se ENMASCARA a
> los z bits utiles, para que z=0 fuerce k=0 en vez de mandar todo al canal 0 en
> silencio si alguien deja un k viejo escrito.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/mca_zoom.md, no aca. -->

**Qué hace.** Lleva una feature de `FW` bits al bin de un eje de `AW` bits,
con **zoom alineado a potencias de 2**. Es la etapa que hay entre el mux de eje
y la memoria del histograma en [`mca_top`](datasheet_mca_top.md), y hay una por
eje.

Sobre una feature de `FW` bits, una ventana `[k·2^(FW−z), (k+1)·2^(FW−z))` es
**puro rebanado de bits**: estar dentro de la ventana es que los `z` bits altos
valgan `k`, y el bin son los `AW` bits siguientes. Ni restador ni
multiplicador: un comparador y un corrimiento variable. Alinear a potencias de
2 sale **más barato** que un offset arbitrario, no más caro.

**Por qué alineado y no un offset libre.** Con offsets arbitrarios, dos
espectros tomados con ventanas distintas tienen bordes de bin que **no
coinciden**, y combinarlos exige re-samplear — con su jacobiano y el peine de
DNL que eso introduce
([`limites_resolucion_y_deriva.md`](../mca/limites_resolucion_y_deriva.md) §5).
Alineados, los bins de cada nivel son subdivisiones **exactamente anidadas** de
los del nivel anterior: un bin de nivel `z` es la suma **entera** de dos de
nivel `z+1`. Se cosen con aritmética entera, sin interpolar y sin agregar DNL.

**Lo que el zoom NO hace: no mejora la resolución.** Sólo recupera la pérdida
por binning (Sheppard), que a 8.6 canales/FWHM ya es el **0.31 % de σ**. Sirve
para *ubicar* el eje sobre dos picos juntos y para poder usar un histograma más
chico — no para inventar precisión que la feature no tiene.

**Fuera de la ventana satura: no envuelve ni descarta.** Un evento por encima
va al último canal y uno por debajo al canal 0. Es el mismo contrato que ya
tenía el eje sin zoom —un evento nunca puede aparecer en el extremo opuesto— y
deja los bins de los extremos como **indicadores visibles de desborde**. Con la
deriva medida esto importa de verdad: a `z = 3`, un corrimiento del 6.45 % mueve
el pico un **41 % del ancho de la ventana**, así que los extremos avisan antes
de que el pico se vaya.

Dos saturaciones de configuración, por el mismo motivo —evitar ajustes que
parecen funcionar y no—: `z` se satura a `FW − AW`, porque más allá no quedan
bits que rebanar; y `k` se enmascara a los `z` bits útiles, para que `z = 0`
fuerce `k = 0` en vez de mandar todo al canal 0 en silencio si quedó escrito un
`k` viejo.
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `FW` | `integer` | `16` | ancho de la feature |
| `AW` | `integer` | `13` | bits del eje de destino |


#### Puertos

##### Señales

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `feat_i` | in | 16 `[FW-1:0]` | sin reloj |  |
| `z_i` | in | 4 | sin reloj | nivel de zoom: ventana = 2^-z del fondo |
| `k_i` | in | 8 | sin reloj | indice de ventana, 0 .. 2^z-1 |
| `bin_o` | out | 13 `[AW-1:0]` | sin reloj |  |
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
El `metrics.txt` del módulo es de `mca_top`, no de `mca_zoom`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
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
| [`tb_mca_zoom`](../../modulos/mca/sim/tb_mca_zoom.sv) | `mca_zoom` | 5 | 11 | vectores a mano | **sí** |
| [`tb_mca_discriminator`](../../modulos/mca/sim/tb_mca_discriminator.sv) | `mca_discriminator` | 7 | 21 | vectores a mano |  |
| [`tb_mca_trap`](../../modulos/mca/sim/tb_mca_trap.sv) | `mca_trap` | — | — | vectores a mano |  |
| [`tb_mca_multi`](../../modulos/mca/sim/tb_mca_multi.sv) | `mca_multi` | — | — | vectores a mano |  |
| [`tb_mca_pulse_feature_evt`](../../modulos/mca/sim/tb_mca_pulse_feature_evt.sv) | `mca_pulse_feature_evt` | — | — | RTL de referencia `mca_pulse_feature_ref.v` instanciado al lado del DUT |  |
| [`tb_mca_top`](../../modulos/mca/sim/tb_mca_top.sv) | `mca_top` | 11 | 131 | vectores a mano |  |


**216 casos con nombre** en 8 testbenches (37 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_mca_zoom`](../../modulos/mca/sim/tb_mca_zoom.sv): 1) z=0, 2) Saturacion, 3) ANIDAMIENTO EXACTO — la propiedad que justifica , 4) Contra el modelo de referencia, barriendo todo e, 5) Configuraciones que NO deben ser trampas silenci.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`mca_top_sva.sv`](../../modulos/mca/sim/sva/mca_top_sva.sv) — 74 propiedades

Plan de verificación, casos cubiertos y deuda: [`mca/sim/VERIFICACION.md`](../../modulos/mca/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
