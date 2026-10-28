# Datasheet — `mca_div_restore`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/mca_div_restore.md.
     Regenerar:  make -C modulos/mca/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `mca_div_restore` |
| Archivo | [`mca_div_restore.sv`](../../modulos/mca/rtl/mca_div_restore.sv) |
| Parámetros | 2 |
| Puertos | 10 (5 in / 5 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mca_div_restore](figuras/mca_div_restore_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`mca_div_restore.sv`](../../modulos/mca/rtl/mca_div_restore.sv)):

> mca_div_restore — divisor restaurador para el factor de forma (PSD)
>
> Calcula  q = floor( num * 2^Q_W / den )  con num < den, o sea la fracción
> num/den expresada en Q_W bits. Se usa para  PSD = Q_cola / Q_total, donde
> el resultado ES directamente el índice de bin del eje de forma.
>
> Truco: como num < den, arrancando con rem = num y haciendo
>        rem = 2*rem;  if (rem >= den) { rem -= den; q |= 1; }
> se obtiene un bit de cociente por iteración, así que hacen falta
> EXACTAMENTE Q_W iteraciones sin importar el ancho de los operandos
> (no hace falta normalizar previamente). Con Q_W=6 son 6 ciclos y cero DSP.
>
> Invariante: rem < den en todo momento. Inicialmente rem=num<den; y si
> rem2=2*rem >= den entonces rem2-den < den (porque rem2 < 2*den). Por eso
> `rem` entra en D_W bits aunque el intermedio `rem2` necesite D_W+1.
>
> Latencia FIJA de Q_W ciclos para TODOS los casos, incluidos los de error.
> Es deliberado: hace predecible el tiempo muerto por evento, que es uno de
> los parámetros a caracterizar del MCA.
>
> Casos borde (los tres rompen si no se tratan explícitamente):
>   den == 0  -> err_o. Sin esta guarda `rem >= 0` da siempre true y el
>                cociente sale todo unos: todos esos eventos caerían en el
>                bin superior del eje de forma.
>   num >= den-> sat_o y q = 2^Q_W-1. Sin saturar, num==den da 2^Q_W que no
>                entra en Q_W bits y ENVUELVE A 0, o sea manda el evento al
>                extremo OPUESTO del eje. Es el modo de falla peligroso.
>   num == 0  -> q = 0, sin flags. Es un resultado válido.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/mca_div_restore.md, no aca. -->

**Qué hace.** Es el divisor que convierte dos acumuladores de carga en un
**índice de bin**: calcula `q = floor(num · 2^Q_W / den)` con `num < den`, o
sea la fracción `num/den` expresada en `Q_W` bits. El resultado **es**
directamente la coordenada del eje de forma, sin escalado posterior.

[`mca_pulse_feature`](datasheet_mca_pulse_feature.md) instancia **dos**, con el
mismo denominador y el mismo arranque: uno para `Q_cola/Q_total` y otro para
`Pico/Q_total`. Como comparten latencia, el segundo no necesita ni que se le
mire el `valid`.

**El truco que lo hace barato.** Como `num < den`, arrancando con `rem = num` y
haciendo `rem = 2·rem; if (rem ≥ den) { rem −= den; q |= 1; }` sale **un bit de
cociente por iteración**, así que hacen falta exactamente `Q_W` iteraciones sin
importar el ancho de los operandos: no hay que normalizar nada de antemano.
Cero DSP. El invariante `rem < den` vale siempre —si `2·rem ≥ den` entonces
`2·rem − den < den`, porque `2·rem < 2·den`— y por eso `rem` entra en `D_W`
bits aunque el intermedio necesite `D_W+1`.

**La latencia es fija para todos los casos, incluidos los de error.** Es
deliberado: hace predecible el tiempo muerto por evento, que es uno de los
parámetros a caracterizar del MCA
([`tiempo_muerto.md`](../mca/tiempo_muerto.md)). Tal como está instanciado
—`D_W = 32`, `Q_W = 16`— son 16 ciclos, 128 ns.

**Los tres casos borde rompen cosas distintas si no se tratan.**

| Caso | Sin la guarda | Con la guarda |
|---|---|---|
| `den == 0` | `rem ≥ 0` da siempre cierto y el cociente sale todo unos: **todos** esos eventos caen en el bin superior del eje | `err_o`, y el evento se rechaza |
| `num ≥ den` | `num == den` da `2^Q_W`, que no entra en `Q_W` bits y **envuelve a 0**: manda el evento al extremo **opuesto** del eje. Es el modo de falla peligroso | `sat_o` y `q = 2^Q_W − 1` |
| `num == 0` | — | `q = 0`, sin flags. Es un resultado válido |

