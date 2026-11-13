// Este módulo tiene la tarea de dar la salida de eventos.
// Une el trigger_shield (que afecta el disable de los mt_trig_src)
// con N_CH instancias de mt_trig_src y sus conexiones de cadena.
//
// Trabaja con N_CH canales: instancia un mt_trig_src por canal y
// produce un evento conjunto = OR de todas las salidas de trigger.

module mt_event_logic #(
  parameter integer N_CH       = 2,    // Number of Channels
  parameter integer DW         = 14,   // Data Width
  parameter integer SRC_W      = 32,   // Ancho de la máscara de fuentes
  parameter integer SHIELD_N   = 4,    // Canales del trigger_shield
  parameter integer DURATION_W = 16,   // Ancho del contador de holdoff
  // Fuentes y destinos del escudo: canales + {ext_p, ext_n, ext_lvl} y
  // canales + {mca}. Ver trigger_shield.sv.
  parameter integer SHIELD_SRC = SHIELD_N + 3,
  parameter integer SHIELD_DST = SHIELD_N + 1
)(
  // ADC
  input                          adc_clk_i        ,  // ADC clock
  input                          adc_rstn_i       ,  // ADC reset - active low

  // Control / config (de rp_scope_cfg vía scope_com)
  input  [        4-1: 0]        adc_rst_do_i     ,
  input                          adc_dly_do_i     ,
  input  [        4-1: 0]        sw_trig_dis_clr_i,  // clear de SW (reg 0x94)
  input  [        4-1: 0]        adc_we_keep_i    ,  // modo continuo por canal (0x00 bit3)
  input  [ N_CH*SRC_W-1: 0]      set_trg_src_i    ,  // máscara de fuentes por canal
  input  [        4-1: 0]        set_trg_new_i    ,
  input  [        4-1: 0]        dly_valp_i       ,

  // Fuentes de trigger
  input  [        4-1: 0]        adc_trig_sw_i    ,
  input  [        4-1: 0]        adc_trig_p_i     ,
  input  [        4-1: 0]        adc_trig_n_i     ,
  input                          ext_trig_p_i     ,
  input                          ext_trig_n_i     ,
  input                          asg_trig_p_i     ,
  input                          asg_trig_n_i     ,
  input                          ext_lvl_i        ,  // NIVEL externo sincronizado (veto)
  input  [        4-1: 0]        trig_ch_i        ,  // cadena desde el otro scope
  input  [        4-1: 0]        slope_p_i        ,  // pendiente positiva por canal
  input  [        4-1: 0]        slope_n_i        ,  // pendiente negativa por canal
  input  [        4-1: 0]        pz_p_i           ,  // polo-cero por canal
  // Estado de re-armado de los Schmitt, por canal: 1 = el próximo cruce dispara
  input  [        4-1: 0]        slope_arm_p_i    ,
  input  [        4-1: 0]        slope_arm_n_i    ,
  input  [        4-1: 0]        pz_arm_i         ,

  // Shield config - Control Signals
  input  [SHIELD_SRC-1: 0]       shield_src_i     ,
  input  [SHIELD_DST-1: 0]       shield_dst_i     ,
  input  [DURATION_W-1: 0]       shield_dur_i     ,

  // Salidas
  output [        4-1: 0]        trig_ch_o        ,  // cadena hacia el otro scope
  output [N_CH*SRC_W-1: 0]       trg_state_o      ,  // máscara activa por canal (32 b/ch)
  output [        4-1: 0]        adc_trg_dis_o    ,  // bit de disable por canal (padded)
  output                         daisy_trig_o     ,
  output                         event_arm_o      ,
  output                         trigger_event_o  ,  // evento conjunto -> bram_sm/axi_sm
  output                         mca_veto_o       ,  // nivel: el MCA no abre pulsos
  output reg                     trig_arm_o       ,  // nivel: algún canal puede disparar

  // State
  output [DURATION_W-1: 0]       shield_cnt_o     ,  // contador del shield
  output                         shield_active_o  ,  // shield en holdoff
  output [       29-1: 0]        trig_snapshot_o     // sticky: qué disparó el último evento
);

