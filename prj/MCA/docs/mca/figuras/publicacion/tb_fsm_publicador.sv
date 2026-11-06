`timescale 1ns/1ps
//=============================================================================
// tb_fsm_publicador — la escena de la figura fsm_publicador
//
// NO es un testbench de verificacion: no chequea nada. Corre un mca_top con dos
// ranuras habilitadas y dos disparos separados por 8 muestras, y vuelca ciclo a
// ciclo el estado de las ranuras y del publicador a un CSV. La figura se dibuja
// de ese CSV, asi que los ciclos que muestra son los del RTL.
//
// Configuracion: compuertas 8/20, base fija en 0, sin decimar y
// cfg_pre_dly = 0. La ranura 0 cierra con la cola de publicacion vacia
// (arranque directo); la 1 cierra 8 ciclos despues, con el publicador ocupado,
// y espera en la cola.
//
// Regenerar: python3 fsm_publicador.py --sim
//=============================================================================
module tb_fsm_publicador;
  localparam integer DW   = 14;
  localparam integer NCYC = 70;     // ciclos que se vuelcan
  localparam real    TAU  = 30.0;
  localparam integer LAT  = 2;      // muestra -> ventana dentro de mca_top

  reg clk = 1'b0;
  always #4 clk = ~clk;
  reg rstn = 1'b0;

  localparam integer NP = 2;
  integer p_t [0:NP-1];
  real    p_a [0:NP-1];
  initial begin
    p_t[0] = 3;  p_a[0] = 400.0;
    p_t[1] = 11; p_a[1] = 300.0;
  end

  function automatic real pulso(input integer k, input real a);
    if      (k <  0) pulso = 0.0;
    else if (k == 0) pulso = a / 2.0;
    else             pulso = a * $exp(-(k - 1) / TAU);
  endfunction

  reg signed [DW-1:0] x_in = '0;
  reg                 trig = 1'b0;
  reg [31:0] addr = '0, wdata = '0;
  reg        wen  = 1'b0;
  wire [31:0] rd;
  wire        err, ack;

  mca_top #(.H_AW(13), .H2_AW(7), .PSD_AW(6)) u (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i({x_in, x_in}), .mca_val_i(2'b11),
    .veto_i(1'b0), .trig_i(trig),
    .sys_addr(addr), .sys_wdata(wdata), .sys_wen(wen), .sys_ren(1'b0),
    .sys_rdata(rd), .sys_err(err), .sys_ack(ack));

  task automatic wr(input [31:0] a, input [31:0] d);
    @(negedge clk); addr = a; wdata = d; wen = 1'b1;
    @(negedge clk); wen = 1'b0;
    repeat (8) @(negedge clk);
  endtask

  `define P u.i_feat.i_pub
  `define EST(k) ((u.i_feat.i_win.reserva_q[k]) ? 1 : u.i_feat.i_win.g_slot[k].i_slot.est)

  integer fd, n, i;
  string  csv;
  real    acc;

  initial begin
    if (!$value$plusargs("CSV=%s", csv)) csv = "fsm_publicador.csv";
    fd = $fopen(csv, "w");
    $fdisplay(fd, "n,trig,s0,s1,acepta0,acepta1,pst,div_start,cur,busy,div_valid,libera0,libera1,ev_valid,n_cola,dt_div");

    repeat (10) @(negedge clk);
    rstn = 1'b1;
    repeat (4) @(negedge clk);

    wr(32'h01C, 0);                       // base fija en 0
    wr(32'h020, 32'h60);                  // seguidor apagado
    wr(32'h04C, (20 << 16) | 8);          // gate_long = 20, gate_short = 8
    wr(32'h124, 0);                       // sin retardo extra
    wr(32'h120, 2);                       // dos ranuras

    @(negedge clk); addr = 32'h00C; wdata = 1; wen = 1'b1;
    @(negedge clk); wen = 1'b0;
    repeat (4) @(negedge clk);

    for (n = 0; n < NCYC; n = n + 1) begin
      $fdisplay(fd, "%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                n, trig, `EST(0), `EST(1),
                `P.acepta_i[0], `P.acepta_i[1], `P.pst, `P.div_start, `P.cur,
                `P.div_busy, `P.div_valid, `P.libera_o[0], `P.libera_o[1],
                `P.ev_valid_o, `P.n_cola, u.dt_div);
      acc = 0.0;
      for (i = 0; i < NP; i = i + 1) acc = acc + pulso(n - p_t[i], p_a[i]);
      x_in = $rtoi(acc + 0.5);
      trig = 1'b0;
      for (i = 0; i < NP; i = i + 1) if (n == p_t[i] + LAT) trig = 1'b1;
      @(negedge clk);
    end

    $fclose(fd);
    $finish;
  end
endmodule
