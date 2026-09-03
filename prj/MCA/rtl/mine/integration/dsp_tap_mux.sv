`timescale 1ns/1ps
//=============================================================================
// dsp_tap_mux — elige de qué punto de la cadena DSP toma un consumidor
//
// La cadena DSP del scope tiene varios nodos utilizables, y hasta el refactor
// cada consumidor estaba cableado a uno fijo:
//
//   adc_dat ─→ calib ─→ osc_filter ─→ [byp] ─→ adc_dec_in ──────── TAP_DEC_IN
//      │                                            │                  └→ MCA
//   TAP_ADC                                     rp_decim ─→ adc_dly_in
//                                                    │           └→ rp_adc_trig (MTRG)
//                                               rp_delay ─→ adc_bram_in ── TAP_BRAM_IN
//                                                                  └→ rp_acq_bram (OSC)
//
// Este mux deja que el software lo decida en runtime, desde los registros
// ROUTE_* de la región de TOP (integration_cfg, slot 6).
//
// EL DATO Y SU VALID VIAJAN JUNTOS. Los nodos post-decimación llevan estrobo
// (dec_val, dly_val) porque la decimación no es 1; los pre-decimación son
// continuos a 125 MSPS y su valid es constante. Mezclarlos sin arrastrar el
// valid daría un consumidor que lee muestras repetidas o se saltea muestras,
// según el sentido del cambio.
//
// POR QUÉ EL MUX ES COMBINACIONAL Y NO REGISTRADO. Registrar la salida sería
// lo natural para timing, pero correría el dato UN ciclo respecto de las
// señales de control que lo acompañan (adc_we y el write pointer en el caso
// del OSC, la alineación trigger-vs-captura en el del multitrigger), y en modo
// NATIVO el hardware dejaría de ser idéntico al de antes del refactor — que es
// justamente la propiedad que se quiso preservar. Un mux 4:1 de 14 bits es un
// LUT6 por bit, un solo nivel de lógica, y no cae sobre el camino crítico del
// diseño (que era el lazo IIR de osc_filter, deshabilitado con EN_FILT=0).
// Si alguna vez hiciera falta registrarlo, hay que registrar TAMBIÉN el valid
// y las señales de control de cada consumidor, en conjunto.
//=============================================================================

module dsp_tap_mux #(
  parameter integer DW = 14
)(
  // Selección (desde integration_cfg). Ver la lista canónica de taps en
  // integration_cfg.sv; si cambia allá, cambia acá.
  input      [2-1:0]  tap_sel_i ,
  input               en_i      ,

  // Fuentes: un par (dato, valid) por tap.
  input      [DW-1:0] nat_dat_i , input nat_val_i ,  // 0: como estaba cableado
  input      [DW-1:0] adc_dat_i , input adc_val_i ,  // 1: crudo, pre-DSP
  input      [DW-1:0] dec_dat_i , input dec_val_i ,  // 2: pre-decimación
  input      [DW-1:0] bram_dat_i, input bram_val_i,  // 3: post-DSP completo

  output reg [DW-1:0] dat_o     ,
  output reg          val_o
);

localparam [1:0] TAP_NATIVE  = 2'd0;
localparam [1:0] TAP_ADC     = 2'd1;
localparam [1:0] TAP_DEC_IN  = 2'd2;
localparam [1:0] TAP_BRAM_IN = 2'd3;

always @(*) begin
  case (tap_sel_i)
    TAP_ADC     : begin dat_o = adc_dat_i ; val_o = adc_val_i ; end
    TAP_DEC_IN  : begin dat_o = dec_dat_i ; val_o = dec_val_i ; end
    TAP_BRAM_IN : begin dat_o = bram_dat_i; val_o = bram_val_i; end
    default     : begin dat_o = nat_dat_i ; val_o = nat_val_i ; end
  endcase
  // El enable corta el valid, no el dato: así el consumidor deja de ver
  // muestras nuevas sin que le cambie el nivel de la entrada de datos.
  if (!en_i) val_o = 1'b0;
end

endmodule
