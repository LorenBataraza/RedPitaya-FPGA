# Testbenches de integración (`prj/MCA/sim/`)

Acá quedan **sólo los testbenches que cruzan módulos**. Los unitarios viven con
su módulo, en `../modulos/<m>/sim/`, y se corren desde `../modulos/<m>/work/`.

El criterio de reparto es simple: si un TB instancia RTL de más de un módulo a
la vez, no pertenece a ninguno y va acá.

| Testbench | Módulos que cruza |
|-----------|-------------------|
| `tb_slots_integration` | comun + multitrigger + mca |
| `tb_trig_capture` | multitrigger + `rtl/classic/rp_bram_sm.v` (repo raíz) |
| `tb_osc_cfg` | osc contra multitrigger (diferencial) |

## Requisitos

QuestaSim (`vlib`/`vlog`/`vsim`) en el PATH. Si no está:

```bash
make VSIM=/home/lorenzo/questasim/questasim/linux_x86_64/vsim \
     VLOG=/home/lorenzo/questasim/questasim/linux_x86_64/vlog \
     VLIB=/home/lorenzo/questasim/questasim/linux_x86_64/vlib
```

## Correr

Desde `prj/MCA` (recomendado, no hay que acordarse dónde quedó cada TB):

```bash
make rtl                      # todos: los 5 módulos + integración
make rtl-mca                  # un módulo entero
make rtl-tb_trig_capture      # un TB suelto, lo busca solo
make wave TB=tb_trig_capture  # abre las ondas ya grabadas
```

O directamente acá, para los tres de integración:

```bash
cd prj/MCA/sim
make                    # los 3
make tb_trig_capture    # uno solo
make clean
```

Cada TB imprime `RESULT: PASS` o `RESULT: FAIL`. **El Makefile lo chequea**: si
un TB falla, `make` sale con estado ≠ 0. (Antes no lo miraba, así que `make`
salía con 0 aunque un testbench fallara.)

Las ondas se graban **siempre** en `waves/<tb>.wlf`, no sólo cuando algo falla:
para cuando el chequeo falla, el tiempo que hay que mirar ya pasó. Se abren con
`make wave TB=<tb>`. Para exportarlas fuera de Questa, `make vcd TB=<tb>`.

## Qué verifica cada uno

| Testbench | Qué verifica |
|-----------|--------------|
| `tb_slots_integration` | las tres regiones cableadas como en el top: independencia entre slots y **ruteo del datapath de punta a punta** (con `TAP_ADC` el MCA ve la muestra cruda, no la calibrada). |
| `tb_osc_cfg` | **diferencial contra `multitrigger_rp_scope_cfg`**: mismo estímulo por los offsets legacy, salidas idénticas. Más el alias legacy↔canónico y la regresión del cuelgue de `ack` en las aperturas de canales no construidos. |
| `tb_trig_capture` | **centro del debug del race arm-vs-máscara**: `event_logic` + `rp_bram_sm` como en `rp_scope_multitrigger_com`. Escenario A (máscara-antes-de-arm + flanco pre-arm) → **deadlock** (`wp_trig=0`, `adc_trg_rd=0`); escenario B (arm-antes-de-máscara) → **captura**; escenario C (SW trigger) → captura (inmune al orden). Ver [`../docs/multitrigger/orden_arm_trigger_captura.md`](../docs/multitrigger/orden_arm_trigger_captura.md). |

## Fuentes bajo test

No hay RTL propio acá: todo entra por `DEPS` en el [`Makefile`](Makefile), que
lee los `files.f`/`extra.f` de `comun`, `osc`, `multitrigger` y `mca`. Así esta
carpeta no puede desincronizarse del RTL de los módulos.

## Los testbenches unitarios

| Módulo | Testbenches |
|--------|-------------|
| [`comun`](../modulos/comun/sim/) | `tb_integration_cfg` |
| [`osc`](../modulos/osc/sim/) | `tb_osc_filter` |
| [`multitrigger`](../modulos/multitrigger/sim/) | `tb_multitrigger_cfg`, `tb_multitrigger_trig_src`, `tb_multitrigger_event_logic`, `tb_trigger_shield` |
| [`mca`](../modulos/mca/sim/) | `tb_mca_div_restore`, `tb_mca_hist`, `tb_mca_zoom`, `tb_mca_discriminator`, `tb_mca_pulse_feature`, `tb_mca_top` |
| [`event_ring`](../modulos/event_ring/sim/) | `tb_event_window_capture`, `tb_event_stage_fifo`, `tb_event_slot_writer`, `tb_event_ring_top` |

Cada módulo tiene su plan de verificación en `../modulos/<m>/sim/VERIFICACION.md`.
