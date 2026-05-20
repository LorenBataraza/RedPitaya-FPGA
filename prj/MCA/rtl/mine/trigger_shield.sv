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
  output [N-1:0]             trig_dis_clr_o    , // a multitrigger_trig_src.trig_dis_clr_i
  // Estado expuesto para debug
  output [DURATION_W-1:0]    cnt_o             , // contador holdoff actual
  output                     active_o            // holdoff en progreso
);

reg  [DURATION_W-1:0] cnt   ;   // contador de holdoff (global)
reg                   active;   // holdoff en progreso
reg  [N-1:0]          clr_q ;   // pulso de re-arm hacia los dest

wire src_fire = |(trig_event_i & shield_src_i);

always @(posedge clk_i)
if (rstn_i == 1'b0) begin
   cnt    <= {DURATION_W{1'b0}} ;
   active <= 1'b0 ;
   clr_q  <= {N{1'b0}} ;
end else begin
   clr_q <= {N{1'b0}} ;                       // por defecto sin pulso
   if (src_fire) begin
      cnt    <= shield_dur_i ;
      active <= (shield_dur_i != {DURATION_W{1'b0}}) ;
      if (shield_dur_i == {DURATION_W{1'b0}})
         clr_q <= shield_dst_i ;               // dur==0 -> re-arm inmediato
   end else if (active) begin
      if (cnt <= {{(DURATION_W-1){1'b0}}, 1'b1}) begin
         cnt    <= {DURATION_W{1'b0}} ;
         active <= 1'b0 ;
         clr_q  <= shield_dst_i ;              // fin del holdoff -> re-arm dest
      end else begin
         cnt <= cnt - 1'b1 ;
      end
   end
end

// Canales escudados: manda el pulso del escudo (ignora el clear de SW durante
// el holdoff). Canales no escudados: transparentes al clear de SW.
genvar GV;
generate
for (GV = 0; GV < N; GV = GV + 1) begin : g_shield_mux
   assign trig_dis_clr_o[GV] = shield_dst_i[GV] ? clr_q[GV]
                                                : sw_trig_dis_clr_i[GV];
end
endgenerate

// Estado interno para debug
assign cnt_o    = cnt    ;
assign active_o = active ;

endmodule
