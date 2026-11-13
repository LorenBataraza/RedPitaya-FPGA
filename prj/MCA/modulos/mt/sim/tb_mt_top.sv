`timescale 1ns/1ps
//============================================================================
// tb_mt_top — el multitrigger entero, solo, a través de su borde.
//
// Los TB unitarios prueban cada pieza (mt_trig_src, mt_slope_trig,
// trigger_shield, mt_event_logic, mt_cfg) con sus vecinos simulados. Antes de
// mt_top, la única forma de ver las piezas JUNTAS era rp_scope_mt_com, con la
// cadena del scope entera adelante. Acá el tap MTRG y el control de la captura
// los maneja el TB, y lo que se verifica es el cableado entre las piezas:
//
//  1. IDENTIFICACIÓN por el slot 3 (MAGIC, CAPS con N_CH del top).
//  2. NIVEL: tap → rp_adc_trig → máscara (bit 1) → trigger_event; snapshot,
//     auto-limpieza en single-shot, DIS_FLAGS y re-arm por TRIG_DIS_CLR.
//  3. PENDIENTE configurada por registros: SLOPE_* → mt_slope_trig → bit 17.
//     El bit no sale por event_snap_o (17 b) pero sí por SNAPSHOT.
// 3b. POLO-CERO configurado por registros en ch1: PZ_* → mt_pz_trig → bit 26.
//  4. EXTERNA: trig_ext_i → rp_ext_trig → trig_ext_asg_o → (lazo del top) →
//     trig_ext_asg_i → bit 9.
//  5. VETO por nivel externo: SHIELD_CFG src=ext_lvl, dst=mca → mca_veto_o.
//  6. SW por el puente legacy (lo que usa librp) y por el registro propio.
//  7. CADENA: trig_ch_i → bit 13, y trig_ch_o con los flancos de nivel.
//  8. MODO CONTINUO: con we_keep la máscara sobrevive al disparo.
//  9. EL LAZO CON LA CAPTURA: adc_rst_do y adc_dly_do limpian la máscara.
// 10. RELLENO: los canales >= N_CH valen 0 en trg_state_o.
//============================================================================
module tb_mt_top;

  localparam integer N_CH = 2;
  localparam integer DW   = 14;
  localparam [31:0] MAGIC = 32'h4D545247;   // "MTRG"

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  // --- tap MTRG y config del slot 1 ---
  reg  [N_CH*DW-1:0] mtrg_dat  = 0;
  reg  [4*DW-1:0]    set_tresh = 0, set_hyst = 0;
  reg  [20-1:0]      deb_len   = 20'd10;
  reg  [3:0]         indep_mode = 4'h0;
  reg  [3:0]         legacy_sw = 4'h0, legacy_disclr = 4'h0;

  // --- control de la captura (en el diseño real: osc_cfg, rp_bram_sm, rp_delay)
  reg  [3:0] adc_rst_do = 0, adc_dly_do = 0, we_keep = 0;
  reg  [3:0] dly_valp   = 4'hF;   // decimación 1: una muestra válida por ciclo

  // --- fuentes externas ---
  reg        trig_ext = 0, trig_asg = 0;
  reg  [3:0] trig_ch_i = 0;
  wire [3:0] trig_ext_asg;        // el top une la salida con la entrada
  wire [3:0] trig_ch_o;

  wire        trigger_event, daisy, veto;
  wire [16:0] event_snap;
  wire [3:0]  trig_dis_clr, new_trg_src;
  wire [4*32-1:0] trg_src;
  wire [4*8-1:0]  trg_state;

  reg  [31:0] addr = 0, wdata = 0;
  reg         wen = 0, ren = 0;
  wire [31:0] rdata;
  wire        err, ack;
  wire        trig_arm;     // el disparo puede salir (hacia el MCA)

  mt_top #(.N_CH(N_CH), .DW(DW)) dut (
    .adc_clk_i({N_CH{clk}}), .adc_rstn_i({N_CH{rstn}}),
    .mtrg_dat_i(mtrg_dat), .mtrg_val_i({N_CH{1'b1}}),
    .set_tresh_i(set_tresh), .set_hyst_i(set_hyst), .set_deb_len_i(deb_len),
    .indep_mode_i(indep_mode),
    .legacy_trig_sw_i(legacy_sw), .legacy_trig_dis_clr_i(legacy_disclr),
    .adc_rst_do_i(adc_rst_do), .adc_dly_do_i(adc_dly_do),
    .adc_we_keep_i(we_keep), .dly_valp_i(dly_valp),
    .trig_ext_i(trig_ext), .trig_asg_i(trig_asg),
    .trig_ext_asg_o(trig_ext_asg), .trig_ext_asg_i(trig_ext_asg),
    .trig_ch_i(trig_ch_i), .trig_ch_o(trig_ch_o),
    .trigger_event_o(trigger_event), .daisy_trig_o(daisy), .mca_veto_o(veto),
    .trig_arm_o(trig_arm),
    .event_snap_o(event_snap),
    .trig_dis_clr_o(trig_dis_clr), .trg_src_o(trg_src),
    .new_trg_src_o(new_trg_src), .trg_state_o(trg_state),
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

  task automatic bus_write(input [19:0] a, input [31:0] d);
    integer n;
    begin
      @(negedge clk); addr = {12'h403, a}; wdata = d; wen = 1'b1;
      n = 0;
      while (!ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!ack) ack_timeouts = ack_timeouts + 1;
      @(negedge clk); wen = 1'b0; addr = 0;
      while (ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  task automatic bus_read(input [19:0] a, output [31:0] d);
    integer n;
    begin
      @(negedge clk); addr = {12'h403, a}; ren = 1'b1;
      n = 0;
      while (!ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!ack) ack_timeouts = ack_timeouts + 1;
      d = rdata;
      @(negedge clk); ren = 1'b0; addr = 0;
      while (ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  //--------------------------------------------------------------------------
  // Monitores
  //--------------------------------------------------------------------------
  integer n_events = 0, n_daisy_diff = 0;
  reg     ev_q = 0;
  reg [3:0] ext_asg_seen = 0, trig_ch_seen = 0, disclr_seen = 0;
  reg       pad_bad = 0;
  always @(posedge clk) if (rstn) begin
    ev_q <= trigger_event;
    if (trigger_event && !ev_q) n_events <= n_events + 1;
    if (daisy !== trigger_event) n_daisy_diff <= n_daisy_diff + 1;
    ext_asg_seen <= ext_asg_seen | trig_ext_asg;
    trig_ch_seen <= trig_ch_seen | trig_ch_o;
    disclr_seen  <= disclr_seen  | trig_dis_clr;
    if (trg_state[31:N_CH*8] !== 0) pad_bad <= 1'b1;
  end

  // Espera un evento nuevo; devuelve 1 si llegó antes del timeout.
  task automatic wait_event(input integer timeout, output bit got);
    integer n0, k;
    begin
      n0 = n_events; got = 0;
      for (k = 0; k < timeout && !got; k = k + 1) begin
        @(negedge clk); if (n_events != n0) got = 1;
      end
    end
  endtask

  // Lo mismo, contando desde n0: para estímulos que disparan MIENTRAS duran
  // (un pulso de SW de ~5 ciclos, una transacción de bus), donde el evento ya
  // pasó cuando el estímulo termina.
  task automatic wait_since(input integer n0, input integer timeout, output bit got);
    integer k;
    begin
      got = (n_events != n0);
      for (k = 0; k < timeout && !got; k = k + 1) begin
        @(negedge clk); if (n_events != n0) got = 1;
      end
    end
  endtask

  // Ningún evento durante 'cycles' ciclos.
  task automatic no_event(input integer cycles, output bit quiet);
    integer n0;
    begin
      n0 = n_events; repeat (cycles) @(negedge clk); quiet = (n_events == n0);
    end
  endtask

  task automatic set_ch(input integer ch, input integer v);
    begin @(negedge clk); mtrg_dat[ch*DW +: DW] = v[DW-1:0]; end
  endtask

  // re-arm completo entre pruebas: limpia el disable de los canales y el snapshot
  task automatic rearm();
    begin bus_write(20'h024, 32'hF); repeat (5) @(negedge clk); end
  endtask

  reg [31:0] d;
  bit got, quiet;
  integer n0;

  initial begin
    $dumpfile("tb_mt_top.vcd");
    $dumpvars(0, tb_mt_top);

    set_tresh[0*DW +: DW] = 1000; set_hyst[0*DW +: DW] = 50;
    set_tresh[1*DW +: DW] = 1000; set_hyst[1*DW +: DW] = 50;
    repeat (10) @(negedge clk); rstn = 1;
    repeat (10) @(negedge clk);

    //----------------------------------------------------------------------
    // 1. IDENTIFICACIÓN
    //----------------------------------------------------------------------
    $display("-- 1. identificacion por el slot 3 --");
    bus_read(20'h000, d); checkv("MAGIC", d, MAGIC);
    bus_read(20'h004, d);
    checkv("CAPS.N_CH es el del top", d[3:0], N_CH);
    checkv("CAPS.SRC_W", d[11:4], 32);
    check ("CAPS.HAS_SLOPE", d[16]);
    check ("CAPS.HAS_PZ", d[17]);
    check ("reset: ningun evento", n_events == 0);

    //----------------------------------------------------------------------
    // 2. NIVEL, single-shot
    //----------------------------------------------------------------------
    $display("-- 2. disparo de nivel por el tap --");
    bus_write(20'h040, 32'h0000_0002);                 // ch0 posedge
    checkv("trg_state: mascara activa en ch0", trg_state[7:0], 8'h02);
    checkv("trg_state: ch1 sigue a ch0 sin indep_mode", trg_state[15:8], 8'h02);
    set_ch(0, 2000);
    wait_event(50, got); check("evento por flanco de nivel", got);
    check ("trig_ch_o lleva el flanco de ch0", trig_ch_seen[0]);
    repeat (3) @(negedge clk);
    check ("event_snap_o: adc_p[0]", event_snap[1]);
    bus_read(20'h018, d); check("SNAPSHOT: adc_p[0]", d[1]);
    checkv("event_snap_o == SNAPSHOT[16:0]", event_snap, d[16:0]);
    checkv("single-shot: mascara auto-limpiada", trg_state[15:0], 16'h0);
    bus_read(20'h01C, d); checkv("DIS_FLAGS: disable de ch0 y ch1", d[3:0], 4'h3);
    set_ch(0, 0); set_ch(0, 2000);
    no_event(30, quiet); check("sin mascara no re-dispara", quiet);
    set_ch(0, 0);
    rearm();
    check ("trig_dis_clr_o pulso", disclr_seen[0]);
    bus_read(20'h01C, d); checkv("TRIG_DIS_CLR limpia los disable", d[3:0], 4'h0);
    bus_read(20'h018, d); checkv("TRIG_DIS_CLR limpia el snapshot", d, 32'h0);

    //----------------------------------------------------------------------
    // 3. PENDIENTE, configurada por registros
    //----------------------------------------------------------------------
    $display("-- 3. disparo de pendiente --");
    set_tresh[0*DW +: DW] = 8000;                       // el de nivel no molesta
    bus_write(20'h070, 2000);                           // SLOPE_THR ch0
    bus_write(20'h080, 200);                            // SLOPE_HYST ch0
    bus_write(20'h060, 32'h8000_0204);                  // en, G=2, L=4
    repeat (40) @(negedge clk);                         // llena 2L+G
    bus_write(20'h040, 32'h0002_0000);                  // bit 17: slope_p ch0
    set_ch(0, 1500);                                    // s = L*A = 6000
    wait_event(50, got); check("evento por pendiente", got);
    repeat (3) @(negedge clk);
    bus_read(20'h018, d); check("SNAPSHOT: slope_p[0] (bit 17)", d[17]);
    check ("event_snap_o no tiene los bits de pendiente", event_snap === d[16:0]);
    set_ch(0, 0);
    bus_write(20'h060, 32'h0);
    rearm();

    //----------------------------------------------------------------------
    // 3b. POLO-CERO, configurado por registros, en ch1
    //----------------------------------------------------------------------
    // Un escalon de 500 por el trapecio k=2, m=1 con polo-cero: el transitorio
    // sube a ~3900 (dispara) y se asienta en ~47, debajo del re-armado (176).
    $display("-- 3b. disparo con polo-cero en ch1 --");
    set_tresh[1*DW +: DW] = 8000;
    bus_write(20'h0B4, 353);                            // PZ_THR ch1
    bus_write(20'h0C4, 177);                            // PZ_HYST ch1
    bus_write(20'h0A4, 3992);                           // PZ_MQ ch1 (tau = 250)
    bus_write(20'h094, 32'h8A00_0102);                  // en, sh=10, m=1, k=2
    repeat (40) @(negedge clk);                         // el arranque
    bus_write(20'h040, 32'h1 << 26);                    // bit 26: pz_p ch1
    no_event(20, quiet); check("polo-cero sin pulso: quieto", quiet);
    check("trig_arm: polo-cero armado en la mascara", trig_arm === 1'b1);
    bus_read(20'h014, d); check("SHIELD_STAT: bit 18 (trig_arm) en 1", d[18]);
    set_ch(1, 500);
    wait_event(50, got); check("evento por polo-cero en ch1", got);
    repeat (3) @(negedge clk);
    // disparo unico: tras el evento el canal queda deshabilitado y sin mascara
    check("trig_arm: tras el disparo unico, no puede disparar", trig_arm === 1'b0);
    bus_read(20'h014, d); check("SHIELD_STAT: bit 18 (trig_arm) en 0", !d[18]);
    bus_read(20'h018, d); checkv("SNAPSHOT: solo pz_p[1] (bit 26)", d, 32'h1 << 26);
    check ("event_snap_o no tiene los bits de polo-cero", event_snap === d[16:0]);
    set_ch(1, 0);
    bus_write(20'h094, 32'h0);
    rearm();

    //----------------------------------------------------------------------
    // 4. EXTERNA, por el lazo trig_ext_asg
    //----------------------------------------------------------------------
    $display("-- 4. disparo externo --");
    bus_write(20'h040, 32'h0000_0200);                  // bit 9: ext posedge
    @(negedge clk); trig_ext = 1;
    wait_event(60, got); check("evento por flanco externo", got);
    check ("trig_ext_asg_o[0] (ext_p) pulso", ext_asg_seen[0]);
    repeat (3) @(negedge clk);
    check ("event_snap_o: ext_p", event_snap[9]);
    @(negedge clk); trig_ext = 0;
    repeat (40) @(negedge clk);
    rearm();

    //----------------------------------------------------------------------
    // 5. VETO por nivel externo
    //----------------------------------------------------------------------
    $display("-- 5. veto al MCA por nivel externo --");
    bus_write(20'h010, (32'd20 << 16) | (32'h1 << 12) | (32'h1 << 6));
    bus_read(20'h010, d);
    checkv("SHIELD_CFG readback", d, (32'd20 << 16) | (32'h1 << 12) | (32'h1 << 6));
    check ("sin linea, sin veto", !veto);
    @(negedge clk); trig_ext = 1;
    repeat (10) @(negedge clk);
    check ("linea alta: veto", veto);
    bus_read(20'h014, d); check("SHIELD_STAT: mca_veto", d[17]);
    repeat (100) @(negedge clk);
    check ("veto se sostiene con la linea", veto);
    @(negedge clk); trig_ext = 0;
    repeat (10) @(negedge clk);
    check ("cola del holdoff (dur=20)", veto);
    repeat (30) @(negedge clk);
    check ("veto termina", !veto);
    bus_write(20'h010, 32'h0);
    repeat (40) @(negedge clk);
    rearm();

    //----------------------------------------------------------------------
    // 6. SW: puente legacy y registro propio
    //----------------------------------------------------------------------
    $display("-- 6. disparo por software --");
    bus_write(20'h040, 32'h0000_0001);                  // bit 0: SW
    n0 = n_events;
    @(negedge clk); legacy_sw = 4'h1;                   // dura lo que la transaccion
    repeat (5) @(negedge clk); legacy_sw = 4'h0;
    wait_since(n0, 20, got); check("evento por SW legacy (0x004 del slot 1)", got);
    repeat (3) @(negedge clk);
    check ("event_snap_o: sw", event_snap[0]);
    @(negedge clk); legacy_disclr = 4'hF;               // re-arm por el puente
    repeat (5) @(negedge clk); legacy_disclr = 4'h0;
    repeat (3) @(negedge clk);
    bus_read(20'h01C, d); checkv("disclr legacy limpia los disable", d[3:0], 4'h0);
    bus_write(20'h040, 32'h0000_0001);
    n0 = n_events;
    bus_write(20'h020, 32'h1);                          // TRIG_SW propio
    wait_since(n0, 20, got); check("evento por TRIG_SW (0x020)", got);
    rearm();

    //----------------------------------------------------------------------
    // 7. CADENA
    //----------------------------------------------------------------------
    $display("-- 7. cadena desde el otro scope --");
    bus_write(20'h040, 32'h0000_2000);                  // bit 13: trig_ch[0]
    @(negedge clk); trig_ch_i = 4'h1; @(negedge clk); trig_ch_i = 4'h0;
    wait_event(20, got); check("evento por la cadena", got);
    rearm();

    //----------------------------------------------------------------------
    // 8. MODO CONTINUO
    //----------------------------------------------------------------------
    $display("-- 8. modo continuo (we_keep) --");
    set_tresh[0*DW +: DW] = 1000;
    we_keep = 4'hF;
    bus_write(20'h040, 32'h0000_0002);
    set_ch(0, 2000);
    wait_event(50, got); check("continuo: primer evento", got);
    repeat (3) @(negedge clk);
    checkv("continuo: la mascara persiste", trg_state[7:0], 8'h02);
    set_ch(0, 0); set_ch(0, 2000);
    no_event(30, quiet); check("continuo: el disable bloquea hasta el clear", quiet);
    set_ch(0, 0);
    rearm();
    set_ch(0, 2000);
    wait_event(50, got); check("continuo: re-dispara tras TRIG_DIS_CLR", got);
    set_ch(0, 0);
    we_keep = 4'h0;
    rearm();

    //----------------------------------------------------------------------
    // 9. EL LAZO CON LA CAPTURA
    //----------------------------------------------------------------------
    $display("-- 9. control de la captura --");
    bus_write(20'h040, 32'h0000_0002);
    checkv("mascara cargada", trg_state[7:0], 8'h02);
    @(negedge clk); adc_dly_do = 4'h1; @(negedge clk); adc_dly_do = 4'h0;
    @(negedge clk);
    checkv("adc_dly_do limpia la mascara (single-shot)", trg_state[15:0], 16'h0);
    bus_write(20'h040, 32'h0000_0002);
    @(negedge clk); adc_rst_do = 4'h3; @(negedge clk); adc_rst_do = 4'h0;
    @(negedge clk);
    checkv("adc_rst_do limpia la mascara", trg_state[15:0], 16'h0);

    //----------------------------------------------------------------------
    // 10. RELLENO Y CONTRATO
    //----------------------------------------------------------------------
    check ("trg_state_o: canales >= N_CH siempre en 0", !pad_bad);
    check ("daisy_trig_o == trigger_event_o", n_daisy_diff == 0);
    checkv("sin timeouts de ack", ack_timeouts, 0);

    $display("tb_mt_top: %0d PASS, %0d FAIL (%0d eventos)", pass_cnt, fail_cnt, n_events);
    if (fail_cnt == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end

endmodule
