# Mapa de registros — región de MULTITRIGGER

**Base:** `0x4030_0000` (slot 3 del bus de sistema)
**RTL:** [`multitrigger_cfg.sv`](../../rtl/mine/multitrigger/multitrigger_cfg.sv)
**Lógica:** [`multitrigger_event_logic.v`](../../rtl/mine/multitrigger/multitrigger_event_logic.v) ·
[`multitrigger_trig_src.sv`](../../rtl/mine/multitrigger/multitrigger_trig_src.sv) ·
[`trigger_shield.sv`](../../rtl/mine/multitrigger/trigger_shield.sv)

Antes del refactor estos registros vivían dentro del `casez` de
`multitrigger_rp_scope_cfg` (slot 1), mezclados con los del scope y colgados del
mismo `sys_ack` que las aperturas BRAM — el mismo ack que tenía el bug de
`bram_ack[2]`/`[3]` atado a cero. Al separarlos, el multitrigger deja de
compartir esa ruta.

Contrato del bus: [`../TOP/bus_sistema_redpitaya.md`](../TOP/bus_sistema_redpitaya.md).
Mapa de slots: [`../TOP/register_map_top.md`](../TOP/register_map_top.md).

> En `red_pitaya_top` esta región **no** está en el slot 3 sino en el **7**: ese
> top conserva el ASG y el PID. El registro `SLOTS` (`0x4060_0024`) publica el
> mapa real de cada bitstream.

---

## Registros

| Offset | R/W | Campo | Antes vivía en |
|---|---|---|---|
| `0x000` | R | `MAGIC` = `0x4D545247` (`"MTRG"`) | — |
| `0x004` | R | `CAPS` `{SHIELD_N[15:12], SRC_W[11:4], N_CH[3:0]}` | — |
| `0x010` | RW | `SHIELD_CFG` | `0x4010_0210` |
| `0x014` | R | `SHIELD_STAT` `{active[16], cnt[15:0]}` | `0x4010_0214` |
| `0x018` | R | `SNAPSHOT` (17 b, sticky) | `0x4010_0218` |
| `0x01C` | R | `DIS_FLAGS` `{we_keep[7:4], dis_act[3:0]}` | `0x4010_021C` |
| `0x020` | W | `TRIG_SW` — **bit por canal** | `0x4010_0004` bits `[3:0]` |
| `0x024` | W | `TRIG_DIS_CLR` — bit por canal | `0x4010_0094` |
| `0x028` | R | `TRG_STATE` — máscara activa, 8 b por canal | `0x4010_0004` |
| `0x040`+4·ch | RW | `OR_MASK` ch0..ch3 | `0x4010_0240`+4·ch |

### `SHIELD_CFG` (`0x010`)

```
 31            16 15  12 11   8 7   4 3   0
+---------------+------+------+-----+-----+
|     dur       | 0000 | dst  | 0000| src |
+---------------+------+------+-----+-----+
```

`src` dispara el holdoff, `dst` es el canal inhibido, `dur` la duración en
ciclos de `adc_clk`. Con `dur = 0` el re-arme es inmediato.

### `OR_MASK` (`0x040` + 4·canal)

Un registro de 32 b por canal, *word-aligned*. La escritura emite el pulso
`new_trg_src` **incluso con `wdata = 0`**, para poder limpiar la máscara
explícitamente. El readback refleja siempre el último write y cubre ch0..ch3
aunque `N_CH < 4`. La máscara activa (8 b bajos) también se lee en `TRG_STATE`.

Bits, definidos en `multitrigger_trig_src.sv`:

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

> **El snapshot de `0x018` usa otro orden de bits** (`p0,p1,p2,p3,n0,n1,…`),
> no el de esta tabla. Es correcto siempre que el empaquetado de
> `trig_snapshot_i` en `multitrigger_trig_src.sv` use ese segundo orden — es una
> trampa conocida, no un error del mapa.

---

## Lo que cambió respecto del mapa viejo

**`TRIG_SW` y `TRIG_DIS_CLR` pasaron a un bit por canal.** Antes eran
byte-por-canal (por eso el driver escribía `0x0101` para ch0+ch1) y el
SW-trigger estaba escondido en los bits `[3:0]` de un registro compartido con el
`trg_state`. El formato viejo **se sigue aceptando** por el puente legacy del
slot 1: `osc_cfg` decodifica `0x004` y `0x094`, y manda el pulso ya decodificado
por canal, que acá se OR-ea con el registro propio. Así `librp` sigue
funcionando.

**`trig_dis_clr` ahora tiene readback.** En el mapa viejo `0x094` era un offset
"reservado" sin lectura.

---

## Una verruga preservada a propósito

`sys_bus_cdc` sostiene `wen` hasta el ack, así que los pulsos de este módulo
—`TRIG_SW`, `TRIG_DIS_CLR`, `new_trg_src`— duran **~5 ciclos, no uno**.

Es el comportamiento que tenía el módulo original y del que depende la lógica
aguas abajo. Convertirlos en estrobos de un ciclo es un cambio deliberado y
aparte: no es algo que deba colarse en una mudanza de registros, donde lo que se
busca es mover código sin cambiar semántica.

(Los registros de configuración —`SHIELD_CFG`, `OR_MASK`— no sufren: la
escritura es idempotente.)

---

## El fan-out por `indep_mode`

Sin modo independiente, **todos los canales siguen al canal 0**. Vale para
`TRIG_SW`, `TRIG_DIS_CLR`, `new_trg_src` y `OR_MASK`. `indep_mode` vive en el
OSC (`0x4010_1014` canónico, `0x4010_0000` bit 5 del byte legacy) y llega acá
por puerto.

No está en el mapa de direcciones —vive entre el banco de registros y las
salidas— y es lo primero que se pierde al mover código de un archivo a otro.
`tb_multitrigger_cfg` lo cubre en las dos ramas.

---

## Testbenches

| Testbench | Qué verifica |
|---|---|
| [`tb_multitrigger_cfg`](../../sim/tb_multitrigger_cfg.sv) | equivalencia con el mapa viejo registro por registro; puente legacy en las dos vías; fan-out por `indep_mode`; contrato de bus sobre todo el slot |
| [`tb_multitrigger_trig_src`](../../sim/tb_multitrigger_trig_src.sv) | la OR-mask dispara; latch/clear de `adc_trg_dis`; gating SW por `dly_valp` |
| [`tb_trigger_shield`](../../sim/tb_trigger_shield.sv) | holdoff `src→dst`, `dur=0` vs `dur=K` |
| [`tb_multitrigger_event_logic`](../../sim/tb_multitrigger_event_logic.sv) | `trigger_event` = OR de canales; latch/reset del snapshot |
| [`tb_trig_capture`](../../sim/tb_trig_capture.sv) | el race arm-vs-máscara; ver [`orden_arm_trigger_captura.md`](orden_arm_trigger_captura.md) |
