`timescale 1ns/1ps
//============================================================================
// tb_event_stage_fifo — unidad.
//
// Las dos propiedades que tiene que sostener este bloque:
//
//   A. `s_accept_o` es una PROMESA: si dice 1 en el SOF, la ventana entera
//      entra. Si mintiera, la captura empezaria a emitir un evento que despues
//      no cabe y el ring quedaria con basura indistinguible de un evento bueno.
//   B. Un evento solo se ofrece al writer cuando esta COMPLETO (llego su EOF).
//      Si se ofreciera en el SOF, el writer podria drenar muestras mas rapido
//      de lo que entran y leer posiciones todavia no escritas.
//
// Chequea ademas: FIFO de datos en orden, latencia de 1 ciclo del puerto de
// lectura, contabilidad de niveles, y flush.
//============================================================================
module tb_event_stage_fifo;

  localparam integer SW      = 16;
  localparam integer S_AW    = 11;
  localparam integer TS_W    = 64;
  localparam integer DATA_AW = 7;   // 128 muestras: la llenamos a proposito
  localparam integer E       = 4;

  reg clk = 1'b0, rstn = 1'b0;
  always #5 clk = ~clk;

  reg              flush = 1'b0;
  reg [S_AW+2:0]   win_len = 14'd64;   // 32 muestras/canal x 2 canales

  reg              s_val = 1'b0, s_sof = 1'b0, s_eof = 1'b0;
  reg [SW-1:0]     s_dat = 16'h0;
  reg [TS_W-1:0]   s_ts  = 64'h0;
  reg [16:0]       s_snap= 17'h0;
  reg [S_AW-1:0]   s_ns  = 11'd0;
  wire             s_accept;

  wire             m_meta_val;
  wire [TS_W-1:0]  m_ts;
  wire [16:0]      m_snap;
  wire [S_AW-1:0]  m_ns;
  reg              m_meta_rd = 1'b0;
  wire [SW-1:0]    m_dat;
  reg              m_dat_rd  = 1'b0;
  wire [DATA_AW:0] lvl;
  wire [$clog2(E+1)-1:0] ev_lvl;

  event_stage_fifo #(
    .SW(SW), .S_AW(S_AW), .TS_W(TS_W), .DATA_AW(DATA_AW), .E(E)
  ) dut (
    .clk_i(clk), .rstn_i(rstn), .flush_i(flush), .win_len_i(win_len),
    .s_accept_o(s_accept), .s_val_i(s_val), .s_sof_i(s_sof), .s_eof_i(s_eof),
    .s_dat_i(s_dat), .s_ts_i(s_ts), .s_snap_i(s_snap), .s_nsamp_i(s_ns),
    .m_meta_val_o(m_meta_val), .m_ts_o(m_ts), .m_snap_o(m_snap),
    .m_nsamp_o(m_ns), .m_meta_rd_i(m_meta_rd),
    .m_dat_o(m_dat), .m_dat_rd_i(m_dat_rd),
    .lvl_o(lvl), .ev_lvl_o(ev_lvl)
  );

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
        $display("  FAIL: %s (got=%0d exp=%0d)", name, got, exp);
      end
    end
  endtask

  // Una muestra, exactamente un posedge. Todo el estimulo pasa por aca para no
  // empujar valores duplicados sin querer.
  task automatic push_sample(input [SW-1:0] d, input bit sof, input bit eof,
                             input [63:0] ts, input [16:0] sn, input [S_AW-1:0] ns);
    begin
      @(negedge clk);
      s_val = 1'b1; s_sof = sof; s_eof = eof;
      s_dat = d;    s_ts  = ts;  s_snap = sn; s_ns = ns;
      @(posedge clk);
      @(negedge clk);
      s_val = 1'b0; s_sof = 1'b0; s_eof = 1'b0;
    end
  endtask

  // Empuja un evento de `n` muestras con valores base..base+n-1
  task automatic push_event(input integer n, input integer base,
                            input [63:0] ts, input [16:0] sn);
    integer k;
    begin
      for (k = 0; k < n; k = k + 1) begin
        @(negedge clk);
        s_val = 1'b1;
        s_sof = (k == 0);
        s_eof = (k == n-1);
        s_dat = base + k;
        s_ts  = ts;
        s_snap= sn;
        s_ns  = n/2;
      end
      @(negedge clk);
      s_val = 1'b0; s_sof = 1'b0; s_eof = 1'b0;
    end
  endtask

  // Drena n muestras y verifica que salgan en orden desde `base`
  task automatic drain_check(input integer n, input integer base,
                             input string name);
    integer k, errs;
    begin
      errs = 0;
      for (k = 0; k < n; k = k + 1) begin
        @(negedge clk);
        m_dat_rd = 1'b1;
        @(negedge clk);
        m_dat_rd = 1'b0;
        // latencia de 1 ciclo: el dato vale ahora
        if (m_dat !== ((base + k) & 16'hFFFF)) errs = errs + 1;
      end
      checkv(name, errs, 0);
    end
  endtask

  integer i;
  initial begin
    $dumpfile("tb_event_stage_fifo.vcd");
    $dumpvars(0, tb_event_stage_fifo);

    repeat (4) @(posedge clk);
    rstn = 1'b1;
    repeat (2) @(posedge clk);

    //======================================================================
    $display("[1] vacia: acepta, y no ofrece nada al writer");
    check("accept con FIFO vacia", s_accept === 1'b1);
    check("sin metadatos", m_meta_val === 1'b0);

    //======================================================================
    $display("[2] PROPIEDAD B: el evento no se ofrece hasta el EOF");
    // 6 muestras sin EOF: el evento esta a medio entrar
    for (i = 0; i < 6; i = i + 1)
      push_sample(16'd1000 + i, (i == 0), 1'b0, 64'hAA, 17'h7, 11'd32);
    check("evento incompleto NO se ofrece", m_meta_val === 1'b0);
    // la 7ma cierra el evento
    push_sample(16'd1006, 1'b0, 1'b1, 64'hAA, 17'h7, 11'd32);
    check("evento completo SI se ofrece", m_meta_val === 1'b1);
    checkv("metadato ts", m_ts, 64'hAA);
    checkv("metadato snap", m_snap, 17'h7);
    checkv("metadato nsamp", m_ns, 32);
    checkv("ev_lvl=1", ev_lvl, 1);

    // drenarlo
    drain_check(7, 1000, "datos en orden");
    @(negedge clk); m_meta_rd = 1'b1; @(negedge clk); m_meta_rd = 1'b0;
    @(posedge clk);
    check("sin eventos tras el pop", m_meta_val === 1'b0);
    checkv("lvl=0", lvl, 0);

    //======================================================================
    $display("[3] PROPIEDAD A: accept baja antes de que no entre la ventana");
    // Capacidad 128 muestras, ventana 64 -> entran 2 eventos, no 3
    check("accept antes del 1ro", s_accept === 1'b1);
    push_event(64, 2000, 64'h1, 17'h1);
    @(posedge clk);
    check("accept antes del 2do", s_accept === 1'b1);
    push_event(64, 3000, 64'h2, 17'h2);
    @(posedge clk);
    check("accept BAJA antes del 3ro (no entra)", s_accept === 1'b0);
    checkv("lvl=128", lvl, 128);
    checkv("ev_lvl=2", ev_lvl, 2);

    // Drenar uno y ver que vuelve a aceptar
    drain_check(64, 2000, "1er evento en orden");
    @(negedge clk); m_meta_rd = 1'b1; @(negedge clk); m_meta_rd = 1'b0;
    @(posedge clk);
    check("accept vuelve tras drenar", s_accept === 1'b1);
    checkv("ev_lvl=1", ev_lvl, 1);
    checkv("metadato del 2do evento", m_ts, 64'h2);

    drain_check(64, 3000, "2do evento en orden");
    @(negedge clk); m_meta_rd = 1'b1; @(negedge clk); m_meta_rd = 1'b0;
    @(posedge clk);
    checkv("lvl=0 al final", lvl, 0);
    checkv("ev_lvl=0 al final", ev_lvl, 0);

    //======================================================================
    $display("[4] limite de eventos en vuelo E=4 con ventana chica");
    win_len = 14'd8;
    for (i = 0; i < E; i = i + 1) begin
      check($sformatf("accept antes del evento %0d", i), s_accept === 1'b1);
      push_event(8, 4000 + 100*i, i+1, 17'h1);
      @(posedge clk);
    end
    checkv("ev_lvl=E", ev_lvl, E);
    check("accept BAJA por meta llena (no por espacio)", s_accept === 1'b0);
    check("hay espacio de sobra", lvl < (1<<DATA_AW));

    //======================================================================
    $display("[5] flush");
    @(negedge clk); flush = 1'b1; @(negedge clk); flush = 1'b0;
    @(posedge clk);
    checkv("lvl=0 tras flush", lvl, 0);
    checkv("ev_lvl=0 tras flush", ev_lvl, 0);
    check("accept tras flush", s_accept === 1'b1);

    //======================================================================
    $display("");
    $display("  pass=%0d  fail=%0d", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #500000;
    $display("RESULT: FAIL (timeout global)");
    $finish;
  end

endmodule
