# Síntesis previa al banco de trapecios (2026-10-30)

Es el último build que estaba en `out/` antes de rearmar con el banco de trapecios y el
disparo con polo-cero (2026-11-03). Lo archivé acá antes de rearmar.

- **Lo que tiene:** el MCA2 (`N_ACC = 4` ranuras) con un solo trapecio (`F_TRAP`, feature
  9; registros 0x128/0x12C/0x130). No tiene el banco (`0x134` y `0x180..0x1BF`) ni
  `F_FORMA`. El multitrigger no tiene la fuente con polo-cero (`CAPS[17] = 0`).
- **Timing:** WNS −0.383 ns en `clk_fpga_3` (el `axi_protocol_converter_0` del XADC, a
  200 MHz). El MCA cerraba (+0.023 ns). El arreglo, el XADC a `FCLK_CLK0` en
  `ip/systemZ10.tcl`, vino después y no está en este build.
- **Recursos:** 12 188 LUT (69.25 %), 26.5 BRAM y 5 DSP.
- **md5 de `mca_red_pitaya_Z10_2CH.bit.bin`:** `a3d14be6fecb6f50ca00658dbb50906b`.

El MCA2 validado en placa no es este build: está en la placa, en
`/root/mca_red_pitaya_Z10_2CH.bit.bin`. La prueba del trapecio en placa se hizo con
`/root/mca_trap_prueba_Z10_2CH.bit.bin`.

Para cargar este build:

    fpgautil -b mca_red_pitaya_Z10_2CH.bit.bin
