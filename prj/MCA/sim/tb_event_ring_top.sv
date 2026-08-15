`timescale 1ns/1ps
//============================================================================
// tb_event_ring_top — integracion.
//
// Cablea el ring completo (captura -> stage -> writer -> axi_wr_fifo) contra un
// modelo de memoria y ejercita el camino punta a punta.
//
// El test [4] es el que justifica la arquitectura entera: una RAFAGA mas rapida
// que el consumidor tiene que ser ABSORBIDA mientras haya creditos, y cuando se
// acaban, la perdida tiene que quedar CONTADA en vez de ser invisible. El
// invariante de cierre es
//
//     eventos_capturados + drop_busy + drop_full == triggers_inyectados
//
// que es exactamente lo que hoy no se puede escribir (docs: "un segundo trigger
// mientras el SW lee el anterior es invisible desde el software").
//
// Chequea ademas: layout del slot en memoria, avance de seq, wrap del ring,
// rechazo de cambios de geometria en marcha, y que ningun slot quede a medias.
//============================================================================
module tb_event_ring_top;

  localparam integer DW      = 14;
  localparam integer N_CH    = 2;
  localparam integer PRE_AW  = 6;
  localparam integer S_AW    = 11;
  localparam integer DATA_AW = 9;    // stage chica a proposito: 512 muestras
  localparam integer E       = 4;

  localparam integer SLOT_SHIFT = 9;             // 512 B por slot
  localparam integer SLOT_W     = (1<<SLOT_SHIFT)/8;   // 64 palabras
  localparam [31:0]  RING_BASE  = 32'h1000_0000;
  localparam integer N_SLOTS    = 4;             // ring corto: fuerza el wrap
  localparam [31:0]  RING_SZ    = N_SLOTS * (1<<SLOT_SHIFT);

  reg clk = 1'b0, rstn = 1'b0;
  always #4 clk = ~clk;   // 125 MHz

  reg [N_CH*DW-1:0] dat = '0;
  reg               dv   = 1'b1;
  reg               trig = 1'b0;
  reg [16:0]        snap = 17'h2;

  wire [31:0] axi_waddr;
  wire [63:0] axi_wdata;
  wire [7:0]  axi_wsel;
  wire [2:0]  axi_wsize;
  wire        axi_wvalid;
  wire [3:0]  axi_wlen;
  wire        axi_wfixed;
  reg         axi_wrdy = 1'b1;

  reg  [31:0] sys_addr = 32'h0, sys_wdata = 32'h0;
  reg         sys_wen = 1'b0, sys_ren = 1'b0;
  wire [31:0] sys_rdata;
  wire        sys_err, sys_ack;

  event_ring_top #(
    .DW(DW), .N_CH(N_CH), .PRE_AW(PRE_AW), .S_AW(S_AW),
    .DATA_AW(DATA_AW), .E(E)
  ) dut (
    .adc_clk_i(clk), .adc_rstn_i(rstn),
    .dat_i(dat), .dv_i(dv), .trig_i(trig), .snapshot_i(snap),
    .axi_waddr_o(axi_waddr), .axi_wdata_o(axi_wdata), .axi_wsel_o(axi_wsel),
    .axi_wsize_o(axi_wsize), .axi_wvalid_o(axi_wvalid), .axi_wlen_o(axi_wlen),
    .axi_wfixed_o(axi_wfixed), .axi_werr_i(1'b0), .axi_wrdy_i(axi_wrdy),
    .sys_addr(sys_addr), .sys_wdata(sys_wdata), .sys_wen(sys_wen),
    .sys_ren(sys_ren), .sys_rdata(sys_rdata), .sys_err(sys_err),
    .sys_ack(sys_ack)
  );

  //--------------------------------------------------------------------------
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
        $display("  FAIL: %s (got=%0h exp=%0h)", name, got, exp);
      end
    end
  endtask

  //--------------------------------------------------------------------------
  // Bus de sistema
  //--------------------------------------------------------------------------
  task automatic bus_wr(input [19:0] a, input [31:0] d);
    begin
      @(negedge clk);
      sys_addr = {12'h0, a}; sys_wdata = d; sys_wen = 1'b1;
      @(negedge clk);
      sys_wen = 1'b0;
      repeat (6) @(negedge clk);
    end
  endtask

  task automatic bus_rd(input [19:0] a, output [31:0] d);
    integer k;
    begin
      @(negedge clk);
      sys_addr = {12'h0, a}; sys_ren = 1'b1;
      @(negedge clk);
      sys_ren = 1'b0;
      k = 0;
      // la direccion se mantiene hasta el ack, como en el bus real
      while (!sys_ack && k < 20) begin @(negedge clk); k = k + 1; end
      d = sys_rdata;
      repeat (2) @(negedge clk);
    end
  endtask

  //--------------------------------------------------------------------------
  // Modelo de memoria DIRECCIONADO, no un contador de beats.
  //
  // axi_wr_fifo avanza axi_waddr_o POR BEAT (axi_wr_fifo.v:281), y si una
  // rafaga se queda sin datos puede repetir el ultimo beat. Contar beats daria
  // un resultado que no se parece a lo que ve el PS; escribir por direccion, si
  // — un beat repetido simplemente reescribe la misma celda, igual que en la
  // DDR real. Este modelo es el que hace que el test signifique algo.
  //--------------------------------------------------------------------------
  reg [63:0] ddr [0:2047];
  integer    beats = 0;
  integer    addr_out_of_range = 0;
  integer    widx;

  always @(posedge clk) begin
    if (axi_wvalid && axi_wrdy) begin
      beats = beats + 1;
      if (axi_waddr < RING_BASE || axi_waddr >= (RING_BASE + RING_SZ)) begin
        addr_out_of_range = addr_out_of_range + 1;
      end else begin
        widx = (axi_waddr - RING_BASE) >> 3;
        ddr[widx] = axi_wdata;
      end
    end
  end

  // Palabra `w` del slot `s` del ring
  function automatic [63:0] slot_w(input integer s, input integer w);
    slot_w = ddr[((s % N_SLOTS) * SLOT_W) + w];
  endfunction

  // Volcado del ring para que el decodificador de Python lo lea. Es el enganche
  // entre el RTL y el software: si el layout, el endianness o el intercalado no
  // coinciden, el test de Python falla ANTES de tocar la placa.
  task automatic dump_ring(input string fname);
    integer fd, k;
    begin
      fd = $fopen(fname, "w");
      $fwrite(fd, "# event_ring dump: slot_shift=%0d n_slots=%0d words=%0d\n",
              SLOT_SHIFT, N_SLOTS, N_SLOTS*SLOT_W);
      for (k = 0; k < N_SLOTS*SLOT_W; k = k + 1)
        $fwrite(fd, "%016x\n", ddr[k]);
      $fclose(fd);
    end
  endtask

  //--------------------------------------------------------------------------
  // Rampa de muestras
  //--------------------------------------------------------------------------
  integer sample_idx = 0;
  reg signed [DW-1:0] c0, c1;
  always @(posedge clk) if (dv) sample_idx <= sample_idx + 1;
  always @(*) begin
    c0  = sample_idx[DW-1:0];
    c1  = -sample_idx[DW-1:0];
    dat = {c1, c0};
  end

  task automatic pulse_trig;
    begin @(negedge clk); trig = 1'b1; @(negedge clk); trig = 1'b0; end
  endtask

  //--------------------------------------------------------------------------
  integer i, s, errs;
  reg [31:0] rv, ev_c, db_c, df_c, wrs, rds;
  integer    n_trig;

  initial begin
    $dumpfile("tb_event_ring_top.vcd");
    $dumpvars(0, tb_event_ring_top);

    repeat (4) @(posedge clk);
    rstn = 1'b1;
    repeat (4) @(posedge clk);

    //======================================================================
    $display("[0] magic y configuracion en STOPPED");
    bus_rd(20'h50, rv);
    checkv("MAGIC", rv, 32'h45564E54);

    bus_wr(20'h08, RING_BASE);
    bus_wr(20'h0C, RING_SZ);
    bus_wr(20'h10, SLOT_SHIFT);
    bus_wr(20'h14, 32'd8);     // pre
    bus_wr(20'h18, 32'd24);    // post
    bus_rd(20'h2C, rv);
    checkv("N_SLOTS derivado", rv, N_SLOTS);
    bus_rd(20'h08, rv);
    checkv("slot_base latcheado", rv, RING_BASE);

    //======================================================================
    $display("[1] arranque y primer evento");
    bus_wr(20'h00, 32'h1);     // run
    repeat (80) @(posedge clk);   // llenar el pre-buffer

    pulse_trig();
    repeat (400) @(posedge clk);

    checkv("hdr1 seq=0",    slot_w(0,1)[31:0],  32'd0);
    checkv("hdr1 n_samp",   slot_w(0,1)[47:32], 32);
    checkv("hdr1 n_ch",     slot_w(0,1)[55:48], N_CH);
    checkv("hdr2 snapshot", slot_w(0,2)[16:0],  17'h2);
    checkv("footer al final del slot", slot_w(0,SLOT_W-1), {~32'd0, 32'd0});
    checkv("direcciones dentro del ring", addr_out_of_range, 0);

    // La rampa: ch1 = -ch0 en cada par de muestras, sobre TODAS las palabras de
    // datos. Si el empaquetado o el intercalado estuvieran mal, esto se cae.
    errs = 0;
    for (i = 0; i < (32*N_CH)/4; i = i + 1) begin
      if (slot_w(0,4+i)[31:16] !== ((-$signed(slot_w(0,4+i)[15:0])) & 16'hFFFF))
        errs = errs + 1;
      if (slot_w(0,4+i)[63:48] !== ((-$signed(slot_w(0,4+i)[47:32])) & 16'hFFFF))
        errs = errs + 1;
    end
    checkv("intercalado ch0/ch1 en todo el slot", errs, 0);

    bus_rd(20'h20, wrs); checkv("WR_SLOT=1", wrs, 1);
    bus_rd(20'h28, rv);  checkv("SEQ=1", rv, 1);
    bus_rd(20'h38, rv);  checkv("EV_CNT=1", rv, 1);

    //======================================================================
    $display("[2] geometria en marcha: se ignora y marca err_cfg");
    bus_wr(20'h10, 32'd12);          // intento de cambiar slot_shift corriendo
    bus_rd(20'h10, rv);
    checkv("slot_shift NO cambio", rv, SLOT_SHIFT);
    bus_rd(20'h04, rv);
    check("err_cfg levantado", rv[5] === 1'b1);

    //======================================================================
    $display("[3] wrap del ring con el PS drenando");
    for (i = 0; i < N_SLOTS + 2; i = i + 1) begin
      pulse_trig();
      repeat (300) @(posedge clk);
      // el PS consume: publica RD_SLOT por batch
      bus_rd(20'h20, wrs);
      bus_wr(20'h24, wrs);
    end
    checkv("direcciones siempre dentro del ring", addr_out_of_range, 0);
    // seq sigue avanzando linealmente aunque el ring haya dado la vuelta
    bus_rd(20'h28, rv);
    checkv("SEQ acumulado", rv, 1 + N_SLOTS + 2);
    bus_rd(20'h20, wrs);
    checkv("WR_SLOT acumulado", wrs, 1 + N_SLOTS + 2);
    // Tras el wrap, cada slot fisico guarda el ULTIMO evento que le toco, y su
    // footer tiene que ser el seq de ese evento. Es lo que le permite al PS
    // distinguir un slot fresco de uno de la vuelta anterior.
    errs = 0;
    for (s = 0; s < N_SLOTS; s = s + 1) begin
      // seq del ultimo evento que aterrizo en el slot fisico s
      i = ((wrs - 1 - s) / N_SLOTS) * N_SLOTS + s;
      if (i >= 0 && i < wrs)
        if (slot_w(s, SLOT_W-1) !== {~i[31:0], i[31:0]}) errs = errs + 1;
    end
    checkv("footer de cada slot = seq del ultimo evento que le toco", errs, 0);

    // Volcar el ring lleno para el decodificador de Python (Fase 0)
    dump_ring("../software/tests/fase0/ring_dump.hex");

    //======================================================================
    $display("[4] RAFAGA sin drenaje: absorbe, despues cuenta la perdida");
    // Congelar el consumidor: RD_SLOT deja de avanzar.
    bus_wr(20'h00, 32'h3);      // run + clr: limpia contadores
    repeat (10) @(posedge clk);
    bus_wr(20'h00, 32'h1);
    bus_rd(20'h20, wrs);
    bus_wr(20'h24, wrs);        // rd_slot al dia, N_SLOTS creditos libres
    repeat (60) @(posedge clk);

    n_trig = 0;
    // Rafaga: muchos mas triggers que creditos, bien espaciados para que el
    // limite sea el CREDITO y no el tiempo muerto intrinseco de la captura.
    for (i = 0; i < 20; i = i + 1) begin
      pulse_trig();
      n_trig = n_trig + 1;
      repeat (60) @(posedge clk);
    end
    repeat (600) @(posedge clk);

    bus_rd(20'h38, ev_c);
    bus_rd(20'h30, db_c);
    bus_rd(20'h34, df_c);
    bus_rd(20'h20, wrs);
    bus_rd(20'h24, rds);

    $display("      capturados=%0d drop_busy=%0d drop_full=%0d wr_slot=%0d rd_slot=%0d",
             ev_c, db_c, df_c, wrs, rds);

    // EL INVARIANTE
    checkv("capturados + drop_busy + drop_full == triggers",
           ev_c + db_c + df_c, n_trig);
    check("hubo perdida contada (la rafaga excedio los creditos)", df_c > 0);
    check("los creditos frenaron al writer", (wrs - rds) <= N_SLOTS);
    checkv("el writer escribio exactamente los slots acreditados",
           wrs - rds, N_SLOTS);
    // Todo slot escrito tiene footer bien formado: no quedo ninguno a medias
    errs = 0;
    for (s = 0; s < N_SLOTS; s = s + 1)
      if (slot_w(s, SLOT_W-1)[63:32] !== ~slot_w(s, SLOT_W-1)[31:0])
        errs = errs + 1;
    checkv("ningun slot quedo a medias", errs, 0);

    // Al devolver creditos, el writer drena SOLO lo que quedo en el stage — que
    // es justamente la rafaga absorbida — y despues sigue tomando eventos
    // nuevos, sin ninguna intervencion mas del PS.
    bus_wr(20'h24, wrs);
    repeat (2000) @(posedge clk);
    bus_rd(20'h20, rv);
    check("drena el stage al volver el credito", rv > wrs);

    // Esperar a que el sistema quede QUIETO antes de medir: leer wr_slot dos
    // veces y exigir que no se haya movido. Si no, se estaria midiendo contra
    // un baseline que todavia esta drenando.
    wrs = 32'hFFFF_FFFF;
    for (i = 0; i < 20 && wrs != rv; i = i + 1) begin
      wrs = rv;
      bus_wr(20'h24, rv);        // el PS se pone al dia
      repeat (500) @(posedge clk);
      bus_rd(20'h20, rv);
    end
    checkv("el ring quedo quieto", rv, wrs);

    pulse_trig();
    repeat (600) @(posedge clk);
    bus_rd(20'h20, rv);
    checkv("y sigue tomando eventos nuevos", rv, wrs + 1);

    //======================================================================
    // Regresion del bug que aparecio en la PLACA y no en simulacion: wr_slot se
    // reseteaba con el flush de STOPPED pero rd_slot no, asi que un stop/start
    // dejaba `ocupados = wr - rd` en underflow (~2^32) y el ring descartaba
    // TODO sin credito. El TB no lo veia porque re-publicaba rd_slot despues de
    // cada arranque; aca se hace justamente lo contrario.
    // Regresion del bug de la PLACA: wr_slot se reseteaba con el flush de
    // STOPPED pero rd_slot no, asi que un stop/start dejaba `ocupados = wr - rd`
    // en underflow (~2^32) y el ring descartaba TODO. El TB no lo veia porque
    // re-publicaba rd_slot despues de cada arranque; aca se hace lo contrario.
    //
    // El invariante que hay que sostener es
    //     direccion_fisica = slot_base + (wr_slot mod N_SLOTS) * SLOT_SZ
    // y por eso los DOS contadores y la direccion del axi_wr_fifo se reinician
    // juntos: un stop deja el ring como recien arrancado, sin desincronizar el
    // indice de la memoria.
    $display("[4b] stop/start SIN republicar rd_slot: nada de underflow");
    bus_wr(20'h00, 32'h0);            // stop
    repeat (400) @(posedge clk);
    bus_wr(20'h00, 32'h1);            // start, SIN tocar rd_slot
    repeat (80) @(posedge clk);
    bus_rd(20'h20, rv);
    bus_rd(20'h24, rds);
    checkv("wr_slot reiniciado", rv, 0);
    checkv("rd_slot reiniciado JUNTO con wr_slot", rds, 0);
    check("ocupados sano (sin underflow)", (rv - rds) <= N_SLOTS);

    // Y el primer evento tras el stop/start aterriza en el slot fisico 0,
    // que es lo que el PS va a ir a buscar con (wr_slot mod N_SLOTS).
    pulse_trig();
    repeat (400) @(posedge clk);
    bus_rd(20'h20, rv);
    checkv("captura tras el stop/start", rv, 1);
    checkv("y aterrizo en el slot fisico 0", slot_w(0, SLOT_W-1),
           {~32'd0, 32'd0});

    //======================================================================
    $display("[5] parada ordenada: DRAINING no corta la ventana en vuelo");
    // wr_slot se resetea al volver a STOPPED (arranca una corrida nueva), asi
    // que la evidencia hay que buscarla en la MEMORIA, que no se toca.
    bus_rd(20'h20, wrs);
    bus_rd(20'h28, rv);             // seq del proximo evento
    s = rv;
    pulse_trig();
    repeat (20) @(posedge clk);     // parar en pleno drenaje de la ventana
    bus_wr(20'h00, 32'h0);
    repeat (1200) @(posedge clk);
    bus_rd(20'h00, rv);
    checkv("volvio a STOPPED", rv[2:1], 2'd0);
    // La ventana en vuelo tiene que haber terminado y aterrizado completa
    checkv("la ventana en vuelo se completo y su footer esta bien",
           slot_w(s, SLOT_W-1), {~s[31:0], s[31:0]});
    checkv("cabecera del ultimo evento intacta", slot_w(s,1)[31:0], s[31:0]);

    //======================================================================
    $display("[6] contrapresion del bus AXI");
    bus_wr(20'h00, 32'h1);
    repeat (80) @(posedge clk);
    bus_rd(20'h20, wrs);
    bus_wr(20'h24, wrs);
    bus_rd(20'h28, rv);        // seq que le va a tocar al proximo evento
    s = rv;
    fork
      begin
        pulse_trig();
        repeat (2000) @(posedge clk);
      end
      begin
        for (i = 0; i < 2000; i = i + 1) begin
          @(negedge clk);
          axi_wrdy = ($urandom % 100) < 40;
        end
      end
    join_any
    axi_wrdy = 1'b1;
    repeat (800) @(posedge clk);
    bus_rd(20'h20, rv);
    checkv("el evento salio pese a la contrapresion", rv, wrs + 1);
    checkv("footer bien formado con contrapresion",
           slot_w(s, SLOT_W-1), {~s[31:0], s[31:0]});
    // intercalado intacto: la contrapresion no debe desalinear el empaquetado
    errs = 0;
    for (i = 0; i < (32*N_CH)/4; i = i + 1)
      if (slot_w(s,4+i)[31:16] !== ((-$signed(slot_w(s,4+i)[15:0])) & 16'hFFFF))
        errs = errs + 1;
    checkv("intercalado intacto con contrapresion", errs, 0);
    bus_rd(20'h04, rv);
    check("sin overflow del axi_wr_fifo", rv[7] === 1'b0);

    //======================================================================
    $display("");
    $display("  pass=%0d  fail=%0d", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #5000000;
    $display("RESULT: FAIL (timeout global)");
    $finish;
  end

endmodule
