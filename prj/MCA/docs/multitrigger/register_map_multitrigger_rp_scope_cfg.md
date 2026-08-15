# Mapa de registros — `multitrigger_rp_scope_cfg`

Módulo: [`prj/MCA/rtl/mine/multitrigger_rp_scope_cfg.sv`](../../rtl/mine/multitrigger/multitrigger_rp_scope_cfg.sv)

Da acceso a los registros y buffers internos del scope a través del *system
bus* de la Pitaya. Las direcciones son `sys_addr[19:0]` (offset dentro del
bloque del scope), siempre *word-aligned* (múltiplos de 4).

Base física del bloque: `0x4010_0000`, tamaño `0x30000` (ver
[`multitrigger_utils.py`](../../software/multitrigger_utils.py), `SCOPE_PHYS` /
`SCOPE_SIZE`).

Parámetros relevantes: `CHN` (0/1, selecciona qué mitad del estado se
expone), `N_CH` (canales activos), `DW=14` (ancho de dato ADC), `RSZ=14`
(tamaño RAM 2^RSZ).

---

## Comandos / control

Escrituras de pulso (auto-clear en 1 ciclo de `adc_clk`). El byte que se
decodifica por canal (`sys_dats`) depende de `indep_mode`.

| Offset | Acc | Bits | Símbolo | Función |
|--------|-----|------|---------|---------|
| `0x000` | W | [0]  | `adc_arm_do`   | SW ARM |
| `0x000` | W | [1]  | `adc_rst_do`   | reset del FSM |
| `0x000` | W | [3]  | `adc_we_keep`  | ARM permanece activo tras el trigger |
| `0x000` | W | [5]  | `indep_mode`   | modo de adquisición independiente por canal |
| `0x000` | R | [31:0] | `adc_state_rd` | estado del ADC (`adc_state` + `adc_state_ext`, orden según `CHN`) |
| `0x004` | W | [3:0]==`0x1` | `adc_trig_sw` | SW trigger |
| `0x004` | R | [31:0] | `trg_state_rd` | estado/máscara de trigger activa (8 b bajos por canal) |
| `0x094` | W | [0]  | `trig_dis_clr` | clear del trigger protect/disable (`adc_trg_dis`). Offset reservado, sin readback |

> El byte por canal: con `indep_mode` se decodifica un byte distinto de
> `sys_wdata`; por eso el driver escribe `0x0101` (ch0+ch1) y `0x0202`, etc.

---

## Configuración de adquisición (R/W)

| Offset | Bits | Reset | Símbolo | Descripción |
|--------|------|-------|---------|-------------|
| `0x008` | [DW-1:0] | `+5000` | `set_tresh` ch1 | umbral de trigger (signed) |
| `0x00C` | [DW-1:0] | `-5000` | `set_tresh` ch2 | umbral de trigger (signed) |
| `0x010` | [31:0] | 0 | `set_dly` ch1 | trigger delay (post-trigger) |
| `0x014` | [16:0] | 1 | `set_dec` ch1 | factor de decimación |
| `0x020` | [DW-1:0] | 20 | `set_hyst` ch1 | histéresis |
| `0x024` | [DW-1:0] | 20 | `set_hyst` ch2 | histéresis |
| `0x028` | [0] | 0 | `set_avg_en` | averaging enable (R devuelve 4 canales empaquetados en bytes) |
| `0x110` | [31:0] | 0 | `set_dly` ch2 | trigger delay |
| `0x114` | [16:0] | 1 | `set_dec` ch2 | factor de decimación |

---

## Filtros (R/W)

| Offset | Bits | Reset | Símbolo |
|--------|------|-------|---------|
| `0x030` / `0x040` | [17:0] | 0 | `set_filt_aa` ch1 / ch2 |
| `0x034` / `0x044` | [24:0] | 0 | `set_filt_bb` ch1 / ch2 |
| `0x038` / `0x048` | [24:0] | `0xFFFFFF` | `set_filt_kk` ch1 / ch2 |
| `0x03C` / `0x04C` | [24:0] | 0 | `set_filt_pp` ch1 / ch2 |
| `0x098` | [3:0] | 0 | `set_filt_byp` (bypass por canal) |

---

## AXI (R/W config + R-only status)

| Offset | Acc | Bits | Símbolo |
|--------|-----|------|---------|
| `0x050` / `0x070` | R/W | [31:0] | `set_axi_start` ch1 / ch2 |
| `0x054` / `0x074` | R/W | [31:0] | `set_axi_stop` ch1 / ch2 |
| `0x058` / `0x078` | R/W | [31:0] | `set_axi_dly` ch1 / ch2 |
| `0x05C` / `0x07C` | R/W | [0] | `set_axi_en` ch1 / ch2 (write con bit0=1 emite `axi_en_pulse`) |
| `0x060` / `0x080` | R | [31:0] | `axi_wp_trig_i` ch1 / ch2 |
| `0x064` / `0x084` | R | [31:0] | `axi_wp_cur_i` ch1 / ch2 |
| `0x088` | R | — | `axi_state_i` (2 bytes) |

---

