/**
 * $Id: red_pitaya_scope.v 965 2014-01-24 13:39:56Z matej.oblak $
 *
 * @brief Red Pitaya oscilloscope application, used for capturing ADC data
 *        into BRAMs, which can be later read by SW.
 *
 * @Author Matej Oblak
 *
 * (c) Red Pitaya  http://www.redpitaya.com
 *
 * This part of code is written in Verilog hardware description language (HDL).
 * Please visit http://en.wikipedia.org/wiki/Verilog
 * for more details on the language used herein.
 */

/**
 * GENERAL DESCRIPTION:
 *
 * This is simple data aquisition module, primerly used for scilloscope 
 * application. It consists from three main parts.
 *
 *
*
 *                /--------\      /--------\      /-----------\            /-----\
 *   ADC CHA ---> | CALIB1 | ---> | DFILT1 | ---> | AVG & DEC | ---------> | BUF | --->  SW
 *                \--------/      \--------/      \-----------/     |      \-----/
 *                                                                  ˇ         ^
 *                                                              /------\      |
 *   ext trigger ---------------------------------------------> | TRIG | -----+
 *                                                              \------/      |
 *                                                                  ^         ˇ
 *                /--------\      /--------\      /-----------\     |      /-----\
 *   ADC CHB ---> | CALIB1 | ---> | DFILT1 | ---> | AVG & DEC | ---------> | BUF | --->  SW
 *                \--------/      \--------/      \-----------/            \-----/ 
 *
 *
 * Input data is optionaly averaged and decimated via average filter.
 *
 * Trigger section makes triggers from input ADC data or external digital 
 * signal. To make trigger from analog signal schmitt trigger is used, external
 * trigger goes first over debouncer, which is separate for pos. and neg. edge.
 *
 * Data capture buffer is realized with BRAM. Writing into ram is done with 
 * arm/trig logic. With adc_arm_do signal (SW) writing is enabled, this is active
 * until trigger arrives and adc_dly_cnt counts to zero. Value adc_wp_trig
 * serves as pointer which shows when trigger arrived. This is used to show
 * pre-trigger data.
 * 
 */
/* 
* May 2025 - Alen Luin
* added calibration at the input from adc
*
* May 2026 - Lorenzo Cabrera
* added multitiger event logic
*/

