`timescale 1ns/1ps
//============================================================================
// tb_slots_integration — las tres regiones cableadas como en el top.
//
// Replica el cableado de mca_red_pitaya_top: integration_cfg (slot 6) manda
// los ROUTE_* a rp_scope_multitrigger_com, que expone el bus del OSC (slot 1)
// y el del multitrigger (slot 3).
//
// Verifica lo que ningún TB de módulo suelto puede ver:
//
//  1. LAS TRES REGIONES SON INDEPENDIENTES. Escribir en un slot no altera los
//     otros, y cada uno responde su propio MAGIC. Es la razón de ser del
//     refactor.
//
//  2. EL RUTEO FUNCIONA DE PUNTA A PUNTA. Se escribe ROUTE_MCA en el slot 6 y
//     se observa que cambia el dato que sale por mca_dat_o. Con TAP_ADC la
//     muestra tiene que ser la CRUDA (pre-calibración): se le mete una
//     ganancia de calibración distinta de la unidad para que el nodo crudo y
//     el calibrado no puedan confundirse.
//
//  3. EL RESET ES EL COMPORTAMIENTO PRE-REFACTOR: sin escribir ningún ROUTE_*,
//     el MCA ve el nodo post-calibración, que es donde estaba cableado.
//============================================================================
module tb_slots_integration;

  localparam integer DW   = 14;
  localparam integer RSZ  = 14;
  localparam integer N_CH = 2;

  localparam [1:0] TAP_NATIVE  = 2'd0;
  localparam [1:0] TAP_ADC     = 2'd1;
  localparam [1:0] TAP_DEC_IN  = 2'd2;
  localparam [1:0] TAP_BRAM_IN = 2'd3;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  // --- tres buses independientes ---
  reg  [31:0] o_addr=0, o_wdata=0;  reg o_wen=0, o_ren=0;
  wire [31:0] o_rdata; wire o_err, o_ack;
  reg  [31:0] m_addr=0, m_wdata=0;  reg m_wen=0, m_ren=0;
  wire [31:0] m_rdata; wire m_err, m_ack;
  reg  [31:0] t_addr=0, t_wdata=0;  reg t_wen=0, t_ren=0;
  wire [31:0] t_rdata; wire t_err, t_ack;

  // --- ruteo, de integration_cfg al scope ---
  wire [1:0] r_osc_tap, r_mtrg_tap, r_mca_tap, r_ring_tap;
  wire       r_osc_en,  r_mtrg_en,  r_mca_en,  r_ring_en;

  integration_cfg #(
    .MAGIC(32'h494E5447), .GITH('0),
    .EN_OSC(1), .EN_MTRG(1), .EN_MCA(1), .EN_RING(0),
    .SLOT_OSC(1), .SLOT_RING(2), .SLOT_MTRG(3), .SLOT_TOP(6), .SLOT_MCA(7),
    .N_CH(N_CH), .DW(DW), .RSZ(RSZ), .EN_FILT(0)
  ) i_integration (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .route_osc_tap_o (r_osc_tap ), .route_osc_en_o (r_osc_en ),
    .route_mtrg_tap_o(r_mtrg_tap), .route_mtrg_en_o(r_mtrg_en),
    .route_mca_tap_o (r_mca_tap ), .route_mca_en_o (r_mca_en ),
    .route_ring_tap_o(r_ring_tap), .route_ring_en_o(r_ring_en),
    .ctrl_run_o(), .ctrl_clear_o(), .ctrl_srst_o(),
    .pll_locked_i(1'b1),
    .sys_addr(t_addr), .sys_wdata(t_wdata), .sys_wen(t_wen), .sys_ren(t_ren),
    .sys_rdata(t_rdata), .sys_err(t_err), .sys_ack(t_ack)
  );

  // --- estímulo del ADC ---
  reg [DW-1:0] adc0 = 0, adc1 = 0;
  wire [N_CH*DW-1:0] mca_dat;
  wire [N_CH   -1:0] mca_val;

  rp_scope_multitrigger_com #(
    .CHN(0), .N_CH(N_CH), .DW(DW), .RSZ(RSZ), .EN_FILT(0)
  ) i_scope (
    .adc_clk_i({2{clk}}), .adc_rstn_i({2{rstn}}),
    .adc_dat_i({adc1, adc0}),
    .mca_dat_o(mca_dat), .mca_val_o(mca_val),
    .event_trig_o(), .event_snap_o(),
    .trig_ext_i(1'b0), .trig_ch_o(), .trig_ch_i(4'h0),
    .trig_asg_i(1'b0), .trig_ext_asg_o(), .trig_ext_asg_i(4'h0),
    .daisy_trig_o(),
    .axi_clk_o(), .axi_rstn_o(), .axi_waddr_o(), .axi_wdata_o(),
    .axi_wsel_o(), .axi_wvalid_o(), .axi_wlen_o(), .axi_wfixed_o(),
    .axi_werr_i(2'h0), .axi_wrdy_i(2'h3),
    .adc_state_o(), .adc_state_i(16'h0),
    .axi_state_o(), .axi_state_i(16'h0),
    .trg_state_o(), .trg_state_i(16'h0),
    .route_osc_tap_i (r_osc_tap ), .route_osc_en_i (r_osc_en ),
    .route_mtrg_tap_i(r_mtrg_tap), .route_mtrg_en_i(r_mtrg_en),
    .route_mca_tap_i (r_mca_tap ), .route_mca_en_i (r_mca_en ),
    .sys_osc_addr(o_addr), .sys_osc_wdata(o_wdata), .sys_osc_wen(o_wen),
    .sys_osc_ren(o_ren), .sys_osc_rdata(o_rdata), .sys_osc_err(o_err),
    .sys_osc_ack(o_ack),
    .sys_mtrg_addr(m_addr), .sys_mtrg_wdata(m_wdata), .sys_mtrg_wen(m_wen),
    .sys_mtrg_ren(m_ren), .sys_mtrg_rdata(m_rdata), .sys_mtrg_err(m_err),
    .sys_mtrg_ack(m_ack)
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
  // BFM por bus
  //--------------------------------------------------------------------------
  localparam integer ACK_LIMIT = 20;
  integer ack_timeouts = 0;

  `define BFM(NAME, PFX, SLOT)                                                \
  task automatic NAME``_write(input [19:0] a, input [31:0] d);                \
    integer n;                                                                \
    begin                                                                     \
      @(negedge clk); PFX``_addr = {12'h``SLOT, a}; PFX``_wdata = d;          \
      PFX``_wen = 1'b1; n = 0;                                                \
      while (!PFX``_ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end \
      if (!PFX``_ack) ack_timeouts = ack_timeouts + 1;                        \
      @(negedge clk); PFX``_wen = 1'b0; PFX``_addr = 0;                       \
      while (PFX``_ack) @(negedge clk);                                       \
      @(negedge clk);                                                         \
    end                                                                       \
  endtask                                                                     \
  task automatic NAME``_read(input [19:0] a, output [31:0] d);                \
    integer n;                                                                \
    begin                                                                     \
      @(negedge clk); PFX``_addr = {12'h``SLOT, a}; PFX``_ren = 1'b1; n = 0;  \
      while (!PFX``_ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end \
      if (!PFX``_ack) ack_timeouts = ack_timeouts + 1;                        \
      d = PFX``_rdata;                                                        \
      @(negedge clk); PFX``_ren = 1'b0; PFX``_addr = 0;                       \
      while (PFX``_ack) @(negedge clk);                                       \
      @(negedge clk);                                                         \
    end                                                                       \
  endtask

  `BFM(osc,  o, 401)
  `BFM(mtrg, m, 403)
  `BFM(top,  t, 406)

  reg [31:0] d;
  reg [DW-1:0] seen_crudo, seen_calib;

  initial begin
    $dumpfile("tb_slots_integration.vcd");
    $dumpvars(0, tb_slots_integration);

    repeat (10) @(negedge clk);
    rstn = 1;
    repeat (20) @(negedge clk);

    //----------------------------------------------------------------------
    // 1. TRES REGIONES INDEPENDIENTES
    //----------------------------------------------------------------------
    $display("-- 1. las tres regiones responden por separado --");
    top_read (20'h000, d); checkv("slot 6: MAGIC de TOP",          d, 32'h494E5447);
    mtrg_read(20'h000, d); checkv("slot 3: MAGIC de MULTITRIGGER", d, 32'h4D545247);
    osc_read (20'h1000, d); checkv("slot 1: MAGIC de OSC",         d, 32'h4F534331);

    // El slot 6 dice dónde vive cada módulo
    top_read(20'h024, d); checkv("SLOTS describe el sistema", d, 32'h0007_6321);

    // Escribir en un slot no toca a los otros
    osc_read(20'h008, d);  checkv("umbral ch0 en su valor de reset", d, 32'h0000_1388);
    mtrg_write(20'h040, 32'h0000_00FF);       // OR-mask del multitrigger
    osc_read(20'h008, d);  checkv("el slot 1 no cambio", d, 32'h0000_1388);
    top_read(20'h038, d);  checkv("el slot 6 no cambio", d, {23'h0, 1'b1, 6'h0, TAP_NATIVE});
    mtrg_read(20'h040, d); checkv("y el slot 3 guardo lo suyo", d, 32'h0000_00FF);

    //----------------------------------------------------------------------
    // 2. EL RESET ES EL COMPORTAMIENTO PRE-REFACTOR
    //----------------------------------------------------------------------
    $display("-- 2. en reset, el MCA ve el nodo post-calibracion --");

    // Ganancia de calibracion != 1 para que el nodo crudo y el calibrado
    // den valores distintos y no se puedan confundir.
    // rp_scope_calib: gain 0x8000 = x1. Con 0x4000 la salida es la mitad.
    osc_write(20'h204, 32'h0000_4000);   // calib_gain ch0 = x0.5
    osc_write(20'h200, 32'h0000_0000);   // calib_offset ch0 = 0
    repeat (10) @(negedge clk);

    adc0 = 14'd2000;
    repeat (20) @(negedge clk);
    seen_calib = mca_dat[DW-1:0];
    check("MCA ve la muestra CALIBRADA (~mitad de 2000)",
          (seen_calib > 14'd900) && (seen_calib < 14'd1100));
    check("y su valid esta activo", mca_val[0] === 1'b1);

    //----------------------------------------------------------------------
    // 3. RUTEO DE PUNTA A PUNTA: slot 6 -> dato que ve el MCA
    //----------------------------------------------------------------------
    $display("-- 3. ROUTE_MCA cambia de donde toma el MCA --");

    // TAP_ADC: crudo, ANTES de la calibracion -> tiene que ser 2000, no 1000
    top_write(20'h038, {23'h0, 1'b1, 6'h0, TAP_ADC});
    check("ROUTE_MCA quedo en TAP_ADC", r_mca_tap === TAP_ADC);
    repeat (20) @(negedge clk);
    seen_crudo = mca_dat[DW-1:0];
    checkv("MCA ahora ve la muestra CRUDA", {18'h0, seen_crudo}, 32'd2000);
    check("crudo y calibrado son distintos (la prueba no es vacua)",
          seen_crudo !== seen_calib);

    // TAP_DEC_IN: vuelve al nodo post-calibracion
    top_write(20'h038, {23'h0, 1'b1, 6'h0, TAP_DEC_IN});
    repeat (20) @(negedge clk);
    check("con TAP_DEC_IN vuelve a ver el calibrado",
          mca_dat[DW-1:0] === seen_calib);

    // enable = 0: el dato sigue pero el valid se corta
    top_write(20'h038, {23'h0, 1'b0, 6'h0, TAP_DEC_IN});
    repeat (10) @(negedge clk);
    check("enable=0 corta el valid del MCA", mca_val[0] === 1'b0);

    top_write(20'h038, {23'h0, 1'b1, 6'h0, TAP_NATIVE});
    repeat (10) @(negedge clk);
    check("vuelto a NATIVO, el valid vuelve", mca_val[0] === 1'b1);
    check("y el dato es otra vez el calibrado", mca_dat[DW-1:0] === seen_calib);

    //----------------------------------------------------------------------
    // 4. Ningun slot cuelga el bus
    //----------------------------------------------------------------------
    $display("-- 4. contrato de bus en los tres slots --");
    begin
      integer i;
      for (i = 0; i < 20'h120; i = i + 4) begin
        osc_read (i[19:0], d);
        mtrg_read(i[19:0], d);
        top_read (i[19:0], d);
      end
      // aperturas BRAM del OSC, incluidos los canales no construidos
      osc_read(20'h10000, d); osc_read(20'h30000, d); osc_read(20'h40000, d);
    end
    checkv("sin timeouts de ack en ningun slot", ack_timeouts, 0);

    $display("tb_slots_integration: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end

endmodule
