`timescale 1ns/1ps
//=============================================================================
// event_ring_top — ring de slots de evento en DDR. Esclavo del bus de sistema.
//
// Reemplaza el ciclo "capturar -> congelar -> que el PS lea por GP0 -> re-armar"
// (K=1, tau = 252.7 us) por una COLA productor/consumidor de N_SLOTS eventos en
// DDR. El PS deja de estar en el camino critico: el HW sigue capturando
// mientras el PS drena.
//
// ACK DE LATENCIA FIJA, igual que mca_top: el ack sale de un shift register
// incondicional, sin ninguna ruta de ack por sub-bloque. Un esclavo que no hace
// ack no produce solo una lectura mala — deja el CDC del slot desincronizado y
// ese slot no acepta mas transacciones (ver docs/TOP/bus_sistema_redpitaya.md 7.1,
// y el bug latente de bram_ack[2]/[3] en el scope).
//
// UN SOLO DOMINIO DE RELOJ. En rp_scope_multitrigger_com.sv:686 hay
// `assign axi_clk = adc_clk_i`, y el bus llega ya sincronizado a adc_clk por
// sys_bus_cdc. O sea captura, writer y registros comparten adc_clk: no hace
// falta ningun CDC ni codificacion Gray entre WR_SLOT y RD_SLOT.
//
// COMO LEE EL PS (importante, porque define el techo de tasa):
//   1. No necesita leer NINGUN registro por GP0 en el lazo caliente. Polea el
//      FOOTER del proximo slot directamente en DDR: la ultima palabra del slot
//      vale {~seq, seq}. Cuando las dos mitades son complementarias y seq es el
//      esperado, el slot esta completo (ver event_slot_writer.sv).
//   2. Consume el batch.
//   3. Publica RD_SLOT una vez POR BATCH, no por evento. Publicarlo por evento
//      devolveria el GP0 al camino critico, que es exactamente lo que se
//      esta sacando.
//
// GEOMETRIA CONGELADA EN STOPPED. SLOT_BASE / RING_SZ / SLOT_SHIFT / PRE / POST
// solo latchean con la adquisicion parada, para que nunca convivan dos
// geometrias en el mismo ring. Escribirlos corriendo se ignora y levanta
// err_cfg (sticky).
//=============================================================================

module event_ring_top #(
  parameter integer DW      = 14,
  parameter integer N_CH    = 2,
  parameter integer SW      = 16,
  parameter integer PRE_AW  = 9,    // pre-buffer: 512 muestras
  parameter integer S_AW    = 11,
  parameter integer DATA_AW = 12,   // stage: 4096 muestras (~2 RAMB36)
  parameter integer E       = 4,    // eventos en vuelo en el stage
  parameter integer FIFO_FW = 8     // profundidad del axi_wr_fifo (2^FW)
)(
  input                    adc_clk_i,
  input                    adc_rstn_i,

  // --- muestras y trigger (del scope) --------------------------------------
  input      [N_CH*DW-1:0] dat_i,
  input                    dv_i,
  input                    trig_i,
  input      [16:0]        snapshot_i,

  // --- AXI master hacia el puerto HP ---------------------------------------
  output     [32-1:0]      axi_waddr_o,
  output     [64-1:0]      axi_wdata_o,
  output     [ 8-1:0]      axi_wsel_o,
  output     [ 3-1:0]      axi_wsize_o,
  output                   axi_wvalid_o,
  output     [ 4-1:0]      axi_wlen_o,
  output                   axi_wfixed_o,
  input                    axi_werr_i,
  input                    axi_wrdy_i,

  // --- bus de sistema ------------------------------------------------------
  input      [32-1:0]      sys_addr,
  input      [32-1:0]      sys_wdata,
  input                    sys_wen,
  input                    sys_ren,
  output reg [32-1:0]      sys_rdata,
  output reg               sys_err,
  output reg               sys_ack
);

  localparam [31:0] MAGIC = 32'h45564E54;   // "EVNT"

  //--------------------------------------------------------------------------
  // FSM global de adquisicion
  //--------------------------------------------------------------------------
  localparam [1:0] G_STOPPED  = 2'd0,
                   G_RUNNING  = 2'd1,
                   G_DRAINING = 2'd2;

  reg [1:0] gst;

  reg        cfg_run;        // pedido de software
  reg        cfg_clr;        // pulso de limpieza

  wire       wr_busy, cap_busy;
  wire       stopped = (gst == G_STOPPED);

  //--------------------------------------------------------------------------
  // Registros de configuracion (latchean solo en STOPPED)
  //--------------------------------------------------------------------------
  reg [31:0] slot_base;
  reg [31:0] ring_sz;
  reg [4:0]  slot_shift;
  reg [S_AW-1:0] pre_n, post_n;
  reg        err_cfg;        // sticky: escritura de geometria corriendo

  wire [31:0] n_slots = (ring_sz >> slot_shift);
  wire [S_AW+2:0] win_len = ({{3{1'b0}}, pre_n} + {{3{1'b0}}, post_n}) * N_CH;

  //--------------------------------------------------------------------------
  // Timestamp libre. Se resetea al arrancar, asi el t=0 de la corrida es el
  // arranque y los timestamps de los eventos son directamente comparables.
  //--------------------------------------------------------------------------
  reg [63:0] ts_cnt;
  always @(posedge adc_clk_i) begin
    if (!adc_rstn_i || (gst == G_STOPPED)) ts_cnt <= 64'h0;
    else if (dv_i)                          ts_cnt <= ts_cnt + 1'b1;
  end

  //--------------------------------------------------------------------------
  // Creditos. Contadores LIBRES de 32 b: la resta en modulo 2^32 da la
  // ocupacion correcta aunque hayan dado vueltas, mientras N_SLOTS < 2^31.
  //--------------------------------------------------------------------------
  wire [31:0] wr_slot;
  reg  [31:0] rd_slot;
  wire [31:0] occupied  = wr_slot - rd_slot;
  wire        credit_ok = (occupied < n_slots);

  //--------------------------------------------------------------------------
  // Captura de ventana
  //--------------------------------------------------------------------------
  wire            cap_sof, cap_eof, cap_val;
  wire [SW-1:0]   cap_dat;
  wire [63:0]     cap_ts;
  wire [16:0]     cap_snap;
  wire [S_AW-1:0] cap_nsamp;
  wire            cap_drop_busy, cap_drop_full;
  wire            stg_accept;

  event_window_capture #(
    .DW(DW), .N_CH(N_CH), .SW(SW), .PRE_AW(PRE_AW), .S_AW(S_AW)
  ) i_capture (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i),
    // En DRAINING sigue drenando pero ya no acepta triggers: asi la parada no
    // trunca la ventana en vuelo.
    .run_i(gst != G_STOPPED), .accept_trig_i(gst == G_RUNNING),
    .pre_i(pre_n), .post_i(post_n),
    .dat_i(dat_i), .dv_i(dv_i),
    .trig_i(trig_i), .snapshot_i(snapshot_i), .ts_i(ts_cnt),
    .m_sof_o(cap_sof), .m_eof_o(cap_eof), .m_val_o(cap_val), .m_dat_o(cap_dat),
    .m_accept_i(stg_accept),
    .m_ts_o(cap_ts), .m_snap_o(cap_snap), .m_nsamp_o(cap_nsamp),
    .drop_busy_o(cap_drop_busy), .drop_full_o(cap_drop_full), .busy_o(cap_busy)
  );

  //--------------------------------------------------------------------------
  // Stage elastico
  //--------------------------------------------------------------------------
  wire            stg_meta_val, stg_meta_rd, stg_dat_rd;
  wire [63:0]     stg_ts;
  wire [16:0]     stg_snap;
  wire [S_AW-1:0] stg_nsamp;
  wire [SW-1:0]   stg_dat;
  wire [DATA_AW:0] stg_lvl;
  wire [$clog2(E+1)-1:0] stg_ev_lvl;
  wire            flush = (gst == G_STOPPED) || cfg_clr;

  event_stage_fifo #(
    .SW(SW), .S_AW(S_AW), .DATA_AW(DATA_AW), .E(E)
  ) i_stage (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i), .flush_i(flush),
    .win_len_i(win_len),
    .s_accept_o(stg_accept), .s_val_i(cap_val), .s_sof_i(cap_sof),
    .s_eof_i(cap_eof), .s_dat_i(cap_dat), .s_ts_i(cap_ts),
    .s_snap_i(cap_snap), .s_nsamp_i(cap_nsamp),
    .m_meta_val_o(stg_meta_val), .m_ts_o(stg_ts), .m_snap_o(stg_snap),
    .m_nsamp_o(stg_nsamp), .m_meta_rd_i(stg_meta_rd),
    .m_dat_o(stg_dat), .m_dat_rd_i(stg_dat_rd),
    .lvl_o(stg_lvl), .ev_lvl_o(stg_ev_lvl)
  );

  //--------------------------------------------------------------------------
  // Writer de slots
  //--------------------------------------------------------------------------
  wire [63:0] wr_dat;
  wire        wr_val, wr_rdy;
  wire [31:0] seq;
  wire        no_credit, err_slot_ovf;

  event_slot_writer #(
    .SW(SW), .S_AW(S_AW), .N_CH(N_CH)
  ) i_writer (
    .clk_i(adc_clk_i), .rstn_i(adc_rstn_i), .flush_i(flush), .clr_cnt_i(flush),
    .slot_shift_i(slot_shift),
    .s_meta_val_i(stg_meta_val), .s_ts_i(stg_ts), .s_snap_i(stg_snap),
    .s_nsamp_i(stg_nsamp), .s_meta_rd_o(stg_meta_rd),
    .s_dat_i(stg_dat), .s_dat_rd_o(stg_dat_rd),
    .credit_ok_i(credit_ok),
    .wr_dat_o(wr_dat), .wr_val_o(wr_val), .wr_rdy_i(wr_rdy),
    .wr_slot_o(wr_slot), .seq_o(seq),
    .no_credit_o(no_credit), .busy_o(wr_busy), .err_slot_ovf_o(err_slot_ovf)
  );

  //--------------------------------------------------------------------------
  // Contrapresion del axi_wr_fifo.
  //
  // axi_wr_fifo NO expone su fill_lvl y DESCARTA en silencio si se empuja lleno
  // (solo levanta stat_overflow_o). Asi que se lleva una sombra propia:
  //   occ = empujes - palabras aceptadas por el master
  // Entre el pop interno y la aceptacion del master hay una palabra en vuelo
  // (data_in_reg), asi que esta cuenta SOBREESTIMA la ocupacion real. Es
  // deliberado: sobreestimar frena de mas, subestimar corrompe.
  //--------------------------------------------------------------------------
  localparam integer FIFO_N = (1 << FIFO_FW);
  reg [FIFO_FW:0] fifo_occ;
  wire fifo_push = wr_val && wr_rdy;
  wire fifo_pop  = axi_wvalid_o && axi_wrdy_i;

  always @(posedge adc_clk_i) begin
    if (!adc_rstn_i || flush) fifo_occ <= '0;
    else case ({fifo_push, fifo_pop})
      2'b10:   fifo_occ <= fifo_occ + 1'b1;
      2'b01:   fifo_occ <= fifo_occ - 1'b1;
      default: ;
    endcase
  end
  // Margen de 8 palabras: cubre las que puedan estar en vuelo dentro del master.
  assign wr_rdy = (fifo_occ < (FIFO_N - 8));

  //--------------------------------------------------------------------------
  // axi_wr_fifo -> axi_master -> puerto HP
  //--------------------------------------------------------------------------
  wire [31:0] axi_cur_addr;
  wire        axi_ovf;

  axi_wr_fifo #(
    .DW(64), .AW(32), .FW(FIFO_FW), .BYTE_SEL(0)
  ) i_axi_fifo (
    .axi_clk_i          (adc_clk_i),
    .axi_rstn_i         (adc_rstn_i),
    .axi_waddr_o        (axi_waddr_o),
    .axi_wdata_o        (axi_wdata_o),
    .axi_wsel_o         (axi_wsel_o),
    .axi_wsize_o        (axi_wsize_o),
    .axi_wvalid_o       (axi_wvalid_o),
    .axi_wlen_o         (axi_wlen_o),
    .axi_wfixed_o       (axi_wfixed_o),
    .axi_werr_i         (axi_werr_i),
    .axi_wrdy_i         (axi_wrdy_i),
    .wr_data_i          (wr_dat),
    .wr_byte_val_i      (8'hFF),
    .wr_size_i          (3'h3),          // 8 bytes
    .wr_val_i           (fifo_push),
    .ctrl_start_addr_i  (slot_base),
    // stop_addr es INCLUSIVO: axi_wr_fifo.v:283 envuelve cuando
    // axi_waddr_o == stop_addr, o sea que ESCRIBE en esa direccion antes de
    // volver al principio. Sin el -8 el ring pisa la primera palabra que sigue
    // a la region reservada.
    .ctrl_stop_addr_i   (slot_base + ring_sz - 32'd8),
    // 4'hF es el valor de produccion (rp_axi_sm.v:242). Con un umbral mas bajo
    // el FIFO arranca rafagas cortas y el ultimo beat se repite cuando se queda
    // sin datos a mitad de rafaga.
    .ctrl_trig_size_i   (4'hF),
    .ctrl_wrap_i        (1'b1),          // ring: al llegar al final, vuelve
    .ctrl_clr_i         (flush),
    .stat_overflow_o    (axi_ovf),
    .stat_cur_addr_o    (axi_cur_addr),
    .stat_write_data_o  ()
  );

  // Sticky del overflow del FIFO: si alguna vez pasa, la sombra de arriba tiene
  // un bug y los datos en DDR son basura. Tiene que ser visible, no silencioso.
  reg err_fifo_ovf;
  always @(posedge adc_clk_i) begin
    if (!adc_rstn_i || cfg_clr) err_fifo_ovf <= 1'b0;
    else if (axi_ovf)           err_fifo_ovf <= 1'b1;
  end

  //--------------------------------------------------------------------------
  // Contadores de perdida
  //--------------------------------------------------------------------------
  reg [31:0] drop_busy_cnt, drop_full_cnt, ev_cnt;
  always @(posedge adc_clk_i) begin
    if (!adc_rstn_i || cfg_clr) begin
      drop_busy_cnt <= 32'h0;
      drop_full_cnt <= 32'h0;
      ev_cnt        <= 32'h0;
    end else begin
      if (cap_drop_busy) drop_busy_cnt <= drop_busy_cnt + 1'b1;
      if (cap_drop_full) drop_full_cnt <= drop_full_cnt + 1'b1;
      if (cap_val && cap_sof) ev_cnt <= ev_cnt + 1'b1;
    end
  end

  //--------------------------------------------------------------------------
  // FSM global
  //--------------------------------------------------------------------------
  always @(posedge adc_clk_i) begin
    if (!adc_rstn_i) begin
      gst <= G_STOPPED;
    end else case (gst)
      G_STOPPED:  if (cfg_run) gst <= G_RUNNING;
      G_RUNNING:  if (!cfg_run) gst <= G_DRAINING;
      // DRAINING existe para no cortar un slot por la mitad: espera a que la
      // captura y el writer terminen lo que tienen en vuelo.
      G_DRAINING: if (!wr_busy && !cap_busy && !stg_meta_val) gst <= G_STOPPED;
      default:    gst <= G_STOPPED;
    endcase
  end

  //--------------------------------------------------------------------------
  // Bus de sistema
  //--------------------------------------------------------------------------
  wire [19:0] a = sys_addr[19:0];
  wire        geom_wr = sys_wen && !stopped;   // intento de escribir corriendo

  always @(posedge adc_clk_i) begin
    if (!adc_rstn_i) begin
      cfg_run    <= 1'b0;
      cfg_clr    <= 1'b0;
      slot_base  <= 32'h0;
      ring_sz    <= 32'h0;
      slot_shift <= 5'd9;
      pre_n      <= 11'd8;
      post_n     <= 11'd24;
      rd_slot    <= 32'h0;
      err_cfg    <= 1'b0;
    end else begin
      cfg_clr <= 1'b0;

      // rd_slot se reinicia EXACTAMENTE con lo mismo que wr_slot y que el
      // generador de direcciones del axi_wr_fifo (los tres cuelgan de `flush`).
      //
      // El invariante del que depende el PS es
      //     direccion_fisica = slot_base + (wr_slot mod N_SLOTS) * SLOT_SZ
      // y solo se sostiene si los contadores y la direccion se reinician
      // JUNTOS. Resetear wr_slot sin rd_slot deja `ocupados = wr - rd` en
      // underflow (~2^32) y el ring descarta todo (bug visto en la placa, no en
      // simulacion, porque el TB re-publicaba rd_slot tras cada arranque).
      // Resetear los contadores sin la direccion desincroniza el indice con la
      // memoria y el PS lee el slot equivocado.
      if (flush) rd_slot <= 32'h0;

      if (sys_wen) begin
        case (a)
          20'h00: begin cfg_run <= sys_wdata[0]; cfg_clr <= sys_wdata[1]; end
          20'h24: rd_slot <= sys_wdata;          // publicable siempre
          // --- geometria: solo en STOPPED ---
          20'h08: if (stopped) slot_base  <= sys_wdata;       else err_cfg <= 1'b1;
          20'h0C: if (stopped) ring_sz    <= sys_wdata;       else err_cfg <= 1'b1;
          20'h10: if (stopped) slot_shift <= sys_wdata[4:0];  else err_cfg <= 1'b1;
          20'h14: if (stopped) pre_n      <= sys_wdata[S_AW-1:0]; else err_cfg <= 1'b1;
          20'h18: if (stopped) post_n     <= sys_wdata[S_AW-1:0]; else err_cfg <= 1'b1;
          default: ;
        endcase
        if (a == 20'h00 && sys_wdata[1]) err_cfg <= 1'b0;   // clr limpia el sticky
      end
    end
  end

  // Lectura combinacional; el ack va por el shift register de abajo.
  always @(posedge adc_clk_i) begin
    sys_err <= 1'b0;
    case (a)
      20'h00:  sys_rdata <= {29'h0, gst, cfg_run};
      20'h04:  sys_rdata <= {24'h0, err_fifo_ovf, err_slot_ovf, err_cfg,
                             no_credit, 2'h0, gst};
      20'h08:  sys_rdata <= slot_base;
      20'h0C:  sys_rdata <= ring_sz;
      20'h10:  sys_rdata <= {27'h0, slot_shift};
      20'h14:  sys_rdata <= {{(32-S_AW){1'b0}}, pre_n};
      20'h18:  sys_rdata <= {{(32-S_AW){1'b0}}, post_n};
      20'h20:  sys_rdata <= wr_slot;
      20'h24:  sys_rdata <= rd_slot;
      20'h28:  sys_rdata <= seq;
      20'h2C:  sys_rdata <= n_slots;
      20'h30:  sys_rdata <= drop_busy_cnt;
      20'h34:  sys_rdata <= drop_full_cnt;
      20'h38:  sys_rdata <= ev_cnt;
      20'h3C:  sys_rdata <= {{(31-DATA_AW){1'b0}}, stg_lvl,
                             {(4-$clog2(E+1)){1'b0}}, stg_ev_lvl} ;
      20'h40:  sys_rdata <= ts_cnt[31:0];
      20'h44:  sys_rdata <= ts_cnt[63:32];
      20'h48:  sys_rdata <= axi_cur_addr;
      20'h50:  sys_rdata <= MAGIC;
      default: sys_rdata <= 32'h0;
    endcase
  end

  // ACK incondicional de latencia fija: ninguna ruta de ack depende de un
  // sub-bloque, asi que ningun estado interno puede colgar el slot del bus.
  reg [3:0] ack_sr;
  always @(posedge adc_clk_i) begin
    if (!adc_rstn_i) begin ack_sr <= 4'h0; sys_ack <= 1'b0; end
    else begin
      ack_sr  <= {ack_sr[2:0], (sys_wen || sys_ren)};
      sys_ack <= ack_sr[2];
    end
  end

endmodule