> **Dónde no llega el testbench.** `tb_mca_div_restore` hace un barrido
> **exhaustivo** de `num`/`den`… con anchos reducidos: `D_W = 8, Q_W = 6`. El
> diseño lo instancia con `D_W = 32, Q_W = 16`. O sea que la prueba más fuerte
> que tiene el módulo cubre un ancho que el diseño no usa. Es exacto, acotado y
> de espacio de estados chico: el mejor candidato barato a verificación formal
> del repo, con `q·d + r == n` y `start |-> ##N valid` como propiedades. Ver
> [`verificacion_formal.md`](../verificacion_formal.md).
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `D_W` | `integer` | `32` | ancho de numerador y denominador |
| `Q_W` | `integer` | `6` | bits de cociente (= bits del eje PSD) |


#### Puertos

##### Señales

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `clk_i` | in | 1 | — |  |
| `rstn_i` | in | 1 | — | reset síncrono activo-bajo |
| `start_i` | in | 1 | clk_i | pulso de arranque (ignorado si busy) |
| `num_i` | in | 32 `[D_W-1:0]` | clk_i | numerador   (Q_cola) |
| `den_i` | in | 32 `[D_W-1:0]` | clk_i | denominador (Q_total) |
| `q_o` | out | 6 `[Q_W-1:0]` | clk_i | cociente en Q_W bits |
| `valid_o` | out | 1 | clk_i | pulso de 1 ciclo: q_o/err_o/sat_o válidos |
| `err_o` | out | 1 | clk_i | den_i == 0     -> rechazar el evento |
| `sat_o` | out | 1 | clk_i | num_i >= den_i -> q_o saturado |
| `busy_o` | out | 1 | clk_i |  |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
Mapas de registros de la región:

- [`register_map_mca.md`](../mca/register_map_mca.md)

Contrato del bus: [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) · Mapa de slots: [`register_map_top.md`](../TOP/register_map_top.md)
<!-- /AUTO:regmap -->

### 1.4 Clock domains

<!-- AUTO:clocks -->
| Puerto | Qué es | Polaridad | Notas |
|---|---|---|---|
| `clk_i` | reloj |  |  |
| `rstn_i` | reset | activo-bajo | reset síncrono activo-bajo |


**Un solo dominio.** Todos los puertos de datos y de control son síncronos a `clk_i`: no hay cruce de dominio dentro de este módulo.
<!-- /AUTO:clocks -->

<!-- A mano: si hay más de un reloj, cuál es el cruce, con qué se sincroniza y
     qué se asume de la relación de frecuencias. Si hay uno solo, borrar. -->

### 1.5 Frecuencia máxima de trabajo

<!-- AUTO:timing -->
El `metrics.txt` del módulo es de `mca_top`, no de `mca_div_restore`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
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
| [`tb_mca_div_restore`](../../modulos/mca/sim/tb_mca_div_restore.sv) | `mca_div_restore` | 6 | 22 | vectores a mano | **sí** |
| [`tb_mca_hist`](../../modulos/mca/sim/tb_mca_hist.sv) | `mca_hist` | 8 | 31 | vectores a mano |  |
| [`tb_mca_zoom`](../../modulos/mca/sim/tb_mca_zoom.sv) | `mca_zoom` | 5 | 11 | vectores a mano |  |
| [`tb_mca_discriminator`](../../modulos/mca/sim/tb_mca_discriminator.sv) | `mca_discriminator` | 7 | 21 | vectores a mano |  |
| [`tb_mca_pulse_feature`](../../modulos/mca/sim/tb_mca_pulse_feature.sv) | `mca_pulse_feature` | 17 | 161 | vectores a mano |  |
| [`tb_mca_pulse_feature_eq`](../../modulos/mca/sim/tb_mca_pulse_feature_eq.sv) | `mca_pulse_feature_eq` | — | — | RTL de referencia `mca_pulse_feature_ref.v` instanciado al lado del DUT |  |
| [`tb_mca_top`](../../modulos/mca/sim/tb_mca_top.sv) | `mca_top` | 9 | 82 | vectores a mano |  |


**328 casos con nombre** en 7 testbenches (52 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_mca_div_restore`](../../modulos/mca/sim/tb_mca_div_restore.sv): 1) Barrido EXHAUSTIVO del camino normal, 2) den == 0 -> err_o, 3) num >= den -> sat_o, q = 2^Q_W-1. Sin esta guard, 4) Casos de valor conocido, 5) Latencia fija = Q_W ciclos, tambien en los casos, 6) start_i durante busy se ignora (no corrompe la d.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`mca_top_sva.sv`](../../modulos/mca/sim/sva/mca_top_sva.sv) — 64 propiedades

Plan de verificación, casos cubiertos y deuda: [`mca/sim/VERIFICACION.md`](../../modulos/mca/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
