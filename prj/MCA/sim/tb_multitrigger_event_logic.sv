`timescale 1ns/1ps
//============================================================================
// tb_multitrigger_event_logic — integracion. Verifica:
//   - trigger_event_o = OR de las salidas de trigger de los N_CH canales
//   - el snapshot engancha la fuente que disparo (adc_p0 -> bit 1)
//   - el snapshot se resetea con sw_trig_dis_clr
//   - un flanco en ch1 tambien dispara el evento conjunto
//============================================================================
module tb_multitrigger_event_logic;

  localparam integer N_CH = 2;

  reg clk=0, rstn=0;
  always #5 clk = ~clk;

  reg  [3:0]         rst_do=0, sw_clr=0, we_keep=0, set_new=0, trig_sw=0, trig_p=0, trig_n=0, trig_ch=0;
  reg                dly_do=0, ext_p=0, ext_n=0, asg_p=0, asg_n=0;
  reg  [3:0]         dly_valp=4'hF;
  reg  [N_CH*32-1:0] set_src=0;
  reg  [3:0]         sh_src=0, sh_dst=0;
  reg  [15:0]        sh_dur=0;

  wire [3:0]         trig_ch_o;
  wire [N_CH*32-1:0] trg_state;
  wire [3:0]         dis;
  wire               daisy, arm, trigger_event;
  wire [15:0]        sh_cnt;
  wire               sh_active;
  wire [16:0]        snapshot;

  multitrigger_event_logic #(.N_CH(N_CH)) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .adc_rst_do_i(rst_do), .adc_dly_do_i(dly_do),
    .sw_trig_dis_clr_i(sw_clr), .adc_we_keep_i(we_keep),
    .set_trg_src_i(set_src), .set_trg_new_i(set_new), .dly_valp_i(dly_valp),
    .adc_trig_sw_i(trig_sw), .adc_trig_p_i(trig_p), .adc_trig_n_i(trig_n),
    .ext_trig_p_i(ext_p), .ext_trig_n_i(ext_n), .asg_trig_p_i(asg_p), .asg_trig_n_i(asg_n),
    .trig_ch_i(trig_ch),
    .shield_src_i(sh_src), .shield_dst_i(sh_dst), .shield_dur_i(sh_dur),
    .trig_ch_o(trig_ch_o), .trg_state_o(trg_state), .adc_trg_dis_o(dis),
    .daisy_trig_o(daisy), .event_arm_o(arm), .trigger_event_o(trigger_event),
    .shield_cnt_o(sh_cnt), .shield_active_o(sh_active), .trig_snapshot_o(snapshot)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) begin pass_cnt=pass_cnt+1; $display("  PASS: %s", name); end
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  [ev=%b snap=0x%05x]", name, trigger_event, snapshot); end
    end
  endtask

  reg seen_event=0;
  always @(posedge clk) if (rstn && trigger_event) seen_event<=1'b1;

  task automatic reset_dut;
    begin
      @(negedge clk); rstn=0; rst_do=4'hF; sw_clr=4'hF; set_src=0; set_new=0;
      trig_p=0; trig_sw=0; we_keep=0; dly_do=0; seen_event=0;
      repeat(3) @(negedge clk); rstn=1; @(negedge clk); rst_do=0; sw_clr=0; @(negedge clk);
    end
  endtask

  task automatic load_mask(input [31:0] m0, input [31:0] m1);
    begin @(negedge clk); set_src={m1,m0}; set_new=4'hF; @(negedge clk); set_new=0; end
  endtask

  initial begin
    $dumpfile("tb_multitrigger_event_logic.vcd"); $dumpvars(0, tb_multitrigger_event_logic);
    $display("=== tb_multitrigger_event_logic ===");

    // 1) flanco ch0 -> evento conjunto + snapshot bit1 (adc_p0)
    reset_dut;
    load_mask(32'h2, 32'h2);  // BIT_ADC_P0 en ambos canales
    seen_event=0;
    @(negedge clk); trig_p=4'b0001; @(negedge clk); trig_p=0;
    repeat(2) @(negedge clk);
    check("flanco ch0 dispara trigger_event", seen_event==1'b1);
    check("snapshot engancha adc_p0 (bit1)", snapshot[1]==1'b1);

    // 2) snapshot se resetea con sw_trig_dis_clr
    @(negedge clk); sw_clr=4'hF; @(negedge clk); sw_clr=0; @(negedge clk);
    check("sw_trig_dis_clr resetea el snapshot", snapshot==17'h0);

    // 3) flanco en ch1 (adc_trig_p bit1) tambien dispara el evento conjunto
    reset_dut;
    load_mask(32'h8, 32'h8);  // BIT_ADC_P1 (bit3) en ambos canales
    seen_event=0;
    @(negedge clk); trig_p=4'b0010; @(negedge clk); trig_p=0;  // adc_trig_p[1]
    repeat(2) @(negedge clk);
    check("flanco adc ch1 dispara trigger_event (OR conjunto)", seen_event==1'b1);
    check("snapshot engancha adc_p1 (bit2)", snapshot[2]==1'b1);

    $display("---------------------------------------------");
    $display("tb_multitrigger_event_logic: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #50000; $display("TIMEOUT"); $finish; end

endmodule
