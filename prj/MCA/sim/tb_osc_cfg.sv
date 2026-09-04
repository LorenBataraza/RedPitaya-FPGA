`timescale 1ns/1ps
//============================================================================
// tb_osc_cfg — el OSC no cambió de comportamiento, y los dos mapas son el
// mismo banco de registros.
//
// Cuatro bloques:
//
//  A. EQUIVALENCIA DIFERENCIAL. Se instancian el módulo VIEJO
//     (multitrigger_rp_scope_cfg) y el NUEVO (osc_cfg), se les da EXACTAMENTE
//     el mismo estímulo por los offsets legacy, y se comparan todas las
//     salidas comunes ciclo a ciclo. Es la prueba de que la mudanza no cambió
//     nada de lo que librp ya usaba: 111 llamadas a la API rp dependen de eso.
//
//  B. ALIAS DE LOS DOS MAPAS. Escribir por legacy y leer por canónico (y al
//     revés) tiene que dar el mismo valor: es UN solo flop con dos
//     decodificadores. Si esto falla, hay estado duplicado y se van a
//     desincronizar.
//
//  C. EL PUENTE LEGACY hacia el slot 3 (0x004 SW-trigger, 0x094 dis_clr).
//
//  D. CONTRATO DE BUS, incluida la regresión del cuelgue: las aperturas de los
//     canales NO construidos. El módulo viejo ataba el ack a bram_ack_i[2]/[3],
//     que rp_scope_multitrigger_com fija en 0, y no hacía ack nunca. El nuevo
//     usa latencia fija. Este TB barre esas direcciones.
//============================================================================
module tb_osc_cfg;

  localparam integer DW   = 14;
  localparam integer RSZ  = 14;
  localparam integer N_CH = 2;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg  [31:0] addr = 0, wdata = 0;
  reg         wen = 0, ren = 0;

  // estado de vuelta (comun a los dos DUT)
  reg [4*8  -1:0] adc_state   = 32'h0, axi_state = 32'h0, trg_state = 32'h0;
  reg [2*8  -1:0] adc_state_x = 16'h0, axi_state_x = 16'h0, trg_state_x = 16'h0;
  reg [4*RSZ-1:0] adc_wp_cur  = 0, adc_wp_trig = 0;
  reg [4*32 -1:0] adc_we_cnt  = 0, axi_wp_cur = 0, axi_wp_trig = 0;
  reg [4*DW -1:0] bram_rd_dat = 0;
  // Los canales 2 y 3 NO existen: ack atado a cero, igual que en el diseño real.
  wire [4-1:0]    bram_ack    = 4'b0011;

  //--------------------------------------------------------------------------
  // DUT NUEVO
  //--------------------------------------------------------------------------
  wire [31:0] n_rdata; wire n_err, n_ack;
  wire [ 4-1:0] n_arm, n_rst, n_wekeep, n_indep, n_axien_p, n_dec1, n_filtrstn;
  wire [ 4-1:0] n_avg, n_byp, n_axien, n_leg_sw, n_leg_disclr;
  wire [4*DW-1:0] n_tresh, n_hyst, n_calib_off;
  wire [4*32-1:0] n_dly, n_axi_start, n_axi_stop, n_axi_dly;
  wire [4*17-1:0] n_dec;
  wire [4*18-1:0] n_aa; wire [4*25-1:0] n_bb, n_kk, n_pp;
  wire [4*16-1:0] n_calib_gain;
  wire [  20-1:0] n_deblen;

  osc_cfg #(.EN_LEGACY_MAP(1), .CHN(0), .N_CH(N_CH), .DW(DW), .RSZ(RSZ)) dut_new (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .sys_addr(addr), .sys_wdata(wdata), .sys_wen(wen), .sys_ren(ren),
    .sys_rdata(n_rdata), .sys_err(n_err), .sys_ack(n_ack),
    .adc_state_i(adc_state), .axi_state_i(axi_state), .trg_state_i(trg_state),
    .adc_state_ext_i(adc_state_x), .axi_state_ext_i(axi_state_x),
    .trg_state_ext_i(trg_state_x),
    .adc_wp_cur_i(adc_wp_cur), .adc_wp_trig_i(adc_wp_trig),
    .adc_we_cnt_i(adc_we_cnt), .axi_wp_cur_i(axi_wp_cur),
    .axi_wp_trig_i(axi_wp_trig), .bram_rd_dat_i(bram_rd_dat),
    .adc_arm_do_o(n_arm), .adc_rst_do_o(n_rst), .adc_we_keep_o(n_wekeep),
    .indep_mode_o(n_indep), .axi_en_pulse_o(n_axien_p), .set_dec1_o(n_dec1),
    .filt_rstn_o(n_filtrstn), .set_tresh_o(n_tresh), .set_dly_o(n_dly),
    .set_dec_o(n_dec), .set_hyst_o(n_hyst), .set_avg_en_o(n_avg),
    .set_filt_aa_o(n_aa), .set_filt_bb_o(n_bb), .set_filt_kk_o(n_kk),
    .set_filt_pp_o(n_pp), .set_calib_offset_o(n_calib_off),
    .set_calib_gain_o(n_calib_gain), .set_filt_byp_o(n_byp),
    .set_deb_len_o(n_deblen), .set_axi_start_o(n_axi_start),
    .set_axi_stop_o(n_axi_stop), .set_axi_dly_o(n_axi_dly),
    .set_axi_en_o(n_axien),
    .legacy_trig_sw_o(n_leg_sw), .legacy_trig_dis_clr_o(n_leg_disclr)
  );

  //--------------------------------------------------------------------------
  // DUT VIEJO — referencia. Mismo estímulo, se comparan las salidas comunes.
  //--------------------------------------------------------------------------
  wire [31:0] o_rdata; wire o_err, o_ack;
  wire [ 4-1:0] o_arm, o_rst, o_swtrig, o_wekeep, o_disclr, o_indep;
  wire [ 4-1:0] o_axien_p, o_newsrc, o_dec1, o_filtrstn, o_avg, o_byp, o_axien;
  wire [4*DW-1:0] o_tresh, o_hyst, o_calib_off;
  wire [4*32-1:0] o_dly, o_src, o_axi_start, o_axi_stop, o_axi_dly;
  wire [4*17-1:0] o_dec;
  wire [4*18-1:0] o_aa; wire [4*25-1:0] o_bb, o_kk, o_pp;
  wire [4*16-1:0] o_calib_gain;
  wire [  20-1:0] o_deblen;
  wire [ 4-1:0] o_sh_src, o_sh_dst; wire [16-1:0] o_sh_dur;

  multitrigger_rp_scope_cfg #(.CHN(0), .N_CH(N_CH), .DW(DW), .RSZ(RSZ)) dut_old (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .sys_addr(addr), .sys_wdata(wdata), .sys_wen(wen), .sys_ren(ren),
    .sys_rdata(o_rdata), .sys_err(o_err), .sys_ack(o_ack),
    .adc_state_i(adc_state), .axi_state_i(axi_state), .trg_state_i(trg_state),
    .adc_state_ext_i(adc_state_x), .axi_state_ext_i(axi_state_x),
    .trg_state_ext_i(trg_state_x),
    .adc_wp_cur_i(adc_wp_cur), .adc_wp_trig_i(adc_wp_trig),
    .adc_we_cnt_i(adc_we_cnt), .axi_wp_cur_i(axi_wp_cur),
    .axi_wp_trig_i(axi_wp_trig),
    .bram_rd_dat_i(bram_rd_dat), .bram_ack_i(bram_ack),
    .adc_arm_do_o(o_arm), .adc_rst_do_o(o_rst), .adc_trig_sw_o(o_swtrig),
    .adc_we_keep_o(o_wekeep), .trig_dis_clr_o(o_disclr), .indep_mode_o(o_indep),
    .axi_en_pulse_o(o_axien_p), .new_trg_src_o(o_newsrc), .trg_src_o(o_src),
    .set_dec1_o(o_dec1), .filt_rstn_o(o_filtrstn), .set_tresh_o(o_tresh),
    .set_dly_o(o_dly), .set_dec_o(o_dec), .set_hyst_o(o_hyst),
    .set_avg_en_o(o_avg), .set_filt_aa_o(o_aa), .set_filt_bb_o(o_bb),
    .set_filt_kk_o(o_kk), .set_filt_pp_o(o_pp),
    .set_calib_offset_o(o_calib_off), .set_calib_gain_o(o_calib_gain),
    .set_filt_byp_o(o_byp), .set_deb_len_o(o_deblen),
    .set_axi_start_o(o_axi_start), .set_axi_stop_o(o_axi_stop),
    .set_axi_dly_o(o_axi_dly), .set_axi_en_o(o_axien),
    .shield_src_o(o_sh_src), .shield_dst_o(o_sh_dst), .shield_dur_o(o_sh_dur),
    .adc_trg_dis_act_i(4'h0), .shield_cnt_i(16'h0), .shield_active_i(1'b0),
    .trig_snapshot_i(17'h0)
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
  // Comparación diferencial continua: cualquier divergencia en cualquier
  // ciclo queda registrada. Sólo se miran los bits de los canales que existen.
  //--------------------------------------------------------------------------
  integer diff_cnt = 0;
  reg     diff_armed = 0;

  task automatic cmp(input string name, input [127:0] a, input [127:0] b);
    begin
      if (a !== b) begin
        diff_cnt = diff_cnt + 1;
        if (diff_cnt < 12)
          $display("  DIVERGE %s: nuevo=0x%0h viejo=0x%0h (t=%0t)", name, a, b, $time);
      end
    end
  endtask

  always @(posedge clk) if (diff_armed) begin
    cmp("set_tresh",   n_tresh[2*DW-1:0],  o_tresh[2*DW-1:0]);
    cmp("set_hyst",    n_hyst[2*DW-1:0],   o_hyst[2*DW-1:0]);
    cmp("set_dly",     n_dly[2*32-1:0],    o_dly[2*32-1:0]);
    cmp("set_dec",     n_dec[2*17-1:0],    o_dec[2*17-1:0]);
    cmp("set_dec1",    n_dec1[1:0],        o_dec1[1:0]);
    cmp("set_avg_en",  n_avg[1:0],         o_avg[1:0]);
    cmp("set_aa",      n_aa[2*18-1:0],     o_aa[2*18-1:0]);
    cmp("set_bb",      n_bb[2*25-1:0],     o_bb[2*25-1:0]);
    cmp("set_kk",      n_kk[2*25-1:0],     o_kk[2*25-1:0]);
    cmp("set_pp",      n_pp[2*25-1:0],     o_pp[2*25-1:0]);
    cmp("filt_byp",    n_byp,              o_byp);
    cmp("deb_len",     n_deblen,           o_deblen);
    cmp("calib_off",   n_calib_off[2*DW-1:0],   o_calib_off[2*DW-1:0]);
    cmp("calib_gain",  n_calib_gain[2*16-1:0],  o_calib_gain[2*16-1:0]);
    cmp("axi_start",   n_axi_start[2*32-1:0],   o_axi_start[2*32-1:0]);
    cmp("axi_stop",    n_axi_stop[2*32-1:0],    o_axi_stop[2*32-1:0]);
    cmp("axi_dly",     n_axi_dly[2*32-1:0],     o_axi_dly[2*32-1:0]);
    cmp("axi_en",      n_axien[1:0],       o_axien[1:0]);
    cmp("axi_en_pulse",n_axien_p[1:0],     o_axien_p[1:0]);
    cmp("arm_do",      n_arm[1:0],         o_arm[1:0]);
    cmp("rst_do",      n_rst[1:0],         o_rst[1:0]);
    cmp("we_keep",     n_wekeep[1:0],      o_wekeep[1:0]);
    cmp("indep_mode",  n_indep[1:0],       o_indep[1:0]);
    cmp("filt_rstn",   n_filtrstn[1:0],    o_filtrstn[1:0]);
    // el SW-trigger del viejo sale por adc_trig_sw_o; en el nuevo, por el puente
    cmp("sw_trigger",  n_leg_sw[1:0],      o_swtrig[1:0]);
    cmp("dis_clr",     n_leg_disclr[1:0],  o_disclr[1:0]);
  end

  //--------------------------------------------------------------------------
  // BFM: sostiene wen/ren hasta el ack del DUT NUEVO.
  //--------------------------------------------------------------------------
  localparam integer ACK_LIMIT = 20;
  integer ack_timeouts = 0, old_timeouts = 0;

  task automatic bus_write(input [19:0] a, input [31:0] d);
    integer n;
    begin
      @(negedge clk); addr = {12'h401, a}; wdata = d; wen = 1'b1;
      n = 0;
      while (!n_ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!n_ack) begin ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK en escritura a 0x%05h", a); end
      @(negedge clk); wen = 1'b0; addr = 0;
      while (n_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  task automatic bus_read(input [19:0] a, output [31:0] d);
    integer n;
    begin
      @(negedge clk); addr = {12'h401, a}; ren = 1'b1;
      n = 0;
      while (!n_ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!n_ack) begin ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK en lectura de 0x%05h", a); end
      if (!o_ack) old_timeouts = old_timeouts + 1;
      d = n_rdata;
      @(negedge clk); ren = 1'b0; addr = 0;
      while (n_ack) @(negedge clk);
      @(negedge clk);
    end
  endtask

  reg [31:0] d;
  integer i;

  // Direcciones canónicas
  localparam [19:0] CB = 20'h01000;              // globales
  function automatic [19:0] CCH(input integer ch, input [19:0] off);
    CCH = 20'h01100 + ch*20'h40 + off;
  endfunction
  function automatic [19:0] CAX(input integer ch, input [19:0] off);
    CAX = 20'h01200 + ch*20'h20 + off;
  endfunction

  initial begin
    $dumpfile("tb_osc_cfg.vcd");
    $dumpvars(0, tb_osc_cfg);

    repeat (10) @(negedge clk);
    rstn = 1;
    repeat (10) @(negedge clk);
    diff_armed = 1;

    //----------------------------------------------------------------------
    // A. EQUIVALENCIA DIFERENCIAL sobre todos los offsets legacy
    //----------------------------------------------------------------------
    $display("-- A. equivalencia con el modulo viejo (offsets legacy) --");

    bus_write(20'h008, 32'h0000_1FAB);   // tresh ch0
    bus_write(20'h00C, 32'h0000_2CDE);   // tresh ch1
    bus_write(20'h010, 32'h1234_5678);   // dly ch0
    bus_write(20'h014, 32'h0000_0007);   // dec ch0
    bus_write(20'h020, 32'h0000_0033);   // hyst ch0
    bus_write(20'h024, 32'h0000_0044);   // hyst ch1
    bus_write(20'h028, 32'h0101_0101);   // avg_en, byte por canal
    bus_write(20'h030, 32'h0002_ABCD);   // filt aa ch0
    bus_write(20'h034, 32'h0012_3456);   // filt bb ch0
    bus_write(20'h038, 32'h0055_5555);   // filt kk ch0
    bus_write(20'h03C, 32'h0011_1111);   // filt pp ch0
    bus_write(20'h040, 32'h0003_1234);   // filt aa ch1
    bus_write(20'h044, 32'h0065_4321);   // filt bb ch1
    bus_write(20'h048, 32'h0077_7777);   // filt kk ch1
    bus_write(20'h04C, 32'h0022_2222);   // filt pp ch1
    bus_write(20'h050, 32'hA000_0000);   // axi start ch0
    bus_write(20'h054, 32'hB000_0000);   // axi stop ch0
    bus_write(20'h058, 32'h0000_00FF);   // axi dly ch0
    bus_write(20'h05C, 32'h0000_0001);   // axi en ch0 (+ pulso)
    bus_write(20'h070, 32'hC000_0000);   // axi start ch1
    bus_write(20'h074, 32'hD000_0000);
    bus_write(20'h078, 32'h0000_00EE);
    bus_write(20'h07C, 32'h0000_0001);
    bus_write(20'h090, 32'h0000_F424);   // deb_len
    bus_write(20'h098, 32'h0000_000A);   // filt_byp
    bus_write(20'h110, 32'h8765_4321);   // dly ch1
    bus_write(20'h114, 32'h0000_0003);   // dec ch1
    bus_write(20'h200, 32'h0000_0123);   // calib offset ch0
    bus_write(20'h204, 32'h0000_9000);   // calib gain ch0
    bus_write(20'h208, 32'h0000_0456);   // calib offset ch1
    bus_write(20'h20C, 32'h0000_A000);   // calib gain ch1

    // comandos: arm, reset, we_keep, indep_mode (byte por canal)
    bus_write(20'h000, 32'h0000_0101);   // arm ch0+ch1
    bus_write(20'h000, 32'h0000_0202);   // reset ch0+ch1
    bus_write(20'h000, 32'h0000_0808);   // we_keep
    bus_write(20'h000, 32'h0000_2020);   // indep_mode
    bus_write(20'h004, 32'h0000_0101);   // SW trigger
    bus_write(20'h094, 32'h0000_0101);   // trig_dis_clr

    // con indep_mode ya en 1, repetir para cubrir la otra rama del fan-out
    bus_write(20'h010, 32'h0F0F_0F0F);
    bus_write(20'h110, 32'hF0F0_F0F0);
    bus_write(20'h014, 32'h0000_0001);
    bus_write(20'h000, 32'h0000_0100);   // arm solo ch0
    bus_write(20'h000, 32'h0000_0000);   // escritura nula

    // y volver a indep_mode = 0 para cubrir el fan-out desde ch0
    bus_write(20'h000, 32'h0000_0808);
    bus_write(20'h000, 32'h0000_0101);

    repeat (10) @(negedge clk);
    checkv("ninguna divergencia con el modulo viejo", diff_cnt, 0);

    //----------------------------------------------------------------------
    // B. LOS DOS MAPAS SON EL MISMO BANCO
    //----------------------------------------------------------------------
    $display("-- B. alias legacy <-> canonico --");
    // A partir de acá se escribe por el mapa canónico, que el módulo viejo no
    // tiene: divergir es lo esperado, así que se desarma la comparación.
    diff_armed = 0;

    // escrito por legacy, leido por canonico
    bus_write(20'h008, 32'h0000_1ABC);
    bus_read(CCH(0, 20'h00), d);
    checkv("tresh ch0: escrito legacy, leido canonico", d, 32'h0000_1ABC);

    bus_write(20'h110, 32'hCAFE_0001);
    bus_read(CCH(1, 20'h08), d);
    checkv("dly ch1: escrito legacy, leido canonico", d, 32'hCAFE_0001);

    bus_write(20'h204, 32'h0000_8ABC);
    bus_read(CCH(0, 20'h20), d);
    checkv("calib_gain ch0: escrito legacy, leido canonico", d, 32'h0000_8ABC);

    bus_write(20'h070, 32'h5555_0000);
    bus_read(CAX(1, 20'h00), d);
    checkv("axi_start ch1: escrito legacy, leido canonico", d, 32'h5555_0000);

    // escrito por canonico, leido por legacy
    bus_write(CCH(0, 20'h00), 32'h0000_0DEF);
    bus_read(20'h008, d);
    checkv("tresh ch0: escrito canonico, leido legacy", d, 32'h0000_0DEF);
    check("y el puerto de salida tambien cambio", n_tresh[DW-1:0] === 14'h0DEF);

    bus_write(CCH(1, 20'h04), 32'h0000_0077);
    bus_read(20'h024, d);
    checkv("hyst ch1: escrito canonico, leido legacy", d, 32'h0000_0077);

    bus_write(CCH(1, 20'h0C), 32'h0000_0005);
    bus_read(20'h114, d);
    checkv("dec ch1: escrito canonico, leido legacy", d, 32'h0000_0005);

    bus_write(CB + 20'h01C, 32'h0000_1234);
    bus_read(20'h090, d);
    checkv("deb_len: escrito canonico, leido legacy", d, 32'h0000_1234);

    bus_write(CB + 20'h020, 32'h0000_0005);
    bus_read(20'h098, d);
    checkv("filt_byp: escrito canonico, leido legacy", d, 32'h0000_0005);

    // identificacion y caps del mapa canonico
    bus_read(CB + 20'h000, d); checkv("MAGIC canonico", d, 32'h4F534331);
    bus_read(CB + 20'h004, d);
    checkv("CAPS canonico", d, {10'h0, 6'd14, 2'h0, 6'd14, 4'h0, 4'd2});

    // ch2/ch3 son escribibles por el mapa canonico aunque N_CH=2 (superset)
    bus_write(CCH(2, 20'h00), 32'h0000_0321);
    bus_read(CCH(2, 20'h00), d);
    checkv("tresh ch2 por mapa canonico", d, 32'h0000_0321);

    //----------------------------------------------------------------------
    // C. PUENTE LEGACY hacia el slot 3
    //----------------------------------------------------------------------
    $display("-- C. puente legacy hacia el multitrigger --");
    diff_armed = 0;   // el viejo ya no hace falta para esto
    bus_write(20'h000, 32'h0000_0000);   // indep_mode a 0
    fork
      begin bus_write(20'h004, 32'h0000_0101); end
      begin : watch_sw
        integer k; reg seen;
        seen = 0;
        for (k = 0; k < 30; k = k + 1) begin
          @(posedge clk); if (|n_leg_sw) seen = 1;
        end
        check("0x004 emite el SW-trigger por el puente", seen);
      end
    join

    fork
      begin bus_write(20'h094, 32'h0000_0101); end
      begin : watch_dc
        integer k; reg seen;
        seen = 0;
        for (k = 0; k < 30; k = k + 1) begin
          @(posedge clk); if (|n_leg_disclr) seen = 1;
        end
        check("0x094 emite el dis_clr por el puente", seen);
      end
    join

    //----------------------------------------------------------------------
    // D. CONTRATO DE BUS — incluida la regresión del cuelgue
    //----------------------------------------------------------------------
    $display("-- D. barrido de ack --");
    old_timeouts = 0;

    for (i = 0; i < 20'h300; i = i + 4) bus_read(i[19:0], d);      // legacy
    for (i = 20'h1000; i < 20'h1300; i = i + 4) bus_read(i[19:0], d); // canonico

    // Aperturas BRAM: los canales 3 y 4 (0x3xxxx/0x4xxxx) NO estan construidos.
    // Es exactamente donde el modulo viejo dejaba el bus colgado.
    bus_read(20'h10000, d);
    bus_read(20'h20000, d);
    bus_read(20'h30000, d);   // canal no construido
    bus_read(20'h40000, d);   // canal no construido
    bus_read(20'h3FFFC, d);
    bus_read(20'h4FFFC, d);

    // huecos y direcciones no mapeadas
    bus_read(20'h00300, d); checkv("hueco devuelve 0", d, 32'h0);
    bus_read(20'h0F000, d); checkv("no mapeada devuelve 0", d, 32'h0);
    bus_read(20'hFFFFC, d); checkv("tope del slot devuelve 0", d, 32'h0);
    bus_write(20'h0F000, 32'hA5A5A5A5);

    checkv("DUT NUEVO: sin timeouts de ack en ninguna direccion", ack_timeouts, 0);
    // El viejo sí se cuelga en las aperturas no construidas: es el bug que
    // motivó el ack de latencia fija. Se reporta como evidencia del arreglo.
    $display("   (referencia: el modulo viejo no hizo ack en %0d accesos)", old_timeouts);
    check("el modulo viejo efectivamente colgaba en alguna direccion", old_timeouts > 0);

    $display("tb_osc_cfg: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end

endmodule
