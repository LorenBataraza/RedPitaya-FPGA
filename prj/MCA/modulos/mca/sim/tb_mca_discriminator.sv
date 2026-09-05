`timescale 1ns/1ps
//============================================================================
// tb_mca_discriminator — unidad. Verifica el corte por feature:
//   - deshabilitado deja pasar TODO (es el default, y es lo que garantiza que
//     el refactor no cambie nada de lo ya caracterizado)
//   - intervalo interno y su complemento, con los BORDES incluidos
//   - el selector realmente elige la ranura (y no se queda clavado)
//   - INTERVALO VACIO (min > max): interno rechaza todo, externo acepta todo.
//     Es el caso que hay que definir explicitamente en vez de descubrirlo.
//============================================================================
module tb_mca_discriminator;

  localparam integer FW = 16, NFEAT = 16;

  reg  [NFEAT*FW-1:0] ev_feat = '0;
  reg                 en  = 1'b0;
  reg  [3:0]          sel = 4'd0;
  reg                 out = 1'b0;
  reg  [FW-1:0]       mn  = '0, mx = '1;
  wire                acc;

  mca_discriminator #(.FW(FW), .NFEAT(NFEAT)) dut (
    .ev_feat_i(ev_feat), .cfg_en_i(en), .cfg_sel_i(sel), .cfg_out_i(out),
    .cfg_min_i(mn), .cfg_max_i(mx), .accept_o(acc)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1; $display("  FAIL: %s", name); end
    end
  endtask

  // Escribe una ranura del bus.
  task automatic set_feat(input integer idx, input integer v);
    begin ev_feat[idx*FW +: FW] = v[FW-1:0]; #1; end
  endtask

  task automatic cfg(input bit e, input integer s, input bit o,
                     input integer a, input integer b);
    begin en=e; sel=s[3:0]; out=o; mn=a[FW-1:0]; mx=b[FW-1:0]; #1; end
  endtask

  integer i;

  initial begin
    $dumpfile("tb_mca_discriminator.vcd");
    $dumpvars(0, tb_mca_discriminator);

    // Contenido conocido: la ranura i vale i*1000.
    for (i=0; i<NFEAT; i=i+1) set_feat(i, i*1000);

    //-----------------------------------------------------------------------
    // 1) Deshabilitado pasa TODO, sin importar min/max ni la feature.
    //-----------------------------------------------------------------------
    cfg(1'b0, 3, 1'b0, 100, 200);
    check("deshabilitado: acepta aunque la feature este fuera", acc===1'b1);
    cfg(1'b0, 3, 1'b1, 0, 65535);
    check("deshabilitado: acepta tambien con intervalo externo", acc===1'b1);

    //-----------------------------------------------------------------------
    // 2) Intervalo INTERNO [min,max], bordes INCLUIDOS.
    //    La ranura 3 vale 3000.
    //-----------------------------------------------------------------------
    cfg(1'b1, 3, 1'b0, 2000, 4000);
    check("interno: 3000 dentro de [2000,4000]", acc===1'b1);
    cfg(1'b1, 3, 1'b0, 3000, 4000);
    check("interno: el borde inferior ENTRA", acc===1'b1);
    cfg(1'b1, 3, 1'b0, 2000, 3000);
    check("interno: el borde superior ENTRA", acc===1'b1);
    cfg(1'b1, 3, 1'b0, 3001, 4000);
    check("interno: justo por debajo del min, rechaza", acc===1'b0);
    cfg(1'b1, 3, 1'b0, 2000, 2999);
    check("interno: justo por encima del max, rechaza", acc===1'b0);

    //-----------------------------------------------------------------------
    // 3) Intervalo EXTERNO: el complemento exacto del interno.
    //-----------------------------------------------------------------------
    cfg(1'b1, 3, 1'b1, 2000, 4000);
    check("externo: 3000 dentro del intervalo -> RECHAZA", acc===1'b0);
    cfg(1'b1, 3, 1'b1, 3001, 4000);
    check("externo: fuera del intervalo -> acepta", acc===1'b1);
    cfg(1'b1, 3, 1'b1, 3000, 4000);
    check("externo: el borde tambien rechaza (complemento exacto)", acc===1'b0);

    //-----------------------------------------------------------------------
    // 4) El SELECTOR elige de verdad. Con la misma ventana, cambiar de ranura
    //    tiene que cambiar la respuesta: es el check que agarra un mux que se
    //    quedo clavado (que es exactamente el bug que aparecio en mca_top al
    //    escribir el mux como function dentro de un assign continuo).
    //-----------------------------------------------------------------------
    cfg(1'b1, 3, 1'b0, 2500, 3500);
    check("selector: ranura 3 (=3000) entra", acc===1'b1);
    cfg(1'b1, 5, 1'b0, 2500, 3500);
    check("selector: ranura 5 (=5000) NO entra", acc===1'b0);
    cfg(1'b1, 2, 1'b0, 2500, 3500);
    check("selector: ranura 2 (=2000) NO entra", acc===1'b0);
    // Y cambiar el CONTENIDO de la ranura seleccionada tambien tiene que verse.
    cfg(1'b1, 5, 1'b0, 2500, 3500);
    set_feat(5, 3000);
    check("selector: sigue al contenido de la ranura, no solo al indice",
          acc===1'b1);
    set_feat(5, 5000);

    //-----------------------------------------------------------------------
    // 5) INTERVALO VACIO (min > max). No es un error: el conjunto interno es
    //    vacio, asi que interno rechaza todo y externo acepta todo. Queda
    //    fijado para que nadie lo "arregle" invirtiendo los limites en
    //    silencio, que convertiria una configuracion mal escrita en un corte
    //    que parece funcionar.
    //-----------------------------------------------------------------------
    cfg(1'b1, 3, 1'b0, 4000, 2000);
    check("vacio: interno con min>max rechaza TODO", acc===1'b0);
    cfg(1'b1, 3, 1'b1, 4000, 2000);
    check("vacio: externo con min>max acepta todo", acc===1'b1);
    // Y con cualquier otra feature da lo mismo: no depende del valor.
    cfg(1'b1, 7, 1'b0, 4000, 2000);
    check("vacio: no depende de que feature se mire", acc===1'b0);

    //-----------------------------------------------------------------------
    // 6) Ventana degenerada de UN valor (min == max).
    //-----------------------------------------------------------------------
    cfg(1'b1, 3, 1'b0, 3000, 3000);
    check("min==max: acepta exactamente ese valor", acc===1'b1);
    cfg(1'b1, 4, 1'b0, 3000, 3000);
    check("min==max: rechaza cualquier otro", acc===1'b0);

    //-----------------------------------------------------------------------
    // 7) Los extremos del rango sin signo, que es el contrato del bus.
    //-----------------------------------------------------------------------
    set_feat(1, 65535);
    cfg(1'b1, 1, 1'b0, 0, 65535);
    check("sin signo: 0xFFFF entra en [0,0xFFFF]", acc===1'b1);
    set_feat(1, 0);
    check("sin signo: 0x0000 tambien", acc===1'b1);

    $display("tb_mca_discriminator: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    $display("RESULT: %s", (fail_cnt==0) ? "PASS" : "FAIL");
    $finish;
  end

endmodule
