# Datasheet — `mca_hist`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     Regenerar:  make -C modulos/mca/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `mca_hist` |
| Archivo | [`mca_hist.sv`](../../modulos/mca/rtl/mca_hist.sv) |
| Parámetros | 2 |
| Puertos | 13 (8 in / 5 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mca_hist](figuras/mca_hist_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`mca_hist.sv`](../../modulos/mca/rtl/mca_hist.sv)):

> mca_hist — motor de histograma genérico (una implementación, N instancias)
>
> Memoria de 2^AW bins de CW bits, inferida como BRAM simple-dual-port:
>   Puerto A: SÓLO ESCRITURA  — write-back del incremento, y barrido de borrado
>   Puerto B: SÓLO LECTURA    — lectura del bus, y lectura del pipeline
>
> Por qué no un read-modify-write de 3 estados (como el axis_histogram.v de
> pavel-demin): un puerto de BRAM tiene UNA dirección por ciclo, así que no
> puede leer addr(n) y escribir addr(n-2) a la vez. Con la lectura en el
> puerto B y la escritura en el A se consigue 1 incremento por ciclo, a costa
> de necesitar forwarding (abajo). El de 3 estados acepta 1 evento cada 3
> ciclos, lo que obligaría a decimar un futuro mapa de persistencia.
>
> FORWARDING (2 etapas). El evento que lee en el ciclo m tiene su dato en m+1
> y escribe en m+2. Un evento a la MISMA dirección en m+1 o m+2 leería un
> valor viejo, así que hay que puentear:
>   - distancia 1: la escritura que ocurre en este mismo ciclo  -> wdata2
>   - distancia 2: la escritura que ocurrió en el ciclo anterior -> wdata3
>   - distancia >=3: la memoria ya está actualizada, no hace falta.
> La prioridad va de más nuevo a más viejo.
>
> BARRIDO DE BORRADO: usa SÓLO el puerto de escritura, así que el puerto de
> lectura queda vivo durante todo el barrido. Es un requisito duro: un barrido
> de 16384 bins son 16384 ciclos = 131 us, ~500 veces el timeout de 32 ciclos
> de axi4_slave.sv:193. Si el barrido frenara el ack, el bus se colgaría.
>
> CONTENCIÓN: la lectura del bus tiene prioridad sobre el puerto B. Un evento
> que llegue en ese ciclo (o durante el barrido) se descarta y se CUENTA en
> dropped_o, para que la pérdida sea medible. Con eventos separados por
> cientos de ciclos y lecturas de bus separadas por microsegundos, la
> probabilidad de colisión es despreciable; leer con run=0 la elimina.
>
> NOTA: rd_i tiene que ser un PULSO DE 1 CICLO, no el `ren` sostenido del bus.
> sys_bus_cdc mantiene ren alto hasta el ack (~4 ciclos); si se conectara
> directo, cada acceso del bus robaría 4 ciclos al pipeline en vez de 1.
<!-- /AUTO:resumen -->

<!-- A mano: qué problema resuelve el bloque, cómo encaja en la cadena y las
     dos o tres decisiones de diseño que explican por qué está hecho así. -->

**Qué hace.** TODO

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `AW` | `integer` | `12` | bins = 2^AW |
| `CW` | `integer` | `32` | ancho del contador (saturante) |


#### Puertos

##### Reloj y reset

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `clk_i` | in | 1 | — |  |
| `rstn_i` | in | 1 | — | reset síncrono activo-bajo |


##### Entrada de eventos: 1 incremento por ciclo

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `inc_i` | in | 1 | clk_i |
| `inc_addr_i` | in | 12 `[AW-1:0]` | clk_i |


##### Borrado

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `clear_i` | in | 1 | clk_i | pulso: arranca el barrido |
| `busy_o` | out | 1 | clk_i | barrido en progreso |


##### Lectura de bus (prioridad sobre el pipeline)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `rd_i` | in | 1 | clk_i | PULSO de 1 ciclo |
| `rd_addr_i` | in | 12 `[AW-1:0]` | clk_i |  |
| `rd_data_o` | out | 32 `[CW-1:0]` | clk_i | válido 2 ciclos después de rd_i |


