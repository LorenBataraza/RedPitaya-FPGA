`timescale 1ns/1ps
//============================================================================
// tb_mca_hist — unidad. Verifica el motor de histograma:
//   - incrementos simples y acumulados
//   - FORWARDING: incrementos en ciclos consecutivos a la MISMA dirección
//     (el caso donde es más fácil un off-by-one)
//   - saturación del contador (se instancia con CW=8 para poder alcanzarla)
//   - barrido de borrado, y que el puerto de LECTURA siga vivo durante él
//     (precondición para que el bus no se cuelgue)
//   - contador de descartes
//============================================================================
module tb_mca_hist;

  localparam integer AW = 4;    // 16 bins: barrido de borrado corto
  localparam integer CW = 8;    // saturación alcanzable en 255 incrementos
  localparam integer NB = (1<<AW);

  reg             clk=0, rstn=0;
  always #5 clk = ~clk;

  reg             inc=0;
  reg  [AW-1:0]   inc_addr=0;
  reg             clear=0;
  reg             rd=0;
  reg  [AW-1:0]   rd_addr=0;
  wire [CW-1:0]   rd_data;
  wire            busy;
  wire [31:0]     dropped;

  mca_hist #(.AW(AW), .CW(CW)) dut (
    .clk_i(clk), .rstn_i(rstn),
    .inc_i(inc), .inc_addr_i(inc_addr),
    .clear_i(clear), .busy_o(busy),
    .rd_i(rd), .rd_addr_i(rd_addr), .rd_data_o(rd_data),
    .dropped_o(dropped)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1; $display("  FAIL: %s", name); end
    end
  endtask

  //--------------------------------------------------------------------------
  // Tareas de estímulo
  //--------------------------------------------------------------------------
  // Lectura de bus: rd_i es un PULSO de 1 ciclo; el dato sale 2 ciclos después.
  task automatic bus_rd(input [AW-1:0] a, output [CW-1:0] d);
    begin
      @(negedge clk); rd_addr = a; rd = 1'b1;
      @(negedge clk); rd = 1'b0;      // pasó el posedge que cargó pb_dout
      @(negedge clk); d = rd_data;    // pasó el posedge que cargó rd_data_r
    end
  endtask

  // Un incremento en un único ciclo.
  task automatic inc1(input [AW-1:0] a);
    begin
      @(negedge clk); inc_addr = a; inc = 1'b1;
      @(negedge clk); inc = 1'b0;
    end
  endtask

  // n incrementos en n ciclos CONSECUTIVOS a la misma dirección (test forwarding).
  task automatic inc_burst(input [AW-1:0] a, input integer n);
    integer k;
    begin
      @(negedge clk); inc_addr = a; inc = 1'b1;
      for (k=0; k<n; k=k+1) @(negedge clk);
      inc = 1'b0;
    end
  endtask

  // Alterna entre dos direcciones, 1 incremento por ciclo, n ciclos.
  task automatic inc_alt(input [AW-1:0] a, input [AW-1:0] b, input integer n);
    integer k;
    begin
      @(negedge clk); inc = 1'b1;
      for (k=0; k<n; k=k+1) begin
        inc_addr = (k[0]) ? b : a;
        @(negedge clk);
      end
      inc = 1'b0;
    end
  endtask

  task automatic flush;  begin repeat(4) @(negedge clk); end  endtask

  task automatic do_clear;
    begin
      @(negedge clk); clear = 1'b1;
      @(negedge clk); clear = 1'b0;
      while (busy) @(negedge clk);
      @(negedge clk);
    end
  endtask

  task automatic reset_dut;
    begin rstn=0; repeat(2) @(negedge clk); rstn=1; @(negedge clk); end
  endtask

  reg [CW-1:0] d;
  integer i, nz;

  initial begin
    $dumpfile("tb_mca_hist.vcd");
    $dumpvars(0, tb_mca_hist);

    reset_dut;

    //-----------------------------------------------------------------------
    // 1) Estado inicial: todos los bins en cero
    //-----------------------------------------------------------------------
    nz = 0;
    for (i=0; i<NB; i=i+1) begin bus_rd(i[AW-1:0], d); if (d !== {CW{1'b0}}) nz = nz+1; end
    check("todos los bins arrancan en 0", nz==0);

    //-----------------------------------------------------------------------
    // 2) Incremento simple y acumulación
    //-----------------------------------------------------------------------
    inc1(4'd5); flush;
    bus_rd(4'd5, d);  check("1 incremento en bin 5 -> 1", d===8'd1);
    bus_rd(4'd6, d);  check("bin vecino sin tocar -> 0", d===8'd0);

    for (i=0; i<9; i=i+1) begin inc1(4'd5); flush; end
    bus_rd(4'd5, d);  check("10 incrementos espaciados -> 10", d===8'd10);

    //-----------------------------------------------------------------------
    // 3) FORWARDING: incrementos en ciclos CONSECUTIVOS a la misma dirección.
    //    Distancia 1 y 2 requieren puentear la escritura en vuelo.
    //-----------------------------------------------------------------------
    do_clear;
    inc_burst(4'd3, 2); flush;
    bus_rd(4'd3, d);  check("forwarding: 2 incrementos consecutivos -> 2", d===8'd2);

    do_clear;
    inc_burst(4'd3, 3); flush;
    bus_rd(4'd3, d);  check("forwarding: 3 incrementos consecutivos -> 3", d===8'd3);

    do_clear;
    inc_burst(4'd3, 4); flush;
    bus_rd(4'd3, d);  check("forwarding: 4 incrementos consecutivos -> 4", d===8'd4);

    do_clear;
    inc_burst(4'd7, 20); flush;
    bus_rd(4'd7, d);  check("forwarding: 20 incrementos consecutivos -> 20", d===8'd20);

    // Alternado A,B,A,B a 1 por ciclo: distancia 2 al mismo bin
    do_clear;
    inc_alt(4'd1, 4'd2, 20); flush;
    bus_rd(4'd1, d);  check("alternado A,B x20: bin A -> 10", d===8'd10);
    bus_rd(4'd2, d);  check("alternado A,B x20: bin B -> 10", d===8'd10);

    // Todas direcciones distintas, 1 por ciclo
    do_clear;
    @(negedge clk); inc = 1'b1;
    for (i=0; i<NB; i=i+1) begin inc_addr = i[AW-1:0]; @(negedge clk); end
    inc = 1'b0;
    flush;
    nz = 0;
    for (i=0; i<NB; i=i+1) begin bus_rd(i[AW-1:0], d); if (d !== 8'd1) nz = nz+1; end
    check("16 direcciones distintas a 1/ciclo -> todos en 1", nz==0);

    //-----------------------------------------------------------------------
    // 4) Saturación: se queda en 2^CW-1, NO envuelve a 0
    //-----------------------------------------------------------------------
    do_clear;
    inc_burst(4'd9, 300);           // 300 > 255
    flush;
    bus_rd(4'd9, d);  check("saturacion: se queda en 2^CW-1 (255)", d===8'd255);
    inc1(4'd9); flush;
    bus_rd(4'd9, d);  check("saturacion: sigue en 255 tras otro incremento", d===8'd255);

    //-----------------------------------------------------------------------
    // 5) Barrido de borrado
    //-----------------------------------------------------------------------
    do_clear;
    inc1(4'd2); inc1(4'd8); inc1(4'd15); flush;
    bus_rd(4'd15, d); check("pre-borrado: bin 15 en 1", d===8'd1);
    do_clear;
    nz = 0;
    for (i=0; i<NB; i=i+1) begin bus_rd(i[AW-1:0], d); if (d !== {CW{1'b0}}) nz = nz+1; end
    check("tras el borrado todos los bins en 0", nz==0);

    //-----------------------------------------------------------------------
    // 6) El puerto de LECTURA sigue vivo durante el barrido.
    //    Si se colgara, el bus se colgaria (32 ciclos de timeout vs 16k de barrido).
    //-----------------------------------------------------------------------
    do_clear;
    inc_burst(4'd4, 5); flush;
    @(negedge clk); clear = 1'b1;
    @(negedge clk); clear = 1'b0;
    check("barrido en curso (busy alto)", busy===1'b1);
    bus_rd(4'd0, d);                       // lectura EN MEDIO del barrido
    check("la lectura responde durante el barrido", busy===1'b1 && d!==8'hxx);
    while (busy) @(negedge clk);
    @(negedge clk);
    check("busy baja al terminar el barrido", busy===1'b0);

    //-----------------------------------------------------------------------
    // 7) Contador de descartes: eventos que llegan durante el barrido
    //-----------------------------------------------------------------------
    do_clear;
    check("dropped se resetea con el borrado", dropped===32'd0);
    @(negedge clk); clear = 1'b1;
    @(negedge clk); clear = 1'b0;          // arranca el barrido
    inc_burst(4'd1, 5);                    // 5 eventos durante el barrido
    while (busy) @(negedge clk);
    flush;
    check("dropped cuenta los 5 eventos del barrido", dropped===32'd5);
    bus_rd(4'd1, d);
    check("esos eventos NO se contabilizaron en el bin", d===8'd0);

    //-----------------------------------------------------------------------
    // 8) Los eventos en vuelo al arrancar un borrado se descartan
    //    (si no, escribirian despues del barrido y ensuciarian el histograma)
    //-----------------------------------------------------------------------
    do_clear;
    @(negedge clk); inc_addr = 4'd6; inc = 1'b1;   // evento entrando...
    @(negedge clk); inc = 1'b0; clear = 1'b1;      // ...y borrado justo detras
    @(negedge clk); clear = 1'b0;
    while (busy) @(negedge clk);
    flush;
    bus_rd(4'd6, d);
    check("evento en vuelo al borrar no deja cuenta suelta", d===8'd0);

    $display("---------------------------------------------");
    $display("tb_mca_hist: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #500000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
