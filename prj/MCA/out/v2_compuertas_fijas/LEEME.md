# Síntesis v2 — compuertas de largo FIJO (etapa B)

Build del 2026-08-12 con Vivado 2020.1. Agrega el modo de ventana por
**compuertas de largo fijo** al segmentador, seleccionable por registro.

**Todavía NO se midió en placa.**

## Qué cambia respecto de v1

| Registro | Contenido |
|---|---|
| `0x048` | `cfg_gate_mode`: 0 = ventana por histéresis, 1 = compuertas fijas |
| `0x04C` | `{larga[31:16], corta[15:0]}` en muestras |

**Arranca en modo 0**, así que hasta que se escriba `0x048` se comporta
exactamente como v1. Es lo que permite comparar los dos modos en el mismo
bitstream, igual que ya se hace con `cfg_amp_src`.

Detalle del diseño en [`../../docs/mca/register_map_mca.md`](../../docs/mca/register_map_mca.md)
y en la cabecera de [`../../rtl/mine/mca/mca_pulse_feature.sv`](../../rtl/mine/mca/mca_pulse_feature.sv).

## Timing y recursos, contra v1

| | v1 (histéresis) | v2 (compuertas) |
|---|---|---|
| WNS | −0.114 ns | **−0.027 ns** |
| TNS | −0.570 | **−0.372** |
| Endpoints en falla | 14 / 22 493 | 22 / 22 571 |
| Slice LUTs | 5841 (33.19 %) | 5874 (33.38 %) |
| Registros | 7579 (21.53 %) | 7612 (21.63 %) |
| Block RAM | 40 / 60 | 40 / 60 |
| DSP | 4 / 80 | 4 / 80 |

El costo del modo nuevo es **+33 LUT y +33 registros**. Subieron los endpoints
en falla pero bajaron el peor slack y la violación total: es ruido de ruteo, y
todas las violaciones están por debajo de 0.03 ns (0.3 % del período de 8 ns).

Los dos caminos violados:

- `i_mca/i_feat/q_tot_reg[14]` → `cnt_rej_amp_o_reg[24]/CE`, **−0.027 ns**
  (la ventana de aceptación de amplitud; en v1 el peor del MCA era −0.057);
- `ps/system_i/axi_protocol_converter_0/…` → `xadc/…`, **−0.005 ns**, del block
  design de Xilinx y preexistente.

Los `CRITICAL WARNING` de `sdc/red_pitaya.xdc` (`set_property expects at least
one object`) también son **preexistentes**: el IO ruteado es idéntico al de v1.

## Verificado

- 37 celdas `cfg_gate_*` en el netlist ruteado, o sea que la funcionalidad
  está realmente en el bitstream.
- Simulación: 9 testbenches / 178 checks, incluidos 5 escenarios nuevos de
  compuerta fija y la regresión de que el modo 0 no cambió.

## Cargar en la placa

```bash
fpgautil -b mca_red_pitaya.bit.bin
python3 test_mca_hw.py                          # 29 PASS / 0 FAIL
python3 testbench_mca.py sweep_gate --outdir <dir>
```

Predicción del análisis offline sobre 7054 pulsos reales
([`../../software/tests/estimadores/`](../../software/tests/estimadores/)):
mínimo cerca de **384 muestras** y una mejora de **~3.5×** sobre la histéresis
(0.528 % → 0.149 %). Si sale menos de 1.2×, `sweep_gate` lo avisa solo.

Para volver al bitstream anterior: [`../v1_histeresis/`](../v1_histeresis/).
