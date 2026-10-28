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
  bind mca_top mca_top_sva u_sva (.*);

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

    // 3 pulsos de amplitud 200 (thr=50) -> canal_de(200) del espectro.
    pulse_rect(200, 20); settle;
    pulse_rect(200, 20); settle;
    pulse_rect(200, 20); settle;

    bus_a_read(20'h00050, d); checkv("cnt_total = 3",    d, 3);
    bus_a_read(20'h00054, d); checkv("cnt_accepted = 3", d, 3);
    // Todos los bins fuera del canal del pico tienen que estar en cero: si la
    // lectura no retuviera el dato, todos devolverian el bin del ultimo evento.
    nz = 0;
    for (i=0; i<(1<<H_AW); i=i+1) begin
      bus_a_read(20'h10000 + i[19:0]*4, d2);
      if (i != canal_de(200) && d2 !== 32'h0) nz = nz + 1;
    end
    checkv("espectro: todos los demas bins en 0", nz, 0);
    bus_a_read(20'h10000 + canal_de(200)*4, d);
    checkv("espectro: el canal del pico acumulo 3 cuentas", d, 3);
    bus_a_read(20'h10000 + (canal_de(200)+1)*4, d);
    checkv("espectro: bin vecino en 0", d, 0);

    // El mapa 2D: amplitud 40 con h2_shift=0 satura el eje (H2_AW=4 -> 15)
    bus_a_read(20'h00080, d);
    checkv("ultimo evento: amplitud 200", d[15:0], 200);

    // Relojes
    bus_a_read(20'h00068, d);  bus_a_read(20'h0006C, d2);
    check("realtime avanza", d != 0);
    bus_a_read(20'h00070, d);
    check("livetime avanza", d != 0);
    bus_a_read(20'h000C0, d);
    checkv("vetotime en 0 sin veto", d, 0);

    //-----------------------------------------------------------------------
    // 6b) VETO externo: no abre pulsos, se ve en el estado, y el tiempo va a
    //     vetotime en vez de a livetime.
    //-----------------------------------------------------------------------
    veto = 1'b1;
    bus_a_read(20'h00010, d);
    check("estado: bit 3 = vetoed", d[3] == 1'b1);
    bus_a_read(20'h00070, d);      // livetime congelado durante el veto
    pulse_rect(200, 20); settle;
    pulse_rect(200, 20); settle;
    bus_a_read(20'h00070, d2);
    checkv("livetime NO avanza bajo veto", d2, d);
    bus_a_read(20'h00050, d); checkv("bajo veto: cnt_total sigue en 3", d, 3);
    bus_a_read(20'h000C0, d); check("vetotime avanza", d != 0);
    veto = 1'b0;
    // La senal vuelve a la base antes del pulso siguiente: el Schmitt se
    // rearma y el MCA vuelve a contar.
    push(0); push(0); push(0); settle;
    bus_a_read(20'h00010, d);
    check("estado: vetoed vuelve a 0", d[3] == 1'b0);
    pulse_rect(200, 20); settle;
    bus_a_read(20'h00050, d); checkv("tras el veto: cnt_total = 4", d, 4);

    //-----------------------------------------------------------------------
    // 7) El borrado deja el espectro y los contadores en cero
    //-----------------------------------------------------------------------
    bus_a_write(20'h0000C, 32'h00000003);
    repeat (2*(1<<H_AW)) @(negedge clk);
    bus_a_read(20'h10000 + canal_de(200)*4, d); checkv("tras borrar: el canal del pico en 0", d, 0);
    bus_a_read(20'h00050, d);        checkv("tras borrar: cnt_total en 0", d, 0);

    //-----------------------------------------------------------------------
    // 8) EL TESELADO DEL TIEMPO MUERTO, visto por el BUS
    //
    // Las assertions de sva/mca_top_sva.sv ya verifican la invariante sobre las
    // senales internas. Esto es distinto y hace falta igual: comprueba que los
    // registros nuevos DECODIFICAN, que las lecturas de 64 b respetan el
    // latcheo de la sombra, y que la suma cierra leida como la va a leer
    // API/mca.py. Un registro bien calculado y mal decodificado se ve igual que
    // uno que no existe.
    //-----------------------------------------------------------------------
    bus_a_write(20'h0000C, 32'h00000003);      // clear
    repeat (2*(1<<H_AW)) @(negedge clk);
    bus_a_write(20'h0000C, 32'h00000001);      // run
    // Compuerta corta sobre una senal que NO baja: fabrica tiempo muerto
    // oculto, que es el casillero que antes no existia.
    bus_a_write(20'h00048, 32'h00000001);      // gate_mode = 1
    bus_a_write(20'h0004C, {16'd10, 16'd4});   // larga = 10, corta = 4
    pulse_rect(200, 60);                        // 60 muestras altas
    push(0); push(0); push(0);
    settle;

    // SE PARA LA ADQUISICION ANTES DE LEER, y no es un detalle del testbench.
    // Los relojes avanzan con cfg_run, y cada acceso al bus se lleva ~6 ciclos:
    // leyendo en caliente, realtime se mide antes que livetime y la suma NO
    // cierra por la diferencia de instantes (medido: 651 contra 677). La
    // invariante vale ciclo a ciclo —lo prueba ap_suma_relojes sobre las
    // senales internas—, pero para COMPROBARLA desde software hay que congelar
    // los contadores. API/mca.py tiene que hacer lo mismo.
    bus_a_write(20'h0000C, 32'h00000000);      // run = 0: congela los relojes

    begin
      reg [31:0] rt_lo, rt_hi, lt_lo, dt_lo, vt_lo, tw_lo, td_lo, tr_lo;
      reg [31:0] cruces, open_c, l_rearm, l_act, l_busy, l_veto, per, ext, mx;
      integer suma;

      bus_a_read(20'h00068, rt_lo); bus_a_read(20'h0006C, rt_hi);
      bus_a_read(20'h00070, lt_lo);
      bus_a_read(20'h00078, dt_lo);
      bus_a_read(20'h000C0, vt_lo);
      bus_a_read(20'h000C8, tw_lo);            // t_win
      bus_a_read(20'h000D0, td_lo);            // t_div
      bus_a_read(20'h000D8, tr_lo);            // t_rearm

      checkv("teselado: la palabra alta de realtime es 0", rt_hi, 0);
      check ("teselado: realtime avanzo", rt_lo > 0);
      // LA INVARIANTE, leida por bus.
      suma = lt_lo + vt_lo + tw_lo + td_lo + tr_lo;
      checkv("teselado: realtime = veto+win+div+rearm+live", rt_lo, suma);
      // El registro viejo conserva su definicion: solo ventana + divisores.
      checkv("compat: deadtime (0x078) = t_win + t_div", dt_lo, tw_lo + td_lo);
      // Y el casillero nuevo tiene contenido: es el tiempo muerto que el
      // contador viejo daba como VIVO.
      check ("oculto: t_rearm > 0", tr_lo > 0);
      check ("oculto: y supera a la ventana", tr_lo > tw_lo);
      $display("  [info] por bus: win=%0d div=%0d rearm=%0d live=%0d de %0d",
               tw_lo, td_lo, tr_lo, lt_lo, rt_lo);

      // --- atribucion de arribos, tambien por bus ---
      bus_a_read(20'h000EC, cruces);  bus_a_read(20'h000B4, open_c);
      bus_a_read(20'h000F0, l_rearm); bus_a_read(20'h000F4, l_act);
      bus_a_read(20'h00064, l_busy);  // sum_lost incluye cnt_lost_busy
      bus_a_read(20'h000F8, l_veto);
      check ("arribos: hubo al menos uno", cruces > 0);
      checkv("arribos: uno abrio ventana", open_c, 1);
      checkv("arribos: ninguno bajo veto", l_veto, 0);

      // --- distribucion del periodo muerto ---
      bus_a_read(20'h000E0, per); bus_a_read(20'h000E4, mx);
      bus_a_read(20'h000E8, ext);
      check ("periodo: hubo al menos un periodo muerto", per > 0);
      check ("periodo: el maximo no excede el total", mx <= (tw_lo+td_lo+tr_lo));
      check ("periodo: los extendidos no superan los periodos", ext <= per);
    end

    // Una direccion NO mapeada sigue ackeando y devolviendo 0: el contrato del
    // bus no cambia por agregar registros (ver el encabezado de mca_top.sv).
    bus_a_read(20'h00F00, d);
    checkv("bus: direccion no mapeada devuelve 0", d, 0);

    bus_a_write(20'h00048, 32'h00000000);      // vuelve a histeresis

    //-----------------------------------------------------------------------
    // 9) FASE 2 POR EL BUS: las politicas de ventana y el arbitro
    //
    // Lo que se comprueba aca es lo que las assertions NO pueden: que los
    // registros nuevos decodifican en los dos sentidos y que el teselado sigue
    // cerrando con el modo FIFO puesto. El comportamiento de cada politica se
    // verifica en tb_mca_pulse_feature, que tiene acceso a la senal.
    //-----------------------------------------------------------------------
    begin
      reg [31:0] d9, rt, lt, vt, tw, td, tr;
      integer suma9;

      // Ida y vuelta de la palabra de politicas.
      bus_a_write(20'h00104, 32'h00010102);    // pub=1, rearm=1, src=2
      bus_a_read (20'h00104, d9);
      checkv("fase2: la palabra de politicas vuelve igual", d9, 32'h00010102);
      bus_a_write(20'h00108, 32'd250);
      bus_a_read (20'h00108, d9);
      checkv("fase2: el holdoff de re-armado vuelve igual", d9, 250);
      // PUB_K se publica para que el software sepa cuantos lugares hay sin
      // tener que saber con que parametros se sintetizo.
      bus_a_read (20'h0011C, d9);
      checkv("fase2: PUB_K publicado", d9, 2);

      // Ahora una corrida de verdad en modo FIFO + re-armado por contador, con
      // los contadores borrados primero: el borrado es lo que hace comparables
      // los relojes (ver el flag modo_mixto de las assertions).
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
      bus_a_write(20'h00104, 32'h00010100);    // pub=FIFO, rearm=contador, src=interno
      bus_a_write(20'h00108, 32'd4);           // holdoff corto: fuerza la cola
      bus_a_write(20'h00048, 32'h00000001);    // gate_mode = 1
      bus_a_write(20'h0004C, {16'd3, 16'd1});  // larga = 3, corta = 1
      bus_a_write(20'h0000C, 32'h00000001);    // run
      pulse_rect(200, 120);                    // 120 muestras altas
      push(0); push(0); push(0);
      settle;
      bus_a_write(20'h0000C, 32'h00000000);    // stop: congela los relojes

      bus_a_read(20'h00068, rt); bus_a_read(20'h00070, lt);
      bus_a_read(20'h000C0, vt); bus_a_read(20'h000C8, tw);
      bus_a_read(20'h000D0, td); bus_a_read(20'h000D8, tr);
      suma9 = lt + vt + tw + td + tr;
      checkv("fifo: el teselado sigue cerrando", rt, suma9);
      // En modo FIFO el casillero de publicacion recibe la CONTRAPRESION, que
      // ocurre con la FSM de ventana en reposo. Si fuera cero, o la FIFO nunca
      // se lleno o el bloqueo del arbitro se esta yendo a livetime.
      check ("fifo: hubo tiempo de publicacion contado", td > 0);
      $display("  [info] fifo por bus: win=%0d div=%0d rearm=%0d live=%0d de %0d",
               tw, td, tr, lt, rt);

      // El registro viejo ya NO es t_win + t_div en modo FIFO: es solo t_win.
      // Esta comprobacion existe para que el cambio quede fijado desde el bus y
      // no solo en una assertion sobre senales internas.
      bus_a_read(20'h00078, d9);
      checkv("fifo: deadtime (0x078) = solo t_win", d9, tw);

      // Estado del arbitro y atribucion nueva.
      // Campos de 0x10C: id[31:16], occ_max[15:8], occ[7:0].
      bus_a_read(20'h0010C, d9);
      $display("  [info] arbitro: occ=%0d occ_max=%0d id=%0d",
               d9 & 32'hFF, (d9 >> 8) & 32'hFF, d9 >> 16);
      check ("arbitro: la marca de agua llego al tope",
             ((d9 >> 8) & 32'hFF) == 2);
      check ("arbitro: el id de ventana avanzo", (d9 >> 16) > 1);
      bus_a_read(20'h00110, d9);
      check ("arbitro: se abrieron varias ventanas", d9 > 1);
      bus_a_read(20'h00114, d9);
      checkv("arbitro: sin perdidas por falta de trigger", d9, 0);
      bus_a_read(20'h00118, d9);
      checkv("arbitro: ningun trigger externo", d9, 0);

      // Y la atribucion de arribos, ahora con seis casilleros.
      begin
        reg [31:0] cr, op, lr, la, lv, ln, lb;
        bus_a_read(20'h000EC, cr); bus_a_read(20'h000B4, op);
        bus_a_read(20'h000F0, lr); bus_a_read(20'h000F4, la);
        bus_a_read(20'h000F8, lv); bus_a_read(20'h00114, ln);
        bus_a_read(20'h00064, lb);     // sum_lost incluye cnt_lost_busy
        check ("arribos: hubo cruces", cr > 0);
        // lb trae los dropped de los histogramas sumados, asi que solo se puede
        // acotar: los seis casilleros nunca pueden exceder los cruces.
        check ("arribos: los casilleros no exceden los cruces",
               (op + lr + la + lv + ln) <= cr);
      end

      //---------------------------------------------------------------------
      // APERTURA POR TRIGGER EXTERNO, por el puerto trig_i DEL TOP.
      //
      // Esto no se puede probar en tb_mca_pulse_feature: ahi el trigger entra
      // directo al extractor, mientras que aca atraviesa el puerto de mca_top y
      // el registro de entrada. Y es lo que engancha las propiedades de
      // cobertura cp_trig_ext / cp_trig_flanco / cp_notrig, que sin esto quedan
      // en CERO — o sea, la fuente externa sin verificar al nivel del top.
      //---------------------------------------------------------------------
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
      bus_a_write(20'h00104, 32'h00000001);    // src = EXTERNO
      bus_a_write(20'h00048, 32'h00000001);    // gate_mode = 1
      bus_a_write(20'h0004C, {16'd10, 16'd4});
      bus_a_write(20'h0000C, 32'h00000001);    // run

      // (a) Un pulso SIN trigger: cruza el umbral y no abre nada.
      //     Primero hay que ARMAR el Schmitt: `armed` queda en 0 despues de un
      //     stop (`!cfg_run && st==S_IDLE` lo desarma) y se pone recien con una
      //     muestra por debajo de thr_lo. Sin esto el cruce caeria en
      //     lost_rearm, que es correcto pero no es lo que este test mide.
      push(0); push(0); push(0);
      pulse_rect(200, 20);
      push(0); push(0); push(0);
      settle;
      bus_a_read(20'h00110, d9);
      checkv("ext: ninguna ventana sin trigger",   d9, 0);
      bus_a_read(20'h00114, d9);
      check ("ext: el cruce quedo en lost_notrig", d9 > 0);
      bus_a_read(20'h00118, d9);
      checkv("ext: ningun flanco de trigger",      d9, 0);

      // (b) Ahora con trigger, y SOSTENIDO 5 muestras: es el largo de un
      //     sys_wen, el caso que en la placa producia dos eventos por trigger
      //     de software. Por flanco tiene que dar UNA ventana.
      trig = 1'b1;
      push(200); push(200); push(200); push(200); push(200);
      trig = 1'b0;
      for (i=0;i<20;i=i+1) push(200);
      push(0); push(0); push(0);
      settle;
      bus_a_read(20'h00118, d9);
      checkv("ext: un solo flanco contado",        d9, 1);
      bus_a_read(20'h00110, d9);
      checkv("ext: y UNA sola ventana abierta",    d9, 1);
      bus_a_read(20'h00050, d9);
      checkv("ext: la ventana cerro",              d9, 1);

      bus_a_write(20'h0000C, 32'h00000000);    // stop

      //---------------------------------------------------------------------
      // ARRIBOS PERDIDOS DENTRO DE LA VENTANA Y DURANTE LA PUBLICACION.
      //
      // Los dos casos existian desde la Fase 1 y estaban verificados en
      // tb_mca_pulse_feature, pero NUNCA se ejercitaban en tb_mca_top — que es
      // el unico TB con el bind de assertions puesto. O sea que cp_lost_active y
      // cp_lost_busy leian CERO y las ramas correspondientes de
      // ap_atribucion_arribos no se habian evaluado nunca con contenido.
      //---------------------------------------------------------------------
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
      bus_a_write(20'h00104, 32'h00000000);    // fuente interna otra vez
      bus_a_write(20'h00048, 32'h00000001);    // gate_mode = 1
      bus_a_write(20'h0004C, {16'd60, 16'd4}); // larga = 60: entra un 2do pulso
      bus_a_write(20'h0000C, 32'h00000001);    // run

      // (a) DENTRO de la ventana: baja de thr_lo y vuelve a cruzar thr_hi.
      push(0); push(0); push(0);               // arma
      for (i=0;i<5;i=i+1)  push(200);          // abre
      for (i=0;i<5;i=i+1)  push(0);            // baja, ventana sigue abierta
      for (i=0;i<10;i=i+1) push(200);          // 2do cruce ADENTRO
      for (i=0;i<60;i=i+1) push(0);
      settle;
      bus_a_read(20'h000F4, d9);
      check ("arribo adentro: contado en lost_active", d9 > 0);

      // (b) Durante la PUBLICACION: ventana corta, y el 2do pulso cae en los
      //     17 ciclos del divisor.
      bus_a_write(20'h0004C, {16'd4, 16'd2});  // larga = 4
      push(0); push(0); push(0);
      for (i=0;i<4;i=i+1) push(200);           // abre y cierra
      push(0); push(0);                        // baja de thr_lo: re-arma
      for (i=0;i<6;i=i+1) push(200);           // 2do cruce con el divisor ocupado
      for (i=0;i<30;i=i+1) push(0);
      settle;
      bus_a_write(20'h0000C, 32'h00000000);    // stop
      bus_a_read(20'h00064, d9);               // sum_lost incluye cnt_lost_busy
      check ("arribo publicando: contado en lost_busy", d9 > 0);

      // Se vuelve al default para no dejar el estado contaminado.
      bus_a_write(20'h00104, 32'h00000000);
      bus_a_write(20'h00108, 32'h00000000);
      bus_a_write(20'h00048, 32'h00000000);
      bus_a_write(20'h0000C, 32'h00000003);    // clear
      repeat (2*(1<<H_AW)) @(negedge clk);
    end

    $display("---------------------------------------------");
    $display("tb_mca_top: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #20000000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
