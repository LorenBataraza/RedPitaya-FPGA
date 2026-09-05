`timescale 1ns/1ps
//============================================================================
// tb_mca_div_restore — unidad. Verifica el divisor restaurador del eje PSD:
//   - barrido EXHAUSTIVO de num/den con anchos reducidos (D_W=8, Q_W=6)
//   - den == 0            -> err_o, sin colgarse
//   - num >= den          -> sat_o y q = 2^Q_W-1 (NO el wrap a 0)
//   - latencia exacta = Q_W ciclos, busy_o sólo durante ese lapso
//============================================================================
module tb_mca_div_restore;

  localparam integer D_W = 8, Q_W = 6;

  reg              clk=0, rstn=0;
  always #5 clk = ~clk;

  reg              start=0;
  reg  [D_W-1:0]   num=0, den=0;
  wire [Q_W-1:0]   q;
  wire             valid, err, sat, busy;

  mca_div_restore #(.D_W(D_W), .Q_W(Q_W)) dut (
    .clk_i(clk), .rstn_i(rstn),
    .start_i(start), .num_i(num), .den_i(den),
    .q_o(q), .valid_o(valid), .err_o(err), .sat_o(sat), .busy_o(busy)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  [num=%0d den=%0d q=%0d err=%b sat=%b]",
                 name, num, den, q, err, sat); end
    end
  endtask

  // Lanza una division y espera el valid. Devuelve la latencia medida.
  task automatic run_div(input integer n, input integer d, output integer lat);
    begin
      @(negedge clk);
      num = n[D_W-1:0]; den = d[D_W-1:0]; start = 1'b1;
      @(negedge clk);
      start = 1'b0;
      lat = 0;
      while (!valid) begin @(negedge clk); lat = lat + 1; if (lat > 100) begin
        $display("  FAIL: timeout esperando valid (num=%0d den=%0d)", n, d);
        fail_cnt = fail_cnt + 1; disable run_div; end
      end
    end
  endtask

  task automatic reset_dut;
    begin rstn=0; @(negedge clk); @(negedge clk); rstn=1; @(negedge clk); end
  endtask

  integer n, d, lat, expected, errs_sweep;

  initial begin
    $dumpfile("tb_mca_div_restore.vcd");
    $dumpvars(0, tb_mca_div_restore);

    reset_dut;

    //-----------------------------------------------------------------------
    // 1) Barrido EXHAUSTIVO del camino normal: den en 1..2^D_W-1, num en 0..den-1
    //    Referencia: la division entera de Verilog.
    //-----------------------------------------------------------------------
    errs_sweep = 0;
    for (d = 1; d < (1<<D_W); d = d + 1) begin
      for (n = 0; n < d; n = n + 1) begin
        run_div(n, d, lat);
        expected = (n << Q_W) / d;
        if (q !== expected[Q_W-1:0] || err !== 1'b0 || sat !== 1'b0) begin
          if (errs_sweep < 5)   // no inundar el log
            $display("  FAIL sweep: num=%0d den=%0d -> q=%0d (esperado %0d) err=%b sat=%b",
                     n, d, q, expected, err, sat);
          errs_sweep = errs_sweep + 1;
        end
      end
    end
    check("barrido exhaustivo num<den contra division de referencia", errs_sweep==0);
    $display("  (barrido: %0d combinaciones, %0d discrepancias)",
             ((1<<D_W)*((1<<D_W)-1))/2, errs_sweep);

    //-----------------------------------------------------------------------
    // 2) den == 0 -> err_o
    //-----------------------------------------------------------------------
    reset_dut;
    run_div(0, 0, lat);
    check("den=0: err_o alto",            err===1'b1);
    check("den=0: sat_o bajo",            sat===1'b0);
    check("den=0: q=0 (no todo unos)",    q===
          {Q_W{1'b0}});
    run_div(37, 0, lat);
    check("den=0 con num!=0: err_o alto", err===1'b1);
    check("den=0 con num!=0: q=0",        q==={Q_W{1'b0}});

    //-----------------------------------------------------------------------
    // 3) num >= den -> sat_o, q = 2^Q_W-1. Sin esta guarda num==den envuelve a 0,
    //    que es el modo de falla peligroso (evento al extremo OPUESTO del eje).
    //-----------------------------------------------------------------------
    reset_dut;
    run_div(50, 50, lat);
    check("num==den: sat_o alto",              sat===1'b1);
    check("num==den: q satura a 2^Q_W-1",      q==={Q_W{1'b1}});
    check("num==den: err_o bajo",              err===1'b0);
    run_div(200, 50, lat);
    check("num>den: sat_o alto",               sat===1'b1);
    check("num>den: q satura a 2^Q_W-1",       q==={Q_W{1'b1}});
    run_div(255, 1, lat);
    check("num>>den: q satura, no envuelve",   q==={Q_W{1'b1}});

    //-----------------------------------------------------------------------
    // 4) Casos de valor conocido
    //-----------------------------------------------------------------------
    reset_dut;
    run_div(0, 100, lat);
    check("num=0: q=0",                        q==={Q_W{1'b0}});
    run_div(50, 100, lat);                     // 1/2 -> 32 de 64
    check("num/den=1/2: q=32",                 q===6'd32);
    run_div(25, 100, lat);                     // 1/4 -> 16
    check("num/den=1/4: q=16",                 q===6'd16);
    run_div(75, 100, lat);                     // 3/4 -> 48
    check("num/den=3/4: q=48",                 q===6'd48);

    //-----------------------------------------------------------------------
    // 5) Latencia fija = Q_W ciclos, tambien en los casos borde
    //-----------------------------------------------------------------------
    reset_dut;
    run_div(50, 100, lat);
    check("latencia normal = Q_W ciclos",      lat==Q_W);
    run_div(0, 0, lat);
    check("latencia con den=0 = Q_W ciclos",   lat==Q_W);
    run_div(200, 50, lat);
    check("latencia con saturacion = Q_W",     lat==Q_W);

    // busy_o baja tras el valid y no vuelve a subir solo
    @(negedge clk);
    check("busy_o bajo tras terminar",         busy===1'b0);
    @(negedge clk); @(negedge clk);
    check("busy_o sigue bajo sin start",       busy===1'b0);

    //-----------------------------------------------------------------------
    // 6) start_i durante busy se ignora (no corrompe la division en curso)
    //-----------------------------------------------------------------------
    reset_dut;
    @(negedge clk);
    num = 8'd50; den = 8'd100; start = 1'b1;
    @(negedge clk); start = 1'b0;
    @(negedge clk);                     // en plena division
    num = 8'd99; den = 8'd100; start = 1'b1;   // intento de arranque espurio
    @(negedge clk); start = 1'b0;
    while (!valid) @(negedge clk);
    check("start durante busy se ignora (q sigue siendo 32)", q===6'd32);

    $display("---------------------------------------------");
    $display("tb_mca_div_restore: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #200000000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