// Cada uno de estos tiene como entradas dos canales de datos 
module rp_scope_multitrigger_com #(
  // En estos valores se encuentra el modelo de Pitaya empleado
  // 
  parameter CHN  = 0 , // Channel Number
  parameter N_CH = 2 , // Number of Channels
  parameter DW   = 14, // Data Width
  parameter RSZ  = 14, // RAM size 2^RSZ
  // EN_FILT=0 saca el ecualizador osc_filter del camino de datos.
  //
  // El lazo IIR de osc_filter no cierra timing a 125 MHz en el -1: es
  // registro -> multiplicacion -> suma de 48 bits -> registro en UN ciclo,
  // 9.421 ns contra 8 ns de periodo, y son 137 de los 221 endpoints en falla
  // del diseno (con toda la severidad: -1.820 ns contra <=0.2 ns del resto).
  // Se probaron dos reescrituras equivalentes bit a bit y ninguna mejoro:
  // plegar el termino al coeficiente lo lleva a 27 bits y Vivado parte el
  // multiplicador en dos DSP en cascada dentro del lazo (-3.514 ns); y
  // reasociar en dos pasos deja igual un sumador en el lazo (-1.957 ns).
  // Es una limitacion estructural, no de codificacion.
  //
  // El default es 1: red_pitaya_top NO cambia en nada. Solo el top del MCA
  // usa 0, porque para espectroscopia el ecualizador no hace falta (ademas
  // con los coeficientes de reset es un pass-through) y asi ese bitstream
  // queda libre del camino critico.
  parameter EN_FILT = 1
)(
   // ADC
   input      [N_CH   -1: 0] adc_clk_i      ,  // ADC clock
   input      [N_CH   -1: 0] adc_rstn_i     ,  // ADC reset - active low
   input      [N_CH*DW-1: 0] adc_dat_i      ,  // ADC data CHA - Hace mal uso de las dimensiones packed?

   // Muestra acondicionada hacia el MCA: post-calibracion, post-ecualizador
   // (si EN_FILT=1) y PRE-decimacion, a 125 MSPS. Es el mismo nodo que
   // alimenta a rp_decim, asi que los umbrales del MCA y del scope son
   // comparables, pero el MCA lleva su propia decimacion y queda desacoplado
   // del set_dec del scope.
   // En red_pitaya_top estos puertos quedan sin conectar (es legal para
   // salidas) y se podan: el netlist del scope no cambia.
   output     [N_CH*DW-1: 0] mca_dat_o      ,
   output     [N_CH   -1: 0] mca_val_o      ,
   
   // trigger sources - Chain Topology
   input                     trig_ext_i     ,  // external trigger
   
   // Exporto senal de salida 
   output     [      4-1: 0] trig_ch_o      ,  // output trigger to ADC for other 2 channels. Q: por qué 4? Por n y p
   input      [      4-1: 0] trig_ch_i      ,  // input ADC trigger from other 2 channels
   
   input                     trig_asg_i     ,  // ASG trigger
   output     [      4-1: 0] trig_ext_asg_o ,  // output External and ASG trigger to share between multiple scope modules

   input      [      4-1: 0] trig_ext_asg_i ,  // input External and ASG trigger 
   output                    daisy_trig_o   ,  // trigger for daisy chaining
   
   // axi master
   output     [N_CH   -1: 0] axi_clk_o      ,  // global clock
   output     [N_CH   -1: 0] axi_rstn_o     ,  // global reset
   output     [N_CH*32-1: 0] axi_waddr_o    ,  // system write address
   output     [N_CH*64-1: 0] axi_wdata_o    ,  // system write data
   output     [N_CH* 8-1: 0] axi_wsel_o     ,  // system write byte select
   output     [N_CH   -1: 0] axi_wvalid_o   ,  // system write data valid
   output     [N_CH* 4-1: 0] axi_wlen_o     ,  // system write burst length
   output     [N_CH   -1: 0] axi_wfixed_o   ,  // system write burst type (fixed / incremental)
   input      [N_CH   -1: 0] axi_werr_i     ,  // system write error
   input      [N_CH   -1: 0] axi_wrdy_i     ,  // system write ready

   output     [     16-1: 0] adc_state_o    ,
   input      [     16-1: 0] adc_state_i    ,
   output     [     16-1: 0] axi_state_o    ,
   input      [     16-1: 0] axi_state_i    ,

   output     [     16-1: 0] trg_state_o    , // 
   input      [     16-1: 0] trg_state_i    , // Trigger state? Se conecta a la configuración. 

   // System bus
   input      [     32-1: 0] sys_addr       ,  // bus saddress
   input      [     32-1: 0] sys_wdata      ,  // bus write data
   input                     sys_wen        ,  // bus write enable
   input                     sys_ren        ,  // bus read enable
   output     [     32-1: 0] sys_rdata      ,  // bus read data
   output                    sys_err        ,  // bus error indicator
   output                    sys_ack           // bus acknowledge signal
);

wire [    N_CH-1: 0] axi_clk           ;
wire [    N_CH-1: 0] axi_rstn          ;

wire [       4-1: 0] adc_arm_do        ; // Tengo un arm por canal

wire [       4-1: 0] adc_rst_do        ;
wire [       4-1: 0] adc_trig_sw       ; // SW
wire [       4-1: 0] adc_we_keep       ;

wire [       4-1: 0] trig_dis_clr      ;

// multitrigger: config del trigger_shield (desde multitrigger_rp_scope_cfg)
wire [       4-1: 0] shield_src        ;
wire [       4-1: 0] shield_dst        ;
wire [      16-1: 0] shield_dur        ;

// adc_dly_do a nivel módulo (cada rp_bram_sm maneja su bit por canal)
wire [       4-1: 0] adc_dly_do        ;

// estado de trigger del event_logic: solo la máscara activa set_trig_src[31:0]
// por canal (32 b cada uno). El bit adc_trg_dis sale por puerto aparte.
wire [N_CH*32-1: 0]  ev_trg_state      ;
wire [      4-1: 0]  ev_adc_trg_dis    ; // dis por canal (padded por el event_logic)

// debug: adc_trg_dis_act, estado del shield, snapshot (la máscara configurada
// se lee desde el cfg-stored, no de aquí)
wire [      4-1: 0]  adc_trg_dis_act   ;
wire [     16-1: 0]  shield_cnt        ;
wire                 shield_active     ;
wire [     17-1: 0]  trig_snapshot     ;

