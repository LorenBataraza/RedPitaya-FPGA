`timescale 1ns/1ps
//============================================================================
// tb_event_slot_writer — unidad. Verifica el layout del slot y, sobre todo,
// la DISCIPLINA DE COMMIT.
//
// El punto central: el footer {~seq, seq} tiene que ser la ULTIMA palabra
// emitida del slot, siempre, incluso con contrapresion aleatoria. De eso
// depende que el PS pueda usarlo como marca de "slot completo" apoyandose en el
// ordenamiento de AXI. Si alguna vez saliera antes de algun dato, el PS leeria
// eventos a medio escribir sin ninguna indicacion.
//
// Chequea:
//   1. cantidad exacta de palabras por slot = 2^(slot_shift-3)
//   2. cabecera: timestamp, seq, n_samp, n_ch, snapshot en su lugar
//   3. empaquetado 4 muestras/palabra, primera muestra en [15:0] (little-endian)
//   4. relleno de ceros entre datos y footer
//   5. FOOTER = ultima palabra, y vale {~seq, seq}
//   6. IDEMPOTENCIA ANTE CONTRAPRESION: con wr_rdy aleatorio la secuencia de
//      palabras es identica a la del caso sin contrapresion
//   7. sin creditos el writer SE FRENA (no descarta) y retoma despues
//   8. seq y wr_slot avanzan de a uno por evento
//   9. err_slot_ovf con ventana que no entra en el slot
//============================================================================
module tb_event_slot_writer;

  localparam integer SW    = 16;
  localparam integer S_AW  = 11;
  localparam integer TS_W  = 64;
  localparam integer N_CH  = 2;

  reg clk = 1'b0, rstn = 1'b0;
  always #5 clk = ~clk;

  reg        flush = 1'b0;
  reg [4:0]  slot_shift = 5'd9;      // 512 B = 64 palabras
  reg        credit_ok = 1'b1;
  reg        wr_rdy = 1'b1;

  // --- modelo del stage ---
  reg              stg_meta_val = 1'b0;
  reg [TS_W-1:0]   stg_ts   = 64'h0;
  reg [16:0]       stg_snap = 17'h0;
  reg [S_AW-1:0]   stg_ns   = 11'd0;
  reg [SW-1:0]     stg_dat  = 16'h0;
  wire             stg_meta_rd, stg_dat_rd;

  wire [63:0] wr_dat;
  wire        wr_val;
  wire [31:0] wr_slot, seq;
  wire        no_credit, busy, err_ovf;

  event_slot_writer #(
    .SW(SW), .S_AW(S_AW), .TS_W(TS_W), .N_CH(N_CH)
  ) dut (
    .clk_i(clk), .rstn_i(rstn), .flush_i(flush),
    .slot_shift_i(slot_shift),
    .s_meta_val_i(stg_meta_val), .s_ts_i(stg_ts), .s_snap_i(stg_snap),
    .s_nsamp_i(stg_ns), .s_meta_rd_o(stg_meta_rd),
    .s_dat_i(stg_dat), .s_dat_rd_o(stg_dat_rd),
    .credit_ok_i(credit_ok),
    .wr_dat_o(wr_dat), .wr_val_o(wr_val), .wr_rdy_i(wr_rdy),
    .wr_slot_o(wr_slot), .seq_o(seq),
    .no_credit_o(no_credit), .busy_o(busy), .err_slot_ovf_o(err_ovf)
  );

  //--------------------------------------------------------------------------
  integer pass_cnt = 0, fail_cnt = 0;
  task automatic checkv(input string name, input longint got, input longint exp);
    begin
      if (got === exp) pass_cnt = pass_cnt + 1;
      else begin
        fail_cnt = fail_cnt + 1;
        $display("  FAIL: %s (got=%0h exp=%0h)", name, got, exp);
      end
    end
  endtask
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt = pass_cnt + 1;
      else begin fail_cnt = fail_cnt + 1; $display("  FAIL: %s", name); end
    end
  endtask

  //--------------------------------------------------------------------------
  // Modelo del stage: rampa de muestras. La muestra i-esima del evento vale
  // (base + i), asi el empaquetado es verificable por valor.
  //--------------------------------------------------------------------------
  integer stg_idx  = 0;
  integer stg_base = 0;

  always @(posedge clk) begin
    if (stg_dat_rd) begin
      stg_dat <= (stg_base + stg_idx);
      stg_idx <= stg_idx + 1;
    end
  end

  //--------------------------------------------------------------------------
  // Captura del stream de salida
  //--------------------------------------------------------------------------
  reg [63:0] cap [0:1023];
  integer    cap_n = 0;
  integer    foot_pos = -1;
  integer    last_data_pos = -1;

  always @(posedge clk) begin
    if (wr_val && wr_rdy) begin
      cap[cap_n] = wr_dat;
      // posicion de la ultima palabra que NO es cero (proxy de "ultimo dato")
      if (wr_dat != 64'h0) last_data_pos = cap_n;
      cap_n = cap_n + 1;
    end
  end

  task automatic cap_clear; begin cap_n = 0; last_data_pos = -1; end endtask

  //--------------------------------------------------------------------------
  task automatic push_event(input [63:0] ts, input [16:0] sn,
                            input integer ns, input integer base);
    begin
      @(negedge clk);
      stg_ts       = ts;
      stg_snap     = sn;
      stg_ns       = ns;
      stg_base     = base;
      stg_idx      = 0;
      stg_meta_val = 1'b1;
      // el writer consume el metadato al final del slot
      wait (stg_meta_rd === 1'b1);
      @(negedge clk);
      stg_meta_val = 1'b0;
    end
  endtask

  task automatic wait_idle(input integer max_cyc);
    integer k;
    begin
      k = 0;
      while (busy && k < max_cyc) begin @(posedge clk); k = k + 1; end
      repeat (3) @(posedge clk);
    end
  endtask

  //--------------------------------------------------------------------------
  integer i, errs, exp_words, ndata;
  reg [63:0] w, ref_cap [0:1023];
  integer    ref_n;

  initial begin
    $dumpfile("tb_event_slot_writer.vcd");
    $dumpvars(0, tb_event_slot_writer);

    repeat (4) @(posedge clk);
    rstn = 1'b1;
    repeat (2) @(posedge clk);

    exp_words = (1 << (9-3));   // slot_shift=9 -> 64 palabras

    //======================================================================
    $display("[1] layout de un slot: pre+post = 32 muestras/canal");
    cap_clear();
    push_event(64'h1122_3344_5566_7788, 17'h5, 32, 100);
    wait_idle(2000);

    checkv("palabras por slot", cap_n, exp_words);
    checkv("hdr0 timestamp",    cap[0], 64'h1122_3344_5566_7788);
    checkv("hdr1 seq",          cap[1][31:0],  32'd0);
    checkv("hdr1 n_samp",       cap[1][47:32], 32);
    checkv("hdr1 n_ch",         cap[1][55:48], N_CH);
    checkv("hdr2 snapshot",     cap[2][16:0],  17'h5);
    checkv("hdr3 reservado",    cap[3], 64'h0);

    // Empaquetado: 32 muestras/canal x 2 canales = 64 muestras = 16 palabras
    ndata = (32*N_CH)/4;
    errs = 0;
    for (i = 0; i < ndata; i = i + 1) begin
      w = cap[4+i];
      if (w[15:0]  !== ((100 + 4*i + 0) & 16'hFFFF)) errs = errs + 1;
      if (w[31:16] !== ((100 + 4*i + 1) & 16'hFFFF)) errs = errs + 1;
      if (w[47:32] !== ((100 + 4*i + 2) & 16'hFFFF)) errs = errs + 1;
      if (w[63:48] !== ((100 + 4*i + 3) & 16'hFFFF)) errs = errs + 1;
    end
    checkv("empaquetado 4 muestras/palabra little-endian", errs, 0);

    // Relleno de ceros entre datos y footer
    errs = 0;
    for (i = 4+ndata; i < exp_words-1; i = i + 1)
      if (cap[i] !== 64'h0) errs = errs + 1;
    checkv("relleno de ceros", errs, 0);

    // EL PUNTO CENTRAL: footer al final, y despues de todos los datos
    checkv("footer es la ultima palabra", cap[exp_words-1], {~32'd0, 32'd0});
    check("footer despues del ultimo dato", last_data_pos <= exp_words-1);
    checkv("wr_slot avanzo", wr_slot, 1);
    checkv("seq avanzo", seq, 1);

    // guardar como referencia para el test de contrapresion
    ref_n = cap_n;
    for (i = 0; i < cap_n; i = i + 1) ref_cap[i] = cap[i];

    //======================================================================
    $display("[2] segundo evento: seq y footer avanzan");
    cap_clear();
    push_event(64'hDEAD_BEEF_0000_0001, 17'h9, 32, 200);
    wait_idle(2000);
    checkv("palabras por slot (2do)", cap_n, exp_words);
    checkv("hdr1 seq = 1", cap[1][31:0], 32'd1);
    checkv("footer = {~1,1}", cap[exp_words-1], {~32'd1, 32'd1});
    checkv("wr_slot=2", wr_slot, 2);

    //======================================================================
    $display("[3] contrapresion aleatoria: stream identico");
    cap_clear();
    fork
      begin
        // reproducir exactamente el evento [1] pero con wr_rdy pinchado
        push_event(64'h1122_3344_5566_7788, 17'h5, 32, 100);
      end
      begin
        for (i = 0; i < 4000; i = i + 1) begin
          @(negedge clk);
          wr_rdy = ($random % 100) < 55;
        end
      end
    join_any
    wr_rdy = 1'b1;
    wait_idle(4000);

    checkv("misma cantidad de palabras con contrapresion", cap_n, ref_n);
    errs = 0;
    for (i = 0; i < ref_n; i = i + 1) begin
      // seq cambia (es el 3er evento), asi que se excluyen hdr1 y el footer
      if (i != 1 && i != ref_n-1 && cap[i] !== ref_cap[i]) errs = errs + 1;
    end
    checkv("stream identico salvo seq/footer", errs, 0);
    checkv("footer al final con contrapresion", cap[ref_n-1], {~32'd2, 32'd2});

    //======================================================================
    $display("[4] sin creditos: se FRENA, no descarta");
    cap_clear();
    credit_ok = 1'b0;
    fork
      begin push_event(64'h5555_0000_0000_0000, 17'h3, 32, 300); end
      begin
        repeat (60) @(posedge clk);
        checkv("nada emitido sin creditos", cap_n, 0);
        check("no_credit levantado", no_credit === 1'b1);
        check("no esta busy", busy === 1'b0);
        @(negedge clk);
        credit_ok = 1'b1;     // devolver el credito
      end
    join
    wait_idle(2000);
    checkv("el evento salio entero al volver el credito", cap_n, exp_words);
    checkv("footer correcto tras el freno", cap[exp_words-1], {~32'd3, 32'd3});
    checkv("wr_slot=4", wr_slot, 4);

    //======================================================================
    $display("[5] ventana impar (30 muestras/canal = 60, no multiplo de 4)");
    cap_clear();
    push_event(64'h7777_0000_0000_0000, 17'h1, 30, 400);
    wait_idle(2000);
    checkv("palabras por slot (impar)", cap_n, exp_words);
    // 60 muestras -> 15 palabras exactas
    checkv("ultima palabra de datos", cap[4+14][63:48], (400+59) & 16'hFFFF);
    checkv("footer al final (impar)", cap[exp_words-1], {~32'd4, 32'd4});

    //======================================================================
    $display("[6] err_slot_ovf: ventana que no entra en el slot");
    cap_clear();
    check("err_ovf limpio antes", err_ovf === 1'b0);
    slot_shift = 5'd6;    // 64 B = 8 palabras: no entra ni la cabecera + datos
    push_event(64'h0, 17'h0, 32, 500);
    wait_idle(4000);
    check("err_slot_ovf levantado", err_ovf === 1'b1);
    checkv("no se paso del slot", cap_n, (1<<(6-3)));

    //======================================================================
    $display("");
    $display("  pass=%0d  fail=%0d", pass_cnt, fail_cnt);
    if (fail_cnt == 0) $display("RESULT: PASS");
    else               $display("RESULT: FAIL");
    $finish;
  end

  initial begin
    #2000000;
    $display("RESULT: FAIL (timeout global)");
    $finish;
  end

endmodule
