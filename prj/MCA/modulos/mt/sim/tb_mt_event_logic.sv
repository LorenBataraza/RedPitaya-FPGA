`timescale 1ns/1ps
//============================================================================
// tb_mt_event_logic — integracion. Verifica:
//   - trigger_event_o = OR de las salidas de trigger de los N_CH canales
//   - el snapshot engancha la fuente que disparo (adc_p0 -> bit 1)
//   - el snapshot se resetea con sw_trig_dis_clr
//   - un flanco en ch1 tambien dispara el evento conjunto
//   - una fuente de pendiente queda en el snapshot en el mismo bit que en la
//     mascara (slope_p0 -> bit 17)
//   - un SW de 6 ciclos, lo que dura en el bus, con auto-rearme inmediato da un
//     solo evento, con el trigger_shield de verdad
//   - el snapshot ya vale en el ciclo del evento, que es cuando lo lee el ring
//============================================================================
module tb_mt_event_logic;

  localparam integer N_CH = 2;

  reg clk=0, rstn=0;
  always #5 clk = ~clk;

  reg  [3:0]         rst_do=0, sw_clr=0, we_keep=0, set_new=0, trig_sw=0, trig_p=0, trig_n=0, trig_ch=0;
  reg                dly_do=0, ext_p=0, ext_n=0, asg_p=0, asg_n=0;
  reg  [3:0]         dly_valp=4'hF;
  reg  [3:0]         slope_p=0, slope_n=0, pz_p=0;
  reg  [3:0]         slope_arm_p=4'hF, slope_arm_n=4'hF, pz_arm=4'hF;   // Schmitt armados
  reg  [N_CH*32-1:0] set_src=0;
  reg  [6:0]         sh_src=0;
  reg  [4:0]         sh_dst=0;
  reg  [15:0]        sh_dur=0;

  wire [3:0]         trig_ch_o;
  wire [N_CH*32-1:0] trg_state;
  wire [3:0]         dis;
  wire               daisy, arm, trigger_event;
  wire [15:0]        sh_cnt;
  wire               sh_active;
  wire               trig_arm, veto;
  wire [28:0]        snapshot;

  mt_event_logic #(.N_CH(N_CH)) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .adc_rst_do_i(rst_do), .adc_dly_do_i(dly_do),
    .sw_trig_dis_clr_i(sw_clr), .adc_we_keep_i(we_keep),
    .set_trg_src_i(set_src), .set_trg_new_i(set_new), .dly_valp_i(dly_valp),
    .adc_trig_sw_i(trig_sw), .adc_trig_p_i(trig_p), .adc_trig_n_i(trig_n),
    .ext_trig_p_i(ext_p), .ext_trig_n_i(ext_n), .asg_trig_p_i(asg_p), .asg_trig_n_i(asg_n),
    .ext_lvl_i(1'b0),
    .trig_ch_i(trig_ch),
    .slope_p_i(slope_p), .slope_n_i(slope_n), .pz_p_i(pz_p),
    .slope_arm_p_i(slope_arm_p), .slope_arm_n_i(slope_arm_n), .pz_arm_i(pz_arm),
    .shield_src_i(sh_src), .shield_dst_i(sh_dst), .shield_dur_i(sh_dur),
    .trig_ch_o(trig_ch_o), .trg_state_o(trg_state), .adc_trg_dis_o(dis),
    .daisy_trig_o(daisy), .event_arm_o(arm), .trigger_event_o(trigger_event),
    .mca_veto_o(veto), .trig_arm_o(trig_arm),
    .shield_cnt_o(sh_cnt), .shield_active_o(sh_active), .trig_snapshot_o(snapshot)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) begin pass_cnt=pass_cnt+1; $display("  PASS: %s", name); end
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  [ev=%b snap=0x%07x]", name, trigger_event, snapshot); end
    end
  endtask

  reg seen_event=0;
  always @(posedge clk) if (rstn && trigger_event) seen_event<=1'b1;

  // Como lo ve event_window_capture: por flanco, y el snapshot en ese mismo flanco.
  reg        ev_d=0;
  integer    ev_flancos=0;
  reg [28:0] snap_en_flanco=0;
  always @(posedge clk) begin
    ev_d <= trigger_event;
    if (rstn && trigger_event && !ev_d) begin
      ev_flancos = ev_flancos + 1;
      snap_en_flanco <= snapshot;
    end
  end

  // Ciclos con el disparo desarmado, como los cuenta t_rearm en el MCA.
  reg     contar_desarme = 0;
  integer ciclos_desarme = 0;
  always @(posedge clk) if (contar_desarme && !trig_arm) ciclos_desarme = ciclos_desarme + 1;

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
    $dumpfile("tb_mt_event_logic.vcd"); $dumpvars(0, tb_mt_event_logic);
    $display("=== tb_mt_event_logic ===");

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
    check("sw_trig_dis_clr resetea el snapshot", snapshot==29'h0);

    // 3) flanco en ch1 (adc_trig_p bit1) tambien dispara el evento conjunto
    reset_dut;
    load_mask(32'h8, 32'h8);  // BIT_ADC_P1 (bit3) en ambos canales
    seen_event=0;
    @(negedge clk); trig_p=4'b0010; @(negedge clk); trig_p=0;  // adc_trig_p[1]
    repeat(2) @(negedge clk);
    check("flanco adc ch1 dispara trigger_event (OR conjunto)", seen_event==1'b1);
    check("snapshot engancha adc_p1 (bit2)", snapshot[2]==1'b1);

    // 4) pendiente: slope_p[0] con BIT_SLOPE_P0 -> evento + snapshot bit 17
    reset_dut;
    load_mask(32'h1 << 17, 32'h1 << 17);
    seen_event=0;
    @(negedge clk); slope_p=4'b0001; @(negedge clk); slope_p=0;
    repeat(2) @(negedge clk);
    check("slope_p0 dispara trigger_event", seen_event==1'b1);
    check("snapshot engancha slope_p0 (bit17) y nada mas", snapshot==(29'h1 << 17));

    // 5) slope_n[1] (bit 22)
    reset_dut;
    load_mask(32'h1 << 22, 32'h1 << 22);
    seen_event=0;
    @(negedge clk); slope_n=4'b0010; @(negedge clk); slope_n=0;
    repeat(2) @(negedge clk);
    check("slope_n1 dispara trigger_event", seen_event==1'b1);
    check("snapshot engancha slope_n1 (bit22)", snapshot==(29'h1 << 22));

    // 6) polo-cero: pz_p[1] (bit 26) -> evento + snapshot bit 26
    reset_dut;
    load_mask(32'h1 << 26, 32'h1 << 26);
    seen_event=0;
    @(negedge clk); pz_p=4'b0010; @(negedge clk); pz_p=0;
    repeat(2) @(negedge clk);
    check("pz_p1 dispara trigger_event", seen_event==1'b1);
    check("snapshot engancha pz_p1 (bit26) y nada mas", snapshot==(29'h1 << 26));

    // 7) SW de 6 ciclos con auto-rearme: una escritura, un evento
    reset_dut;
    we_keep=4'hF; sh_src=7'h3; sh_dst=5'h3; sh_dur=0;
    load_mask(32'h1, 32'h0);
    for (int vuelta = 1; vuelta <= 3; vuelta++) begin
      ev_flancos=0;
      @(negedge clk); trig_sw=4'h1; repeat(6) @(negedge clk); trig_sw=0;
      repeat(8) @(negedge clk);
      check($sformatf("SW de 6 ciclos con auto-rearme, escritura %0d: un evento", vuelta),
            ev_flancos==1);
    end

    // 8) dos fuentes alternadas: cada evento lee la suya en el ciclo del disparo
    reset_dut;
    we_keep=4'hF; sh_src=7'h3; sh_dst=5'h3; sh_dur=0;
    load_mask((32'h1 << 1) | (32'h1 << 2), 32'h0);   // BIT_ADC_P0 y BIT_ADC_N0
    for (int vuelta = 0; vuelta < 3; vuelta++) begin
      @(negedge clk); trig_p=4'b0001; @(negedge clk); trig_p=0;
      repeat(6) @(negedge clk);
      check($sformatf("snapshot en el flanco, vuelta %0d: adc_p0 (bit1)", vuelta),
            snap_en_flanco==(29'h1 << 1));
      @(negedge clk); trig_n=4'b0001; @(negedge clk); trig_n=0;
      repeat(6) @(negedge clk);
      check($sformatf("snapshot en el flanco, vuelta %0d: adc_n0 (bit5)", vuelta),
            snap_en_flanco==(29'h1 << 5));
    end
    sh_src=0; sh_dst=0;

    // 9) trig_arm: el disparo puede salir. Modo del MCA (multitrigger_armar_mca):
    //    continuo, escudo src = dst = ch0 con dur = 0, y en la mascara de ch0 el
    //    polo-cero de ch0 (bit 25).
    reset_dut;
    we_keep=4'hF; sh_src=7'h1; sh_dst=5'h1; sh_dur=0;
    pz_arm=4'hF; slope_arm_p=4'hF; slope_arm_n=4'hF;
    @(negedge clk); @(negedge clk);
    check("trig_arm: mascaras vacias, no puede disparar", trig_arm==1'b0);
    load_mask(32'h1 << 25, 32'h0);
    @(negedge clk);
    check("trig_arm: polo-cero de ch0 armado", trig_arm==1'b1);
    pz_arm[1] = 1'b0;
    repeat(2) @(negedge clk);
    check("trig_arm: el polo-cero de ch1 no esta en la mascara, no cuenta", trig_arm==1'b1);
    pz_arm[1] = 1'b1;

    // un disparo como lo da mt_pz_trig: el Schmitt se desarma en t, el pulso
    // sale en t+1, y re-arma 10 ciclos despues. El disable del escudo (un
    // ciclo, en t+3) cae adentro: son 10 ciclos desarmado, ni uno mas.
    ciclos_desarme = 0; contar_desarme = 1; ev_flancos = 0;
    @(negedge clk); pz_arm[0] = 1'b0;
    @(negedge clk); pz_p[0] = 1'b1;
    @(negedge clk); pz_p[0] = 1'b0;
    repeat(8) @(negedge clk);
    pz_arm[0] = 1'b1;
    repeat(6) @(negedge clk);
    contar_desarme = 0;
    check("trig_arm: el disparo sale (un evento)", ev_flancos==1);
    check($sformatf("trig_arm: 10 ciclos desarmado por el re-armado del Schmitt (%0d)", ciclos_desarme),
          ciclos_desarme==10);

    // re-armado instantaneo: lo que queda es el disable del escudo, un ciclo
    ciclos_desarme = 0; contar_desarme = 1; ev_flancos = 0;
    @(negedge clk); pz_p[0] = 1'b1;
    @(negedge clk); pz_p[0] = 1'b0;
    repeat(8) @(negedge clk);
    contar_desarme = 0;
    check("trig_arm: sin Schmitt desarmado, un evento", ev_flancos==1);
    check($sformatf("trig_arm: solo el ciclo del disable del escudo (%0d)", ciclos_desarme),
          ciclos_desarme==1);

    // una fuente sin re-armado (SW) en la mascara: siempre puede
    load_mask((32'h1 << 25) | 32'h1, 32'h0);
    pz_arm[0] = 1'b0;
    repeat(2) @(negedge clk);
    check("trig_arm: con SW en la mascara puede aunque el polo-cero no", trig_arm==1'b1);
    pz_arm[0] = 1'b1;

    // pendiente negativa de ch1 en la mascara de ch1
    load_mask(32'h0, 32'h1 << 22);
    repeat(2) @(negedge clk);
    check("trig_arm: pendiente n de ch1 armada", trig_arm==1'b1);
    slope_arm_n[1] = 1'b0;
    repeat(2) @(negedge clk);
    check("trig_arm: pendiente n de ch1 desarmada", trig_arm==1'b0);
    slope_arm_n[1] = 1'b1;
    sh_src=0; sh_dst=0;

    $display("---------------------------------------------");
    $display("tb_mt_event_logic: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #50000; $display("TIMEOUT"); $finish; end

endmodule
