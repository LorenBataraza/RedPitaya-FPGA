`timescale 1ns/1ps
//============================================================================
// tb_multitrigger_cfg — contrato de bus + equivalencia con el mapa viejo.
//
// Lo que importa verificar en una mudanza de registros no es que el módulo
// nuevo "funcione", sino que haga LO MISMO que hacía el bloque del que salió:
//
//  1. CONTRATO DE BUS: ack en <= 20 ciclos para toda dirección del slot.
//  2. Los registros mudados conservan valor y layout de bits
//     (0x210 -> 0x010, 0x240+4c -> 0x040+4c, ...).
//  3. EL PUENTE LEGACY. librp escribe el SW-trigger en 0x004 y el
//     trig_dis_clr en 0x094 del slot 1. osc_cfg los sigue decodificando y los
//     manda acá ya decodificados por canal; las dos vías se OR-ean. Si esto
//     falla, el bitstream nuevo deja de disparar por software desde librp.
//  4. EL FAN-OUT POR indep_mode: sin modo independiente todos los canales
//     siguen al canal 0. Es la lógica *_x del módulo original.
//============================================================================
module tb_multitrigger_cfg;

  localparam integer N_CH = 2;
  localparam [31:0] MAGIC = 32'h4D545247;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg  [31:0] addr = 0, wdata = 0;
  reg         wen = 0, ren = 0;
  wire [31:0] rdata;
  wire        err, ack;

  // estado de entrada (lo que en el diseño real llega desde scope_com)
  reg  [4*8-1:0] trg_state       = 32'h0;
  reg  [  4-1:0] adc_trg_dis_act = 4'h0;
  reg  [  4-1:0] adc_we_keep     = 4'h0;
  reg  [  4-1:0] indep_mode      = 4'h0;
  reg  [ 16-1:0] shield_cnt      = 16'h0;
  reg            shield_active   = 1'b0;
  reg  [ 17-1:0] trig_snapshot   = 17'h0;

  // puente legacy desde osc_cfg
  reg  [  4-1:0] legacy_trig_sw      = 4'h0;
  reg  [  4-1:0] legacy_trig_dis_clr = 4'h0;

  wire [  4-1:0] adc_trig_sw, trig_dis_clr, new_trg_src;
  wire [4*32-1:0] trg_src;
  wire [  4-1:0] shield_src, shield_dst;
  wire [ 16-1:0] shield_dur;

  multitrigger_cfg #(
    .MAGIC(MAGIC), .N_CH(N_CH), .SRC_W(32), .SHIELD_N(4)
  ) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .trg_state_i(trg_state), .adc_trg_dis_act_i(adc_trg_dis_act),
    .adc_we_keep_i(adc_we_keep), .indep_mode_i(indep_mode),
    .shield_cnt_i(shield_cnt), .shield_active_i(shield_active),
    .trig_snapshot_i(trig_snapshot),
    .legacy_trig_sw_i(legacy_trig_sw),
    .legacy_trig_dis_clr_i(legacy_trig_dis_clr),
    .adc_trig_sw_o(adc_trig_sw), .trig_dis_clr_o(trig_dis_clr),
    .new_trg_src_o(new_trg_src), .trg_src_o(trg_src),
    .shield_src_o(shield_src), .shield_dst_o(shield_dst),
    .shield_dur_o(shield_dur),
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
      @(negedge clk); addr = {12'h403, a}; wdata = d; wen = 1'b1;
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
      @(negedge clk); addr = {12'h403, a}; ren = 1'b1;
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

  // Observa el pulso combinacional mientras dura la transacción de escritura.
  reg [3:0] sw_seen, disclr_seen, newsrc_seen;
  always @(posedge clk) if (rstn) begin
    sw_seen     <= sw_seen     | adc_trig_sw;
    disclr_seen <= disclr_seen | trig_dis_clr;
    newsrc_seen <= newsrc_seen | new_trg_src;
  end

  reg [31:0] d;
  integer i;

  initial begin
    $dumpfile("tb_multitrigger_cfg.vcd");
    $dumpvars(0, tb_multitrigger_cfg);
    sw_seen = 0; disclr_seen = 0; newsrc_seen = 0;

    repeat (10) @(negedge clk);
    rstn = 1;
    repeat (10) @(negedge clk);

    //----------------------------------------------------------------------
    // 1. IDENTIFICACIÓN
    //----------------------------------------------------------------------
    $display("-- identificacion --");
    bus_read(20'h000, d); checkv("MAGIC", d, MAGIC);
    bus_read(20'h004, d); checkv("CAPS", d, {16'h0, 4'd4, 8'd32, 4'd2});

    //----------------------------------------------------------------------
    // 2. SHIELD: 0x210 del mapa viejo -> 0x010, mismo layout de bits
    //----------------------------------------------------------------------
    $display("-- trigger_shield (era 0x210) --");
    bus_write(20'h010, {16'd1234, 4'h0, 4'd2, 4'h0, 4'd1});
    check("shield_src", shield_src === 4'd1);
    check("shield_dst", shield_dst === 4'd2);
    check("shield_dur", shield_dur === 16'd1234);
    bus_read(20'h010, d);
    checkv("SHIELD_CFG readback", d, {16'd1234, 4'h0, 4'd2, 4'h0, 4'd1});

    // runtime (era 0x214): {active[16], cnt[15:0]}
    shield_cnt = 16'd77; shield_active = 1'b1;
    @(negedge clk);
    bus_read(20'h014, d); checkv("SHIELD_STAT", d, {15'h0, 1'b1, 16'd77});

    //----------------------------------------------------------------------
    // 3. SNAPSHOT y FLAGS (eran 0x218 y 0x21C)
    //----------------------------------------------------------------------
    $display("-- snapshot y flags --");
    trig_snapshot = 17'h1_5A5A; adc_trg_dis_act = 4'b0101; adc_we_keep = 4'b1100;
    @(negedge clk);
    bus_read(20'h018, d); checkv("SNAPSHOT",  d, {15'h0, 17'h1_5A5A});
    bus_read(20'h01C, d); checkv("DIS_FLAGS", d, {24'h0, 4'b1100, 4'b0101});

    trg_state = 32'hAABBCCDD;
    @(negedge clk);
    bus_read(20'h028, d); checkv("TRG_STATE", d, 32'hAABBCCDD);

    //----------------------------------------------------------------------
    // 4. MÁSCARAS OR: 0x240+4c del mapa viejo -> 0x040+4c
    //----------------------------------------------------------------------
    $display("-- mascaras OR (eran 0x240+) --");
    indep_mode = 4'b1111;   // cada canal independiente: sin fan-out desde ch0
    @(negedge clk);

    newsrc_seen = 0;
    bus_write(20'h040, 32'h0000_1234);
    check("new_trg_src ch0 pulso", newsrc_seen[0] === 1'b1);
    check("new_trg_src ch1 quieto", newsrc_seen[1] === 1'b0);
    bus_read(20'h040, d); checkv("OR_MASK ch0 readback", d, 32'h0000_1234);

    bus_write(20'h044, 32'h0000_5678);
    bus_read(20'h044, d); checkv("OR_MASK ch1 readback", d, 32'h0000_5678);

    // Cubre ch2/ch3 aunque N_CH = 2: el store es de 4 canales a proposito.
    bus_write(20'h048, 32'h0000_9ABC);
    bus_read(20'h048, d); checkv("OR_MASK ch2 readback (N_CH=2)", d, 32'h0000_9ABC);
    bus_write(20'h04C, 32'h0000_DEF0);
    bus_read(20'h04C, d); checkv("OR_MASK ch3 readback (N_CH=2)", d, 32'h0000_DEF0);

    // El pulso se emite incluso con wdata = 0, para poder limpiar la mascara.
    newsrc_seen = 0;
    bus_write(20'h040, 32'h0);
    check("new_trg_src con wdata=0 igual pulsa", newsrc_seen[0] === 1'b1);
    bus_read(20'h040, d); checkv("OR_MASK ch0 limpiada", d, 32'h0);

    //----------------------------------------------------------------------
    // 5. SW-TRIGGER: registro propio (bit por canal) + PUENTE LEGACY
    //----------------------------------------------------------------------
    $display("-- SW trigger: registro propio y puente legacy --");
    sw_seen = 0;
    bus_write(20'h020, 32'h0000_0001);           // solo ch0
    check("TRIG_SW ch0 por registro propio", sw_seen[0] === 1'b1);
    check("TRIG_SW ch1 quieto",              sw_seen[1] === 1'b0);

    sw_seen = 0;
    bus_write(20'h020, 32'h0000_0002);           // solo ch1
    check("TRIG_SW ch1 por registro propio", sw_seen[1] === 1'b1);

    // Puente legacy: llega ya decodificado por canal desde osc_cfg (0x004).
    sw_seen = 0;
    legacy_trig_sw = 4'b0001;
    repeat (3) @(negedge clk);
    check("TRIG_SW ch0 por puente legacy", sw_seen[0] === 1'b1);
    legacy_trig_sw = 4'b0000;
    repeat (3) @(negedge clk);

    // dis_clr: registro propio (0x024, era 0x094) + puente legacy
    disclr_seen = 0;
    bus_write(20'h024, 32'h0000_0001);
    check("TRIG_DIS_CLR ch0 por registro propio", disclr_seen[0] === 1'b1);

    disclr_seen = 0;
    legacy_trig_dis_clr = 4'b0010;
    repeat (3) @(negedge clk);
    check("TRIG_DIS_CLR ch1 por puente legacy", disclr_seen[1] === 1'b1);
    legacy_trig_dis_clr = 4'b0000;
    repeat (3) @(negedge clk);

    //----------------------------------------------------------------------
    // 6. FAN-OUT POR indep_mode: sin modo independiente, ch1 sigue a ch0
    //----------------------------------------------------------------------
    $display("-- fan-out por indep_mode --");
    indep_mode = 4'b0000;
    @(negedge clk);

    sw_seen = 0;
    bus_write(20'h020, 32'h0000_0001);           // dispara solo ch0...
    check("indep_mode=0: ch1 sigue a ch0", sw_seen[1] === 1'b1);

    indep_mode = 4'b0010;                        // ch1 independiente
    @(negedge clk);
    sw_seen = 0;
    bus_write(20'h020, 32'h0000_0001);
    check("indep_mode=1: ch1 NO sigue a ch0", sw_seen[1] === 1'b0);

    //----------------------------------------------------------------------
    // 7. BARRIDO DE ACK
    //----------------------------------------------------------------------
    $display("-- barrido de ack sobre todo el slot --");
    for (i = 0; i < 20'h200; i = i + 4) bus_read(i[19:0], d);
    for (i = 20'h1000; i < 20'h1040; i = i + 4) bus_read(i[19:0], d);
    bus_read(20'h30000, d); checkv("no mapeada devuelve 0", d, 32'h0);
    bus_read(20'hFFFFC, d); checkv("tope del slot devuelve 0", d, 32'h0);
    bus_write(20'h30000, 32'hA5A5A5A5);

    checkv("sin timeouts de ack", ack_timeouts, 0);
    checkv("sin err en ningun acceso", err_seen, 0);

    $display("tb_multitrigger_cfg: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end

endmodule
