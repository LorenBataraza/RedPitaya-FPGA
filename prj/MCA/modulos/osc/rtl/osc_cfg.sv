`timescale 1ns/1ps
//=============================================================================
// osc_cfg — región de OSC: esclavo del bus de sistema (slot 1, 0x4010_0000)
//
// Sale de multitrigger_rp_scope_cfg, quitándole los registros del multitrigger
// (que se mudaron al slot 3, ver multitrigger_cfg.sv) y reorganizando el mapa.
//
//=============================================================================
// LOS DOS MAPAS
//=============================================================================
//
// Este esclavo decodifica DOS rangos de direcciones sobre EL MISMO banco de
// registros físicos. No hay estado duplicado: un solo flop por registro, dos
// decodificadores para alcanzarlo. Escribir por un mapa y leer por el otro
// devuelve el mismo valor, así que no se pueden desincronizar.
//
//   0x00000 - 0x00FFF   mapa LEGACY   offsets históricos de Red Pitaya
//   0x01000 - 0x01FFF   mapa CANÓNICO stride uniforme por canal
//   0x10000 - 0x4FFFF   aperturas BRAM (comunes a los dos mapas)
//
// POR QUÉ EXISTE EL MAPA LEGACY. librp es una librería C cerrada que lee y
// escribe offsets fijos en 0x4010_0000; hay 111 llamadas a la API rp repartidas
// en 14 archivos del software del proyecto (run_acquire, e2e_espectro,
// mca/sources, los benches). Mover los registros sin dejar los offsets viejos
// rompería todo eso de golpe y sin posibilidad de parche del lado Python.
// Con la ventana, la migración del software es incremental.
//
// CÓMO SE SACA. El parámetro EN_LEGACY_MAP la compila fuera. Cuando el software
// esté migrado se pone en 0 y las ramas legacy desaparecen en síntesis; es el
// único lugar donde hay que tocar.
//
// LO QUE EL MAPA LEGACY *NO* CUBRE. Los registros del multitrigger que se
// fueron al slot 3 (0x210, 0x214, 0x218, 0x21C, 0x240-0x24C): librp no los
// conoce, son propios del proyecto, así que no hay compatibilidad que
// preservar — sólo hay que reapuntar multitrigger_utils.py.
//
// Excepción: dos offsets legacy SÍ pertenecen a lógica que se mudó, y librp los
// usa. Se siguen decodificando acá y se mandan al slot 3 ya decodificados por
// canal, por los puertos legacy_trig_sw_o / legacy_trig_dis_clr_o:
//
//   0x004  SW-trigger      (bits [3:0] == 1 del byte del canal)
//   0x094  trig_dis_clr
//
// OJO, DIVERGENCIA PREEXISTENTE. En 0x004 este diseño ya no es el Red Pitaya de
// fábrica: el RTL sólo honra el valor 1 (SW). Un rp_AcqSetTriggerSrc con una
// fuente de flanco escribe 2, 3, ... y se ignora, porque esas fuentes pasaron a
// la OR-mask del multitrigger. La ventana legacy preserva EL COMPORTAMIENTO
// ACTUAL, no el original de Red Pitaya.
//
//=============================================================================
// ACK DE LATENCIA FIJA — Y EL BUG QUE ESTO ARREGLA
//=============================================================================
//
// El módulo original sacaba el ack de las aperturas BRAM de bram_ack_i[i], y
// rp_scope_multitrigger_com ata bram_ack[2]/[3] = 0 para los canales no
// construidos: cualquier lectura en 0x4013_0000-0x4014_FFFF no hacía ack NUNCA
// y dejaba el CDC del slot desincronizado (docs/TOP/bus_sistema_redpitaya.md §7.1).
//
// Acá el ack sale de un shift register incondicional, a los 4 ciclos y para
// cualquier dirección. Para los canales que sí existen el timing es IDÉNTICO:
// rp_acq_bram genera bram_ack_o = sys_en retrasado 4 ciclos
// (adc_rval <= {adc_rval[2:0], bram_ack_i}), que es exactamente en_sr[3].
// O sea que se arregla el cuelgue sin cambiar en nada las lecturas buenas.
//=============================================================================

module osc_cfg #(
  parameter [31:0]  MAGIC          = 32'h4F534331,  // "OSC1"
  parameter integer EN_LEGACY_MAP  = 1,             // 0 = compila fuera el mapa viejo
  parameter integer CHN            = 0,
  parameter integer N_CH           = 2,
  parameter integer DW             = 14,
  parameter integer RSZ            = 14
)(
  input                      adc_clk_i            ,
  input                      adc_rstn_i           ,

  // --- bus de sistema ---
  input      [      32-1: 0] sys_addr             ,
  input      [      32-1: 0] sys_wdata            ,
  input                      sys_wen              ,
  input                      sys_ren              ,
  output reg [      32-1: 0] sys_rdata            ,
  output reg                 sys_err              ,
  output reg                 sys_ack              ,

  // --- estado de vuelta desde el datapath ---
  input      [   4*8  -1: 0] adc_state_i          ,
  input      [   4*8  -1: 0] axi_state_i          ,
  input      [   4*8  -1: 0] trg_state_i          ,
  input      [   2*8  -1: 0] adc_state_ext_i      ,
  input      [   2*8  -1: 0] axi_state_ext_i      ,
  input      [   2*8  -1: 0] trg_state_ext_i      ,

  input      [   4*RSZ-1: 0] adc_wp_cur_i         ,
  input      [   4*RSZ-1: 0] adc_wp_trig_i        ,
  input      [   4*32 -1: 0] adc_we_cnt_i         ,
  input      [   4*32 -1: 0] axi_wp_cur_i         ,
  input      [   4*32 -1: 0] axi_wp_trig_i        ,
  input      [   4*DW -1: 0] bram_rd_dat_i        ,

  // --- comandos y configuración hacia el datapath ---
  output     [       4-1: 0] adc_arm_do_o         ,
  output     [       4-1: 0] adc_rst_do_o         ,
  output     [       4-1: 0] adc_we_keep_o        ,
  output     [       4-1: 0] indep_mode_o         ,
  output     [       4-1: 0] axi_en_pulse_o       ,
  output     [       4-1: 0] set_dec1_o           ,
  output     [       4-1: 0] filt_rstn_o          ,
  output     [   4*DW -1: 0] set_tresh_o          ,
  output     [   4*32 -1: 0] set_dly_o            ,
  output     [   4*17 -1: 0] set_dec_o            ,
  output     [   4*DW -1: 0] set_hyst_o           ,
  output     [       4-1: 0] set_avg_en_o         ,
  output     [   4*18 -1: 0] set_filt_aa_o        ,
  output     [   4*25 -1: 0] set_filt_bb_o        ,
  output     [   4*25 -1: 0] set_filt_kk_o        ,
  output     [   4*25 -1: 0] set_filt_pp_o        ,
  output     [   4*DW -1: 0] set_calib_offset_o   ,
  output     [   4*16 -1: 0] set_calib_gain_o     ,
  output     [      4 -1: 0] set_filt_byp_o       ,
  output     [      20-1: 0] set_deb_len_o        ,
  output     [   4*32 -1: 0] set_axi_start_o      ,
  output     [   4*32 -1: 0] set_axi_stop_o       ,
  output     [   4*32 -1: 0] set_axi_dly_o        ,
  output     [       4-1: 0] set_axi_en_o         ,

  // --- puente legacy hacia multitrigger_cfg (slot 3) ---
  // Pulsos ya decodificados por canal desde los offsets 0x004 y 0x094.
  output     [       4-1: 0] legacy_trig_sw_o     ,
  output     [       4-1: 0] legacy_trig_dis_clr_o
);

//=============================================================================
// Banco de registros físicos — UNO SOLO, alcanzable desde los dos mapas
//=============================================================================
reg  [    4-1: 0] adc_arm_do    ;
reg  [    4-1: 0] adc_rst_do    ;
reg  [    4-1: 0] adc_we_keep   ;
reg  [    4-1: 0] indep_mode    ;
reg  [    4-1: 0] trig_sw       ;
reg  [    4-1: 0] trig_dis_clr  ;

reg  [ 4*DW-1: 0] set_tresh     ;
reg  [ 4*32-1: 0] set_dly       ;
reg  [ 4*17-1: 0] set_dec       ;
reg  [ 4*DW-1: 0] set_hyst      ;
reg  [    4-1: 0] set_avg_en    ;

reg  [ 4*18-1: 0] set_filt_aa   ;
reg  [ 4*25-1: 0] set_filt_bb   ;
reg  [ 4*25-1: 0] set_filt_kk   ;
reg  [ 4*25-1: 0] set_filt_pp   ;
reg  [    4-1: 0] set_filt_byp  ;

reg  [ 4*DW-1: 0] set_calib_offset ;
reg  [ 4*16-1: 0] set_calib_gain   ;

reg  [   20-1: 0] set_deb_len   ;

reg  [ 4*32-1: 0] set_axi_start ;
reg  [ 4*32-1: 0] set_axi_stop  ;
reg  [ 4*32-1: 0] set_axi_dly   ;
reg  [    4-1: 0] set_axi_en    ;

wire [    4-1: 0] axi_en_addr   ;
wire [    4-1: 0] axi_en_pulse  ;
wire [    4-1: 0] set_dec1      ;
wire [    4-1: 0] filt_rstn     ;
wire [    4-1: 0] filt_coef_adr ;

wire              sys_en = sys_wen | sys_ren;

wire [   32-1: 0] adc_state_rd ;
wire [   32-1: 0] trg_state_rd ;

assign adc_state_rd = (CHN == 0) ? {adc_state_ext_i, adc_state_i[15:0]}
                                 : {adc_state_i[15:0], adc_state_ext_i};
assign trg_state_rd = (CHN == 0) ? {trg_state_ext_i, trg_state_i[15:0]}
                                 : {trg_state_i[15:0], trg_state_ext_i};

//=============================================================================
// Direcciones canónicas: bases y stride por canal
//=============================================================================
localparam [19:0] CANON_BASE = 20'h01000;  // registros globales del mapa nuevo
localparam [19:0] CANON_CH   = 20'h01100;  // por canal, stride 0x40
localparam [19:0] CANON_AXI  = 20'h01200;  // AXI por canal, stride 0x20

// Un canal "acierta" si la dirección cae en su ventana de 0x40 / 0x20.
function automatic bit ch_hit(input [19:0] a, input [19:0] base,
                              input integer ch, input integer stride,
                              input [19:0] off);
  ch_hit = (a == (base + ch*stride + off));
endfunction

//=============================================================================
// Pulsos legacy: el byte por canal depende de indep_mode (igual que el
// original). Se mantiene tal cual para no cambiar la semántica de librp.
//=============================================================================
wire [4-1:0]   legacy_arm, legacy_rst, legacy_sw, legacy_disclr;
wire [4*8-1:0] sys_dats_all;   // el byte de cada canal, ya remapeado

genvar GV;
generate
for (GV = 0; GV < 4; GV = GV + 1) begin : g_legacy_dats
  wire [8-1:0] sys_dats;
  if (GV < 2) begin : g_dats_sel
    assign sys_dats = ((CHN == 1) && (indep_mode[GV] == 1'b1))
                      ? sys_wdata[(GV+3)*8-1:(GV+2)*8]
                      : sys_wdata[(GV+1)*8-1:GV*8];
  end else begin : g_dats_hi
    assign sys_dats = sys_wdata[(GV+1)*8-1:GV*8];
  end
  assign sys_dats_all[GV*8 +: 8] = sys_dats;

  if (EN_LEGACY_MAP != 0) begin : g_leg_on
    assign legacy_arm[GV]    = sys_wen && (sys_addr[19:0]==20'h000) && sys_dats[0];
    assign legacy_rst[GV]    = sys_wen && (sys_addr[19:0]==20'h000) && sys_dats[1];
    assign legacy_sw[GV]     = sys_wen && (sys_addr[19:0]==20'h004) && (sys_dats[3:0]==4'h1);
    assign legacy_disclr[GV] = sys_wen && (sys_addr[19:0]==20'h094) && sys_dats[0];
  end else begin : g_leg_off
    assign legacy_arm[GV]    = 1'b0;
    assign legacy_rst[GV]    = 1'b0;
    assign legacy_sw[GV]     = 1'b0;
    assign legacy_disclr[GV] = 1'b0;
  end
end
endgenerate

//=============================================================================
// Pulsos canónicos: un bit por canal
//=============================================================================
wire [4-1:0] canon_arm, canon_rst, canon_sw, canon_disclr;

generate
for (GV = 0; GV < 4; GV = GV + 1) begin : g_canon_pulses
  assign canon_arm[GV]    = sys_wen && (sys_addr[19:0]==(CANON_BASE+20'h008)) && sys_wdata[GV];
  assign canon_rst[GV]    = sys_wen && (sys_addr[19:0]==(CANON_BASE+20'h00C)) && sys_wdata[GV];
  assign canon_sw[GV]     = 1'b0;   // el SW-trigger canónico vive en el slot 3
  assign canon_disclr[GV] = 1'b0;   // idem
end
endgenerate

// Los pulsos de arm/rst se registran, igual que en el original.
always @(posedge adc_clk_i)
if (!adc_rstn_i) begin
  adc_arm_do <= 4'h0; adc_rst_do <= 4'h0;
  trig_sw    <= 4'h0; trig_dis_clr <= 4'h0;
end else begin
  adc_arm_do   <= legacy_arm    | canon_arm;
  adc_rst_do   <= legacy_rst    | canon_rst;
  trig_sw      <= legacy_sw     | canon_sw;
  trig_dis_clr <= legacy_disclr | canon_disclr;
end

// Hacia el slot 3. Registrados igual que antes: en el módulo original
// adc_trig_sw y trig_dis_clr salían de un always, no de un assign.
assign legacy_trig_sw_o      = trig_sw;
assign legacy_trig_dis_clr_o = trig_dis_clr;

//=============================================================================
// axi_en_pulse y reset del filtro: direcciones de los dos mapas
//=============================================================================
assign axi_en_addr[0] = (sys_addr[19:0] == 20'h05C) ||
                        (sys_addr[19:0] == (CANON_AXI + 0*20'h20 + 20'h0C));
assign axi_en_addr[1] = (sys_addr[19:0] == 20'h07C) ||
                        (sys_addr[19:0] == (CANON_AXI + 1*20'h20 + 20'h0C));
assign axi_en_addr[2] = (sys_addr[19:0] == 20'h09C) ||
                        (sys_addr[19:0] == (CANON_AXI + 2*20'h20 + 20'h0C));
assign axi_en_addr[3] = (sys_addr[19:0] == 20'h0BC) ||
                        (sys_addr[19:0] == (CANON_AXI + 3*20'h20 + 20'h0C));

assign filt_coef_adr[0] = (sys_addr[7:4] == 4'h3);
assign filt_coef_adr[1] = (sys_addr[7:4] == 4'h4);
assign filt_coef_adr[2] = (sys_addr[7:4] == 4'h3);
assign filt_coef_adr[3] = (sys_addr[7:4] == 4'h3);

generate
for (GV = 0; GV < 4; GV = GV + 1) begin : g_percanal
  reg filt_coef_wr;

  assign axi_en_pulse[GV] = sys_wen && axi_en_addr[GV] && sys_wdata[0];
  assign set_dec1[GV]     = (set_dec[GV*17 +: 17] == 17'h1);
  assign filt_rstn[GV]    = (adc_rstn_i == 1'b1) && filt_coef_wr;

  always @(posedge adc_clk_i)
  if (!adc_rstn_i) filt_coef_wr <= 1'b1;
  else             filt_coef_wr <= ~(sys_wen && filt_coef_adr[GV]);
end
endgenerate

//=============================================================================
// Escritura de registros: las dos ramas escriben el MISMO banco
//=============================================================================
integer c;
always @(posedge adc_clk_i)
if (!adc_rstn_i) begin
  set_tresh[DW*1-1:DW*0] <=  'd5000 ;
  set_tresh[DW*2-1:DW*1] <= -'d5000 ;
  set_tresh[DW*3-1:DW*2] <=  'd5000 ;
  set_tresh[DW*4-1:DW*3] <= -'d5000 ;

  set_dly                <= {4{32'd0}}      ;
  set_dec                <= {4{17'd1}}      ;
  set_hyst[DW*1-1:DW*0]  <= 'd20            ;
  set_hyst[DW*2-1:DW*1]  <= 'd20            ;
  set_hyst[DW*3-1:DW*2]  <= 'd20            ;
  set_hyst[DW*4-1:DW*3]  <= 'd20            ;
  set_avg_en             <=  4'h0           ;

  set_filt_aa            <= {4{18'h0}}      ;
  set_filt_bb            <= {4{25'h0}}      ;
  set_filt_kk            <= {4{25'hFFFFFF}} ;
  set_filt_pp            <= {4{25'h0}}      ;
  set_filt_byp           <=  4'h0           ;

  set_calib_offset       <= {4{{DW{1'b0}}}} ;
  set_calib_gain         <= {4{16'h8000}}   ;

  set_deb_len            <= 20'd62500       ;

  set_axi_start          <= {4{32'd0}}      ;
  set_axi_stop           <= {4{32'd0}}      ;
  set_axi_dly            <= {4{32'd0}}      ;
  set_axi_en             <=  4'h0           ;

  adc_we_keep            <=  4'h0           ;
  indep_mode             <=  4'h0           ;
end else if (sys_wen) begin

  //-------------------------------------------------------------------------
  // Rama LEGACY: offsets históricos de Red Pitaya. Idénticos al módulo
  // original; es lo que escribe librp.
  //-------------------------------------------------------------------------
  if (EN_LEGACY_MAP != 0) begin
    // we_keep / indep_mode / avg_en salen del BYTE POR CANAL, ya remapeado por
    // CHN e indep_mode en sys_dats_all. El guard |sys_dats es del original: sin
    // él, escribir el byte de un canal apagaría los flags de los otros.
    for (c = 0; c < 4; c = c + 1) begin
      if (sys_addr[19:0]==20'h000 && |sys_dats_all[c*8 +: 8]) begin
        adc_we_keep[c] <= sys_dats_all[c*8 + 3];
        indep_mode[c]  <= sys_dats_all[c*8 + 5];
      end
      if (sys_addr[19:0]==20'h028) set_avg_en[c] <= sys_dats_all[c*8 + 0];
    end

    if (sys_addr[19:0]==20'h008) set_tresh[DW*1-1:DW*0]     <= sys_wdata[DW-1:0];
    if (sys_addr[19:0]==20'h00C) set_tresh[DW*2-1:DW*1]     <= sys_wdata[DW-1:0];
    if (sys_addr[19:0]==20'h010) set_dly[32*1-1:32*0]       <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h014) set_dec[17*1-1:17*0]       <= sys_wdata[17-1:0];
    if (sys_addr[19:0]==20'h020) set_hyst[DW*1-1:DW*0]      <= sys_wdata[DW-1:0];
    if (sys_addr[19:0]==20'h024) set_hyst[DW*2-1:DW*1]      <= sys_wdata[DW-1:0];

    if (sys_addr[19:0]==20'h030) set_filt_aa[18*1-1:18*0]   <= sys_wdata[18-1:0];
    if (sys_addr[19:0]==20'h034) set_filt_bb[25*1-1:25*0]   <= sys_wdata[25-1:0];
    if (sys_addr[19:0]==20'h038) set_filt_kk[25*1-1:25*0]   <= sys_wdata[25-1:0];
    if (sys_addr[19:0]==20'h03C) set_filt_pp[25*1-1:25*0]   <= sys_wdata[25-1:0];
    if (sys_addr[19:0]==20'h040) set_filt_aa[18*2-1:18*1]   <= sys_wdata[18-1:0];
    if (sys_addr[19:0]==20'h044) set_filt_bb[25*2-1:25*1]   <= sys_wdata[25-1:0];
    if (sys_addr[19:0]==20'h048) set_filt_kk[25*2-1:25*1]   <= sys_wdata[25-1:0];
    if (sys_addr[19:0]==20'h04C) set_filt_pp[25*2-1:25*1]   <= sys_wdata[25-1:0];

    if (sys_addr[19:0]==20'h050) set_axi_start[32*1-1:32*0] <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h054) set_axi_stop[32*1-1:32*0]  <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h058) set_axi_dly[32*1-1:32*0]   <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h05C) set_axi_en[0]              <= sys_wdata[0];

    if (sys_addr[19:0]==20'h070) set_axi_start[32*2-1:32*1] <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h074) set_axi_stop[32*2-1:32*1]  <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h078) set_axi_dly[32*2-1:32*1]   <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h07C) set_axi_en[1]              <= sys_wdata[0];

    if (sys_addr[19:0]==20'h090) set_deb_len                <= sys_wdata[20-1:0];
    // 0x094 reservado para el trig_dis_clr (puente legacy, arriba)
    if (sys_addr[19:0]==20'h098) set_filt_byp               <= sys_wdata[4-1:0];

    if (sys_addr[19:0]==20'h110) set_dly[32*2-1:32*1]       <= sys_wdata[32-1:0];
    if (sys_addr[19:0]==20'h114) set_dec[17*2-1:17*1]       <= sys_wdata[17-1:0];

    if (sys_addr[19:0]==20'h200) set_calib_offset[DW*1-1:DW*0] <= sys_wdata[DW-1:0];
    if (sys_addr[19:0]==20'h204) set_calib_gain[16*1-1:16*0]   <= sys_wdata[16-1:0];
    if (sys_addr[19:0]==20'h208) set_calib_offset[DW*2-1:DW*1] <= sys_wdata[DW-1:0];
    if (sys_addr[19:0]==20'h20C) set_calib_gain[16*2-1:16*1]   <= sys_wdata[16-1:0];
  end

  //-------------------------------------------------------------------------
  // Rama CANÓNICA: globales en 0x1000, por canal en 0x1100 + 0x40*ch,
  // AXI en 0x1200 + 0x20*ch. Escribe EXACTAMENTE los mismos registros.
  //-------------------------------------------------------------------------
  if (sys_addr[19:0]==(CANON_BASE+20'h010)) adc_we_keep  <= sys_wdata[3:0];
  if (sys_addr[19:0]==(CANON_BASE+20'h014)) indep_mode   <= sys_wdata[3:0];
  if (sys_addr[19:0]==(CANON_BASE+20'h01C)) set_deb_len  <= sys_wdata[20-1:0];
  if (sys_addr[19:0]==(CANON_BASE+20'h020)) set_filt_byp <= sys_wdata[4-1:0];
  if (sys_addr[19:0]==(CANON_BASE+20'h024)) set_avg_en   <= sys_wdata[3:0];

  for (c = 0; c < 4; c = c + 1) begin
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h00)) set_tresh[c*DW +: DW]        <= sys_wdata[DW-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h04)) set_hyst[c*DW +: DW]         <= sys_wdata[DW-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h08)) set_dly[c*32 +: 32]          <= sys_wdata[32-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h0C)) set_dec[c*17 +: 17]          <= sys_wdata[17-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h1C)) set_calib_offset[c*DW +: DW] <= sys_wdata[DW-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h20)) set_calib_gain[c*16 +: 16]   <= sys_wdata[16-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h24)) set_filt_aa[c*18 +: 18]      <= sys_wdata[18-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h28)) set_filt_bb[c*25 +: 25]      <= sys_wdata[25-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h2C)) set_filt_kk[c*25 +: 25]      <= sys_wdata[25-1:0];
    if (ch_hit(sys_addr[19:0], CANON_CH, c, 'h40, 'h30)) set_filt_pp[c*25 +: 25]      <= sys_wdata[25-1:0];

    if (ch_hit(sys_addr[19:0], CANON_AXI, c, 'h20, 'h00)) set_axi_start[c*32 +: 32]   <= sys_wdata[32-1:0];
    if (ch_hit(sys_addr[19:0], CANON_AXI, c, 'h20, 'h04)) set_axi_stop[c*32 +: 32]    <= sys_wdata[32-1:0];
    if (ch_hit(sys_addr[19:0], CANON_AXI, c, 'h20, 'h08)) set_axi_dly[c*32 +: 32]     <= sys_wdata[32-1:0];
    if (ch_hit(sys_addr[19:0], CANON_AXI, c, 'h20, 'h0C)) set_axi_en[c]               <= sys_wdata[0];
  end
end

//=============================================================================
// Lectura
//=============================================================================
reg [7:0] en_sr;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) en_sr <= 8'h0;
  else             en_sr <= {en_sr[6:0], sys_en};

// Canal seleccionado por la dirección canónica (para no repetir 4 ramas).
wire [1:0] canon_ch  = sys_addr[7:6];   // stride 0x40 -> bits [7:6]
wire [1:0] canon_ach = sys_addr[6:5];   // stride 0x20 -> bits [6:5]

reg [31:0] rd_legacy, rd_canon, rd_bram;
wire       is_canon_ch  = (sys_addr[19:8] == CANON_CH[19:8]);
wire       is_canon_axi = (sys_addr[19:8] == CANON_AXI[19:8]);

// Aperturas BRAM: 0x1xxxx..0x4xxxx, una por canal (comunes a los dos mapas).
always @(*) begin
  case (sys_addr[19:16])
    4'h1    : rd_bram = {{32-DW{1'b0}}, bram_rd_dat_i[DW*1-1:DW*0]};
    4'h2    : rd_bram = {{32-DW{1'b0}}, bram_rd_dat_i[DW*2-1:DW*1]};
    4'h3    : rd_bram = {{32-DW{1'b0}}, bram_rd_dat_i[DW*3-1:DW*2]};
    4'h4    : rd_bram = {{32-DW{1'b0}}, bram_rd_dat_i[DW*4-1:DW*3]};
    default : rd_bram = 32'h0;
  endcase
end

always @(*) begin
  rd_legacy = 32'h0;
  if (EN_LEGACY_MAP != 0) begin
    case (sys_addr[19:0])
      20'h000 : rd_legacy = adc_state_rd;
      20'h004 : rd_legacy = trg_state_rd;
      20'h008 : rd_legacy = {{32-DW{1'b0}},  set_tresh[DW*1-1:DW*0]};
      20'h00C : rd_legacy = {{32-DW{1'b0}},  set_tresh[DW*2-1:DW*1]};
      20'h010 : rd_legacy = set_dly[32*1-1:32*0];
      20'h014 : rd_legacy = {{32-17{1'b0}},  set_dec[17*1-1:17*0]};
      20'h018 : rd_legacy = {{32-RSZ{1'b0}}, adc_wp_cur_i[RSZ*1-1:RSZ*0]};
      20'h01C : rd_legacy = {{32-RSZ{1'b0}}, adc_wp_trig_i[RSZ*1-1:RSZ*0]};
      20'h020 : rd_legacy = {{32-DW{1'b0}},  set_hyst[DW*1-1:DW*0]};
      20'h024 : rd_legacy = {{32-DW{1'b0}},  set_hyst[DW*2-1:DW*1]};
      20'h028 : rd_legacy = {7'h0, set_avg_en[3], 7'h0, set_avg_en[2],
                             7'h0, set_avg_en[1], 7'h0, set_avg_en[0]};
      20'h02C : rd_legacy = adc_we_cnt_i[32*1-1:32*0];
      20'h030 : rd_legacy = {{32-18{1'b0}},  set_filt_aa[18*1-1:18*0]};
      20'h034 : rd_legacy = {{32-25{1'b0}},  set_filt_bb[25*1-1:25*0]};
      20'h038 : rd_legacy = {{32-25{1'b0}},  set_filt_kk[25*1-1:25*0]};
      20'h03C : rd_legacy = {{32-25{1'b0}},  set_filt_pp[25*1-1:25*0]};
      20'h040 : rd_legacy = {{32-18{1'b0}},  set_filt_aa[18*2-1:18*1]};
      20'h044 : rd_legacy = {{32-25{1'b0}},  set_filt_bb[25*2-1:25*1]};
      20'h048 : rd_legacy = {{32-25{1'b0}},  set_filt_kk[25*2-1:25*1]};
      20'h04C : rd_legacy = {{32-25{1'b0}},  set_filt_pp[25*2-1:25*1]};
      20'h050 : rd_legacy = set_axi_start[32*1-1:32*0];
      20'h054 : rd_legacy = set_axi_stop[32*1-1:32*0];
      20'h058 : rd_legacy = set_axi_dly[32*1-1:32*0];
      20'h05C : rd_legacy = {31'h0, set_axi_en[0]};
      20'h060 : rd_legacy = axi_wp_trig_i[32*1-1:32*0];
      20'h064 : rd_legacy = axi_wp_cur_i[32*1-1:32*0];
      20'h070 : rd_legacy = set_axi_start[32*2-1:32*1];
      20'h074 : rd_legacy = set_axi_stop[32*2-1:32*1];
      20'h078 : rd_legacy = set_axi_dly[32*2-1:32*1];
      20'h07C : rd_legacy = {31'h0, set_axi_en[1]};
      20'h080 : rd_legacy = axi_wp_trig_i[32*2-1:32*1];
      20'h084 : rd_legacy = axi_wp_cur_i[32*2-1:32*1];
      20'h088 : rd_legacy = {8'h0, axi_state_i[16-1:8], 8'h0, axi_state_i[8-1:0]};
      20'h090 : rd_legacy = {{32-20{1'b0}}, set_deb_len};
      20'h098 : rd_legacy = {{32-4{1'b0}},  set_filt_byp};
      20'h110 : rd_legacy = set_dly[32*2-1:32*1];
      20'h114 : rd_legacy = {{32-17{1'b0}},  set_dec[17*2-1:17*1]};
      20'h118 : rd_legacy = {{32-RSZ{1'b0}}, adc_wp_cur_i[RSZ*2-1:RSZ*1]};
      20'h11C : rd_legacy = {{32-RSZ{1'b0}}, adc_wp_trig_i[RSZ*2-1:RSZ*1]};
      20'h12C : rd_legacy = adc_we_cnt_i[32*2-1:32*1];
      20'h200 : rd_legacy = {{32-DW{1'b0}},  set_calib_offset[DW*1-1:DW*0]};
      20'h204 : rd_legacy = {{32-16{1'b0}},  set_calib_gain[16*1-1:16*0]};
      20'h208 : rd_legacy = {{32-DW{1'b0}},  set_calib_offset[DW*2-1:DW*1]};
      20'h20C : rd_legacy = {{32-16{1'b0}},  set_calib_gain[16*2-1:16*1]};
      default : rd_legacy = 32'h0;
    endcase
  end
end

always @(*) begin
  rd_canon = 32'h0;
  if (is_canon_ch) begin
    case (sys_addr[5:0])
      6'h00 : rd_canon = {{32-DW{1'b0}},  set_tresh[canon_ch*DW +: DW]};
      6'h04 : rd_canon = {{32-DW{1'b0}},  set_hyst[canon_ch*DW +: DW]};
      6'h08 : rd_canon = set_dly[canon_ch*32 +: 32];
      6'h0C : rd_canon = {{32-17{1'b0}},  set_dec[canon_ch*17 +: 17]};
      6'h10 : rd_canon = {{32-RSZ{1'b0}}, adc_wp_cur_i[canon_ch*RSZ +: RSZ]};
      6'h14 : rd_canon = {{32-RSZ{1'b0}}, adc_wp_trig_i[canon_ch*RSZ +: RSZ]};
      6'h18 : rd_canon = adc_we_cnt_i[canon_ch*32 +: 32];
      6'h1C : rd_canon = {{32-DW{1'b0}},  set_calib_offset[canon_ch*DW +: DW]};
      6'h20 : rd_canon = {{32-16{1'b0}},  set_calib_gain[canon_ch*16 +: 16]};
      6'h24 : rd_canon = {{32-18{1'b0}},  set_filt_aa[canon_ch*18 +: 18]};
      6'h28 : rd_canon = {{32-25{1'b0}},  set_filt_bb[canon_ch*25 +: 25]};
      6'h2C : rd_canon = {{32-25{1'b0}},  set_filt_kk[canon_ch*25 +: 25]};
      6'h30 : rd_canon = {{32-25{1'b0}},  set_filt_pp[canon_ch*25 +: 25]};
      default : rd_canon = 32'h0;
    endcase
  end else if (is_canon_axi) begin
    case (sys_addr[4:0])
      5'h00 : rd_canon = set_axi_start[canon_ach*32 +: 32];
      5'h04 : rd_canon = set_axi_stop[canon_ach*32 +: 32];
      5'h08 : rd_canon = set_axi_dly[canon_ach*32 +: 32];
      5'h0C : rd_canon = {31'h0, set_axi_en[canon_ach]};
      5'h10 : rd_canon = axi_wp_trig_i[canon_ach*32 +: 32];
      5'h14 : rd_canon = axi_wp_cur_i[canon_ach*32 +: 32];
      5'h18 : rd_canon = {8'h0, axi_state_i[16-1:8], 8'h0, axi_state_i[8-1:0]};
      default : rd_canon = 32'h0;
    endcase
  end else begin
    case (sys_addr[19:0])
      (CANON_BASE+20'h000) : rd_canon = MAGIC;
      (CANON_BASE+20'h004) : rd_canon = {10'h0, RSZ[5:0], 2'h0, DW[5:0], 4'h0, N_CH[3:0]};
      (CANON_BASE+20'h010) : rd_canon = {28'h0, adc_we_keep};
      (CANON_BASE+20'h014) : rd_canon = {28'h0, indep_mode};
      (CANON_BASE+20'h018) : rd_canon = adc_state_rd;
      (CANON_BASE+20'h01C) : rd_canon = {{32-20{1'b0}}, set_deb_len};
      (CANON_BASE+20'h020) : rd_canon = {28'h0, set_filt_byp};
      (CANON_BASE+20'h024) : rd_canon = {28'h0, set_avg_en};
      default              : rd_canon = 32'h0;
    endcase
  end
end

always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    sys_ack <= 1'b0; sys_err <= 1'b0; sys_rdata <= 32'h0;
  end else begin
    // Ack incondicional a los 4 ciclos, para CUALQUIER dirección: es lo que
    // arregla el cuelgue de las aperturas de los canales no construidos.
    sys_ack <= en_sr[3];
    sys_err <= 1'b0;

    if (sys_addr[19:16] != 4'h0)
      sys_rdata <= rd_bram;                       // aperturas 0x1xxxx-0x4xxxx
    else if (sys_addr[19:12] == 8'h01)
      sys_rdata <= rd_canon;                      // mapa canónico 0x01xxx
    else
      sys_rdata <= rd_legacy;                     // mapa legacy 0x00xxx
  end
end

//=============================================================================
// Fan-out por indep_mode
//
// Sin modo independiente, TODOS los canales siguen al canal 0: es lo que hace
// que un solo arm dispare la captura de los dos canales a la vez. Estaba en el
// bloque *_x del módulo original y es lo primero que se pierde al mudar
// registros de un archivo a otro, porque no está en el mapa de direcciones —
// vive entre el banco de registros y las salidas.
//
// Se cubren los 4 canales aunque N_CH < 4. El original sólo asignaba GL < N_CH
// y dejaba los bits altos en X, que se propagaban a los reductores del
// event_logic; con el fan-out completo quedan en un valor definido y el
// resultado de cualquier OR es el mismo.
//=============================================================================
wire [   4-1:0] adc_arm_do_x  ;
wire [   4-1:0] adc_rst_do_x  ;
wire [   4-1:0] adc_we_keep_x ;
wire [   4-1:0] set_dec1_x    ;
wire [   4-1:0] set_avg_en_x  ;
wire [4*32-1:0] set_dly_x     ;
wire [4*17-1:0] set_dec_x     ;

generate
for (GV = 0; GV < 4; GV = GV + 1) begin : g_fanout
  if (GV == 0) begin : g_ch0
    assign adc_arm_do_x [GV]        = adc_arm_do [GV];
    assign adc_rst_do_x [GV]        = adc_rst_do [GV];
    assign adc_we_keep_x[GV]        = adc_we_keep[GV];
    assign set_dec1_x   [GV]        = set_dec1   [GV];
    assign set_avg_en_x [GV]        = set_avg_en [GV];
    assign set_dly_x[GV*32 +: 32]   = set_dly[GV*32 +: 32];
    assign set_dec_x[GV*17 +: 17]   = set_dec[GV*17 +: 17];
  end else begin : g_chn
    assign adc_arm_do_x [GV]        = indep_mode[GV] ? adc_arm_do [GV] : adc_arm_do [0];
    assign adc_rst_do_x [GV]        = indep_mode[GV] ? adc_rst_do [GV] : adc_rst_do [0];
    assign adc_we_keep_x[GV]        = indep_mode[GV] ? adc_we_keep[GV] : adc_we_keep[0];
    assign set_dec1_x   [GV]        = indep_mode[GV] ? set_dec1   [GV] : set_dec1   [0];
    assign set_avg_en_x [GV]        = indep_mode[GV] ? set_avg_en [GV] : set_avg_en [0];
    assign set_dly_x[GV*32 +: 32]   = indep_mode[GV] ? set_dly[GV*32 +: 32] : set_dly[31:0];
    assign set_dec_x[GV*17 +: 17]   = indep_mode[GV] ? set_dec[GV*17 +: 17] : set_dec[16:0];
  end
end
endgenerate

//=============================================================================
// Salidas
//=============================================================================
assign adc_arm_do_o       = adc_arm_do_x    ;
assign adc_rst_do_o       = adc_rst_do_x    ;
assign adc_we_keep_o      = adc_we_keep_x   ;
assign indep_mode_o       = indep_mode      ;  // sin fan-out: lo decide él mismo
assign axi_en_pulse_o     = axi_en_pulse    ;
assign set_dec1_o         = set_dec1_x      ;
assign filt_rstn_o        = filt_rstn       ;
assign set_tresh_o        = set_tresh       ;  // sin fan-out en el original
assign set_dly_o          = set_dly_x       ;
assign set_dec_o          = set_dec_x       ;
assign set_hyst_o         = set_hyst        ;  // sin fan-out en el original
assign set_avg_en_o       = set_avg_en_x    ;
assign set_filt_aa_o      = set_filt_aa     ;
assign set_filt_bb_o      = set_filt_bb     ;
assign set_filt_kk_o      = set_filt_kk     ;
assign set_filt_pp_o      = set_filt_pp     ;
assign set_filt_byp_o     = set_filt_byp    ;
assign set_deb_len_o      = set_deb_len     ;
assign set_axi_start_o    = set_axi_start   ;
assign set_axi_stop_o     = set_axi_stop    ;
assign set_axi_dly_o      = set_axi_dly     ;
assign set_axi_en_o       = set_axi_en      ;
assign set_calib_offset_o = set_calib_offset;
assign set_calib_gain_o   = set_calib_gain  ;

endmodule
