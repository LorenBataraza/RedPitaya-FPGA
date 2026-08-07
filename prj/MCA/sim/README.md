# Testbenches del multitrigger scope (`prj/MCA/sim/`)

Testbenches en SystemVerilog para verificar la lógica de trigger del scope
multitrigger y, en particular, **reproducir el bug del race arm-vs-máscara** y
**validar el fix** (armar la `bram_sm` antes de habilitar la OR-mask).

Ver la explicación completa del bug y la convención de uso en
[`../docs/orden_arm_trigger_captura.md`](../docs/orden_arm_trigger_captura.md).

## Requisitos

QuestaSim (`vlib`/`vlog`/`vsim`) en el PATH. Si no está en el PATH:

```bash
make VSIM=/home/lorenzo/questasim/questasim/linux_x86_64/vsim \
     VLOG=/home/lorenzo/questasim/questasim/linux_x86_64/vlog \
     VLIB=/home/lorenzo/questasim/questasim/linux_x86_64/vlib
```

## Correr

```bash
cd prj/MCA/sim
make                     # compila y corre los 4 testbenches
make tb_trig_capture     # corre uno solo
make wave TB=tb_trig_capture   # GUI con ondas
make clean
```

Cada TB imprime `RESULT: PASS` o `RESULT: FAIL` al final (y un detalle por
chequeo). Todos generan un `.vcd` para inspección con GTKWave/QuestaSim.

## Testbenches

| Testbench | Qué verifica |
|-----------|--------------|
| `tb_multitrigger_trig_src` | unidad: la OR-mask dispara `adc_trig`, latch/clear de `adc_trg_dis`, auto-clear single-shot vs persistencia en `we_keep=1`, gating SW por `dly_valp`. |
| `tb_trigger_shield` | unidad: holdoff `src→dst` (`dur=0` re-arm inmediato, `dur=K` con contador), transparencia del clear de SW en canales no escudados. |
| `tb_multitrigger_event_logic` | integración: `trigger_event_o` = OR de canales, latch/reset del `snapshot`. |
| `tb_trig_capture` | **centro del debug**: `event_logic` + `rp_bram_sm` como en `rp_scope_multitrigger_com`. Escenario A (máscara-antes-de-arm + flanco pre-arm) → **deadlock** (`wp_trig=0`, `adc_trg_rd=0`); escenario B (arm-antes-de-máscara) → **captura**; escenario C (SW trigger) → captura (inmune al orden). |

## Fuentes bajo test

`../rtl/mine/{multitrigger_trig_src.sv, trigger_shield.sv,
multitrigger_event_logic.v}` + `../../../rtl_250/classic/rp_bram_sm.v`
(la FSM de captura stock). Ver [`filelist.f`](filelist.f).
