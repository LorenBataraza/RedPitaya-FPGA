# Datasheet — `osc_filter`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/osc_filter.md.
     Regenerar:  make -C modulos/osc/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `osc_filter` |
| Archivo | [`osc_filter.v`](../../modulos/osc/rtl/osc_filter.v) |
| Parámetros | 1 |
| Puertos | 13 (10 in / 3 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de osc_filter](figuras/osc_filter_interfaz.svg)
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/osc_filter.md, no aca. -->

**Qué hace.** Es el **ecualizador** del camino de datos del osciloscopio: una
compensación polo-cero de cuatro coeficientes (`aa`, `bb`, `kk`, `pp`), dos IIR
de primer orden más una etapa de escalado, que procesa una muestra por ciclo de
`adc_clk`. Va entre la calibración y la decimación, dentro de
[`rp_scope_mt_com`](datasheet_rp_scope_mt_com.md), y su
razón de ser es cancelar la cola del detector: poner un **cero donde el
preamplificador pone su polo**.

Lo que el filtro hace está medido, no descrito: su respuesta al impulso lo
caracteriza entero, y es lo que dibuja
[`osc_c_respuesta.png`](../osc/figuras/transacciones/osc_c_respuesta.png).

| Coeficientes | Qué sale de un impulso de 4000 cuentas |
|---|---|
| los de **reset** | una sola muestra de 3999 — ganancia 0.99975, que es el redondeo de `kk = 2^24−1` en vez de `2^24` |
| **polo-cero** | una exponencial que arranca en 3943 y tarda 99 ciclos en caer al 1 % |

La latencia medida es **8 ciclos en los dos casos**: el pipeline no depende de
los coeficientes. Con polo-cero el pico viene precedido por un precursor de
hasta 118 cuentas que arranca 4 ciclos antes —el camino directo llega antes que
las dos IIR—, así que medir la latencia por la primera muestra no nula daría 4
y sería una lectura equivocada del mismo dato.

**Tres cosas que conviene saber antes de usarlo.**

- **No está en el bitstream del MCA.** El lazo IIR no cierra timing a 125 MHz y
  es lo que fijaba el camino crítico del diseño, así que los tops del MCA y del
  anillo de eventos lo instancian con `EN_FILT = 0`, que lo saca del camino de
  datos; sólo el top de fábrica
  ([`red_pitaya_top.sv`](../../rtl/mine/tops/red_pitaya_top.sv)) lo compila
  dentro. Con `EN_FILT = 0` la señal calibrada pasa directo y **también
  desaparecen los ~5 ciclos de latencia del filtro**, pero el corrimiento es
  común al trigger y al buffer, así que siguen alineados.
- **El `tready` de la interfaz AXI-S no frena nada.** El dato llega una muestra
  por ciclo venga de donde venga, así que lo que el bloque hace tiene que
  hacerlo en un ciclo. El puerto existe; el contrato de flujo, no.
- **El bypass no se hace acá.** `cfg_bypass` está atado a `1'b0` en la
  instancia; quien elige entre señal filtrada y señal cruda es `set_filt_byp`,
  un mux de afuera.

El bloque se verifica por **equivalencia secuencial** contra una copia
congelada del filtro anterior al rediseño (`osc_filter_ref.v`), instanciada al
lado del DUT y alimentada con el mismo flujo: no se comparan métricas sino las
dos salidas muestra por muestra, y coinciden en 460 de 460 ciclos dibujados
([`osc_b_cadena.png`](../osc/figuras/transacciones/osc_b_cadena.png)). Eso vale
**para los coeficientes de esas escenas más los 12 juegos aleatorios del
testbench**, no para todo el espacio; cubrirlo entero con `aa/bb/kk/pp`
simbólicos es uno de los candidatos que discute
[`verificacion_formal.md`](../verificacion_formal.md).

> **Dos deudas documentadas.** El archivo es Verilog heredado y **no tiene
> cabecera**: todo lo de arriba está reconstruido del código y de la
> simulación, no copiado de un comentario. Y la escena 5 de `tb_osc_filter`,
> que se llama «kk extremos: saturación en la etapa de escalado», escribe
> `25'h1FFFFFF` sobre un `wire signed [24:0]`: ese valor es **−1**, no un
> máximo. La ganancia queda en ≈−2⁻²⁴, la salida colapsa a 0 y las ramas de
> saturación nunca se ejercitan. La escena pasa; lo que dice probar, no.
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Default |
|---|---|
| `DW` | `16` |


#### Puertos

##### Reloj y reset

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `clk` | in | 1 | — |
| `rst_n` | in | 1 | — |


##### Slave AXI-S

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `s_axis_tdata` | in | 16 `[DW-1:0]` | clk |
| `s_axis_tvalid` | in | 1 | clk |
| `s_axis_tready` | out | 1 | clk |