assign adc_trg_dis_act = ev_adc_trg_dis;

wire [       4-1: 0] axi_en_pulse      ;
wire [       4-1: 0] new_trg_src       ; // Indica cuando el trig_src actualiza la entrada 

wire [   4*32 -1: 0] trg_src           ;  // máscara de fuentes 32b/canal
wire [       4-1: 0] set_dec1          ;
wire [       4-1: 0] filt_rstn         ;
wire [   4*DW -1: 0] set_tresh         ;
wire [   4*32 -1: 0] set_adc_dly       ;
wire [   4*17 -1: 0] set_dec           ;
wire [   4*DW -1: 0] set_hyst          ;
wire [       4-1: 0] set_avg_en        ;
wire [   4*18 -1: 0] set_filt_aa       ;
wire [   4*25 -1: 0] set_filt_bb       ;
wire [   4*25 -1: 0] set_filt_kk       ;
wire [   4*25 -1: 0] set_filt_pp       ;
wire [   4*DW -1: 0] set_calib_offset  ;
wire [   4*16 -1: 0] set_calib_gain    ;
wire [      4 -1: 0] set_filt_byp      ;
wire [      20-1: 0] set_deb_len       ;
wire [   4*32 -1: 0] set_axi_start     ;
wire [   4*32 -1: 0] set_axi_stop      ;
wire [   4*32 -1: 0] set_axi_dly       ;
wire [       4-1: 0] set_axi_en        ;
wire [       4-1: 0] indep_mode        ;

wire [   4*8  -1: 0] axi_state    ;
wire [   4*8  -1: 0] adc_state    ;
wire [   4*8  -1: 0] trg_state    ;

// Write Pointer
wire [   4*RSZ-1: 0] adc_wp_cur   ;
wire [   4*RSZ-1: 0] adc_wp_trig  ;
wire [   4*32 -1: 0] adc_we_cnt   ;
wire [   4*32 -1: 0] axi_wp_cur   ;
wire [   4*32 -1: 0] axi_wp_trig  ;

wire [       4-1: 0] bram_ack     ;
wire [   4*DW -1: 0] bram_rd_dat  ;

// Todas las senales de triggering, siguen siendo útiles
wire [       4-1: 0] adc_trig_p   ; // posedge de canales adc
wire [       4-1: 0] adc_trig_n   ; // nedege del canales adc
wire                 ext_trig_p   ;
wire                 ext_trig_n   ;
wire                 asg_trig_p   ;
wire                 asg_trig_n   ;

wire                 trigger_event; // Nueva senal de disparo conjunta

wire [       4-1: 0] axi_trig     ; // Controlado por la sm del rp_axi
wire                 sys_en       ; 


wire [   4*RSZ-1: 0] adc_wp_act   ;
wire [    4*DW-1: 0] adc_bram_in  ;
wire [       4-1: 0] adc_we       ;
wire [       4-1: 0] adc_dv_del   ;
wire [       4-1: 0] adc_dv_bram  ;
wire [       4-1: 0] adc_dv_del_p ;

assign sys_en = sys_wen | sys_ren;

// Estados de salida
assign adc_state_o = adc_state[15:0]; 
assign axi_state_o = axi_state[15:0];
assign trg_state_o = trg_state[15:0];

