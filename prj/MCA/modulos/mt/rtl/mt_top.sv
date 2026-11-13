`timescale 1ns/1ps
//=============================================================================
// mt_top — el MULTITRIGGER entero: un solo bloque con un solo borde
//
// Hasta acá el multitrigger no era un módulo sino una "región": sus piezas se
// instanciaban sueltas dentro de rp_scope_mt_com (mt_event_logic y mt_cfg en
// el nivel de arriba, mt_slope_trig y rp_adc_trig dentro del generate por
// canal, más el sync del nivel externo y el empaquetado de trg_state). Lo único
// que lo delimitaba era su mapa de registros (slot 3). Este módulo junta todo
// eso detrás de un borde, con la misma interfaz que ya describía la tabla de
// puertos de docs/mt/register_map_mt.md.
//
//   tap MTRG ──→ rp_adc_trig ×N_CH  (nivel) ─┐
//            ├─→ mt_slope_trig ×N_CH (pend.) ─┤
//            └─→ mt_pz_trig ×N_CH (polo-cero) ┤
//   trig_ext ──→ rp_ext_trig ──→ (afuera y vuelve por trig_ext_asg_i)
//            └─→ sync 2 FF (nivel, veto) ─────┼─→ mt_event_logic ──→ trigger_event
//   trig_ch_i ────────────────────────────────┘          ↑
//   sys_bus slot 3 ──→ mt_cfg ── máscaras, escudo, pendiente, polo-cero, pulsos
//
// mt_pz_trig (el disparo con polo-cero) se agregó después de la mudanza: es una
// fuente nueva en los bits 25..28 de la máscara, no un cambio de las de antes.
//
// ES UNA MUDANZA, NO UN CAMBIO DE LÓGICA. Cada instancia es la que estaba en
// rp_scope_mt_com, con los mismos parámetros y las mismas conexiones; los
// relojes por canal se conservan (rp_adc_trig y mt_slope_trig corren con
// adc_clk_i[GV], el resto con adc_clk_i[0]). El netlist sólo cambia de nombres
// jerárquicos.
//
// Lo que cruza el borde:
//
// - El TAP (mtrg_dat_i/mtrg_val_i) lo elige afuera el dsp_tap_mux MTRG: el
//   ruteo es de la cadena del scope, no del multitrigger.
// - La configuración del disparo de NIVEL y del debounce externo (set_tresh,
//   set_hyst, set_deb_len) entra desde osc_cfg: son registros del slot 1 que
//   librp conoce, así que no se mudan. Mismo criterio que el puente legacy.
// - El LAZO CON LA CAPTURA. trigger_event sale hacia rp_bram_sm/rp_axi_sm, y
//   vuelve el control de la captura (adc_dly_do, adc_rst_do, we_keep,
//   dly_valp). trig_dis_clr, trg_src y new_trg_src salen porque rp_bram_sm y
//   rp_delay también los usan.
// - rp_ext_trig saca sus flancos por trig_ext_asg_o y el multitrigger los
//   toma de trig_ext_asg_i: el top los une, para poder compartirlos entre
//   varios scopes. Se respeta ese lazo tal cual.
//=============================================================================

module mt_top #(
  parameter integer N_CH = 2 ,  // canales
  parameter integer DW   = 14   // ancho de la muestra
)(
  input      [N_CH   -1: 0] adc_clk_i            ,
  input      [N_CH   -1: 0] adc_rstn_i           ,

  // --- tap MTRG, uno por canal (desde el dsp_tap_mux) ---
  input      [N_CH*DW-1: 0] mtrg_dat_i           ,
  input      [N_CH   -1: 0] mtrg_val_i           ,

  // --- config del slot 1 (osc_cfg) ---
  input      [   4*DW-1: 0] set_tresh_i          ,  // umbral del disparo de nivel
  input      [   4*DW-1: 0] set_hyst_i           ,  // histéresis del disparo de nivel
  input      [     20-1: 0] set_deb_len_i        ,  // debounce de la entrada externa
  input      [      4-1: 0] indep_mode_i         ,
  input      [      4-1: 0] legacy_trig_sw_i     ,  // puente legacy: 0x004 del slot 1
  input      [      4-1: 0] legacy_trig_dis_clr_i,  // puente legacy: 0x094 del slot 1

  // --- control de la captura (osc_cfg, rp_bram_sm, rp_delay) ---
  input      [      4-1: 0] adc_rst_do_i         ,
  input      [      4-1: 0] adc_dly_do_i         ,
  input      [      4-1: 0] adc_we_keep_i        ,
  input      [      4-1: 0] dly_valp_i           ,

  // --- fuentes externas ---
  input                     trig_ext_i           ,  // DIO0_P
  input                     trig_asg_i           ,  // ASG
  output     [      4-1: 0] trig_ext_asg_o       ,  // {asg_n, asg_p, ext_n, ext_p}
  input      [      4-1: 0] trig_ext_asg_i       ,  // los mismos, de vuelta del top
  input      [      4-1: 0] trig_ch_i            ,  // cadena desde el otro scope
  output     [      4-1: 0] trig_ch_o            ,  // cadena hacia el otro scope

  // --- el evento y lo que se cuelga de él ---
  output                    trigger_event_o      ,  // dispara la captura de todos los canales
  output                    daisy_trig_o         ,
  output                    mca_veto_o           ,
  // nivel: algún canal puede disparar ya (ningún Schmitt habilitado esperando
  // re-armar, sin disable). El MCA lo usa para su tiempo de re-armado.
  output                    trig_arm_o           ,
  output     [     17-1: 0] event_snap_o         ,  // snapshot hacia el event_ring

  // --- hacia la captura del scope ---
  output     [      4-1: 0] trig_dis_clr_o       ,  // rp_bram_sm
  output     [   4*32-1: 0] trg_src_o            ,  // rp_delay (hint de categoría)
  output     [      4-1: 0] new_trg_src_o        ,  // rp_delay
  output     [    4*8-1: 0] trg_state_o          ,  // máscara activa, 8 b/canal (readback)

  // --- bus de sistema del slot 3 (0x4030_0000) ---
  input      [     32-1: 0] sys_addr             ,
  input      [     32-1: 0] sys_wdata            ,
  input                     sys_wen              ,
  input                     sys_ren              ,
  output     [     32-1: 0] sys_rdata            ,
  output                    sys_err              ,
  output                    sys_ack
);

// multitrigger: config del trigger_shield (desde mt_cfg). Fuentes:
// 4 canales + {ext_p, ext_n, ext_lvl}; destinos: 4 canales + {mca}.
wire [       7-1: 0] shield_src        ;
wire [       5-1: 0] shield_dst        ;
wire [      16-1: 0] shield_dur        ;

// multitrigger: config del disparo por pendiente (desde mt_cfg), por canal.
localparam integer SLOPE_LW = 5;
localparam integer SLOPE_GW = 5;
localparam integer SLOPE_TW = DW + 4;   // = SW-1 de mt_slope_trig con LMAX=16
wire [       4-1: 0] slope_en          ;
wire [4*SLOPE_LW-1:0] slope_len        ;
wire [4*SLOPE_GW-1:0] slope_gap        ;
wire [4*SLOPE_TW-1:0] slope_thr        ;
wire [4*SLOPE_TW-1:0] slope_hyst       ;

// multitrigger: config del disparo con polo-cero (desde mt_cfg), por canal.
localparam integer PZ_KW  = 5;
localparam integer PZ_MW  = 20;
localparam integer PZ_TW  = 18;
wire [       4-1: 0] pz_en             ;
wire [4*PZ_KW-1: 0]  pz_k              ;
wire [4*PZ_KW-1: 0]  pz_m              ;
wire [   4*6-1: 0]   pz_sh             ;
wire [4*PZ_MW-1: 0]  pz_mq             ;
wire [4*PZ_TW-1: 0]  pz_thr            ;
wire [4*PZ_TW-1: 0]  pz_hyst           ;

// Fuentes de disparo por canal, rellenas con ceros hasta 4.
wire [       4-1: 0] adc_trig_p        ; // flanco positivo de nivel
wire [       4-1: 0] adc_trig_n        ; // flanco negativo de nivel
wire [       4-1: 0] slope_p           ; // pendiente positiva (mt_slope_trig)
wire [       4-1: 0] slope_n           ; // pendiente negativa
wire [       4-1: 0] pz_p              ; // polo-cero (mt_pz_trig)
wire [       4-1: 0] slope_arm_p       ; // estado de re-armado de cada Schmitt
wire [       4-1: 0] slope_arm_n       ;
wire [       4-1: 0] pz_arm            ;
wire [       4-1: 0] adc_trig_sw       ; // SW

// estado de trigger del event_logic: solo la máscara activa set_trig_src[31:0]
// por canal (32 b cada uno). El bit adc_trg_dis sale por puerto aparte.
wire [N_CH*32-1: 0]  ev_trg_state      ;
wire [      4-1: 0]  ev_adc_trg_dis    ; // dis por canal (padded por el event_logic)

// debug: estado del shield, snapshot (la máscara configurada se lee desde el
// cfg-stored, no de aquí)
wire [     16-1: 0]  shield_cnt        ;
wire                 shield_active     ;
wire [     29-1: 0]  trig_snapshot     ;

// NIVEL de la entrada externa, sincronizado a adc_clk para usarlo como fuente
// de veto. rp_ext_trig ya sincroniza y rebota la misma linea, pero solo saca
// los flancos; el nivel rebotado no es puerto suyo y es RTL del repo raiz, asi
// que se sincroniza aca aparte (dos flops). Un veto es un nivel largo: un
// ciclo de mas o de menos en el borde no importa.
reg  [2-1:0] ext_lvl_sync;
always @(posedge adc_clk_i[0])
  if (!adc_rstn_i[0]) ext_lvl_sync <= 2'b00;
  else                ext_lvl_sync <= {ext_lvl_sync[0], trig_ext_i};
wire ext_lvl = ext_lvl_sync[1];

//---------------------------------------------------------------------------
// Cálculo de disparos por canal: nivel (Schmitt) y pendiente (trapezoidal),
// los dos sobre el mismo tap.
//---------------------------------------------------------------------------
genvar GV;
generate
for (GV = 0 ; GV < N_CH ; GV = GV + 1) begin : g_ch

// Este módulo convierte los datos del adc en las senales de trigger a partir
// de un disparador smith
rp_adc_trig #(
  .DW  (  DW     )
) i_adc_trig (
  .adc_clk_i      ( adc_clk_i[GV]                     ),
  .adc_rstn_i     ( adc_rstn_i[GV]                    ),
  .adc_dat_i      ( mtrg_dat_i[(GV+1)*DW-1:GV*DW]     ),
  .adc_dv_i       ( mtrg_val_i[GV]                    ),
  .set_tresh_i    ( set_tresh_i[(GV+1)*DW-1:GV*DW]    ),
  .set_hyst_i     ( set_hyst_i[(GV+1)*DW-1:GV*DW]     ),
  .adc_trig_p_o   ( adc_trig_p[GV]                    ),
  .adc_trig_n_o   ( adc_trig_n[GV]                    )
);

// Disparo por PENDIENTE: trapezoidal rápido sobre el mismo tap que el Schmitt
// de nivel. Ver mt_slope_trig.sv.
mt_slope_trig #(
  .DW   ( DW       ),
  .LMAX ( 16       ),
  .GMAX ( 31       ),
  .LW   ( SLOPE_LW ),
  .GW   ( SLOPE_GW )
) i_slope_trig (
  .adc_clk_i      ( adc_clk_i[GV]                           ),
  .adc_rstn_i     ( adc_rstn_i[GV]                          ),
  .adc_dat_i      ( mtrg_dat_i[(GV+1)*DW-1:GV*DW]           ),
  .adc_dv_i       ( mtrg_val_i[GV]                          ),
  .cfg_en_i       ( slope_en[GV]                            ),
  .cfg_len_i      ( slope_len [GV*SLOPE_LW +: SLOPE_LW]     ),
  .cfg_gap_i      ( slope_gap [GV*SLOPE_GW +: SLOPE_GW]     ),
  .cfg_thr_i      ( slope_thr [GV*SLOPE_TW +: SLOPE_TW]     ),
  .cfg_hyst_i     ( slope_hyst[GV*SLOPE_TW +: SLOPE_TW]     ),
  .slope_p_o      ( slope_p[GV]                             ),
  .slope_n_o      ( slope_n[GV]                             ),
  .armado_p_o     ( slope_arm_p[GV]                         ),
  .armado_n_o     ( slope_arm_n[GV]                         )
);

// Disparo con POLO-CERO: un trapecio corto (mca_trap) y un Schmitt, sobre el
// mismo tap. Ver mt_pz_trig.sv.
mt_pz_trig #(
  .DW   ( DW    ),
  .DAW  ( 5     ),
  .KW   ( PZ_KW ),
  .MW   ( PZ_MW ),
  .TW   ( PZ_TW )
) i_pz_trig (
  .adc_clk_i      ( adc_clk_i[GV]                           ),
  .adc_rstn_i     ( adc_rstn_i[GV]                          ),
  .adc_dat_i      ( mtrg_dat_i[(GV+1)*DW-1:GV*DW]           ),
  .adc_dv_i       ( mtrg_val_i[GV]                          ),
  .cfg_en_i       ( pz_en[GV]                               ),
  .cfg_k_i        ( pz_k   [GV*PZ_KW +: PZ_KW]              ),
  .cfg_m_i        ( pz_m   [GV*PZ_KW +: PZ_KW]              ),
  .cfg_mq_i       ( pz_mq  [GV*PZ_MW +: PZ_MW]              ),
  .cfg_sh_i       ( pz_sh  [GV*6 +: 6]                      ),
  .cfg_thr_i      ( pz_thr [GV*PZ_TW +: PZ_TW]              ),
  .cfg_hyst_i     ( pz_hyst[GV*PZ_TW +: PZ_TW]              ),
  .pz_p_o         ( pz_p[GV]                                ),
  .armado_o       ( pz_arm[GV]                              )
);

// Empaqueta el estado por canal en el bus trg_state de 8 b/canal: los 8 bits
// bajos de la máscara activa (set_trig_src). El bit adc_trg_dis sale por su
// propia vía (ev_adc_trg_dis → DIS_FLAGS @0x01C de mt_cfg). La máscara completa
// configurada se lee desde la copia de mt_cfg en 0x040+4*ch, no de aquí.
assign trg_state_o[(GV+1)*8-1:GV*8] = ev_trg_state[GV*32 +: 8];

end

// Rellena los canales que no existen.
for (GV = N_CH ; GV < 4 ; GV = GV + 1) begin : g_pad
assign adc_trig_p[GV]               = 1'b0;
assign adc_trig_n[GV]               = 1'b0;
assign slope_p[GV]                  = 1'b0;
assign slope_n[GV]                  = 1'b0;
assign pz_p[GV]                     = 1'b0;
assign slope_arm_p[GV]              = 1'b0;   // un canal que no existe no dispara
assign slope_arm_n[GV]              = 1'b0;
assign pz_arm[GV]                   = 1'b0;
assign trg_state_o[(GV+1)*8-1:GV*8] = 8'h0;
end
endgenerate

//---------------------------------------------------------------------------
// Entrada externa y ASG: debounce y flancos. Salen al top y vuelven por
// trig_ext_asg_i (ver la cabecera).
//---------------------------------------------------------------------------
wire ext_trig_p, ext_trig_n, asg_trig_p, asg_trig_n;

rp_ext_trig #(
  .DW  (  DW     )
) i_ext_trig (
  .adc_clk_i      ( adc_clk_i[0]    ),
  .adc_rstn_i     ( adc_rstn_i[0]   ),
  .trig_asg_i     ( trig_asg_i      ),
  .trig_ext_i     ( trig_ext_i      ),
  .set_deb_len_i  ( set_deb_len_i   ),
  .ext_trig_p_o   ( ext_trig_p      ),
  .ext_trig_n_o   ( ext_trig_n      ),
  .asg_trig_p_o   ( asg_trig_p      ),
  .asg_trig_n_o   ( asg_trig_n      )
);

assign trig_ext_asg_o = {asg_trig_n, asg_trig_p, ext_trig_n, ext_trig_p};

//---------------------------------------------------------------------------
// Lógica de evento conjunta: N mt_trig_src + trigger_shield.
//---------------------------------------------------------------------------
mt_event_logic #(
  .N_CH       ( N_CH ),
  .DW         ( DW   ),
  .SRC_W      ( 32   ),
  .SHIELD_N   ( 4    ),
  .DURATION_W ( 16   )
) i_event_logic (
  .adc_clk_i        ( adc_clk_i[0]        ),
  .adc_rstn_i       ( adc_rstn_i[0]       ),

  .adc_rst_do_i     ( adc_rst_do_i        ),
  .adc_dly_do_i     ( |adc_dly_do_i       ),
  .sw_trig_dis_clr_i( trig_dis_clr_o      ),
  .adc_we_keep_i    ( adc_we_keep_i       ),

  .set_trg_src_i    ( trg_src_o[N_CH*32-1:0] ),
  .set_trg_new_i    ( new_trg_src_o       ),
  .dly_valp_i       ( dly_valp_i          ),

  .adc_trig_sw_i    ( adc_trig_sw         ),
  .adc_trig_p_i     ( adc_trig_p          ),
  .adc_trig_n_i     ( adc_trig_n          ),
  .ext_trig_p_i     ( trig_ext_asg_i[0]   ),
  .ext_trig_n_i     ( trig_ext_asg_i[1]   ),
  .asg_trig_p_i     ( trig_ext_asg_i[2]   ),
  .asg_trig_n_i     ( trig_ext_asg_i[3]   ),
  .ext_lvl_i        ( ext_lvl             ),
  .trig_ch_i        ( trig_ch_i           ),
  .slope_p_i        ( slope_p             ),
  .slope_n_i        ( slope_n             ),
  .pz_p_i           ( pz_p                ),
  .slope_arm_p_i    ( slope_arm_p         ),
  .slope_arm_n_i    ( slope_arm_n         ),
  .pz_arm_i         ( pz_arm              ),

  .shield_src_i     ( shield_src          ),
  .shield_dst_i     ( shield_dst          ),
  .shield_dur_i     ( shield_dur          ),

  .trig_ch_o        ( trig_ch_o           ),
  .trg_state_o      ( ev_trg_state        ),
  .adc_trg_dis_o    ( ev_adc_trg_dis      ),
  .daisy_trig_o     ( daisy_trig_o        ),
  .event_arm_o      (                     ),  // redundante con trigger_event_o
  .trigger_event_o  ( trigger_event_o     ),
  .mca_veto_o       ( mca_veto_o          ),
  .trig_arm_o       ( trig_arm_o          ),

  // Debug
  .shield_cnt_o     ( shield_cnt          ),
  .shield_active_o  ( shield_active       ),
  .trig_snapshot_o  ( trig_snapshot       )
);

// El event ring guarda 17 bits por slot: las fuentes de pendiente (bits
// 17..24) y de polo-cero (25..28) solo se ven en el registro SNAPSHOT de mt_cfg.
assign event_snap_o = trig_snapshot[16:0];

//---------------------------------------------------------------------------
// Registros del slot 3.
//---------------------------------------------------------------------------
mt_cfg #(
  .N_CH     ( N_CH     ),
  .SRC_W    ( 32       ),
  .SHIELD_N ( 4        ),
  .SLOPE_LW ( SLOPE_LW ),
  .SLOPE_GW ( SLOPE_GW ),
  .SLOPE_TW ( SLOPE_TW ),
  .PZ_KW    ( PZ_KW    ),
  .PZ_MW    ( PZ_MW    ),
  .PZ_TW    ( PZ_TW    )
) i_mtrg_cfg (
  .adc_clk_i          ( adc_clk_i[0]    ),
  .adc_rstn_i         ( adc_rstn_i[0]   ),

  .sys_addr           ( sys_addr        ),
  .sys_wdata          ( sys_wdata       ),
  .sys_wen            ( sys_wen         ),
  .sys_ren            ( sys_ren         ),
  .sys_rdata          ( sys_rdata       ),
  .sys_err            ( sys_err         ),
  .sys_ack            ( sys_ack         ),

  .trg_state_i        ( trg_state_o     ),
  .adc_trg_dis_act_i  ( ev_adc_trg_dis  ),
  .adc_we_keep_i      ( adc_we_keep_i   ),
  .indep_mode_i       ( indep_mode_i    ),
  .shield_cnt_i       ( shield_cnt      ),
  .shield_active_i    ( shield_active   ),
  .mca_veto_i         ( mca_veto_o      ),
  .trig_arm_i         ( trig_arm_o      ),
  .trig_snapshot_i    ( trig_snapshot   ),

  .legacy_trig_sw_i      ( legacy_trig_sw_i      ),
  .legacy_trig_dis_clr_i ( legacy_trig_dis_clr_i ),

  .adc_trig_sw_o      ( adc_trig_sw     ),
  .trig_dis_clr_o     ( trig_dis_clr_o  ),
  .new_trg_src_o      ( new_trg_src_o   ),
  .trg_src_o          ( trg_src_o       ),
  .shield_src_o       ( shield_src      ),
  .shield_dst_o       ( shield_dst      ),
  .shield_dur_o       ( shield_dur      ),

  .slope_en_o         ( slope_en        ),
  .slope_len_o        ( slope_len       ),
  .slope_gap_o        ( slope_gap       ),
  .slope_thr_o        ( slope_thr       ),
  .slope_hyst_o       ( slope_hyst      ),

  .pz_en_o            ( pz_en           ),
  .pz_k_o             ( pz_k            ),
  .pz_m_o             ( pz_m            ),
  .pz_sh_o            ( pz_sh           ),
  .pz_mq_o            ( pz_mq           ),
  .pz_thr_o           ( pz_thr          ),
  .pz_hyst_o          ( pz_hyst         )
);

endmodule