##### Master AXI-

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `m_axis_tdata` | out | 16 `[DW-1:0]` | clk |
| `m_axis_tvalid` | out | 1 | clk |
| `m_axis_tready` | in | 1 | clk |


##### Confi

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `cfg_bypass` | in | 1 | clk |
| `cfg_coeff_aa` | in | 18 | clk |
| `cfg_coeff_bb` | in | 25 | clk |
| `cfg_coeff_kk` | in | 25 | clk |
| `cfg_coeff_pp` | in | 25 | clk |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
Mapas de registros de la región:

- [`register_map_mt_rp_scope_cfg.md`](../osc/register_map_mt_rp_scope_cfg.md)
- [`register_map_osc.md`](../osc/register_map_osc.md)

Contrato del bus: [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) · Mapa de slots: [`register_map_top.md`](../TOP/register_map_top.md)
<!-- /AUTO:regmap -->

### 1.4 Clock domains

<!-- AUTO:clocks -->
| Puerto | Qué es | Polaridad |
|---|---|---|
| `clk` | reloj |  |
| `rst_n` | reset | activo-alto |


**Un solo dominio.** Todos los puertos de datos y de control son síncronos a `clk`: no hay cruce de dominio dentro de este módulo.
<!-- /AUTO:clocks -->

<!-- A mano: si hay más de un reloj, cuál es el cruce, con qué se sincroniza y
     qué se asume de la relación de frecuencias. Si hay uno solo, borrar. -->

### 1.5 Frecuencia máxima de trabajo

<!-- AUTO:timing -->
El `metrics.txt` del módulo es de `osc_cfg`, no de `osc_filter`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
<!-- /AUTO:timing -->

<!-- A mano: qué hay en el camino crítico y qué se haría para romperlo si
     hubiera que subir la frecuencia. -->

### 1.6 Transacciones

<!-- AUTO:transacciones -->
**LO QUE ENTRA: UN IMPULSO**

![LO QUE ENTRA: UN IMPULSO](../osc/figuras/transacciones/osc_a_impulso.png)

Que entra. Una muestra de 4000 cuentas y el resto cero. Para un filtro lineal invariante eso no es un caso mas: la respuesta al impulso LO DESCRIBE ENTERO, asi que las dos curvas del panel (c) son la caracterizacion completa del bloque con cada juego de coeficientes. El flujo es de una muestra por ciclo de adc_clk (8 ns) y no hay handshake que lo pueda frenar: el `tready` existe en los puertos pero el dato llega igual, asi que lo que el bloque hace tiene que hacerlo en un ciclo.

_Origen: `tb_osc_filter`, VCD completo._

**EL BLOQUE, Y EL MODELO QUE CORRE AL LADO**

![EL BLOQUE, Y EL MODELO QUE CORRE AL LADO](../osc/figuras/transacciones/osc_b_cadena.png)

Que viaja. El bloque es una compensacion polo-cero, dos IIR de primer orden y una etapa de escalado, con cuatro coeficientes configurables. Lo que esta figura agrega a un diagrama de bloques es el segundo camino: el testbench instancia AL LADO del DUT una copia congelada del filtro anterior al rediseno (`osc_filter_ref.v`) y le da el mismo flujo. No se comparan resumenes ni metricas: se comparan las dos salidas muestra por muestra.

_Origen: `osc_filter.v` y `sim/osc_filter_ref.v`._

**LO QUE SALE: EL MISMO IMPULSO, DOS FILTROS**

![LO QUE SALE: EL MISMO IMPULSO, DOS FILTROS](../osc/figuras/transacciones/osc_c_respuesta.png)

Que sale, y es donde esta todo. Con los coeficientes de RESET la cadena queda transparente: el impulso de 4000 sale como una sola muestra de 3999 --o sea ganancia 0.99975, el error de redondeo de kk = 2^24-1 en vez de 2^24-- 8 ciclos despues. Con la compensacion POLO-CERO el mismo impulso sale como una exponencial que arranca en 3943 y tarda 99 ciclos en caer al 1 %: el filtro no recorta la cola, la FABRICA, porque esta pensado para cancelar la del detector --un cero donde el preamplificador pone su polo--. La latencia es la misma en los dos casos, 8 ciclos, porque el pipeline no depende de los coeficientes: lo MEDIDO es 8 y 8. Lo que si cambia es que con polo-cero el pico viene precedido por un precursor de hasta 118 cuentas que arranca 4 ciclos antes --el camino directo, que llega antes que las dos IIR--; es chico pero existe, y medir la latencia por la primera muestra no nula en vez de por el pico lo contaria como si la respuesta empezara ahi. Los circulos son `ref_out`: la salida del modelo congelado coincide con la del DUT en 460 de los 460 ciclos dibujados, o sea TODOS. Esa coincidencia es el contenido de la figura.

