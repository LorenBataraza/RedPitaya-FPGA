// Assertions de mca_top, enganchadas por `bind` desde sim/sva/bind_mca.sv.
//
// Van aparte del RTL a proposito: el RTL sintetizable no se toca, no hace falta
// un `ifndef SYNTHESIS`, y estas propiedades nunca entran a files.f, asi que
// Vivado ni las ve. Se compilan solo en el flujo de simulacion.
//
// El modulo replica los puertos del DUT que quiere observar; el bind con `.*`
// los conecta por nombre.

module mca_top_sva (
    input logic adc_clk_i,
    input logic adc_rstn_i
);

  default clocking cb @(posedge adc_clk_i); endclocking
  default disable iff (!adc_rstn_i);

  // TODO: propiedades de mca. Arrancar por las invariantes que el testbench
  // hoy comprueba a mano en puntos sueltos: aca valen en TODO ciclo.
  //
  // Ejemplo de la forma:
  //   ap_handshake_estable: assert property (
  //     valid_o && !ready_i |=> valid_o && $stable(data_o)
  //   ) else $error("dato cambio con valid alto y ready bajo");

endmodule
