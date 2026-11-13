`timescale 1ns/1ps
//============================================================================
// tb_mt_slope_trig — unidad. Verifica:
//   - s es EXACTAMENTE el trapezoidal Σ_L x[n-i] - Σ_L x[n-L-G-i] con historia
//     en cero desde el re-arranque (modelo de referencia por suma directa,
//     muestra a muestra), incluido el rango completo con L=16, G=31
//   - L=1, G=0 es la diferencia x[n]-x[n-1]; L=0 se toma como 1
//   - huecos en adc_dv: el filtro avanza solo con muestras válidas
//   - un escalón da UN pulso p a la subida y UN pulso n a la bajada,
//     con s de pico L·A
//   - una continua (aunque el arranque desde historia cero sea un escalón
//     falso) y una rampa lenta NO disparan
//   - escalones ruidosos: la histéresis evita pulsos múltiples
//   - cambiar L o G en caliente re-arranca sin pulsos espurios
//   - cfg_en=0 no dispara
//============================================================================
module tb_mt_slope_trig;

  localparam integer DW   = 14;
  localparam integer LMAX = 16;
  localparam integer GMAX = 31;
  localparam integer SW   = DW + $clog2(LMAX) + 1;
  localparam integer TW   = SW - 1;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg  signed [DW-1:0] x  = 0;
  reg                  dv = 0;
  reg                  en = 0;
  reg         [   4:0] len = 1, gap = 0;
  reg         [TW-1:0] thr = 0, hyst = 0;
  wire                 sp, sn;
  wire                 ap, an;        // estado de re-armado de cada Schmitt

  mt_slope_trig #(.DW(DW), .LMAX(LMAX), .GMAX(GMAX)) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .adc_dat_i(x), .adc_dv_i(dv),
    .cfg_en_i(en), .cfg_len_i(len), .cfg_gap_i(gap),
    .cfg_thr_i(thr), .cfg_hyst_i(hyst),
    .slope_p_o(sp), .slope_n_o(sn),
    .armado_p_o(ap), .armado_n_o(an)
  );

  integer pass_cnt = 0, fail_cnt = 0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) begin pass_cnt = pass_cnt + 1; $display("  PASS: %s", name); end
      else begin fail_cnt = fail_cnt + 1; $display("  FAIL: %s", name); end
    end
  endtask

  //--------------------------------------------------------------------------
  // Modelo de referencia: historia desde el re-arranque, cero antes.
  //--------------------------------------------------------------------------
  int hist[$];          // muestras válidas desde el último re-arranque
  int expq[$];          // s esperado, en orden de muestra
  int L_m = 1, G_m = 0; // L y G efectivos (ya saturados)

  function automatic int xh(int idx);
    return (idx >= 0) ? hist[idx] : 0;
  endfunction

  function automatic int model_s();
    int n = hist.size() - 1;
    int acc = 0;
    for (int i = 0; i < L_m; i++) acc += xh(n - i) - xh(n - L_m - G_m - i);
    return acc;
  endfunction

  // Comparación muestra a muestra contra el acumulador interno.
  bit     chk_en = 0;
  integer mism = 0, compared = 0, s_max = 0;
  always @(negedge clk) if (chk_en && dut.p3_v) begin
    int e;
    if (expq.size() == 0) begin
      mism++; if (mism < 5) $display("    s sin esperado (cola vacia)");
    end else begin
      e = expq.pop_front();
      compared++;
      if (int'(dut.s) > s_max) s_max = int'(dut.s);
      if (int'(dut.s) !== e) begin
        mism++; if (mism < 5) $display("    s=%0d esperado %0d", int'(dut.s), e);
      end
    end
  end

  // Contadores de pulsos
  integer np = 0, nn = 0;
  always @(posedge clk) if (rstn) begin
    if (sp) np++;
    if (sn) nn++;
  end

  // El armado contra los pulsos, en toda la corrida: cada pulso sale con el
  // Schmitt recien desarmado (armado en 1 dos ciclos antes, en 0 desde el
  // ciclo anterior), que es lo que el MCA necesita para su t_rearm.
  reg     ap_d1 = 0, ap_d2 = 0, an_d1 = 0, an_d2 = 0;
  integer arm_np = 0, arm_nn = 0, arm_vp = 0, arm_vn = 0;
  always @(posedge clk) if (rstn) begin
    if (sp) begin arm_np++; if (!(!ap && !ap_d1 && ap_d2)) arm_vp++; end
    if (sn) begin arm_nn++; if (!(!an && !an_d1 && an_d2)) arm_vn++; end
    ap_d2 <= ap_d1; ap_d1 <= ap;
    an_d2 <= an_d1; an_d1 <= an;
  end

  //--------------------------------------------------------------------------
  // Estímulo
  //--------------------------------------------------------------------------
  // Una muestra por ciclo (o un hueco con v=0).
  task automatic drive(input int v, input bit valid = 1);
    begin
      @(negedge clk);
      x  = v;
      dv = valid;
      if (valid) begin hist.push_back(v); expq.push_back(model_s()); end
    end
  endtask

  task automatic idle(input int n);
    begin repeat (n) begin @(negedge clk); dv = 0; end end
  endtask

  // Reconfiguración con el pipeline vacío: el modelo re-arranca en sincronía.
  // Pasa por en=0 para vaciar el filtro aunque L y G no cambien.
  task automatic configure(input int l, input int g, input int t, input int h,
                           input bit e = 1);
    begin
      idle(8);
      en = 0;
      idle(4);
      len = l; gap = g; thr = t; hyst = h; en = e;
      L_m = (l == 0) ? 1 : (l > LMAX ? LMAX : l);
      G_m = (g > GMAX) ? GMAX : g;
      idle(8);
      hist.delete(); expq.delete();
      np = 0; nn = 0; mism = 0; compared = 0; s_max = 0;
    end
  endtask

  task automatic hold(input int v, input int n);
    begin repeat (n) drive(v); end
  endtask

  int i, k, r;

  initial begin
    $dumpfile("tb_mt_slope_trig.vcd"); $dumpvars(0, tb_mt_slope_trig);
    $display("=== tb_mt_slope_trig ===");

    repeat (5) @(negedge clk);
    rstn = 1;
    chk_en = 1;

    //----------------------------------------------------------------------
    // 1) Exactitud: datos aleatorios en todo el rango, L=16 G=31
    //----------------------------------------------------------------------
    configure(16, 31, 18'h3FFFF, 0);
    for (i = 0; i < 2000; i++) drive($urandom_range(0, 16383) - 8192);
    idle(8);
    check($sformatf("modelo == RTL, rango completo L=16 G=31 (%0d muestras)", compared),
          mism == 0 && compared == 2000);

    //----------------------------------------------------------------------
    // 2) Exactitud con huecos de dv y L, G intermedios
    //----------------------------------------------------------------------
    configure(5, 3, 18'h3FFFF, 0);
    for (i = 0; i < 1500; i++) begin
      if ($urandom_range(0, 2) == 0) drive(0, 0);
      else                           drive($urandom_range(0, 4000) - 2000);
    end
    idle(8);
    check("modelo == RTL con huecos de dv (L=5 G=3)", mism == 0 && compared > 900);

    //----------------------------------------------------------------------
    // 3) L=1 G=0 es x[n]-x[n-1]; L=0 se satura a 1; L>LMAX a LMAX
    //----------------------------------------------------------------------
    configure(0, 0, 18'h3FFFF, 0);
    for (i = 0; i < 300; i++) drive($urandom_range(0, 1000) - 500);
    idle(8);
    check("L=0 -> L=1, G=0: diferencia de 1 muestra", mism == 0 && compared == 300);

    configure(31, 0, 18'h3FFFF, 0);
    for (i = 0; i < 300; i++) drive($urandom_range(0, 1000) - 500);
    idle(8);
    check("L=31 satura a LMAX=16", mism == 0 && compared == 300);

    //----------------------------------------------------------------------
    // 4) Escalón sobre una base: un pulso p, un pulso n, pico L·A
    //----------------------------------------------------------------------
    configure(4, 7, 800, 200);                  // L·A = 1600, thr = L·A/2
    hold(1000, 100);                            // base (arranque: no dispara)
    check("arranque sobre base 1000: sin pulsos", np == 0 && nn == 0);
    s_max = 0;                                  // descarta el transitorio de arranque
    hold(1400, 60);                             // escalón +400
    hold(1000, 60);                             // escalón -400
    idle(8);
    check("escalon de subida: exactamente 1 pulso p", np == 1);
    check("escalon de bajada: exactamente 1 pulso n", nn == 1);
    check($sformatf("pico de s = L*A = 1600 (medido %0d)", s_max), s_max == 1600);
    check("modelo == RTL en el escalon", mism == 0);
    check("tras los dos escalones los dos Schmitt re-armaron", ap === 1'b1 && an === 1'b1);

    //----------------------------------------------------------------------
    // 5) Continua grande y rampa lenta: no disparan
    //----------------------------------------------------------------------
    configure(4, 7, 800, 200);
    hold(6000, 200);                            // historia cero -> 6000: escalón falso
    check("continua 6000 desde el arranque: sin pulsos", np == 0 && nn == 0);
    for (i = 0; i < 400; i++) drive(6000 + 4*i);   // m=4: s = L·(L+G)·m = 176
    for (i = 0; i < 400; i++) drive(7600 - 4*i);
    idle(8);
    check("rampa lenta (s=176 < thr=800): sin pulsos", np == 0 && nn == 0);

    //----------------------------------------------------------------------
    // 6) Escalones ruidosos: la histéresis evita re-disparos
    //----------------------------------------------------------------------
    configure(8, 4, 1600, 800);                 // L·A = 3200
    hold(0, 60);
    for (k = 0; k < 20; k++) begin
      for (i = 0; i < 80; i++) drive(400 + $urandom_range(0, 60) - 30);
      for (i = 0; i < 80; i++) drive(       $urandom_range(0, 60) - 30);
    end
    idle(8);
    check($sformatf("20 escalones ruidosos: 20 pulsos p (%0d)", np), np == 20);
    check($sformatf("20 escalones ruidosos: 20 pulsos n (%0d)", nn), nn == 20);
    check("modelo == RTL con ruido", mism == 0);

    //----------------------------------------------------------------------
    // 7) Cambio de L en caliente: re-arranca sin pulsos y vuelve a disparar
    //----------------------------------------------------------------------
    configure(4, 7, 800, 200);
    chk_en = 0;                                 // el modelo no sigue el cambio en caliente
    hold(3000, 100);
    np = 0; nn = 0;
    for (i = 0; i < 200; i++) begin
      if (i == 50)  len = 8;                    // L·A con la base = 24000 si no re-arrancara
      if (i == 120) gap = 2;
      drive(3000);
    end
    check("cambio de L/G en caliente: sin pulsos", np == 0 && nn == 0);
    hold(3400, 60);
    check("tras el cambio vuelve a disparar", np == 1);
    hold(3000, 60);
    check("y el escalon de bajada da pulso n", nn == 1);

    //----------------------------------------------------------------------
    // 8) cfg_en = 0: nada
    //----------------------------------------------------------------------
    configure(4, 7, 100, 50, 0);
    chk_en = 0;
    for (k = 0; k < 5; k++) begin hold(2000, 40); hold(0, 40); end
    check("cfg_en=0: sin pulsos", np == 0 && nn == 0);
    check("cfg_en=0: s queda en 0", dut.s == 0);
    check("cfg_en=0: desarmado (no puede disparar)", ap === 1'b0 && an === 1'b0);
    check($sformatf("armado_p: los %0d pulsos p salen con el Schmitt recien desarmado", arm_np),
          arm_vp == 0 && arm_np > 20);
    check($sformatf("armado_n: los %0d pulsos n salen con el Schmitt recien desarmado", arm_nn),
          arm_vn == 0 && arm_nn > 20);

    $display("---------------------------------------------");
    $display("tb_mt_slope_trig: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt != 0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #2_000_000; $display("TIMEOUT"); $finish; end

endmodule
