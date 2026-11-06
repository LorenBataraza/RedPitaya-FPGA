`timescale 1ns/1ps
//============================================================================
// tb_mca_top — integración y, sobre todo, REGRESIÓN CONTRA EL CUELGUE DE BUS.
//
// El scope tiene un bug latente que este TB existe para no repetir: ata
// bram_ack[2]/[3] = 0 para los canales no construidos, y
// mt_rp_scope_cfg.sv:506-507 entonces NUNCA hace ack, así que el bus
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
  localparam integer AMP_W  = 16;
  // CANAL ESPERADO PARA UNA AMPLITUD DE PICO.
  //
  // Cambio de semantica del eje: antes era `amp >> h_shift` saturado, o sea que
  // con h_shift=0 un pulso de 200 cuentas caia en el canal 200. Ahora la feature
  // se NORMALIZA (el pico se alinea a la izquierda de AMP_W bits) y el eje cubre
  // siempre el FONDO DE ESCALA completo, con el zoom para acercarse. Entonces:
  //
  //     bin = (pico << (AMP_W-DW)) >> (AMP_W-H_AW)
  //
  // Se gana que el eje siempre abarca todo el rango de entrada y que los niveles
  // de zoom quedan exactamente anidados; se pierde el "1 canal = 1 cuenta" que
  // daba h_shift=0, que el zoom recupera con mas control.
  function automatic integer canal_de(input integer pico);
    canal_de = (pico << (AMP_W-DW)) >> (AMP_W-H_AW);
  endfunction
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

  reg veto = 1'b0;                 // veto externo, solo en dut_a
  reg trig = 1'b0;                 // trigger externo (Fase 2), solo en dut_a

  mca_top #(
    .DW(DW), .EN_HIST_H(1), .H_AW(H_AW),
    .EN_HIST_H_PSD(1), .H2_AW(H2_AW), .PSD_AW(PSD_AW)
  ) dut_a (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i(mca_dat), .mca_val_i(mca_val), .veto_i(veto), .trig_i(trig),
    .sys_addr(a_addr), .sys_wdata(a_wdata), .sys_wen(a_wen), .sys_ren(a_ren),
    .sys_rdata(a_rdata), .sys_err(a_err), .sys_ack(a_ack)
  );

  mca_top #(
    .DW(DW), .EN_HIST_H(1), .H_AW(H_AW),
    .EN_HIST_H_PSD(0), .H2_AW(H2_AW), .PSD_AW(PSD_AW)
  ) dut_b (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i(mca_dat), .mca_val_i(mca_val), .veto_i(1'b0), .trig_i(1'b0),
    .sys_addr(b_addr), .sys_wdata(b_wdata), .sys_wen(b_wen), .sys_ren(b_ren),
    .sys_rdata(b_rdata), .sys_err(b_err), .sys_ack(b_ack)
  );

  // Engancha las assertions de sva/mca_top_sva.sv a las dos instancias.
  //
  // EL BIND VA ACA, DENTRO DEL TESTBENCH, Y NO EN UN ARCHIVO SUELTO. Un `bind`
  // en el scope de la unidad de compilacion NO SE ELABORA: Questa avisa con
  // (vlog-2650) "Please use -cuname to ensure that 'bind' gets elaborated",
  // despues sigue adelante, el TB pasa, y las propiedades NO EXISTEN. Asi
  // estaba sva/bind_mca.sv, y no se habia notado porque el archivo de
  // propiedades estaba vacio; se descubrio con `find instances -recursive
  // u_sva`, que no encontraba nada con 21 propiedades escritas.
  //
  // La via de -cuname tambien funciona pero hay que pasar la unidad como top
  // adicional de vsim, lo que obliga a suprimir el error de los TB que no
  // instancian el modulo y choca con "'u_sva' already declared" cuando el DUT
  // es el propio objetivo del bind. Un bind dentro del modulo que instancia el
  // DUT se elabora con el, sin flags y sin supresiones, y ademas deja a la
  // vista en el testbench que las assertions estan activas.
  bind mca_top mca_top_sva #(.N_ACC(N_ACC), .N_FORMAS(N_FORMAS), .AMP_W(AMP_W), .NFEAT(NFEAT)) u_sva (.*);

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

  // UN PULSO CON SU DISPARO. Sin Schmitt interno, lo que abre la ventana es
  // trig_i, y en el top la muestra tarda LAT_TOP ciclos en llegar al extractor
  // (registro de entrada + registro de salida de la linea de retardo, con
  // cfg_pre_dly = 0). El trigger sube con la muestra LAT_TOP del pulso, que es
  // cuando el pie llega a la ventana: asi la ventana arranca justo en el pie,
  // como con el multitrigger y la linea de retardo bien ajustada.
  localparam integer LAT_TOP = 2;
  task automatic pulse_trig(input integer v, input integer n);
    integer k;
    begin
      for (k=0;k<n;k=k+1) begin
        push(v);
        trig = (k == LAT_TOP);
      end
      push(0); trig = 1'b0;
    end
  endtask

  task automatic settle; begin @(negedge clk); mca_val = 2'b00; repeat(20) @(negedge clk); end endtask

  // Los eventos de dut_a, con F_TRAP, F_FORMA y el pico, para la seccion del
  // trapecio
  int ev_trap[$], ev_pico[$], ev_forma[$];
  always @(posedge clk) if (dut_a.ev_valid) begin
    ev_trap.push_back(dut_a.ev_feat[9*AMP_W +: AMP_W]);
    ev_forma.push_back(dut_a.ev_feat[10*AMP_W +: AMP_W]);
    ev_pico.push_back(dut_a.ev_feat[0 +: AMP_W] >> (AMP_W - DW));
  end

  // El clr del banco: sube con la escritura de k, m o M de cualquier forma
  bit vio_clr = 0;
  always @(posedge clk) if (rstn && dut_a.trap_clr) vio_clr = 1;

  // Dos pulsos exponenciales (subida de una muestra, cola tau) separados dt,
  // cada uno con su disparo como lo da pulse_trig. a2 = 0: un pulso solo.
  task automatic par_exp(input real a1, input real a2, input integer dt, input real tau);
    integer t; real v;
    begin
      for (t = 0; t < dt + 450; t = t + 1) begin
        v = a1 * $exp(-t / tau);
        if (a2 != 0.0 && t >= dt) v = v + a2 * $exp(-(t - dt) / tau);
        push($rtoi(v + 0.5));
        trig = (t == LAT_TOP) || (a2 != 0.0 && t == dt + LAT_TOP);
      end
      trig = 1'b0;
      settle;
    end
  endtask

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
    checkv("magic = 'MCA2'", d, 32'h4D434132);
    bus_a_read(20'h00004, d);
    checkv("CAPS: los dos motores presentes", d[1:0], 2'b11);
    bus_a_read(20'h00008, d);
    checkv("anchos: H_AW",   d[7:0],   H_AW);
    checkv("anchos: H2_AW",  d[15:8],  H2_AW);
    checkv("anchos: PSD_AW", d[23:16], PSD_AW);

    bus_b_read(20'h00004, d);
    checkv("CAPS del DUT B: 2D ausente", d[1:0], 2'b01);
    bus_a_read(20'h00004, d);
    checkv("CAPS: trapecio presente (bit 2)", d[2], 1'b1);

    // valores de reset del trapecio: k = 64, m = 32, M = 0, off = 72, lw = 4,
    // sh = 7, y la ventana entra en la compuerta de 384 (bit 31)
    bus_a_read(20'h00128, d);
    checkv("reset: trapecio k y m", d, {16'd32, 16'd64});
    bus_a_read(20'h0012C, d);
    checkv("reset: trapecio M", d, 0);
    bus_a_read(20'h00130, d);
    checkv("reset: ventana de la meseta (ok, sh, lw, off)", d, {1'b1, 1'b0, 6'd7, 5'd0, 3'd4, 16'd72});

    // el banco: cuatro formas, una en uso, umbrales en cero; la forma 0 es la
    // de 0x128/0x130 y las otras, la mitad de la anterior
    bus_a_read(20'h00134, d);
    checkv("reset: banco (umbr_ok, N_FORMAS = 4, n_formas = 1)", d, {1'b1, 20'h0, 3'd4, 5'd0, 3'd1});
    bus_a_read(20'h00180, d); checkv("reset: FORMA_KM 0 = 0x128", d, {16'd32, 16'd64});
    bus_a_read(20'h00184, d); checkv("reset: FORMA_MED 0 = 0x130", d, {1'b1, 1'b0, 6'd7, 5'd0, 3'd4, 16'd72});
    for (i = 1; i < 4; i++) begin
      bus_a_read(20'h00180 + 16*i, d);
      checkv($sformatf("reset: FORMA_KM %0d", i), d, {16'd32 >> i, 16'd64 >> i});
      bus_a_read(20'h00184 + 16*i, d);
      checkv($sformatf("reset: FORMA_MED %0d", i), d,
             {1'b1, 1'b0, 6'd7 - i[5:0], 5'd0, 3'd4 - i[2:0],
              16'd4 + (16'd64 >> i) + ((16'd32 >> i) - (16'd16 >> i)) / 16'd2});
    end
    for (i = 0; i < 4; i++) begin
      bus_a_read(20'h00188 + 16*i, d);
      checkv($sformatf("reset: FORMA_UMBR %0d en cero", i), d, 0);
    end

    //-----------------------------------------------------------------------
    // 2) Escritura y relectura de todos los registros RW
    //-----------------------------------------------------------------------
    bus_a_write(20'h0001C, 32'd12);   bus_a_read(20'h0001C, d);
    checkv("RW cfg_baseline", d[13:0], 12);
    bus_a_write(20'h00020, 32'h00050031); bus_a_read(20'h00020, d);
    checkv("RW cfg_bl_ctrl (holdoff)", d[31:16], 16'h0005);
    checkv("RW cfg_bl_ctrl (k)",       d[7:4],   4'h3);
    checkv("RW cfg_bl_ctrl (auto)",    d[0],     1'b1);
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
    bus_a_write(20'h0004C, {16'd300, 16'd30}); bus_a_read(20'h0004C, d);
    checkv("RW compuerta larga", d[31:16], 300);
    checkv("RW compuerta corta", d[15:0],  30);
    bus_a_write(20'h00120, 32'd3);    bus_a_read(20'h00120, d);
    checkv("RW cfg_n_acc",    d[2:0],  3);
    bus_a_write(20'h00124, 32'd45);   bus_a_read(20'h00124, d);
    checkv("RW cfg_pre_dly",  d[6:0],  45);
    bus_a_read(20'h0011C, d);
    checkv("N_ACC publicado", d, 4);
    bus_a_write(20'h00128, {16'd200, 16'd700}); bus_a_read(20'h00128, d);
    checkv("RW trapecio k", d[9:0],   700);
    checkv("RW trapecio m", d[25:16], 200);
    bus_a_write(20'h0012C, 32'hFFF_FFFFF); bus_a_read(20'h0012C, d);
    checkv("RW trapecio M (20 bits)", d, 32'h000F_FFFF);
    // con la compuerta larga en 300: 100 + 8 + 16 entra, 290 + 8 + 16 no
    bus_a_write(20'h00130, {2'b0, 6'd9, 5'd0, 3'd4, 16'd100}); bus_a_read(20'h00130, d);
    checkv("RW meseta off", d[15:0], 100);
    checkv("RW meseta lw",  d[18:16], 4);
    checkv("RW meseta sh",  d[29:24], 9);
    repeat (3) @(negedge clk); bus_a_read(20'h00130, d);
    checkv("la ventana de la meseta entra en la compuerta", d[31], 1'b1);
    bus_a_write(20'h00130, {2'b0, 6'd9, 5'd0, 3'd4, 16'd290});
    repeat (3) @(negedge clk); bus_a_read(20'h00130, d);
    checkv("la ventana de la meseta NO entra en la compuerta", d[31], 1'b0);
    bus_a_write(20'h00128, {16'd32, 16'd64});
    bus_a_write(20'h0012C, 32'd0);
    bus_a_write(20'h00130, {2'b0, 6'd7, 5'd0, 3'd4, 16'd72});

    // el banco: escritura y relectura de los tres registros de cada forma
    for (i = 0; i < 4; i++) begin
      bus_a_write(20'h00180 + 16*i, {16'd100 + i[15:0], 16'd200 + i[15:0]});
      bus_a_read (20'h00180 + 16*i, d);
      checkv($sformatf("RW FORMA_KM %0d", i), d, {16'd100 + i[15:0], 16'd200 + i[15:0]});
      bus_a_write(20'h00184 + 16*i, {2'b0, 6'd10 + i[5:0], 5'd0, i[2:0], 16'd50 + i[15:0]});
      bus_a_read (20'h00184 + 16*i, d);
      checkv($sformatf("RW FORMA_MED %0d", i), d[30:0], {1'b0, 6'd10 + i[5:0], 5'd0, i[2:0], 16'd50 + i[15:0]});
      bus_a_write(20'h00188 + 16*i, {16'd300 + i[15:0], 16'd400 + i[15:0]});
      bus_a_read (20'h00188 + 16*i, d);
      checkv($sformatf("RW FORMA_UMBR %0d", i), d, {16'd300 + i[15:0], 16'd400 + i[15:0]});
    end
    bus_a_read(20'h00128, d); checkv("alias: 0x128 es FORMA_KM 0", d, {16'd100, 16'd200});
    bus_a_read(20'h00130, d); checkv("alias: 0x130 es FORMA_MED 0", d[15:0], 50);
    bus_a_write(20'h00128, {16'd7, 16'd9});
    bus_a_read(20'h00180, d); checkv("alias: escribir 0x128 escribe FORMA_KM 0", d, {16'd7, 16'd9});
    bus_a_read(20'h0018C, d); checkv("reservado: +C de la forma 0 lee 0", d, 0);
    bus_a_read(20'h001C0, d); checkv("reservado: 0x1C0 lee 0", d, 0);
    // el clr: con k y m de cualquier forma, no con la ventana ni los umbrales
    repeat (3) @(negedge clk); vio_clr = 0;
    bus_a_write(20'h001A4, {2'b0, 6'd5, 5'd0, 3'd1, 16'd20});
    bus_a_write(20'h001A8, 32'h0001_0002);
    repeat (3) @(negedge clk);
    checkv("la ventana y los umbrales no pulsan clr", vio_clr, 0);
    bus_a_write(20'h001A0, {16'd3, 16'd4});
    repeat (3) @(negedge clk);
    checkv("FORMA_KM 2 pulsa clr", vio_clr, 1);
    // n_formas y umbr_ok, con la compuerta larga en 300: despues de la forma 0
    // es 300 (entra) y el de la 1 es 301 (no entra)
    bus_a_read(20'h0004C, d2);
    bus_a_write(20'h0004C, {16'd300, d2[15:0]});
    bus_a_write(20'h00134, 32'd1);
    repeat (3) @(negedge clk); bus_a_read(20'h00134, d);
    checkv("n_formas = 1: el despues de la forma 0 entra (umbr_ok)", {d[31], d[2:0]}, {1'b1, 3'd1});
    bus_a_write(20'h00134, 32'd2);
    repeat (3) @(negedge clk); bus_a_read(20'h00134, d);
    checkv("n_formas = 2: el de la forma 1 no entra (umbr_ok = 0)", {d[31], d[2:0]}, {1'b0, 3'd2});
    bus_a_write(20'h00134, 32'd7);
    bus_a_read(20'h00134, d); checkv("RW n_formas (3 bits)", d[2:0], 7);
    checkv("N_FORMAS es de solo lectura", d[10:8], 4);
    // de vuelta al reset
    bus_a_write(20'h0004C, d2);
    for (i = 0; i < 4; i++) begin
      bus_a_write(20'h00180 + 16*i, {16'd32 >> i, 16'd64 >> i});
      bus_a_write(20'h00184 + 16*i, {2'b0, 6'd7 - i[5:0], 5'd0, 3'd4 - i[2:0],
                                     (i == 0) ? 16'd72 : 16'd4 + (16'd64 >> i) + ((16'd32 >> i) - (16'd16 >> i)) / 16'd2});
      bus_a_write(20'h00188 + 16*i, 32'd0);
    end
    bus_a_write(20'h00134, 32'd1);
    bus_a_write(20'h0000C, 32'h00000101); bus_a_read(20'h0000C, d);
    checkv("RW CTRL run",     d[0],    1'b1);
    checkv("RW CTRL chan_sel",d[8],    1'b1);

    // Lo que dejaron libre el Schmitt, la histeresis, el re-armado y el modo de
    // publicacion: se escribe sin efecto y se lee en cero.
    nz = 0;
    for (i = 0; i < 10; i = i + 1) begin
      reg [19:0] rsv;
      case (i)
        0: rsv = 20'h00014; 1: rsv = 20'h00018; 2: rsv = 20'h00028;
        3: rsv = 20'h0002C; 4: rsv = 20'h00048; 5: rsv = 20'h00104;
        6: rsv = 20'h00108; 7: rsv = 20'h000D8; 8: rsv = 20'h000F0;
        default: rsv = 20'h00114;
      endcase
      bus_a_write(rsv, 32'hFFFF_FFFF); bus_a_read(rsv, d);
      if (d !== 32'h0) nz = nz + 1;
    end
    checkv("reservados: se leen en cero", nz, 0);
    bus_a_write(20'h0000C, 32'h00000000);
    bus_a_write(20'h00120, 32'd1);
    bus_a_write(20'h00124, 32'd0);
    bus_a_write(20'h00020, 32'h00000060);

    //-----------------------------------------------------------------------
    // 3) BARRIDO DE ACK — la regresión importante.
    //    Todas las direcciones tienen que ack-ear y sys_err tiene que ser 0.
    //-----------------------------------------------------------------------
    ack_timeouts = 0; err_seen = 0;

    for (i = 0; i < 32'h100; i = i + 4)         // registros y huecos
      bus_a_read(i[19:0], d);
    for (i = 32'h100; i < 32'h200; i = i + 4)   // las ranuras, la ocupacion y lo no mapeado
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
    //    El pulso entra por mca_dat_i y su disparo por trig_i, como en la placa.
    //-----------------------------------------------------------------------
    bus_a_write(20'h0000C, 32'h00000000);   // parar
    bus_a_write(20'h0001C, 32'd0);          // baseline fija
    bus_a_write(20'h00020, 32'd0);          // sin base automatica
    bus_a_write(20'h0004C, {16'd20, 16'd4});// compuerta de 20, cola desde 4
    bus_a_write(20'h00030, 32'd0);          // amp_min
    bus_a_write(20'h00034, 32'hFFFF);       // amp_max
    bus_a_write(20'h00038, 32'h0);          // amp_src = pico
    bus_a_write(20'h00044, 32'd1);          // sin decimacion
    bus_a_write(20'h0000C, 32'h00000003);   // run + clear
    repeat (2*(1<<H_AW)) @(negedge clk);

    // 3 pulsos de amplitud 200 -> canal_de(200) del espectro.
    pulse_trig(200, 20); settle;
    pulse_trig(200, 20); settle;
    pulse_trig(200, 20); settle;

    bus_a_read(20'h00050, d); checkv("cnt_total = 3",    d, 3);
    bus_a_read(20'h00054, d); checkv("cnt_accepted = 3", d, 3);
    nz = 0;
    for (i = 0; i < (1<<H_AW); i = i + 1) begin
      bus_a_read(20'h10000 + i[19:0]*4, d);
      if (i != canal_de(200) && d != 0) nz = nz + 1;
    end
    checkv("espectro: todos los demas bins en 0", nz, 0);
    bus_a_read(20'h10000 + canal_de(200)*4, d);
    checkv("espectro: el canal del pico acumulo 3 cuentas", d, 3);
    bus_a_read(20'h10000 + (canal_de(200)+1)*4, d);
    checkv("espectro: bin vecino en 0", d, 0);
    bus_a_read(20'h00080, d);
    checkv("ultimo evento: amplitud 200", d[15:0], 200);
    bus_a_read(20'h00068, d);
    check("realtime avanza", d != 0);
    bus_a_read(20'h00070, d);
    check("livetime avanza", d != 0);
    bus_a_read(20'h000C0, d);
    checkv("vetotime en 0 sin veto", d, 0);

    // Un pulso SIN disparo no abre nada: el Schmitt interno ya no existe.
    pulse_rect(200, 20); settle;
    bus_a_read(20'h00050, d); checkv("sin disparo: cnt_total sigue en 3", d, 3);

    //-----------------------------------------------------------------------
    // 6b) VETO externo: el disparo bajo veto no abre, y el tiempo va a vetotime
    //-----------------------------------------------------------------------
    veto = 1'b1;
    bus_a_read(20'h00010, d);
    check("estado: bit 3 = vetoed", d[3] == 1'b1);
    bus_a_read(20'h00070, d);
    pulse_trig(200, 20); settle;
    pulse_trig(200, 20); settle;
    bus_a_read(20'h00070, d2);
    checkv("livetime NO avanza bajo veto", d2, d);
    bus_a_read(20'h00050, d); checkv("bajo veto: cnt_total sigue en 3", d, 3);
    bus_a_read(20'h000F8, d); checkv("bajo veto: dos arribos vetados", d, 2);
    bus_a_read(20'h000C0, d); check("vetotime avanza", d != 0);
    veto = 1'b0;
    bus_a_read(20'h00010, d);
    check("estado: vetoed vuelve a 0", d[3] == 1'b0);
    pulse_trig(200, 20); settle;
    bus_a_read(20'h00050, d); checkv("tras el veto: cnt_total = 4", d, 4);

    //-----------------------------------------------------------------------
    // 7) El borrado deja el espectro y los contadores en cero
    //-----------------------------------------------------------------------
    bus_a_write(20'h0000C, 32'h00000003);
    repeat (2*(1<<H_AW)) @(negedge clk);
    bus_a_read(20'h10000 + canal_de(200)*4, d); checkv("tras borrar: el canal del pico en 0", d, 0);
    bus_a_read(20'h00050, d);        checkv("tras borrar: cnt_total en 0", d, 0);

    //-----------------------------------------------------------------------
    // 8) EL TESELADO DEL TIEMPO MUERTO, visto por el BUS, con UNA ranura
    //
    //    Las assertions lo verifican ciclo a ciclo adentro; esto verifica que lo
    //    que lee el software cierra igual. Con una ranura el tiempo muerto es la
    //    ventana (t_win) mas la espera de los divisores (t_div), y deadtime
    //    (0x078, la ocupacion) coincide con su suma.
    //-----------------------------------------------------------------------
    bus_a_write(20'h0000C, 32'h00000001);      // run
    bus_a_write(20'h0004C, {16'd10, 16'd4});   // larga = 10, corta = 4
    pulse_trig(200, 30);
    for (i = 0; i < 40; i = i + 1) push(0);
    settle;
    bus_a_write(20'h0000C, 32'h00000000);      // run = 0: congela los relojes
    begin
      reg [31:0] rt_lo, rt_hi, lt_lo, dt_lo, vt_lo, tw_lo, td_lo, suma;
      reg [31:0] cruces, open_c, l_veto, per, mx, ext, o0, o1;
      bus_a_read(20'h00068, rt_lo); bus_a_read(20'h0006C, rt_hi);
      bus_a_read(20'h00070, lt_lo); bus_a_read(20'h00078, dt_lo);
      bus_a_read(20'h000C0, vt_lo); bus_a_read(20'h000C8, tw_lo);
      bus_a_read(20'h000D0, td_lo);
      suma = vt_lo + tw_lo + td_lo + lt_lo;
      checkv("teselado: la palabra alta de realtime es 0", rt_hi, 0);
      check ("teselado: realtime avanzo", rt_lo > 0);
      checkv("teselado: realtime = veto + win + div + live", rt_lo, suma);
      checkv("una ranura: deadtime (0x078) = t_win + t_div", dt_lo, tw_lo + td_lo);
      // La ranura queda ocupada midiendo gate_long + 1 ciclos: el ciclo
      // siguiente a la decision ya esta reservada, y procesa cada muestra un
      // ciclo despues de recibirla (la muestra se registra antes de repartirse
      // a las ranuras). Con la ventana unica de antes eran gate_long.
      checkv("una ranura: la ventana ocupa la compuerta + 1", tw_lo, 11);
      checkv("una ranura: la espera de los divisores", td_lo, 18);
      bus_a_read(20'h00140, o0); bus_a_read(20'h00148, o1);
      checkv("ocupacion: t_ocup[0] + t_ocup[1] = realtime", o0 + o1, rt_lo);
      checkv("ocupacion: t_ocup[1] = deadtime", o1, dt_lo);

      bus_a_read(20'h000EC, cruces); bus_a_read(20'h000B4, open_c);
      bus_a_read(20'h000F8, l_veto);
      checkv("arribos: uno", cruces, 1);
      checkv("arribos: y abrio ventana", open_c, 1);
      checkv("arribos: ninguno bajo veto", l_veto, 0);

      bus_a_read(20'h000E0, per); bus_a_read(20'h000E4, mx); bus_a_read(20'h000E8, ext);
      checkv("periodo: uno", per, 1);
      checkv("periodo: dura la ventana mas la publicacion", mx, tw_lo + td_lo);
      checkv("periodo: sin arribos adentro", ext, 0);
    end
    bus_a_read(20'h001FC, d);
    checkv("bus: direccion no mapeada devuelve 0", d, 0);

    //-----------------------------------------------------------------------
    // 9) VARIAS RANURAS, por el bus
    //
    //    Una rafaga de disparos con compuerta larga: con N ranuras se abren N
    //    ventanas a la vez, el resto se pierde como lost_active, y la cola de
    //    publicacion se llena cuando cierran juntas. Engancha las propiedades de
    //    cobertura de las ranuras, que sin esto quedan en CERO al nivel del top.
    //-----------------------------------------------------------------------
    begin
      reg [31:0] d9, rt, vt, tw, td, lt, cr, op, la, lv, o_sum;
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
      bus_a_write(20'h00120, 32'd4);           // cuatro ranuras
      bus_a_write(20'h0004C, {16'd40, 16'd4}); // larga = 40
      bus_a_write(20'h0000C, 32'h00000001);    // run

      // seis disparos separados 5 muestras: abren cuatro, se pierden dos
      for (i = 0; i < 30; i = i + 1) begin
        push(300);
        trig = ((i % 5) == 0);
      end
      trig = 1'b0;
      for (i = 0; i < 20; i = i + 1) push(300);
      bus_a_read(20'h00010, d9);
      for (i = 0; i < 200; i = i + 1) push(0);
      settle;
      bus_a_write(20'h0000C, 32'h00000000);    // stop

      bus_a_read(20'h00110, d9); checkv("ranuras: cuatro ventanas abiertas", d9, 4);
      bus_a_read(20'h000F4, la); checkv("ranuras: dos perdidas con todas midiendo", la, 2);
      bus_a_read(20'h00054, d9); checkv("ranuras: cuatro eventos publicados", d9, 4);
      bus_a_read(20'h0010C, d9);
      // la cola cuenta las ranuras CERRADAS, incluida la que se esta publicando
      checkv("ranuras: la cola llego a las cuatro cerradas", d9[15:8], 4);
      bus_a_read(20'h000EC, cr); bus_a_read(20'h000B4, op); bus_a_read(20'h000F8, lv);
      checkv("ranuras: atribucion (cross = open + active + veto + busy)", cr, op + la + lv);

      bus_a_read(20'h00068, rt); bus_a_read(20'h000C0, vt);
      bus_a_read(20'h000C8, tw); bus_a_read(20'h000D0, td); bus_a_read(20'h00070, lt);
      checkv("ranuras: el teselado sigue cerrando", rt, vt + tw + td + lt);
      check ("ranuras: hubo tiempo con las cuatro ocupadas", tw > 0);
      o_sum = 0;
      for (i = 0; i <= 4; i = i + 1) begin
        bus_a_read(20'h00140 + 8*i, d9); o_sum = o_sum + d9;
      end
      checkv("ranuras: la ocupacion tesela el tiempo sin veto", o_sum, rt - vt);
      bus_a_read(20'h00160, d9);
      check ("ranuras: t_ocup[4] > 0", d9 > 0);

      // (b) el disparo SOSTENIDO 5 muestras abre UNA ventana, no cinco
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
      bus_a_write(20'h0000C, 32'h00000001);    // run
      trig = 1'b1;
      push(200); push(200); push(200); push(200); push(200);
      trig = 1'b0;
      for (i = 0; i < 60; i = i + 1) push(200);
      push(0); push(0); push(0);
      settle;
      bus_a_read(20'h00118, d9); checkv("disparo sostenido: un solo flanco contado", d9, 1);
      bus_a_read(20'h00110, d9); checkv("disparo sostenido: UNA sola ventana", d9, 1);

      // (c) la linea de retardo: con cfg_pre_dly = 8 la muestra llega 8 ciclos
      //     mas tarde, asi que un disparo 8 muestras despues del pie sigue
      //     abriendo en el pie y el evento mide la amplitud entera.
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
      bus_a_write(20'h00120, 32'd1);
      bus_a_write(20'h00124, 32'd8);
      bus_a_write(20'h0004C, {16'd6, 16'd2});  // compuerta CORTA: 6 muestras
      bus_a_write(20'h0000C, 32'h00000001);    // run
      push(0); push(0);
      for (i = 0; i < 12; i = i + 1) begin
        push((i < 3) ? 500 : 50);              // 3 muestras altas y una cola baja
        trig = (i == LAT_TOP + 8);
      end
      trig = 1'b0;
      for (i = 0; i < 40; i = i + 1) push(0);
      settle;
      bus_a_read(20'h00080, d9);
      checkv("retardo: la ventana abrio en el pie (pico 500)", d9[15:0], 500);
      bus_a_write(20'h00124, 32'd0);

      bus_a_write(20'h0000C, 32'h00000000);    // stop
      bus_a_write(20'h00120, 32'd1);
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
    end

    //-----------------------------------------------------------------------
    // 10) EL TRAPECIO: el pulso que monta sobre la cola de otro mide limpio
    //
    //    Pulsos exponenciales con tau = 50 y M exacto (Mq = 16 M = 792): cada
    //    uno sale como un trapecio de k = 32, m = 16 que vuelve a cero en 80
    //    muestras. La ventana [36, 44) de la meseta, desde el pie. Con dos
    //    ranuras, un segundo pulso a dt >= k + m mide su propia altura aunque
    //    llegue sobre 30 % de cola del primero, que es lo que F_PEAK no puede.
    //-----------------------------------------------------------------------
    begin
      integer t_solo, t1, t2, p2;
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
      bus_a_write(20'h00020, 32'h00000000);    // base fija en 0
      bus_a_write(20'h0001C, 32'd0);
      bus_a_write(20'h00120, 32'd2);
      bus_a_write(20'h00124, 32'd0);
      bus_a_write(20'h0004C, {16'd200, 16'd20});
      bus_a_write(20'h00128, {16'd16, 16'd32});
      bus_a_write(20'h0012C, 32'd792);
      bus_a_write(20'h00130, {2'b0, 6'd12, 5'd0, 3'd3, 16'd36});
      bus_a_write(20'h00090, {20'h0, 4'd2, 4'd0, 4'd9});   // 1D = F_TRAP
      bus_a_write(20'h0000C, 32'h00000001);    // run
      repeat (40) push(0);

      ev_trap.delete(); ev_pico.delete();
      par_exp(1000.0, 0.0, 0, 50.0);
      checkv("trapecio: un evento", ev_trap.size(), 1);
      t_solo = ev_trap[0];
      // altura 16*A*k*(1+M)/2^sh = 16*1000*32*50.5/4096 = 6312.5
      check($sformatf("trapecio: altura de un pulso solo (%0d ~ 6312)", t_solo),
            t_solo > 6250 && t_solo < 6375);

      ev_trap.delete(); ev_pico.delete();
      par_exp(1000.0, 600.0, 60, 50.0);
      checkv("trapecio: par a dt = 60, dos eventos", ev_trap.size(), 2);
      t1 = ev_trap[0]; t2 = ev_trap[1]; p2 = ev_pico[1];
      check($sformatf("trapecio: el primero mide limpio (%0d vs %0d)", t1, t_solo),
            t1 >= t_solo - 1 && t1 <= t_solo + 1);
      check($sformatf("trapecio: el segundo mide 0.6 del solo (%0d vs %0d)", t2, (t_solo * 6) / 10),
            t2 >= (t_solo * 6) / 10 - 2 && t2 <= (t_solo * 6) / 10 + 2);
      check($sformatf("pico: el segundo arrastra la cola (%0d, no 600)", p2), p2 > 850);
      $display("  trapecio: solo %0d; par a dt=60: %0d y %0d (pico del segundo %0d)",
               t_solo, t1, t2, p2);

      // dt = 30 < k + m: el segundo trapecio arranca dentro de la ventana del
      // primero, y el primero ya no mide limpio
      ev_trap.delete(); ev_pico.delete();
      par_exp(1000.0, 600.0, 30, 50.0);
      checkv("trapecio: par a dt = 30, dos eventos", ev_trap.size(), 2);
      check($sformatf("trapecio: con dt < k + m el primero se contamina (%0d vs %0d)",
                      ev_trap[0], t_solo), ev_trap[0] > t_solo + 100);

      // la ventana de la meseta no entra en la compuerta: F_TRAP = 0
      bus_a_write(20'h00130, {2'b0, 6'd12, 5'd0, 3'd3, 16'd190});
      ev_trap.delete(); ev_pico.delete();
      par_exp(1000.0, 0.0, 0, 50.0);
      checkv("trapecio: ventana incompleta, F_TRAP = 0", ev_trap[0], 0);
      bus_a_write(20'h00130, {2'b0, 6'd12, 5'd0, 3'd3, 16'd36});

      // y llega al histograma por el selector: canal = F_TRAP >> (16 - H_AW)
      bus_a_write(20'h0000C, 32'h00000000);
      bus_a_read(20'h10000 + 4 * (t_solo >> (AMP_W - H_AW)), d);
      check($sformatf("trapecio: el espectro de F_TRAP tiene al pulso solo (canal %0d: %0d)",
                      t_solo >> (AMP_W - H_AW), d), d >= 1);

      //---------------------------------------------------------------------
      // 10b) EL BANCO: la forma 1 (k = 8, m = 8, la misma ganancia con sh =
      //      10) toma los pares que la forma 0 no puede medir limpio
      //
      //   forma 0: antes = despues = 48 (k + m); forma 1: 16 (k + m)
      //   dt = 60: los dos con la forma 0, como en 10)
      //   dt = 30: los dos con la forma 1, y limpios
      //   dt = 5:  ninguna alcanza: marcados, F_TRAP = 0 y F_FORMA = 0xFFFF
      //---------------------------------------------------------------------
      begin
        integer s1;
        bus_a_write(20'h00188, {16'd48, 16'd48});
        bus_a_write(20'h00190, {16'd8, 16'd8});
        bus_a_write(20'h00194, {2'b0, 6'd10, 5'd0, 3'd2, 16'd10});
        bus_a_write(20'h00198, {16'd16, 16'd16});
        bus_a_write(20'h00134, 32'd2);
        bus_a_write(20'h0000C, 32'h00000001);
        repeat (40) push(0);

        // la forma 1 sola: la forma 0 con un antes imposible
        bus_a_write(20'h00188, {16'd48, 16'hFFFF});
        ev_trap.delete(); ev_forma.delete();
        par_exp(1000.0, 0.0, 0, 50.0);
        s1 = ev_trap[0];
        checkv("banco: con la forma 0 descartada, publica la 1", ev_forma[0], 1);
        check($sformatf("banco: la forma 1 tiene la misma ganancia (%0d vs %0d)", s1, t_solo),
              s1 > t_solo - 70 && s1 < t_solo + 70);
        bus_a_write(20'h00188, {16'd48, 16'd48});

        ev_trap.delete(); ev_forma.delete();
        par_exp(1000.0, 600.0, 60, 50.0);
        checkv("banco: dt = 60, dos eventos", ev_trap.size(), 2);
        checkv("banco: dt = 60, el primero con la forma 0", ev_forma[0], 0);
        checkv("banco: dt = 60, el segundo con la forma 0", ev_forma[1], 0);
        check($sformatf("banco: dt = 60, el primero limpio (%0d vs %0d)", ev_trap[0], t_solo),
              ev_trap[0] >= t_solo - 1 && ev_trap[0] <= t_solo + 1);

        ev_trap.delete(); ev_forma.delete();
        par_exp(1000.0, 600.0, 30, 50.0);
        checkv("banco: dt = 30, dos eventos", ev_trap.size(), 2);
        checkv("banco: dt = 30, el primero con la forma 1", ev_forma[0], 1);
        checkv("banco: dt = 30, el segundo con la forma 1", ev_forma[1], 1);
        check($sformatf("banco: dt = 30, el primero ya no se contamina (%0d vs %0d)", ev_trap[0], s1),
              ev_trap[0] >= s1 - 2 && ev_trap[0] <= s1 + 2);
        check($sformatf("banco: dt = 30, el segundo mide 0.6 (%0d vs %0d)", ev_trap[1], (s1 * 6) / 10),
              ev_trap[1] >= (s1 * 6) / 10 - 3 && ev_trap[1] <= (s1 * 6) / 10 + 3);
        $display("  banco: forma 1 sola %0d; par a dt=30 con la forma 1: %0d y %0d", s1, ev_trap[0], ev_trap[1]);

        ev_trap.delete(); ev_forma.delete();
        par_exp(1000.0, 600.0, 5, 50.0);
        checkv("banco: dt = 5, dos eventos", ev_trap.size(), 2);
        checkv("banco: dt = 5, el primero marcado (F_FORMA)", ev_forma[0], 16'hFFFF);
        checkv("banco: dt = 5, el primero marcado (F_TRAP = 0)", ev_trap[0], 0);
        checkv("banco: dt = 5, el segundo marcado (F_FORMA)", ev_forma[1], 16'hFFFF);
        checkv("banco: dt = 5, el segundo marcado (F_TRAP = 0)", ev_trap[1], 0);

        bus_a_write(20'h00188, 32'd0);
        bus_a_write(20'h00190, {16'd16, 16'd32});
        bus_a_write(20'h00194, {2'b0, 6'd6, 5'd0, 3'd3, 16'd40});
        bus_a_write(20'h00198, 32'd0);
        bus_a_write(20'h00134, 32'd1);
      end

      bus_a_write(20'h00090, {20'h0, 4'd2, 4'd0, 4'd0});
      bus_a_write(20'h00120, 32'd1);
      bus_a_write(20'h0000C, 32'h00000003);
      repeat (2*(1<<H_AW)) @(negedge clk);
    end

    $display("---------------------------------------------");
    $display("tb_mca_top: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #20000000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
