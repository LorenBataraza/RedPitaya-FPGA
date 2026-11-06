`timescale 1ns/1ps
//============================================================================
// tb_event_ring_ventana — ventanas largas, con la geometria del bitstream.
//
// Los otros testbenches usan PRE_AW=6 y una stage chica a proposito, asi que no
// dicen nada de los parametros que se construyen. Este deja al DUT con sus
// DEFAULTS, los mismos que instancia event_ring_red_pitaya_top.
//
// Lo que se protege es el limite de event_window_capture: si
//     (pre + post)*N_CH - post >= 2^PRE_AW
// el escritor del pre-buffer pisa lo que falta leer, sin ningun error ni contador.
// Por eso cada escena mira la rampa ENTERA en memoria, muestra por muestra: un
// conteo de muestras o un footer correcto no veria el dano.
//
// Chequea:
//   1. ventana de 1024 con pre=32: cabecera, footer y rampa exacta
//   2. la alineacion del trigger no depende de la geometria
//   3. los extremos de 1024: pre=0 y pre=1023 (el rezago mas grande)
//   4. el limite real del pre-buffer: pre=0, post=2047
//   5. triggers que llegan apenas termina la ventana: el invariante y que todos
//      los slots escritos sigan limpios
//   6. contrapresion de AXI con la ventana entera
//   7. 1024 muestras no entran en un slot de 4 KB: err_slot_ovf
//   8. 1014 muestras entran justas en 4 KB, y eso no es un error
//============================================================================
module tb_event_ring_ventana;

  localparam integer DW   = 14;
  localparam integer N_CH = 2;

  localparam integer SLOT_SHIFT = 13;                    // 8 KB
  localparam integer SLOT_W     = (1<<SLOT_SHIFT)/8;
  localparam integer N_SLOTS    = 8;
  localparam [31:0]  RING_BASE  = 32'h1000_0000;
  localparam [31:0]  RING_SZ    = N_SLOTS * (1<<SLOT_SHIFT);
  localparam integer HDR_W      = 4;

  reg clk = 1'b0, rstn = 1'b0;
  always #4 clk = ~clk;   // 125 MHz

  reg [N_CH*DW-1:0] dat = '0;
  reg               dv   = 1'b1;
  reg               trig = 1'b0;
  reg [16:0]        snap = 17'h2;

  wire [31:0] axi_waddr;
  wire [63:0] axi_wdata;
  wire [7:0]  axi_wsel;
  wire [2:0]  axi_wsize;
  wire        axi_wvalid;
  wire [3:0]  axi_wlen;
  wire        axi_wfixed;
  reg         axi_wrdy = 1'b1;

  reg  [31:0] sys_addr = 32'h0, sys_wdata = 32'h0;
  reg         sys_wen = 1'b0, sys_ren = 1'b0;
  wire [31:0] sys_rdata;
  wire        sys_err, sys_ack;

  // Sin parametros de geometria: los defaults son los del bitstream.
  event_ring_top dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .dat_i(dat), .dv_i(dv), .trig_i(trig), .snapshot_i(snap),
    .axi_waddr_o(axi_waddr), .axi_wdata_o(axi_wdata), .axi_wsel_o(axi_wsel),
    .axi_wsize_o(axi_wsize), .axi_wvalid_o(axi_wvalid), .axi_wlen_o(axi_wlen),
    .axi_wfixed_o(axi_wfixed), .axi_werr_i(1'b0), .axi_wrdy_i(axi_wrdy),
    .sys_addr(sys_addr), .sys_wdata(sys_wdata), .sys_wen(sys_wen),
    .sys_ren(sys_ren), .sys_rdata(sys_rdata), .sys_err(sys_err),
    .sys_ack(sys_ack)
  );

  //--------------------------------------------------------------------------
  integer pass_cnt = 0, fail_cnt = 0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt = pass_cnt + 1;
      else begin fail_cnt = fail_cnt + 1; $display("  FAIL: %s", name); end
    end
  endtask
  task automatic checkv(input string name, input longint got, input longint exp);
    begin
      if (got === exp) pass_cnt = pass_cnt + 1;
      else begin
        fail_cnt = fail_cnt + 1;
        $display("  FAIL: %s (got=%0h exp=%0h)", name, got, exp);
      end
    end
  endtask

  task automatic bus_wr(input [19:0] a, input [31:0] d);
    begin
      @(negedge clk);
      sys_addr = {12'h0, a}; sys_wdata = d; sys_wen = 1'b1;
      @(negedge clk);
      sys_wen = 1'b0;
      repeat (6) @(negedge clk);
    end
  endtask
  task automatic bus_rd(input [19:0] a, output [31:0] d);
    integer k;
    begin
      @(negedge clk);
      sys_addr = {12'h0, a}; sys_ren = 1'b1;
      @(negedge clk);
      sys_ren = 1'b0;
      k = 0;
      while (!sys_ack && k < 20) begin @(negedge clk); k = k + 1; end
      d = sys_rdata;
      repeat (2) @(negedge clk);
    end
  endtask

  //--------------------------------------------------------------------------
  // Memoria direccionada: la misma idea que tb_event_ring_top.
  //--------------------------------------------------------------------------
  reg [63:0] ddr [0:N_SLOTS*SLOT_W-1];
  integer    addr_out_of_range = 0;
  integer    widx;
  always @(posedge clk) begin
    if (axi_wvalid && axi_wrdy) begin
      if (axi_waddr < RING_BASE || axi_waddr >= (RING_BASE + RING_SZ))
        addr_out_of_range = addr_out_of_range + 1;
      else begin
        widx = (axi_waddr - RING_BASE) >> 3;
        ddr[widx] = axi_wdata;
      end
    end
  end
  function automatic [63:0] slot_w(input integer s, input integer w);
    slot_w = ddr[((s % N_SLOTS) * SLOT_W) + w];
  endfunction

  // Muestra k del canal c del slot s (palabras de 64 b con 4 muestras de 16 b).
  function automatic [15:0] muestra(input integer s, input integer k, input integer c);
    integer i;
    reg [63:0] w;
    begin
      i = k * N_CH + c;
      w = slot_w(s, HDR_W + i / 4);
      muestra = w[(i % 4) * 16 +: 16];
    end
  endfunction

  //--------------------------------------------------------------------------
  // Rampa de 14 b: ch0 cuenta, ch1 = -ch0.
  //--------------------------------------------------------------------------
  integer sample_idx = 0;
  reg signed [DW-1:0] c0, c1;
  always @(posedge clk) if (dv) sample_idx <= sample_idx + 1;
  always @(*) begin
    c0  = sample_idx[DW-1:0];
    c1  = -sample_idx[DW-1:0];
    dat = {c1, c0};
  end

  integer t_trig;      // sample_idx en el flanco del trigger
  task automatic pulse_trig;
    begin
      @(negedge clk); t_trig = sample_idx; trig = 1'b1;
      @(negedge clk); trig = 1'b0;
    end
  endtask

  // Cuantas muestras del slot s NO siguen la rampa, en cualquiera de los dos canales.
  function automatic integer saltos_rampa(input integer s, input integer n);
    integer k, malas;
    reg [13:0] a0, b0;
    begin
      malas = 0;
      a0 = muestra(s, 0, 0);
      for (k = 0; k < n; k = k + 1) begin
        b0 = -a0;
        if (muestra(s, k, 0) !== {{2{a0[13]}}, a0}) malas = malas + 1;
        if (muestra(s, k, 1) !== {{2{b0[13]}}, b0}) malas = malas + 1;
        a0 = a0 + 1'b1;
      end
      saltos_rampa = malas;
    end
  endfunction

  // Para, limpia y arranca con esta geometria. Espera a que el pre-buffer se llene.
  task automatic arrancar(input integer pre, input integer post, input integer sh);
    reg [31:0] rv;
    integer k;
    begin
      bus_wr(20'h00, 32'h0);
      k = 0; rv = 32'hFFFF_FFFF;
      while (rv[2:1] != 2'd0 && k < 40000) begin
        repeat (50) @(posedge clk);
        bus_rd(20'h00, rv); k = k + 1;
      end
      bus_wr(20'h00, 32'h2);
      bus_wr(20'h08, RING_BASE);
      bus_wr(20'h0C, RING_SZ);
      bus_wr(20'h10, sh);
      bus_wr(20'h14, pre);
      bus_wr(20'h18, post);
      bus_wr(20'h00, 32'h1);
      repeat (2100) @(posedge clk);
    end
  endtask

  // Espera a que el writer vuelque todo lo capturado.
  task automatic esperar_slots(input integer n, input integer max_cyc);
    reg [31:0] rv;
    integer k;
    begin
      k = 0; rv = 0;
      while (rv < n && k < max_cyc) begin
        repeat (100) @(posedge clk);
        bus_rd(20'h20, rv); k = k + 100;
      end
      // el footer sale al FIFO antes de llegar a memoria
      repeat (300) @(posedge clk);
    end
  endtask

  // Un evento suelto de esta geometria, verificado entero contra la rampa.
  task automatic un_evento(input string nom, input integer pre, input integer post);
    reg [31:0] rv;
    integer n;
    begin
      n = pre + post;
      arrancar(pre, post, SLOT_SHIFT);
      pulse_trig();
      esperar_slots(1, 40000);
      bus_rd(20'h20, rv);
      checkv({nom, ": WR_SLOT"}, rv, 1);
      checkv({nom, ": n_samp"}, slot_w(0,1)[47:32], n);
      checkv({nom, ": n_ch"}, slot_w(0,1)[55:48], N_CH);
      checkv({nom, ": footer"}, slot_w(0,SLOT_W-1), {~32'd0, 32'd0});
      checkv({nom, ": rampa sin saltos"}, saltos_rampa(0, n), 0);
      bus_rd(20'h34, rv); checkv({nom, ": sin drop_full"}, rv, 0);
    end
  endtask

  //--------------------------------------------------------------------------
  integer i, s, errs, n_trig, k_ref, k_got;
  reg [31:0] rv, ev_c, db_c, df_c, wrs;

  initial begin
    repeat (4) @(posedge clk);
    rstn = 1'b1;
    repeat (4) @(posedge clk);

    //======================================================================
    $display("[1] ventana de 1024 con pre=32");
    un_evento("1024 pre=32", 32, 992);
    checkv("dentro del ring", addr_out_of_range, 0);
    // relleno: de la ultima palabra de datos al footer
    errs = 0;
    for (i = HDR_W + 1024*N_CH/4; i < SLOT_W-1; i = i + 1)
      if (slot_w(0,i) !== 64'h0) errs = errs + 1;
    checkv("relleno en cero hasta el footer", errs, 0);

    //======================================================================
    $display("[2] la alineacion del trigger no depende de la geometria");
    arrancar(8, 24, SLOT_SHIFT);
    pulse_trig();
    esperar_slots(1, 2000);
    k_ref = (muestra(0, 8, 0) - t_trig) & 14'h3FFF;
    arrancar(32, 992, SLOT_SHIFT);
    pulse_trig();
    esperar_slots(1, 40000);
    k_got = (muestra(0, 32, 0) - t_trig) & 14'h3FFF;
    checkv("muestra `pre` = la del trigger, en 8+24 y en 32+992", k_got, k_ref);

    //======================================================================
    $display("[3] los extremos de 1024: pre=0 y pre=1023");
    un_evento("1024 pre=0", 0, 1024);
    un_evento("1024 pre=1023", 1023, 1);

    //======================================================================
    $display("[4] el limite real: pre=0, post=2047");
    arrancar(0, 2047, 14);
    pulse_trig();
    esperar_slots(1, 40000);
    // con slot de 16 KB las palabras caen en otra posicion: se lee directo
    errs = 0;
    for (i = 0; i < 2047; i = i + 1) begin
      reg [63:0] w; integer j;
      j = i * N_CH;
      w = ddr[HDR_W + j / 4];
      if (w[(j % 4) * 16 +: 14] !== (14'(ddr[HDR_W][13:0]) + 14'(i))) errs = errs + 1;
    end
    checkv("post=2047: rampa sin saltos", errs, 0);

    //======================================================================
    $display("[5] triggers apenas termina la ventana: invariante y slots limpios");
    arrancar(32, 992, SLOT_SHIFT);
    n_trig = 0;
    for (i = 0; i < 10; i = i + 1) begin
      pulse_trig();
      n_trig = n_trig + 1;
      repeat (2100) @(posedge clk);      // apenas mas que los 2050 de la captura
      if (i % 2 == 1) begin bus_rd(20'h20, wrs); bus_wr(20'h24, wrs); end
    end
    bus_rd(20'h38, ev_c);
    bus_rd(20'h30, db_c);
    bus_rd(20'h34, df_c);
    checkv("capturados + drop_busy + drop_full == triggers", ev_c + db_c + df_c, n_trig);
    checkv("ningun trigger cayo adentro de una ventana", db_c, 0);
    check("el writer no da abasto: hubo drop_full", df_c > 0);
    esperar_slots(ev_c, 60000);
    bus_rd(20'h20, wrs);
    checkv("todo lo capturado se escribio", wrs, ev_c);
    errs = 0;
    for (s = (wrs > N_SLOTS ? wrs - N_SLOTS : 0); s < wrs; s = s + 1) begin
      errs = errs + saltos_rampa(s, 1024);
      if (slot_w(s, SLOT_W-1) !== {~s[31:0], s[31:0]}) errs = errs + 1;
    end
    checkv("todos los slots con la rampa exacta y su footer", errs, 0);
    bus_rd(20'h04, rv);
    check("sin overflow del axi_wr_fifo", rv[7] === 1'b0);

    //======================================================================
    $display("[6] contrapresion de AXI con la ventana entera");
    arrancar(32, 992, SLOT_SHIFT);
    fork : f
      begin
        pulse_trig();
        repeat (60000) @(posedge clk);
      end
      forever begin
        @(negedge clk);
        axi_wrdy = ($urandom % 100) < 30;
      end
    join_any
    disable f;
    axi_wrdy = 1'b1;
    repeat (600) @(posedge clk);
    bus_rd(20'h20, rv);
    checkv("el evento salio", rv, 1);
    checkv("footer bien formado", slot_w(0, SLOT_W-1), {~32'd0, 32'd0});
    checkv("rampa exacta con contrapresion", saltos_rampa(0, 1024), 0);
    bus_rd(20'h04, rv);
    check("sin overflow con contrapresion", rv[7] === 1'b0);

    //======================================================================
    $display("[7] 1024 muestras no entran en un slot de 4 KB");
    arrancar(32, 992, 12);
    pulse_trig();
    repeat (8000) @(posedge clk);
    bus_rd(20'h04, rv);
    check("err_slot_ovf", rv[6] === 1'b1);

    //======================================================================
    $display("[8] 1014 muestras entran justas en un slot de 4 KB");
    arrancar(16, 998, 12);
    pulse_trig();
    esperar_slots(1, 40000);
    bus_rd(20'h20, rv); checkv("1014: WR_SLOT", rv, 1);
    bus_rd(20'h04, rv); check("1014: sin err_slot_ovf", rv[6] === 1'b0);
    checkv("1014: n_samp", ddr[1][47:32], 1014);
    checkv("1014: footer en la ultima palabra", ddr[511], {~32'd0, 32'd0});
    checkv("1014: rampa sin saltos", saltos_rampa(0, 1014), 0);

    //======================================================================
    $display("");
    $display("  pass=%0d  fail=%0d", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #20000000;
    $display("RESULT: FAIL (timeout global)");
    $finish;
  end

endmodule
