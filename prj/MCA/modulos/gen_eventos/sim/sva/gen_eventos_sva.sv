// Assertions de gen_eventos, enganchadas por `bind` desde el testbench.
//
// Van aparte del RTL a proposito: el RTL sintetizable no se toca, no hace falta
// un `ifndef SYNTHESIS`, y estas propiedades nunca entran a files.f, asi que
// Vivado ni las ve. Se compilan solo en el flujo de simulacion.
//
// El bind con `.*` conecta por nombre, incluidas senales internas del DUT.

module gen_eventos_sva (
    input logic        clk_i,
    input logic        rstn_i,
    input logic        cfg_en,
    input logic        cfg_aleat,
    input logic        run_i,
    input logic        trig_o,
    input logic [16:0] snap_o,
    input logic        disp_c,
    input logic        hecho,
    input logic [15:0] hold
);

  default clocking cb @(posedge clk_i); endclocking
  default disable iff (!rstn_i);

  // La captura toma el flanco: dos pulsos seguidos serian UN evento, y GEN_CNT
  // contaria dos. Es lo que garantizan los minimos de PERIODO y DT_MIN.
  ap_sin_pulsos_seguidos: assert property (cfg_en && trig_o |=> !trig_o)
    else $error("dos disparos generados en ciclos seguidos");

  // Un pulso generado con el ring fuera de RUNNING no lo cuenta nadie.
  ap_pulso_con_ring: assert property (cfg_en && trig_o |-> run_i)
    else $error("disparo generado con el ring fuera de RUNNING");

  // Con el generador prendido, el snapshot lo marca.
  ap_snap_marcado: assert property (cfg_en |-> snap_o[16])
    else $error("snapshot sin la marca del generador");

  // Llegado a N no se decide ningun disparo mas.
  ap_hecho_calla: assert property (hecho |-> !disp_c)
    else $error("disparo despues de llegar a N");

  // En el modo aleatorio, mientras espera no dispara.
  ap_espera: assert property (cfg_aleat && hold != 0 |-> !disp_c)
    else $error("disparo durante la espera de DT_MIN");

  cp_pulso:   cover property (cfg_en && trig_o);
  cp_hecho:   cover property ($rose(hecho));
  cp_espera:  cover property (cfg_aleat && hold != 0 && run_i);

endmodule
