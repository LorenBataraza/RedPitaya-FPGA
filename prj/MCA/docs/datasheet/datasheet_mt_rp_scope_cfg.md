# Datasheet — `mt_rp_scope_cfg`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/mt_rp_scope_cfg.md.
     Regenerar:  make -C modulos/mt/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `mt_rp_scope_cfg` |
| Archivo | [`mt_rp_scope_cfg.sv`](../../modulos/osc/rtl/mt_rp_scope_cfg.sv) |
| Parámetros | 4 |
| Puertos | 57 (23 in / 34 out) |
| Parte | `xc7z010clg400-1` |


![Interfaz de mt_rp_scope_cfg](figuras/mt_rp_scope_cfg_interfaz.svg)
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/mt_rp_scope_cfg.md, no aca. -->

> **Este bloque ya no se instancia en ningún top.** Está en el repo como
> referencia del diseño anterior a la separación en regiones, y esta página
> existe para que el lector que lo encuentre sepa en un renglón por qué no
> tiene que tocarlo. Su reemplazo son **dos** esclavos con slot propio:
> [`osc_cfg`](datasheet_osc_cfg.md) (slot 1) y
> [`mt_cfg`](datasheet_mt_cfg.md) (slot 3).

**Qué hace.** Es el esclavo de registros del scope en su forma **monolítica**:
el `rp_scope_cfg` de Red Pitaya con los registros del multitrigger agregados
adentro —la máscara de fuentes de 32 b por canal en `0x240 + 4·ch` y la
configuración del escudo en `0x210`—, y con un
[`trigger_shield`](datasheet_trigger_shield.md) instanciado en su cuerpo. El
resto del mapa es idéntico al original.

Por qué se partió: tener la configuración del scope y la del multitrigger en el
mismo esclavo hacía que **cualquier** registro nuevo del multitrigger tuviera
que entrar en la ventana de direcciones del slot 1, que es la que `librp`
escribe con offsets fijos. Separar en slots deja crecer el multitrigger sin
tocar el mapa que el software cerrado ya usa, y el mapa histórico está
documentado en
[`register_map_mt_rp_scope_cfg.md`](../osc/register_map_mt_rp_scope_cfg.md).

**El bug que la separación arregló —y que acá sigue estando.** Las aperturas de
BRAM sacan su `sys_ack` de `bram_ack_i[i]`, y
[`rp_scope_mt_com`](datasheet_rp_scope_mt_com.md) ata
`bram_ack[2]` y `bram_ack[3]` a cero para los canales que no se construyen:
cualquier lectura en `0x4013_0000`–`0x4014_FFFF` **no hacía ack nunca** y
dejaba el CDC del slot desincronizado, o sea el slot muerto hasta el próximo
reset (ver [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) §7.1).
En `osc_cfg` el ack sale de un shift register incondicional, a los 4 ciclos y
para cualquier dirección; para los canales que sí existen el timing es
**idéntico**, porque `rp_acq_bram` ya generaba su ack como `sys_en` retrasado 4
ciclos. Se arregla el cuelgue sin cambiar una sola lectura buena.

Se conserva sin corregir a propósito: es el estado de las cosas contra el que
se compara, y tocarlo haría perder la referencia sin ganar nada — no está en
ningún bitstream.
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Default | Para qué |
|---|---|---|
| `CHN` | `0` |  |
| `N_CH` | `2` |  |
| `DW` | `14` |  |
| `RSZ` | `14` | RAM size 2^RSZ |


#### Puertos

##### ADC

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `adc_clk_i` | in | 1 | — | ADC clock |
| `adc_rstn_i` | in | 1 | — | ADC reset - active low |


