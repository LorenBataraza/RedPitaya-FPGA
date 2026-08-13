`timescale 1ns/1ps
//============================================================================
// tb_mca_pulse_feature — unidad. Verifica el segmentador y el extractor:
//   - ventana del pulso, q_tot y q_tail contra valores calculados a mano
//   - los dos estimadores de amplitud (pico / integral)
//   - línea de base fija y automática, con holdoff
//   - rechazos: bajo umbral, fuera de [min,max], apilamiento
//   - casos borde del PSD: q_tot=0 y q_tail==q_tot
//
// Se usa un pulso RECTANGULAR en casi todos los tests a propósito: su ventana
// es inequívoca, así que los valores esperados salen de una multiplicación y
// el test no termina reimplementando el DUT.
//============================================================================
module tb_mca_pulse_feature;

  localparam integer DW = 14, QW = 32, AMP_W = 16, PSD_AW = 6, LEN_W = 16;

  reg  clk=0, rstn=0;
  always #5 clk = ~clk;

  reg signed [DW-1:0]  dat = 0;
  reg                  val = 0;

  reg                  cfg_run      = 1'b1;
  reg signed [DW-1:0]  cfg_thr      = 100;
  reg        [DW-1:0]  cfg_hyst     = 50;
  reg signed [DW-1:0]  cfg_baseline = 0;
  reg                  cfg_bl_auto  = 1'b0;
  reg        [3:0]     cfg_bl_k     = 4'd4;
  reg        [LEN_W-1:0] cfg_bl_holdoff = 0;
  reg        [LEN_W-1:0] cfg_maxlen   = 1000;
  reg        [LEN_W-1:0] cfg_tail_dly = 1;
  reg                    cfg_gate_mode  = 1'b0;   // 0 = histeresis (como antes)
  reg        [LEN_W-1:0] cfg_gate_short = 32;
  reg        [LEN_W-1:0] cfg_gate_long  = 384;
  reg        [AMP_W-1:0] cfg_amp_min  = 0;
  reg        [AMP_W-1:0] cfg_amp_max  = 16'hFFFF;
  reg                  cfg_amp_src  = 1'b0;
  reg        [4:0]     cfg_q_shift  = 0;

  wire                 ev_valid;
  wire [AMP_W-1:0]     ev_amp;
  wire [PSD_AW-1:0]    ev_psd;
  wire                 ev_psd_ok;
  wire signed [DW-1:0] baseline;
  wire                 bl_stale, busy;
  wire [31:0]          c_total, c_acc, c_rej_amp, c_rej_psd, c_pileup, c_lost;
  wire [QW-1:0]        last_qtot, last_qtail;

  mca_pulse_feature #(
    .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .LEN_W(LEN_W), .EN_PSD(1)
  ) dut (
    .clk_i(clk), .rstn_i(rstn),
    .dat_i(dat), .val_i(val),
    .cfg_run_i(cfg_run), .cnt_clr_i(1'b0),
    .cfg_thr_i(cfg_thr), .cfg_hyst_i(cfg_hyst),
    .cfg_baseline_i(cfg_baseline), .cfg_bl_auto_i(cfg_bl_auto),
    .cfg_bl_k_i(cfg_bl_k), .cfg_bl_holdoff_i(cfg_bl_holdoff),
    .cfg_maxlen_i(cfg_maxlen), .cfg_tail_dly_i(cfg_tail_dly),
    .cfg_gate_mode_i(cfg_gate_mode), .cfg_gate_short_i(cfg_gate_short),
    .cfg_gate_long_i(cfg_gate_long),
    .cfg_amp_min_i(cfg_amp_min), .cfg_amp_max_i(cfg_amp_max),
    .cfg_amp_src_i(cfg_amp_src), .cfg_q_shift_i(cfg_q_shift),
    .ev_valid_o(ev_valid), .ev_amp_o(ev_amp), .ev_psd_o(ev_psd),
    .ev_psd_ok_o(ev_psd_ok),
    .baseline_o(baseline), .baseline_stale_o(bl_stale),
    .cnt_total_o(c_total), .cnt_accepted_o(c_acc), .cnt_rej_amp_o(c_rej_amp),
    .cnt_rej_psd_o(c_rej_psd), .cnt_pileup_o(c_pileup), .cnt_lost_busy_o(c_lost),
    .last_qtot_o(last_qtot), .last_qtail_o(last_qtail),
    .busy_o(busy)
  );

  integer pass_cnt=0, fail_cnt=0;
  task automatic check(input string name, input bit cond);
    begin
      if (cond) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1; $display("  FAIL: %s", name); end
    end
  endtask
  task automatic checkv(input string name, input integer got, input integer exp);
    begin
      if (got===exp) pass_cnt=pass_cnt+1;
      else begin fail_cnt=fail_cnt+1;
        $display("  FAIL: %s  (obtenido %0d, esperado %0d)", name, got, exp); end
    end
  endtask

  // Captura del último evento emitido
  reg [AMP_W-1:0]  ev_amp_q;
  reg [PSD_AW-1:0] ev_psd_q;
  reg              ev_psd_ok_q;
  integer          ev_count;
  always @(posedge clk) if (rstn && ev_valid) begin
    ev_amp_q <= ev_amp; ev_psd_q <= ev_psd; ev_psd_ok_q <= ev_psd_ok;
    ev_count <= ev_count + 1;
  end

  //-------------------------------------------------------------------------
  task automatic push(input integer v);
    begin @(negedge clk); dat = v[DW-1:0]; val = 1'b1; end
  endtask

  // Pulso rectangular de n muestras de valor v, y una muestra de cierre.
  task automatic pulse_rect(input integer v, input integer n, input integer lo);
    integer k;
    begin
      for (k=0;k<n;k=k+1) push(v);
      push(lo);                       // esta muestra cierra y NO se acumula
    end
  endtask

  task automatic settle;             // deja terminar el divisor y el evento
    begin @(negedge clk); val=1'b0; repeat(15) @(negedge clk); end
  endtask

  task automatic reset_dut;
    begin
      rstn=0; val=0; dat=0; ev_count=0;
      repeat(3) @(negedge clk); rstn=1; repeat(2) @(negedge clk);
      // dejar el Schmitt armado (x por debajo de thr_lo)
      push(0); push(0); push(0); @(negedge clk); val=0;
    end
  endtask

  integer i;

  initial begin
    $dumpfile("tb_mca_pulse_feature.vcd");
    $dumpvars(0, tb_mca_pulse_feature);

    //-----------------------------------------------------------------------
    // 1) Pulso rectangular: ventana, q_tot, q_tail, amplitud de pico, psd
    //    20 muestras de 500 sobre base 0, thr=100, hyst=50, tail_dly=1
    //    q_tot  = 20*500 = 10000
    //    q_tail = 19*500 =  9500   (arranca en la 2da muestra)
    //    psd    = floor(9500*64/10000) = 60
    //-----------------------------------------------------------------------
    reset_dut;
    pulse_rect(500, 20, 0);
    settle;
    checkv("rect: cnt_total",        c_total,    1);
    checkv("rect: cnt_accepted",     c_acc,      1);
    checkv("rect: q_tot = 20*500",   last_qtot,  10000);
    checkv("rect: q_tail = 19*500",  last_qtail, 9500);
    checkv("rect: amplitud de pico", ev_amp_q,   500);
    checkv("rect: psd = 60",         ev_psd_q,   60);
    check ("rect: psd valido",       ev_psd_ok_q===1'b1);
    checkv("rect: un solo evento",   ev_count,   1);

    //-----------------------------------------------------------------------
    // 2) Estimador de INTEGRAL: amp = q_tot >> q_shift = 10000>>5 = 312
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_amp_src = 1'b1; cfg_q_shift = 5;
    pulse_rect(500, 20, 0);
    settle;
    checkv("integral: amp = 10000>>5", ev_amp_q, 312);
    cfg_amp_src = 1'b0; cfg_q_shift = 0;

    //-----------------------------------------------------------------------
    // 3) Pulso por debajo del umbral: no genera evento
    //-----------------------------------------------------------------------
    reset_dut;
    pulse_rect(50, 20, 0);            // 50 < thr=100
    settle;
    checkv("bajo umbral: sin eventos",  c_total, 0);
    checkv("bajo umbral: sin aceptados", c_acc,  0);

    //-----------------------------------------------------------------------
    // 4) Ventana de aceptación de amplitud
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_amp_max = 400;                // el pico de 500 queda afuera
    pulse_rect(500, 20, 0);
    settle;
    checkv("amp>max: contado en total",   c_total,   1);
    checkv("amp>max: rechazado",          c_rej_amp, 1);
    checkv("amp>max: no aceptado",        c_acc,     0);
    cfg_amp_max = 16'hFFFF;

    reset_dut;
    cfg_amp_min = 600;                // el pico de 500 queda por debajo
    pulse_rect(500, 20, 0);
    settle;
    checkv("amp<min: rechazado",          c_rej_amp, 1);
    checkv("amp<min: no aceptado",        c_acc,     0);
    cfg_amp_min = 0;

    //-----------------------------------------------------------------------
    // 5) APILAMIENTO: la ventana llega a maxlen
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_maxlen = 10;
    pulse_rect(500, 30, 0);           // 30 muestras > maxlen=10
    settle;
    checkv("apilamiento: cnt_pileup",     c_pileup, 1);
    checkv("apilamiento: no aceptado",    c_acc,    0);
    checkv("apilamiento: contado en total", c_total, 1);

    //-----------------------------------------------------------------------
    // 6) Pulso que NUNCA vuelve a bajar de la histéresis: cierra por maxlen
    //    y el modulo no se cuelga (vuelve a IDLE y acepta el pulso siguiente)
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_maxlen = 10;
    for (i=0;i<40;i=i+1) push(500);   // se queda arriba, sin muestra de cierre
    settle;
    check ("sin retorno: no queda colgado (busy bajo)", busy===1'b0);
    check ("sin retorno: cerro por maxlen",             c_pileup >= 1);
    cfg_maxlen = 1000;

    //-----------------------------------------------------------------------
    // 7) Línea de base FIJA distinta de cero: q_tot usa (muestra - base)
    //    base=200, pulso de 500 -> x=300 ; q_tot = 20*300 = 6000
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_baseline = 200;
    pulse_rect(500, 20, 200);
    settle;
    checkv("base=200: q_tot = 20*300",  last_qtot, 6000);
    checkv("base=200: amp = 300",       ev_amp_q,  300);
    cfg_baseline = 0;

    //-----------------------------------------------------------------------
    // 8) Línea de base AUTOMÁTICA: converge al valor DC de la entrada
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_bl_auto = 1'b1; cfg_bl_k = 4'd4;
    for (i=0;i<400;i=i+1) push(80);   // DC de 80, por debajo del umbral
    @(negedge clk); val=1'b0;
    check("base auto: converge a ~80", (baseline > 70) && (baseline < 90));

    // ...y se CONGELA durante el pulso (no sigue a la cima)
    for (i=0;i<40;i=i+1) push(3000);
    @(negedge clk); val=1'b0;
    check("base auto: congelada durante el pulso", (baseline > 70) && (baseline < 90));
    cfg_bl_auto = 1'b0;

    //-----------------------------------------------------------------------
    // 9) Caso borde PSD: q_tot == 0  -> err del divisor -> cnt_rej_psd
    //    thr=0 y muestras en 0: abre con xc=0 y acumula 0.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_thr = 0; cfg_hyst = 0;
    push(-10); push(-10);             // re-armar por debajo de thr_lo=0
    for (i=0;i<10;i=i+1) push(0);     // abre, q_tot = 0
    push(-10);                        // cierra
    settle;
    checkv("q_tot=0: q_tot leido",       last_qtot,  0);
    checkv("q_tot=0: cnt_rej_psd",       c_rej_psd,  1);
    check ("q_tot=0: evento sin psd valido", ev_psd_ok_q===1'b0);
    checkv("q_tot=0: igual entra al espectro 1D", c_acc, 1);

    //-----------------------------------------------------------------------
    // 10) Caso borde PSD: q_tail == q_tot -> guarda psd_inputs_ok
    //     Con tail_dly=0 y primera muestra nula, la cola acumula lo mismo
    //     que el total. Sin la guarda, el cociente daria 2^PSD_AW y ENVOLVERIA
    //     A 0, mandando el evento al extremo opuesto del eje.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_thr = 0; cfg_hyst = 0; cfg_tail_dly = 0;
    push(-10); push(-10);
    push(0);                          // abre con xc=0
    for (i=0;i<10;i=i+1) push(500);
    push(-10);                        // cierra
    settle;
    checkv("q_tail==q_tot: ambos 5000 (tot)",  last_qtot,  5000);
    checkv("q_tail==q_tot: ambos 5000 (tail)", last_qtail, 5000);
    checkv("q_tail==q_tot: cnt_rej_psd",       c_rej_psd,  1);
    check ("q_tail==q_tot: psd invalidado (no envuelve a 0)", ev_psd_ok_q===1'b0);
    cfg_thr = 100; cfg_hyst = 50; cfg_tail_dly = 1;

    //-----------------------------------------------------------------------
    // 11) Dos pulsos SEPARADOS (hueco > latencia del divisor): se cuentan los dos
    //-----------------------------------------------------------------------
    reset_dut;
    pulse_rect(500, 20, 0);
    for (i=0;i<15;i=i+1) push(0);     // hueco holgado: el divisor termina
    pulse_rect(300, 10, 0);
    settle;
    checkv("dos pulsos separados: cnt_total",     c_total,   2);
    checkv("dos pulsos separados: cnt_accepted",  c_acc,     2);
    checkv("dos pulsos separados: amp del 2do",   ev_amp_q,  300);
    checkv("dos pulsos separados: q_tot del 2do", last_qtot, 3000);
    checkv("dos pulsos separados: nada perdido",  c_lost,    0);

    //-----------------------------------------------------------------------
    // 11b) TIEMPO MUERTO: segundo pulso encima del divisor ocupado.
    //      Tiene que perderse ENTERO y contarse, nunca abrirse a mitad de
    //      camino (una amplitud truncada contaminaria el espectro).
    //-----------------------------------------------------------------------
    reset_dut;
    pulse_rect(500, 20, 0);
    push(0); push(0);                 // hueco corto: el divisor sigue ocupado
    pulse_rect(300, 10, 0);
    settle;
    checkv("tiempo muerto: solo el 1er pulso contado", c_total, 1);
    check ("tiempo muerto: el 2do se contabiliza como perdido", c_lost > 0);
    checkv("tiempo muerto: amp del 1ro intacta",       ev_amp_q,  500);
    checkv("tiempo muerto: q_tot del 1ro intacto",     last_qtot, 10000);

    //-----------------------------------------------------------------------
    // 12) cfg_run=0 inhibe la detección
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_run = 1'b0;
    pulse_rect(500, 20, 0);
    settle;
    checkv("run=0: no detecta", c_total, 0);
    cfg_run = 1'b1;

    //=======================================================================
    // 13) COMPUERTAS DE LARGO FIJO (cfg_gate_mode = 1)
    //
    // Se sigue usando pulso RECTANGULAR: con la compuerta fija los valores
    // esperados salen de una multiplicacion y el test no reimplementa el DUT.
    //=======================================================================

    //-----------------------------------------------------------------------
    // 13a) La compuerta larga define el largo: mas CORTA que el pulso.
    //      30 muestras de 500 con gate_long=10 -> q_tot = 10*500
    //      (10 muestras: la que abre + 9 en S_ACTIVE, igual que en modo 0)
    //      La senal sigue alta al cerrar -> APILAMIENTO.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    pulse_rect(500, 30, 0);
    settle;
    checkv("compuerta corta que el pulso: q_tot = 10*500", last_qtot, 5000);
    checkv("compuerta: contado en total",                  c_total,   1);
    checkv("compuerta: senal alta al cerrar -> apilamiento", c_pileup, 1);
    checkv("compuerta: apilado NO se acepta",              c_acc,     0);

    //-----------------------------------------------------------------------
    // 13b) Compuerta MAS LARGA que el pulso: el pulso entra entero y la
    //      senal ya bajo al cerrar, asi que NO es apilamiento.
    //      q_tot = 20*500 (las 20 muestras del pulso; el resto suma 0)
    //      q_tail: desde gate_short=4 hasta el cierre -> 16 muestras de 500
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 40;
    pulse_rect(500, 20, 0);
    for (i=0;i<30;i=i+1) push(0);      // relleno hasta cerrar la compuerta
    settle;
    checkv("compuerta larga: q_tot = 20*500",   last_qtot,  10000);
    checkv("compuerta larga: q_tail = 16*500",  last_qtail, 8000);
    checkv("compuerta larga: NO es apilamiento", c_pileup,  0);
    checkv("compuerta larga: aceptado",          c_acc,     1);
    checkv("compuerta larga: amplitud de pico",  ev_amp_q,  500);

    //-----------------------------------------------------------------------
    // 13c) El largo NO depende de la senal: dos pulsos de amplitud distinta
    //      pero misma compuerta dan la MISMA cantidad de muestras integradas.
    //      Es la propiedad por la que existe este modo.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 40;
    pulse_rect(200, 20, 0);
    for (i=0;i<30;i=i+1) push(0);
    settle;
    checkv("misma compuerta, otra amplitud: q_tot = 20*200", last_qtot, 4000);

    //-----------------------------------------------------------------------
    // 13d) cfg_maxlen NO actua en modo compuerta: con maxlen mas chico que la
    //      compuerta el evento igual cierra por compuerta, no por maxlen.
    //      (Si maxlen actuara, esto contaria como apilamiento.)
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 40;
    cfg_maxlen = 5;
    pulse_rect(500, 20, 0);
    for (i=0;i<30;i=i+1) push(0);
    settle;
    checkv("maxlen no actua en modo compuerta: q_tot completo", last_qtot, 10000);
    checkv("maxlen no actua en modo compuerta: sin apilamiento", c_pileup, 0);
    cfg_maxlen = 1000;

    //-----------------------------------------------------------------------
    // 13e) REGRESION: con gate_mode=0 todo se comporta como antes.
    //      Mismo escenario que el test 1, con las compuertas configuradas en
    //      valores que romperian el resultado si el modo 0 las mirara.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b0; cfg_gate_short = 2; cfg_gate_long = 3;
    pulse_rect(500, 20, 0);
    settle;
    checkv("modo 0 ignora gate_long: q_tot = 20*500",  last_qtot,  10000);
    checkv("modo 0 ignora gate_short: q_tail = 19*500", last_qtail, 9500);
    checkv("modo 0: sin apilamiento",                   c_pileup,   0);
    cfg_gate_short = 32; cfg_gate_long = 384;

    $display("---------------------------------------------");
    $display("tb_mca_pulse_feature: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #2000000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
