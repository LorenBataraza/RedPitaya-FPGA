`timescale 1ns/1ps
//============================================================================
// tb_mca2_volcado — el MCA2 entero sobre un estimulo dado, volcado a texto
//
// Es la verdad contra la que se compara la replica del Monte Carlo
// (software/monte-carlo/replica_mca2.py, test_replica_mca2.py), del mismo modo
// que tb_event_ring_top vuelca el ring para test_ring_format.py.
//
// mt_top y mca_top conectados como en el top (y como tb_mca_mt_latencia): la
// MISMA muestra entra a los dos y trig_i del MCA es daisy_trig_o del
// multitrigger, en modo continuo con el shield re-armando y el disparo (por
// pendiente o con polo-cero) en la mascara. Es lo que arma multitrigger_armar_mca.
//
// El estimulo lo escribe software/monte-carlo/volcado_mca2.py: bloques de
// configuracion, cada uno con su traza. Entre bloques se resetea el DUT, asi
// cada bloque arranca de cero (como la replica). Por cada bloque se vuelca:
//   T <i>                    cada flanco de trig_i
//   E <i> amp psd ok f0..f10 cada evento publicado (ev_valid de mca_pulse_feature)
//   C ...                    los contadores al final
//   O t_ocup0..t_ocup4       los ciclos con j ranuras ocupadas
// donde <i> es el indice de la muestra del estimulo que esta en la entrada
// en ese flanco.
//
//   +ESTIM=<estimulo>  +VOLCADO=<salida>   (ver PLUS_tb_mca2_volcado en el Makefile)
//============================================================================
module tb_mca2_volcado;
  localparam integer DW = 14, N_CH = 2, N_ACC = 4, NFEAT = 16, AMP_W = 16;
  localparam integer MAXN = 1 << 18;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg signed [DW-1:0] x = 0;

  // ---------------------------------------------------------------- mt_top
  reg  [31:0] m_addr = 0, m_wdata = 0;
  reg         m_wen = 0, m_ren = 0;
  wire [31:0] m_rdata;
  wire        m_err, m_ack, ev, daisy, veto, trig_arm;
  wire [3:0]  ext_asg, trig_ch_o;

  mt_top #(.N_CH(N_CH), .DW(DW)) i_mt (
    .adc_clk_i({N_CH{clk}}), .adc_rstn_i({N_CH{rstn}}),
    .mtrg_dat_i({x, x}), .mtrg_val_i({N_CH{1'b1}}),
    .set_tresh_i({4{14'd8000}}), .set_hyst_i({4{14'd50}}), .set_deb_len_i(20'd0),
    .indep_mode_i(4'h0), .legacy_trig_sw_i(4'h0), .legacy_trig_dis_clr_i(4'h0),
    .adc_rst_do_i(4'h0), .adc_dly_do_i(4'h0), .adc_we_keep_i(4'hF), .dly_valp_i(4'hF),
    .trig_ext_i(1'b0), .trig_asg_i(1'b0),
    .trig_ext_asg_o(ext_asg), .trig_ext_asg_i(ext_asg),
    .trig_ch_i(4'h0), .trig_ch_o(trig_ch_o),
    .trigger_event_o(ev), .daisy_trig_o(daisy), .mca_veto_o(veto), .trig_arm_o(trig_arm),
    .event_snap_o(), .trig_dis_clr_o(), .trg_src_o(), .new_trg_src_o(), .trg_state_o(),
    .sys_addr(m_addr), .sys_wdata(m_wdata), .sys_wen(m_wen), .sys_ren(m_ren),
    .sys_rdata(m_rdata), .sys_err(m_err), .sys_ack(m_ack)
  );

  // --------------------------------------------------------------- mca_top
  reg  [31:0] a_addr = 0, a_wdata = 0;
  reg         a_wen = 0, a_ren = 0;
  wire [31:0] a_rdata;
  wire        a_err, a_ack;

  // PSD_AW = 6 como en el build: ev_psd es feat[2] >> (16 - PSD_AW)
  mca_top #(.DW(DW), .H_AW(8), .H2_AW(4), .PSD_AW(6), .N_ACC(N_ACC), .N_FORMAS(4)) i_mca (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i({x, x}), .mca_val_i(2'b11), .veto_i(1'b0), .trig_i(daisy), .trig_arm_i(trig_arm),
    .sys_addr(a_addr), .sys_wdata(a_wdata), .sys_wen(a_wen), .sys_ren(a_ren),
    .sys_rdata(a_rdata), .sys_err(a_err), .sys_ack(a_ack)
  );

  task automatic m_wr(input [19:0] a, input [31:0] d);
    begin
      @(negedge clk); m_addr = {12'h403, a}; m_wdata = d; m_wen = 1'b1;
      while (!m_ack) @(negedge clk);
      @(negedge clk); m_wen = 1'b0; m_addr = 0;
      while (m_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask
  task automatic a_wr(input [19:0] a, input [31:0] d);
    begin
      @(negedge clk); a_addr = {12'h407, a}; a_wdata = d; a_wen = 1'b1;
      while (!a_ack) @(negedge clk);
      @(negedge clk); a_wen = 1'b0; a_addr = 0;
      while (a_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  // ----------------------------------------------------------- el volcado
  integer fo;
  integer cur = 0;          // muestra del estimulo que esta en la entrada
  bit     activo = 0;
  reg     daisy_q = 0;
  integer j;

  always @(posedge clk) begin
    daisy_q <= daisy;
    if (activo) begin
      if (daisy && !daisy_q) $fdisplay(fo, "T %0d", cur);
      if (i_mca.ev_valid) begin
        $fwrite(fo, "E %0d %0d %0d %0d", cur, i_mca.ev_amp, i_mca.ev_psd, i_mca.ev_psd_ok);
        for (j = 0; j < 11; j++) $fwrite(fo, " %0d", i_mca.ev_feat[j*AMP_W +: AMP_W]);
        $fwrite(fo, "\n");
      end
    end
  end

  // ------------------------------------------------------------- estimulo
  reg [DW-1:0] mem [0:MAXN-1];
  integer fd, r, n, k, bloque = 0, n_ev_total = 0;
  integer na, gs, gl, pre, asrc, qsh, amin, amax, L, G, thr, hyst;
  integer tk, tm, tmq, toff, tlw, tsh;
  integer nf, an0, de0, pz, pzk, pzm, pzmq, pzsh, pzthr, pzhyst;
  integer fm [0:20];        // formas 1..3: k m off lw sh antes despues
  integer v, q, f;
  string  tag, estim, volcado;

  initial begin
    if (!$value$plusargs("ESTIM=%s", estim))
      estim = "../software/monte-carlo/datos_ref/mca2_estimulo.txt";
    if (!$value$plusargs("VOLCADO=%s", volcado))
      volcado = "../software/monte-carlo/datos_ref/mca2_volcado.txt";
    fd = $fopen(estim, "r");
    if (fd == 0) begin
      $display("tb_mca2_volcado: no se puede abrir %s (correr monte-carlo/volcado_mca2.py)", estim);
      $display("RESULT: FAIL");
      $finish;
    end
    fo = $fopen(volcado, "w");

    forever begin
      r = $fscanf(fd, "%s", tag);
      if (r != 1 || tag == "FIN") break;
      r = $fscanf(fd, "%d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d",
                  na, gs, gl, pre, asrc, qsh, amin, amax, L, G, thr, hyst,
                  tk, tm, tmq, toff, tlw, tsh);
      r = $fscanf(fd, "%d %d %d", nf, an0, de0);
      for (q = 0; q < 21; q++) r = $fscanf(fd, "%d", fm[q]);
      r = $fscanf(fd, "%d %d %d %d %d %d %d %d", pz, pzk, pzm, pzmq, pzsh, pzthr, pzhyst, n);
      if (n > MAXN) begin $display("bloque demasiado largo: %0d", n); $display("RESULT: FAIL"); $finish; end
      for (k = 0; k < n; k++) begin r = $fscanf(fd, "%h", v); mem[k] = v[DW-1:0]; end

      // reset del DUT entero: cada bloque arranca de cero
      x = 0; rstn = 0; repeat (10) @(negedge clk); rstn = 1; repeat (10) @(negedge clk);

      // el MCA: base fija en 0, la configuracion del bloque
      a_wr(20'h00020, 0);                                  // BL_CTRL: bl_auto = 0
      a_wr(20'h0001C, 0);                                  // BASELINE
      a_wr(20'h00030, amin);
      a_wr(20'h00034, amax);
      a_wr(20'h00038, (qsh << 8) | asrc);
      a_wr(20'h0004C, (gl << 16) | gs);
      a_wr(20'h00120, na);
      a_wr(20'h00124, pre);
      a_wr(20'h00128, (tm << 16) | tk);
      a_wr(20'h0012C, tmq);
      a_wr(20'h00130, (tsh << 24) | (tlw << 16) | toff);
      // el banco: umbrales de la forma 0, las formas 1..3 y cuantas se usan
      a_wr(20'h00188, (de0 << 16) | an0);
      for (f = 1; f < 4; f++) begin
        q = 7 * (f - 1);
        a_wr(20'h00180 + 16*f, (fm[q+1] << 16) | fm[q]);
        a_wr(20'h00184 + 16*f, (fm[q+4] << 24) | (fm[q+3] << 16) | fm[q+2]);
        a_wr(20'h00188 + 16*f, (fm[q+6] << 16) | fm[q+5]);
      end
      a_wr(20'h00134, nf);
      // el multitrigger: shield src = dst = ch0, dur = 0; el disparo; mascara
      m_wr(20'h010, 32'h0000_0101);
      if (pz != 0) begin
        m_wr(20'h0B0, pzthr);
        m_wr(20'h0C0, pzhyst);
        m_wr(20'h0A0, pzmq);
        m_wr(20'h090, 32'h8000_0000 | (pzsh << 24) | (pzm << 8) | pzk);
        repeat (120) @(negedge clk);
        m_wr(20'h040, 32'h0200_0000);                      // OR_MASK ch0 = pz_p
      end else begin
        m_wr(20'h070, thr);
        m_wr(20'h080, hyst);
        m_wr(20'h060, 32'h8000_0000 | (G << 8) | L);
        repeat (80) @(negedge clk);
        m_wr(20'h040, 32'h0002_0000);                      // OR_MASK ch0 = slope_p
      end
      a_wr(20'h0000C, 2);                                  // clear
      repeat (600) @(negedge clk);
      a_wr(20'h0000C, 1);                                  // run
      repeat (200) @(negedge clk);

      $fdisplay(fo, "B %0d", bloque);
      activo = 1;
      for (k = 0; k < n; k++) begin
        @(negedge clk); x = mem[k]; cur = k;
      end
      @(negedge clk); activo = 0;
      a_wr(20'h0000C, 0);                                  // stop
      $fdisplay(fo, "C %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
                i_mca.c_total, i_mca.c_acc, i_mca.c_rej_amp, i_mca.c_rej_psd,
                i_mca.c_pileup, i_mca.c_lost, i_mca.c_cross, i_mca.c_open,
                i_mca.c_lost_active, i_mca.c_win, i_mca.c_trig);
      $fwrite(fo, "O");
      for (j = 0; j <= N_ACC; j++) $fwrite(fo, " %0d", i_mca.t_ocup_cnt[j]);
      $fwrite(fo, "\n");
      $display("  bloque %0d: n_acc=%0d gl=%0d nf=%0d pz=%0d, %0d muestras, %0d disparos, %0d publicados",
               bloque, na, gl, nf, pz, n, i_mca.c_cross, i_mca.c_acc);
      n_ev_total += i_mca.c_acc;
      bloque++;
    end
    $fdisplay(fo, "FIN");
    $fclose(fo);
    $fclose(fd);
    $display("tb_mca2_volcado: %0d bloques, %0d eventos -> %s", bloque, n_ev_total, volcado);
    if (bloque > 0 && n_ev_total > 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end
endmodule
