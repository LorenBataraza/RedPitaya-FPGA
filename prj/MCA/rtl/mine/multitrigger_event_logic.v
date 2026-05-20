// Este módulo tiene la tarea de dar la salida de eventos.
// Une el trigger_shield (que afecta el disable de los multitrigger_trig_src)
// con N_CH instancias de multitrigger_trig_src y sus conexiones de cadena.
//
// Trabaja con N_CH canales: instancia un multitrigger_trig_src por canal y
// produce un evento conjunto = OR de todas las salidas de trigger.

module multitrigger_event_logic #(
  parameter integer N_CH       = 2,    // Number of Channels
  parameter integer DW         = 14,   // Data Width
  parameter integer SRC_W      = 32,   // Ancho de la máscara de fuentes
  parameter integer SHIELD_N   = 4,    // Canales del trigger_shield
  parameter integer DURATION_W = 16    // Ancho del contador de holdoff
)(
  // ADC
  input                          adc_clk_i        ,  // ADC clock
  input                          adc_rstn_i       ,  // ADC reset - active low

  // Control / config (de rp_scope_cfg vía scope_com)
  input  [        4-1: 0]        adc_rst_do_i     ,
  input                          adc_dly_do_i     ,
  input  [        4-1: 0]        sw_trig_dis_clr_i,  // clear de SW (reg 0x94)
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
  input  [        4-1: 0]        trig_ch_i        ,  // cadena desde el otro scope

  // Shield config
  input  [ SHIELD_N-1: 0]        shield_src_i     ,
  input  [ SHIELD_N-1: 0]        shield_dst_i     ,
  input  [DURATION_W-1: 0]       shield_dur_i     ,

  // Salidas
  output [        4-1: 0]        trig_ch_o        ,  // cadena hacia el otro scope
  output [N_CH*(SRC_W+1)-1: 0]   trg_state_o      ,
  output                         daisy_trig_o     ,
  output                         event_arm_o      ,
  output                         trigger_event_o  ,  // evento conjunto -> bram_sm/axi_sm

  // Debug
  output [DURATION_W-1: 0]       shield_cnt_o     ,  // contador del shield
  output                         shield_active_o  ,  // shield en holdoff
  output [       17-1: 0]        trig_snapshot_o     // sticky: qué disparó el último evento
);

wire [ 4-1: 0] adc_trig    ;  // trigger por canal
wire [ 4-1: 0] trig_dis_clr;  // clear (escudo) por canal

// El escudo afecta el disable de cada multitrigger_trig_src.
trigger_shield #(
  .N          ( SHIELD_N   ),
  .DURATION_W ( DURATION_W )
) i_shield (
  .clk_i             ( adc_clk_i         ),
  .rstn_i            ( adc_rstn_i        ),
  .trig_event_i      ( adc_trig          ),
  .shield_src_i      ( shield_src_i      ),
  .shield_dst_i      ( shield_dst_i      ),
  .shield_dur_i      ( shield_dur_i      ),
  .sw_trig_dis_clr_i ( sw_trig_dis_clr_i ),
  .trig_dis_clr_o    ( trig_dis_clr      ),
  .cnt_o             ( shield_cnt_o      ),
  .active_o          ( shield_active_o   )
);

// Una instancia de multitrigger_trig_src por canal de datos.
genvar GV;
generate
for (GV = 0; GV < N_CH; GV = GV + 1) begin : g_trig_src
multitrigger_trig_src #(
  .CHN   ( GV    ),
  .SRC_W ( SRC_W )
) i_trig_src (
  .adc_clk_i      ( adc_clk_i                                  ),
  .adc_rstn_i     ( adc_rstn_i                                 ),

  .adc_rst_do_i   ( adc_rst_do_i[GV]                           ),
  .adc_dly_do_i   ( adc_dly_do_i                               ),
  .trig_dis_clr_i ( trig_dis_clr[GV]                           ),

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

  .trg_state_o    ( trg_state_o[(GV+1)*(SRC_W+1)-1:GV*(SRC_W+1)] ),
  .adc_trig_o     ( adc_trig[GV]                               )
);
end
endgenerate

// Rellena los canales no usados con ceros (mismo patrón que el scope_com).
genvar GM;
generate
for (GM = N_CH; GM < 4; GM = GM + 1) begin : g_pad
   assign adc_trig[GM] = 1'b0;
end
endgenerate

// Un OR entre todas las fuentes (los canales no usados están en 0).
wire event_signal = |adc_trig;

assign trigger_event_o = event_signal;
assign event_arm_o     = event_signal;
assign daisy_trig_o    = event_signal;

// Cadena entre scopes: mismo formato que rp_scope_com.v
assign trig_ch_o = {adc_trig_n_i[1], adc_trig_p_i[1],
                    adc_trig_n_i[0], adc_trig_p_i[0]};

// Snapshot sticky de las fuentes activas en el momento del último trigger_event.
// 17 bits: {trig_ch[3:0], asg_n, asg_p, ext_n, ext_p, adc_n[3:0], adc_p[3:0], sw_any}
// src_now se retrasa 1 ciclo para alinear con el pipeline de multitrigger_trig_src
// (trig_comb combinacional → adc_trig registrado → event_signal).
reg  [17-1: 0] src_now_d ;
reg  [17-1: 0] trig_snapshot;
wire [17-1: 0] src_now = {trig_ch_i,
                          asg_trig_n_i, asg_trig_p_i,
                          ext_trig_n_i, ext_trig_p_i,
                          adc_trig_n_i, adc_trig_p_i,
                          |adc_trig_sw_i};

always @(posedge adc_clk_i)
   src_now_d <= src_now ;

always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0)
   trig_snapshot <= 17'h0 ;
else if (|adc_rst_do_i)
   trig_snapshot <= 17'h0 ;
else if (|sw_trig_dis_clr_i)
   trig_snapshot <= 17'h0 ;
else if (event_signal)
   trig_snapshot <= src_now_d ;

assign trig_snapshot_o = trig_snapshot;

endmodule
