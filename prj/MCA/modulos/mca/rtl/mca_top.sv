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
// Su apertura simplemente devuelve 0. Ver docs/TOP/bus_sistema_redpitaya.md §7.1.
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
  parameter integer LEN_W  = 16,
  parameter integer DIV_W  = 16,   // bits de cociente de los divisores de forma
  parameter integer NFEAT  = 16    // ranuras del bus de features
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
// DEPRECADOS. Se siguen decodificando —se escriben y se leen— para que el
// software viejo no vea errores, pero YA NO AFECTAN AL DATAPATH: el eje pasó de
// `amp >> h_shift` a "feature normalizada, los AW bits altos de la ventana de
// zoom". Se conservan en vez de borrarse porque hay datos guardados con ese
// metadato; la conversión canal->volts vive en counts_to_volts(h_aw=...).
reg [4:0]        cfg_h_shift;      // sin efecto: lo subsume cfg_zoom_1d
reg [4:0]        cfg_h2_shift;     // sin efecto: lo subsume cfg_zoom_2dx
// Que feature alimenta cada eje. Los indices son los localparam F_* de
// mca_pulse_feature: un solo espacio de numeracion para los tres ejes.
reg [3:0]        cfg_sel_1d, cfg_sel_2dx, cfg_sel_2dy;
// Zoom por eje: {k[15:8], z[3:0]}. z=0 es fondo de escala, o sea el
// comportamiento historico.
reg [3:0]        cfg_z_1d,  cfg_z_2dx,  cfg_z_2dy;
reg [7:0]        cfg_k_1d,  cfg_k_2dx,  cfg_k_2dy;
reg [16-1:0]     cfg_dec;
reg              cfg_keep_full;   // 1 = seguir contando con el histograma lleno
// Discriminador: una condicion sobre una feature elegida.
reg              cfg_discr_en, cfg_discr_out;
reg [3:0]        cfg_discr_sel;
reg [AMP_W-1:0]  cfg_discr_min, cfg_discr_max;
reg [31:0]       cnt_rej_discr;

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

wire [NFEAT*AMP_W-1:0] ev_feat;

mca_pulse_feature #(
  .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .DIV_W(DIV_W),
  .NFEAT(NFEAT), .LEN_W(LEN_W), .EN_PSD(EN_HIST_H_PSD)
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
  .ev_psd_ok_o(ev_psd_ok), .ev_feat_o(ev_feat),
  .baseline_o(baseline_now), .baseline_stale_o(bl_stale),
  .cnt_total_o(c_total), .cnt_accepted_o(c_acc), .cnt_rej_amp_o(c_rej_amp),
  .cnt_rej_psd_o(c_rej_psd), .cnt_pileup_o(c_pileup), .cnt_lost_busy_o(c_lost),
  .last_qtot_o(last_qtot), .last_qtail_o(last_qtail),
  .busy_o(feat_busy)
);

//=============================================================================
// De feature a bin: MUX de eje + ZOOM
//
// El bus de features es INTERNO: no sale al software. El ARM sigue leyendo las
// mismas aperturas 0x10000 y 0x20000. Lo unico que cambia del lado del software
// es un registro que dice que feature alimenta cada eje.
//
// El mux 16:1 y el zoom viven DESPUES del registro ev_feat_o del extractor, o
// sea que arrancan un camino nuevo en vez de alargar el del cierre —que es el
// que esta en falla de timing (WNS -0.294 ns).
//
// La saturacion sigue siendo el contrato: un evento nunca aparece en el extremo
// opuesto del eje. Con zoom, ademas, los bins de los extremos hacen de
// indicadores de desborde de la ventana, que con la deriva medida importa (a
// z=3 un corrimiento del 6.45 % mueve el pico un 41 % del ancho de ventana).
//=============================================================================
// El mux va como part-select indexada y NO como function. Con una function en
// un assign continuo, la sensibilidad se arma con los ARGUMENTOS: `ev_feat` se
// lee del alcance exterior y no entra en la lista, asi que la salida solo se
// actualizaba al cambiar el selector y se quedaba clavada en el valor de reset.
// El sintetizador lo resolvia bien y la simulacion no: lo agarro tb_mca_top con
// las cuentas apareciendo en el canal 0.
wire [AMP_W-1:0] f_1d  = ev_feat[cfg_sel_1d  * AMP_W +: AMP_W];
wire [AMP_W-1:0] f_2dx = ev_feat[cfg_sel_2dx * AMP_W +: AMP_W];
wire [AMP_W-1:0] f_2dy = ev_feat[cfg_sel_2dy * AMP_W +: AMP_W];

