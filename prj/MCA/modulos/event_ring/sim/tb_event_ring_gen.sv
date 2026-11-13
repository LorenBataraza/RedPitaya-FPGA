`timescale 1ns/1ps
// tb_event_ring_gen — el ring entero con el generador PRENDIDO (EN_GEN = 1):
// lo que se va a hacer en la placa para medir la tasa, pero con la DDR de mentira.
//
// Un "PS" lee WR_SLOT, verifica cada slot nuevo y devuelve los creditos por
// RD_SLOT, con una demora por slot que se elige por escenario (asi aparecen los
// DROP_FULL). De cada slot verifica:
//   - el footer {~seq, seq} y que los seq guardados son 0, 1, 2, ...
//   - el snapshot {1, k}: k crece, y los huecos son los descartados
//   - el ts contra el modelo de Python (los vectores de gen_eventos), uno por uno
//   - las 2 x (pre + post) muestras: ch0[j] = ts - pre + j, ch1[j] = ~ch0[j] (14 b)
// Y al final de cada escenario, que cierra
//       EV_CNT + DROP_BUSY + DROP_FULL == GEN_CNT     y     slots leidos == EV_CNT
//
// Escenarios:
//   A. periodico, cada 200: no se pierde nada
//   B. aleatorio p = 0.02, DT_MIN = 5 (54 ciclos de media) contra los vectores:
//      la captura (64 ciclos por ventana) pierde por DROP_BUSY
//   C. periodico cada 100 con un PS lento: el ring se llena, DROP_FULL
//   D. se para el ring con el generador andando: la cuenta sigue cerrando
module tb_event_ring_gen;

  localparam integer DW = 14, N_CH = 2;
  localparam integer PRE_AW = 11, S_AW = 11, DATA_AW = 9, E = 4;   // stage chica
  localparam integer SLOT_SHIFT = 8;                 // 256 B: entran 32 muestras x 2
  localparam integer SLOT_W     = (1 << SLOT_SHIFT) / 8;
  localparam integer N_SLOTS    = 16;
  localparam [31:0]  RING_BASE  = 32'h1000_0000;
  localparam [31:0]  RING_SZ    = N_SLOTS * (1 << SLOT_SHIFT);
  localparam integer PRE = 8, POST = 24;
  localparam [19:0]  G = 20'h100;                   // base del generador

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  reg  [N_CH*DW-1:0] dat = 0;
  reg                dv = 1, trig = 0;
  reg  [16:0]        snap = 17'h2;
  wire [31:0] axi_waddr; wire [63:0] axi_wdata; wire [7:0] axi_wsel; wire [2:0] axi_wsize;
  wire        axi_wvalid; wire [3:0] axi_wlen; wire axi_wfixed;
  reg  [31:0] sys_addr = 0, sys_wdata = 0;
  reg         sys_wen = 0, sys_ren = 0;
  wire [31:0] sys_rdata; wire sys_err, sys_ack;

  event_ring_top #(.DW(DW), .N_CH(N_CH), .PRE_AW(PRE_AW), .S_AW(S_AW), .DATA_AW(DATA_AW),
                   .E(E), .EN_GEN(1)) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .dat_i(dat), .dv_i(dv), .trig_i(trig), .snapshot_i(snap),
    .axi_waddr_o(axi_waddr), .axi_wdata_o(axi_wdata), .axi_wsel_o(axi_wsel),
    .axi_wsize_o(axi_wsize), .axi_wvalid_o(axi_wvalid), .axi_wlen_o(axi_wlen),
    .axi_wfixed_o(axi_wfixed), .axi_werr_i(1'b0), .axi_wrdy_i(1'b1),
    .sys_addr(sys_addr), .sys_wdata(sys_wdata), .sys_wen(sys_wen), .sys_ren(sys_ren),
    .sys_rdata(sys_rdata), .sys_err(sys_err), .sys_ack(sys_ack));

  //--------------------------------------------------------------------------
  integer pass_cnt = 0, fail_cnt = 0;
  task automatic check(input string name, input bit cond);
    if (cond) pass_cnt++; else begin fail_cnt++; $display("  FAIL: %s", name); end
  endtask
  task automatic checkv(input string name, input longint got, input longint exp);
    if (got === exp) pass_cnt++;
    else begin fail_cnt++; $display("  FAIL: %s (%0d, esperaba %0d)", name, got, exp); end
  endtask

  // El bus es uno solo: el "PS" y el que configura no lo usan a la vez.
  semaphore bus = new(1);
  task automatic bus_wr(input [19:0] a, input [31:0] d);
    bus.get();
    @(negedge clk); sys_addr = {12'h0, a}; sys_wdata = d; sys_wen = 1;
    @(negedge clk); sys_wen = 0;
    while (!sys_ack) @(negedge clk);
    bus.put();
  endtask
  task automatic bus_rd(input [19:0] a, output [31:0] d);
    bus.get();
    @(negedge clk); sys_addr = {12'h0, a}; sys_ren = 1;
    @(negedge clk); sys_ren = 0;
    while (!sys_ack) @(negedge clk);
    d = sys_rdata;
    bus.put();
  endtask

  // DDR direccionada, como en tb_event_ring_top
  reg [63:0] ddr [0:N_SLOTS*SLOT_W-1];
  integer fuera_de_rango = 0;
  always @(posedge clk)
    if (axi_wvalid) begin
      if (axi_waddr < RING_BASE || axi_waddr >= RING_BASE + RING_SZ) fuera_de_rango++;
      else ddr[(axi_waddr - RING_BASE) >> 3] = axi_wdata;
    end

  //--------------------------------------------------------------------------
  // El "PS": lee los slots nuevos, los verifica y devuelve los creditos
  //--------------------------------------------------------------------------
  longint esperado[$];        // ts de cada disparo k, del modelo (vacio: no se mira)
  integer demora_slot = 0;    // ciclos que tarda el PS por slot
  bit     ps_corre = 0;
  integer leidos, mal_footer, mal_seq, mal_snap, mal_ts, mal_muestra, k_ultimo, perdidos_vistos;
  reg [31:0] rd_ps;

  task automatic reiniciar_ps();
    leidos = 0; mal_footer = 0; mal_seq = 0; mal_snap = 0; mal_ts = 0; mal_muestra = 0;
    k_ultimo = -1; perdidos_vistos = 0; rd_ps = 0;
  endtask

  // El commit: WR_SLOT avanza cuando el footer ENTRA al axi_wr_fifo, no cuando
  // llega a la DDR. Como el lector de C, el PS mira el footer con el seq que
  // espera y, si todavia no esta, corta el lote y vuelve despues.
  function automatic bit comprometido(input integer s, input integer seq);
    comprometido = (ddr[(s % N_SLOTS) * SLOT_W + SLOT_W - 1] === {~seq[31:0], seq[31:0]});
  endfunction

  task automatic verificar_slot(input integer s);
    reg [63:0] w0, w1, w2, wf, w;
    reg [31:0] seq; reg [15:0] nsamp; reg [16:0] sn;
    integer k, j, idx; reg [15:0] m; reg [DW-1:0] e0;
    integer base = (s % N_SLOTS) * SLOT_W;
    w0 = ddr[base]; w1 = ddr[base + 1]; w2 = ddr[base + 2]; wf = ddr[base + SLOT_W - 1];
    seq = w1[31:0]; nsamp = w1[47:32]; sn = w2[16:0];
    if (wf !== {~seq, seq}) begin
      if (mal_footer < 3) $display("  slot %0d (seq %0d, leidos %0d, ev ?): footer %016h  t=%0t", s, seq, leidos, wf, $time);
      mal_footer++;
    end
    if (seq !== leidos) mal_seq++;
    if (nsamp !== PRE + POST || w1[55:48] !== N_CH) mal_seq++;
    k = sn[15:0];
    if (!sn[16] || k <= k_ultimo) mal_snap++;
    perdidos_vistos += k - k_ultimo - 1;
    k_ultimo = k;
    if (esperado.size() > k && w0 !== esperado[k]) begin
      if (mal_ts < 3) $display("  slot %0d (k = %0d): ts %0d, el modelo dice %0d", s, k, w0, esperado[k]);
      mal_ts++;
    end
    for (j = 0; j < N_CH * (PRE + POST); j++) begin
      idx = 4 + j / 4;                                // las muestras desde 0x20
      w = ddr[base + idx];
      m = w[16 * (j % 4) +: 16];
      e0 = w0 - PRE + j / N_CH;
      if (m[DW-1:0] !== ((j % N_CH) ? ~e0 : e0) || m[15:DW] !== {(16-DW){m[DW-1]}}) begin
        if (mal_muestra < 3) $display("  slot %0d muestra %0d: %04h, esperaba %04h", s, j, m[DW-1:0],
                                      (j % N_CH) ? ~e0 : e0);
        mal_muestra++;
      end
    end
    leidos++;
  endtask

  // WR_SLOT vuelve a 0 con el ring en STOPPED (flush), asi que un WR_SLOT que
  // "va para atras" no se persigue: lo que queda se lee despues, hasta EV_CNT.
  bit ps_ocupado = 0;
  initial begin : ps
    reg [31:0] wr, nuevos;
    forever begin
      @(negedge clk);
      if (ps_corre) begin
        ps_ocupado = 1;
        bus_rd(20'h20, wr);
        nuevos = wr - rd_ps;
        if (nuevos != 0 && nuevos <= N_SLOTS) begin
          while (rd_ps != wr && comprometido(rd_ps, leidos)) begin
            verificar_slot(rd_ps);
            repeat (demora_slot) @(negedge clk);
            rd_ps++;
          end
          bus_wr(20'h24, rd_ps);                   // los creditos, por lote
        end
        ps_ocupado = 0;
      end
    end
  end

  //--------------------------------------------------------------------------
  task automatic cargar(input string nombre, inout longint q[$]);
    integer fd, r; reg [31:0] v;
    q.delete();
    fd = $fopen({"../../gen_eventos/sim/vectores/gen_", nombre, ".hex"}, "r");
    if (fd == 0) begin fail_cnt++; $display("  FAIL: no encuentro gen_%s.hex", nombre); return; end
    while (!$feof(fd)) begin r = $fscanf(fd, "%h\n", v); if (r == 1) q.push_back(v); end
    $fclose(fd);
  endtask

  // Una corrida: arranca el ring (el generador ya configurado), espera, para,
  // deja que el PS se ponga al dia y verifica todo.
  task automatic corrida(input string nombre, input integer ciclos, input bit cortar_andando = 0);
    reg [31:0] st, ev, db, df, gc;
    $display("[%s] arranca en %0t", nombre, $time);
    reiniciar_ps();
    bus_wr(20'h00, 32'h2);                    // clr: contadores y punteros a cero
    bus_wr(20'h24, 32'h0);
    ps_corre = 1;
    bus_wr(20'h00, 32'h1);                    // run: el generador arranca con el ring
    repeat (ciclos) @(negedge clk);
    bus_wr(20'h00, 32'h0);                    // DRAINING -> STOPPED
    $display("[%s] parando en %0t", nombre, $time);
    do bus_rd(20'h04, st); while (st[2:0] != 0);   // el PS sigue devolviendo creditos
    ps_corre = 0;
    wait (!ps_ocupado);
    bus_rd(20'h38, ev); bus_rd(20'h30, db); bus_rd(20'h34, df); bus_rd(G + 20'h18, gc);
    // lo que el writer termino de escribir y el PS no llego a ver por WR_SLOT
    while (rd_ps < ev) begin verificar_slot(rd_ps); rd_ps++; end
    $display("[%s] GEN_CNT %0d = EV %0d + DROP_BUSY %0d + DROP_FULL %0d; leidos %0d", nombre, gc, ev, db, df, leidos);
    checkv({nombre, ": EV + DROP_BUSY + DROP_FULL = GEN_CNT"}, ev + db + df, gc);
    checkv({nombre, ": slots leidos = EV_CNT"}, leidos, ev);
    checkv({nombre, ": los huecos de k = los descartados"}, perdidos_vistos + (gc - 1 - k_ultimo), db + df);
    checkv({nombre, ": footers"}, mal_footer, 0);
    checkv({nombre, ": seq 0, 1, 2, ... y la cabecera"}, mal_seq, 0);
    checkv({nombre, ": snapshot {1, k} creciente"}, mal_snap, 0);
    checkv({nombre, ": ts contra el modelo"}, mal_ts, 0);
    checkv({nombre, ": muestras contra el patron"}, mal_muestra, 0);
    check ({nombre, ": hubo eventos"}, ev > 10);
  endtask

  //--------------------------------------------------------------------------
  reg [31:0] rv;
  reg [31:0] ev0, db0, df0;
  initial begin
    repeat (4) @(posedge clk); rstn = 1; repeat (4) @(posedge clk);

    bus_rd(G + 20'h20, rv); checkv("MAGIC del generador en 0x120", rv, 32'h4745_4E31);
    bus_rd(20'h50, rv);     checkv("MAGIC del ring sigue en 0x50", rv, 32'h4556_4E54);
    bus_wr(20'h08, RING_BASE); bus_wr(20'h0C, RING_SZ); bus_wr(20'h10, SLOT_SHIFT);
    bus_wr(20'h14, PRE); bus_wr(20'h18, POST);
    bus_rd(20'h2C, rv); checkv("N_SLOTS", rv, N_SLOTS);

    // A. periodico cada 200 -------------------------------------------------
    esperado.delete(); for (int k = 0; k < 400; k++) esperado.push_back(201 + 200 * k);
    bus_wr(G + 20'h04, 200); bus_wr(G + 20'h00, 32'h5);      // en + patron
    demora_slot = 0;
    corrida("A periodico 200", 40000);
    bus_rd(20'h30, db0); bus_rd(20'h34, df0);
    checkv("A: sin descartes", db0 + df0, 0);

    // B. aleatorio contra el modelo -------------------------------------------
    cargar("aleat_p02_dt5", esperado);
    bus_wr(G + 20'h08, 32'd85899346); bus_wr(G + 20'h0C, 5); bus_wr(G + 20'h14, 32'h1234_5678);
    bus_wr(G + 20'h00, 32'h7);                               // en + aleatorio + patron
    corrida("B aleatorio p 0.02", 19000);
    bus_rd(20'h30, db0); check("B: la captura pierde por DROP_BUSY", db0 > 0);

    // C. un PS lento: se llena el ring ----------------------------------------
    esperado.delete(); for (int k = 0; k < 2000; k++) esperado.push_back(101 + 100 * k);
    bus_wr(G + 20'h04, 100); bus_wr(G + 20'h00, 32'h5);
    demora_slot = 400;
    corrida("C PS lento", 60000);
    bus_rd(20'h34, df0); check("C: el ring se lleno (DROP_FULL)", df0 > 0);
    demora_slot = 0;

    // D. parar el ring con el generador andando, en un momento cualquiera ------
    esperado.delete();
    bus_wr(G + 20'h08, 32'h1000_0000); bus_wr(G + 20'h0C, 2); bus_wr(G + 20'h00, 32'h7);
    for (int r = 0; r < 3; r++) corrida($sformatf("D cortado %0d", r), 3000 + 37 * r);

    bus_wr(G + 20'h00, 0);
    checkv("ninguna escritura fuera del ring", fuera_de_rango, 0);
    $display("tb_event_ring_gen: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
    $finish;
  end

  initial begin #50ms; $display("RESULT: FAIL (timeout global)"); $finish; end
endmodule