wire [ 4-1: 0] adc_trig    ;  // trigger por canal
wire [ 4-1: 0] trig_dis_clr;  // clear (escudo) por canal
wire [ 4-1: 0] puede       ;  // el canal puede disparar en este ciclo

// ARMADO POR FUENTE, con los bits de la máscara OR (ver mt_trig_src). Es lo que
// el MCA necesita para su tiempo de re-armado: un pulso que llega con el
// disparo desarmado no genera flanco y el MCA no lo ve, así que lo único que se
// puede medir es CUÁNTO TIEMPO estuvo desarmado.
//   - pendiente y polo-cero: el estado de su Schmitt (0 hasta bajar del re-armado)
//   - nivel (bits 1..8): rp_adc_trig es el de Red Pitaya y no expone su estado,
//     así que cuenta como siempre armado. Para el MCA no se usa.
//   - SW, externo, ASG y cadena: no tienen re-armado propio, siempre armados.
wire [SRC_W-1: 0] armado;
assign armado[16:0]        = {17{1'b1}};
assign armado[20:17]       = slope_arm_p_i;
assign armado[24:21]       = slope_arm_n_i;
assign armado[28:25]       = pz_arm_i;
assign armado[SRC_W-1:29]  = {(SRC_W-29){1'b0}};

// El escudo afecta el disable de cada mt_trig_src, y da el veto al
// MCA. Sus fuentes son los disparos por canal MAS la entrada externa cruda
// (flancos y nivel), para poder escudar/vetar desde afuera sin gastar la
// mascara OR de un canal del scope en eso.
trigger_shield #(
  .N          ( SHIELD_N   ),
  .DURATION_W ( DURATION_W ),
  .N_SRC      ( SHIELD_SRC ),
  .N_DST      ( SHIELD_DST )
) i_shield (
  .clk_i             ( adc_clk_i         ),
  .rstn_i            ( adc_rstn_i        ),
  .trig_event_i      ( {ext_lvl_i, ext_trig_n_i, ext_trig_p_i, adc_trig} ),
  .shield_src_i      ( shield_src_i      ),
  .shield_dst_i      ( shield_dst_i      ),
  .shield_dur_i      ( shield_dur_i      ),
  .sw_trig_dis_clr_i ( sw_trig_dis_clr_i ),
  .trig_dis_clr_o    ( trig_dis_clr      ),
  .mca_veto_o        ( mca_veto_o        ),
  .cnt_o             ( shield_cnt_o      ),
  .active_o          ( shield_active_o   )
);

// Una instancia de mt_trig_src por canal de datos.
genvar GV;
generate
for (GV = 0; GV < N_CH; GV = GV + 1) begin : g_trig_src
mt_trig_src #(
  .CHN   ( GV    ),
  .SRC_W ( SRC_W )
) i_trig_src (
  .adc_clk_i      ( adc_clk_i                                  ),
  .adc_rstn_i     ( adc_rstn_i                                 ),

  .adc_rst_do_i   ( adc_rst_do_i[GV]                           ),
  .adc_dly_do_i   ( adc_dly_do_i                               ),
  .trig_dis_clr_i ( trig_dis_clr[GV]                           ),
  .adc_we_keep_i  ( adc_we_keep_i[GV]                          ),

  .set_trg_src_i  ( set_trg_src_i[(GV+1)*SRC_W-1:GV*SRC_W]     ),
  .set_trg_new_i  ( set_trg_new_i[GV]                          ),
  .dly_valp_i     ( dly_valp_i[GV]                             ),

  .adc_trig_sw_i  ( adc_trig_sw_i[GV]                          ),
  .adc_trig_p_i   ( adc_trig_p_i                               ),
  .adc_trig_n_i   ( adc_trig_n_i                               ),
  .ext_trig_p_i   ( ext_trig_p_i                               ),
  .ext_trig_n_i   ( ext_trig_n_i                               ),
  .asg_trig_p_i   ( asg_trig_p_i                               ),
  .asg_trig_n_i   ( asg_trig_n_i                               ),
  .trig_ch_i      ( trig_ch_i                                  ),
  .slope_p_i      ( slope_p_i                                  ),
  .slope_n_i      ( slope_n_i                                  ),
  .pz_p_i         ( pz_p_i                                     ),
  .armado_i       ( armado                                     ),

  .trg_state_o    ( trg_state_o[(GV+1)*SRC_W-1:GV*SRC_W]       ),
  .adc_trg_dis_o  ( adc_trg_dis_o[GV]                          ),
  .adc_trig_o     ( adc_trig[GV]                               ),
  .puede_o        ( puede[GV]                                  )
);
end
endgenerate

// Rellena los canales no usados con ceros (mismo patrón que el scope_com).
genvar GM;
generate
for (GM = N_CH; GM < 4; GM = GM + 1) begin : g_pad
   assign adc_trig[GM]       = 1'b0;
   assign adc_trg_dis_o[GM]  = 1'b0;
   assign puede[GM]          = 1'b0;
end
endgenerate

// Un OR entre todas las fuentes (los canales no usados están en 0).
wire event_signal = |adc_trig;

// El disparo conjunto puede salir si algún canal puede. Registrado, como
// adc_trig: el estado que lo baja (el Schmitt que sube) es el mismo flanco que
// arma el pulso, así que baja 1 ciclo antes de que el disparo llegue al MCA.
// Es un ciclo por evento sobre un re-armado de decenas: no se compensa.
always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0)
   trig_arm_o <= 1'b0 ;
else
   trig_arm_o <= |puede ;

assign trigger_event_o = event_signal;
assign event_arm_o     = event_signal;
assign daisy_trig_o    = event_signal;

// Cadena entre scopes: mismo formato que rp_scope_com.v
assign trig_ch_o = {adc_trig_n_i[1], adc_trig_p_i[1],
                    adc_trig_n_i[0], adc_trig_p_i[0]};

// Snapshot sticky de las fuentes activas en el momento del último trigger_event.
// 29 bits: {pz_p[3:0], slope_n[3:0], slope_p[3:0],
//            trig_ch[3:0], asg_n, asg_p, ext_n, ext_p, adc_n[3:0], adc_p[3:0], sw_any}
// Los 17 bajos conservan el orden histórico (que NO es el de la máscara OR);
// los 8 de pendiente y los 4 de polo-cero caen en los mismos bits 17..28 que
// en la máscara.
// src_now se retrasa 1 ciclo para alinear con el pipeline de mt_trig_src
// (trig_comb combinacional → adc_trig registrado → event_signal).
reg  [29-1: 0] src_now_d ;
reg  [29-1: 0] trig_snapshot;
wire [29-1: 0] src_now = {pz_p_i, slope_n_i, slope_p_i,
                          trig_ch_i,
                          asg_trig_n_i, asg_trig_p_i,
                          ext_trig_n_i, ext_trig_p_i,
                          adc_trig_n_i, adc_trig_p_i,
                          |adc_trig_sw_i};

always @(posedge adc_clk_i)
   src_now_d <= src_now ;

always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0)
   trig_snapshot <= 29'h0 ;
else if (|adc_rst_do_i)
   trig_snapshot <= 29'h0 ;
else if (|sw_trig_dis_clr_i)
   trig_snapshot <= 29'h0 ;
else if (event_signal)
   trig_snapshot <= src_now_d ;

// Con event_signal arriba sale el valor nuevo: el registro lo toma recién en el flanco
// siguiente, y event_window_capture lee el snapshot en el flanco del trigger. Sin esto,
// cada slot se lleva las fuentes del evento anterior.
assign trig_snapshot_o = event_signal ? src_now_d : trig_snapshot;

endmodule
