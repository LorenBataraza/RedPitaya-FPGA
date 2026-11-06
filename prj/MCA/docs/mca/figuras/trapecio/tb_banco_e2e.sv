`timescale 1ns/1ps
//============================================================================
// tb_banco_e2e — el disparo con polo-cero y el banco de trapecios, de punta a
// punta, sobre un tren de Poisson: la verdad del RTL contra pruebas_banco.py
//
// mt_top y mca_top cableados como en el top (y como tb_mca2_volcado): la
// MISMA muestra entra a los dos y trig_i del MCA es daisy_trig_o del
// multitrigger, en modo continuo con el shield re-armando. La fuente de la
// mascara es el polo-cero del canal 0 (bit 25), y el MCA corre con el banco.
//
// El estimulo y la configuracion los escribe banco_e2e.py, que despues compara
// el volcado contra el modelo. Formato del estimulo:
//   CFG n_acc gs gl pre mq n_formas pz_k pz_m pz_mq pz_sh pz_thr pz_hyst n
//   F k m off lw sh antes despues            (cuatro lineas, una por forma)
//   n muestras, una por linea, en decimal con signo
// Volcado, con <i> = la muestra del estimulo que esta en la entrada:
//   T <i>                cada flanco de trig_i (daisy_trig_o)
//   A <i>                cada ventana que abre (el asignador de mca_window)
//   E <i> f0 .. f10      cada evento publicado, con las 11 features
//
//   +ESTIM=<estimulo> +VOLCADO=<salida>
//============================================================================
module tb_banco_e2e;
  localparam integer DW = 14, N_CH = 2, N_ACC = 4, AMP_W = 16;
  localparam integer MAXN = 1 << 23;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg signed [DW-1:0] x = 0;

  // ---------------------------------------------------------------- mt_top
  reg  [31:0] m_addr = 0, m_wdata = 0;
  reg         m_wen = 0, m_ren = 0;
  wire [31:0] m_rdata;
  wire        m_err, m_ack, ev, daisy, veto;
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
    .trigger_event_o(ev), .daisy_trig_o(daisy), .mca_veto_o(veto),
    .event_snap_o(), .trig_dis_clr_o(), .trg_src_o(), .new_trg_src_o(), .trg_state_o(),
    .sys_addr(m_addr), .sys_wdata(m_wdata), .sys_wen(m_wen), .sys_ren(m_ren),
    .sys_rdata(m_rdata), .sys_err(m_err), .sys_ack(m_ack)
  );

  // --------------------------------------------------------------- mca_top
  reg  [31:0] a_addr = 0, a_wdata = 0;
  reg         a_wen = 0, a_ren = 0;
  wire [31:0] a_rdata;
  wire        a_err, a_ack;

  mca_top #(.DW(DW), .H_AW(8), .H2_AW(4), .PSD_AW(6), .N_ACC(N_ACC), .N_FORMAS(4)) i_mca (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i({x, x}), .mca_val_i(2'b11), .veto_i(1'b0), .trig_i(daisy),
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
  integer cur = 0;
  bit     activo = 0;
  reg     daisy_q = 0;
  integer j;

  always @(posedge clk) begin
    daisy_q <= daisy;
    if (activo) begin
      if (daisy && !daisy_q) $fdisplay(fo, "T %0d", cur);
      if (i_mca.i_feat.i_win.abre) $fdisplay(fo, "A %0d", cur);
      if (i_mca.ev_valid) begin
        $fwrite(fo, "E %0d", cur);
        for (j = 0; j < 11; j++) $fwrite(fo, " %0d", i_mca.ev_feat[j*AMP_W +: AMP_W]);
        $fwrite(fo, "\n");
      end
    end
  end

  // ------------------------------------------------------------- estimulo
  reg signed [DW-1:0] mem [0:MAXN-1];
  integer fd, r, n, k, v, f;
  integer na, gs, gl, pre, mq, nf, zk, zm, zmq, zsh, zthr, zhyst;
  integer fk, fm, foff, flw, fsh, fant, fdes;
  string  tag, estim, volcado;

  initial begin
    if (!$value$plusargs("ESTIM=%s", estim)) estim = "banco_e2e_estimulo.txt";
    if (!$value$plusargs("VOLCADO=%s", volcado)) volcado = "banco_e2e_volcado.txt";
    fd = $fopen(estim, "r");
    if (fd == 0) begin
      $display("tb_banco_e2e: no se puede abrir %s (correr banco_e2e.py)", estim);
      $display("RESULT: FAIL");
      $finish;
    end
    fo = $fopen(volcado, "w");

    r = $fscanf(fd, "%s %d %d %d %d %d %d %d %d %d %d %d %d %d", tag,
                na, gs, gl, pre, mq, nf, zk, zm, zmq, zsh, zthr, zhyst, n);
    if (r != 14 || tag != "CFG" || n > MAXN) begin
      $display("tb_banco_e2e: cabecera mala (%0d campos, n = %0d)", r, n);
      $display("RESULT: FAIL");
      $finish;
    end

    x = 0; rstn = 0; repeat (10) @(negedge clk); rstn = 1; repeat (10) @(negedge clk);

    // el MCA: base fija en 0, ventana de amplitud abierta, el banco
    a_wr(20'h00020, 0);
    a_wr(20'h0001C, 0);
    a_wr(20'h0004C, (gl << 16) | gs);
    a_wr(20'h00120, na);
    a_wr(20'h00124, pre);
    a_wr(20'h0012C, mq);
    for (f = 0; f < 4; f++) begin
      r = $fscanf(fd, "%s %d %d %d %d %d %d %d", tag, fk, fm, foff, flw, fsh, fant, fdes);
      a_wr(20'h00180 + 16*f, (fm << 16) | fk);
      a_wr(20'h00184 + 16*f, (fsh << 24) | (flw << 16) | foff);
      a_wr(20'h00188 + 16*f, (fdes << 16) | fant);
    end
    a_wr(20'h00134, nf);
    // el multitrigger: shield src = dst = ch0, dur = 0; polo-cero; mascara
    m_wr(20'h010, 32'h0000_0101);
    m_wr(20'h0B0, zthr);
    m_wr(20'h0C0, zhyst);
    m_wr(20'h0A0, zmq);
    m_wr(20'h090, 32'h8000_0000 | (zsh << 24) | (zm << 8) | zk);

    for (k = 0; k < n; k++) begin r = $fscanf(fd, "%d", v); mem[k] = v[DW-1:0]; end
    $fclose(fd);

    repeat (80) @(negedge clk);
    m_wr(20'h040, 32'h0200_0000);                        // OR_MASK ch0 = pz_p
    a_wr(20'h0000C, 2);                                  // clear
    repeat (600) @(negedge clk);
    a_wr(20'h0000C, 1);                                  // run
    repeat (200) @(negedge clk);

    activo = 1;
    for (k = 0; k < n; k++) begin
      @(negedge clk); x = mem[k]; cur = k;
    end
    repeat (400) @(negedge clk);
    activo = 0;
    $fdisplay(fo, "C %0d %0d %0d %0d %0d", i_mca.c_cross, i_mca.c_open, i_mca.c_acc,
              i_mca.c_lost_active, i_mca.c_lost);
    $fdisplay(fo, "FIN");
    $fclose(fo);
    $display("tb_banco_e2e: %0d muestras, %0d disparos, %0d ventanas, %0d publicados -> %s",
             n, i_mca.c_cross, i_mca.c_open, i_mca.c_acc, volcado);
    $display("RESULT: PASS");
    $finish;
  end
endmodule
