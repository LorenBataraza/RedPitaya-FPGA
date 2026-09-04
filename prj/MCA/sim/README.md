# Testbenches del multitrigger scope (`prj/MCA/sim/`)

Testbenches en SystemVerilog para verificar la lógica de trigger del scope
multitrigger y, en particular, **reproducir el bug del race arm-vs-máscara** y
**validar el fix** (armar la `bram_sm` antes de habilitar la OR-mask).

Ver la explicación completa del bug y la convención de uso en
[`../docs/multitrigger/orden_arm_trigger_captura.md`](../docs/multitrigger/orden_arm_trigger_captura.md).

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
| `tb_integration_cfg` | región de TOP (slot 6): contrato de bus, identificación/descripción del sistema, y que **en reset todos los `ROUTE_*` queden en NATIVO** — la propiedad que hace que el refactor de regiones sea neutro. |
| `tb_slots_integration` | las tres regiones cableadas como en el top: independencia entre slots y **ruteo del datapath de punta a punta** (con `TAP_ADC` el MCA ve la muestra cruda, no la calibrada). |
| `tb_osc_cfg` | **diferencial contra `multitrigger_rp_scope_cfg`**: mismo estímulo por los offsets legacy, salidas idénticas. Más el alias legacy↔canónico y la regresión del cuelgue de `ack` en las aperturas de canales no construidos. |
| `tb_multitrigger_cfg` | región de MULTITRIGGER (slot 3): equivalencia con el mapa viejo, puente legacy desde el slot 1, fan-out por `indep_mode`. |
| `tb_multitrigger_trig_src` | unidad: la OR-mask dispara `adc_trig`, latch/clear de `adc_trg_dis`, auto-clear single-shot vs persistencia en `we_keep=1`, gating SW por `dly_valp`. |
| `tb_trigger_shield` | unidad: holdoff `src→dst` (`dur=0` re-arm inmediato, `dur=K` con contador), transparencia del clear de SW en canales no escudados. |
| `tb_multitrigger_event_logic` | integración: `trigger_event_o` = OR de canales, latch/reset del `snapshot`. |
| `tb_trig_capture` | **centro del debug**: `event_logic` + `rp_bram_sm` como en `rp_scope_multitrigger_com`. Escenario A (máscara-antes-de-arm + flanco pre-arm) → **deadlock** (`wp_trig=0`, `adc_trg_rd=0`); escenario B (arm-antes-de-máscara) → **captura**; escenario C (SW trigger) → captura (inmune al orden). |

> Los cuatro primeros son del refactor a regiones por módulo; el mapa está en
> [`../docs/TOP/register_map_top.md`](../docs/TOP/register_map_top.md).

### MCA

| Testbench | Qué verifica |
|-----------|--------------|
| `tb_mca_div_restore` | unidad del divisor restaurador: cociente exacto, latencia **fija** de `Q_W` ciclos incluso en los casos de error, y los tres bordes que rompen si no se tratan (`den=0`, `num≥den`, `num=0`). |
| `tb_mca_hist` | motor de histograma: acumulación, **forwarding** a distancia 1 y 2 (donde es más fácil un off-by-one), saturación sin envolvimiento, barrido de borrado con el puerto de lectura vivo, y la bandera `full` con `keep_counter_if_full` — incluido que congelar **no** se confunda con `dropped`. |
| `tb_mca_zoom` | el zoom alineado a potencias de 2. El check que gana el sueldo es el **anidamiento exacto**: cada bin grueso es la unión de dos bins finos, que es la propiedad por la que el zoom se alineó así y lo que permite coser espectros de distinto nivel con aritmética entera. Más saturación, y que `z=0` fuerce `k=0` en vez de mandar todo al canal 0 en silencio. |
| `tb_mca_discriminator` | corte por feature: intervalo interno y su complemento con los **bordes incluidos**, que el selector siga al contenido de la ranura (el check que agarra un mux clavado), e **intervalo vacío** (`min>max`) fijado explícitamente. |
| `tb_mca_pulse_feature` | segmentador y extractor: ventanas por histéresis y por compuerta fija, los dos estimadores, línea de base fija y automática, rechazos, bordes del PSD, el **bus de features** con sus valores calculados a mano, el **ancho inverso** separando pulsos de distinto ancho a igual amplitud, y el **borde del tiempo muerto** (dos pulsos separados por menos que la latencia del divisor). |
| `tb_mca_top` | esclavo de bus: contrato de `ack`, registros, aperturas de histograma, y el datapath de punta a punta. |

> Casi todos los valores esperados salen de una **multiplicación a mano** sobre un
> pulso rectangular, no de reimplementar el DUT: es lo que evita que el test
> herede el mismo error que el diseño.

## Fuentes bajo test

`../rtl/mine/{multitrigger_trig_src.sv, trigger_shield.sv,
multitrigger_event_logic.v}` + `../../../rtl_250/classic/rp_bram_sm.v`
(la FSM de captura stock). Ver [`filelist.f`](filelist.f).