//=============================================================================
// Discriminador. Va DESPUES de los divisores para que el selector alcance a las
// features de forma; el detalle esta en mca_discriminator.sv.
//=============================================================================
wire discr_ok;

mca_discriminator #(.FW(AMP_W), .NFEAT(NFEAT)) i_discr (
  .ev_feat_i(ev_feat), .cfg_en_i(cfg_discr_en), .cfg_sel_i(cfg_discr_sel),
  .cfg_out_i(cfg_discr_out), .cfg_min_i(cfg_discr_min),
  .cfg_max_i(cfg_discr_max), .accept_o(discr_ok)
);

// Un evento rechazado por el discriminador NO entra a ningun motor, y se cuenta
// aparte de cnt_rej_amp: son dos criterios distintos y hay que poder atribuir
// la perdida a cada uno.
wire ev_hist = ev_valid && discr_ok;

always @(posedge adc_clk_i)
  if (!adc_rstn_i || clr_pulse)   cnt_rej_discr <= 32'h0;
  else if (ev_valid && !discr_ok) cnt_rej_discr <= cnt_rej_discr + 32'h1;

wire [H_AW-1:0]  h_bin;
wire [H2_AW-1:0] h2_bin;
wire [PSD_AW-1:0] h2y_bin;

mca_zoom #(.FW(AMP_W), .AW(H_AW))   i_zoom_1d
  (.feat_i(f_1d),  .z_i(cfg_z_1d),  .k_i(cfg_k_1d),  .bin_o(h_bin));
mca_zoom #(.FW(AMP_W), .AW(H2_AW))  i_zoom_2dx
  (.feat_i(f_2dx), .z_i(cfg_z_2dx), .k_i(cfg_k_2dx), .bin_o(h2_bin));
mca_zoom #(.FW(AMP_W), .AW(PSD_AW)) i_zoom_2dy
  (.feat_i(f_2dy), .z_i(cfg_z_2dy), .k_i(cfg_k_2dy), .bin_o(h2y_bin));

//-----------------------------------------------------------------------------
// ETAPA DE PIPELINE entre el zoom y los motores. Es obligatoria, y el motivo se
// midio: sin ella el camino ev_feat_o -> mem de mca_hist tiene DIEZ niveles de
// logica (mux 16:1 + barrel shifter del zoom + comparador + mux de saturacion +
// decodificacion de direccion) y la sintesis paso de WNS -0.294 ns / 49
// endpoints a -0.571 / 166, con los 166 en ESE camino.
//
// El razonamiento que fallo, por si vuelve a tentar: "el mux sale de un
// registro, asi que arranca un camino nuevo". Es cierto y es irrelevante — lo
// que importa no es de donde arranca sino cuanta logica hay HASTA el proximo
// registro, y el destino es la direccion de una BRAM.
//
// Cuesta un ciclo mas de latencia entre el evento y su escritura al histograma.
// No hay nada que dependa de cuando ocurre esa escritura, asi que es gratis.
// `inc` y las tres direcciones se registran JUNTOS: si se desalinearan, el
// evento se contaria en el bin del evento anterior.
//-----------------------------------------------------------------------------
reg [H_AW-1:0]   h_bin_q;
reg [H2_AW-1:0]  h2_bin_q;
reg [PSD_AW-1:0] h2y_bin_q;
reg              ev_hist_q, ev_psd_ok_q;