##### System bus

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `sys_addr` | in | 32 | adc_clk_i |
| `sys_wdata` | in | 32 | adc_clk_i |
| `sys_wen` | in | 1 | adc_clk_i |
| `sys_ren` | in | 1 | adc_clk_i |
| `sys_rdata` | out | 32 | adc_clk_i |
| `sys_err` | out | 1 | adc_clk_i |
| `sys_ack` | out | 1 | adc_clk_i |
| `adc_state_i` | in | 32 | adc_clk_i |
| `axi_state_i` | in | 32 | adc_clk_i |
| `trg_state_i` | in | 32 | adc_clk_i |
| `adc_state_ext_i` | in | 16 | adc_clk_i |
| `axi_state_ext_i` | in | 16 | adc_clk_i |
| `trg_state_ext_i` | in | 16 | adc_clk_i |
| `adc_wp_cur_i` | in | 56 `[4*RSZ-1: 0]` | adc_clk_i |
| `adc_wp_trig_i` | in | 56 `[4*RSZ-1: 0]` | adc_clk_i |
| `adc_we_cnt_i` | in | 128 | adc_clk_i |
| `axi_wp_cur_i` | in | 128 | adc_clk_i |
| `axi_wp_trig_i` | in | 128 | adc_clk_i |
| `bram_rd_dat_i` | in | 56 `[4*DW -1: 0]` | adc_clk_i |
| `bram_ack_i` | in | 4 | adc_clk_i |
| `adc_arm_do_o` | out | 4 | adc_clk_i |
| `adc_rst_do_o` | out | 4 | adc_clk_i |
| `adc_trig_sw_o` | out | 4 | adc_clk_i |
| `adc_we_keep_o` | out | 4 | adc_clk_i |
| `trig_dis_clr_o` | out | 4 | adc_clk_i |
| `indep_mode_o` | out | 4 | adc_clk_i |
| `axi_en_pulse_o` | out | 4 | adc_clk_i |
| `new_trg_src_o` | out | 4 | adc_clk_i |
| `trg_src_o` | out | 128 | adc_clk_i |
| `set_dec1_o` | out | 4 | adc_clk_i |
| `filt_rstn_o` | out | 4 | adc_clk_i |
| `set_tresh_o` | out | 56 `[4*DW -1: 0]` | adc_clk_i |
| `set_dly_o` | out | 128 | adc_clk_i |
| `set_dec_o` | out | 68 | adc_clk_i |
| `set_hyst_o` | out | 56 `[4*DW -1: 0]` | adc_clk_i |
| `set_avg_en_o` | out | 4 | adc_clk_i |
| `set_filt_aa_o` | out | 72 | adc_clk_i |
| `set_filt_bb_o` | out | 100 | adc_clk_i |
| `set_filt_kk_o` | out | 100 | adc_clk_i |
| `set_filt_pp_o` | out | 100 | adc_clk_i |
| `set_calib_offset_o` | out | 56 `[4*DW -1: 0]` | adc_clk_i |
| `set_calib_gain_o` | out | 64 | adc_clk_i |
| `set_filt_byp_o` | out | 4 | adc_clk_i |
| `set_deb_len_o` | out | 20 | adc_clk_i |
| `set_axi_start_o` | out | 128 | adc_clk_i |
| `set_axi_stop_o` | out | 128 | adc_clk_i |
| `set_axi_dly_o` | out | 128 | adc_clk_i |
| `set_axi_en_o` | out | 4 | adc_clk_i |


##### Trigger_shield config (registro 0x210)

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `shield_src_o` | out | 4 | adc_clk_i |
| `shield_dst_o` | out | 4 | adc_clk_i |
| `shield_dur_o` | out | 16 | adc_clk_i |


##### Debug readbacks (entradas: estado interno expuesto por scope_com)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `adc_trg_dis_act_i` | in | 4 | adc_clk_i | disable flag por canal |
| `shield_cnt_i` | in | 16 | adc_clk_i | contador del shield |
| `shield_active_i` | in | 1 | adc_clk_i | shield en holdoff |
| `trig_snapshot_i` | in | 17 | adc_clk_i | sticky: qué disparó el último evento |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
`mt_rp_scope_cfg` es esclavo del bus de sistema (`sys_addr`, `sys_wdata`, `sys_wen`, `sys_ren`, `sys_rdata`, `sys_err`, `sys_ack`). El mapa completo está en:

- [`register_map_mt_rp_scope_cfg.md`](../osc/register_map_mt_rp_scope_cfg.md)
- [`register_map_osc.md`](../osc/register_map_osc.md)

Contrato del bus: [`bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md) · Mapa de slots: [`register_map_top.md`](../TOP/register_map_top.md)
<!-- /AUTO:regmap -->

### 1.4 Clock domains

<!-- AUTO:clocks -->
| Puerto | Qué es | Polaridad | Notas |
|---|---|---|---|
| `adc_clk_i` | reloj |  | ADC clock |
| `adc_rstn_i` | reset | activo-bajo | ADC reset - active low |


**Un solo dominio.** Todos los puertos de datos y de control son síncronos a `adc_clk_i`: no hay cruce de dominio dentro de este módulo.
<!-- /AUTO:clocks -->

<!-- A mano: si hay más de un reloj, cuál es el cruce, con qué se sincroniza y
     qué se asume de la relación de frecuencias. Si hay uno solo, borrar. -->

### 1.5 Frecuencia máxima de trabajo

<!-- AUTO:timing -->
El `metrics.txt` del módulo es de `osc_cfg`, no de `mt_rp_scope_cfg`: la síntesis OOC del módulo apunta a otro top, así que acá no hay números propios de este bloque.
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

**FLUJO DE UNA ADQUISICION  -  osc_cfg**

![FLUJO DE UNA ADQUISICION  -  osc_cfg](../osc/figuras/ondas/osc_cfg_adquisicion.svg)

Es un esquema de la SECUENCIA, no una medicion: no hay testbench de osc_cfg del que sacar las ondas (ver §1.7 de su datasheet, que lo marca como deuda de verificacion). Lo que la figura fija es el orden y las dependencias: la configuracion del filtro y del diezmado va ANTES del armado, porque cambiarla con el buffer llenandose mezcla muestras de dos configuraciones en la misma traza; y la lectura va despues de que el puntero deje de moverse, porque leer durante la captura devuelve una traza partida entre dos vueltas del buffer.

_Origen: esquema (sin VCD: `osc_cfg` no tiene testbench)._

---

Las figuras y sus epígrafes los escribe [`ondas_osc.py`](../osc/figuras/ondas/ondas_osc.py): los tiempos y las latencias se **miden sobre el VCD**, no se escriben a mano, así que no pueden desincronizarse del RTL. Los epígrafes completos, con los números, están en [`epigrafes.txt`](../osc/figuras/ondas/epigrafes.txt).

```bash
python3 docs/osc/figuras/ondas/ondas_osc.py    # regenerar
```
<!-- /AUTO:ondas -->

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/mt/figuras/ondas/ondas_mt.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/mt/work wave TB=<tb>   # mirar en Questa
       make -C modulos/mt/work vcd  TB=<tb>   # VCD exportable -->

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
| [`tb_osc_filter`](../../modulos/osc/sim/tb_osc_filter.sv) | `osc_filter` | 7 | 10 | RTL de referencia `osc_filter_ref.v` instanciado al lado del DUT |  |


**10 casos con nombre** en 1 testbench (7 escenas). La lista completa, caso por caso, está en el plan de verificación.

> **`mt_rp_scope_cfg` no tiene testbench propio.** Ningún `TBS` del `work/Makefile` lo instancia como DUT: lo que se verifica de este módulo es lo que arrastre el TB de otro. Es deuda de verificación, no una omisión de esta página.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_osc.sv`](../../modulos/osc/sim/sva/bind_osc.sv)
- [`osc_cfg_sva.sv`](../../modulos/osc/sim/sva/osc_cfg_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`osc/sim/VERIFICACION.md`](../../modulos/osc/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