// Lógica de evento conjunta: N multitrigger_trig_src + trigger_shield.
multitrigger_event_logic #(
  .N_CH       ( N_CH ),
  .DW         ( DW   ),
  .SRC_W      ( 32   ),
  .SHIELD_N   ( 4    ),
  .DURATION_W ( 16   )
) i_event_logic (
  .adc_clk_i        ( adc_clk_i[0]        ),
  .adc_rstn_i       ( adc_rstn_i[0]       ),

  .adc_rst_do_i     ( adc_rst_do          ),
  .adc_dly_do_i     ( |adc_dly_do         ),
  .sw_trig_dis_clr_i( trig_dis_clr        ),
  .adc_we_keep_i    ( adc_we_keep         ),

  .set_trg_src_i    ( trg_src[N_CH*32-1:0] ),
  .set_trg_new_i    ( new_trg_src         ),
  .dly_valp_i       ( adc_dv_del_p        ),

  .adc_trig_sw_i    ( adc_trig_sw         ),
  .adc_trig_p_i     ( adc_trig_p          ),
  .adc_trig_n_i     ( adc_trig_n          ),
  .ext_trig_p_i     ( trig_ext_asg_i[0]   ),
  .ext_trig_n_i     ( trig_ext_asg_i[1]   ),
  .asg_trig_p_i     ( trig_ext_asg_i[2]   ),
  .asg_trig_n_i     ( trig_ext_asg_i[3]   ),
  .trig_ch_i        ( trig_ch_i           ),

  .shield_src_i     ( shield_src          ),
  .shield_dst_i     ( shield_dst          ),
  .shield_dur_i     ( shield_dur          ),

  .trig_ch_o        ( trig_ch_o           ),
  .trg_state_o      ( ev_trg_state        ),
  .adc_trg_dis_o    ( ev_adc_trg_dis      ),
  .daisy_trig_o     ( daisy_trig_o        ),
  .event_arm_o      (                     ),  // redundante con trigger_event_o
  .trigger_event_o  ( trigger_event       ),

  // Debug
  .shield_cnt_o     ( shield_cnt          ),
  .shield_active_o  ( shield_active       ),
  .trig_snapshot_o  ( trig_snapshot       )
);

// Empaqueta el estado por canal en el bus trg_state de 8 b/canal: los 8 bits
// bajos de la máscara activa (set_trig_src). El bit adc_trg_dis sale por su
// propia vía (ev_adc_trg_dis → adc_trg_dis_act @0x21C). La máscara completa
// configurada se lee desde el cfg-stored en 0x240+4*GA, no de aquí.
genvar GS;
generate
for (GS = 0 ; GS < N_CH ; GS = GS + 1) begin : g_trg_state
  assign trg_state[(GS+1)*8-1:GS*8] = ev_trg_state[GS*32 +: 8];
end
endgenerate


// Vectores empaquetados hacia el MCA. Cada iteracion del generate maneja su
// propia rebanada, asi que hay un unico driver por bit (mismo patron que los
// lazos generate de trg_state y del relleno de canales).
wire [N_CH*DW-1:0] mca_dat;
wire [N_CH   -1:0] mca_val;
assign mca_dat_o = mca_dat;
assign mca_val_o = mca_val;

genvar GV;
generate
for(GV = 0 ; GV < N_CH ; GV = GV + 1) begin
//wire [ DW-1: 0] adc_calib_in  ;
wire [ DW-1: 0] adc_calib_in  ;
wire [ DW-1: 0] adc_calib_out ;
//wire [ DW-1: 0] adc_calib_in  ;
//wire [ DW-1: 0] adc_calib_out ;
wire [ DW-1: 0] adc_filt_in  ;
wire [ DW-1: 0] adc_filtered ;

wire [ DW-1: 0] adc_dec_in   ;
wire [ DW-1: 0] adc_dly_in   ;
wire [ DW-1: 0] axi_ram_in   ;

wire            axi_dv_del;
wire            dec_val;
wire            dec_val_65;
wire            cal_val_65;

//assign adc_calib_in  = adc_dat_i[(GV+1)*DW-1:GV*DW] ;
wire  adc_sign_a = adc_dat_i[(GV+1)*DW-1];
//assign adc_calib_in = {adc_dat_i[(GV+1)*DW-1:GV*DW], {(16-DW){adc_sign_a}}};
assign adc_calib_in  = adc_dat_i[(GV+1)*DW-1:GV*DW] ;

assign cal_val_65 = 1'b1;

rp_scope_calib #(
    .DBITS(DW)
    )
    i_calib_ch(
  .adc_clk_i            ( adc_clk_i[GV] ),  // ADC clock
  .adc_rstn_i           ( adc_rstn_i[GV] ),  // ADC reset - active low

  .calib_dat_i          (adc_calib_in),
  //.calib_din_tvalid_i   (1'b1),
  .calib_din_tvalid_i   (cal_val_65),

  .calib_dat_o          (adc_calib_out),
  .calib_dout_tvalid_o  (),
  .cfg_calib_offset_i   ( set_calib_offset[(GV+1)*DW-1:GV*DW] ),
  .cfg_calib_gain_i     ( set_calib_gain[(GV+1)*16-1:GV*16] )   
);

//assign adc_filt_in = adc_calib_out[16-1:2];
assign adc_filt_in = adc_calib_out;

