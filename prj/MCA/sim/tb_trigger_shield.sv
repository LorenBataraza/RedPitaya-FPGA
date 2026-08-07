`timescale 1ns/1ps
//============================================================================
// tb_trigger_shield — unidad. Verifica el holdoff src->dst:
//   - dur=0  : re-arm inmediato (pulso de clear en dst al disparar src)
//   - dur=K  : active durante el holdoff, y pulso de clear en dst al expirar
//   - canal NO escudado: transparente al clear de SW
//============================================================================
module tb_trigger_shield;

  localparam integer N = 4, DUR_W = 16;

  reg              clk=0, rstn=0;
  always #5 clk = ~clk;

  reg  [N-1:0]     trig_event=0, shield_src=0, shield_dst=0, sw_clr=0;
  reg  [DUR_W-1:0] shield_dur=0;
  wire [N-1:0]     trig_dis_clr;
  wire [DUR_W-1:0] cnt;
  wire             active;

  trigger_shield #(.N(N), .DURATION_W(DUR_W)) dut (
    .clk_i(clk), .rstn_i(rstn),
    .trig_event_i(trig_event),
    .shield_src_i(shield_src), .shield_dst_i(shield_dst), .shield_dur_i(shield_dur),
    .sw_trig_dis_clr_i(sw_clr),
    .trig_dis_clr_o(trig_dis_clr), .cnt_o(cnt), .active_o(active)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) begin pass_cnt=pass_cnt+1; $display("  PASS: %s", name); end
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  [clr=0x%1x active=%b cnt=%0d]", name, trig_dis_clr, active, cnt); end
    end
  endtask

  // flag: vio un pulso de clear en el canal 1 (dst)
  reg seen_clr_dst=0;
  always @(posedge clk) if (rstn && trig_dis_clr[1]) seen_clr_dst <= 1'b1;

  task automatic reset_dut;
    begin
      @(negedge clk); rstn=0; trig_event=0; shield_src=0; shield_dst=0; sw_clr=0; shield_dur=0;
      seen_clr_dst=0;
      repeat(3) @(negedge clk); rstn=1; @(negedge clk);
    end
  endtask

  task automatic fire_src0;  // dispara el canal 0 (source)
    begin @(negedge clk); trig_event=4'b0001; @(negedge clk); trig_event=4'b0000; end
  endtask

  initial begin
    $dumpfile("tb_trigger_shield.vcd"); $dumpvars(0, tb_trigger_shield);
    $display("=== tb_trigger_shield ===");

    // 1) dur=0: re-arm inmediato en dst, sin holdoff
    reset_dut;
    shield_src=4'b0001; shield_dst=4'b0010; shield_dur=16'd0;
    seen_clr_dst=0;
    fire_src0;
    @(negedge clk);
    check("dur=0: pulso de clear en dst tras disparo src", seen_clr_dst==1'b1);
    check("dur=0: active se mantiene en 0", active==1'b0);

    // 2) dur=K: active durante el holdoff y clear en dst al expirar
    reset_dut;
    shield_src=4'b0001; shield_dst=4'b0010; shield_dur=16'd5;
    seen_clr_dst=0;
    fire_src0;
    check("dur=5: active se activa durante el holdoff", active==1'b1);
    repeat(10) @(negedge clk);
    check("dur=5: clear en dst al expirar el holdoff", seen_clr_dst==1'b1);
    check("dur=5: active vuelve a 0 tras expirar", active==1'b0);

    // 3) canal no escudado: transparente al clear de SW
    reset_dut;
    shield_src=4'b0001; shield_dst=4'b0010;  // ch0 no es dst
    @(negedge clk); sw_clr=4'b0001;          // clear de SW en ch0
    @(negedge clk);
    check("canal no escudado pasa el clear de SW", trig_dis_clr[0]==1'b1);
    check("canal escudado NO pasa el clear de SW (sin holdoff activo)", trig_dis_clr[1]==1'b0);

    $display("---------------------------------------------");
    $display("tb_trigger_shield: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #50000; $display("TIMEOUT"); $finish; end

endmodule
