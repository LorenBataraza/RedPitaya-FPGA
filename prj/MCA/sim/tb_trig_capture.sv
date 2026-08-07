`timescale 1ns/1ps
//============================================================================
// tb_trig_capture — reproduce el race arm-vs-mascara y valida el fix.
//
// Cablea multitrigger_event_logic + rp_bram_sm igual que en
// rp_scope_multitrigger_com:
//    event_logic.trigger_event_o -> bram_sm.adc_trig_i
//    bram_sm.adc_dly_do_o        -> event_logic.adc_dly_do_i   (realimentacion)
//
// El bug: la logica de trigger (multitrigger_trig_src, dentro del event_logic)
// reacciona a los flancos apenas se carga la OR-mask (set_trg_src) — NO espera
// a que la bram_sm este armada (adc_arm_do). En single-shot, al disparar
// auto-limpia set_trig_src y engancha adc_trg_dis. Si un flanco entra ANTES del
// arm, gasta la mascara y la bram_sm queda armada esperando un trigger imposible
// (adc_wp_trig=0, adc_trg_rd=0).
//
// Escenarios:
//   A  mascara-antes-de-arm + flanco pre-arm  -> DEADLOCK   (documenta el bug)
//   B  arm-antes-de-mascara                    -> captura    (valida el fix)
//   C  SW trigger (mascara-antes-de-arm)       -> captura    (SW inmune)
//============================================================================
module tb_trig_capture;

  localparam integer N_CH = 2;
  localparam integer RSZ  = 14;

  reg clk = 1'b0;
  reg rstn = 1'b0;
  always #5 clk = ~clk;   // 100 MHz

  // ---- control del event_logic (lo que en HW escribe el rp_scope_cfg) ----
  reg  [3:0]         el_rst_do   = 4'h0;
  reg  [3:0]         el_sw_clr   = 4'h0;
  reg  [3:0]         el_we_keep  = 4'h0;
  reg  [N_CH*32-1:0] el_set_src  = '0;
  reg  [3:0]         el_set_new  = 4'h0;
  reg  [3:0]         el_dly_valp = 4'hF;   // decim=1 -> muestra valida siempre
  reg  [3:0]         el_trig_sw  = 4'h0;
  reg  [3:0]         el_trig_p   = 4'h0;
  reg  [3:0]         el_trig_n   = 4'h0;
  reg                el_ext_p=0, el_ext_n=0, el_asg_p=0, el_asg_n=0;
  reg  [3:0]         el_trig_ch  = 4'h0;
  reg  [3:0]         sh_src = 4'h0, sh_dst = 4'h0;
  reg  [15:0]        sh_dur = 16'h0;

  wire [3:0]         el_trig_ch_o;
  wire [N_CH*32-1:0] el_trg_state;
  wire [3:0]         el_dis;
  wire               el_daisy, el_arm, trigger_event;
  wire [15:0]        sh_cnt;
  wire               sh_active;
  wire [16:0]        snapshot;

  // ---- control de la bram_sm ----
  reg  [31:0] bs_set_dly = 32'd20;   // delay chico para congelar rapido en sim
  reg         bs_set_dec1 = 1'b1;
  reg         bs_rst_do   = 1'b0;
  reg         bs_we_keep  = 1'b0;
  reg         bs_arm      = 1'b0;
  reg         bs_dv       = 1'b1;    // decim=1 -> dato valido cada ciclo
  reg         bs_indep    = 1'b0;
  reg         bs_trig_dis_clr = 1'b0;

  wire [RSZ-1:0] bs_wp, bs_wp_cur, bs_wp_trig;
  wire [31:0]    bs_we_cnt;
  wire [7:0]     bs_state;
  wire           bs_dly_do, bs_we;

  wire adc_trg_rd = bs_state[2];     // rp_bram_sm: adc_state_o[2] = adc_trg_rd

  //--------------------------------------------------------------------------
  // DUTs cableados como en rp_scope_multitrigger_com
  //--------------------------------------------------------------------------
  multitrigger_event_logic #(.N_CH(N_CH)) i_el (
    .adc_clk_i        (clk),
    .adc_rstn_i       (rstn),
    .adc_rst_do_i     (el_rst_do),
    .adc_dly_do_i     (bs_dly_do),      // realimentacion desde la bram_sm
    .sw_trig_dis_clr_i(el_sw_clr),
    .adc_we_keep_i    (el_we_keep),
    .set_trg_src_i    (el_set_src),
    .set_trg_new_i    (el_set_new),
    .dly_valp_i       (el_dly_valp),
    .adc_trig_sw_i    (el_trig_sw),
    .adc_trig_p_i     (el_trig_p),
    .adc_trig_n_i     (el_trig_n),
    .ext_trig_p_i     (el_ext_p),
    .ext_trig_n_i     (el_ext_n),
    .asg_trig_p_i     (el_asg_p),
    .asg_trig_n_i     (el_asg_n),
    .trig_ch_i        (el_trig_ch),
    .shield_src_i     (sh_src),
    .shield_dst_i     (sh_dst),
    .shield_dur_i     (sh_dur),
    .trig_ch_o        (el_trig_ch_o),
    .trg_state_o      (el_trg_state),
    .adc_trg_dis_o    (el_dis),
    .daisy_trig_o     (el_daisy),
    .event_arm_o      (el_arm),
    .trigger_event_o  (trigger_event),
    .shield_cnt_o     (sh_cnt),
    .shield_active_o  (sh_active),
    .trig_snapshot_o  (snapshot)
  );

  rp_bram_sm #(.RSZ(RSZ)) i_bram (
    .adc_clk_i     (clk),
    .adc_rstn_i    (rstn),
    .set_dly_i     (bs_set_dly),
    .set_dec1_i    (bs_set_dec1),
    .adc_rst_do_i  (bs_rst_do),
    .adc_we_keep_i (bs_we_keep),
    .adc_arm_do_i  (bs_arm),
    .adc_trig_i    (trigger_event),   // <- salida conjunta del event_logic
    .adc_dv_i      (bs_dv),
    .indep_mode_i  (bs_indep),
    .trig_dis_clr_i(bs_trig_dis_clr),
    .adc_wp_o      (bs_wp),
    .adc_wp_cur_o  (bs_wp_cur),
    .adc_wp_trig_o (bs_wp_trig),
    .adc_we_cnt_o  (bs_we_cnt),
    .adc_state_o   (bs_state),
    .adc_dly_do_o  (bs_dly_do),
    .adc_we_o      (bs_we)
  );

  //--------------------------------------------------------------------------
  // Utilidades
  //--------------------------------------------------------------------------
  integer pass_cnt = 0, fail_cnt = 0;

  task automatic check(input string name, input bit cond);
    begin
      if (cond) begin pass_cnt = pass_cnt + 1; $display("  PASS: %s", name); end
      else begin
        fail_cnt = fail_cnt + 1;
        $display("  FAIL: %s  [wp_trig=%0d adc_trg_rd=%0b trg_state_ch0=0x%08x dis=0x%1x]",
                 name, bs_wp_trig, adc_trg_rd, el_trg_state[31:0], el_dis);
      end
    end
  endtask

  // reset general + reset funcional (adc_rst_do, como 0x0202) + clear (0x94)
  task automatic init_idle;
    begin
      @(negedge clk);
      rstn=0; el_rst_do=4'hF; bs_rst_do=1; el_sw_clr=4'hF;
      el_set_src='0; el_set_new=0; el_trig_p=0; el_trig_sw=0;
      el_we_keep=0; bs_we_keep=0; bs_arm=0; sh_src=0; sh_dst=0; sh_dur=0;
      repeat(4) @(negedge clk);
      rstn=1;
      @(negedge clk);
      el_rst_do=0; bs_rst_do=0; el_sw_clr=0;
      @(negedge clk);
    end
  endtask

  task automatic arm;  // pulso adc_arm_do (como escribir 0x00 bit0)
    begin @(negedge clk); bs_arm=1; @(negedge clk); bs_arm=0; end
  endtask

  task automatic load_mask(input [31:0] m);  // pulso new_trg_src + set_trg_src
    begin
      @(negedge clk); el_set_src={m,m}; el_set_new=4'hF;
      @(negedge clk); el_set_new=0;
    end
  endtask

  task automatic inject_edge;  // 1 flanco posedge en ADC ch0
    begin @(negedge clk); el_trig_p=4'b0001; @(negedge clk); el_trig_p=4'b0000; end
  endtask

  task automatic sw_pulse;     // pulso de SW trigger (como escribir 0x04)
    begin @(negedge clk); el_trig_sw=4'b0001; @(negedge clk); el_trig_sw=4'b0000; end
  endtask

  //--------------------------------------------------------------------------
  // Escenarios
  //--------------------------------------------------------------------------
  initial begin
    $dumpfile("tb_trig_capture.vcd");
    $dumpvars(0, tb_trig_capture);

    $display("=== tb_trig_capture ===");

    // ---- A: mascara-antes-de-arm + flanco pre-arm -> DEADLOCK (bug) ----
    init_idle;
    load_mask(32'hFFFF_FFFF);          // mascara viva ANTES de armar
    inject_edge;                       // flanco pre-arm: gasta la mascara
    @(negedge clk);                    // dejar propagar el auto-clear (adc_trig -> set_trig_src<=0)
    check("A: mascara auto-limpiada por flanco pre-arm (trg_state==0)",
          el_trg_state[31:0]==32'h0);
    repeat(2) @(negedge clk);
    arm;                               // recien ahora se arma
    repeat(4) begin inject_edge; repeat(3) @(negedge clk); end
    check("A: DEADLOCK reproducido (wp_trig==0 && adc_trg_rd==0)",
          (bs_wp_trig==0) && (adc_trg_rd==1'b0));

    // ---- B: arm-antes-de-mascara -> captura (fix) ----
    init_idle;
    arm;                               // 1) armar PRIMERO
    load_mask(32'hFFFF_FFFF);          // 2) recien ahora habilitar la mascara
    repeat(3) @(negedge clk);
    inject_edge;                       // primer flanco post-arm
    repeat(40) @(negedge clk);         // dejar contar el delay y congelar
    check("B: captura OK (wp_trig!=0 && adc_trg_rd==1)",
          (bs_wp_trig!=0) && (adc_trg_rd==1'b1));
    check("B: buffer congelado (adc_we==0 tras el delay)", bs_we==1'b0);

    // ---- C: SW trigger, mascara-antes-de-arm -> captura (SW inmune) ----
    init_idle;
    load_mask(32'h0000_0001);          // BIT_SW, antes de armar
    arm;
    sw_pulse;                          // pulso SW despues del arm
    repeat(40) @(negedge clk);
    check("C: SW trigger inmune al orden (wp_trig!=0 && adc_trg_rd==1)",
          (bs_wp_trig!=0) && (adc_trg_rd==1'b1));

    $display("---------------------------------------------");
    $display("tb_trig_capture: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  // guarda de timeout
  initial begin #100000; $display("TIMEOUT"); $finish; end

endmodule
