`timescale 1ns/1ps
//============================================================================
// tb_trigger_shield — unidad. Verifica el holdoff src->dst:
//   - dur=0  : re-arm inmediato (pulso de clear en dst al disparar src)
//   - dur=K  : active durante el holdoff, y pulso de clear en dst al expirar
//   - canal NO escudado: transparente al clear de SW
//   - VETO al MCA (dst[N]): con fuente de nivel (src[N+2]) y dur=0 es el
//     nivel; con dur=K se extiende K ciclos; con fuente de flanco (src[N]) es
//     una ventana de K ciclos; y sin dst[N] no hay veto aunque el escudo corra
//============================================================================
module tb_trigger_shield;

  localparam integer N = 4, DUR_W = 16, N_SRC = N + 3, N_DST = N + 1;
  localparam integer SRC_EXT_P = N, SRC_EXT_N = N + 1, SRC_EXT_LVL = N + 2, DST_MCA = N;

  reg              clk=0, rstn=0;
  always #5 clk = ~clk;

  reg  [N_SRC-1:0] trig_event=0, shield_src=0;
  reg  [N_DST-1:0] shield_dst=0;
  reg  [N-1:0]     sw_clr=0;
  reg  [DUR_W-1:0] shield_dur=0;
  wire [N-1:0]     trig_dis_clr;
  wire [DUR_W-1:0] cnt;
  wire             active, mca_veto;

  trigger_shield #(.N(N), .DURATION_W(DUR_W)) dut (
    .clk_i(clk), .rstn_i(rstn),
    .trig_event_i(trig_event),
    .shield_src_i(shield_src), .shield_dst_i(shield_dst), .shield_dur_i(shield_dur),
    .sw_trig_dis_clr_i(sw_clr),
    .trig_dis_clr_o(trig_dis_clr), .mca_veto_o(mca_veto),
    .cnt_o(cnt), .active_o(active)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) begin pass_cnt=pass_cnt+1; $display("  PASS: %s", name); end
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  [clr=0x%1x active=%b cnt=%0d veto=%b]", name, trig_dis_clr, active, cnt, mca_veto); end
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
    begin @(negedge clk); trig_event=0; trig_event[0]=1'b1; @(negedge clk); trig_event=0; end
  endtask

  // cuenta ciclos con veto=1 en los proximos `tope` ciclos
  integer n_veto;
  task automatic contar_veto(input integer tope);
    begin
      n_veto = 0;
      repeat (tope) begin @(negedge clk); if (mca_veto) n_veto = n_veto + 1; end
    end
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

    // 4) VETO de nivel: src=ext_lvl, dst=mca, dur=0 -> el veto ES el nivel
    //    (con la latencia de un flop), y cae cuando cae la linea.
    reset_dut;
    shield_src=0; shield_src[SRC_EXT_LVL]=1'b1;
    shield_dst=0; shield_dst[DST_MCA]=1'b1; shield_dur=16'd0;
    @(negedge clk); trig_event=0; trig_event[SRC_EXT_LVL]=1'b1;   // linea alta
    @(negedge clk);
    check("veto nivel: sube con la linea", mca_veto==1'b1);
    check("veto nivel: NO usa el holdoff (active=0 con dur=0)", active==1'b0);
    repeat(20) @(negedge clk);
    check("veto nivel: sigue mientras la linea esta alta", mca_veto==1'b1);
    trig_event=0;                                                   // linea baja
    @(negedge clk); @(negedge clk);
    check("veto nivel: cae con la linea", mca_veto==1'b0);
    check("veto nivel: no toca los canales del scope", trig_dis_clr==4'h0);

    // 5) VETO de nivel con cola: dur=8 -> sigue 8 ciclos despues de bajar
    reset_dut;
    shield_src=0; shield_src[SRC_EXT_LVL]=1'b1;
    shield_dst=0; shield_dst[DST_MCA]=1'b1; shield_dur=16'd8;
    @(negedge clk); trig_event=0; trig_event[SRC_EXT_LVL]=1'b1;
    repeat(5) @(negedge clk);
    trig_event=0;
    contar_veto(30);
    // 1 ciclo de latencia del flop + 8 de holdoff, +-1 por el borde
    check("veto con cola: ~8 ciclos tras bajar la linea", n_veto>=8 && n_veto<=10);
    check("veto con cola: termina", mca_veto==1'b0);

    // 6) VETO de ventana: src=ext_p (flanco), dur=12 -> 12 ciclos y listo
    reset_dut;
    shield_src=0; shield_src[SRC_EXT_P]=1'b1;
    shield_dst=0; shield_dst[DST_MCA]=1'b1; shield_dur=16'd12;
    @(negedge clk); trig_event=0; trig_event[SRC_EXT_P]=1'b1;
    @(negedge clk); trig_event=0;                                   // un pulso
    contar_veto(40);
    check("veto ventana: ~12 ciclos tras el flanco", n_veto>=12 && n_veto<=14);
    check("veto ventana: termina", mca_veto==1'b0);

    // 7) sin dst=mca no hay veto, aunque el escudo corra
    reset_dut;
    shield_src=0; shield_src[SRC_EXT_LVL]=1'b1;
    shield_dst=0; shield_dst[1]=1'b1; shield_dur=16'd8;             // dst = ch1, no mca
    @(negedge clk); trig_event=0; trig_event[SRC_EXT_LVL]=1'b1;
    repeat(5) @(negedge clk);
    check("sin dst=mca: el escudo corre", active==1'b1);
    check("sin dst=mca: pero no hay veto", mca_veto==1'b0);
    trig_event=0;

    // 8) los canales del scope como fuente tambien vetan (dst=mca, src=ch0)
    reset_dut;
    shield_src=0; shield_src[0]=1'b1;
    shield_dst=0; shield_dst[DST_MCA]=1'b1; shield_dur=16'd6;
    fire_src0;
    contar_veto(30);
    check("src=ch0, dst=mca: veto de ~6 ciclos", n_veto>=6 && n_veto<=8);

    $display("---------------------------------------------");
    $display("tb_trigger_shield: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #50000; $display("TIMEOUT"); $finish; end

endmodule
