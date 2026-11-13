`timescale 1ns/1ps
//============================================================================
// tb_pulsos_mca — el generador de pulsos manejando el multitrigger y el MCA
//
// Es la prueba del generador como estimulo: el RTL entero, generador incluido,
// contra el modelo del generador y la replica del MCA. La compara
// software/monte-carlo/test_pulsos_mca.py, del mismo modo que
// test_replica_mca2.py compara tb_mca2_volcado.
//
// El cableado es el del top con digital_loop[0] = 1:
//   - gen_pulsos en 0x4021_0000, por sys_bus_split (el slot 2), con un stub
//     del lado del ring como en el top del MCA;
//   - su salida (asg_dat[0]) es la muestra del multitrigger y del MCA. En el
//     top pasa ademas por el registro de adc_dat y la calibracion de i_scope:
//     unos ciclos de latencia que la replica no ve, porque dispara sobre el dato;
//   - su disparo (trig_asg_out) entra al multitrigger por trig_asg_i, con el
//     antirrebote en 0;
//   - trig_i del MCA es daisy_trig_o, como en tb_mca2_volcado.
// Cada bloque dispara de una de dos maneras: por pendiente o polo-cero sobre el
// dato (como en la placa), o por la fuente ASG del OR_MASK (bit 11), que abre
// una ventana por pulso generado.
//
// El estimulo lo escribe software/monte-carlo/volcado_pulsos.py: por bloque,
// la configuracion del MCA (la linea B de volcado_mca2.py, sin el largo), la
// del generador y su tabla. Entre bloques se resetea todo. Por bloque se vuelca
// lo mismo que tb_mca2_volcado (T, E, C, O), con <i> el indice de la muestra
// del generador en la entrada: i = 0 es el primer ciclo despues del arranque
// (la convencion de gen_pulsos_model.py).
//
//   +ESTIM=<estimulo>  +VOLCADO=<salida>   (ver PLUS_tb_pulsos_mca en el Makefile)
//============================================================================
// N_ACC y N_FORMAS son los del mca_top: por defecto 4 y 4, los de la replica
// (N_ACC_RTL, N_FORMAS_RTL). Los tops se sintetizan con 3 y 3; los bloques del
// estimulo usan 3 o menos, asi que con -gN_ACC=3 -gN_FORMAS=3 los eventos y los
// contadores tienen que salir iguales (t_ocup trae una columna menos).
module tb_pulsos_mca #(parameter integer N_ACC = 4, N_FORMAS = 4);
  localparam integer DW = 14, N_CH = 2, AMP_W = 16;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  // ------------------------------------------------- el slot 2 y el generador
  reg  [31:0] s_addr = 0, s_wdata = 0;
  reg         s_wen = 0, s_ren = 0;
  wire [31:0] s_rdata;
  wire        s_err, s_ack;
  wire [31:0] r_addr, r_wdata, p_addr, p_wdata, p_rdata;
  wire        r_wen, r_ren, p_wen, p_ren, p_err, p_ack;

  sys_bus_split #(.SEL_B(4'h1)) i_slot2 (
    .s_addr(s_addr), .s_wdata(s_wdata), .s_wen(s_wen), .s_ren(s_ren),
    .s_rdata(s_rdata), .s_err(s_err), .s_ack(s_ack),
    .a_addr(r_addr), .a_wdata(r_wdata), .a_wen(r_wen), .a_ren(r_ren),
    .a_rdata(32'hx), .a_err(1'b1), .a_ack(1'b1),          // sys_bus_stub
    .b_addr(p_addr), .b_wdata(p_wdata), .b_wen(p_wen), .b_ren(p_ren),
    .b_rdata(p_rdata), .b_err(p_err), .b_ack(p_ack)
  );

  wire [DW-1:0] asg_a, asg_b;
  wire          trig_asg;
  gen_pulsos #(.DW(DW)) i_gen (
    .clk_i(clk), .rstn_i(rstn),
    .dat_a_o(asg_a), .dat_b_o(asg_b), .trig_o(trig_asg),
    .sys_addr(p_addr), .sys_wdata(p_wdata), .sys_wen(p_wen), .sys_ren(p_ren),
    .sys_rdata(p_rdata), .sys_err(p_err), .sys_ack(p_ack)
  );

  wire signed [DW-1:0] x = asg_a;     // digital_loop[0]: el DAC vuelve como la muestra

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
    .trig_ext_i(1'b0), .trig_asg_i(trig_asg),
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

  mca_top #(.DW(DW), .H_AW(8), .H2_AW(4), .PSD_AW(6), .N_ACC(N_ACC), .N_FORMAS(N_FORMAS)) i_mca (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i({x, x}), .mca_val_i(2'b11), .veto_i(1'b0), .trig_i(daisy), .trig_arm_i(trig_arm),
    .sys_addr(a_addr), .sys_wdata(a_wdata), .sys_wen(a_wen), .sys_ren(a_ren),
    .sys_rdata(a_rdata), .sys_err(a_err), .sys_ack(a_ack)
  );

  // ------------------------------------------------------------- el bus
  task automatic p_wr(input [15:0] a, input [31:0] d);
    begin
      @(negedge clk); s_addr = {16'h4021, a}; s_wdata = d; s_wen = 1'b1;
      #1;                    // que el mux del slot ya elija al generador
      while (!s_ack) @(negedge clk);
      @(negedge clk); s_wen = 1'b0;
      while (s_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask
  task automatic p_rd(input [15:0] a, output [31:0] d);
    begin
      @(negedge clk); s_addr = {16'h4021, a}; s_ren = 1'b1;
      #1;
      while (!s_ack) @(negedge clk);
      d = s_rdata;
      @(negedge clk); s_ren = 1'b0;
      while (s_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask
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
  // cur es la muestra del generador que esta en la entrada: arranca en 0 el
  // ciclo despues del arranque, como `g` en gen_pulsos_model.py.
  integer fo;
  integer cur = -1;
  bit     armado = 0, empieza = 0, activo = 0;
  reg     daisy_q = 0;
  integer j;

  always @(negedge clk) begin
    if (cur >= 0)     cur = cur + 1;
    else if (empieza) begin cur = 0; empieza = 0; end
    if (armado && i_gen.arranque) begin empieza = 1; armado = 0; end
  end

  always @(posedge clk) begin
    daisy_q <= daisy;
    if (activo && cur >= 0) begin
      if (daisy && !daisy_q) $fdisplay(fo, "T %0d", cur);
      if (i_mca.ev_valid) begin
        $fwrite(fo, "E %0d %0d %0d %0d", cur, i_mca.ev_amp, i_mca.ev_psd, i_mca.ev_psd_ok);
        for (j = 0; j < 11; j++) $fwrite(fo, " %0d", i_mca.ev_feat[j*AMP_W +: AMP_W]);
        $fwrite(fo, "\n");
      end
    end
  end

  // ------------------------------------------------------------- estimulo
  integer fd, r, k, bloque = 0, n_ev_total = 0, n_gen_total = 0;
  integer na, gs, gl, pre, asrc, qsh, amin, amax, L, G, thr, hyst;
  integer tk, tm, tmq, toff, tlw, tsh;
  integer nf, an0, de0, pz, pzk, pzm, pzmq, pzsh, pzthr, pzhyst;
  integer fm [0:20];
  integer g_asg, g_aleat, g_per, g_umb, g_dtm, g_n, g_sem, g_amp_aleat, g_amp_n,
          g_decae, g_subida, g_base, g_ruido, g_sh, n_tab, n_cic;
  integer v, q, f;
  reg [31:0] d;
  string  tag, estim, volcado;

  initial begin
    if (!$value$plusargs("ESTIM=%s", estim))
      estim = "../software/monte-carlo/datos_ref/pulsos_estimulo.txt";
    if (!$value$plusargs("VOLCADO=%s", volcado))
      volcado = "../software/monte-carlo/datos_ref/pulsos_volcado.txt";
    fd = $fopen(estim, "r");
    if (fd == 0) begin
      $display("tb_pulsos_mca: no se puede abrir %s (correr monte-carlo/volcado_pulsos.py)", estim);
      $display("RESULT: FAIL");
      $finish;
    end
    fo = $fopen(volcado, "w");

    forever begin
      r = $fscanf(fd, "%s", tag);
      if (r != 1 || tag == "FIN") break;
      // la configuracion del MCA: la linea B de volcado_mca2.py, sin el largo
      r = $fscanf(fd, "%d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d",
                  na, gs, gl, pre, asrc, qsh, amin, amax, L, G, thr, hyst,
                  tk, tm, tmq, toff, tlw, tsh);
      r = $fscanf(fd, "%d %d %d", nf, an0, de0);
      for (q = 0; q < 21; q++) r = $fscanf(fd, "%d", fm[q]);
      r = $fscanf(fd, "%d %d %d %d %d %d %d", pz, pzk, pzm, pzmq, pzsh, pzthr, pzhyst);
      // la del generador y su tabla
      r = $fscanf(fd, "%s", tag);
      r = $fscanf(fd, "%d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d",
                  g_asg, g_aleat, g_per, g_umb, g_dtm, g_n, g_sem, g_amp_aleat, g_amp_n,
                  g_decae, g_subida, g_base, g_ruido, g_sh, n_tab, n_cic);

      // reset de todo: cada bloque arranca de cero
      rstn = 0; repeat (10) @(negedge clk); rstn = 1; repeat (10) @(negedge clk);

      // el generador, apagado, con su tabla entera
      p_rd(16'h0020, d);
      if (d !== 32'h5055_4C31) begin $display("MAGIC del generador: %h", d); $display("RESULT: FAIL"); $finish; end
      p_wr(16'h0004, g_per);
      p_wr(16'h0008, g_umb);
      p_wr(16'h000C, g_dtm);
      p_wr(16'h0010, g_n);
      p_wr(16'h0014, g_sem);
      p_wr(16'h0024, g_decae);
      p_wr(16'h0028, g_subida);
      p_wr(16'h002C, g_amp_n);
      p_wr(16'h0030, g_base);
      p_wr(16'h0034, (g_ruido << 8) | g_sh);
      for (k = 0; k < 1024; k++) begin
        if (k < n_tab) r = $fscanf(fd, "%h", v); else v = 0;
        p_wr(16'h1000 + 4 * k, {{18{v[13]}}, v[13:0]});
      end

      // el MCA, como en tb_mca2_volcado: base fija en 0, la configuracion del bloque
      a_wr(20'h00020, 0);
      a_wr(20'h0001C, 0);
      a_wr(20'h00030, amin);
      a_wr(20'h00034, amax);
      a_wr(20'h00038, (qsh << 8) | asrc);
      a_wr(20'h0004C, (gl << 16) | gs);
      a_wr(20'h00120, na);
      a_wr(20'h00124, pre);
      a_wr(20'h00128, (tm << 16) | tk);
      a_wr(20'h0012C, tmq);
      a_wr(20'h00130, (tsh << 24) | (tlw << 16) | toff);
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
      if (g_asg != 0) begin
        m_wr(20'h040, 32'h0000_0800);                      // OR_MASK ch0 = ASG_P
      end else if (pz != 0) begin
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

      // el generador: en, los dos modos, out1
      $fdisplay(fo, "B %0d", bloque);
      activo = 1; armado = 1; cur = -1;
      p_wr(16'h0000, 32'h1 | (g_aleat << 1) | (g_amp_aleat << 2) | (1 << 3));
      while (cur < 0 || cur < n_cic - 1) @(negedge clk);
      @(posedge clk); #1 activo = 0;
      a_wr(20'h0000C, 0);                                  // stop
      p_rd(16'h0018, d);
      n_gen_total += d;
      p_wr(16'h0000, 0);
      $fdisplay(fo, "C %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
                i_mca.c_total, i_mca.c_acc, i_mca.c_rej_amp, i_mca.c_rej_psd,
                i_mca.c_pileup, i_mca.c_lost, i_mca.c_cross, i_mca.c_open,
                i_mca.c_lost_active, i_mca.c_win, i_mca.c_trig);
      $fwrite(fo, "O");
      for (j = 0; j <= N_ACC; j++) $fwrite(fo, " %0d", i_mca.t_ocup_cnt[j]);
      $fwrite(fo, "\n");
      $fdisplay(fo, "P %0d", d);                           // GEN_CNT al final
      $display("  bloque %0d: %s n_acc=%0d, %0d muestras, %0d pulsos, %0d disparos, %0d publicados",
               bloque, g_asg ? "ASG" : (pz ? "pz" : "pendiente"), na, n_cic, d,
               i_mca.c_cross, i_mca.c_acc);
      n_ev_total += i_mca.c_acc;
      bloque++;
    end
    $fdisplay(fo, "FIN");
    $fclose(fo);
    $fclose(fd);
    $display("tb_pulsos_mca: %0d bloques, %0d pulsos, %0d eventos -> %s", bloque, n_gen_total, n_ev_total, volcado);
    if (bloque > 0 && n_ev_total > 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end
endmodule