## Status / punteros (read-only)

| Offset | Símbolo |
|--------|---------|
| `0x018` / `0x118` | `adc_wp_cur_i` ch1 / ch2 (write pointer actual) |
| `0x01C` / `0x11C` | `adc_wp_trig_i` ch1 / ch2 (write pointer al trigger) |
| `0x02C` / `0x12C` | `adc_we_cnt_i` ch1 / ch2 |
| `0x090` | `set_deb_len` (R/W, reset 62500) |

---

## Calibración (R/W)

| Offset | Bits | Reset | Símbolo |
|--------|------|-------|---------|
| `0x200` / `0x208` | [DW-1:0] | 0 | `set_calib_offset` ch1 / ch2 |
| `0x204` / `0x20C` | [15:0] | `0x8000` | `set_calib_gain` ch1 / ch2 |

---

## Multitrigger — añadidos respecto al `rp_scope_cfg` original

| Offset | Acc | Campos | Símbolo / función |
|--------|-----|--------|-------------------|
| `0x210` | R/W | `[3:0]` src · `[11:8]` dst · `[31:16]` dur | **trigger_shield config** — `shield_src` / `shield_dst` / `shield_dur`. Reset 0 |
| `0x214` | R | `[15:0]` cnt · `[16]` active | **shield runtime**: `shield_cnt_i`, `shield_active_i` |
| `0x218` | R | `[16:0]` | **trig_snapshot** (sticky: qué disparó el último evento) |
| `0x21C` | R | `[3:0]` dis_act · `[7:4]` we_keep | flags de `adc_trg_dis_act` y `adc_we_keep` por canal |
| `0x240` | R/W | `[31:0]` | **OR_MASK ch0** — máscara de fuentes de trigger |
| `0x244` | R/W | `[31:0]` | OR_MASK ch1 |
| `0x248` | R/W | `[31:0]` | OR_MASK ch2 |
| `0x24C` | R/W | `[31:0]` | OR_MASK ch3 |

### Layout del registro `0x210` (trigger_shield)

```
 31            16 15  12 11   8 7   4 3   0
+---------------+------+------+-----+-----+
|     dur       | 0000 | dst  | 0000| src |
+---------------+------+------+-----+-----+
```

### OR_MASK (`0x240` + 4·canal)

- Un registro de 32 b por canal, *word-aligned*, separado del SW-trigger de
  `0x04`.
- El write emite el pulso `new_trg_src` **incluso con `wdata=0`** (para poder
  limpiar la máscara explícitamente).
- El readback (`trg_src_stored`) refleja siempre el último write y cubre
  ch0..ch3 aunque `N_CH < 4`.
- La máscara activa (8 b bajos) también se lee en `trg_state` @ `0x04`.

Bits de la máscara (definidos en `multitrigger_trig_src.sv`, replicados en el
driver):

| Bit | Símbolo | Bit | Símbolo |
|-----|---------|-----|---------|
| 0 | `BIT_SW`     | 9  | `BIT_EXT_P`    |
| 1 | `BIT_ADC_P0` | 10 | `BIT_EXT_N`    |
| 2 | `BIT_ADC_N0` | 11 | `BIT_ASG_P`    |
| 3 | `BIT_ADC_P1` | 12 | `BIT_ASG_N`    |
| 4 | `BIT_ADC_N1` | 13 | `BIT_TRIG_CH0` |
| 5 | `BIT_ADC_P2` | 14 | `BIT_TRIG_CH1` |
| 6 | `BIT_ADC_N2` | 15 | `BIT_TRIG_CH2` |
| 7 | `BIT_ADC_P3` | 16 | `BIT_TRIG_CH3` |
| 8 | `BIT_ADC_N3` |    |                |

---

## Espacios BRAM (read-only)

| Offset | Símbolo |
|--------|---------|
| `0x1xxxx` | `bram_rd_dat_i` ch1 |
| `0x2xxxx` | `bram_rd_dat_i` ch2 |
| `0x3xxxx` | `bram_rd_dat_i` ch3 |
| `0x4xxxx` | `bram_rd_dat_i` ch4 |

---

### Observaciones (no son errores del mapa)

1. **Orden de bits OR_MASK vs snapshot.** Las constantes `BIT_*` (orden
   `p0,n0,p1,n1,…`) y el decoder `_SNAP_NAMES` del snapshot @`0x218`
   (orden `p0,p1,p2,p3,n0,n1,…`) usan **órdenes de bit distintos**. Eso es
   correcto siempre que el empaquetado de `trig_snapshot_i` en
   `multitrigger_trig_src.sv` use ese segundo orden — conviene verificarlo
   ahí, queda fuera de este módulo (`*_cfg` solo pasa los 17 b directos).
2. El driver llega a `set_tresh` (`0x08`/`0x0C`) vía la API `rp`
   (`rp_AcqSetTriggerLevel`), no por escritura directa; el readback directo en
   `debug_trigger()` sí coincide.

---

*Generado a partir de la inspección de `multitrigger_rp_scope_cfg.sv`. Si se
modifica el `casez` de readback o el bloque de writes, regenerar este mapa.*
