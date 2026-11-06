`timescale 1ns/1ps
//============================================================================
// tb_mca_trap — mca_trap contra el modelo de referencia de Python, bit a bit
//
// Los vectores salen de estimadores.trapecio (software/API/modelo_rtl), con
// sim/vectores/gen_trap.py: por caso, la forma (k, m, Mq, sh) y para cada
// muestra la salida que tiene que dar mca_trap. Se comparan TODAS, en enteros.
//
// Lo que ademas ejercita:
//   - huecos de val (30 %) con basura en x: el trapecio avanza por muestra, no
//     por ciclo, y la latencia es de LAT muestras;
//   - el clr entre casos, con val en alto: la muestra de ese ciclo no entra y
//     el contenido viejo de las lineas de retardo no se cuela (las primeras
//     salidas tienen que ser exactamente las del modelo, que arranca de cero);
//   - que mientras val = 0 la salida no cambie;
//   - un RESET SIN CLR con basura en las lineas, repitiendo el primer caso: la
//     salida tiene que ser la del modelo igual. Es el bug de kl, que antes se
//     reseteaba a cero y dejaba entrar la BRAM sin escribir en el primer flanco;
//   - las dos memorias: dut con BRAM y dut_lut con RAM_STYLE = "distributed"
//     (la del disparo con polo-cero del multitrigger), con los mismos vectores.
//
//   vsim ... +VEC=<ruta a trap_ref.txt> [+NCASOS=<casos esperados, 4>]
//============================================================================
module tb_mca_trap;
  localparam integer LAT = 8;

  reg clk = 0;
  always #4 clk = ~clk;

  reg               rstn = 0, clr = 0, val = 0;
  reg signed [14:0] x = 0;
  reg        [9:0]  k = 1, l = 1;
  reg        [19:0] mq = 0;
  reg        [5:0]  sh = 0;
  wire signed [17:0] y;

  wire signed [17:0] y_lut;

  mca_trap dut (
    .clk_i(clk), .rstn_i(rstn), .clr_i(clr), .x_i(x), .val_i(val),
    .cfg_k_i(k), .cfg_l_i(l), .cfg_mq_i(mq), .cfg_sh_i(sh), .trap_o(y)
  );

  mca_trap #(.RAM_STYLE("distributed")) dut_lut (
    .clk_i(clk), .rstn_i(rstn), .clr_i(clr), .x_i(x), .val_i(val),
    .cfg_k_i(k), .cfg_l_i(l), .cfg_mq_i(mq), .cfg_sh_i(sh), .trap_o(y_lut)
  );

  integer fd, r, n, i, kk, mm, mmq, ssh, n_casos, n_esp, errores, comparadas, xi, yi;
  string  vec, nombre, palabra;
  int     xs[$], ys[$];
  int     xs0[$], ys0[$];
  integer k0, m0, mq0, sh0;
  string  nombre0;
  reg signed [17:0] y_ant;

  task automatic chk(input string que, input integer got, input integer exp);
    comparadas++;
    if (got !== exp) begin
      errores++;
      if (errores <= 20) $display("  FAIL %s: DUT=%0d esperado=%0d", que, got, exp);
    end
  endtask

  initial begin
    if (!$value$plusargs("VEC=%s", vec)) vec = "../sim/vectores/trap_ref.txt";
    if (!$value$plusargs("NCASOS=%d", n_esp)) n_esp = 4;
    fd = $fopen(vec, "r");
    if (fd == 0) begin
      $display("no se pudo abrir %s", vec);
      $display("RESULT: FAIL");
      $finish;
    end
    errores = 0; comparadas = 0; n_casos = 0;
    process::self().srandom(11);

    repeat (4) @(posedge clk);
    #1 rstn = 1;
    // antes del primer clr: basura en las lineas de retardo, a proposito
    repeat (2000) begin
      @(posedge clk); #1 val = 1; x = $urandom_range(0, 32767);
    end

    while (!$feof(fd)) begin
      r = $fscanf(fd, "%s %s %d %d %d %d %d\n", palabra, nombre, kk, mm, mmq, ssh, n);
      if (r != 7) break;
      xs.delete(); ys.delete();
      for (i = 0; i < n; i++) begin
        r = $fscanf(fd, "%d %d\n", xi, yi);
        xs.push_back(xi); ys.push_back(yi);
      end
      n_casos++;
      if (n_casos == 1) begin
        xs0 = xs; ys0 = ys; k0 = kk; m0 = mm; mq0 = mmq; sh0 = ssh; nombre0 = nombre;
      end

      // la forma nueva y el clr en el mismo ciclo, con una muestra que NO
      // tiene que entrar
      @(posedge clk); #1;
      k = kk; l = kk + mm; mq = mmq; sh = ssh;
      clr = 1; val = 1; x = 15'sh3FFF;
      @(posedge clk); #1 clr = 0;

      for (i = 0; i < n; i++) begin
        while ($urandom_range(0, 9) < 3) begin
          val = 0; x = $urandom_range(0, 32767);
          y_ant = y;
          @(posedge clk); #1;
          chk($sformatf("%s: la salida se mueve sin val (muestra %0d)", nombre, i), y, y_ant);
        end
        val = 1; x = xs[i];
        chk($sformatf("%s muestra %0d", nombre, i), y, (i >= LAT) ? ys[i - LAT] : 0);
        chk($sformatf("%s muestra %0d (LUT)", nombre, i), y_lut, (i >= LAT) ? ys[i - LAT] : 0);
        @(posedge clk); #1;
      end
      val = 0;
      $display("  caso %-10s k=%0d m=%0d Mq=%0d sh=%0d: %0d muestras", nombre, kk, mm, mmq, ssh, n);
    end
    $fclose(fd);

    // Reset SIN clr: basura en las lineas, reset con la forma del primer caso
    // ya puesta, y el primer caso otra vez sin pulsar clr.
    if (n_casos > 0) begin
      repeat (2000) begin
        @(posedge clk); #1 val = 1; x = $urandom_range(0, 32767);
      end
      rstn = 0; val = 0;
      k = k0; l = k0 + m0; mq = mq0; sh = sh0;
      repeat (3) @(posedge clk);
      #1 rstn = 1;
      for (i = 0; i < xs0.size(); i++) begin
        val = 1; x = xs0[i];
        chk($sformatf("reset sin clr, %s muestra %0d", nombre0, i), y, (i >= LAT) ? ys0[i - LAT] : 0);
        chk($sformatf("reset sin clr, %s muestra %0d (LUT)", nombre0, i), y_lut,
            (i >= LAT) ? ys0[i - LAT] : 0);
        @(posedge clk); #1;
      end
      val = 0;
      $display("  reset sin clr, caso %s: %0d muestras", nombre0, xs0.size());
    end

    $display("tb_mca_trap: %0d casos, %0d comparaciones, %0d errores", n_casos, comparadas, errores);
    if (errores == 0 && n_casos == n_esp) $display("RESULT: PASS");
    else $display("RESULT: FAIL");
    $finish;
  end
endmodule
