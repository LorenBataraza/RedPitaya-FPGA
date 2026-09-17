
// Módulo que toma configuración como parámetros.
// La salida se la conecta al trig_dis_clr_i del multitrigger_trig_src.
//
//   Cantidad de canales:  parameter integer N          = 4
//   Duración del holdoff: parameter integer DURATION_W = 16
//   Shield src  vector de N_SRC (qué fuentes actúan de disparo del escudo)
//   Shield dest vector de N_DST (qué destinos quedan escudados)
//
// Holdoff src->dest: cuando una fuente "src" dispara, los canales "dest" quedan
// deshabilitados durante DURATION ciclos de ADC; al expirar se emite un pulso
// de trig_dis_clr que los re-arma. Los canales no escudados siguen de forma
// transparente al clear de SW.
//
// FUENTES Y DESTINOS NO SON LO MISMO. Los N primeros bits de cada vector son los
// canales del scope, como siempre. Por encima:
//
//   src[N+0]  ext_p    flanco de subida de la entrada externa (DIO0_P)
//   src[N+1]  ext_n    flanco de bajada
//   src[N+2]  ext_lvl  NIVEL de la entrada externa, sincronizado
//   dst[N]    mca      el analizador multicanal, como VETO
//
// Con `ext_lvl` como fuente el escudo "dispara" cada ciclo que la línea está
// alta, y como cada disparo recarga el contador, el veto queda activo mientras
// dura la línea y DURATION ciclos más: un veto de nivel con cola programable.
// Con `ext_p` da una ventana de DURATION ciclos tras el flanco. Las dos cosas
// salen del mismo contador; lo que cambia es qué bit de src se habilita.
//
// El veto al MCA es un NIVEL, no un pulso de re-arm: vale mientras alguna
// fuente dispara o el holdoff está corriendo. Va registrado porque termina en
// la lógica de apertura de pulso del MCA y no hace falta que sea inmediato.

module trigger_shield #(
  parameter integer N          = 4,    // canales del scope
  parameter integer DURATION_W = 16,   // ancho del contador de holdoff
  parameter integer N_SRC      = N + 3,// canales + {ext_p, ext_n, ext_lvl}
  parameter integer N_DST      = N + 1 // canales + {mca}
)(
  input                      clk_i             ,
  input                      rstn_i            , // reset síncrono activo-bajo
  input  [N_SRC-1:0]         trig_event_i      , // disparo por fuente
  input  [N_SRC-1:0]         shield_src_i      , // fuentes del escudo
  input  [N_DST-1:0]         shield_dst_i      , // destinos escudados
  input  [DURATION_W-1:0]    shield_dur_i      , // duración del holdoff (ciclos ADC)
  input  [N-1:0]             sw_trig_dis_clr_i , // clear de SW (rp_scope_cfg, reg 0x94)
  output [N-1:0]             trig_dis_clr_o    , // a multitrigger_trig_src.trig_dis_clr_i
  output reg                 mca_veto_o        , // nivel: el MCA no abre pulsos
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
   cnt        <= {DURATION_W{1'b0}} ;
   active     <= 1'b0 ;
   clr_q      <= {N{1'b0}} ;
   mca_veto_o <= 1'b0 ;
end else begin
   clr_q <= {N{1'b0}} ;                       // por defecto sin pulso
   if (src_fire) begin
      cnt    <= shield_dur_i ;
      active <= (shield_dur_i != {DURATION_W{1'b0}}) ;
      if (shield_dur_i == {DURATION_W{1'b0}})
         clr_q <= shield_dst_i[N-1:0] ;        // dur==0 -> re-arm inmediato
   end else if (active) begin
      if (cnt <= {{(DURATION_W-1){1'b0}}, 1'b1}) begin
         cnt    <= {DURATION_W{1'b0}} ;
         active <= 1'b0 ;
         clr_q  <= shield_dst_i[N-1:0] ;       // fin del holdoff -> re-arm dest
      end else begin
         cnt <= cnt - 1'b1 ;
      end
   end
   // Veto: mientras dispara una fuente o corre el holdoff. Con dur==0 y una
   // fuente de nivel, es exactamente el nivel (sincronizado).
   mca_veto_o <= shield_dst_i[N] & (src_fire | active) ;
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
