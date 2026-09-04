`timescale 1ns/1ps
//============================================================================
// tb_integration_cfg — contrato de bus + registros de la región de TOP.
//
// Dos cosas que verificar:
//
//  1. CONTRATO DE BUS. El BFM imita a sys_bus_cdc (sostiene wen/ren hasta el
//     ack) y FALLA si el ack no llega en <= 20 ciclos, barriendo TODAS las
//     direcciones del slot: registros, huecos, offsets altos y no mapeados.
//     Es la misma regresión que tb_mca_top: un esclavo que no hace ack deja el
//     CDC del slot desincronizado, no sólo devuelve un valor malo.
//
//  2. EL RESET ES EL COMPORTAMIENTO PRE-REFACTOR. Todos los ROUTE_* tienen que
//     arrancar en TAP_NATIVE con enable en 1. Es la propiedad que hace que el
//     refactor sea neutro: si esto falla, cargar el bitstream nuevo cambia el
//     hardware sin que nadie lo haya pedido.
//============================================================================
module tb_integration_cfg;

  localparam [1:0] TAP_NATIVE  = 2'd0;
  localparam [1:0] TAP_ADC     = 2'd1;
  localparam [1:0] TAP_DEC_IN  = 2'd2;
  localparam [1:0] TAP_BRAM_IN = 2'd3;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg  [31:0] addr = 0, wdata = 0;
  reg         wen = 0, ren = 0;
  wire [31:0] rdata;
  wire        err, ack;

  wire [1:0] r_osc_tap, r_mtrg_tap, r_mca_tap, r_ring_tap;
  wire       r_osc_en,  r_mtrg_en,  r_mca_en,  r_ring_en;
  wire       ctrl_run, ctrl_clear, ctrl_srst;

  localparam [31:0] MAGIC   = 32'h494E5447;
  localparam [31:0] VERSION = 32'h0001_0000;

  integration_cfg #(
    .MAGIC(MAGIC), .VERSION(VERSION),
    .GITH({32'hDEADBEEF, 32'h11111111, 32'h22222222, 32'h33333333, 32'h44444444}),
    .EN_OSC(1), .EN_MTRG(1), .EN_MCA(1), .EN_RING(0), .EN_ASG(0), .EN_PID(0),
    .SLOT_OSC(1), .SLOT_RING(2), .SLOT_MTRG(3), .SLOT_TOP(6), .SLOT_MCA(7),
    .N_CH(2), .DW(14), .RSZ(14), .EN_FILT(0), .H_AW(14), .H2_AW(7), .PSD_AW(6)
  ) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .route_osc_tap_o (r_osc_tap ), .route_osc_en_o (r_osc_en ),
    .route_mtrg_tap_o(r_mtrg_tap), .route_mtrg_en_o(r_mtrg_en),
    .route_mca_tap_o (r_mca_tap ), .route_mca_en_o (r_mca_en ),
    .route_ring_tap_o(r_ring_tap), .route_ring_en_o(r_ring_en),
    .ctrl_run_o(ctrl_run), .ctrl_clear_o(ctrl_clear), .ctrl_srst_o(ctrl_srst),
    .pll_locked_i(1'b1),
    .sys_addr(addr), .sys_wdata(wdata), .sys_wen(wen), .sys_ren(ren),
    .sys_rdata(rdata), .sys_err(err), .sys_ack(ack)
  );

  integer pass_cnt = 0, fail_cnt = 0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt = pass_cnt + 1;
      else begin fail_cnt = fail_cnt + 1; $display("  FAIL: %s", name); end
    end
  endtask
  task automatic checkv(input string name, input [31:0] got, input [31:0] exp);
    begin
      if (got === exp) pass_cnt = pass_cnt + 1;
      else begin fail_cnt = fail_cnt + 1;
        $display("  FAIL: %s  (obtenido 0x%08h, esperado 0x%08h)", name, got, exp); end
    end
  endtask

  //--------------------------------------------------------------------------
  // BFM: imita a sys_bus_cdc — sostiene wen/ren hasta ver el ack.
  //--------------------------------------------------------------------------
  localparam integer ACK_LIMIT = 20;
  integer ack_timeouts = 0;
  integer err_seen     = 0;

  task automatic bus_write(input [19:0] a, input [31:0] d);
    integer n;
    begin
      @(negedge clk); addr = {12'h406, a}; wdata = d; wen = 1'b1;
      n = 0;
      while (!ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!ack) begin ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK en escritura a 0x%05h", a); end
      if (err) err_seen = err_seen + 1;
      @(negedge clk); wen = 1'b0; addr = 0;
      while (ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  task automatic bus_read(input [19:0] a, output [31:0] d);
    integer n;
    begin
      @(negedge clk); addr = {12'h406, a}; ren = 1'b1;
      n = 0;
      while (!ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!ack) begin ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK en lectura de 0x%05h", a); end
      if (err) err_seen = err_seen + 1;
      d = rdata;
      @(negedge clk); ren = 1'b0; addr = 0;
      while (ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  reg [31:0] d;
  integer i;
  integer clear_seen, srst_seen;

  // Cuenta cuántos ciclos estuvieron altos los autolimpiantes.
  always @(posedge clk) if (rstn) begin
    if (ctrl_clear) clear_seen = clear_seen + 1;
    if (ctrl_srst)  srst_seen  = srst_seen  + 1;
  end

  initial begin
    $dumpfile("tb_integration_cfg.vcd");
    $dumpvars(0, tb_integration_cfg);
    clear_seen = 0; srst_seen = 0;

    repeat (10) @(negedge clk);
    rstn = 1;
    repeat (10) @(negedge clk);

    //----------------------------------------------------------------------
    // 1. EL RESET ES EL COMPORTAMIENTO PRE-REFACTOR
    //----------------------------------------------------------------------
    $display("-- reset: todos los consumidores en NATIVO --");
    check("ROUTE_OSC  tap = NATIVO en reset", r_osc_tap  === TAP_NATIVE);
    check("ROUTE_MTRG tap = NATIVO en reset", r_mtrg_tap === TAP_NATIVE);
    check("ROUTE_MCA  tap = NATIVO en reset", r_mca_tap  === TAP_NATIVE);
    check("ROUTE_RING tap = NATIVO en reset", r_ring_tap === TAP_NATIVE);
    check("ROUTE_OSC  enable en reset",  r_osc_en  === 1'b1);
    check("ROUTE_MTRG enable en reset",  r_mtrg_en === 1'b1);
    check("ROUTE_MCA  enable en reset",  r_mca_en  === 1'b1);
    check("ROUTE_RING enable en reset",  r_ring_en === 1'b1);
    check("run global apagado en reset", ctrl_run  === 1'b0);

    //----------------------------------------------------------------------
    // 2. IDENTIFICACIÓN Y DESCRIPCIÓN
    //----------------------------------------------------------------------
    $display("-- identificacion y descripcion del sistema --");
    bus_read(20'h000, d); checkv("MAGIC",   d, MAGIC);
    bus_read(20'h004, d); checkv("VERSION", d, VERSION);
    bus_read(20'h008, d); checkv("GITH_0",  d, 32'hDEADBEEF);
    bus_read(20'h018, d); checkv("GITH_4",  d, 32'h44444444);

    // MODULES: OSC(b0) + MTRG(b1) + MCA(b2) presentes; RING/ASG/PID no.
    bus_read(20'h020, d); checkv("MODULES", d, 32'h0000_0007);
    // SLOTS: {MCA=7, TOP=6, MTRG=3, RING=2, OSC=1}
    bus_read(20'h024, d); checkv("SLOTS",   d, 32'h0007_6321);
    // CAPS0: EN_FILT=0, RSZ=14, DW=14, N_CH=2
    bus_read(20'h028, d); checkv("CAPS0",   d, {7'h0, 1'b0, 2'h0, 6'd14, 2'h0, 6'd14, 4'h0, 4'd2});
    // CAPS1: PSD_AW=6, H2_AW=7, H_AW=14
    bus_read(20'h02C, d); checkv("CAPS1",   d, {8'h0, 8'd6, 8'd7, 8'd14});

    //----------------------------------------------------------------------
    // 3. RUTEO: escritura, readback y efecto en los puertos
    //----------------------------------------------------------------------
    $display("-- ruteo del datapath --");
    bus_write(20'h038, {23'h0, 1'b1, 6'h0, TAP_DEC_IN});   // MCA -> pre-decimacion
    check("ROUTE_MCA tap = DEC_IN", r_mca_tap === TAP_DEC_IN);
    check("ROUTE_MCA enable sigue en 1", r_mca_en === 1'b1);
    bus_read(20'h038, d); checkv("ROUTE_MCA readback", d, {23'h0, 1'b1, 6'h0, TAP_DEC_IN});

    bus_write(20'h030, {23'h0, 1'b0, 6'h0, TAP_ADC});      // OSC -> crudo, deshabilitado
    check("ROUTE_OSC tap = ADC",     r_osc_tap === TAP_ADC);
    check("ROUTE_OSC enable en 0",   r_osc_en  === 1'b0);
    bus_read(20'h030, d); checkv("ROUTE_OSC readback", d, {23'h0, 1'b0, 6'h0, TAP_ADC});

    bus_write(20'h034, {23'h0, 1'b1, 6'h0, TAP_BRAM_IN});
    check("ROUTE_MTRG tap = BRAM_IN", r_mtrg_tap === TAP_BRAM_IN);

    // Escribir un ROUTE no toca a los demas
    check("ROUTE_RING intacto tras escribir los otros", r_ring_tap === TAP_NATIVE);

    //----------------------------------------------------------------------
    // 4. CONTROL GLOBAL: run es nivel, clear/srst son de UN ciclo
    //----------------------------------------------------------------------
    $display("-- control global --");
    clear_seen = 0; srst_seen = 0;
    bus_write(20'h040, 32'h0000_0001);                     // run = 1
    check("run global en 1", ctrl_run === 1'b1);
    bus_read(20'h040, d); checkv("CTRL readback", d, 32'h0000_0001);
    check("clear no se activo", clear_seen === 0);

    clear_seen = 0;
    bus_write(20'h040, 32'h0000_0003);                     // run=1 + clear
    // El estrobo de un ciclo es lo que impide que clear valga 5 ciclos por
    // culpa de que sys_bus_cdc sostiene wen hasta el ack.
    checkv("clear duro exactamente 1 ciclo", clear_seen, 1);
    check("run sigue en 1 tras el clear", ctrl_run === 1'b1);

    srst_seen = 0;
    bus_write(20'h040, 32'h0000_0004);                     // solo srst
    checkv("srst duro exactamente 1 ciclo", srst_seen, 1);
    check("run bajo a 0", ctrl_run === 1'b0);

    //----------------------------------------------------------------------
    // 5. BARRIDO DE ACK: toda dirección del slot tiene que responder
    //----------------------------------------------------------------------
    $display("-- barrido de ack sobre todo el slot --");
    for (i = 0; i < 20'h200; i = i + 4) bus_read(i[19:0], d);
    // huecos, offsets altos y direcciones no mapeadas
    for (i = 20'h1000; i < 20'h1040; i = i + 4) bus_read(i[19:0], d);
    bus_read(20'h50000, d); checkv("no mapeada devuelve 0", d, 32'h0);
    bus_read(20'hFFFFC, d); checkv("tope del slot devuelve 0", d, 32'h0);
    bus_write(20'h50000, 32'hA5A5A5A5);   // escritura a no mapeada: no debe colgar

    checkv("sin timeouts de ack", ack_timeouts, 0);
    checkv("sin err en ningun acceso", err_seen, 0);

    $display("tb_integration_cfg: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end

endmodule
