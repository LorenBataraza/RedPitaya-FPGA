`timescale 1ns/1ps
//============================================================================
// tb_mca_zoom — unidad. Verifica el zoom alineado a potencias de 2:
//   - z=0 es exactamente el comportamiento anterior (los AW bits altos)
//   - saturacion arriba y abajo, nunca envolvimiento
//   - ANIDAMIENTO EXACTO entre niveles: es la propiedad por la que el zoom se
//     alineo a potencias de 2, asi que es el check que de verdad importa
//   - saturacion de z y enmascarado de k (configuraciones que no deben
//     convertirse en trampas silenciosas)
//
// El modelo de referencia se calcula con aritmetica de enteros del TB, no
// reimplementando el DUT: bin = (feat << z) >> (FW-AW) cuando los z bits altos
// valen k.
//============================================================================
module tb_mca_zoom;

  localparam integer FW = 16, AW = 13;
  localparam integer ZMAX = FW - AW;          // 3

  reg  [FW-1:0] feat;
  reg  [3:0]    z;
  reg  [7:0]    k;
  wire [AW-1:0] bin;

  mca_zoom #(.FW(FW), .AW(AW)) dut (.feat_i(feat), .z_i(z), .k_i(k), .bin_o(bin));

  integer pass_cnt=0, fail_cnt=0;
  task automatic checkv(input string name, input integer got, input integer exp);
    begin
      if (got===exp) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  (obtenido %0d, esperado %0d)", name, got, exp); end
    end
  endtask
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1; $display("  FAIL: %s", name); end
    end
  endtask

  // Aplica una configuracion y deja asentar la combinacional.
  task automatic ap(input integer f, input integer zz, input integer kk);
    begin feat = f[FW-1:0]; z = zz[3:0]; k = kk[7:0]; #1; end
  endtask

  // Modelo de referencia.
  function automatic integer ref_bin(input integer f, input integer zz,
                                     input integer kk);
    integer zc, kc, alto;
    begin
      zc = (zz > ZMAX) ? ZMAX : zz;
      kc = (zc == 0) ? 0 : (kk & ((1 << zc) - 1));
      alto = (zc == 0) ? 0 : (f >> (FW - zc));
      if      (alto > kc) ref_bin = (1 << AW) - 1;
      else if (alto < kc) ref_bin = 0;
      else                ref_bin = ((f << zc) & ((1 << FW) - 1)) >> (FW - AW);
    end
  endfunction

  integer i, zz, kk, f, b_grueso, b_fino, k_fino;

  initial begin
    $dumpfile("tb_mca_zoom.vcd");
    $dumpvars(0, tb_mca_zoom);

    //-----------------------------------------------------------------------
    // 1) z=0: tiene que ser EXACTAMENTE el corrimiento de antes (feat >> 3).
    //    Es lo que garantiza que el default no cambie nada de lo caracterizado.
    //-----------------------------------------------------------------------
    ap(16'h0000, 0, 0);  checkv("z=0: feat 0x0000",  bin, 0);
    ap(16'hFFFF, 0, 0);  checkv("z=0: feat 0xFFFF",  bin, (1<<AW)-1);
    ap(16'h1234, 0, 0);  checkv("z=0: feat 0x1234",  bin, 16'h1234 >> (FW-AW));
    ap(16'h8000, 0, 0);  checkv("z=0: feat 0x8000",  bin, 16'h8000 >> (FW-AW));

    //-----------------------------------------------------------------------
    // 2) Saturacion: fuera de la ventana va a un EXTREMO, nunca envuelve.
    //-----------------------------------------------------------------------
    ap(16'h9234, 1, 0);  checkv("fuera por arriba satura al ultimo canal",
                                bin, (1<<AW)-1);
    ap(16'h1234, 1, 1);  checkv("fuera por abajo satura al canal 0", bin, 0);
    ap(16'h4000, 2, 1);  checkv("justo en el borde inferior de la ventana", bin, 0);
    ap(16'h7FFF, 2, 1);  checkv("justo en el borde superior de la ventana",
                                bin, (1<<AW)-1);

    //-----------------------------------------------------------------------
    // 3) ANIDAMIENTO EXACTO — la propiedad que justifica alinear a potencias
    //    de 2. Para CUALQUIER feature, cada bin grueso es la union EXACTA de dos
    //    bins finos adyacentes. Eso es lo que permite coser dos espectros de
    //    niveles distintos con aritmetica ENTERA, sin resamplear y sin DNL.
    //
    //    OJO con la aritmetica de indices: al subir un nivel el bit de MAS PESO
    //    de la feature pasa a ser parte del selector de ventana, asi que el bin
    //    fino es relativo al arranque de SU ventana. La relacion exacta es
    //
    //        bin(f,z,k) == (bin(f,z+1,k') >> 1) + (k' & 1) * 2^(AW-1)
    //
    //    o sea: cada bin grueso es la union de DOS bins finos adyacentes, y el
    //    termino extra dice en cual de las dos mitades de la ventana gruesa cae.
    //-----------------------------------------------------------------------
    for (zz = 0; zz < ZMAX; zz = zz + 1) begin
      for (i = 0; i < 64; i = i + 1) begin
        f = ($random & 16'hFFFF);
        kk     = (zz == 0) ? 0 : (f >> (FW - zz));           // su ventana gruesa
        k_fino = f >> (FW - (zz + 1));                        // su ventana fina
        ap(f, zz, kk);          b_grueso = bin;
        ap(f, zz + 1, k_fino);  b_fino   = bin;
        checkv($sformatf("anidamiento z=%0d feat=0x%04h", zz, f),
               b_grueso, (b_fino >> 1) + ((k_fino & 1) << (AW-1)));
      end
    end

    //-----------------------------------------------------------------------
    // 4) Contra el modelo de referencia, barriendo todo el espacio util.
    //-----------------------------------------------------------------------
    for (zz = 0; zz <= ZMAX + 1; zz = zz + 1)
      for (kk = 0; kk < 8; kk = kk + 1)
        for (i = 0; i < 24; i = i + 1) begin
          f = ($random & 16'hFFFF);
          ap(f, zz, kk);
          checkv($sformatf("modelo z=%0d k=%0d feat=0x%04h", zz, kk, f),
                 bin, ref_bin(f, zz, kk));
        end

    //-----------------------------------------------------------------------
    // 5) Configuraciones que NO deben ser trampas silenciosas.
    //-----------------------------------------------------------------------
    // z por encima del maximo se satura a ZMAX en vez de rebanar bits que no
    // existen.
    ap(16'h1234, 15, 0);
    checkv("z > ZMAX se satura a ZMAX", bin, ref_bin(16'h1234, ZMAX, 0));
    // Con z=0 hay UNA sola ventana, asi que k se ignora: si no, un k viejo
    // escrito mandaria todo el espectro al canal 0 sin ninguna senal.
    ap(16'h1234, 0, 5);
    checkv("z=0 ignora k (no manda todo al canal 0)", bin, 16'h1234 >> (FW-AW));
    // Y k por encima de 2^z-1 se enmascara, no satura.
    ap(16'h1234, 1, 8'hFE);
    checkv("k se enmascara a los z bits utiles", bin, ref_bin(16'h1234, 1, 0));

    $display("tb_mca_zoom: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    $display("RESULT: %s", (fail_cnt==0) ? "PASS" : "FAIL");
    $finish;
  end

endmodule