if (EN_FILT != 0) begin : g_filt

osc_filter #(
    .DW     ( DW )
) i_dfilt1_ch (
   // ADC
  .clk         ( adc_clk_i[GV] ),  // ADC clock
  .rst_n       ( filt_rstn[GV] ),  // ADC reset - active low
  .s_axis_tdata( adc_filt_in   ),  // ADC raw data
  .s_axis_tvalid(1'b1),
  .m_axis_tdata( adc_filtered  ),  // filtered data
  .cfg_bypass(1'b0),
   // configuration
  .cfg_coeff_aa( set_filt_aa[(GV+1)*18-1:GV*18] ),  // config AA coefficient
  .cfg_coeff_bb( set_filt_bb[(GV+1)*25-1:GV*25] ),  // config BB coefficient
  .cfg_coeff_kk( set_filt_kk[(GV+1)*25-1:GV*25] ),  // config KK coefficient
  .cfg_coeff_pp( set_filt_pp[(GV+1)*25-1:GV*25] )   // config PP coefficient
);

end else begin : g_nofilt
  // Sin ecualizador: la señal calibrada pasa directo. Se elimina el lazo IIR
  // que no cierra timing (ver el comentario de EN_FILT en la cabecera).
  // Ojo: tambien desaparecen los ~5 ciclos de latencia del filtro, pero el
  // corrimiento es comun al trigger y al buffer, asi que siguen alineados.
  assign adc_filtered = adc_filt_in;
end

assign adc_dec_in = set_filt_byp[GV] ? adc_filt_in : adc_filtered;

// Toma para el MCA: mismo nodo que alimenta a rp_decim y a rp_adc_trig, y
// respeta set_filt_byp. Es un alias de una señal que ya existe, asi que no
// agrega logica; con los puertos sin conectar en red_pitaya_top se poda todo.
assign mca_dat[(GV+1)*DW-1:GV*DW] = adc_dec_in;
assign mca_val[GV]                = adc_rstn_i[GV];

rp_decim #(
  .DW  (  DW    )
) i_dec (
   // global signals
  .adc_clk_i    ( adc_clk_i[GV]  ),  // ADC clock
  .adc_rstn_i   ( adc_rstn_i[GV] ),  // ADC reset - active low

   // Connection to AXI master
  .dec_dat_i    ( adc_dec_in                 ),  // data in
  .set_dec_i    ( set_dec[(GV+1)*17-1:GV*17] ),  // decimation
  .set_avg_en_i ( set_avg_en[GV]             ),  // averaging enable
  .adc_arm_do_i ( adc_arm_do[GV]             ),    

  .dec_val_o    ( dec_val       ),
  .dec_dat_o    ( adc_dly_in    )   // decimated data out
);

assign dec_val_65 = dec_val;

// Hint de categoría de delay para rp_delay (4b, codificación legacy) derivado
// de la máscara de 32b: ext/ASG (bits 9..12) -> 4'd6, flanco ADC (bits 1..8)
// -> 4'd2, resto -> 4'd0.
wire [4-1:0] dly_src_hint =
   (|trg_src[GV*32+9 +: 4]) ? 4'd6 :
   (|trg_src[GV*32+1 +: 8]) ? 4'd2 : 4'd0 ;

rp_delay #(
  .DW  (  DW    )
) i_dly (
   // global signals
  .adc_clk_i     ( adc_clk_i[GV]                  ),  // ADC clock
  .adc_rstn_i    ( adc_rstn_i[GV]                 ),  // ADC reset - active low
  .axi_clk_i     ( axi_clk[GV]                    ),  // AXI clock
  .axi_rstn_i    ( axi_rstn[GV]                   ),  // AXI reset - active low

   // Connection to AXI master
  .dly_dat_i     ( adc_dly_in                     ),
  .dly_val_i     ( dec_val_65                        ),
  .set_trg_src_i ( dly_src_hint                   ),
  .set_trg_new_i ( new_trg_src[GV]                ),

  .axidly_val_o  ( axi_dv_del                     ),
  .axidly_dat_o  ( axi_ram_in                     ), // delayed data to AXI

  .dly_valp_o    ( adc_dv_del_p[GV]               ),
  .dly_val_o     ( adc_dv_del[GV]                 ),
  .dly_dat_o     ( adc_bram_in[(GV+1)*DW-1:GV*DW] )  // delayed data to BRAM
);


