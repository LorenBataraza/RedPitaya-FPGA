# Datasheet — `multitrigger_event_logic`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     Regenerar:  make -C modulos/multitrigger/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `multitrigger_event_logic` |
| Archivo | [`multitrigger_event_logic.v`](../../modulos/multitrigger/rtl/multitrigger_event_logic.v) |
| Parámetros | 7 |
| Puertos | 31 (21 in / 10 out) |


![Interfaz de multitrigger_event_logic](figuras/multitrigger_event_logic_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`multitrigger_event_logic.v`](../../modulos/multitrigger/rtl/multitrigger_event_logic.v)):

> Este módulo tiene la tarea de dar la salida de eventos.
> Une el trigger_shield (que afecta el disable de los multitrigger_trig_src)
> con N_CH instancias de multitrigger_trig_src y sus conexiones de cadena.
>
> Trabaja con N_CH canales: instancia un multitrigger_trig_src por canal y
> produce un evento conjunto = OR de todas las salidas de trigger.
<!-- /AUTO:resumen -->

<!-- A mano: qué problema resuelve el bloque, cómo encaja en la cadena y las
     dos o tres decisiones de diseño que explican por qué está hecho así. -->

**Qué hace.** TODO

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `N_CH` | `integer` | `2` | Number of Channels |
| `DW` | `integer` | `14` | Data Width |
| `SRC_W` | `integer` | `32` | Ancho de la máscara de fuentes |
| `SHIELD_N` | `integer` | `4` | Canales del trigger_shield |
| `DURATION_W` | `integer` | `16` | Ancho del contador de holdoff |
| `SHIELD_SRC` | `integer` | `SHIELD_N + 3` = `7` |  |
| `SHIELD_DST` | `integer` | `SHIELD_N + 1` = `5` |  |


#### Puertos

##### ADC

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `adc_clk_i` | in | 1 | — | ADC clock |
| `adc_rstn_i` | in | 1 | — | ADC reset - active low |


##### Control / config (de rp_scope_cfg vía scope_com)

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `adc_rst_do_i` | in | 4 | adc_clk_i |  |
| `adc_dly_do_i` | in | 1 | adc_clk_i |  |
| `sw_trig_dis_clr_i` | in | 4 | adc_clk_i | clear de SW (reg 0x94) |
| `adc_we_keep_i` | in | 4 | adc_clk_i | modo continuo por canal (0x00 bit3) |
| `set_trg_src_i` | in | 64 `[N_CH*SRC_W-1: 0]` | adc_clk_i | máscara de fuentes por canal |
| `set_trg_new_i` | in | 4 | adc_clk_i |  |
| `dly_valp_i` | in | 4 | adc_clk_i |  |


##### Fuentes de trigger

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `adc_trig_sw_i` | in | 4 | adc_clk_i |  |
| `adc_trig_p_i` | in | 4 | adc_clk_i |  |
| `adc_trig_n_i` | in | 4 | adc_clk_i |  |
| `ext_trig_p_i` | in | 1 | adc_clk_i |  |
| `ext_trig_n_i` | in | 1 | adc_clk_i |  |
| `asg_trig_p_i` | in | 1 | adc_clk_i |  |
| `asg_trig_n_i` | in | 1 | adc_clk_i |  |
| `ext_lvl_i` | in | 1 | adc_clk_i | NIVEL externo sincronizado (veto) |
| `trig_ch_i` | in | 4 | adc_clk_i | cadena desde el otro scope |


##### Shield config - Control Signals

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `shield_src_i` | in | 7 `[SHIELD_SRC-1: 0]` | adc_clk_i |
| `shield_dst_i` | in | 5 `[SHIELD_DST-1: 0]` | adc_clk_i |
| `shield_dur_i` | in | 16 `[DURATION_W-1: 0]` | adc_clk_i |


##### Salidas

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `trig_ch_o` | out | 4 | adc_clk_i | cadena hacia el otro scope |
| `trg_state_o` | out | 64 `[N_CH*SRC_W-1: 0]` | adc_clk_i | máscara activa por canal (32 b/ch) |
| `adc_trg_dis_o` | out | 4 | adc_clk_i | bit de disable por canal (padded) |
| `daisy_trig_o` | out | 1 | adc_clk_i |  |
| `event_arm_o` | out | 1 | adc_clk_i |  |
| `trigger_event_o` | out | 1 | adc_clk_i | evento conjunto -> bram_sm/axi_sm |
| `mca_veto_o` | out | 1 | adc_clk_i | nivel: el MCA no abre pulsos |


##### State

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `shield_cnt_o` | out | 16 `[DURATION_W-1: 0]` | adc_clk_i | contador del shield |
| `shield_active_o` | out | 1 | adc_clk_i | shield en holdoff |
| `trig_snapshot_o` | out | 17 | adc_clk_i | sticky: qué disparó el último evento |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
Mapas de registros de la región:

- [`register_map_multitrigger.md`](../multitrigger/register_map_multitrigger.md)
- [`register_map_multitrigger_rp_scope_cfg.md`](../multitrigger/register_map_multitrigger_rp_scope_cfg.md)

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
Sin datos de síntesis todavía. Correr:

```bash
make -C modulos/multitrigger/work syn
make -C modulos/multitrigger/work sweep-all
```

y volver a generar esta página.
<!-- /AUTO:timing -->

<!-- A mano: qué hay en el camino crítico y qué se haría para romperlo si
     hubiera que subir la frecuencia. -->

### 1.6 Waveforms

<!-- AUTO:ondas -->
**LAS TRES FORMAS DEL VETO AL MCA  -  nivel / nivel con cola / ventana por flanco**