##### Saturacion

`full_o` es PEGAJOSO: se pone en el primer bin que llega al tope y solo lo limpia el barrido de borrado. Con `cfg_keep_i = 0` la acumulacion se congela ahi mismo, en TODO el histograma y no solo en el bin saturado: un espectro con unos canales congelados y otros no ya no es un espectro, porque las areas relativas dejan de corresponder al mismo live time.  Escala, para no sobredimensionar el problema: 2^32 cuentas a 794 kcps con TODO en un solo pico son ~14 h. Es real en una corrida larga, pero esta a cuatro ordenes de magnitud de la deriva, que es lo que de verdad limita (docs/mca/limites_resolucion_y_deriva.md §7). Sirve sobre todo como disparador de rebanada y como seguro contra la saturacion silenciosa.

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `cfg_keep_i` | in | 1 | clk_i | 1 = seguir contando aunque haya full |
| `full_o` | out | 1 | clk_i | pegajoso: algun bin llego al tope |


##### Diagnóstico

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `dropped_o` | out | 32 | clk_i | eventos perdidos por colisión/barrido |
| `suppressed_o` | out | 32 | clk_i | eventos NO contados por histograma lleno |
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
El `metrics.txt` del módulo es de `mca_top`, no de `mca_hist`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
<!-- /AUTO:timing -->

<!-- A mano: qué hay en el camino crítico y qué se haría para romperlo si
     hubiera que subir la frecuencia. -->

### 1.6 Waveforms

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

Es un esquema de la SECUENCIA, no una medicion. Las dos cosas que fija: el borrado hay que ESPERARLO --`clear_busy` avisa, y los eventos que llegan mientras barre se descartan y se cuentan en `dropped`--, y los contadores se pueden leer con la medicion corriendo, que es lo que permite supervisar sin frenar. La misma secuencia en software esta en docs/API/guia_de_uso.md; si las dos se contradicen, una de las dos esta mal.

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

### 1.7 Verificación realizada

<!-- AUTO:verificacion -->
Todo corre en batch y se chequea el `RESULT: PASS` del testbench; las ondas quedan en `work/waves/<tb>.wlf`.

```bash
make -C modulos/mca/work            # los 6 testbenches
make -C modulos/mca/work cov        # + cobertura
make -C modulos/mca/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_mca_div_restore`](../../modulos/mca/sim/tb_mca_div_restore.sv) | `mca_div_restore` | 6 | 22 | vectores a mano |  |
| [`tb_mca_hist`](../../modulos/mca/sim/tb_mca_hist.sv) | `mca_hist` | 8 | 31 | vectores a mano | **sí** |
| [`tb_mca_zoom`](../../modulos/mca/sim/tb_mca_zoom.sv) | `mca_zoom` | 5 | 11 | vectores a mano |  |
| [`tb_mca_discriminator`](../../modulos/mca/sim/tb_mca_discriminator.sv) | `mca_discriminator` | 7 | 21 | vectores a mano |  |
| [`tb_mca_pulse_feature`](../../modulos/mca/sim/tb_mca_pulse_feature.sv) | `mca_pulse_feature` | 13 | 99 | vectores a mano |  |
| [`tb_mca_top`](../../modulos/mca/sim/tb_mca_top.sv) | `mca_top` | 7 | 48 | vectores a mano |  |


**232 casos con nombre** en 6 testbenches (46 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_mca_hist`](../../modulos/mca/sim/tb_mca_hist.sv): 1) Estado inicial, 2) Incremento simple y acumulación, 3) FORWARDING, 4) Saturación, 5) Barrido de borrado, 6) El puerto de LECTURA sigue vivo durante el barri, 7) Contador de descartes, 8) Los eventos en vuelo al arrancar un borrado se d.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_mca.sv`](../../modulos/mca/sim/sva/bind_mca.sv)
- [`mca_top_sva.sv`](../../modulos/mca/sim/sva/mca_top_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`mca/sim/VERIFICACION.md`](../../modulos/mca/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
