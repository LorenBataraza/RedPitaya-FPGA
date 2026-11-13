`timescale 1ns/1ps
// tb_sys_bus_split — el reparto de un slot entre dos esclavos
//
// Dos esclavos de mentira con latencias de ack distintas y registros propios.
// Por cada direccion (las dos mitades, los bordes de la region de B, la
// direccion entera con y sin la base del slot):
//   - la escritura llega solo al esclavo que corresponde
//   - la lectura devuelve el dato, el err y el ack de ese esclavo
//   - el otro no ve ni un ciclo de wen/ren
module tb_sys_bus_split;
  reg clk = 0;
  always #4 clk = ~clk;

  reg  [31:0] addr = 0, wdata = 0;
  reg         wen = 0, ren = 0;
  wire [31:0] rdata;
  wire        err, ack;

  wire [31:0] a_addr, a_wdata, b_addr, b_wdata;
  wire        a_wen, a_ren, b_wen, b_ren;
  reg  [31:0] a_rdata, b_rdata;
  reg         a_ack = 0, b_ack = 0;

  sys_bus_split #(.SEL_B(4'h1)) dut (
    .s_addr(addr), .s_wdata(wdata), .s_wen(wen), .s_ren(ren),
    .s_rdata(rdata), .s_err(err), .s_ack(ack),
    .a_addr(a_addr), .a_wdata(a_wdata), .a_wen(a_wen), .a_ren(a_ren),
    .a_rdata(a_rdata), .a_err(1'b1), .a_ack(a_ack),
    .b_addr(b_addr), .b_wdata(b_wdata), .b_wen(b_wen), .b_ren(b_ren),
    .b_rdata(b_rdata), .b_err(1'b0), .b_ack(b_ack)
  );

  // Los esclavos: un registro cada uno, ack a los 2 (A) y a los 4 (B) ciclos
  reg [31:0] reg_a = 0, reg_b = 0;
  integer    vistos_a = 0, vistos_b = 0;
  reg [3:0]  sr_a = 0, sr_b = 0;
  always @(posedge clk) begin
    sr_a <= {sr_a[2:0], a_wen | a_ren};
    sr_b <= {sr_b[2:0], b_wen | b_ren};
    a_ack <= sr_a[0];
    b_ack <= sr_b[2];
    if (a_wen) reg_a <= a_wdata;
    if (b_wen) reg_b <= b_wdata;
    a_rdata <= reg_a ^ a_addr;
    b_rdata <= reg_b ^ b_addr;
    if (a_wen | a_ren) vistos_a++;
    if (b_wen | b_ren) vistos_b++;
  end

  integer pass_cnt = 0, fail_cnt = 0;
  task automatic checkv(input string name, input longint got, input longint exp);
    if (got === exp) pass_cnt++;
    else begin fail_cnt++; $display("FAIL %s: 0x%0h, esperaba 0x%0h", name, got, exp); end
  endtask

  // Como sys_bus_cdc: wen/ren y la direccion quietos hasta el ack
  task automatic wr(input [31:0] a, input [31:0] d);
    @(negedge clk); addr = a; wdata = d; wen = 1;
    #1;                      // el ack del esclavo nuevo, no del anterior
    while (!ack) @(negedge clk);
    wen = 0; @(negedge clk);
  endtask
  task automatic rd(input [31:0] a, output [31:0] d, output bit e);
    @(negedge clk); addr = a; ren = 1;
    #1;
    while (!ack) @(negedge clk);
    d = rdata; e = err; ren = 0; @(negedge clk);
  endtask

  reg [31:0] d;
  bit        e;
  integer    va, vb;
  initial begin
    repeat (3) @(negedge clk);
    for (int i = 0; i < 8; i++) begin
      automatic logic [31:0] adr = (i == 0) ? 32'h4020_0000 : (i == 1) ? 32'h4020_FFFC :
                                   (i == 2) ? 32'h4022_0000 : (i == 3) ? 32'h402F_0000 :
                                   (i == 4) ? 32'h0000_0010 : (i == 5) ? 32'h4021_0000 :
                                   (i == 6) ? 32'h4021_FFFC :              32'h0001_1000;
      automatic bit es_b = (adr[19:16] == 4'h1);
      automatic logic [31:0] dato = 32'hC0DE_0000 | i;
      va = vistos_a; vb = vistos_b;
      wr(adr, dato);
      rd(adr, d, e);
      if (es_b) begin
        checkv($sformatf("0x%08h va a B: el registro de B", adr), reg_b, dato);
        checkv($sformatf("0x%08h va a B: el dato de B", adr), d, dato ^ adr);
        checkv($sformatf("0x%08h va a B: el err de B", adr), e, 0);
        checkv($sformatf("0x%08h: A no vio nada", adr), vistos_a, va);
      end else begin
        checkv($sformatf("0x%08h va a A: el registro de A", adr), reg_a, dato);
        checkv($sformatf("0x%08h va a A: el dato de A", adr), d, dato ^ adr);
        checkv($sformatf("0x%08h va a A: el err de A", adr), e, 1);
        checkv($sformatf("0x%08h: B no vio nada", adr), vistos_b, vb);
      end
    end
    $display("tb_sys_bus_split: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin #1ms; $display("RESULT: FAIL (timeout global)"); $finish; end
endmodule
