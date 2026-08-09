`timescale 1ns/1ps
//============================================================================
// tb_mca_top — integración y, sobre todo, REGRESIÓN CONTRA EL CUELGUE DE BUS.
//
// El scope tiene un bug latente que este TB existe para no repetir: ata
// bram_ack[2]/[3] = 0 para los canales no construidos, y
// multitrigger_rp_scope_cfg.sv:506-507 entonces NUNCA hace ack, así que el bus
// se cuelga hasta el timeout de 32 ciclos de rtl/axi4_slave.sv:193 y devuelve
// basura. Acá el BFM imita a sys_bus_cdc (sostiene wen/ren hasta el ack) y
// FALLA el test si el ack no llega en <= 20 ciclos, barriendo TODAS las
// direcciones: registros, huecos, aperturas, offsets fuera de rango, motores
// apagados por parámetro y direcciones no mapeadas.
//
// Se instancian DOS DUT con parámetros distintos (con y sin el motor 2D) para
// verificar que un motor no construido tampoco puede colgar el bus.
//============================================================================
module tb_mca_top;

  // Anchos chicos: el barrido de borrado dura 2^H_AW ciclos.
  localparam integer DW     = 14;
  localparam integer H_AW   = 8;    // 256 canales
  localparam integer H2_AW  = 4;    // 16 bins de amplitud
  localparam integer PSD_AW = 4;    // 16 bins de forma

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg  [2*DW-1:0] mca_dat = 0;
  reg  [1:0]      mca_val = 0;

  // --- bus hacia el DUT A (con motor 2D) ---
  reg  [31:0] a_addr = 0, a_wdata = 0;
  reg         a_wen = 0, a_ren = 0;
  wire [31:0] a_rdata;
  wire        a_err, a_ack;

  // --- bus hacia el DUT B (sin motor 2D) ---
  reg  [31:0] b_addr = 0, b_wdata = 0;
  reg         b_wen = 0, b_ren = 0;
  wire [31:0] b_rdata;
  wire        b_err, b_ack;

  mca_top #(
    .DW(DW), .EN_HIST_H(1), .H_AW(H_AW),
    .EN_HIST_H_PSD(1), .H2_AW(H2_AW), .PSD_AW(PSD_AW)
  ) dut_a (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i(mca_dat), .mca_val_i(mca_val),
    .sys_addr(a_addr), .sys_wdata(a_wdata), .sys_wen(a_wen), .sys_ren(a_ren),
    .sys_rdata(a_rdata), .sys_err(a_err), .sys_ack(a_ack)
  );

  mca_top #(
    .DW(DW), .EN_HIST_H(1), .H_AW(H_AW),
    .EN_HIST_H_PSD(0), .H2_AW(H2_AW), .PSD_AW(PSD_AW)
  ) dut_b (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i(mca_dat), .mca_val_i(mca_val),
    .sys_addr(b_addr), .sys_wdata(b_wdata), .sys_wen(b_wen), .sys_ren(b_ren),
    .sys_rdata(b_rdata), .sys_err(b_err), .sys_ack(b_ack)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1; $display("  FAIL: %s", name); end
    end
  endtask
  task automatic checkv(input string name, input integer got, input integer exp);
    begin
      if (got===exp) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  (obtenido 0x%08h, esperado 0x%08h)", name, got, exp); end
    end
  endtask

  //--------------------------------------------------------------------------
  // BFM: imita a sys_bus_cdc — sostiene wen/ren hasta ver el ack.
  // ack_timeouts cuenta las veces que el esclavo NO respondio a tiempo.
  //--------------------------------------------------------------------------
  localparam integer ACK_LIMIT = 20;
  integer ack_timeouts = 0;
  integer err_seen     = 0;

  task automatic bus_a_write(input [19:0] a, input [31:0] d);
    integer n;
    begin
      @(negedge clk); a_addr = {12'h407, a}; a_wdata = d; a_wen = 1'b1;
      n = 0;
      while (!a_ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!a_ack) begin ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK en escritura a 0x%05h", a); end
      if (a_err) err_seen = err_seen + 1;
      @(negedge clk); a_wen = 1'b0; a_addr = 0;
      while (a_ack) @(negedge clk);   // esperar a que baje el ack viejo
      @(negedge clk);
    end
  endtask

  task automatic bus_a_read(input [19:0] a, output [31:0] d);
    integer n;
    begin
      @(negedge clk); a_addr = {12'h407, a}; a_ren = 1'b1;
      n = 0;
      while (!a_ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!a_ack) begin ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK en lectura de 0x%05h", a); end
      if (a_err) err_seen = err_seen + 1;
      d = a_rdata;
      @(negedge clk); a_ren = 1'b0; a_addr = 0;
      while (a_ack) @(negedge clk);   // esperar a que baje el ack viejo
      @(negedge clk);
    end
  endtask

  task automatic bus_b_read(input [19:0] a, output [31:0] d);
    integer n;
    begin
      @(negedge clk); b_addr = {12'h407, a}; b_ren = 1'b1;
      n = 0;
      while (!b_ack && n < ACK_LIMIT) begin @(negedge clk); n = n + 1; end
      if (!b_ack) begin ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK (DUT B) en lectura de 0x%05h", a); end
      if (b_err) err_seen = err_seen + 1;
      d = b_rdata;
      @(negedge clk); b_ren = 1'b0; b_addr = 0;
      while (b_ack) @(negedge clk);   // esperar a que baje el ack viejo
      @(negedge clk);
    end
  endtask

  // Empuja una muestra a los dos DUT
  task automatic push(input integer v);
    begin
      @(negedge clk);
      mca_dat = {v[DW-1:0], v[DW-1:0]};
      mca_val = 2'b11;
    end
  endtask

  task automatic pulse_rect(input integer v, input integer n);
    integer k;
    begin for (k=0;k<n;k=k+1) push(v); push(0); end
  endtask

  task automatic settle; begin @(negedge clk); mca_val = 2'b00; repeat(20) @(negedge clk); end endtask

  reg [31:0] d, d2;
  integer i, nz;

  initial begin
    $dumpfile("tb_mca_top.vcd");
    $dumpvars(0, tb_mca_top);

    rstn = 0; repeat (5) @(negedge clk); rstn = 1; repeat (3) @(negedge clk);

    //-----------------------------------------------------------------------
    // 1) Identificación
    //-----------------------------------------------------------------------
    bus_a_read(20'h00000, d);
    checkv("magic = 'MCA1'", d, 32'h4D434131);
    bus_a_read(20'h00004, d);
    checkv("CAPS: los dos motores presentes", d[1:0], 2'b11);
    bus_a_read(20'h00008, d);
    checkv("anchos: H_AW",   d[7:0],   H_AW);
    checkv("anchos: H2_AW",  d[15:8],  H2_AW);
    checkv("anchos: PSD_AW", d[23:16], PSD_AW);

    bus_b_read(20'h00004, d);
    checkv("CAPS del DUT B: 2D ausente", d[1:0], 2'b01);

    //-----------------------------------------------------------------------
    // 2) Escritura y relectura de todos los registros RW
    //-----------------------------------------------------------------------
    bus_a_write(20'h00014, 32'd333);  bus_a_read(20'h00014, d);
    checkv("RW cfg_thr",      d[13:0], 333);
    bus_a_write(20'h00018, 32'd77);   bus_a_read(20'h00018, d);
    checkv("RW cfg_hyst",     d[13:0], 77);
    bus_a_write(20'h0001C, 32'd12);   bus_a_read(20'h0001C, d);
    checkv("RW cfg_baseline", d[13:0], 12);
    bus_a_write(20'h00020, 32'h00050031); bus_a_read(20'h00020, d);
    checkv("RW cfg_bl_ctrl (holdoff)", d[31:16], 16'h0005);
    checkv("RW cfg_bl_ctrl (k)",       d[7:4],   4'h3);
    checkv("RW cfg_bl_ctrl (auto)",    d[0],     1'b1);
    bus_a_write(20'h00028, 32'd500);  bus_a_read(20'h00028, d);
    checkv("RW cfg_maxlen",   d[15:0], 500);
    bus_a_write(20'h0002C, 32'd3);    bus_a_read(20'h0002C, d);
    checkv("RW cfg_tail_dly", d[15:0], 3);
    bus_a_write(20'h00030, 32'd10);   bus_a_read(20'h00030, d);
    checkv("RW cfg_amp_min",  d[15:0], 10);
    bus_a_write(20'h00034, 32'd9000); bus_a_read(20'h00034, d);
    checkv("RW cfg_amp_max",  d[15:0], 9000);
    bus_a_write(20'h00038, 32'h00000401); bus_a_read(20'h00038, d);
    checkv("RW cfg_amp_src",  d[0],    1'b1);
    checkv("RW cfg_q_shift",  d[12:8], 5'd4);
    bus_a_write(20'h0003C, 32'd2);    bus_a_read(20'h0003C, d);
    checkv("RW cfg_h_shift",  d[4:0],  2);
    bus_a_write(20'h00040, 32'd7);    bus_a_read(20'h00040, d);
    checkv("RW cfg_h2_shift", d[4:0],  7);
    bus_a_write(20'h00044, 32'd4);    bus_a_read(20'h00044, d);
    checkv("RW cfg_dec",      d[15:0], 4);
    bus_a_write(20'h0000C, 32'h00000101); bus_a_read(20'h0000C, d);
    checkv("RW CTRL run",     d[0],    1'b1);
    checkv("RW CTRL chan_sel",d[8],    1'b1);

    //-----------------------------------------------------------------------
    // 3) BARRIDO DE ACK — la regresión importante.
    //    Todas las direcciones tienen que ack-ear y sys_err tiene que ser 0.
    //-----------------------------------------------------------------------
    ack_timeouts = 0; err_seen = 0;

    for (i = 0; i < 32'h100; i = i + 4)         // registros y huecos
      bus_a_read(i[19:0], d);
    for (i = 32'h100; i < 32'h200; i = i + 4)   // zona no mapeada
      bus_a_read(i[19:0], d);
    for (i = 0; i < 32'h400; i = i + 4)         // apertura 1D, dentro y fuera
      bus_a_read(20'h10000 + i[19:0], d);
    for (i = 0; i < 32'h400; i = i + 4)         // apertura 2D
      bus_a_read(20'h20000 + i[19:0], d);
    bus_a_read(20'h30000, d);                   // apertura inexistente
    bus_a_read(20'h40000, d);
    bus_a_read(20'h7FFFC, d);                   // extremo del slot
    bus_a_read(20'h1FFFC, d);                   // final de la apertura 1D
    bus_a_read(20'h2FFFC, d);

    checkv("barrido de ack: ningun timeout", ack_timeouts, 0);
    checkv("barrido de ack: sys_err siempre 0", err_seen, 0);

    //-----------------------------------------------------------------------
    // 4) El mismo barrido en el DUT B, con el motor 2D AUSENTE.
    //    Su apertura 0x20000 igual tiene que ack-ear y devolver 0.
    //-----------------------------------------------------------------------
    ack_timeouts = 0; err_seen = 0; nz = 0;
    for (i = 0; i < 32'h400; i = i + 4) begin
      bus_b_read(20'h20000 + i[19:0], d);
      if (d !== 32'h0) nz = nz + 1;
    end
    bus_b_read(20'h30000, d);
    bus_b_read(20'h7FFFC, d);
    checkv("motor 2D ausente: sin timeouts de ack", ack_timeouts, 0);
    checkv("motor 2D ausente: devuelve 0",          nz, 0);
    checkv("motor 2D ausente: sys_err 0",           err_seen, 0);

    //-----------------------------------------------------------------------
    // 5) Lectura DURANTE el barrido de borrado.
    //    Un barrido dura 2^H_AW ciclos, muchísimo más que el timeout de 32
    //    ciclos del axi4_slave: si frenara el ack, el bus se colgaria.
    //-----------------------------------------------------------------------
    ack_timeouts = 0;
    bus_a_write(20'h0000C, 32'h00000003);   // run + clear_all
    bus_a_read(20'h00010, d);
    check("barrido en curso (clear_busy)", d[0] === 1'b1);
    for (i = 0; i < 20; i = i + 1) begin    // leer mientras barre
      bus_a_read(20'h00050, d);
      bus_a_read(20'h10000 + i[19:0]*4, d);
    end
    checkv("lecturas durante el borrado: sin timeouts", ack_timeouts, 0);
    repeat (2*(1<<H_AW)) @(negedge clk);
    bus_a_read(20'h00010, d);
    check("clear_busy baja al terminar", d[0] === 1'b0);

    //-----------------------------------------------------------------------
    // 6) CAMINO DE DATOS COMPLETO: inyectar pulsos y ver el bin correcto.
    //    thr=100, hyst=50, base=0, amp_src=pico, h_shift=0, dec=1
    //-----------------------------------------------------------------------
    bus_a_write(20'h0000C, 32'h00000000);   // parar
    bus_a_write(20'h00014, 32'd50);         // thr
    bus_a_write(20'h00018, 32'd20);         // hyst
    bus_a_write(20'h0001C, 32'd0);          // baseline fija
    bus_a_write(20'h00020, 32'd0);          // sin base automatica
    bus_a_write(20'h00028, 32'd1000);       // maxlen
    bus_a_write(20'h0002C, 32'd1);          // tail_dly
    bus_a_write(20'h00030, 32'd0);          // amp_min
    bus_a_write(20'h00034, 32'hFFFF);       // amp_max
    bus_a_write(20'h00038, 32'h0);          // amp_src = pico
    bus_a_write(20'h0003C, 32'd0);          // h_shift = 0
    bus_a_write(20'h00040, 32'd0);          // h2_shift = 0
    bus_a_write(20'h00044, 32'd1);          // sin decimacion
    bus_a_write(20'h0000C, 32'h00000003);   // run + clear
    repeat (2*(1<<H_AW)) @(negedge clk);

    // El Schmitt arranca DESARMADO: hay que pasar por debajo de thr-hyst
    // antes del primer disparo, si no el primer pulso no se detecta.
    push(0); push(0); push(0); settle;

    // 3 pulsos de amplitud 200 (thr=50) -> bin 200 del espectro.
    // La amplitud tiene que superar el umbral Y entrar en 2^H_AW=256 bins.
    pulse_rect(200, 20); settle;
    pulse_rect(200, 20); settle;
    pulse_rect(200, 20); settle;

    bus_a_read(20'h00050, d); checkv("cnt_total = 3",    d, 3);
    bus_a_read(20'h00054, d); checkv("cnt_accepted = 3", d, 3);
    // Todos los bins fuera del 200 tienen que estar en cero: si la lectura
    // no retuviera el dato, todos devolverian el bin del ultimo evento.
    nz = 0;
    for (i=0; i<(1<<H_AW); i=i+1) begin
      bus_a_read(20'h10000 + i[19:0]*4, d2);
      if (i != 200 && d2 !== 32'h0) nz = nz + 1;
    end
    checkv("espectro: todos los demas bins en 0", nz, 0);
    bus_a_read(20'h10000 + 200*4, d);
    checkv("espectro: bin 200 acumulo 3 cuentas", d, 3);
    bus_a_read(20'h10000 + 201*4, d);
    checkv("espectro: bin vecino en 0", d, 0);

    // El mapa 2D: amplitud 40 con h2_shift=0 satura el eje (H2_AW=4 -> 15)
    bus_a_read(20'h00080, d);
    checkv("ultimo evento: amplitud 200", d[15:0], 200);

    // Relojes
    bus_a_read(20'h00068, d);  bus_a_read(20'h0006C, d2);
    check("realtime avanza", d != 0);
    bus_a_read(20'h00070, d);
    check("livetime avanza", d != 0);

    //-----------------------------------------------------------------------
    // 7) El borrado deja el espectro y los contadores en cero
    //-----------------------------------------------------------------------
    bus_a_write(20'h0000C, 32'h00000003);
    repeat (2*(1<<H_AW)) @(negedge clk);
    bus_a_read(20'h10000 + 200*4, d); checkv("tras borrar: bin 200 en 0", d, 0);
    bus_a_read(20'h00050, d);        checkv("tras borrar: cnt_total en 0", d, 0);

    $display("---------------------------------------------");
    $display("tb_mca_top: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #20000000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