// Este módulo convierte los datos del adc en las senales de trigger a partir 
// de un disparador smith
rp_adc_trig #(
  .DW  (  DW     )
) i_adc_trig (
   // global signals
  .adc_clk_i      ( adc_clk_i[GV]   ),  // ADC clock
  .adc_rstn_i     ( adc_rstn_i[GV]  ),  // ADC reset - active low

   // Connection to AXI master
  .adc_dat_i      ( adc_dly_in                      ),
  .adc_dv_i       ( dec_val_65                         ),
  .set_tresh_i    ( set_tresh[(GV+1)*DW-1:GV*DW]    ),
  .set_hyst_i     ( set_hyst[(GV+1)*DW-1:GV*DW]     ),

  .adc_trig_p_o   ( adc_trig_p[GV]                  ),
  .adc_trig_n_o   ( adc_trig_n[GV]                  )
);



assign adc_dv_bram[GV] = adc_dv_del[GV];
// Tenemos cada uno de estos módulos como canales de entrada 
rp_bram_sm #(
) i_bram_sm (
   // global signals
  .adc_clk_i      ( adc_clk_i[GV]   ),  // ADC clock
  .adc_rstn_i     ( adc_rstn_i[GV]  ),  // ADC reset - active low

   // Connection to AXI master
  .set_dly_i      ( set_adc_dly[(GV+1)*32 -1:GV*32 ]  ),
  .set_dec1_i     ( set_dec1[GV]                      ),
  .adc_rst_do_i   ( adc_rst_do[GV]                    ),
  .adc_we_keep_i  ( adc_we_keep[GV]                   ),
  .adc_arm_do_i   ( adc_arm_do[GV]                    ) ,    // Lógica de inicio
  .adc_trig_i     ( trigger_event                      ), // Este también tengo que mod?
  .adc_dv_i       ( adc_dv_bram[GV]                   ),
  .indep_mode_i   ( indep_mode[GV]                    ),
  .trig_dis_clr_i ( trig_dis_clr[GV]                  ),

  .adc_wp_o       ( adc_wp_act[(GV+1)*RSZ-1:GV*RSZ]   ),
  .adc_wp_cur_o   ( adc_wp_cur[(GV+1)*RSZ-1:GV*RSZ]   ),
  .adc_wp_trig_o  ( adc_wp_trig[(GV+1)*RSZ-1:GV*RSZ]  ),
  .adc_we_cnt_o   ( adc_we_cnt[(GV+1)*32-1:GV*32]     ),
  .adc_state_o    ( adc_state[(GV+1)*8-1:GV*8]        ),
  .adc_we_o       ( adc_we[GV]                        ),
  .adc_dly_do_o   ( adc_dly_do[GV]                    )
);

rp_acq_bram #(
  .DW  (  DW     ),
  .RSZ (  RSZ    ) // Utiliza el RAMsize como parámetro
) i_acq_bram (
   // global signals
  .adc_clk_i      ( adc_clk_i[GV]   ),  // ADC clock
  .adc_rstn_i     ( adc_rstn_i[GV]  ),  // ADC reset - active low

   // Connection to AXI master
  .bram_wp_i      ( adc_wp_act[(GV+1)*RSZ-1:GV*RSZ] ),
  .bram_dat_i     ( adc_bram_in[(GV+1)*DW-1:GV*DW]  ),
  .bram_val_i     ( adc_dv_bram[GV]                 ), // 
  .bram_we_i      ( adc_we[GV]                      ), // Write enable  
  .bram_ack_i     ( sys_en                          ), // 

  .bram_rp_i      ( sys_addr[RSZ+1:2]               ), // Read pointer
  .bram_dat_o     ( bram_rd_dat[(GV+1)*DW-1:GV*DW]  ), // 
  .bram_ack_o     ( bram_ack[GV]                    )
);

