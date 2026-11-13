`timescale 1ns/1ps
// tb_gen_pulsos — el generador de pulsos solo, contra su modelo de Python.
//
//   1. registros: MAGIC, reset, RW con sus anchos, la tabla (con signo), lo no
//      mapeado, el ack de latencia fija
//   2. apagado: las dos salidas y el disparo en cero, con todo cargado
//   3. los vectores del modelo (sim/vectores/pul_*.txt), muestra por muestra y
//      pulso por pulso: periodico con signo, Poisson apilado con ruido y
//      saturacion, negativos con N, el desborde de y1, el periodo minimo
//      recorriendo la tabla entera. Y ESTADO (hecho, desborde) y GEN_CNT.
//   4. el mismo vector dos veces: el arranque lo reinicia todo
//   5. out1 / out2: cada canal por su bit
//   6. apagarlo a mitad: la salida a cero en el ciclo siguiente
//
// Los vectores: python3 ../modelos/python_model/gen_pulsos_model.py --vectores
module tb_gen_pulsos;
  localparam integer DW = 14, MAXC = 1 << 16;

  reg clk = 0;
  always #4 clk = ~clk;
  reg rstn = 0;

  wire [DW-1:0] dat_a, dat_b;
  wire          trig;
  reg  [31:0]   a = 0, wd = 0;
  reg           wen = 0, ren = 0;
  wire [31:0]   rd;
  wire          err, ack;

  gen_pulsos #(.DW(DW)) dut (
    .clk_i(clk), .rstn_i(rstn),
    .dat_a_o(dat_a), .dat_b_o(dat_b), .trig_o(trig),
    .sys_addr(a), .sys_wdata(wd), .sys_wen(wen), .sys_ren(ren),
    .sys_rdata(rd), .sys_err(err), .sys_ack(ack)
  );

  bind gen_pulsos gen_pulsos_sva u_sva (.*);

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

  // El generador vive en 0x4021_0000: el slot 2, segunda region de 64 KB.
  localparam [31:0] BASE = 32'h4021_0000;
  task automatic wr(input [15:0] off, input [31:0] data);
    @(negedge clk); a = BASE | off; wd = data; wen = 1;
    @(negedge clk); wen = 0;
    while (!ack) @(negedge clk);
  endtask
  integer lat;
  task automatic rdr(input [15:0] off, output [31:0] data);
    @(negedge clk); a = BASE | off; ren = 1; lat = 0;
    @(negedge clk); ren = 0;
    while (!ack) begin @(negedge clk); lat++; end
    data = rd;
  endtask
  task automatic esperar(input integer n); repeat (n) @(negedge clk); endtask

  //--------------------------------------------------------------------------
  // Los vectores: la configuracion, la tabla y lo que sale en cada ciclo
  //--------------------------------------------------------------------------
  integer c_aleat, c_per, c_umb, c_dtm, c_n, c_sem, c_amp_aleat, c_amp_n,
          c_decae, c_subida, c_base, c_ruido, c_sh, n_tab, n_cic, e_desb, e_pulsos;
  reg [DW-1:0] tab   [0:1023];
  reg [DW-1:0] e_dat [0:MAXC-1];
  reg          e_trg [0:MAXC-1];

  task automatic cargar(input string nombre, output bit ok);
    integer fd, r, t; reg [31:0] v;
    ok = 0;
    fd = $fopen({"../sim/vectores/pul_", nombre, ".txt"}, "r");
    if (fd == 0) begin fail_cnt++; $display("FAIL no encuentro pul_%s.txt", nombre); return; end
    r = $fscanf(fd, "%d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d\n",
                c_aleat, c_per, c_umb, c_dtm, c_n, c_sem, c_amp_aleat, c_amp_n,
                c_decae, c_subida, c_base, c_ruido, c_sh, n_tab, n_cic, e_desb, e_pulsos);
    for (int i = 0; i < 1024; i++) tab[i] = '0;
    for (int i = 0; i < n_tab; i++) begin r = $fscanf(fd, "%h\n", v); tab[i] = v[DW-1:0]; end
    for (int i = 0; i < n_cic; i++) begin r = $fscanf(fd, "%h %d\n", v, t); e_dat[i] = v[DW-1:0]; e_trg[i] = t[0]; end
    $fclose(fd);
    ok = (r == 2);
  endtask

  // Configura todo, carga la tabla entera (lo que no trae el vector, en cero:
  // la tabla guarda lo del vector anterior) y deja el generador apagado.
  task automatic configurar();
    wr(16'h0000, 0);
    wr(16'h0004, c_per);
    wr(16'h0008, c_umb);
    wr(16'h000C, c_dtm);
    wr(16'h0010, c_n);
    wr(16'h0014, c_sem);
    wr(16'h0024, c_decae);
    wr(16'h0028, c_subida);
    wr(16'h002C, c_amp_n);
    wr(16'h0030, c_base);
    wr(16'h0034, (c_ruido << 8) | c_sh);
    for (int i = 0; i < 1024; i++) wr(16'h1000 + 4 * i, {{(32-DW){tab[i][DW-1]}}, tab[i]});
  endtask

  // El monitor: desde el ciclo despues del arranque, cada muestra de los dos
  // canales y cada pulso contra el vector.
  integer g = -1, mal_dat = 0, mal_trg = 0, n_trg = 0;
  bit     armado = 0;
  always @(negedge clk) begin
    if (g >= 0 && g < n_cic) begin
      if (dat_a !== e_dat[g] || dat_b !== e_dat[g]) begin
        if (mal_dat < 4) $display("  ciclo %0d: dat %0d / %0d, el modelo dice %0d",
                                  g, $signed(dat_a), $signed(dat_b), $signed(e_dat[g]));
        mal_dat++;
      end
      if (trig !== e_trg[g]) begin
        if (mal_trg < 4) $display("  ciclo %0d: trig %0b, el modelo dice %0b", g, trig, e_trg[g]);
        mal_trg++;
      end
      if (trig) n_trg++;
      g++;
    end
    if (armado && dut.arranque) begin g = 0; armado = 0; end
  end

  // Corre un vector: lo prende con los dos canales y espera a que pase.
  task automatic correr(input string nombre);
    reg [31:0] d;
    mal_dat = 0; mal_trg = 0; n_trg = 0; g = -1;
    armado = 1;
    wr(16'h0000, 32'h1 | (c_aleat << 1) | (c_amp_aleat << 2) | (1 << 3) | (1 << 4));
    while (g < 0 || g < n_cic) @(negedge clk);
    g = -1;                                     // el monitor se calla hasta el proximo
    checkv({nombre, ": muestras distintas del modelo"}, mal_dat, 0);
    checkv({nombre, ": pulsos distintos del modelo"}, mal_trg, 0);
    checkv({nombre, ": cantidad de pulsos"}, n_trg, e_pulsos);
    rdr(16'h001C, d);
    checkv({nombre, ": ESTADO.desborde"}, d[2], e_desb);
    if (c_n != 0) begin
      checkv({nombre, ": ESTADO.hecho"}, d[1], 1);
      rdr(16'h0018, d);
      checkv({nombre, ": GEN_CNT = N"}, d, c_n);
    end
  endtask

  //--------------------------------------------------------------------------
  reg [31:0] d;
  bit ok;
  integer apagado_mal;
  string VECS [5] = '{"periodico_escalon", "poisson_apilado", "negativos_n", "desborde", "rafaga_tabla"};
  initial begin
    repeat (5) @(negedge clk);
    rstn = 1;
    esperar(5);

    // ---- 1. registros ----------------------------------------------------
    rdr(16'h0020, d); checkv("MAGIC", d, 32'h5055_4C31);
    checkv("ack de latencia fija", lat, 2);
    rdr(16'h0004, d); checkv("PERIODO en reset", d, 1000);
    rdr(16'h000C, d); checkv("DT_MIN en reset", d, 2);
    rdr(16'h0024, d); checkv("DECAE en reset", d, 65280);
    rdr(16'h0000, d); checkv("CTRL en reset", d, 0);
    rdr(16'h001C, d); checkv("ESTADO en reset", d, 0);
    wr(16'h0000, 32'hFFFF_FFFE);                 // todo menos en
    rdr(16'h0000, d); checkv("CTRL: 5 bits", d, 32'h1E);
    wr(16'h0000, 0);
    wr(16'h000C, 32'h1234_5678); rdr(16'h000C, d); checkv("DT_MIN: 16 bits", d, 32'h5678);
    wr(16'h0024, 32'hABCD_EF01); rdr(16'h0024, d); checkv("DECAE: 16 bits", d, 32'hEF01);
    wr(16'h0028, 32'hFFFF_FFFF); rdr(16'h0028, d); checkv("SUBIDA: 3 bits", d, 7);
    wr(16'h002C, 32'hFFFF_FFFF); rdr(16'h002C, d); checkv("AMP_N: 10 bits", d, 32'h3FF);
    wr(16'h0030, 32'h0000_2001); rdr(16'h0030, d); checkv("BASE: 14 bits con signo", d, 32'hFFFF_E001);
    wr(16'h0034, 32'hFFFF_FFFF); rdr(16'h0034, d); checkv("RUIDO: [8] y [3:0]", d, 32'h10F);
    wr(16'h0014, 32'hDEAD_BEEF); rdr(16'h0014, d); checkv("SEMILLA", d, 32'hDEAD_BEEF);
    wr(16'h1000, 32'h0000_1FFF); rdr(16'h1000, d); checkv("TABLA[0] positiva", d, 32'h1FFF);
    wr(16'h1FFC, 32'h0000_2000); rdr(16'h1FFC, d); checkv("TABLA[1023] negativa, con signo", d, 32'hFFFF_E000);
    rdr(16'h1000, d); checkv("TABLA[0] no la piso la 1023", d, 32'h1FFF);
    rdr(16'h0F00, d); checkv("no mapeado lee 0", d, 0);
    check("no mapeado: hay ack", lat == 2);

    // ---- 2. apagado ------------------------------------------------------
    wr(16'h0000, 32'h18);                        // out1 y out2, sin en
    apagado_mal = 0;
    repeat (2000) begin @(negedge clk); if (dat_a !== 0 || dat_b !== 0 || trig !== 0) apagado_mal++; end
    checkv("apagado: las salidas y el disparo en cero", apagado_mal, 0);

    // ---- 3. los vectores -------------------------------------------------
    foreach (VECS[i]) begin
      string v;
      v = VECS[i];
      cargar(v, ok);
      check({v, ": vector cargado"}, ok);
      if (!ok) continue;
      configurar();
      correr(v);
    end

    // ---- 4. el mismo vector otra vez -------------------------------------
    cargar("poisson_apilado", ok);
    configurar();
    correr("poisson_apilado, de nuevo");

    // ---- 5. cada canal por su bit ----------------------------------------
    begin
      automatic integer a_vivo = 0, b_vivo = 0;
      wr(16'h0000, 32'h1 | (1 << 1) | (1 << 2) | (1 << 3));      // solo out1
      repeat (3000) begin @(negedge clk); if (dat_a !== 0) a_vivo++; if (dat_b !== 0) b_vivo++; end
      check("solo out1: el canal A se mueve", a_vivo > 0);
      checkv("solo out1: el canal B en cero", b_vivo, 0);
      a_vivo = 0; b_vivo = 0;
      wr(16'h0000, 32'h1 | (1 << 1) | (1 << 2) | (1 << 4));      // solo out2 (sin arranque: en sigue)
      repeat (3000) begin @(negedge clk); if (dat_a !== 0) a_vivo++; if (dat_b !== 0) b_vivo++; end
      checkv("solo out2: el canal A en cero", a_vivo, 0);
      check("solo out2: el canal B se mueve", b_vivo > 0);
    end

    // ---- 6. apagarlo a mitad ---------------------------------------------
    begin
      automatic integer tarde = 0;
      wr(16'h0000, 32'h1 | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4));
      esperar(1000);
      @(negedge clk); a = BASE; wd = 32'h18; wen = 1;   // en = 0
      @(negedge clk); wen = 0;                          // cfg_en ya bajo en este flanco
      @(negedge clk);                                   // y dat en el siguiente
      repeat (50) begin if (dat_a !== 0 || dat_b !== 0 || trig !== 0) tarde++; @(negedge clk); end
      checkv("apagado a mitad: cero desde el ciclo siguiente", tarde, 0);
    end

    esperar(10);
    $display("tb_gen_pulsos: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #50ms;
    $display("RESULT: FAIL (timeout global)");
    $finish;
  end
endmodule
