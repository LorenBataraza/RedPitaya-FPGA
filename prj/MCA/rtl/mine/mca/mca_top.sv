`timescale 1ns/1ps
//=============================================================================
// mca_top — analizador multicanal: esclavo del bus de sistema (slot 7)
//
// Base 0x4070_0000. Todo en el dominio adc_clk; el cruce a fclk[0] lo hace
// sys_bus_cdc por slot, así que acá no hace falta CDC.
//
// ACK DE LATENCIA FIJA — es lo más importante de este módulo.
//
// Un esclavo que no hace ack NO produce sólo una lectura mala: deja el CDC del
// slot DESINCRONIZADO. En sys_bus_cdc.sv, reg_done sólo avanza con bus_m.ack,
// así que sin ack queda reg_do != reg_done para siempre, el strobe de lectura
// pegado en alto, y del lado controlador ctrl_do ya no puede togglear: ese slot
// no acepta más transacciones. Al ARM lo rescata el timeout de 32 ciclos de
// rtl/axi4_slave.sv:193, que fabrica un ack por su cuenta, pero la transacción
// devuelve un valor sin sentido y SIN indicación de error.
//
// El scope tiene ese bug latente: ata bram_ack[2]/[3] = 0 para los canales no
// construidos (rp_scope_multitrigger_com.sv:572-573) y
// multitrigger_rp_scope_cfg.sv:506-507 lo usa como ack de las aperturas 3 y 4.
//
// Acá el ack sale de un shift register incondicional: NO existe ninguna ruta de
// ack por motor, así que un motor apagado por parámetro no puede colgar el bus.
// Su apertura simplemente devuelve 0. Ver docs/bus_sistema_redpitaya.md §7.1.
//
// CONTADORES DE 64 BITS. Leer lo y después hi puede partirse: a 125 MHz el
// contador avanza entre las dos lecturas. Leer la palabra BAJA congela la
// ALTA en un registro sombra, que es lo que devuelve la dirección alta.
//=============================================================================

module mca_top #(
  parameter integer DW      = 14,
  // --- espectro 1D de amplitud ---
  parameter integer EN_HIST_H     = 1,
  parameter integer H_AW          = 14,   // 16384 canales
  // --- mapa 2D amplitud x factor de forma ---
  parameter integer EN_HIST_H_PSD = 1,
  parameter integer H2_AW         = 7,    // 128 bins de amplitud
  parameter integer PSD_AW        = 6,    // 64 bins de forma
  // --- varios ---
  parameter integer AMP_W  = 16,
  parameter integer QW     = 32,
  parameter integer LEN_W  = 16
)(
  input                    adc_clk_i   ,
  input                    adc_rstn_i  ,

  // --- muestras de los dos canales (post-calib/filtro, pre-decimación) ---
  input      [2*DW-1:0]    mca_dat_i   ,
  input      [2-1:0]       mca_val_i   ,

  // --- bus de sistema ---
  input      [32-1:0]      sys_addr    ,
  input      [32-1:0]      sys_wdata   ,
  input                    sys_wen     ,
  input                    sys_ren     ,
  output reg [32-1:0]      sys_rdata   ,
  output reg               sys_err     ,
  output reg               sys_ack
);

localparam [31:0] MAGIC = 32'h4D434131;   // "MCA1"

//=============================================================================
// Registros de configuración
//=============================================================================
reg              cfg_run;
reg              cfg_chan;                // 0 = IN1, 1 = IN2
reg signed [DW-1:0] cfg_thr;
reg        [DW-1:0] cfg_hyst;
reg signed [DW-1:0] cfg_baseline;
reg              cfg_bl_auto;
reg        [3:0] cfg_bl_k;
reg [LEN_W-1:0]  cfg_bl_holdoff;
reg [LEN_W-1:0]  cfg_maxlen;
reg [LEN_W-1:0]  cfg_tail_dly;
reg              cfg_gate_mode;    // 0 = histeresis, 1 = compuertas fijas
reg [LEN_W-1:0]  cfg_gate_short;
reg [LEN_W-1:0]  cfg_gate_long;
reg [AMP_W-1:0]  cfg_amp_min;
reg [AMP_W-1:0]  cfg_amp_max;
reg              cfg_amp_src;
reg [4:0]        cfg_q_shift;
reg [4:0]        cfg_h_shift;
reg [4:0]        cfg_h2_shift;
reg [16-1:0]     cfg_dec;

// Pulsos de un ciclo generados por escritura
reg              clr_pulse;               // borra histogramas y contadores

wire sys_en = sys_wen | sys_ren;

//=============================================================================
// Decimación propia del MCA (independiente del set_dec del scope)
//=============================================================================
wire [DW-1:0] dat_sel = cfg_chan ? mca_dat_i[2*DW-1:DW] : mca_dat_i[DW-1:0];
wire          val_sel = cfg_chan ? mca_val_i[1]         : mca_val_i[0];

reg [16-1:0] dec_cnt;
wire         dec_pass = (cfg_dec <= 16'd1) || (dec_cnt >= (cfg_dec - 16'd1));
wire         dat_val  = val_sel && dec_pass;

always @(posedge adc_clk_i)
  if (!adc_rstn_i)      dec_cnt <= 16'd0;
  else if (val_sel)     dec_cnt <= dec_pass ? 16'd0 : (dec_cnt + 16'd1);

// Registro de entrada. Corta el camino que venia desde el registro de salida
// de la calibracion del scope (i_calib_ch/calib_dat_o) y atravesaba el mux de
// canal, el decimador y toda la logica de umbral del extractor: eran 34 de los
// 60 endpoints en falla del build. El MCA no tiene relacion temporal con nada
// mas, asi que un ciclo de latencia extra es gratis.
reg [DW-1:0] dat_q;
reg          val_q;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) begin
    dat_q <= {DW{1'b0}};
    val_q <= 1'b0;
  end else begin
    dat_q <= dat_sel;
    val_q <= dat_val;
  end

//=============================================================================
// Extractor de características
//=============================================================================
wire                ev_valid;
wire [AMP_W-1:0]    ev_amp;
wire [PSD_AW-1:0]   ev_psd;
wire                ev_psd_ok;
wire signed [DW-1:0] baseline_now;
wire                bl_stale, feat_busy;
wire [31:0]         c_total, c_acc, c_rej_amp, c_rej_psd, c_pileup, c_lost;
wire [QW-1:0]       last_qtot, last_qtail;

mca_pulse_feature #(
  .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .LEN_W(LEN_W),
  .EN_PSD(EN_HIST_H_PSD)
) i_feat (
  .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
  .dat_i($signed(dat_q)), .val_i(val_q),
  .cfg_run_i(cfg_run), .cnt_clr_i(clr_pulse),
  .cfg_thr_i(cfg_thr), .cfg_hyst_i(cfg_hyst),
  .cfg_baseline_i(cfg_baseline), .cfg_bl_auto_i(cfg_bl_auto),
  .cfg_bl_k_i(cfg_bl_k), .cfg_bl_holdoff_i(cfg_bl_holdoff),
  .cfg_maxlen_i(cfg_maxlen), .cfg_tail_dly_i(cfg_tail_dly),
  .cfg_gate_mode_i(cfg_gate_mode), .cfg_gate_short_i(cfg_gate_short),
  .cfg_gate_long_i(cfg_gate_long),
  .cfg_amp_min_i(cfg_amp_min), .cfg_amp_max_i(cfg_amp_max),
  .cfg_amp_src_i(cfg_amp_src), .cfg_q_shift_i(cfg_q_shift),
  .ev_valid_o(ev_valid), .ev_amp_o(ev_amp), .ev_psd_o(ev_psd),
  .ev_psd_ok_o(ev_psd_ok),
  .baseline_o(baseline_now), .baseline_stale_o(bl_stale),
  .cnt_total_o(c_total), .cnt_accepted_o(c_acc), .cnt_rej_amp_o(c_rej_amp),
  .cnt_rej_psd_o(c_rej_psd), .cnt_pileup_o(c_pileup), .cnt_lost_busy_o(c_lost),
  .last_qtot_o(last_qtot), .last_qtail_o(last_qtail),
  .busy_o(feat_busy)
);

//=============================================================================
// Cálculo de bins, con saturación (nunca envolver: un evento no puede
// aparecer en el extremo opuesto del eje)
//=============================================================================
wire [AMP_W-1:0] h_shifted  = ev_amp >> cfg_h_shift;
wire [AMP_W-1:0] h2_shifted = ev_amp >> cfg_h2_shift;

wire [H_AW-1:0]  h_bin  = (|h_shifted[AMP_W-1:H_AW])  ? {H_AW{1'b1}}  : h_shifted[H_AW-1:0];
wire [H2_AW-1:0] h2_bin = (|h2_shifted[AMP_W-1:H2_AW]) ? {H2_AW{1'b1}} : h2_shifted[H2_AW-1:0];

//=============================================================================
// Estrobo de lectura de bus: UN ciclo. sys_bus_cdc mantiene ren alto hasta el
// ack (~4 ciclos); si se pasara directo a los motores, cada acceso robaría 4
// ciclos al pipeline de incremento en vez de 1.
//=============================================================================
reg [7:0] en_sr;
always @(posedge adc_clk_i)
  if (!adc_rstn_i) en_sr <= 8'h0;
  else             en_sr <= {en_sr[6:0], sys_en};

wire rd_stb = sys_en && !en_sr[0];

// Lo mismo para la escritura: sys_bus_cdc sostiene wen hasta el ack (~5
// ciclos), así que sin estrobo cada transacción ejecutaría el case 5 veces.
// Para los registros de config sería inocuo (es idempotente), pero clr_pulse
// quedaría alto 5 ciclos en vez de uno.
wire wr_stb = sys_wen && !en_sr[0];

//=============================================================================
// Motores de histograma
//=============================================================================
wire [31:0] hist_h_data,  hist_2d_data;
wire        hist_h_busy,  hist_2d_busy;
wire [31:0] hist_h_drop,  hist_2d_drop;

generate if (EN_HIST_H) begin : g_hist_h
  mca_hist #(.AW(H_AW), .CW(32)) i_hist_h (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
    .inc_i(ev_valid), .inc_addr_i(h_bin),
    .clear_i(clr_pulse), .busy_o(hist_h_busy),
    .rd_i(rd_stb && (sys_addr[19:16] == 4'h1)), .rd_addr_i(sys_addr[H_AW+1:2]),
    .rd_data_o(hist_h_data), .dropped_o(hist_h_drop)
  );
end else begin : g_no_hist_h
  assign hist_h_data = 32'h0;
  assign hist_h_busy = 1'b0;
  assign hist_h_drop = 32'h0;
end endgenerate

generate if (EN_HIST_H_PSD) begin : g_hist_2d
  mca_hist #(.AW(H2_AW+PSD_AW), .CW(32)) i_hist_2d (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
    // Sólo entran los eventos con factor de forma válido; los rechazados por
    // el divisor siguen contando en el espectro 1D pero no en el mapa 2D.
    .inc_i(ev_valid && ev_psd_ok), .inc_addr_i({h2_bin, ev_psd}),
    .clear_i(clr_pulse), .busy_o(hist_2d_busy),
    .rd_i(rd_stb && (sys_addr[19:16] == 4'h2)),
    .rd_addr_i(sys_addr[H2_AW+PSD_AW+1:2]),
    .rd_data_o(hist_2d_data), .dropped_o(hist_2d_drop)
  );
end else begin : g_no_hist_2d
  assign hist_2d_data = 32'h0;
  assign hist_2d_busy = 1'b0;
  assign hist_2d_drop = 32'h0;
end endgenerate

wire clear_busy = hist_h_busy || hist_2d_busy;

//=============================================================================
// Relojes de adquisición
//=============================================================================
reg [63:0] realtime_cnt, livetime_cnt, deadtime_cnt;

always @(posedge adc_clk_i) begin
  if (!adc_rstn_i || clr_pulse) begin
    realtime_cnt <= 64'h0; livetime_cnt <= 64'h0; deadtime_cnt <= 64'h0;
  end else if (cfg_run) begin
    realtime_cnt <= realtime_cnt + 64'h1;
    if (feat_busy) deadtime_cnt <= deadtime_cnt + 64'h1;
    else           livetime_cnt <= livetime_cnt + 64'h1;
  end
end

//=============================================================================
// Escritura de registros
//=============================================================================
always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    cfg_run <= 1'b0; cfg_chan <= 1'b0;
    cfg_thr <= 100; cfg_hyst <= 50; cfg_baseline <= 0;
    cfg_bl_auto <= 1'b0; cfg_bl_k <= 4'd6; cfg_bl_holdoff <= 16'd0;
    cfg_maxlen <= 16'd1024; cfg_tail_dly <= 16'd4;
    cfg_gate_mode <= 1'b0; cfg_gate_short <= 16'd32; cfg_gate_long <= 16'd384;
    cfg_amp_min <= 16'd0; cfg_amp_max <= 16'hFFFF;
    cfg_amp_src <= 1'b0; cfg_q_shift <= 5'd0;
    cfg_h_shift <= 5'd0; cfg_h2_shift <= 5'd0;
    cfg_dec <= 16'd1;
    clr_pulse <= 1'b0;
  end else begin
    clr_pulse <= 1'b0;
    if (wr_stb) begin
      case (sys_addr[19:0])
        20'h0000C : begin
                      cfg_run   <= sys_wdata[0];
                      clr_pulse <= sys_wdata[1];     // autolimpiante
                      cfg_chan  <= sys_wdata[8];
                    end
        20'h00014 : cfg_thr        <= sys_wdata[DW-1:0];
        20'h00018 : cfg_hyst       <= sys_wdata[DW-1:0];
        20'h0001C : cfg_baseline   <= sys_wdata[DW-1:0];
        20'h00020 : begin
                      cfg_bl_auto    <= sys_wdata[0];
                      cfg_bl_k       <= sys_wdata[7:4];
                      cfg_bl_holdoff <= sys_wdata[31:16];
                    end
        20'h00028 : cfg_maxlen     <= sys_wdata[LEN_W-1:0];
        20'h0002C : cfg_tail_dly   <= sys_wdata[LEN_W-1:0];
        20'h00030 : cfg_amp_min    <= sys_wdata[AMP_W-1:0];
        20'h00034 : cfg_amp_max    <= sys_wdata[AMP_W-1:0];
        20'h00038 : begin
                      cfg_amp_src <= sys_wdata[0];
                      cfg_q_shift <= sys_wdata[12:8];
                    end
        20'h0003C : cfg_h_shift    <= sys_wdata[4:0];
        20'h00040 : cfg_h2_shift   <= sys_wdata[4:0];
        20'h00044 : cfg_dec        <= sys_wdata[15:0];
        20'h00048 : cfg_gate_mode  <= sys_wdata[0];
        20'h0004C : begin
          cfg_gate_short <= sys_wdata[LEN_W-1:0];
          cfg_gate_long  <= sys_wdata[16+LEN_W-1:16];
        end
        default   : ;
      endcase
    end
  end
end

//=============================================================================
// Lectura de registros
//
// sys_rdata es un registro PLANO a propósito: el set_false_path del XDC sobre
// inst_sys_bus_cdc/reg_rdata* no engancha nada (sys_bus_cdc.sv hace un assign,
// no tiene ese registro), así que el cruce de datos de lectura se timea de
// verdad y no conviene colgarle lógica combinacional ancha.
//=============================================================================
reg [31:0] rt_hi_shadow, lt_hi_shadow, dt_hi_shadow;

always @(posedge adc_clk_i) begin
  if (!adc_rstn_i) begin
    sys_ack <= 1'b0; sys_err <= 1'b0; sys_rdata <= 32'h0;
    rt_hi_shadow <= 32'h0; lt_hi_shadow <= 32'h0; dt_hi_shadow <= 32'h0;
  end else begin
    // Ack incondicional a los 4 ciclos, para CUALQUIER dirección.
    sys_ack <= en_sr[3];
    sys_err <= 1'b0;

    // Leer la palabra baja congela la alta (evita lecturas partidas)
    if (rd_stb) begin
      case (sys_addr[19:0])
        20'h00068 : rt_hi_shadow <= realtime_cnt[63:32];
        20'h00070 : lt_hi_shadow <= livetime_cnt[63:32];
        20'h00078 : dt_hi_shadow <= deadtime_cnt[63:32];
        default   : ;
      endcase
    end

    casez (sys_addr[19:0])
      // --- identificación ---
      20'h00000 : sys_rdata <= MAGIC;
      20'h00004 : sys_rdata <= {28'h0, 1'b0, 1'b0,
                                EN_HIST_H_PSD[0], EN_HIST_H[0]};
      20'h00008 : sys_rdata <= {8'h0, PSD_AW[7:0], H2_AW[7:0], H_AW[7:0]};

      // --- control y estado ---
      20'h0000C : sys_rdata <= {23'h0, cfg_chan, 6'h0, 1'b0, cfg_run};
      20'h00010 : sys_rdata <= {29'h0, bl_stale, feat_busy, clear_busy};

      // --- configuración ---
      20'h00014 : sys_rdata <= {{(32-DW){cfg_thr[DW-1]}}, cfg_thr};
      20'h00018 : sys_rdata <= {{(32-DW){1'b0}}, cfg_hyst};
      20'h0001C : sys_rdata <= {{(32-DW){cfg_baseline[DW-1]}}, cfg_baseline};
      20'h00020 : sys_rdata <= {cfg_bl_holdoff, 8'h0, cfg_bl_k, 3'h0, cfg_bl_auto};
      20'h00024 : sys_rdata <= {{(32-DW){baseline_now[DW-1]}}, baseline_now};
      20'h00028 : sys_rdata <= {{(32-LEN_W){1'b0}}, cfg_maxlen};
      20'h0002C : sys_rdata <= {{(32-LEN_W){1'b0}}, cfg_tail_dly};
      20'h00030 : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_amp_min};
      20'h00034 : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_amp_max};
      20'h00038 : sys_rdata <= {19'h0, cfg_q_shift, 7'h0, cfg_amp_src};
      20'h0003C : sys_rdata <= {27'h0, cfg_h_shift};
      20'h00040 : sys_rdata <= {27'h0, cfg_h2_shift};
      20'h00044 : sys_rdata <= {16'h0, cfg_dec};
      20'h00048 : sys_rdata <= {31'h0, cfg_gate_mode};
      20'h0004C : sys_rdata <= {cfg_gate_long, cfg_gate_short};

      // --- contadores de eventos ---
      20'h00050 : sys_rdata <= c_total;
      20'h00054 : sys_rdata <= c_acc;
      20'h00058 : sys_rdata <= c_rej_amp;
      20'h0005C : sys_rdata <= c_rej_psd;
      20'h00060 : sys_rdata <= c_pileup;
      20'h00064 : sys_rdata <= c_lost + hist_h_drop + hist_2d_drop;

      // --- relojes (64 b, con sombra en la palabra alta) ---
      20'h00068 : sys_rdata <= realtime_cnt[31:0];
      20'h0006C : sys_rdata <= rt_hi_shadow;
      20'h00070 : sys_rdata <= livetime_cnt[31:0];
      20'h00074 : sys_rdata <= lt_hi_shadow;
      20'h00078 : sys_rdata <= deadtime_cnt[31:0];
      20'h0007C : sys_rdata <= dt_hi_shadow;

      // --- último evento (depuración) ---
      20'h00080 : sys_rdata <= {{(32-AMP_W){1'b0}}, ev_amp};
      20'h00084 : sys_rdata <= {{(32-PSD_AW){1'b0}}, ev_psd};
      20'h00088 : sys_rdata <= last_qtot;
      20'h0008C : sys_rdata <= last_qtail;

      // --- aperturas de histograma ---
      20'h1???? : sys_rdata <= hist_h_data;
      20'h2???? : sys_rdata <= hist_2d_data;

      default   : sys_rdata <= 32'h0;
    endcase
  end
end

endmodule
