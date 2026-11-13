// Assertions de gen_pulsos, enganchadas por `bind` desde el testbench.
//
// Van aparte del RTL a proposito (ver gen_eventos_sva.sv): nunca entran a
// files.f, asi que Vivado ni las ve.
//
// El bind con `.*` conecta por nombre, incluidas senales internas del DUT.

module gen_pulsos_sva (
    input logic        clk_i,
    input logic        rstn_i,
    input logic        cfg_en,
    input logic        arranque,
    input logic        trig_o,
    input logic        disp_c,
    input logic        hecho,
    input logic        desborde,
    input logic [13:0] dat
);

  default clocking cb @(posedge clk_i); endclocking
  default disable iff (!rstn_i);

  // El multitrigger toma el disparo del ASG por flanco: dos pulsos seguidos
  // serian uno.
  ap_sin_pulsos_seguidos: assert property (trig_o |=> !trig_o)
    else $error("dos pulsos en ciclos seguidos");

  // Apagado no hay pulsos, y la salida queda en cero (el DAC mudo).
  ap_pulso_prendido: assert property (trig_o |-> cfg_en)
    else $error("pulso con el generador apagado");
  ap_apagado_mudo: assert property (!cfg_en |=> dat == 14'd0)
    else $error("salida distinta de cero con el generador apagado");

  // Llegado a N no se decide ningun pulso mas.
  ap_hecho_calla: assert property (hecho |-> !disp_c)
    else $error("pulso despues de llegar a N");

  // El desborde es pegajoso hasta el proximo arranque.
  ap_desborde_pegajoso: assert property (desborde && !arranque |=> desborde)
    else $error("el desborde se borro sin un arranque");

  cp_pulso:    cover property (trig_o);
  cp_desborde: cover property ($rose(desborde));
  cp_satura:   cover property (cfg_en && (dat == 14'h1FFF || dat == 14'h2000));

endmodule
