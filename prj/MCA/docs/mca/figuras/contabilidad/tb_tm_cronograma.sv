`timescale 1ns/1ps
//=============================================================================
// tb_tm_cronograma — la escena de la figura tm_cronograma
//
// NO es un testbench de verificacion: no chequea nada. Corre dos mca_top con el
// MISMO tren de pulsos y los mismos disparos, uno con UNA ranura y otro con
// DOS, y vuelca ciclo a ciclo las senales de la contabilidad a un CSV. La
// figura se dibuja de ese CSV, asi que las ranuras, los casilleros, los
// periodos muertos y los contadores que muestra son los del RTL.
//
// Configuracion: compuertas 8/40, base fija en 0, sin decimar (un ciclo = una
// muestra) y cfg_pre_dly = 0. Cada pulso trae su disparo, que llega al MCA
// cuando su pie llega a la ventana (es lo que hace la linea de retardo bien
// ajustada; ver sim/tb_mca_mt_latencia.sv).
//
// El tren: A aislado al principio, B y C con A todavia abierta (C con A y B),
// D cuando la ranura de A ya cerro y espera al publicador, y E aislado. Con una
// ranura B y C se pierden con la ventana abierta y D por la espera de los
// divisores; con dos, B abre la segunda y solo se pierden C (las dos midiendo)
// y D (una midiendo y la otra esperando publicar).
//
// Regenerar: python3 tm_cronograma.py --sim
//=============================================================================
module tb_tm_cronograma;
  localparam integer DW   = 14;
  localparam integer NCYC = 240;    // ciclos que se vuelcan
  localparam real    TAU  = 30.0;   // cola de los pulsos, en muestras
  localparam integer LAT  = 2;      // muestra -> ventana dentro de mca_top

  reg clk = 1'b0;
  always #4 clk = ~clk;
  reg rstn = 1'b0;

  // Tren de pulsos: ciclo del pie y amplitud
  localparam integer NP = 5;
  integer p_t [0:NP-1];
  real    p_a [0:NP-1];
  initial begin
    p_t[0] = 10;  p_a[0] = 400.0;   // A
    p_t[1] = 30;  p_a[1] = 300.0;   // B, con A abierta
    p_t[2] = 48;  p_a[2] = 350.0;   // C, con A y B abiertas
    p_t[3] = 64;  p_a[3] = 250.0;   // D, con A esperando publicar
    p_t[4] = 160; p_a[4] = 400.0;   // E
  end

  // Subida de una muestra a media altura y cola exponencial
  function automatic real pulso(input integer k, input real a);
    if      (k <  0) pulso = 0.0;
    else if (k == 0) pulso = a / 2.0;
    else             pulso = a * $exp(-(k - 1) / TAU);
  endfunction

  reg signed [DW-1:0] x_in = '0;
  reg                 trig = 1'b0;

  // Bus compartido; un wen por instancia
  reg [31:0] addr = '0, wdata = '0;
  reg [1:0]  wen  = 2'b00;
  wire [31:0] rd0, rd1;
  wire        err0, err1, ack0, ack1;

  mca_top #(.H_AW(13), .H2_AW(7), .PSD_AW(6)) u0 (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i({x_in, x_in}), .mca_val_i(2'b11),
    .veto_i(1'b0), .trig_i(trig), .trig_arm_i(1'b1),
    .sys_addr(addr), .sys_wdata(wdata), .sys_wen(wen[0]), .sys_ren(1'b0),
    .sys_rdata(rd0), .sys_err(err0), .sys_ack(ack0));

  mca_top #(.H_AW(13), .H2_AW(7), .PSD_AW(6)) u1 (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .mca_dat_i({x_in, x_in}), .mca_val_i(2'b11),
    .veto_i(1'b0), .trig_i(trig), .trig_arm_i(1'b1),
    .sys_addr(addr), .sys_wdata(wdata), .sys_wen(wen[1]), .sys_ren(1'b0),
    .sys_rdata(rd1), .sys_err(err1), .sys_ack(ack1));

  task automatic wr(input [1:0] m, input [31:0] a, input [31:0] d);
    @(negedge clk); addr = a; wdata = d; wen = m;
    @(negedge clk); wen = 2'b00;
    repeat (8) @(negedge clk);
  endtask

  // Estado de una ranura para el CSV: 0 libre, 1 midiendo (o reservada para
  // abrir), 2 cerrada esperando publicar
  `define EST(u, k) ((u.i_feat.i_win.reserva_q[k]) ? 1 : u.i_feat.i_win.g_slot[k].i_slot.est)

  // Una instancia, en el orden de la cabecera del CSV
  `define FILA(u) \
    `EST(u,0), `EST(u,1), `EST(u,2), `EST(u,3), \
    u.dt_win, u.dt_div, u.puede_abrir, u.n_ocup, u.arribo, u.bloqueado, \
    u.dead_len, u.cnt_dead_periods, u.cnt_dead_ext, u.max_dead_len, \
    u.c_open, u.c_lost_active, u.c_lost, \
    u.t_win_cnt, u.t_div_cnt, u.livetime_cnt, u.realtime_cnt, \
    u.t_ocup_cnt[0], u.t_ocup_cnt[1], u.t_ocup_cnt[2], u.t_ocup_cnt[3], u.t_ocup_cnt[4], \
    u.ev_valid, u.c_pileup

  integer fd, n, i;
  string  csv, cab;
  real    acc;

  initial begin
    if (!$value$plusargs("CSV=%s", csv)) csv = "tm_cronograma.csv";
    fd = $fopen(csv, "w");
    cab = "s0,s1,s2,s3,win,div,ok,ocup,arribo,bloq,dlen,per,ext,maxl,open,lact,lbusy,tw,td,tl,rt,o0,o1,o2,o3,o4,ev,pile";
    $fdisplay(fd, "n,x,trig,%s,%s", prefijo("u0", cab), prefijo("u1", cab));

    repeat (10) @(negedge clk);
    rstn = 1'b1;
    repeat (4) @(negedge clk);

    wr(2'b11, 32'h01C, 0);                    // base fija en 0
    wr(2'b11, 32'h020, 32'h60);               // seguidor apagado
    wr(2'b11, 32'h04C, (40 << 16) | 8);       // gate_long = 40, gate_short = 8
    wr(2'b11, 32'h124, 0);                    // sin retardo extra
    wr(2'b01, 32'h120, 1);                    // u0: una ranura
    wr(2'b10, 32'h120, 2);                    // u1: dos ranuras

    // run = 1 en los dos a la vez; la escena arranca unos ciclos despues
    @(negedge clk); addr = 32'h00C; wdata = 1; wen = 2'b11;
    @(negedge clk); wen = 2'b00;
    repeat (4) @(negedge clk);

    for (n = 0; n < NCYC; n = n + 1) begin
      // Se vuelca ANTES de cambiar la entrada: todo lo de la fila es estable
      // entre dos flancos.
      $fdisplay(fd, "%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
                n, $signed(u0.dat_q), trig, `FILA(u0), `FILA(u1));
      acc = 0.0;
      for (i = 0; i < NP; i = i + 1) acc = acc + pulso(n - p_t[i], p_a[i]);
      x_in = $rtoi(acc + 0.5);
      // el disparo de cada pulso, LAT ciclos despues de su pie: cuando el pie
      // llega a la ventana
      trig = 1'b0;
      for (i = 0; i < NP; i = i + 1) if (n == p_t[i] + LAT) trig = 1'b1;
      @(negedge clk);
    end

    $fclose(fd);
    $finish;
  end

  function automatic string prefijo(input string p, input string campos);
    string out, c;
    out = ""; c = "";
    foreach (campos[i]) begin
      if (campos[i] == ",") begin out = {out, p, "_", c, ","}; c = ""; end
      else c = {c, campos[i]};
    end
    return {out, p, "_", c};
  endfunction
endmodule
