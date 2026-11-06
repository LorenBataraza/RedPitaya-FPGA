`timescale 1ns/1ps
// Latencia pie -> disparo del multitrigger (mt_slope_trig, L=8 G=4, thr 600,
// hyst 300: la configuracion de la placa) con pulsos de preamplificador:
// subida 1-exp(-t/tr), cola de 250 muestras, fase del pie dentro de la muestra
// al azar y ruido gaussiano de 4.5 cuentas. Escribe una linea por pulso:
//   tr10_90 amplitud fase latencia
// con la latencia en ciclos desde la primera muestra con pulso. Despues, PARES de
// pulsos a dt = 1..48 (banco_pares.txt): cuantos disparos salen y cuando:
//   a1 a2 dt fase1 fase2 n_disparos latencia1 latencia2
// (dt de 1 a 48 de a una muestra y despues de a 8 hasta 300: un pulso chico
// sobre la cola de uno grande tarda en disparar). +L= +G= +THR= +HYST= cambian
// el disparo (los archivos salen con sufijo _L<L>); +SOLO_PARES salta la latencia.
//
// En paralelo, sobre la MISMA muestra, un segundo mt_top con el disparo con
// POLO-CERO (mt_pz_trig: k = 2, m = 1, el Mq de la cola, 3992) en su mascara, en
// modo continuo como el primero. Con la configuracion de la placa escribe
// tambien banco_latencias_pz.txt y banco_pares_pz.txt, con el mismo formato y
// medidos en el mismo punto: el flanco de daisy_trig_o, lo que le llega al MCA
// como trig_i. +PZ_THR= +PZ_HYST= en unidades de la salida del trapecio (7.07
// por cuenta de amplitud con esta forma y subida de 1.2 muestras: 353 = 50
// cuentas).
//
// Hasta el 2026-11-03 el polo-cero de aca era un mca_trap suelto con un Schmitt
// escrito en el TB; ahora es la fuente del RTL, y la latencia incluye la cadena
// del multitrigger (el registro de mt_trig_src).
module tb_banco_disparo;
  localparam integer DW = 14, N_CH = 2;
  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;
  reg signed [DW-1:0] x = 0;

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

  // el segundo multitrigger: el disparo con polo-cero
  reg         z_wen = 0;
  wire [31:0] z_rdata;
  wire        z_err, z_ack, z_ev, z_daisy, z_veto;
  wire [3:0]  z_ext_asg, z_trig_ch_o;

  mt_top #(.N_CH(N_CH), .DW(DW)) i_mt_pz (
    .adc_clk_i({N_CH{clk}}), .adc_rstn_i({N_CH{rstn}}),
    .mtrg_dat_i({x, x}), .mtrg_val_i({N_CH{1'b1}}),
    .set_tresh_i({4{14'd8000}}), .set_hyst_i({4{14'd50}}), .set_deb_len_i(20'd0),
    .indep_mode_i(4'h0), .legacy_trig_sw_i(4'h0), .legacy_trig_dis_clr_i(4'h0),
    .adc_rst_do_i(4'h0), .adc_dly_do_i(4'h0), .adc_we_keep_i(4'hF), .dly_valp_i(4'hF),
    .trig_ext_i(1'b0), .trig_asg_i(1'b0),
    .trig_ext_asg_o(z_ext_asg), .trig_ext_asg_i(z_ext_asg),
    .trig_ch_i(4'h0), .trig_ch_o(z_trig_ch_o),
    .trigger_event_o(z_ev), .daisy_trig_o(z_daisy), .mca_veto_o(z_veto),
    .event_snap_o(), .trig_dis_clr_o(), .trg_src_o(), .new_trg_src_o(), .trg_state_o(),
    .sys_addr(m_addr), .sys_wdata(m_wdata), .sys_wen(z_wen), .sys_ren(1'b0),
    .sys_rdata(z_rdata), .sys_err(z_err), .sys_ack(z_ack)
  );

  // sel 0: el de la pendiente; 1: el del polo-cero
  task automatic m_wr(input bit sel, input [19:0] a, input [31:0] d);
    begin
      @(negedge clk); m_addr = {12'h403, a}; m_wdata = d;
      if (sel) z_wen = 1'b1; else m_wen = 1'b1;
      while (!(sel ? z_ack : m_ack)) @(negedge clk);
      @(negedge clk); m_wen = 1'b0; z_wen = 1'b0; m_addr = 0;
      while (sel ? z_ack : m_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  longint ciclo = 0;
  always @(posedge clk) ciclo <= ciclo + 1;
  longint t_pie, t_trig, t_trig2;
  bit visto;
  integer n_disp;
  reg daisy_q = 0;
  always @(posedge clk) begin
    daisy_q <= daisy;
    if (daisy && !daisy_q) begin
      if (!visto) begin visto = 1; t_trig = ciclo; end
      else if (n_disp == 1) t_trig2 = ciclo;
      n_disp++;
    end
  end

  // ------------------------------------------- el disparo con polo-cero
  integer pz_thr = 353, pz_hyst = 177;
  longint t_pz, t_pz2;
  bit visto_pz;
  integer n_pz;
  reg z_daisy_q = 0;
  always @(posedge clk) begin
    z_daisy_q <= z_daisy;
    if (z_daisy && !z_daisy_q) begin
      if (!visto_pz) begin visto_pz = 1; t_pz = ciclo; end
      else if (n_pz == 1) t_pz2 = ciclo;
      n_pz++;
    end
  end

  // gaussiana por Box-Muller
  function automatic real gauss();
    real u1, u2;
    u1 = ($urandom_range(1, 1000000)) / 1000000.0;
    u2 = ($urandom_range(0, 999999)) / 1000000.0;
    return $sqrt(-2.0 * $ln(u1)) * $cos(6.283185307 * u2);
  endfunction

  task automatic pulso(input real a, input real tr, input real fase, input integer largo);
    integer k; real s, t;
    begin
      visto = 0; n_disp = 0; visto_pz = 0; n_pz = 0;
      for (k = -40; k < largo; k++) begin
        @(negedge clk);
        t = k - fase;
        s = 0.0;
        if (t > 0) s = a * (1.0 - $exp(-t / tr)) * $exp(-t / 250.0);
        s = s + 4.5 * gauss();
        if (s > 8100.0) s = 8100.0;
        x = $rtoi(s + ((s >= 0) ? 0.5 : -0.5));
        if (k == 0) t_pie = ciclo;
      end
    end
  endtask

  // Un PAR: a1 con el pie en fase1 y a2 con el pie dt + fase2 muestras despues
  task automatic par(input real a1, input real a2, input integer dt, input real tr,
                     input real fase1, input real fase2, input integer largo);
    integer k; real s, t1, t2;
    begin
      visto = 0; n_disp = 0; visto_pz = 0; n_pz = 0;
      for (k = -40; k < largo; k++) begin
        @(negedge clk);
        t1 = k - fase1; t2 = k - dt - fase2;
        s = 0.0;
        if (t1 > 0) s = s + a1 * (1.0 - $exp(-t1 / tr)) * $exp(-t1 / 250.0);
        if (t2 > 0) s = s + a2 * (1.0 - $exp(-t2 / tr)) * $exp(-t2 / 250.0);
        s = s + 4.5 * gauss();
        if (s > 8100.0) s = 8100.0;
        x = $rtoi(s + ((s >= 0) ? 0.5 : -0.5));
        if (k == 0) t_pie = ciclo;
      end
    end
  endtask

  integer fd, fp, fdz, fpz, i, j, r, rep, dt, cL, cG, cthr, chyst, solo_pares, con_pz;
  string  suf;
  real pa1 [5] = '{2000.0, 8000.0, 300.0, 300.0, 8000.0};
  real pa2 [5] = '{1200.0, 300.0, 8000.0, 300.0, 8000.0};
  real f1, f2;
  real amps [12] = '{100.0, 150.0, 200.0, 300.0, 500.0, 800.0, 1200.0, 2000.0, 3000.0, 4500.0, 6000.0, 8000.0};
  real tr10 [5]  = '{1.2, 2.0, 4.0, 8.0, 16.0};   // subida 10-90 % en muestras
  real fase;

  initial begin
    process::self().srandom(17);
    // por defecto, los de la placa (test_mca2_placa.Pendiente.armar)
    if (!$value$plusargs("L=%d", cL)) cL = 8;
    if (!$value$plusargs("G=%d", cG)) cG = 4;
    if (!$value$plusargs("THR=%d", cthr)) cthr = 600;
    if (!$value$plusargs("HYST=%d", chyst)) chyst = 300;
    solo_pares = $test$plusargs("SOLO_PARES");
    if ($value$plusargs("PZ_THR=%d", pz_thr)) ;
    if ($value$plusargs("PZ_HYST=%d", pz_hyst)) ;
    suf = (cL == 8 && cG == 4 && cthr == 600) ? "" : $sformatf("_L%0d", cL);
    con_pz = (suf == "");
    if (!solo_pares) fd = $fopen({"banco_latencias", suf, ".txt"}, "w");
    if (!solo_pares && con_pz) fdz = $fopen("banco_latencias_pz.txt", "w");
    repeat (10) @(negedge clk); rstn = 1;
    repeat (10) @(negedge clk);
    m_wr(0, 20'h010, 32'h0000_0101);       // shield: src = dst = ch0, dur = 0
    m_wr(0, 20'h070, cthr);
    m_wr(0, 20'h080, chyst);
    m_wr(0, 20'h060, 32'h8000_0000 | (cG << 8) | cL);
    // el polo-cero, en el segundo multitrigger
    m_wr(1, 20'h010, 32'h0000_0101);
    m_wr(1, 20'h0B0, pz_thr);              // PZ_THR ch0
    m_wr(1, 20'h0C0, pz_hyst);             // PZ_HYST ch0
    m_wr(1, 20'h0A0, 3992);                // PZ_MQ ch0
    m_wr(1, 20'h090, 32'h8A00_0102);       // PZ_CFG ch0: en, sh = 10, m = 1, k = 2
    repeat (80) @(negedge clk);
    m_wr(0, 20'h040, 32'h0002_0000);       // OR_MASK ch0 = slope_p
    m_wr(1, 20'h040, 32'h0200_0000);       // OR_MASK ch0 = pz_p (bit 25)
    repeat (200) @(negedge clk);
    if (!solo_pares) for (r = 0; r < 5; r++)
      for (i = 0; i < 12; i++)
        for (rep = 0; rep < 60; rep++) begin
          fase = $urandom_range(0, 999) / 1000.0;
          pulso(amps[i], tr10[r] / 2.197, fase, 1800);
          $fdisplay(fd, "%0.1f %0.1f %0.3f %0d %0d", tr10[r], amps[i], fase,
                    visto ? int'(t_trig - t_pie) : -1, n_disp);
          if (con_pz)
            $fdisplay(fdz, "%0.1f %0.1f %0.3f %0d %0d", tr10[r], amps[i], fase,
                      visto_pz ? int'(t_pz - t_pie) : -1, n_pz);
        end
    if (!solo_pares) $fclose(fd);
    if (!solo_pares && con_pz) $fclose(fdz);
    // Pares: cuantos disparos da el multitrigger y con que latencia, contra dt
    fp = $fopen({"banco_pares", suf, ".txt"}, "w");
    if (con_pz) fpz = $fopen("banco_pares_pz.txt", "w");
    for (i = 0; i < 5; i++)
      for (dt = 1; dt <= 300; dt = dt + ((dt < 48) ? 1 : 8))
        for (rep = 0; rep < 16; rep++) begin
          f1 = $urandom_range(0, 999) / 1000.0;
          f2 = $urandom_range(0, 999) / 1000.0;
          par(pa1[i], pa2[i], dt, 1.2 / 2.197, f1, f2, 1800);
          $fdisplay(fp, "%0.1f %0.1f %0d %0.3f %0.3f %0d %0d %0d", pa1[i], pa2[i], dt, f1, f2, n_disp,
                    visto ? int'(t_trig - t_pie) : -1, (n_disp > 1) ? int'(t_trig2 - t_pie) : -1);
          if (con_pz)
            $fdisplay(fpz, "%0.1f %0.1f %0d %0.3f %0.3f %0d %0d %0d", pa1[i], pa2[i], dt, f1, f2, n_pz,
                      visto_pz ? int'(t_pz - t_pie) : -1, (n_pz > 1) ? int'(t_pz2 - t_pie) : -1);
        end
    $fclose(fp);
    if (con_pz) $fclose(fpz);
    $display("RESULT: PASS");
    $finish;
  end
endmodule
