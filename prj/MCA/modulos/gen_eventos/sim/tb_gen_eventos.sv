`timescale 1ns/1ps
// tb_gen_eventos — el generador solo, con un ring de mentira: run_i y el reloj ts
// (que vuelve a 0 mientras no corre, como ts_cnt de event_ring_top).
//
//   1. registros: MAGIC, reset, RW, lo no mapeado, el ack de latencia fija
//   2. apagado: es un cable (las salidas son las entradas del mismo ciclo)
//   3. patron: ch0 = ts, ch1 = ~ts (del mismo ciclo), con el disparo real
//   4. periodico: cada PERIODO desde ts = PERIODO + 1, snapshot {1, k}, GEN_CNT
//   5. los minimos: PERIODO = 0 o 1 da un disparo cada 2 ciclos, sin fundirse
//   6. N: exactamente N y ESTADO = hecho
//   7. aleatorio contra el modelo de Python (sim/vectores/gen_*.hex), ciclo a ciclo,
//      y la misma secuencia al rearrancar el ring
//   8. el ring sale de RUNNING a mitad: ningun pulso afuera, y GEN_CNT = los que salieron
//
// Los vectores: python3 ../modelos/python_model/gen_eventos_model.py --vectores
module tb_gen_eventos;
  localparam integer N_CH = 2, DW = 14;

  reg clk = 0;
  always #4 clk = ~clk;
  reg rstn = 0;

  reg  [N_CH*DW-1:0] dat_i  = 0;
  reg                dv_i   = 1;
  reg                trig_i = 0;
  reg  [16:0]        snap_i = 0;
  reg                run    = 0;
  reg  [63:0]        ts     = 0;
  always @(posedge clk) ts <= run ? ts + 1 : 64'd0;

  wire [N_CH*DW-1:0] dat_o;
  wire               dv_o, trig_o;
  wire [16:0]        snap_o;
  reg  [31:0]        a = 0, wd = 0;
  reg                wen = 0, ren = 0;
  wire [31:0]        rd;
  wire               err, ack;

  gen_eventos #(.N_CH(N_CH), .DW(DW)) dut (
    .clk_i(clk), .rstn_i(rstn),
    .dat_i(dat_i), .dv_i(dv_i), .trig_i(trig_i), .snap_i(snap_i),
    .ts_i(ts), .run_i(run),
    .dat_o(dat_o), .dv_o(dv_o), .trig_o(trig_o), .snap_o(snap_o),
    .sys_addr(a), .sys_wdata(wd), .sys_wen(wen), .sys_ren(ren),
    .sys_rdata(rd), .sys_err(err), .sys_ack(ack)
  );

  bind gen_eventos gen_eventos_sva u_sva (.*);

  //--------------------------------------------------------------------------
  integer pass_cnt = 0, fail_cnt = 0;
  task automatic checkv(input string name, input longint got, input longint exp);
    if (got === exp) pass_cnt++;
    else begin fail_cnt++; $display("FAIL %s: %0d (0x%0h), esperaba %0d (0x%0h)", name, got, got, exp, exp); end
  endtask
  task automatic check(input string name, input bit cond);
    if (cond) pass_cnt++;
    else begin fail_cnt++; $display("FAIL %s", name); end
  endtask

  task automatic wr(input [31:0] addr, input [31:0] data);
    @(negedge clk); a = addr; wd = data; wen = 1;
    @(negedge clk); wen = 0;
    while (!ack) @(negedge clk);
  endtask
  integer lat;
  task automatic rdr(input [31:0] addr, output [31:0] data);
    @(negedge clk); a = addr; ren = 1; lat = 0;
    @(negedge clk); ren = 0;
    while (!ack) begin @(negedge clk); lat++; end
    data = rd;
  endtask

  //--------------------------------------------------------------------------
  // Monitor: los pulsos que salen (ts del ciclo del pulso, como lo toma la
  // captura), el snapshot de cada uno, y las salidas contra las entradas.
  //--------------------------------------------------------------------------
  longint pulsos[$];
  integer snap_mal = 0, paso_mal = 0, patron_mal = 0, fuera = 0;
  bit     mirar_paso = 0, mirar_patron = 0;
  reg [N_CH*DW-1:0] dat_d;
  reg               dv_d, trig_d;
  reg [16:0]        snap_d;
  reg [63:0]        ts_d;
  reg               run_q = 0;
  integer           desde_arranque = 0;   // pulsos desde que el ring arranco: GEN_CNT
  always @(posedge clk) begin
    run_q <= run;
    if (rstn) begin
      if (run && !run_q) desde_arranque = 0;
      if (trig_o && dut.cfg_en) desde_arranque = desde_arranque + 1;
      if (trig_o && dut.cfg_en) begin
        if (snap_o !== {1'b1, pulsos.size()[15:0]}) snap_mal++;
        if (!run) fuera++;
        pulsos.push_back(ts);
      end
      if (mirar_paso && (dat_o !== dat_i || dv_o !== dv_i || trig_o !== trig_i || snap_o !== snap_i))
        paso_mal++;
      if (mirar_patron && (dat_o[DW-1:0] !== ts[DW-1:0] || dat_o[2*DW-1:DW] !== ~ts[DW-1:0]))
        patron_mal++;
    end
    dat_d <= dat_i; dv_d <= dv_i; trig_d <= trig_i; snap_d <= snap_i; ts_d <= ts;
  end

  // estimulo de la "cadena del scope": cambia en cada flanco de bajada
  bit ruido = 0;
  always @(negedge clk) if (ruido) begin
    dat_i  <= {$urandom, $urandom};
    trig_i <= ($urandom_range(0, 9) == 0);
    snap_i <= $urandom;
  end

  task automatic arrancar();  @(negedge clk); run = 1; endtask
  task automatic parar();     @(negedge clk); run = 0; endtask
  task automatic esperar(input integer n); repeat (n) @(negedge clk); endtask

  // Los vectores del modelo: los ts de los disparos, uno por linea.
  task automatic cargar(input string nombre, inout longint q[$]);
    integer fd, r; reg [31:0] v;
    q.delete();
    fd = $fopen({"../sim/vectores/gen_", nombre, ".hex"}, "r");
    if (fd == 0) begin fail_cnt++; $display("FAIL no encuentro gen_%s.hex", nombre); return; end
    while (!$feof(fd)) begin r = $fscanf(fd, "%h\n", v); if (r == 1) q.push_back(v); end
    $fclose(fd);
  endtask

  task automatic comparar(input string nombre, input longint esp[$], input longint hasta);
    integer n = 0, m = 0, mal = 0;
    foreach (esp[i]) if (esp[i] < hasta) n++;
    foreach (pulsos[i]) if (pulsos[i] < hasta) m++;   // el RTL corre unos ciclos de mas
    checkv({nombre, ": cantidad de disparos"}, m, n);
    for (int i = 0; i < n && i < pulsos.size(); i++)
      if (pulsos[i] != esp[i]) begin
        if (mal < 3) $display("  %s: disparo %0d en ts %0d, el modelo dice %0d", nombre, i, pulsos[i], esp[i]);
        mal++;
      end
    checkv({nombre, ": los ts, uno por uno"}, mal, 0);
  endtask

  //--------------------------------------------------------------------------
  reg [31:0] d;
  longint vec[$], prim[$];
  integer gaps_mal;
  initial begin
    repeat (5) @(negedge clk);
    rstn = 1;
    esperar(2);

    // 1) registros -----------------------------------------------------------
    rdr(32'h20, d); checkv("MAGIC", d, 32'h4745_4E31);
    checkv("ack de latencia fija", lat, 2);
    rdr(32'h00, d); checkv("reset: CTRL", d, 0);
    rdr(32'h04, d); checkv("reset: PERIODO", d, 1000);
    rdr(32'h0C, d); checkv("reset: DT_MIN", d, 2);
    rdr(32'h18, d); checkv("reset: GEN_CNT", d, 0);
    begin
      automatic reg [31:0] dirs [0:4] = '{32'h04, 32'h08, 32'h0C, 32'h10, 32'h14};
      automatic reg [31:0] masc [0:4] = '{32'hFFFF_FFFF, 32'hFFFF_FFFF, 32'h0000_FFFF, 32'hFFFF_FFFF, 32'hFFFF_FFFF};
      for (int i = 0; i < 5; i++) begin
        wr(dirs[i], 32'hA5A5_0000 + i); rdr(dirs[i], d);
        checkv($sformatf("RW 0x%02h", dirs[i]), d, (32'hA5A5_0000 + i) & masc[i]);
      end
    end
    wr(32'h00, 32'hFFFF_FFFF); rdr(32'h00, d); checkv("RW CTRL (3 bits)", d, 7);
    wr(32'h00, 0);
    wr(32'h18, 32'd55); rdr(32'h18, d); checkv("GEN_CNT es de solo lectura", d, 0);
    rdr(32'h24, d); checkv("no mapeado lee 0", d, 0);
    rdr(32'hFC, d); checkv("no mapeado lee 0 (0xFC)", d, 0);
    check("sys_err nunca", err === 1'b0);

    // 2) apagado: todo pasa un ciclo tarde ------------------------------------
    ruido = 1; esperar(3);
    mirar_paso = 1;
    arrancar(); esperar(500); parar(); esperar(500); arrancar(); esperar(300); parar();
    mirar_paso = 0;
    checkv("apagado: las salidas son las entradas, en el mismo ciclo", paso_mal, 0);

    // 3) patron, con el disparo real ------------------------------------------
    wr(32'h00, 32'h4);                    // patron, sin generar
    esperar(3); mirar_patron = 1;
    arrancar(); esperar(20000); parar(); esperar(50);
    mirar_patron = 0;
    checkv("patron: ch0 = ts y ch1 = ~ts, dando la vuelta a 2^14", patron_mal, 0);
    begin
      automatic integer trig_mal = 0;
      for (int i = 0; i < 200; i++) begin
        @(negedge clk); if (trig_o !== trig_i) trig_mal++;
      end
      checkv("patron: el disparo real sigue pasando", trig_mal, 0);
    end
    wr(32'h00, 0);

    // 4) periodico ------------------------------------------------------------
    wr(32'h04, 32'd10); wr(32'h10, 0);
    wr(32'h00, 32'h1);
    pulsos.delete();
    arrancar(); esperar(1003); parar(); esperar(5);
    vec.delete(); for (int k = 0; k < 100; k++) vec.push_back(11 + 10 * k);
    comparar("periodico 10", vec, 1003);
    rdr(32'h18, d); checkv("periodico: GEN_CNT = los que salieron", d, pulsos.size());
    checkv("periodico: snapshot {1, k} en cada uno", snap_mal, 0);
    checkv("periodico: el disparo real no pasa", fuera, 0);

    // 5) los minimos ------------------------------------------------------------
    for (int p = 0; p < 3; p++) begin
      wr(32'h04, p); pulsos.delete();
      arrancar(); esperar(200); parar(); esperar(5);
      gaps_mal = 0;
      for (int i = 1; i < pulsos.size(); i++) if (pulsos[i] - pulsos[i-1] != 2) gaps_mal++;
      checkv($sformatf("PERIODO = %0d: un disparo cada 2 ciclos", p), gaps_mal, 0);
      check($sformatf("PERIODO = %0d: ~100 disparos en 200 ciclos (%0d)", p, pulsos.size()),
            pulsos.size() >= 98 && pulsos.size() <= 100);
    end

    // 6) N ----------------------------------------------------------------------
    wr(32'h04, 32'd7); wr(32'h10, 32'd5); pulsos.delete();
    arrancar(); esperar(400);
    checkv("N = 5: cinco disparos", pulsos.size(), 5);
    rdr(32'h1C, d); checkv("N = 5: ESTADO = hecho, sin generar", d, 2);
    rdr(32'h18, d); checkv("N = 5: GEN_CNT", d, 5);
    parar(); esperar(5);
    wr(32'h10, 0);

    // 7) aleatorio contra el modelo ----------------------------------------------
    // El modelo cuenta N_CICLOS_VECTORES = 20000 ciclos de decision: el ultimo
    // disparo posible sale en ts = 20001.
    cargar("aleat_p02_dt5", vec);
    wr(32'h08, 32'd85899346);             // round(2^32 * 0.02)
    wr(32'h0C, 32'd5); wr(32'h14, 32'h1234_5678);
    wr(32'h00, 32'h3);
    pulsos.delete(); snap_mal = 0;
    arrancar(); esperar(20010); parar(); esperar(5);
    comparar("aleatorio p = 0.02, DT_MIN = 5", vec, 20002);
    checkv("aleatorio: snapshot {1, k}", snap_mal, 0);
    gaps_mal = 0;
    for (int i = 1; i < pulsos.size(); i++) if (pulsos[i] - pulsos[i-1] < 5) gaps_mal++;
    checkv("aleatorio: nunca menos de DT_MIN", gaps_mal, 0);
    // rearrancar el ring: la misma secuencia
    prim = pulsos; pulsos.delete();
    arrancar(); esperar(20010); parar(); esperar(5);
    comparar("aleatorio, rearrancado", prim, 20002);

    cargar("aleat_p50_dt2", vec);
    wr(32'h08, 32'h8000_0000); wr(32'h0C, 32'd0); wr(32'h14, 32'd0);   // DT_MIN 0 -> 2, semilla 0 -> la de siempre
    wr(32'h00, 32'h3);                    // prender en de nuevo no hace falta: arranca con el ring
    pulsos.delete(); snap_mal = 0;
    arrancar(); esperar(20010); parar(); esperar(5);
    comparar("aleatorio p = 0.5, DT_MIN = 2", vec, 20002);
    checkv("p = 0.5: snapshot {1, k}", snap_mal, 0);

    // 8) el ring sale de RUNNING a mitad -----------------------------------------
    fuera = 0; pulsos.delete();
    arrancar();
    for (int i = 0; i < 400; i++) begin
      esperar($urandom_range(1, 40));
      @(negedge clk); run = $urandom_range(0, 1);
    end
    parar(); esperar(5);
    checkv("con el ring entrando y saliendo: ningun pulso afuera", fuera, 0);
    rdr(32'h18, d);
    checkv("GEN_CNT = los pulsos desde el ultimo arranque", d, desde_arranque);

    // 9) el ring sale de RUNNING justo cuando hay un disparo decidido: el pulso
    //    no sale, y GEN_CNT no lo cuenta (si no, EV + DROP != GEN_CNT)
    wr(32'h00, 32'h1); wr(32'h04, 32'd10);
    for (int r = 0; r < 3; r++) begin
      arrancar();
      esperar(25 + r);
      while (!dut.disp_c) @(negedge clk);
      // justo despues del flanco que registra la decision (trig_gen = 1): el
      // pulso saldria en este ciclo, pero el ring ya no esta en RUNNING
      @(posedge clk); #1 run = 0;
      check($sformatf("cortado (%0d): hay un disparo decidido en vuelo", r), dut.trig_gen === 1'b1);
      esperar(5);
      rdr(32'h18, d);
      checkv($sformatf("cortado con un disparo decidido (%0d): GEN_CNT = los que salieron", r), d, desde_arranque);
    end

    wr(32'h00, 0);
    ruido = 0;
    esperar(10);
    $display("tb_gen_eventos: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #20ms;
    $display("RESULT: FAIL (timeout global)");
    $finish;
  end
endmodule
