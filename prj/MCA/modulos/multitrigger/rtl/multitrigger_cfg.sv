`timescale 1ns/1ps
//=============================================================================
// multitrigger_cfg — región de MULTITRIGGER: esclavo del bus de sistema
//
// Base 0x4030_0000 (slot 3). Dominio adc_clk; el CDC lo hace el interconnect.
//
// Antes del refactor estos registros vivían dentro del casez de
// multitrigger_rp_scope_cfg (slot 1), mezclados con los del scope y colgados
// del mismo sys_ack que las aperturas BRAM — el mismo ack que tiene el bug
// latente de bram_ack[2]/[3] atado a cero. Al separarlos, el multitrigger deja
// de compartir esa ruta de ack.
//
// EQUIVALENCIA CON EL MAPA VIEJO (todo esto vivía en el slot 1):
//
//   0x210 -> 0x010   SHIELD_CFG
//   0x214 -> 0x014   SHIELD_STAT
//   0x218 -> 0x018   SNAPSHOT
//   0x21C -> 0x01C   DIS_FLAGS
//   0x240 -> 0x040   OR_MASK ch0   (+4 por canal)
//   0x004 -> 0x020   TRIG_SW       (estaba escondido en bits [3:0] del scope)
//   0x094 -> 0x024   TRIG_DIS_CLR  (era un offset "reservado", sin readback)
//
// Los dos últimos los conoce librp, así que además del registro propio se
// aceptan por el puente legacy (legacy_trig_sw_i / legacy_trig_dis_clr_i):
// osc_cfg sigue decodificando 0x004 y 0x094 en el slot 1 y manda acá el pulso
// ya decodificado por canal. Las dos vías se OR-ean.
//
// SEMÁNTICA PRESERVADA TAL CUAL, INCLUIDA UNA VERRUGA. sys_bus_cdc sostiene
// wen hasta el ack, así que los pulsos de abajo (adc_trig_sw, trig_dis_clr,
// new_trg_src) duran ~5 ciclos, no uno. Es el comportamiento que tenía el
// módulo original y del que depende la lógica aguas abajo; convertirlos en
// estrobos de un ciclo es un cambio deliberado y aparte, no algo que deba
// colarse en una mudanza de registros.
//=============================================================================

module multitrigger_cfg #(
  parameter [31:0]  MAGIC    = 32'h4D545247,  // "MTRG"
  parameter integer N_CH     = 2,
  parameter integer SRC_W    = 32,
  parameter integer SHIELD_N = 4
)(
  input                    adc_clk_i  ,
  input                    adc_rstn_i ,

  // --- estado desde el resto del scope (para readback) ---
  input      [   4*8 -1:0] trg_state_i        , // máscara activa, 8 b por canal
  input      [   4  -1:0]  adc_trg_dis_act_i  ,
  input      [   4  -1:0]  adc_we_keep_i      ,
  input      [   4  -1:0]  indep_mode_i       ,
  input      [  16  -1:0]  shield_cnt_i       ,
  input                    shield_active_i    ,
  input      [  17  -1:0]  trig_snapshot_i    ,

  // --- puente legacy desde osc_cfg (offsets 0x004 y 0x094 del slot 1) ---
  input      [   4  -1:0]  legacy_trig_sw_i      ,
  input      [   4  -1:0]  legacy_trig_dis_clr_i ,

  // --- salidas hacia multitrigger_event_logic ---
  output     [   4  -1:0]  adc_trig_sw_o  ,
  output     [   4  -1:0]  trig_dis_clr_o ,
  output     [   4  -1:0]  new_trg_src_o  ,
  output     [4*32  -1:0]  trg_src_o      ,
  output     [   4  -1:0]  shield_src_o   ,
  output     [   4  -1:0]  shield_dst_o   ,
  output     [  16  -1:0]  shield_dur_o   ,

  // --- bus de sistema ---
  input      [  32  -1:0]  sys_addr   ,
  input      [  32  -1:0]  sys_wdata  ,
  input                    sys_wen    ,
  input                    sys_ren    ,
  output reg [  32  -1:0]  sys_rdata  ,
  output reg               sys_err    ,
  output reg               sys_ack
);

wire sys_en = sys_wen | sys_ren;

//=============================================================================
// Config del trigger_shield (0x010) y máscaras OR por canal (0x040 + 4*ch)
//=============================================================================
reg [ 4-1:0] shield_src ;
reg [ 4-1:0] shield_dst ;
reg [16-1:0] shield_dur ;

// Copia almacenada de la máscara, para 4 canales aunque N_CH < 4: es lo que
// devuelve el readback, y refleja siempre el último write del software
// independientemente del lifecycle de set_trig_src en multitrigger_trig_src.
reg [4*32-1:0] trg_src_stored;

always @(posedge adc_clk_i)
if (!adc_rstn_i) begin
  shield_src <=  4'h0;
  shield_dst <=  4'h0;
  shield_dur <= 16'h0;
end else if (sys_wen && (sys_addr[19:0] == 20'h010)) begin
  shield_src <= sys_wdata[ 3: 0];
  shield_dst <= sys_wdata[11: 8];
  shield_dur <= sys_wdata[31:16];
end

genvar GA;
generate
for (GA = 0; GA < 4; GA = GA + 1) begin : g_trg_src_store
  always @(posedge adc_clk_i)
  if (!adc_rstn_i)
    trg_src_stored[GA*32 +: 32] <= 32'h0;
  else if (sys_wen && (sys_addr[19:0] == (20'h040 + GA*4)))
    trg_src_stored[GA*32 +: 32] <= sys_wdata[31:0];
end
endgenerate

//=============================================================================
// Pulsos por canal.
//
// Combinacionales sobre sys_wen, igual que en el módulo original: duran lo que
// dura la transacción (~5 ciclos). Ver la nota de la cabecera.
//
// new_trg_src se emite en CUALQUIER escritura a la dirección de la máscara,
// incluso con wdata = 0, para poder limpiarla explícitamente.
//=============================================================================
wire [4-1:0] trig_sw_reg  ;
wire [4-1:0] dis_clr_reg  ;
wire [4-1:0] new_trg_src  ;
wire [4*32-1:0] trg_src   ;

genvar GV;
generate
for (GV = 0; GV < 4; GV = GV + 1) begin : g_pulsos
  // Registro propio: un bit por canal (más limpio que el byte-por-canal del
  // mapa viejo, que se sigue aceptando por el puente legacy).
  assign trig_sw_reg[GV] = sys_wen && (sys_addr[19:0] == 20'h020) && sys_wdata[GV];
  assign dis_clr_reg[GV] = sys_wen && (sys_addr[19:0] == 20'h024) && sys_wdata[GV];

  assign new_trg_src[GV] = sys_wen && (sys_addr[19:0] == (20'h040 + GV*4));
  assign trg_src[GV*32 +: 32] = sys_wdata[31:0];
end
endgenerate

// Las dos vías (registro propio + puente legacy del slot 1) se OR-ean.
wire [4-1:0] adc_trig_sw  = trig_sw_reg | legacy_trig_sw_i;
wire [4-1:0] trig_dis_clr = dis_clr_reg | legacy_trig_dis_clr_i;

//=============================================================================
// Fan-out por indep_mode: sin modo independiente, todos los canales siguen al
// canal 0. Idéntico al bloque *_x del módulo original.
//=============================================================================
wire [4-1:0]    adc_trig_sw_x ;
wire [4-1:0]    trig_dis_clr_x;
wire [4-1:0]    new_trg_src_x ;
wire [4*32-1:0] trg_src_x     ;

genvar GL;
generate
for (GL = 0; GL < 4; GL = GL + 1) begin : g_fanout
  if (GL == 0) begin : g_ch0
    assign adc_trig_sw_x [GL]         = adc_trig_sw [GL];
    assign trig_dis_clr_x[GL]         = trig_dis_clr[GL];
    assign new_trg_src_x [GL]         = new_trg_src [GL];
    assign trg_src_x[GL*32 +: 32]     = trg_src[GL*32 +: 32];
  end else begin : g_chn
    assign adc_trig_sw_x [GL]         = indep_mode_i[GL] ? adc_trig_sw [GL] : adc_trig_sw [0];
    assign trig_dis_clr_x[GL]         = indep_mode_i[GL] ? trig_dis_clr[GL] : trig_dis_clr[0];
    assign new_trg_src_x [GL]         = indep_mode_i[GL] ? new_trg_src [GL] : new_trg_src [0];
    assign trg_src_x[GL*32 +: 32]     = indep_mode_i[GL] ? trg_src[GL*32 +: 32] : trg_src[31:0];
  end
end
endgenerate

assign adc_trig_sw_o  = adc_trig_sw_x ;
assign trig_dis_clr_o = trig_dis_clr_x;
assign new_trg_src_o  = new_trg_src_x ;
assign trg_src_o      = trg_src_x     ;
assign shield_src_o   = shield_src    ;
assign shield_dst_o   = shield_dst    ;
assign shield_dur_o   = shield_dur    ;

//=============================================================================
// Estrobo y ack de latencia fija — mismo contrato que mca_top: 4 ciclos para
// CUALQUIER dirección, mapeada o no, desde un shift register incondicional.
//=============================================================================
reg [7:0] en_sr;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) en_sr <= 8'h0;
  else             en_sr <= {en_sr[6:0], sys_en};

always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    sys_ack <= 1'b0; sys_err <= 1'b0; sys_rdata <= 32'h0;
  end else begin
    sys_ack <= en_sr[3];
    sys_err <= 1'b0;

    casez (sys_addr[19:0])
      // --- identificación ---
      20'h00000 : sys_rdata <= MAGIC;
      20'h00004 : sys_rdata <= {16'h0, SHIELD_N[3:0], SRC_W[7:0], N_CH[3:0]};

      // --- trigger_shield ---
      20'h00010 : sys_rdata <= {shield_dur, 4'h0, shield_dst, 4'h0, shield_src};
      20'h00014 : sys_rdata <= {{32-17{1'b0}}, shield_active_i, shield_cnt_i};

      // --- snapshot y flags ---
      20'h00018 : sys_rdata <= {{32-17{1'b0}}, trig_snapshot_i};
      20'h0001C : sys_rdata <= {24'h0, adc_we_keep_i[3:0], adc_trg_dis_act_i[3:0]};

      // --- comandos (sin estado propio: el readback devuelve 0) ---
      20'h00020 : sys_rdata <= 32'h0;
      20'h00024 : sys_rdata <= 32'h0;

      // --- máscara activa, 8 b por canal ---
      20'h00028 : sys_rdata <= trg_state_i;

      // --- máscaras OR configuradas (cubre ch0..ch3 aunque N_CH < 4) ---
      20'h00040 : sys_rdata <= trg_src_stored[0*32 +: 32];
      20'h00044 : sys_rdata <= trg_src_stored[1*32 +: 32];
      20'h00048 : sys_rdata <= trg_src_stored[2*32 +: 32];
      20'h0004C : sys_rdata <= trg_src_stored[3*32 +: 32];

      default   : sys_rdata <= 32'h0;
    endcase
  end
end

endmodule