_Origen: `tb_osc_filter`, escenas de coeficientes de reset y polo-cero._

**LA TRANSACCION COMPLETA**

![LA TRANSACCION COMPLETA](../osc/figuras/transacciones/osc_transaccion.png)

Las tres preguntas en una imagen: que entra, que viaja y que sale.

_Origen: las tres anteriores, en una figura._

---

Las figuras **recalculan cada número al dibujar** en vez de tomarlo escrito. Las genera [`transacciones_osc.py`](../osc/figuras/transacciones/transacciones_osc.py); de dónde sale el dato de cada una está en la columna «Datos» de [`README.md`](../osc/figuras/transacciones/README.md); los epígrafes completos, en [`epigrafes.txt`](../osc/figuras/transacciones/epigrafes.txt).
<!-- /AUTO:transacciones -->

### 1.7 Waveforms

<!-- AUTO:ondas -->
**RESPUESTA AL IMPULSO  -  coeficientes de reset (la cadena es transparente), osc_filter vs osc_filter_ref**

![RESPUESTA AL IMPULSO  -  coeficientes de reset (la cadena es transparente), osc_filter vs osc_filter_ref](../osc/figuras/ondas/osc_filter_impulso.svg)

Los coeficientes de reset son los que usa el driver hoy, asi que es la configuracion que mas importa que no haya cambiado. Un impulso entra y sale UN solo impulso, del mismo tamano: con aa=bb=pp=0 y kk en 2^24-1 la cadena es transparente y lo unico que agrega es latencia, que es el numero que da esta figura. Las dos salidas se dibujan superpuestas a proposito: tb_osc_filter es un test de EQUIVALENCIA contra el filtro original del repo, asi que las filas de osc_filter y osc_filter_ref tienen que ser la misma onda columna por columna. Si en alguna se separan, el testbench esta fallando y la figura lo muestra.

_Origen: `tb_osc_filter`, caso de coeficientes de reset._

**RESPUESTA AL IMPULSO  -  compensacion polo-cero (aa=25000): la cola que compensa el preamplificador**

![RESPUESTA AL IMPULSO  -  compensacion polo-cero (aa=25000): la cola que compensa el preamplificador](../osc/figuras/ondas/osc_filter_polocero.svg)

La misma entrada que la figura anterior --un impulso-- con el lazo recursivo activo. Ahora la salida no es un impulso sino un pico seguido de una COLA que decae: eso es la compensacion polo-cero, que cancela la cola del preamplificador para que el pulso vuelva a la linea de base antes del siguiente. Es la parte del filtro que se rediseno, y la figura muestra que la cola entera --mas de veinte muestras-- coincide con la del filtro original muestra por muestra. Se dibuja el impulso y no un escalon porque con aa=25000 la constante de tiempo es de cientos de ciclos: un escalon no se asienta dentro de una ventana que se pueda mirar.

_Origen: `tb_osc_filter`, caso de compensacion polo-cero._

---

Las figuras y sus epígrafes los escribe [`ondas_osc.py`](../osc/figuras/ondas/ondas_osc.py): los tiempos y las latencias se **miden sobre el VCD**, no se escriben a mano, así que no pueden desincronizarse del RTL. Los epígrafes completos, con los números, están en [`epigrafes.txt`](../osc/figuras/ondas/epigrafes.txt).

```bash
python3 docs/osc/figuras/ondas/ondas_osc.py    # regenerar
```
<!-- /AUTO:ondas -->

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/osc/figuras/ondas/ondas_osc.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/osc/work wave TB=<tb>   # mirar en Questa
       make -C modulos/osc/work vcd  TB=<tb>   # VCD exportable -->

### 1.8 Verificación realizada

<!-- AUTO:verificacion -->
Todo corre en batch y se chequea el `RESULT: PASS` del testbench; las ondas quedan en `work/waves/<tb>.wlf`.

```bash
make -C modulos/osc/work            # el 1 testbench
make -C modulos/osc/work cov        # + cobertura
make -C modulos/osc/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_osc_filter`](../../modulos/osc/sim/tb_osc_filter.sv) | `osc_filter` | 7 | 10 | RTL de referencia `osc_filter_ref.v` instanciado al lado del DUT | **sí** |


**10 casos con nombre** en 1 testbench (7 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_osc_filter`](../../modulos/osc/sim/tb_osc_filter.sv): 1) Coeficientes de RESET, 2) Compensación polo-cero tipica (aa != 0, 3) aa grande positivo y negativo, 4) pp extremos, 5) kk extremos, 6) Todo al maximo a la vez, 7) Barrido aleatorio de coeficientes.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_osc.sv`](../../modulos/osc/sim/sva/bind_osc.sv)
- [`osc_cfg_sva.sv`](../../modulos/osc/sim/sva/osc_cfg_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`osc/sim/VERIFICACION.md`](../../modulos/osc/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
