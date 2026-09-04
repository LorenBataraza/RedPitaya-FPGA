# Mapa de registros — región de OSC

**Base:** `0x4010_0000` (slot 1 del bus de sistema) · **Tamaño de mmap:** `0x50000`
**RTL:** [`osc_cfg.sv`](../../rtl/mine/osc/osc_cfg.sv)
**Datapath:** [`rp_scope_multitrigger_com.sv`](../../rtl/mine/multitrigger/rp_scope_multitrigger_com.sv)

Sale de `multitrigger_rp_scope_cfg`, quitándole los registros del multitrigger
—que se mudaron al [slot 3](../multitrigger/register_map_multitrigger.md)— y
reorganizando el mapa. El mapa original se conserva como referencia histórica en
[`register_map_multitrigger_rp_scope_cfg.md`](../multitrigger/register_map_multitrigger_rp_scope_cfg.md).

Contrato del bus: [`../TOP/bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md).
Mapa de slots: [`../TOP/register_map_top.md`](../TOP/register_map_top.md).

---

## Los dos mapas

Este esclavo decodifica **dos rangos de direcciones sobre el mismo banco de
registros físicos**. No hay estado duplicado: un solo flop por registro, dos
decodificadores para alcanzarlo. Escribir por un mapa y leer por el otro
devuelve el mismo valor, así que no se pueden desincronizar.

```
0x00000 - 0x00FFF   mapa LEGACY    offsets históricos de Red Pitaya
0x01000 - 0x01FFF   mapa CANÓNICO  stride uniforme por canal
0x10000 - 0x4FFFF   aperturas BRAM (comunes a los dos)
```

### Por qué existe el mapa legacy

`librp` es una librería C **cerrada** que lee y escribe offsets fijos en
`0x4010_0000`. Hay **111 llamadas** a la API `rp` en 14 archivos del software
del proyecto (`run_acquire`, `e2e_espectro`, `mca/sources`, `guardado_mariana`,
los benches), usando `rp_AcqStart`, `rp_AcqSetTriggerLevel`, `rp_AcqGetDataV` y
17 funciones más. Mover los registros sin dejar los offsets viejos rompería todo
eso de golpe, **sin posibilidad de parche del lado Python**. Con la ventana, la
migración del software es incremental.

**Cómo se saca:** el parámetro `EN_LEGACY_MAP` la compila fuera. Cuando el
software esté migrado se pone en `0` y las ramas legacy desaparecen en síntesis.
Es el único lugar que hay que tocar.

**Cuánto cuesta:** un segundo juego de comparadores de dirección, del orden de
100-200 LUTs. Cero impacto en timing: el decode no está en el camino de datos.

> **Divergencia preexistente en `0x004`.** Este diseño ya no es el Red Pitaya de
> fábrica: el RTL sólo honra el valor `1` (SW trigger). Un
> `rp_AcqSetTriggerSrc` con una fuente de flanco escribe `2`, `3`… y se ignora,
> porque esas fuentes pasaron a la OR-mask del multitrigger. La ventana legacy
> preserva **el comportamiento actual**, no el original de Red Pitaya.

---

## Mapa canónico

### Globales — base `0x01000`

| Offset | R/W | Campo | Descripción |
|---|---|---|---|
| `+0x000` | R | `MAGIC` | `0x4F534331` (`"OSC1"`) |
| `+0x004` | R | `CAPS` | `{RSZ[21:16], DW[13:8], N_CH[3:0]}` |
| `+0x008` | W | `CMD_ARM` | bit por canal |
| `+0x00C` | W | `CMD_RST` | bit por canal |
| `+0x010` | RW | `CFG_WE_KEEP` | bit por canal — el ARM sigue activo tras el trigger |
| `+0x014` | RW | `CFG_INDEP` | bit por canal — modo de adquisición independiente |
| `+0x018` | R | `ADC_STATE` | |
| `+0x01C` | RW | `DEB_LEN` | largo del debouncer del trigger externo (reset 62500) |
| `+0x020` | RW | `FILT_BYP` | bypass del ecualizador, bit por canal |
| `+0x024` | RW | `AVG_EN` | averaging, bit por canal |

### Por canal — base `0x01100` + `0x40`·ch

| Offset | R/W | Campo | | Offset | R/W | Campo |
|---|---|---|---|---|---|---|
| `+0x00` | RW | `THRESH` (signed) | | `+0x1C` | RW | `CALIB_OFFSET` |
| `+0x04` | RW | `HYST` | | `+0x20` | RW | `CALIB_GAIN` (reset `0x8000` = ×1) |
| `+0x08` | RW | `DLY` (post-trigger) | | `+0x24` | RW | `FILT_AA` |
| `+0x0C` | RW | `DEC` (decimación) | | `+0x28` | RW | `FILT_BB` |
| `+0x10` | R | `WP_CUR` | | `+0x2C` | RW | `FILT_KK` |
| `+0x14` | R | `WP_TRIG` | | `+0x30` | RW | `FILT_PP` |
| `+0x18` | R | `WE_CNT` | | | | |

### AXI por canal — base `0x01200` + `0x20`·ch

| Offset | R/W | Campo |
|---|---|---|
| `+0x00` / `+0x04` / `+0x08` | RW | `AXI_START` / `AXI_STOP` / `AXI_DLY` |
| `+0x0C` | RW | `AXI_EN` — el write con bit0=1 emite `axi_en_pulse` |
| `+0x10` / `+0x14` | R | `AXI_WP_TRIG` / `AXI_WP_CUR` |
| `+0x18` | R | `AXI_STATE` |

El mapa canónico cubre **ch0..ch3** aunque `N_CH = 2`: es un superset del
legacy, que sólo decodificaba dos canales para la mayoría de los registros.

### Aperturas BRAM

| Offset | Contenido |
|---|---|
| `0x10000` | buffer del canal 1 |
| `0x20000` | canal 2 |
| `0x30000` | canal 3 (no construido con `N_CH=2`) |
| `0x40000` | canal 4 (idem) |

Comunes a los dos mapas. Las muestras son de `DW=14` bits **con signo**: hay que
extender el signo al leerlas, a diferencia de los histogramas del MCA.

---

## Mapa legacy

Idéntico al de Red Pitaya y al del módulo original. Los offsets siguen siendo
válidos y `librp` los usa tal cual.

| Offset | Campo | | Offset | Campo |
|---|---|---|---|---|
| `0x000` | comandos (byte por canal) | | `0x050`–`0x05C` | AXI ch1 |
| `0x004` | SW trigger / `trg_state` | | `0x060` / `0x064` | AXI wp ch1 |
| `0x008` / `0x00C` | `set_tresh` ch1 / ch2 | | `0x070`–`0x07C` | AXI ch2 |
| `0x010` / `0x014` | `set_dly` / `set_dec` ch1 | | `0x080` / `0x084` | AXI wp ch2 |
| `0x018` / `0x01C` | `wp_cur` / `wp_trig` ch1 | | `0x088` | `axi_state` |
| `0x020` / `0x024` | `set_hyst` ch1 / ch2 | | `0x090` | `set_deb_len` |
| `0x028` | `set_avg_en` | | `0x094` | `trig_dis_clr` (sin readback) |
| `0x02C` | `we_cnt` ch1 | | `0x098` | `set_filt_byp` |
| `0x030`–`0x03C` | filtros ch1 | | `0x110`–`0x12C` | ch2: dly, dec, wp, we_cnt |
| `0x040`–`0x04C` | filtros ch2 | | `0x200`–`0x20C` | calibración ch1 / ch2 |

El detalle bit a bit está en el
[mapa histórico](../multitrigger/register_map_multitrigger_rp_scope_cfg.md).

### El puente legacy hacia el slot 3

Dos offsets legacy pertenecen a lógica que se mudó al multitrigger, y `librp`
los usa. `osc_cfg` los sigue decodificando y manda el pulso **ya decodificado
por canal** a `multitrigger_cfg`, donde se OR-ea con el registro propio:

| Offset legacy | Puerto | Va a |
|---|---|---|
| `0x004` (SW trigger) | `legacy_trig_sw_o` | `0x4030_0020` |
| `0x094` (`trig_dis_clr`) | `legacy_trig_dis_clr_o` | `0x4030_0024` |

El resto de los registros del multitrigger (`0x210`, `0x214`, `0x218`, `0x21C`,
`0x240`–`0x24C`) **no** tiene puente: `librp` no los conoce, son propios del
proyecto. Ahí sólo hay que reapuntar el driver de Python al slot 3.

---

## Un bug arreglado de paso

El módulo original sacaba el `ack` de las aperturas BRAM de `bram_ack_i[i]`, y
`rp_scope_multitrigger_com` ata `bram_ack[2]`/`[3]` a cero para los canales no
construidos: **cualquier lectura en `0x4013_0000`–`0x4014_FFFF` no hacía `ack`
nunca** y dejaba el CDC del slot desincronizado
([§7.1](../TOP/bus_sistema_redpitaya.md)).

Ahora el `ack` sale de un shift register incondicional, a los 4 ciclos y para
cualquier dirección. Para los canales que sí existen **el timing es idéntico**:
`rp_acq_bram` genera `bram_ack_o` = `sys_en` retrasado 4 ciclos
(`adc_rval <= {adc_rval[2:0], bram_ack_i}`), que es exactamente `en_sr[3]`. O
sea que se arregla el cuelgue sin cambiar en nada las lecturas buenas.

`tb_osc_cfg` instancia el módulo viejo y el nuevo y barre las mismas
direcciones: **cero** timeouts en el nuevo, **cuatro** en el viejo (`0x30000`,
`0x40000`, `0x3FFFC`, `0x4FFFC`).

---

## Testbenches

| Testbench | Qué verifica |
|---|---|
| [`tb_osc_cfg`](../../sim/tb_osc_cfg.sv) | **diferencial contra el módulo viejo**: mismo estímulo por los offsets legacy, salidas comparadas ciclo a ciclo. Más el alias legacy↔canónico en los dos sentidos, el puente legacy y la regresión del cuelgue de `ack`. |
| [`tb_slots_integration`](../../sim/tb_slots_integration.sv) | que el slot 1 sea independiente del 3 y del 6 |

El bloque diferencial es el que gana el sueldo: en una mudanza de registros lo
que importa no es que el módulo nuevo "funcione", sino que haga **lo mismo** que
el bloque del que salió. Cubre también el fan-out por `indep_mode`, que no está
en el mapa de direcciones —vive entre el banco de registros y las salidas— y es
lo primero que se pierde al mover código de un archivo a otro.