always @(posedge adc_clk_i)
  if (!adc_rstn_i) begin
    h_bin_q <= {H_AW{1'b0}}; h2_bin_q <= {H2_AW{1'b0}};
    h2y_bin_q <= {PSD_AW{1'b0}};
    ev_hist_q <= 1'b0; ev_psd_ok_q <= 1'b0;
  end else begin
    h_bin_q   <= h_bin;
    h2_bin_q  <= h2_bin;
    h2y_bin_q <= h2y_bin;
    ev_hist_q <= ev_hist;
    ev_psd_ok_q <= ev_psd_ok;
  end

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
wire        hist_h_full,  hist_2d_full;
wire [31:0] hist_h_supp,  hist_2d_supp;

generate if (EN_HIST_H) begin : g_hist_h
  mca_hist #(.AW(H_AW), .CW(32)) i_hist_h (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
    .inc_i(ev_hist_q), .inc_addr_i(h_bin_q),
    .clear_i(clr_pulse), .busy_o(hist_h_busy),
    .cfg_keep_i(cfg_keep_full), .full_o(hist_h_full),
    .rd_i(rd_stb && (sys_addr[19:16] == 4'h1)), .rd_addr_i(sys_addr[H_AW+1:2]),
    .rd_data_o(hist_h_data), .dropped_o(hist_h_drop),
    .suppressed_o(hist_h_supp)
  );
end else begin : g_no_hist_h
  assign hist_h_data = 32'h0;
  assign hist_h_busy = 1'b0;
  assign hist_h_drop = 32'h0;
  assign hist_h_full = 1'b0;
  assign hist_h_supp = 32'h0;
end endgenerate

generate if (EN_HIST_H_PSD) begin : g_hist_2d
  mca_hist #(.AW(H2_AW+PSD_AW), .CW(32)) i_hist_2d (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
    // Sólo entran los eventos con factor de forma válido; los rechazados por
    // el divisor siguen contando en el espectro 1D pero no en el mapa 2D.
    .inc_i(ev_hist_q && ev_psd_ok_q), .inc_addr_i({h2_bin_q, h2y_bin_q}),
    .clear_i(clr_pulse), .busy_o(hist_2d_busy),
    .cfg_keep_i(cfg_keep_full), .full_o(hist_2d_full),
    .rd_i(rd_stb && (sys_addr[19:16] == 4'h2)),
    .rd_addr_i(sys_addr[H2_AW+PSD_AW+1:2]),
    .rd_data_o(hist_2d_data), .dropped_o(hist_2d_drop),
    .suppressed_o(hist_2d_supp)
  );
end else begin : g_no_hist_2d
  assign hist_2d_data = 32'h0;
  assign hist_2d_busy = 1'b0;
  assign hist_2d_drop = 32'h0;
  assign hist_2d_full = 1'b0;
  assign hist_2d_supp = 32'h0;
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
    // Defaults = comportamiento historico: eje 1D con la amplitud de PICO
    // (§5 del doc de diseno), eje X del 2D tambien amplitud, eje Y el factor de
    // forma, y zoom en cero (fondo de escala) en los tres.
    cfg_sel_1d <= 4'd0; cfg_sel_2dx <= 4'd0; cfg_sel_2dy <= 4'd2;
    cfg_z_1d <= 4'd0; cfg_z_2dx <= 4'd0; cfg_z_2dy <= 4'd0;
    cfg_k_1d <= 8'd0; cfg_k_2dx <= 8'd0; cfg_k_2dy <= 8'd0;
    cfg_dec <= 16'd1; cfg_keep_full <= 1'b0;
    cfg_discr_en <= 1'b0; cfg_discr_out <= 1'b0; cfg_discr_sel <= 4'd0;
    cfg_discr_min <= {AMP_W{1'b0}}; cfg_discr_max <= {AMP_W{1'b1}};
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
                      // COMPATIBILIDAD: cfg_amp_src era el selector de
                      // estimador del eje 1D. Ahora eso lo dice cfg_sel_1d, y
                      // escribir el registro viejo lo sigue moviendo, asi que
                      // toda la campana de caracterizacion existente anda sin
                      // tocarla. F_PEAK = 0, F_INT = 1.
                      cfg_sel_1d  <= sys_wdata[0] ? 4'd1 : 4'd0;
                      cfg_sel_2dx <= sys_wdata[0] ? 4'd1 : 4'd0;
                    end
        20'h0003C : cfg_h_shift    <= sys_wdata[4:0];
        20'h00040 : cfg_h2_shift   <= sys_wdata[4:0];
        20'h00044 : cfg_dec        <= sys_wdata[15:0];
        20'h000A4 : cfg_keep_full  <= sys_wdata[0];
        20'h00098 : begin
                      cfg_discr_en  <= sys_wdata[0];
                      cfg_discr_out <= sys_wdata[1];
                      cfg_discr_sel <= sys_wdata[7:4];
                    end
        20'h0009C : cfg_discr_min <= sys_wdata[AMP_W-1:0];
        20'h000A0 : cfg_discr_max <= sys_wdata[AMP_W-1:0];
        20'h00048 : cfg_gate_mode  <= sys_wdata[0];
        20'h0004C : begin
          cfg_gate_short <= sys_wdata[LEN_W-1:0];
          cfg_gate_long  <= sys_wdata[16+LEN_W-1:16];
        end
        // Que feature alimenta cada eje. Escribir aca GANA sobre cfg_amp_src,
        // porque es el registro nuevo y explicito.
        20'h00090 : begin
          cfg_sel_1d  <= sys_wdata[3:0];
          cfg_sel_2dx <= sys_wdata[7:4];
          cfg_sel_2dy <= sys_wdata[11:8];
        end
        // Zoom por eje: {k[15:8], z[3:0]}. z=0 = fondo de escala.
        20'h00094 : begin cfg_z_1d  <= sys_wdata[3:0]; cfg_k_1d  <= sys_wdata[15:8]; end
        20'h000B8 : begin cfg_z_2dx <= sys_wdata[3:0]; cfg_k_2dx <= sys_wdata[15:8]; end
        20'h000BC : begin cfg_z_2dy <= sys_wdata[3:0]; cfg_k_2dy <= sys_wdata[15:8]; end
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
      20'h00098 : sys_rdata <= {24'h0, cfg_discr_sel, 2'h0,
                                cfg_discr_out, cfg_discr_en};
      20'h0009C : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_discr_min};
      20'h000A0 : sys_rdata <= {{(32-AMP_W){1'b0}}, cfg_discr_max};
      20'h000A4 : sys_rdata <= {31'h0, cfg_keep_full};
      20'h000AC : sys_rdata <= cnt_rej_discr;
      20'h000A8 : sys_rdata <= {30'h0, hist_2d_full, hist_h_full};
      20'h000B0 : sys_rdata <= hist_h_supp + hist_2d_supp;
      20'h00048 : sys_rdata <= {31'h0, cfg_gate_mode};
      20'h0004C : sys_rdata <= {cfg_gate_long, cfg_gate_short};
      20'h00090 : sys_rdata <= {20'h0, cfg_sel_2dy, cfg_sel_2dx, cfg_sel_1d};
      20'h00094 : sys_rdata <= {16'h0, cfg_k_1d,  4'h0, cfg_z_1d };
      20'h000B8 : sys_rdata <= {16'h0, cfg_k_2dx, 4'h0, cfg_z_2dx};
      20'h000BC : sys_rdata <= {16'h0, cfg_k_2dy, 4'h0, cfg_z_2dy};

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
