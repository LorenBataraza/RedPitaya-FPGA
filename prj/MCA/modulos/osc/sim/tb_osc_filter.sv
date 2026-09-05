`timescale 1ns/1ps
//============================================================================
// tb_osc_filter — EQUIVALENCIA del ecualizador rediseñado contra el original.
//
// El rediseño de osc_filter.v es puramente de timing: reagrupa los lazos IIR
// para que las sumas caigan en el post-sumador del DSP48E1 en vez de en una
// cadena de acarreo en fabric. Las dos transformaciones son identidades
// algebraicas EXACTAS en punto fijo:
//     IIR1:  (y <<< 25) - y*aa        ==  y * (2^25 - aa)
//     IIR2:  floor(a/2^16) + b        ==  floor( (a + b*2^16) / 2^16 )
//
// Por eso este TB no compara "parecido": instancia el filtro NUEVO y la copia
// congelada del ORIGINAL (osc_filter_ref.v), les mete el mismo estímulo y
// exige que m_axis_tdata coincida BIT A BIT en todos los ciclos. Es la única
// verificación fuerte posible sin poder medir en la placa.
//
// Se barren varios juegos de coeficientes, incluidos los de reset (que son los
// que usa el driver hoy) y casos extremos que fuerzan saturación y desborde.
//============================================================================
module tb_osc_filter;

  localparam integer DW = 14;

  reg clk = 0, rst_n = 0;
  always #4 clk = ~clk;          // 125 MHz, como adc_clk

  reg  [DW-1:0] din = 0;
  reg           dvalid = 0;
  reg  [17:0]   c_aa = 0;
  reg  [24:0]   c_bb = 0;
  reg  [24:0]   c_kk = 25'hFFFFFF;
  reg  [24:0]   c_pp = 0;

  wire [DW-1:0] dut_out, ref_out;
  wire          dut_val, ref_val;

  osc_filter #(.DW(DW)) i_dut (
    .clk(clk), .rst_n(rst_n),
    .s_axis_tdata(din), .s_axis_tvalid(dvalid), .s_axis_tready(),
    .m_axis_tdata(dut_out), .m_axis_tvalid(dut_val), .m_axis_tready(1'b1),
    .cfg_bypass(1'b0),
    .cfg_coeff_aa(c_aa), .cfg_coeff_bb(c_bb),
    .cfg_coeff_kk(c_kk), .cfg_coeff_pp(c_pp)
  );

  osc_filter_ref #(.DW(DW)) i_ref (
    .clk(clk), .rst_n(rst_n),
    .s_axis_tdata(din), .s_axis_tvalid(dvalid), .s_axis_tready(),
    .m_axis_tdata(ref_out), .m_axis_tvalid(ref_val), .m_axis_tready(1'b1),
    .cfg_bypass(1'b0),
    .cfg_coeff_aa(c_aa), .cfg_coeff_bb(c_bb),
    .cfg_coeff_kk(c_kk), .cfg_coeff_pp(c_pp)
  );

  integer pass_cnt=0, fail_cnt=0;
  integer mismatches, samples;

  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1; $display("  FAIL: %s", name); end
    end
  endtask

  // Comparador continuo: cualquier discrepancia en cualquier ciclo se cuenta.
  always @(posedge clk) begin
    if (rst_n) begin
      samples = samples + 1;
      if (dut_out !== ref_out) begin
        if (mismatches < 5)
          $display("    discrepancia @%0t : nuevo=%0h original=%0h (din=%0d)",
                   $time, dut_out, ref_out, $signed(din));
        mismatches = mismatches + 1;
      end
      if (dut_val !== ref_val) begin
        if (mismatches < 5) $display("    discrepancia en tvalid @%0t", $time);
        mismatches = mismatches + 1;
      end
    end
  end

  task automatic do_reset;
    begin
      rst_n = 0; dvalid = 0; din = 0;
      repeat (4) @(negedge clk);
      rst_n = 1;
      @(negedge clk);
    end
  endtask

  // Aplica un juego de coeficientes con el filtro en reset, que es lo que hace
  // el diseño real: multitrigger_rp_scope_cfg.sv:201 pulsa filt_rstn en cada
  // escritura de coeficientes.
  task automatic set_coeffs(input [17:0] aa, input [24:0] bb,
                            input [24:0] kk, input [24:0] pp);
    begin
      rst_n = 0; @(negedge clk);
      c_aa = aa; c_bb = bb; c_kk = kk; c_pp = pp;
      @(negedge clk); rst_n = 1; @(negedge clk);
    end
  endtask

  task automatic push(input integer v);
    begin @(negedge clk); din = v[DW-1:0]; dvalid = 1'b1; end
  endtask

  // Estímulos
  task automatic stim_impulse;
    integer k;
    begin
      push(0); push(0);
      push(4000);                       // impulso
      for (k=0;k<200;k=k+1) push(0);    // ver la respuesta completa
    end
  endtask

  task automatic stim_step;
    integer k;
    begin
      for (k=0;k<100;k=k+1) push(0);
      for (k=0;k<200;k=k+1) push(3000);
    end
  endtask

  task automatic stim_random(input integer n, input integer amp);
    integer k;
    begin
      for (k=0;k<n;k=k+1) push($signed($random) % amp);
    end
  endtask

  // Rieles del ADC: fuerza saturación en la etapa de escalado
  task automatic stim_rails(input integer n);
    integer k;
    begin
      for (k=0;k<n;k=k+1) push((k[0]) ? 8191 : -8192);
    end
  endtask

  task automatic run_case(input string name);
    begin
      mismatches = 0; samples = 0;
      stim_impulse;
      stim_step;
      stim_random(600, 8000);
      stim_rails(200);
      stim_random(400, 100);            // señal chica, cerca del ruido
      @(negedge clk); dvalid = 0;
      repeat (10) @(negedge clk);
      check(name, mismatches == 0);
      if (mismatches != 0)
        $display("    (%0d discrepancias en %0d ciclos)", mismatches, samples);
    end
  endtask

  initial begin
    $dumpfile("tb_osc_filter.vcd");
    $dumpvars(0, tb_osc_filter);
    mismatches = 0; samples = 0;

    do_reset;

    //-----------------------------------------------------------------------
    // 1) Coeficientes de RESET: aa=0, bb=0, kk=0xFFFFFF, pp=0.
    //    Es la configuración que usa el driver hoy, así que es la que más
    //    importa que sea idéntica.
    //-----------------------------------------------------------------------
    set_coeffs(18'h0, 25'h0, 25'hFFFFFF, 25'h0);
    run_case("coeficientes de reset (aa=0,bb=0,kk=0xFFFFFF,pp=0)");

    //-----------------------------------------------------------------------
    // 2) Compensación polo-cero tipica (aa != 0: activa el lazo recursivo,
    //    que es justo el que se rediseño)
    //-----------------------------------------------------------------------
    set_coeffs(18'd25000, 25'd1000000, 25'hFFFFFF, 25'd50000);
    run_case("compensacion tipica (aa=25000, bb=1e6, pp=50000)");

    //-----------------------------------------------------------------------
    // 3) aa grande positivo y negativo: el termino 2^25-aa se aleja del centro
    //-----------------------------------------------------------------------
    set_coeffs(18'sd131071, 25'd0, 25'hFFFFFF, 25'd0);
    run_case("aa maximo positivo (131071)");

    set_coeffs(-18'sd131072, 25'd0, 25'hFFFFFF, 25'd0);
    run_case("aa maximo negativo (-131072)");

    //-----------------------------------------------------------------------
    // 4) pp extremos: ejercita la reagrupacion del IIR2
    //-----------------------------------------------------------------------
    set_coeffs(18'd0, 25'd0, 25'hFFFFFF, 25'sd16777215);
    run_case("pp maximo (ejercita el IIR2 reagrupado)");

    set_coeffs(18'd0, 25'd0, 25'hFFFFFF, -25'sd16777216);
    run_case("pp maximo negativo");

    //-----------------------------------------------------------------------
    // 5) kk extremos: saturacion en la etapa de escalado
    //-----------------------------------------------------------------------
    set_coeffs(18'd0, 25'd0, 25'h1FFFFFF, 25'd0);
    run_case("kk maximo (fuerza saturacion)");

    set_coeffs(18'd0, 25'd0, 25'h0, 25'd0);
    run_case("kk = 0 (salida nula)");

    //-----------------------------------------------------------------------
    // 6) Todo al maximo a la vez: peor caso de desborde en los intermedios
    //-----------------------------------------------------------------------
    set_coeffs(18'sd131071, 25'sd16777215, 25'h1FFFFFF, 25'sd16777215);
    run_case("todos los coeficientes al maximo");

    //-----------------------------------------------------------------------
    // 7) Barrido aleatorio de coeficientes
    //-----------------------------------------------------------------------
    begin : sweep
      integer t, bad;
      bad = 0;
      for (t=0; t<12; t=t+1) begin
        set_coeffs($random, $random, $random, $random);
        mismatches = 0;
        stim_random(300, 8000);
        stim_rails(60);
        @(negedge clk); dvalid = 0;
        repeat (8) @(negedge clk);
        if (mismatches != 0) bad = bad + 1;
      end
      check("barrido de 12 juegos de coeficientes aleatorios", bad == 0);
    end

    $display("---------------------------------------------");
    $display("tb_osc_filter: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #5000000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
