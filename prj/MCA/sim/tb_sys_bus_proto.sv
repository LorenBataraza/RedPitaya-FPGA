`timescale 1ns/1ps
//============================================================================
// tb_sys_bus_proto — el PROTOCOLO del bus de sistema, con el RTL de verdad.
//
// Todos los demas testbenches del arbol le hablan al esclavo con un BFM que
// IMITA a sys_bus_cdc (sostiene wen/ren hasta el ack). Este instancia el
// camino real:
//
//     master en fclk[0]  ->  sys_bus_interconnect  ->  sys[7] -> mca_top
//                              (un sys_bus_cdc por slot)      @ adc_clk
//
// o sea que las ondas que salen de aca son el handshake por toggle de
// docs/TOP/bus_sistema_redpitaya.md §6, no una reconstruccion a mano. De eso
// viven las figuras: docs/TOP/figuras/bus_sistema/figuras_bus_sistema.py lee
// este VCD y dibuja los diagramas de tiempo.
//
// LOS DOS RELOJES SON ASINCRONICOS. Los dos son de 125 MHz, pero vienen de
// fuentes distintas (el PS y el PLL del ADC) y no tienen relacion de fase. Aca
// eso se modela con un desfasaje fijo SKEW; cambiando PER_ADC se puede ver como
// se mueve la latencia del cruce.
//
// QUE VERIFICA
//
//  1. ESCRITURA Y LECTURA DE PUNTA A PUNTA por el camino completo: el dato
//     escrito aparece en el registro del esclavo y vuelve por rdata.
//  2. LA VUELTA ENTERA ENTRA EN EL PRESUPUESTO. axi4_slave.sv:193 fabrica un
//     ack a los 32 ciclos de fclk[0]; si la transaccion tarda mas, en la placa
//     el ARM se lleva basura sin aviso. Aca se mide y se falla si no entra.
//  3. EL ACK ES UN PULSO DE UN CICLO (ctrl_done_csff[1] != [2]). Si durara
//     mas, el master arrancaria una transaccion de mas.
//  4. UNA DIRECCION NO MAPEADA TAMBIEN HACE ACK (§7.1). Es el modo de falla
//     grave del bus: sin ack el CDC del slot queda desincronizado para
//     siempre, no es solo una lectura mala.
//  5. SIN PLL ENGANCHADO EL CDC MIENTE: ack=1 inmediato, err=1 y
//     rdata=0xDEADBEEF (sys_bus_cdc.sv:74). Leer 0xDEADBEEF no significa que
//     el registro valga eso.
//  6. EL `err` DEL ESCLAVO NO LLEGA AL MASTER. sys_bus_stub contesta err=1
//     para marcar "slot vacio", pero sys_bus_cdc.sv:73 hace
//         assign bus_s.err = pll_locked_i ? 1'b0 : 1'b1;
//     o sea que nunca mira bus_m.err: el unico err que el software puede ver
//     es el de "PLL sin enganchar". Un slot vacio es indistinguible de uno
//     ocupado por el err; hay que usar el valor magico del offset 0.
//  7. UN REGISTRO QUE CAMBIA SALE ENTERO. Con un contador libre en el slot 5,
//     el dato tiene que llevar un ciclo de clk_ps quieto cuando axi4_slave lo
//     registra: el CDC lo congela en el ack del esclavo (reg_rdata). Sin eso,
//     en la placa salian bits mezclados (2026-11-08).
//
// dbg_showcase marca las transacciones que las figuras dibujan, asi que el
// script no necesita tiempos hardcodeados:
//     1 = escritura    2 = lectura    3 = lectura no mapeada    4 = sin PLL
//============================================================================
module tb_sys_bus_proto;

  //--------------------------------------------------------------------------
  // Relojes: 125 MHz los dos, sin relacion de fase
  //--------------------------------------------------------------------------
  localparam real PER_PS  = 8.0;   // clk_fpga_0, del PS7
  localparam real PER_ADC = 8.0;   // adc_clk, del PLL del ADC
  localparam real SKEW    = 2.6;   // desfasaje entre los dos (son asincronicos)

  logic clk_ps  = 1'b0;
  logic clk_adc = 1'b0;
  initial forever #(PER_PS/2.0) clk_ps = ~clk_ps;
  initial begin
    #(SKEW);
    forever #(PER_ADC/2.0) clk_adc = ~clk_adc;
  end

  logic rstn_ps  = 1'b0;
  logic rstn_adc = 1'b0;
  logic pll_locked = 1'b1;
  initial begin
    repeat (5) @(posedge clk_ps);  rstn_ps  = 1'b1;
  end
  initial begin
    repeat (5) @(posedge clk_adc); rstn_adc = 1'b1;
  end

  //--------------------------------------------------------------------------
  // El bus, cableado como en mca_red_pitaya_top.sv:409
  //--------------------------------------------------------------------------
  localparam integer SLOT_MCA = 7;
  localparam [31:0]  BASE_MCA = 32'h4070_0000;

  sys_bus_if ps_sys        (.clk (clk_ps ), .rstn (rstn_ps ));   // master
  sys_bus_if sys [8-1:0]   (.clk (clk_adc), .rstn (rstn_adc));   // esclavos

  sys_bus_interconnect #(
    .SN (8),
    .SW (20)
  ) i_ic (
    .pll_locked_i (pll_locked),
    .bus_m        (ps_sys),
    .bus_s        (sys)
  );

  // Los slots que no son el MCA quedan terminados, como en el top, salvo
  // SLOT_CNT: un esclavo con un registro que cambia solo (seccion 7).
  localparam integer SLOT_CNT = 5;
  generate
    for (genvar s = 0; s < SLOT_MCA; s++) begin : g_stub
      if (s != SLOT_CNT) begin : g_s
        sys_bus_stub i_stub (.bus (sys[s]));
      end
    end
  endgenerate

  // El esclavo de SLOT_CNT hace lo que event_ring_top: recalcula sys_rdata
  // TODOS los ciclos (aca, un contador libre de adc_clk, como su TS_LO) y da
  // el ack 4 ciclos despues del enable. El contador corre solo en la seccion
  // 7: si no, llena el VCD de las figuras con 32 bits cambiando cada ciclo.
  bit        cnt_corre  = 1'b0;
  reg [31:0] cnt_libre  = 32'h0;
  reg [3:0]  cnt_ack_sr = 4'h0;
  always @(posedge clk_adc) begin
    if (cnt_corre) cnt_libre <= cnt_libre + 32'd1;
    sys[SLOT_CNT].rdata <= cnt_libre;
    cnt_ack_sr          <= {cnt_ack_sr[2:0], sys[SLOT_CNT].wen | sys[SLOT_CNT].ren};
    sys[SLOT_CNT].ack   <= cnt_ack_sr[2];
  end
  assign sys[SLOT_CNT].err = 1'b0;

  // Anchos chicos a proposito: el barrido de borrado del histograma dura
  // 2^H_AW ciclos y aca no interesa el datapath, interesa el bus.
  localparam integer DW     = 14;
  localparam integer H_AW   = 8;
  localparam integer H2_AW  = 4;
  localparam integer PSD_AW = 4;

  mca_top #(
    .DW(DW), .EN_HIST_H(1), .H_AW(H_AW),
    .EN_HIST_H_PSD(1), .H2_AW(H2_AW), .PSD_AW(PSD_AW)
  ) i_mca (
    .adc_clk_i (clk_adc), .adc_rstn_i (rstn_adc),
    .mca_dat_i ('0), .mca_val_i ('0), .veto_i (1'b0), .trig_i (1'b0), .trig_arm_i (1'b1),
    .sys_addr  (sys[SLOT_MCA].addr ), .sys_wdata (sys[SLOT_MCA].wdata),
    .sys_wen   (sys[SLOT_MCA].wen  ), .sys_ren   (sys[SLOT_MCA].ren  ),
    .sys_rdata (sys[SLOT_MCA].rdata), .sys_err   (sys[SLOT_MCA].err  ),
    .sys_ack   (sys[SLOT_MCA].ack  )
  );

  //--------------------------------------------------------------------------
  // Espias para las figuras.
  //
  // El parser de VCD del script de figuras se queda SOLO con el scope raiz del
  // TB, asi que todo lo que haya que dibujar tiene que tener un nombre plano
  // aca. De paso, la lista es la documentacion de que señales componen el
  // protocolo.
  //--------------------------------------------------------------------------

  // --- dominio fclk[0]: lo que ve el master (axi4_slave en la placa) ---
  wire [31:0] m_addr  = ps_sys.addr ;
  wire [31:0] m_wdata = ps_sys.wdata;
  wire        m_wen   = ps_sys.wen  ;
  wire        m_ren   = ps_sys.ren  ;
  wire        m_en    = ps_sys.wen | ps_sys.ren;
  wire [31:0] m_rdata = ps_sys.rdata;
  wire        m_ack   = ps_sys.ack  ;
  wire        m_err   = ps_sys.err  ;

  // --- dominio fclk[0]: adentro del CDC del slot 7 ---
  wire       ctrl_do     = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.ctrl_do;
  wire [2:0] ctrl_done_s = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.ctrl_done_csff;
  wire       ctrl_we     = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.ctrl_we;
  wire       ctrl_re     = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.ctrl_re;
  wire       ctrl_ack    = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.ctrl_ack;

  // --- dominio adc_clk: adentro del CDC del slot 7 ---
  wire [1:0] reg_do_s   = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.reg_do_csff;
  wire       reg_do     = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.reg_do;
  wire       reg_done   = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.reg_done;
  wire [1:0] reg_we_s   = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.reg_we_csff;
  wire [1:0] reg_re_s   = i_ic.for_bus[SLOT_MCA].inst_sys_bus_cdc.reg_re_csff;
  // reg_do != reg_done es el "hay transaccion pendiente" del lado del esclavo.
  wire       reg_pend   = (reg_do != reg_done);

  // --- dominio adc_clk: el bus como lo ve el esclavo ---
  wire [31:0] s_addr  = sys[SLOT_MCA].addr ;
  wire [31:0] s_wdata = sys[SLOT_MCA].wdata;
  wire        s_wen   = sys[SLOT_MCA].wen  ;
  wire        s_ren   = sys[SLOT_MCA].ren  ;
  wire        s_en    = sys[SLOT_MCA].wen | sys[SLOT_MCA].ren;
  wire [31:0] s_rdata = sys[SLOT_MCA].rdata;
  wire        s_ack   = sys[SLOT_MCA].ack  ;
  wire        s_err   = sys[SLOT_MCA].err  ;

  // --- adentro del esclavo: el estrobo de un ciclo y el registro que aterriza
  wire        wr_stb  = i_mca.wr_stb;
  wire        rd_stb  = i_mca.rd_stb;
  wire [15:0] cfg_amp_max = i_mca.cfg_amp_max;

  //--------------------------------------------------------------------------
  // Marcas para el script de figuras
  //--------------------------------------------------------------------------
  reg [2:0] dbg_showcase = 3'd0;   // 1=escritura 2=lectura 3=no mapeada 4=sin PLL
  reg [1:0] dbg_phase    = 2'd0;   // 0=reposo 1=en+addr 2=ack visto 3=en abajo

  //--------------------------------------------------------------------------
  // Master BFM: el contrato del lado controlador.
  //
  // Levanta wen/ren con addr/wdata ya estables y los SOSTIENE hasta ver el
  // ack, igual que axi4_slave. Bajarlos antes aborta la transaccion; dejarlos
  // arriba despues del ack arranca otra (ctrl_do vuelve a togglear en cuanto
  // ctrl_done_csff[2] alcanza a ctrl_do).
  //
  // Se maneja en el flanco de subida de clk_ps y se mira el ack a mitad de
  // ciclo, que es donde ya esta establecido.
  //--------------------------------------------------------------------------
  localparam integer ACK_LIMIT = 32;   // el timeout de axi4_slave.sv:193

  integer ack_timeouts = 0;
  integer peor_latencia = 0;           // ciclos de clk_ps de la vuelta completa
  bit     last_err     = 1'b0;         // err del ultimo acceso, con el ack arriba

  task automatic bus_access(input bit         is_write,
                            input [31:0]      a,
                            input [31:0]      d,
                            output [31:0]     rd,
                            output integer    ciclos);
    integer n;
    begin
      @(posedge clk_ps);
      ps_sys.addr  <= a;
      ps_sys.wdata <= d;
      ps_sys.wen   <= is_write;
      ps_sys.ren   <= !is_write;
      dbg_phase    <= 2'd1;

      n = 0;
      @(negedge clk_ps);
      while (!ps_sys.ack && n < ACK_LIMIT) begin
        @(negedge clk_ps);
        n = n + 1;
      end
      rd       = ps_sys.rdata;  // rdata es valido con el ack arriba
      last_err = ps_sys.err;
      // Ciclos TRANSCURRIDOS desde que subio el enable, no muestras tomadas:
      // es el numero que se compara contra el timeout de axi4_slave y el que
      // escriben las figuras.
      ciclos   = n;
      if (!ps_sys.ack) begin
        ack_timeouts = ack_timeouts + 1;
        $display("    SIN ACK en %s a 0x%08h (%0d ciclos de clk_ps)",
                 is_write ? "escritura" : "lectura", a, ACK_LIMIT);
      end else begin
        dbg_phase <= 2'd2;
        if (ciclos > peor_latencia) peor_latencia = ciclos;
      end

      @(posedge clk_ps);
      ps_sys.wen <= 1'b0;
      ps_sys.ren <= 1'b0;
      dbg_phase  <= 2'd3;

      // Cola: el ack baja y recien despues se libera el bus. Se espera de
      // sobra para que las figuras muestren el final del handshake con addr y
      // wdata todavia estables, que es lo que hace axi4_slave en la placa.
      repeat (4) @(posedge clk_ps);
      ps_sys.addr  <= 32'h0;
      ps_sys.wdata <= 32'h0;
      dbg_phase    <= 2'd0;
      repeat (2) @(posedge clk_ps);
    end
  endtask

  task automatic bus_write(input [19:0] ofs, input [31:0] d);
    reg [31:0] dummy; integer c;
    bus_access(1'b1, BASE_MCA | {12'h0, ofs}, d, dummy, c);
  endtask

  task automatic bus_read(input [19:0] ofs, output [31:0] d);
    integer c;
    bus_access(1'b0, BASE_MCA | {12'h0, ofs}, 32'h0, d, c);
  endtask

  // Un acceso a otro slot, para el stub. addr[31:23] = 9'h080 es 0x4000_0000,
  // addr[22:20] el slot.
  task automatic bus_read_slot(input [2:0] slot, input [19:0] ofs,
                               output [31:0] d);
    integer c;
    bus_access(1'b0, {9'h080, slot, ofs}, 32'h0, d, c);
  endtask

  //--------------------------------------------------------------------------
  // Chequeo del ancho del ack: tiene que ser un pulso de UN ciclo de clk_ps.
  //--------------------------------------------------------------------------
  integer ack_largo = 0;
  integer ack_ancho = 0;
  always @(posedge clk_ps) if (rstn_ps) begin
    if (ps_sys.ack && pll_locked) begin
      ack_ancho <= ack_ancho + 1;
      if (ack_ancho >= 1) ack_largo <= ack_largo + 1;
    end else begin
      ack_ancho <= 0;
    end
  end

  //--------------------------------------------------------------------------
  // Chequeo del dato leido: cuando axi4_slave lo registra (RDATA <= bus.rdata
  // en el flanco de clk_ps que sigue al ciclo del ack), el valor tiene que
  // llevar por lo menos un ciclo de clk_ps sin moverse. Si no, en la placa se
  // muestrea un dato de adc_clk mientras cambia y salen bits mezclados.
  //--------------------------------------------------------------------------
  bit      mirar_rdata = 1'b0;   // solo en la seccion 7
  realtime t_rdata     = 0.0;    // ultimo cambio de rdata, del lado del master
  bit      ack_medio   = 1'b0;
  integer  rdata_movida = 0;
  always @(ps_sys.rdata) t_rdata = $realtime;
  always @(negedge clk_ps) ack_medio <= ps_sys.ack;
  always @(posedge clk_ps) if (mirar_rdata && ack_medio) begin
    if ($realtime - t_rdata < PER_PS) begin
      if (rdata_movida < 4)
        $display("    rdata cambio %0.1f ns antes de que axi4_slave lo registre",
                 $realtime - t_rdata);
      rdata_movida = rdata_movida + 1;
    end
  end

  //--------------------------------------------------------------------------
  // Resultado
  //--------------------------------------------------------------------------
  integer pass_cnt = 0, fail_cnt = 0;

  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt = pass_cnt + 1;
      else begin fail_cnt = fail_cnt + 1; $display("  FAIL: %s", name); end
    end
  endtask

  task automatic checkv(input string name, input [31:0] got, input [31:0] exp);
    begin
      if (got === exp) pass_cnt = pass_cnt + 1;
      else begin
        fail_cnt = fail_cnt + 1;
        $display("  FAIL: %s  (obtenido 0x%08h, esperado 0x%08h)",
                 name, got, exp);
      end
    end
  endtask

  // Offsets de mca_top (ver docs/mca/register_map_mca.md)
  localparam [19:0] OFS_MAGIC   = 20'h00000;
  localparam [19:0] OFS_AMP_MAX = 20'h00034;
  localparam [19:0] OFS_LIBRE   = 20'h00F00;   // no mapeada: cae en el default
  localparam [31:0] MAGIC_MCA   = 32'h4D434132;   // "MCA2": el mapa de las ranuras
  localparam [31:0] VALOR       = 32'h0000_1234;

  reg [31:0] rd;
  integer    ciclos_w, ciclos_r, ciclos_nm;

  initial begin
    ps_sys.addr  = 32'h0;
    ps_sys.wdata = 32'h0;
    ps_sys.wen   = 1'b0;
    ps_sys.ren   = 1'b0;

    wait (rstn_ps && rstn_adc);
    // El esclavo arranca borrando los histogramas (2^H_AW ciclos); esperarlo
    // para que las figuras no salgan con clear_busy arriba.
    repeat (2*(1<<H_AW)) @(posedge clk_adc);

    $display("=== identificacion ===");
    bus_read(OFS_MAGIC, rd);
    checkv("MAGIC del slot 7", rd, MAGIC_MCA);

    //----------------------------------------------------------------------
    // 1) ESCRITURA — la transaccion que dibuja la figura
    //----------------------------------------------------------------------
    $display("=== escritura AMP_MAX <- 0x%08h ===", VALOR);
    dbg_showcase = 3'd1;
    bus_access(1'b1, BASE_MCA | {12'h0, OFS_AMP_MAX}, VALOR, rd, ciclos_w);
    dbg_showcase = 3'd0;
    checkv("el dato aterrizo en el registro del esclavo",
           {16'h0, cfg_amp_max}, VALOR);
    check("la escritura entra en el presupuesto de 32 ciclos",
          ciclos_w < ACK_LIMIT);
    $display("    vuelta completa: %0d ciclos de clk_ps (%0.1f ns)",
             ciclos_w, ciclos_w * PER_PS);

    repeat (8) @(posedge clk_ps);

    //----------------------------------------------------------------------
    // 2) LECTURA — la otra figura
    //----------------------------------------------------------------------
    // Una lectura de otra direccion ANTES de la de vitrina. mca_top recalcula
    // sys_rdata todos los ciclos a partir de sys_addr, y sys_addr se queda
    // donde la dejo la transaccion anterior: sin esto, la lectura de vitrina
    // arrancaria con el 0x1234 que acaba de escribir ya puesto en rdata, y la
    // figura no mostraria el dato llegando.
    bus_read(OFS_MAGIC, rd);
    checkv("MAGIC otra vez, para dejar rdata en otro valor", rd, MAGIC_MCA);

    $display("=== lectura AMP_MAX ===");
    dbg_showcase = 3'd2;
    bus_access(1'b0, BASE_MCA | {12'h0, OFS_AMP_MAX}, 32'h0, rd, ciclos_r);
    dbg_showcase = 3'd0;
    checkv("la lectura devuelve lo escrito", rd, VALOR);
    check("la lectura entra en el presupuesto de 32 ciclos",
          ciclos_r < ACK_LIMIT);
    $display("    vuelta completa: %0d ciclos de clk_ps (%0.1f ns)",
             ciclos_r, ciclos_r * PER_PS);

    repeat (8) @(posedge clk_ps);

    //----------------------------------------------------------------------
    // 3) DIRECCION NO MAPEADA — el ack que evita el deadlock del slot (§7.1)
    //----------------------------------------------------------------------
    $display("=== lectura de una direccion NO MAPEADA (0x%05h) ===", OFS_LIBRE);
    dbg_showcase = 3'd3;
    bus_access(1'b0, BASE_MCA | {12'h0, OFS_LIBRE}, 32'h0, rd, ciclos_nm);
    dbg_showcase = 3'd0;
    check("una direccion no mapeada tambien hace ack", ciclos_nm < ACK_LIMIT);
    checkv("y devuelve 0, no basura", rd, 32'h0);
    $display("    vuelta completa: %0d ciclos de clk_ps (%0.1f ns)",
             ciclos_nm, ciclos_nm * PER_PS);

    // El slot sigue vivo despues de la no mapeada: si el CDC se hubiera
    // desincronizado, esta lectura ya no conseguiria ack.
    bus_read(OFS_MAGIC, rd);
    checkv("el slot sigue respondiendo despues de la no mapeada",
           rd, MAGIC_MCA);

    repeat (8) @(posedge clk_ps);

    //----------------------------------------------------------------------
    // 4) SLOT VACIO — el stub hace ack, pero su err NO llega al master
    //
    // sys_bus_stub contesta ack=1 y err=1. El ack pasa; el err no: el CDC
    // genera bus_s.err solo desde pll_locked_i y nunca mira bus_m.err
    // (sys_bus_cdc.sv:73). Este check fija ese comportamiento para que quede
    // claro que "err=1 marca slot vacio" NO es cierto visto desde el ARM.
    //----------------------------------------------------------------------
    $display("=== lectura de un slot vacio (stub) ===");
    bus_read_slot(3'd2, 20'h00000, rd);
    check("el err del esclavo NO llega al master (el CDC lo pisa)",
          last_err === 1'b0);
    checkv("el stub no cuelga el bus (hubo ack)", ack_timeouts, 32'd0);

    repeat (8) @(posedge clk_ps);

    //----------------------------------------------------------------------
    // 5) SIN PLL ENGANCHADO — ack inmediato, err y 0xDEADBEEF
    //----------------------------------------------------------------------
    $display("=== sin PLL enganchado ===");
    pll_locked = 1'b0;
    dbg_showcase = 3'd4;
    bus_read(OFS_MAGIC, rd);
    dbg_showcase = 3'd0;
    checkv("sin PLL se lee 0xDEADBEEF, no el registro", rd, 32'hDEADBEEF);
    pll_locked = 1'b1;
    repeat (8) @(posedge clk_ps);

    //----------------------------------------------------------------------
    // 7) UN REGISTRO QUE CAMBIA MIENTRAS SE LO LEE
    //
    // Un contador, un puntero, WR_SLOT del ring: el esclavo los recalcula
    // todos los ciclos. El dato tiene que congelarse en el ack del esclavo,
    // en adc_clk, y recien despues cruzar. Si cruza crudo, axi4_slave lo
    // muestrea mientras cambia: en la placa eso dio ~1 de cada 1000 lecturas
    // de wp_cur con bits mezclados (2026-11-08).
    //----------------------------------------------------------------------
    $display("=== un registro que cambia: el contador libre del slot %0d ===", SLOT_CNT);
    begin
      reg [31:0] prev;
      integer    no_crece;
      no_crece = 0;
      cnt_corre = 1'b1;
      bus_read_slot(SLOT_CNT[2:0], 20'h00000, prev);
      mirar_rdata = 1'b1;
      for (int i = 0; i < 16; i++) begin
        bus_read_slot(SLOT_CNT[2:0], 20'h00000, rd);
        if (rd <= prev) no_crece = no_crece + 1;
        prev = rd;
      end
      mirar_rdata = 1'b0;
      cnt_corre = 1'b0;
      checkv("el dato no se mueve cuando axi4_slave lo registra", rdata_movida, 32'd0);
      checkv("las lecturas del contador crecen", no_crece, 32'd0);
    end
    repeat (8) @(posedge clk_ps);

    //----------------------------------------------------------------------
    $display("=== cierre ===");
    checkv("no hubo ningun timeout de ack", ack_timeouts, 32'd0);
    checkv("el ack siempre duro un solo ciclo", ack_largo, 32'd0);
    $display("    peor vuelta completa: %0d ciclos de clk_ps (%0.1f ns)",
             peor_latencia, peor_latencia * PER_PS);
    $display("");
    $display("  checks OK:   %0d", pass_cnt);
    $display("  checks FAIL: %0d", fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #100us;
    $display("RESULT: FAIL  (timeout global del testbench)");
    $finish;
  end

endmodule
