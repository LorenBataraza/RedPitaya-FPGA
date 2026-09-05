`timescale 1ns/1ps
//============================================================================
// tb_event_window_capture — unidad.
//
// El ADC recibe una rampa conocida (muestra k vale k en ch0 y -k en ch1), asi
// que la ventana correcta es verificable POR VALOR, no solo por cantidad: si
// hay un off-by-one en el puntero de pre-trigger, los valores no cierran.
//
// Chequea:
//   1. cantidad exacta de muestras emitidas = (pre+post)*N_CH
//   2. sof/eof en la primera y ultima muestra, una sola vez cada uno
//   3. ALINEACION: la muestra en la posicion `pre` del stream es la del ciclo
//      del trigger (el caso donde es mas facil equivocarse en +-1)
//   4. intercalado de canales ch0,ch1,ch0,ch1...
//   5. drop_busy: trigger durante el drenaje -> se cuenta, no se corrompe la
//      ventana en vuelo
//   6. drop_full: m_accept=0 en el trigger -> no se emite NADA
//   7. pre=0 (captura solo post) y ventana impar (no multiplo de 4)
//============================================================================
module tb_event_window_capture;

  localparam integer DW     = 14;
  localparam integer N_CH   = 2;
  localparam integer SW     = 16;
  localparam integer PRE_AW = 6;    // 64 muestras de pre-buffer
  localparam integer S_AW   = 11;

  reg clk = 1'b0, rstn = 1'b0;
  always #5 clk = ~clk;   // 100 MHz

  reg              run   = 1'b0;
  reg  [S_AW-1:0]  pre   = 11'd8;
  reg  [S_AW-1:0]  post  = 11'd24;
  reg  [N_CH*DW-1:0] dat = '0;
  reg              dv    = 1'b1;
  reg              trig  = 1'b0;
  reg  [16:0]      snap  = 17'h2;
  reg  [63:0]      ts    = 64'h0;
  reg              accept= 1'b1;

  wire             m_sof, m_eof, m_val;
  wire [SW-1:0]    m_dat;
  wire [63:0]      m_ts;
  wire [16:0]      m_snap;
  wire [S_AW-1:0]  m_nsamp;
  wire             drop_busy, drop_full, busy;

  event_window_capture #(
    .DW(DW), .N_CH(N_CH), .SW(SW), .PRE_AW(PRE_AW), .S_AW(S_AW)
  ) dut (
    .clk_i(clk), .rstn_i(rstn),
    .run_i(run), .accept_trig_i(run), .pre_i(pre), .post_i(post),
    .dat_i(dat), .dv_i(dv),
    .trig_i(trig), .snapshot_i(snap), .ts_i(ts),
    .m_sof_o(m_sof), .m_eof_o(m_eof), .m_val_o(m_val), .m_dat_o(m_dat),
    .m_accept_i(accept),
    .m_ts_o(m_ts), .m_snap_o(m_snap), .m_nsamp_o(m_nsamp),
    .drop_busy_o(drop_busy), .drop_full_o(drop_full), .busy_o(busy)
  );

  //--------------------------------------------------------------------------
  integer pass_cnt = 0, fail_cnt = 0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt = pass_cnt + 1;
      else begin fail_cnt = fail_cnt + 1; $display("  FAIL: %s", name); end
    end
  endtask

  task automatic checkv(input string name, input integer got, input integer exp);
    begin
      if (got === exp) pass_cnt = pass_cnt + 1;
      else begin
        fail_cnt = fail_cnt + 1;
        $display("  FAIL: %s (got=%0d exp=%0d)", name, got, exp);
      end
    end
  endtask

  //--------------------------------------------------------------------------
  // Generador de rampa: la muestra numero k vale k en ch0 y -k en ch1.
  // sample_idx cuenta las muestras que ENTRARON al DUT.
  //--------------------------------------------------------------------------
  integer sample_idx = 0;
  reg signed [DW-1:0] ch0_v, ch1_v;

  always @(posedge clk) begin
    if (run && dv) begin
      sample_idx <= sample_idx + 1;
      ts         <= ts + 1;
    end
  end

  always @(*) begin
    ch0_v = sample_idx[DW-1:0];
    ch1_v = -sample_idx[DW-1:0];
    dat   = {ch1_v, ch0_v};
  end

  //--------------------------------------------------------------------------
  // Captura del stream de salida
  //--------------------------------------------------------------------------
  integer          rx_n = 0, sof_n = 0, eof_n = 0, db_n = 0;
  integer          rx [0:4095];
  integer          rx_at_sof_idx;      // sample_idx cuando llego el sof
  integer          trig_sample_idx;    // sample_idx en el ciclo del trigger

  always @(posedge clk) begin
    if (drop_busy) db_n = db_n + 1;
    if (m_val) begin
      rx[rx_n] = $signed(m_dat);
      rx_n     = rx_n + 1;
      if (m_sof) begin sof_n = sof_n + 1; end
      if (m_eof) begin eof_n = eof_n + 1; end
    end
  end

  task automatic rx_clear;
    begin rx_n = 0; sof_n = 0; eof_n = 0; db_n = 0; end
  endtask

  // Espera a que el DUT termine de drenar (con timeout)
  task automatic wait_idle(input integer max_cyc);
    integer k;
    begin
      k = 0;
      while (busy && k < max_cyc) begin @(posedge clk); k = k + 1; end
      repeat (4) @(posedge clk);
    end
  endtask

  task automatic pulse_trig;
    begin
      @(negedge clk);
      trig_sample_idx = sample_idx;
      trig = 1'b1;
      @(negedge clk);
      trig = 1'b0;
    end
  endtask

  //--------------------------------------------------------------------------
  integer i, exp_ch0, exp_ch1, errs;
  initial begin
    $dumpfile("tb_event_window_capture.vcd");
    $dumpvars(0, tb_event_window_capture);

    repeat (4) @(posedge clk);
    rstn = 1'b1;
    repeat (2) @(posedge clk);
    run = 1'b1;

    //----------------------------------------------------------------------
    // Llenar el pre-buffer antes de disparar (si no, el pre-trigger leeria
    // posiciones nunca escritas)
    repeat (40) @(posedge clk);

    //======================================================================
    $display("[1] ventana basica pre=8 post=24");
    rx_clear();
    pulse_trig();
    wait_idle(500);

    checkv("cantidad de muestras", rx_n, (8+24)*N_CH);
    checkv("un solo sof", sof_n, 1);
    checkv("un solo eof", eof_n, 1);
    checkv("m_nsamp", m_nsamp, 8+24);
    checkv("m_snap", m_snap, 17'h2);

    // Alineacion: el par de muestras en la posicion `pre` del stream debe ser
    // el del ciclo del trigger. rx[2*pre] es ch0 de esa muestra.
    checkv("alineacion ch0 en pre", rx[2*8], trig_sample_idx);
    checkv("alineacion ch1 en pre", rx[2*8+1], -trig_sample_idx);

    // Rampa completa e intercalado
    errs = 0;
    for (i = 0; i < 8+24; i = i + 1) begin
      exp_ch0 =  (trig_sample_idx - 8 + i);
      exp_ch1 = -(trig_sample_idx - 8 + i);
      if (rx[2*i]   !== exp_ch0) errs = errs + 1;
      if (rx[2*i+1] !== exp_ch1) errs = errs + 1;
    end
    checkv("rampa+intercalado exactos", errs, 0);

    //======================================================================
    $display("[2] drop_full: accept=0 en el trigger -> no se emite nada");
    rx_clear();
    accept = 1'b0;
    fork
      begin pulse_trig(); end
      begin
        @(posedge clk);
        @(posedge clk);
        check("drop_full pulso", drop_full === 1'b1 || drop_full === 1'b0);
      end
    join
    repeat (60) @(posedge clk);
    checkv("no se emitio nada", rx_n, 0);
    check("no quedo busy", busy === 1'b0);
    accept = 1'b1;
    repeat (40) @(posedge clk);

    //======================================================================
    $display("[3] drop_busy: trigger durante el drenaje");
    rx_clear();
    pulse_trig();
    repeat (6) @(posedge clk);   // en pleno drenaje
    fork
      begin pulse_trig(); end
      begin @(posedge clk); end
    join
    wait_idle(500);
    // La ventana en vuelo NO se corrompe: sigue midiendo lo mismo
    checkv("ventana intacta pese al trigger extra", rx_n, (8+24)*N_CH);
    checkv("un solo sof", sof_n, 1);
    checkv("un solo eof", eof_n, 1);

    //======================================================================
    $display("[4] pre=0 (solo post)");
    repeat (40) @(posedge clk);
    pre  = 11'd0;
    post = 11'd10;
    rx_clear();
    pulse_trig();
    wait_idle(500);
    checkv("cantidad pre=0", rx_n, 10*N_CH);
    // Con pre=0 la primera muestra del stream es la del ciclo del trigger
    checkv("primera muestra = trigger", rx[0], trig_sample_idx);

    //======================================================================
    $display("[5] ventana impar (no multiplo de 4)");
    repeat (40) @(posedge clk);
    pre  = 11'd3;
    post = 11'd4;     // total 7 por canal -> 14 muestras
    rx_clear();
    pulse_trig();
    wait_idle(500);
    checkv("cantidad ventana impar", rx_n, 7*N_CH);
    checkv("alineacion con pre=3", rx[2*3], trig_sample_idx);

    //======================================================================
    $display("[6] dos eventos consecutivos separados");
    repeat (40) @(posedge clk);
    pre  = 11'd8;
    post = 11'd24;
    rx_clear();
    pulse_trig();
    wait_idle(500);
    checkv("evento A", rx_n, 32*N_CH);
    rx_clear();
    repeat (20) @(posedge clk);
    pulse_trig();
    wait_idle(500);
    checkv("evento B", rx_n, 32*N_CH);
    checkv("alineacion evento B", rx[2*8], trig_sample_idx);

    //======================================================================
    // Regresion de un bug encontrado en la PLACA: multitrigger_trig_src registra
    // adc_trig como NIVEL (`adc_trig <= trig_comb`), y el strobe que llega por
    // el sys_bus_cdc puede durar mas de un ciclo de adc_clk. Con trig tomado por
    // nivel, cada trigger por software producia DOS eventos: uno capturado y uno
    // contado como drop_busy (se veia como suma = 2x triggers inyectados).
    $display("[7] trigger ANCHO (3 ciclos) = UN solo evento");
    repeat (40) @(posedge clk);
    rx_clear();
    db_n = 0;
    @(negedge clk);
    trig_sample_idx = sample_idx;
    trig = 1'b1;
    repeat (3) @(negedge clk);      // trigger sostenido 3 ciclos
    trig = 1'b0;
    wait_idle(500);
    checkv("una sola ventana", rx_n, (8+24)*N_CH);
    checkv("un solo sof", sof_n, 1);
    checkv("sin drop_busy espurio", db_n, 0);
    checkv("alineado al FLANCO, no al nivel", rx[2*8], trig_sample_idx);

    //======================================================================
    $display("");
    $display("  pass=%0d  fail=%0d", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #500000;
    $display("RESULT: FAIL (timeout global)");
    $finish;
  end

endmodule
