# Datasheet — `trigger_shield`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     Regenerar:  make -C modulos/multitrigger/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `trigger_shield` |
| Archivo | [`trigger_shield.sv`](../../modulos/multitrigger/rtl/trigger_shield.sv) |
| Parámetros | 4 |
| Puertos | 11 (7 in / 4 out) |


![Interfaz de trigger_shield](figuras/trigger_shield_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`trigger_shield.sv`](../../modulos/multitrigger/rtl/trigger_shield.sv)):

> Módulo que toma configuración como parámetros.
> La salida se la conecta al trig_dis_clr_i del multitrigger_trig_src.
>
>   Cantidad de canales:  parameter integer N          = 4
>   Duración del holdoff: parameter integer DURATION_W = 16
>   Shield src  vector de N_SRC (qué fuentes actúan de disparo del escudo)
>   Shield dest vector de N_DST (qué destinos quedan escudados)
>
> Holdoff src->dest: cuando una fuente "src" dispara, los canales "dest" quedan
> deshabilitados durante DURATION ciclos de ADC; al expirar se emite un pulso
> de trig_dis_clr que los re-arma. Los canales no escudados siguen de forma
> transparente al clear de SW.
>
> FUENTES Y DESTINOS NO SON LO MISMO. Los N primeros bits de cada vector son los
> canales del scope, como siempre. Por encima:
>
>   src[N+0]  ext_p    flanco de subida de la entrada externa (DIO0_P)
>   src[N+1]  ext_n    flanco de bajada
>   src[N+2]  ext_lvl  NIVEL de la entrada externa, sincronizado
>   dst[N]    mca      el analizador multicanal, como VETO
>
> Con `ext_lvl` como fuente el escudo "dispara" cada ciclo que la línea está
> alta, y como cada disparo recarga el contador, el veto queda activo mientras
> dura la línea y DURATION ciclos más: un veto de nivel con cola programable.
> Con `ext_p` da una ventana de DURATION ciclos tras el flanco. Las dos cosas
> salen del mismo contador; lo que cambia es qué bit de src se habilita.
>
> El veto al MCA es un NIVEL, no un pulso de re-arm: vale mientras alguna
> fuente dispara o el holdoff está corriendo. Va registrado porque termina en
> la lógica de apertura de pulso del MCA y no hace falta que sea inmediato.
<!-- /AUTO:resumen -->

<!-- A mano: qué problema resuelve el bloque, cómo encaja en la cadena y las
     dos o tres decisiones de diseño que explican por qué está hecho así. -->

**Qué hace.** TODO

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default | Para qué |
|---|---|---|---|
| `N` | `integer` | `4` | canales del scope |
| `DURATION_W` | `integer` | `16` | ancho del contador de holdoff |
| `N_SRC` | `integer` | `N + 3` = `7` | canales + {ext_p, ext_n, ext_lvl} |
| `N_DST` | `integer` | `N + 1` = `5` | canales + {mca} |


#### Puertos

##### Señales

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `clk_i` | in | 1 | — |  |
| `rstn_i` | in | 1 | — | reset síncrono activo-bajo |
| `trig_event_i` | in | 7 `[N_SRC-1:0]` | clk_i | disparo por fuente |
| `shield_src_i` | in | 7 `[N_SRC-1:0]` | clk_i | fuentes del escudo |
| `shield_dst_i` | in | 5 `[N_DST-1:0]` | clk_i | destinos escudados |
| `shield_dur_i` | in | 16 `[DURATION_W-1:0]` | clk_i | duración del holdoff (ciclos ADC) |
| `sw_trig_dis_clr_i` | in | 4 `[N-1:0]` | clk_i | clear de SW (rp_scope_cfg, reg 0x94) |
| `trig_dis_clr_o` | out | 4 `[N-1:0]` | clk_i | a multitrigger_trig_src.trig_dis_clr_i |
| `mca_veto_o` | out | 1 | clk_i | nivel: el MCA no abre pulsos |


##### Estado expuesto para debug

| Puerto | Dir | Bits | Dominio | Descripción |
|---|---|---|---|---|
| `cnt_o` | out | 16 `[DURATION_W-1:0]` | clk_i | contador holdoff actual |
| `active_o` | out | 1 | clk_i | holdoff en progreso |
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
| `clk_i` | reloj |  |  |
| `rstn_i` | reset | activo-bajo | reset síncrono activo-bajo |


**Un solo dominio.** Todos los puertos de datos y de control son síncronos a `clk_i`: no hay cruce de dominio dentro de este módulo.
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
| [`tb_multitrigger_event_logic`](../../modulos/multitrigger/sim/tb_multitrigger_event_logic.sv) | `multitrigger_event_logic` | 3 | 5 | vectores a mano |  |
| [`tb_trigger_shield`](../../modulos/multitrigger/sim/tb_trigger_shield.sv) | `trigger_shield` | 8 | 19 | vectores a mano | **sí** |


**62 casos con nombre** en 4 testbenches (27 escenas). La lista completa, caso por caso, está en el plan de verificación.

Las escenas de [`tb_trigger_shield`](../../modulos/multitrigger/sim/tb_trigger_shield.sv): 1) dur=0, 2) dur=K, 3) canal no escudado, 4) VETO de nivel, 5) VETO de nivel con cola, 6) VETO de ventana, 7) sin dst=mca no hay veto, aunque el escudo corra, 8) los canales del scope como fuente tambien vetan .

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_multitrigger.sv`](../../modulos/multitrigger/sim/sva/bind_multitrigger.sv)
- [`multitrigger_cfg_sva.sv`](../../modulos/multitrigger/sim/sva/multitrigger_cfg_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`multitrigger/sim/VERIFICACION.md`](../../modulos/multitrigger/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