![LAS TRES FORMAS DEL VETO AL MCA  -  nivel / nivel con cola / ventana por flanco](../multitrigger/figuras/ondas/mt_veto_tres_formas.svg)

El mismo bloque da tres vetos distintos segun como se lo configure, y la diferencia no esta en el RTL sino en que fuente se elige y que duracion se escribe. Con una fuente de NIVEL y dur=0 el veto es la linea con un ciclo de latencia: dura lo que dure la linea. Con la misma fuente y dur=8 el veto se extiende ocho ciclos despues de que la linea baje, que es lo que hace falta cuando el estimulo deja cola. Con una fuente de FLANCO y dur=12 el veto es una ventana fija de doce ciclos, sin importar cuanto dure el pulso. Los tres tramos vienen de escenas distintas del testbench y el hueco entre ellos dice que se salteo tiempo: no es una secuencia.

_Origen: `tb_trigger_shield`, escenas 4, 5 y 6._

**HOLDOFF Y RE-ARM  -  el escudo cuenta y al expirar limpia el canal de destino**

![HOLDOFF Y RE-ARM  -  el escudo cuenta y al expirar limpia el canal de destino](../multitrigger/figuras/ondas/mt_holdoff_rearm.svg)

Lo que el escudo hace de verdad: cuando el canal fuente dispara, arranca un contador y mantiene `active` mientras cuenta; al expirar emite UN pulso de clear en el canal de destino, que es lo que lo vuelve a armar. Importa que el clear salga al EXPIRAR y no al disparar: si saliera al disparar, el canal de destino se re-armaria en medio del evento que el escudo esta tratando de protegerlo.

_Origen: `tb_trigger_shield`, escena 2._

**DISPARO SINGLE-SHOT  -  el flanco dispara, engancha el disable y la mascara se auto-limpia**

![DISPARO SINGLE-SHOT  -  el flanco dispara, engancha el disable y la mascara se auto-limpia](../multitrigger/figuras/ondas/mt_trig_src_enganche.svg)

El flanco de la fuente habilitada dispara `adc_trig` y en el mismo movimiento engancha `adc_trg_dis`, que es lo que impide que el siguiente flanco vuelva a disparar. En modo single-shot la mascara se auto-limpia, asi que para volver a disparar hace falta reescribirla; en modo continuo la mascara persiste y basta con limpiar el disable. Esa es la unica diferencia entre los dos modos.

_Origen: `tb_multitrigger_trig_src`, escena 1._

**FLUJO DE UTILIZACION  -  multitrigger_cfg**

![FLUJO DE UTILIZACION  -  multitrigger_cfg](../multitrigger/figuras/ondas/mt_flujo.svg)

Es un esquema de la SECUENCIA, no una medicion. Lo que fija es el orden y una dependencia que no se ve en el mapa de registros: el disable queda ENGANCHADO despues del disparo, asi que sin escribir TRIG_DIS_CLR no hay segundo disparo. Un programa que configure, dispare y se quede esperando el proximo evento sin limpiar el disable espera para siempre.

_Origen: esquema (sin VCD)._

---

Las figuras y sus epígrafes los escribe [`ondas_multitrigger.py`](../multitrigger/figuras/ondas/ondas_multitrigger.py): los tiempos y las latencias se **miden sobre el VCD**, no se escriben a mano, así que no pueden desincronizarse del RTL. Los epígrafes completos, con los números, están en [`epigrafes.txt`](../multitrigger/figuras/ondas/epigrafes.txt).

```bash
python3 docs/multitrigger/figuras/ondas/ondas_multitrigger.py    # regenerar
```
<!-- /AUTO:ondas -->

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/multitrigger/figuras/ondas/ondas_multitrigger.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/multitrigger/work wave TB=<tb>   # mirar en Questa
       make -C modulos/multitrigger/work vcd  TB=<tb>   # VCD exportable -->

### 1.7 Verificación realizada

<!-- AUTO:verificacion -->
Todo corre en batch y se chequea el `RESULT: PASS` del testbench; las ondas quedan en `work/waves/<tb>.wlf`.

```bash
make -C modulos/multitrigger/work            # los 4 testbenches
make -C modulos/multitrigger/work cov        # + cobertura
make -C modulos/multitrigger/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_multitrigger_cfg`](../../modulos/multitrigger/sim/tb_multitrigger_cfg.sv) | `multitrigger_cfg` | 11 | 30 | vectores a mano |  |
| [`tb_multitrigger_trig_src`](../../modulos/multitrigger/sim/tb_multitrigger_trig_src.sv) | `multitrigger_trig_src` | 5 | 8 | vectores a mano |  |
| [`tb_multitrigger_event_logic`](../../modulos/multitrigger/sim/tb_multitrigger_event_logic.sv) | `multitrigger_event_logic` | 3 | 5 | vectores a mano | **sí** |
| [`tb_trigger_shield`](../../modulos/multitrigger/sim/tb_trigger_shield.sv) | `trigger_shield` | 8 | 19 | vectores a mano |  |


**62 casos con nombre** en 4 testbenches (27 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_multitrigger_event_logic`](../../modulos/multitrigger/sim/tb_multitrigger_event_logic.sv): 1) flanco ch0 -> evento conjunto + snapshot bit1 (a, 2) snapshot se resetea con sw_trig_dis_clr, 3) flanco en ch1 (adc_trig_p bit1) tambien dispara .

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_multitrigger.sv`](../../modulos/multitrigger/sim/sva/bind_multitrigger.sv)
- [`multitrigger_cfg_sva.sv`](../../modulos/multitrigger/sim/sva/multitrigger_cfg_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`multitrigger/sim/VERIFICACION.md`](../../modulos/multitrigger/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