// Datapath a la escritura del RAM?
rp_axi_sm #(
  .DW  (  DW    )
) i_axi_sm (
   // global signals
  .axi_clk_i        ( axi_clk[GV]                       ),
  .axi_rstn_i       ( axi_rstn[GV]                      ),
  .axi_waddr_o      ( axi_waddr_o[(GV+1)*32-1:GV*32]    ),
  .axi_wdata_o      ( axi_wdata_o[(GV+1)*64-1:GV*64]    ),
  .axi_wsel_o       ( axi_wsel_o[(GV+1)*8-1:GV*8]       ),
  .axi_wvalid_o     ( axi_wvalid_o[GV]                  ),
  .axi_wlen_o       ( axi_wlen_o[(GV+1)*4-1:GV*4]       ),
  .axi_wfixed_o     ( axi_wfixed_o[GV]                  ),
  .axi_werr_i       ( axi_werr_i[GV]                    ),
  .axi_wrdy_i       ( axi_wrdy_i[GV]                    ),

   // Connection to AXI master
  .axi_dat_i        ( axi_ram_in                        ),
  .axi_dv_i         ( axi_dv_del                        ),
  .set_dly_i        ( set_axi_dly[(GV+1)*32 -1:GV*32 ]  ),
  .set_dec1_i       ( set_dec1[GV]                      ),
  .adc_rst_do_i     ( adc_rst_do[GV]                    ),
  .adc_we_keep_i    ( adc_we_keep[GV]                   ),
  .adc_arm_do_i     ( adc_arm_do[GV]                         ),
  .adc_trig_i       ( trigger_event                      ),
  .indep_mode_i     ( indep_mode[GV]                    ),

  .axi_en_pulse_i   ( axi_en_pulse[GV]                  ),
  .set_axi_en_i     ( set_axi_en[GV]                    ),
  .set_axi_start_i  ( set_axi_start[(GV+1)*32-1:GV*32]  ),
  .set_axi_stop_i   ( set_axi_stop[(GV+1)*32-1:GV*32]   ),
  .axi_wp_trig_o    ( axi_wp_trig[(GV+1)*32-1:GV*32]    ),
  .axi_wp_cur_o     ( axi_wp_cur[(GV+1)*32-1:GV*32]     ),

  .axi_trig_o       ( axi_trig[GV]                      ), // Trig_0
  .axi_state_o      ( axi_state[(GV+1)*8-1:GV*8]        )  // Axi_state?
);
end
endgenerate

// Rellena el de canales con ceros. 
genvar GM;
generate
for(GM = N_CH ; GM < 4 ; GM = GM + 1) begin // pad out remaining channels

