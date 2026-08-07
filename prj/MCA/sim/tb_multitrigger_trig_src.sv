`timescale 1ns/1ps
//============================================================================
// tb_multitrigger_trig_src — unidad. Verifica:
//   - un flanco de ADC habilitado en la mascara dispara adc_trig (1 ciclo)
//   - adc_trg_dis se engancha tras el disparo y se limpia con trig_dis_clr
//   - single-shot (we_keep=0): set_trig_src (trg_state) se auto-limpia al disparar
//   - modo continuo (we_keep=1): la mascara persiste tras el disparo
//   - una fuente NO habilitada en la mascara no dispara
//   - SW trigger gateado por dly_valp
//============================================================================
module tb_multitrigger_trig_src;

  localparam integer SRC_W = 32;

  // bits de la mascara (matchean multitrigger_utils.py)
  localparam [31:0] BIT_SW     = 32'h1 << 0;
  localparam [31:0] BIT_ADC_P0 = 32'h1 << 1;
  localparam [31:0] BIT_ADC_P1 = 32'h1 << 3;

  reg clk = 0, rstn = 0;
  always #5 clk = ~clk;

  reg              rst_do=0, dly_do=0, dis_clr=0, we_keep=0;
  reg  [SRC_W-1:0] set_src=0;
  reg              set_new=0, dly_valp=1'b1;
  reg              trig_sw=0;
  reg  [3:0]       trig_p=0, trig_n=0, trig_ch=0;
  reg              ext_p=0, ext_n=0, asg_p=0, asg_n=0;

  wire [SRC_W-1:0] trg_state;
  wire             adc_trg_dis, adc_trig;

  multitrigger_trig_src #(.CHN(0), .SRC_W(SRC_W)) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .adc_rst_do_i(rst_do), .adc_dly_do_i(dly_do),
    .trig_dis_clr_i(dis_clr), .adc_we_keep_i(we_keep),
    .set_trg_src_i(set_src), .set_trg_new_i(set_new), .dly_valp_i(dly_valp),
    .adc_trig_sw_i(trig_sw),
    .adc_trig_p_i(trig_p), .adc_trig_n_i(trig_n),
    .ext_trig_p_i(ext_p), .ext_trig_n_i(ext_n),
    .asg_trig_p_i(asg_p), .asg_trig_n_i(asg_n),
    .trig_ch_i(trig_ch),
    .trg_state_o(trg_state), .adc_trg_dis_o(adc_trg_dis), .adc_trig_o(adc_trig)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) begin pass_cnt=pass_cnt+1; $display("  PASS: %s", name); end
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  [adc_trig=%b dis=%b trg_state=0x%08x]",
                 name, adc_trig, adc_trg_dis, trg_state); end
    end
  endtask

  task automatic reset_dut;
    begin
      @(negedge clk); rstn=0; rst_do=0; dis_clr=0; we_keep=0; set_src=0; set_new=0;
      trig_sw=0; trig_p=0; dly_do=0;
      repeat(3) @(negedge clk); rstn=1; @(negedge clk);
    end
  endtask

  task automatic load_mask(input [SRC_W-1:0] m);
    begin @(negedge clk); set_src=m; set_new=1; @(negedge clk); set_new=0; end
  endtask

  task automatic pulse_p0;  // flanco posedge ADC ch0
    begin @(negedge clk); trig_p=4'b0001; @(negedge clk); trig_p=0; end
  endtask

  initial begin
    $dumpfile("tb_multitrigger_trig_src.vcd"); $dumpvars(0, tb_multitrigger_trig_src);
    $display("=== tb_multitrigger_trig_src ===");

    // 1) flanco habilitado dispara adc_trig, engancha dis, single-shot limpia mascara
    reset_dut; we_keep=0;
    load_mask(BIT_ADC_P0);
    check("mascara cargada (trg_state==BIT_ADC_P0)", trg_state==BIT_ADC_P0);
    pulse_p0;   // tras esto, un posedge ya paso -> adc_trig deberia estar en 1
    check("flanco ADC_P0 dispara adc_trig", adc_trig==1'b1);
    @(negedge clk);  // un ciclo mas: dis enganchado, mascara auto-limpiada
    check("adc_trg_dis enganchado tras disparo", adc_trg_dis==1'b1);
    check("single-shot: trg_state auto-limpiada", trg_state==32'h0);

    // 2) trig_dis_clr limpia el disable
    @(negedge clk); dis_clr=1; @(negedge clk); dis_clr=0; @(negedge clk);
    check("trig_dis_clr limpia adc_trg_dis", adc_trg_dis==1'b0);

    // 3) fuente NO habilitada no dispara (mascara solo P1, pulso en P0)
    reset_dut; we_keep=0;
    load_mask(BIT_ADC_P1);
    pulse_p0;
    check("fuente fuera de mascara NO dispara", adc_trig==1'b0);

    // 4) modo continuo: la mascara persiste tras el disparo
    reset_dut; we_keep=1;
    load_mask(BIT_ADC_P0);
    pulse_p0;
    @(negedge clk);
    check("we_keep=1: mascara persiste tras disparo", trg_state==BIT_ADC_P0);

    // 5) SW trigger gateado por dly_valp
    reset_dut; we_keep=0; dly_valp=1'b1;
    load_mask(BIT_SW);
    @(negedge clk); trig_sw=1; @(negedge clk); trig_sw=0;  // pulso SW
    @(negedge clk);
    check("SW trigger dispara adc_trig", adc_trig==1'b1);

    $display("---------------------------------------------");
    $display("tb_multitrigger_trig_src: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #50000; $display("TIMEOUT"); $finish; end

endmodule
