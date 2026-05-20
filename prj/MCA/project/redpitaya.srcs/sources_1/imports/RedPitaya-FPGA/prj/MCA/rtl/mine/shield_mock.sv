// Módulo que toma configuración como parámetros.
// La salida se la conecta al trig_dis_clr_i del multitrigger_trig_src.
//
//   Cantidad de canales:  parameter integer N          = 4
//   Duración del holdoff: parameter integer DURATION_W = 16
//   Shield src  vector de N  (qué canales actúan de fuente)
//   Shield dest vector de N  (qué canales son escudados)
//
// Holdoff src->dest: cuando un canal "src" dispara, los canales "dest" quedan
// deshabilitados durante DURATION ciclos de ADC; al expirar se emite un pulso
// de trig_dis_clr que los re-arma. Los canales no escudados siguen de forma
// transparente al clear de SW.

module trigger_shield #(
  parameter integer N          = 4,    // canales
  parameter integer DURATION_W = 16    // ancho del contador de holdoff
)(
  input                      clk_i             ,
  input                      rstn_i            , // reset síncrono activo-bajo
  input  [N-1:0]             trig_event_i      , // disparo por canal (adc_trig de cada trig_src)
  input  [N-1:0]             shield_src_i      , // canales fuente del escudo
  input  [N-1:0]             shield_dst_i      , // canales escudados (dest)
  input  [DURATION_W-1:0]    shield_dur_i      , // duración del holdoff (ciclos ADC)
  input  [N-1:0]             sw_trig_dis_clr_i , // clear de SW (rp_scope_cfg, reg 0x94)
  output [N-1:0]             trig_dis_clr_o      // a multitrigger_trig_src.trig_dis_clr_i
);

reg  [DURATION_W-1:0] cnt   ;   // contador de holdoff (global)
reg                   active;   // holdoff en progreso
reg  [N-1:0]          clr_q ;   // pulso de re-arm hacia los dest

// 


endmodule