assign adc_bram_in[(GM+1)*DW -1:GM*DW ] = {DW{1'b0}};
assign adc_dv_del[GM]                   =  1'b0;
assign adc_dv_bram[GM]                  =  1'b0;
assign adc_dv_del_p[GM]                 =  1'b0;


assign adc_state[(GM+1)*8  -1:GM*8  ]   =  8'h0;
assign axi_state[(GM+1)*8  -1:GM*8  ]   =  8'h0;
assign trg_state[(GM+1)*8  -1:GM*8  ]   =  8'h0;

assign adc_wp_act[(GM+1)*RSZ-1:GM*RSZ]  = {RSZ{1'b0}};
assign adc_wp_cur[(GM+1)*RSZ-1:GM*RSZ]  = {RSZ{1'b0}};
assign adc_wp_trig[(GM+1)*RSZ-1:GM*RSZ] = {RSZ{1'b0}};
assign adc_we_cnt[(GM+1)*32 -1:GM*32 ]  = 32'h0;

assign axi_wp_cur[(GM+1)*32 -1:GM*32 ]  = 32'h0;
assign axi_wp_trig[(GM+1)*32 -1:GM*32 ] = 32'h0;

assign bram_rd_dat[(GM+1)*DW -1:GM*DW ] = {DW{1'b0}};
assign bram_ack[GM]                     =  1'b0;
assign adc_trig_p[GM]                   =  1'b0;
assign adc_trig_n[GM]                   =  1'b0;
assign axi_trig[GM]                     =  1'b0;

assign adc_we[GM]                       =  1'b0;
assign adc_dly_do[GM]                   =  1'b0;

end
endgenerate

// Externar Trigger 
rp_ext_trig #(
  .DW  (  DW     )
) i_ext_trig (
   // global signals
  .adc_clk_i      ( adc_clk_i[0]    ),  // ADC clock
  .adc_rstn_i     ( adc_rstn_i[0]   ),  // ADC reset - active low

   // Connection to AXI master
  .trig_asg_i     ( trig_asg_i      ),  // Que es esto
  .trig_ext_i     ( trig_ext_i      ),
  .set_deb_len_i  ( set_deb_len     ),  // debouncer len


  .ext_trig_p_o   ( ext_trig_p      ),
  .ext_trig_n_o   ( ext_trig_n      ),
  .asg_trig_p_o   ( asg_trig_p      ),
  .asg_trig_n_o   ( asg_trig_n      )
);

multitrigger_rp_scope_cfg #(
  .CHN (  CHN    ),
  .DW  (  DW     )
) i_cfg (
   // global signals
  .adc_clk_i          ( adc_clk_i[0]    ),  // ADC clock
  .adc_rstn_i         ( adc_rstn_i[0]   ),  // ADC reset - active low

  // System bus
  .sys_addr           ( sys_addr        ),  // Input
  .sys_wdata          ( sys_wdata       ),
  .sys_wen            ( sys_wen         ),
  .sys_ren            ( sys_ren         ),
  .sys_rdata          ( sys_rdata       ),
  .sys_err            ( sys_err         ),
  .sys_ack            ( sys_ack         ),

  // 
  .adc_state_i        ( adc_state       ),
  .axi_state_i        ( axi_state       ),
  .trg_state_i        ( trg_state       ),
  
  // ADC Externo 
  .adc_state_ext_i    ( adc_state_i     ),
  .axi_state_ext_i    ( axi_state_i     ),
  .trg_state_ext_i    ( trg_state_i     ),

  // 
  .adc_wp_cur_i       ( adc_wp_cur      ),
  .adc_wp_trig_i      ( adc_wp_trig     ),
  .adc_we_cnt_i       ( adc_we_cnt      ),

  .axi_wp_cur_i       ( axi_wp_cur      ),
  .axi_wp_trig_i      ( axi_wp_trig     ),

  .bram_rd_dat_i      ( bram_rd_dat     ),
  .bram_ack_i         ( bram_ack        ),

    // TODO cambiar rp_conf
  .adc_arm_do_o       ( adc_arm_do      ),

  .adc_rst_do_o       ( adc_rst_do      ),
  .adc_trig_sw_o      ( adc_trig_sw     ),
  .adc_we_keep_o      ( adc_we_keep     ),
  .trig_dis_clr_o     ( trig_dis_clr    ),
  .indep_mode_o       ( indep_mode      ),
  .axi_en_pulse_o     ( axi_en_pulse    ),
  .new_trg_src_o      ( new_trg_src     ),  // Las fuentes a tomar se decide de forma externa.
  .trg_src_o          ( trg_src         ),
  .set_dec1_o         ( set_dec1        ),
  .filt_rstn_o        ( filt_rstn       ),
  .set_tresh_o        ( set_tresh       ),
  .set_dly_o          ( set_adc_dly     ),
  .set_dec_o          ( set_dec         ),
  .set_hyst_o         ( set_hyst        ),
  .set_avg_en_o       ( set_avg_en      ),
  .set_filt_aa_o      ( set_filt_aa     ),
  .set_filt_bb_o      ( set_filt_bb     ),
  .set_filt_kk_o      ( set_filt_kk     ),
  .set_filt_pp_o      ( set_filt_pp     ),

  .set_calib_offset_o ( set_calib_offset),
  .set_calib_gain_o   ( set_calib_gain  ),

  .set_filt_byp_o     ( set_filt_byp    ),
  .set_deb_len_o      ( set_deb_len     ),
  .set_axi_start_o    ( set_axi_start   ),
  .set_axi_stop_o     ( set_axi_stop    ),
  .set_axi_dly_o      ( set_axi_dly     ),
  .set_axi_en_o       ( set_axi_en      ),

  .shield_src_o       ( shield_src      ),
  .shield_dst_o       ( shield_dst      ),
  .shield_dur_o       ( shield_dur      ),

  // Debug readbacks
  .adc_trg_dis_act_i  ( adc_trg_dis_act ),
  .shield_cnt_i       ( shield_cnt      ),
  .shield_active_i    ( shield_active   ),
  .trig_snapshot_i    ( trig_snapshot   )
);

assign axi_clk    = adc_clk_i ;
assign axi_rstn   = adc_rstn_i;

assign axi_clk_o  = axi_clk ;
assign axi_rstn_o = axi_rstn;

// trig_ch_o y daisy_trig_o los maneja i_event_logic.
assign trig_ext_asg_o = {asg_trig_n, asg_trig_p, ext_trig_n, ext_trig_p};

endmodule
