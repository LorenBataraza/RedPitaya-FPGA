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
  localparam integer DIV_W = 16, NFEAT = 16;
  // Indices del bus de features (los mismos localparam del DUT).
  localparam integer F_PEAK=0, F_INT=1, F_PSD=2, F_INVW=3, F_LEN=4, F_TRISE=5;

  reg  clk=0, rstn=0;
  always #5 clk = ~clk;

  reg signed [DW-1:0]  dat = 0;
  reg                  val = 0;

  reg                  cfg_run      = 1'b1;
  reg                  veto         = 1'b0;
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
  // FASE 2. Arrancan en el comportamiento historico: Schmitt interno, re-armado
  // por nivel, publicacion bloqueante. Asi los tests 1..14 de arriba valen tal
  // cual y cualquier diferencia que aparezca es una regresion de verdad.
  reg                  trig           = 1'b0;
  reg        [1:0]     cfg_trig_src   = 2'd0;   // 0 = interno
  reg                  cfg_rearm_mode = 1'b0;   // 0 = nivel
  reg        [LEN_W-1:0] cfg_rearm_dly = 0;
  reg                  cfg_pub_mode   = 1'b0;   // 0 = bloqueante

  wire                 ev_valid;
  wire [NFEAT*AMP_W-1:0] ev_feat;
  wire [AMP_W-1:0]     ev_amp;
  wire [PSD_AW-1:0]    ev_psd;
  wire                 ev_psd_ok;
  wire signed [DW-1:0] baseline;
  wire                 bl_stale, busy;
  wire [31:0]          c_total, c_acc, c_rej_amp, c_rej_psd, c_pileup, c_lost;
  wire [QW-1:0]        last_qtot, last_qtail;
  // Casilleros de tiempo muerto y atribucion de arribos
  wire                 dt_win, dt_div, dt_rearm, puede_abrir, arribo;
  wire [31:0]          c_cross, c_open, c_lost_rearm, c_lost_active, c_lost_veto;
  // FASE 2
  wire [31:0]          c_lost_notrig, c_win, c_trig;
  wire [1:0]           pub_occ, pub_occ_max;
  wire [15:0]          last_win_id;

  mca_pulse_feature #(
    .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .DIV_W(DIV_W),
    .NFEAT(NFEAT), .LEN_W(LEN_W), .EN_PSD(1)
  ) dut (
    .clk_i(clk), .rstn_i(rstn),
    .dat_i(dat), .val_i(val),
    .cfg_run_i(cfg_run), .veto_i(veto), .cnt_clr_i(1'b0),
    .cfg_thr_i(cfg_thr), .cfg_hyst_i(cfg_hyst),
    .cfg_baseline_i(cfg_baseline), .cfg_bl_auto_i(cfg_bl_auto),
    .cfg_bl_k_i(cfg_bl_k), .cfg_bl_holdoff_i(cfg_bl_holdoff),
    .cfg_maxlen_i(cfg_maxlen), .cfg_tail_dly_i(cfg_tail_dly),
    .cfg_gate_mode_i(cfg_gate_mode), .cfg_gate_short_i(cfg_gate_short),
    .cfg_gate_long_i(cfg_gate_long),
    .cfg_amp_min_i(cfg_amp_min), .cfg_amp_max_i(cfg_amp_max),
    .cfg_amp_src_i(cfg_amp_src), .cfg_q_shift_i(cfg_q_shift),
    .trig_i(trig), .cfg_trig_src_i(cfg_trig_src),
    .cfg_rearm_mode_i(cfg_rearm_mode), .cfg_rearm_dly_i(cfg_rearm_dly),
    .cfg_pub_mode_i(cfg_pub_mode),
    .ev_valid_o(ev_valid), .ev_amp_o(ev_amp), .ev_psd_o(ev_psd),
    .ev_psd_ok_o(ev_psd_ok), .ev_feat_o(ev_feat),
    .baseline_o(baseline), .baseline_stale_o(bl_stale),
    .cnt_total_o(c_total), .cnt_accepted_o(c_acc), .cnt_rej_amp_o(c_rej_amp),
    .cnt_rej_psd_o(c_rej_psd), .cnt_pileup_o(c_pileup), .cnt_lost_busy_o(c_lost),
    .last_qtot_o(last_qtot), .last_qtail_o(last_qtail),
    .busy_o(busy),
    .dt_win_o(dt_win), .dt_div_o(dt_div), .dt_rearm_o(dt_rearm),
    .puede_abrir_o(puede_abrir), .arribo_o(arribo),
    .cnt_cross_o(c_cross), .cnt_open_o(c_open),
    .cnt_lost_rearm_o(c_lost_rearm), .cnt_lost_active_o(c_lost_active),
    .cnt_lost_veto_o(c_lost_veto),
    .cnt_lost_notrig_o(c_lost_notrig), .cnt_win_o(c_win),
    .pub_occ_o(pub_occ), .pub_occ_max_o(pub_occ_max),
    .last_win_id_o(last_win_id), .cnt_trig_o(c_trig)
  );

  // Testigo del tiempo muerto OCULTO: ciclos en que el modulo no puede abrir
  // pero busy_o esta bajo, o sea los que el contador viejo daba como vivos.
  integer ciclos_ocultos = 0;
  always @(posedge clk) if (rstn && dt_rearm && !busy)
    ciclos_ocultos <= ciclos_ocultos + 1;

  // FASE 2. Testigo del bloqueo por CONTRAPRESION de la FIFO: ciclos en que el
  // casillero de publicacion esta alto con la FSM de ventana en reposo. En modo
  // bloqueante es cero por construccion (ahi dt_div == S_DIV, y S_DIV implica
  // busy); todo lo que cuente aca es tiempo muerto del arbitro, que es
  // exactamente lo que no podia quedar sin contar.
  integer ciclos_fifo = 0;
  always @(posedge clk) if (rstn && dt_div && !busy)
    ciclos_fifo <= ciclos_fifo + 1;

  // Suma de los casilleros de perdida, para no repetir la lista en cada check.
  function automatic integer perdidos;
    perdidos = c_lost_rearm + c_lost_active + c_lost + c_lost_veto + c_lost_notrig;
  endfunction

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
  reg [NFEAT*AMP_W-1:0] ev_feat_q;
  integer          ev_count;
  always @(posedge clk) if (rstn && ev_valid) begin
    ev_amp_q <= ev_amp; ev_psd_q <= ev_psd; ev_psd_ok_q <= ev_psd_ok;
    ev_feat_q <= ev_feat;
    ev_count <= ev_count + 1;
  end

  // Lectura de una ranura del bus de features capturado.
  function automatic [AMP_W-1:0] feat(input integer idx);
    feat = ev_feat_q[idx*AMP_W +: AMP_W];
  endfunction

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

  // Los divisores tardan DIV_W ciclos (16), no 6: con 15 el evento todavia no
  // habia salido y TODOS los checks del evento fallaban a la vez. Se deja
  // margen holgado, que en un TB no cuesta nada.
  task automatic settle;             // deja terminar los divisores y el evento
    begin @(negedge clk); val=1'b0; repeat(28) @(negedge clk); end
  endtask

  // Un flanco de trigger externo que dura `n` muestras en alto. Con n > 1 sirve
  // para comprobar que la apertura es por FLANCO: un trigger por software dura
  // ~5 ciclos de bus y por nivel abriria una ventana por ciclo.
  task automatic trig_push(input integer v, input integer n);
    integer k;
    begin
      trig = 1'b1;
      for (k=0;k<n;k=k+1) push(v);
      trig = 1'b0;
    end
  endtask

  task automatic reset_dut;
    begin
      rstn=0; val=0; dat=0; ev_count=0; ciclos_ocultos=0; ciclos_fifo=0;
      trig=0;
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
    // 1b) EL BUS DE FEATURES sobre el mismo pulso rectangular. Los valores
    //     salen de una cuenta a mano, no de reimplementar el DUT:
    //       F_PEAK  = 500 << (AMP_W-DW) = 2000   <- alineado a la IZQUIERDA
    //       F_INT   = q_tot >> q_shift = 10000 (q_shift = 0)
    //       F_LEN   = 20 muestras acumuladas
    //       F_TRISE = 0   (el pico es la PRIMERA muestra; comparacion estricta)
    //       F_PSD   = floor(9500 * 2^16 / 10000) = 62259
    //       F_INVW  = floor( 500 * 2^16 / 10000) =  3276   <- P/Q, ancho inverso
    //-----------------------------------------------------------------------
    checkv("bus: F_PEAK alineado = 500<<2", feat(F_PEAK), 500 << (AMP_W-DW));
    checkv("bus: F_INT   = 10000", feat(F_INT),   10000);
    checkv("bus: F_LEN   = 20",    feat(F_LEN),   20);
    checkv("bus: F_TRISE = 0",     feat(F_TRISE), 0);
    checkv("bus: F_PSD   = 62259", feat(F_PSD),   62259);
    checkv("bus: F_INVW  = 3276",  feat(F_INVW),  3276);
    // El eje de 6 bits del mapa 2D tiene que ser EXACTAMENTE los 6 bits altos
    // del cociente de 16: es lo que hace que ampliar el divisor no mueva ni un
    // evento del mapa ya caracterizado.
    checkv("bus: ev_psd son los 6 bits altos de F_PSD",
           ev_psd_q, 62259 >> (DIV_W - PSD_AW));
    // Las ranuras sin productor tienen que estar en CERO, no en X: el
    // discriminador y el selector de eje las pueden leer.
    check ("bus: ranura 6 reservada en cero",  feat(6)  === {AMP_W{1'b0}});
    check ("bus: ranura 15 reservada en cero", feat(15) === {AMP_W{1'b0}});

    //-----------------------------------------------------------------------
    // 1c) El ANCHO INVERSO separa pulsos de distinto ancho a igual amplitud.
    //     Es la propiedad por la que existe: un apilado es mas ANCHO por unidad
    //     de altura que un evento limpio, y P/Q lo ve aunque Q_cola/Q_total no.
    //       10 muestras: F_INVW = floor(500*2^16/5000)  = 6553
    //       40 muestras: F_INVW = floor(500*2^16/20000) = 1638
    //-----------------------------------------------------------------------
    reset_dut;  pulse_rect(500, 10, 0);  settle;
    checkv("ancho inverso: pulso corto  = 6553", feat(F_INVW), 6553);
    reset_dut;  pulse_rect(500, 40, 0);  settle;
    checkv("ancho inverso: pulso largo  = 1638", feat(F_INVW), 1638);
    check ("ancho inverso: mas ancho => menor P/Q", 6553 > 1638);
    // Y el pico NO cambia: los dos ejes son independientes, que es lo que
    // permite usarlos como ejes separables de un mapa 2D.
    checkv("ancho inverso: el pico no cambia con el ancho",
           feat(F_PEAK), 500 << (AMP_W-DW));

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
    // 4b) BORDES de la ventana. La ventana se evalua sobre q_tot SIN
    //     desplazar, contra umbrales pre-desplazados, un ciclo antes del
    //     cierre (es lo que saco el barrel shifter del camino critico). Estos
    //     casos fijan que la equivalencia sea EXACTA en los bordes:
    //       sat(q_tot >> s) >= min  <=>  q_tot >= min << s
    //       sat(q_tot >> s) <= max  <=>  q_tot <= ((max+1) << s) - 1
    //     con q_tot = 10000, s = 5 -> amp = 312 (10000 >> 5), 312<<5 = 9984.
    //-----------------------------------------------------------------------
    cfg_amp_src = 1'b1; cfg_q_shift = 5;

    reset_dut; cfg_amp_min = 312;     // 9984 <= 10000: justo adentro
    pulse_rect(500, 20, 0); settle;
    checkv("borde min=amp: aceptado",     c_acc,     1);
    checkv("borde min=amp: sin rechazo",  c_rej_amp, 0);

    reset_dut; cfg_amp_min = 313;     // 10016 > 10000: justo afuera
    pulse_rect(500, 20, 0); settle;
    checkv("borde min=amp+1: rechazado",  c_rej_amp, 1);
    cfg_amp_min = 0;

    reset_dut; cfg_amp_max = 312;     // (313<<5)-1 = 10015 >= 10000: adentro
    pulse_rect(500, 20, 0); settle;
    checkv("borde max=amp: aceptado",     c_acc,     1);
    checkv("borde max=amp: sin rechazo",  c_rej_amp, 0);

    reset_dut; cfg_amp_max = 311;     // (312<<5)-1 = 9983 < 10000: afuera
    pulse_rect(500, 20, 0); settle;
    checkv("borde max=amp-1: rechazado",  c_rej_amp, 1);
    cfg_amp_max = 16'hFFFF;

    // SATURACION: q_tot = 8000*10 = 80000 >= 2^16 con s = 0 -> amp = 0xFFFF.
    // Es la unica rama donde las desigualdades pre-desplazadas NO equivalen a
    // las originales, y la restituye sat_ok: se acepta si y solo si max = 0xFFFF.
    cfg_q_shift = 0;
    reset_dut; cfg_amp_max = 16'hFFFF;
    pulse_rect(8000, 10, 0); settle;
    checkv("saturado, max=FFFF: aceptado", c_acc,     1);
    checkv("saturado, max=FFFF: amp",      ev_amp_q,  16'hFFFF);

    reset_dut; cfg_amp_max = 16'hFFFE;
    pulse_rect(8000, 10, 0); settle;
    checkv("saturado, max=FFFE: rechazado", c_rej_amp, 1);
    checkv("saturado, max=FFFE: no acept.", c_acc,     0);
    cfg_amp_max = 16'hFFFF;

    // Y el pico, que va por su propio flop (peak_ok_r):
    cfg_amp_src = 1'b0;
    reset_dut; cfg_amp_min = 500;     // pico = 500: justo adentro
    pulse_rect(500, 20, 0); settle;
    checkv("pico borde min=pico: aceptado", c_acc, 1);
    reset_dut; cfg_amp_min = 501;
    pulse_rect(500, 20, 0); settle;
    checkv("pico borde min=pico+1: rechaz.", c_rej_amp, 1);
    cfg_amp_min = 0;

    //-----------------------------------------------------------------------
    // 4c) VETO externo (nivel)
    //-----------------------------------------------------------------------
    // a) con veto no se abre nada, y no se cuenta como nada
    reset_dut; veto = 1'b1;
    pulse_rect(500, 20, 0); settle;
    checkv("veto: sin eventos",          c_total, 0);
    checkv("veto: no cuenta como perdido", c_lost, 0);
    veto = 1'b0;

    // b) el pulso EN CURSO termina normal aunque el veto llegue en el medio
    reset_dut;
    push(500); push(500); push(500);
    veto = 1'b1;
    for (i=0;i<17;i=i+1) push(500);
    push(0); settle;
    veto = 1'b0;
    checkv("veto a mitad: el pulso termina y se acepta", c_acc, 1);
    checkv("veto a mitad: q_tot completo = 20*500",     last_qtot, 10000);

    // c) un pulso que SUBE bajo veto no se abre al liberarlo a mitad: hay que
    //    volver por debajo de thr_lo (se desarmo). Sin esto se mediria una
    //    amplitud truncada.
    reset_dut; veto = 1'b1;
    push(500); push(500); push(500);
    veto = 1'b0;
    for (i=0;i<17;i=i+1) push(500);   // la senal sigue alta, sin veto
    push(0); settle;
    checkv("liberar a mitad de pulso: no abre", c_total, 0);
    pulse_rect(500, 20, 0); settle;    // ya volvio a la base: el siguiente si
    checkv("liberar a mitad de pulso: el siguiente si", c_acc, 1);

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
    // El hueco se ata a DIV_W en vez de ser un 15 magico: al ampliar el divisor
    // de 6 a 16 bits la latencia paso de 6 a 16 ciclos y este test empezo a
    // fallar aunque su INTENCION ("hueco > latencia") no habia cambiado.
    reset_dut;
    pulse_rect(500, 20, 0);
    for (i=0;i<DIV_W+4;i=i+1) push(0);   // hueco holgado: los divisores terminan
    pulse_rect(300, 10, 0);
    settle;
    checkv("dos pulsos separados: cnt_total",     c_total,   2);
    checkv("dos pulsos separados: cnt_accepted",  c_acc,     2);
    checkv("dos pulsos separados: amp del 2do",   ev_amp_q,  300);
    checkv("dos pulsos separados: q_tot del 2do", last_qtot, 3000);
    checkv("dos pulsos separados: nada perdido",  c_lost,    0);

    //-----------------------------------------------------------------------
    // 11b) El BORDE del tiempo muerto: dos pulsos separados por MENOS que la
    //      latencia del divisor. El segundo tiene que perderse ENTERO y
    //      contarse, no entrar truncado al espectro. Es el comportamiento que
    //      cambia al ampliar DIV_W, asi que conviene tenerlo fijado por un
    //      test y no descubrirlo midiendo.
    //-----------------------------------------------------------------------
    reset_dut;
    pulse_rect(500, 20, 0);
    for (i=0;i<DIV_W-8;i=i+1) push(0);   // hueco CORTO: el divisor sigue ocupado
    pulse_rect(300, 10, 0);
    settle;
    checkv("hueco corto: solo cierra el 1ro",     c_total,   1);
    checkv("hueco corto: solo se acepta el 1ro",  c_acc,     1);
    checkv("hueco corto: el 2do se cuenta perdido", c_lost,  1);
    checkv("hueco corto: la amplitud es la del 1ro", ev_amp_q, 500);

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
    //
    //      Y NO es apilamiento aunque la senal siga alta al cerrar: es la cola
    //      del PROPIO pulso. Esta es la regla que se corrigio despues de medir
    //      en la placa — con la version anterior ("senal alta al cerrar =
    //      apilamiento") el 100 % de los eventos se descartaba con cualquier
    //      compuerta mas corta que la cola, que es justo el rango util.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    pulse_rect(500, 30, 0);
    settle;
    checkv("compuerta corta que el pulso: q_tot = 10*500", last_qtot, 5000);
    checkv("compuerta: contado en total",                  c_total,   1);
    checkv("la cola del PROPIO pulso no es apilamiento",   c_pileup,  0);
    checkv("compuerta corta: el evento se acepta",         c_acc,     1);

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

    //-----------------------------------------------------------------------
    // 13f) APILAMIENTO DE VERDAD en modo compuerta: un SEGUNDO pulso dentro de
    //      la compuerta. La senal tiene que bajar de thr_lo y volver a cruzar
    //      thr_hi con la ventana todavia abierta.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 40;
    for (i=0;i<10;i=i+1) push(500);   // 1er pulso
    for (i=0;i<5;i=i+1)  push(0);     // baja: arma la deteccion del 2do
    for (i=0;i<10;i=i+1) push(500);   // 2do pulso DENTRO de la compuerta
    for (i=0;i<30;i=i+1) push(0);     // relleno hasta cerrar
    settle;
    checkv("2do pulso en la compuerta: contado",        c_total,  1);
    checkv("2do pulso en la compuerta: APILAMIENTO",    c_pileup, 1);
    checkv("2do pulso en la compuerta: NO se acepta",   c_acc,    0);

    //-----------------------------------------------------------------------
    // 13g) ...pero un solo pulso que baja y NO vuelve a subir no es
    //      apilamiento, aunque haya cruzado thr_lo dentro de la compuerta.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 40;
    for (i=0;i<10;i=i+1) push(500);
    for (i=0;i<40;i=i+1) push(0);     // baja y se queda abajo
    settle;
    checkv("bajar sin volver a subir NO es apilamiento", c_pileup, 0);
    checkv("y el evento se acepta",                      c_acc,    1);
    checkv("con la carga del unico pulso",               last_qtot, 5000);

    cfg_gate_mode = 1'b0; cfg_gate_short = 32; cfg_gate_long = 384;

    //=======================================================================
    // 14) TIEMPO MUERTO: los casilleros y la atribucion de arribos
    //
    // Es la parte que el modulo no media antes. `busy_o` no es la condicion de
    // bloqueo: el modulo no puede abrir mientras `armed` siga en 0, y `armed`
    // es una condicion de NIVEL (la senal tiene que bajar de thr_lo). Con la
    // compuerta fija eso deja un lapso en que st == S_IDLE, busy_o == 0, y sin
    // embargo no se puede abrir. Ese lapso no entraba en ningun contador.
    //
    // thr = 100, hyst = 50  =>  thr_hi = 100, thr_lo = 50.
    //=======================================================================

    //-----------------------------------------------------------------------
    // 14a) El tiempo muerto OCULTO existe y se mide. Compuerta de 10 muestras
    //      sobre un pulso de 30: la ventana cierra en la 10, los divisores
    //      tardan 16 ciclos, y despues el modulo queda en S_IDLE SIN poder
    //      abrir porque la senal sigue en 500 (muy arriba de thr_lo).
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    // ARTEFACTO DE ARRANQUE, a proposito no corregido en el RTL: tras el reset
    // `armed` vale 0 hasta la primera muestra por debajo de thr_lo, asi que
    // dt_rearm arranca en 1 y suma unos ciclos. Es correcto —el modulo
    // realmente no puede abrir— y encima es un diagnostico util: si cfg_thr
    // queda por debajo de la linea de base, `armed` no se pone nunca y
    // t_rearm lee el 100 %. Se descuenta en el testigo para que el test mida
    // el pulso y no el arranque.
    ciclos_ocultos = 0;
    // 60 muestras altas: la ventana cierra a las 10, los divisores se llevan 16
    // ciclos, y TODO el resto es bloqueo que busy_o no ve. Medido: 31 de 60.
    for (i=0;i<60;i=i+1) push(500);
    @(negedge clk);
    check ("oculto: en S_IDLE sin poder abrir", dt_rearm===1'b1 && busy===1'b0);
    check ("oculto: puede_abrir en 0",          puede_abrir===1'b0);
    // Cuantitativo, y es el resultado de fondo: de las 60 muestras el modulo
    // estuvo bloqueado todo el tiempo, pero busy_o solo cubrio la ventana (10)
    // mas los divisores (16). El resto —31 ciclos, MAS DE LA MITAD— es tiempo
    // muerto que el contador viejo daba como VIVO.
    checkv("oculto: 31 ciclos que busy_o no ve", ciclos_ocultos, 31);
    $display("  [info] bloqueo invisible a busy_o: %0d de 60 ciclos",
             ciclos_ocultos);

    //-----------------------------------------------------------------------
    // 14b) ...y se sale de el recien por debajo de thr_lo, no de thr_hi.
    //      Una senal en 60 esta debajo de thr_hi pero ARRIBA de thr_lo: el
    //      Schmitt sigue sin re-armarse. Es exactamente el mecanismo que hace
    //      paralizable al modulo.
    //-----------------------------------------------------------------------
    push(60); push(60); @(negedge clk);
    check ("rearm: 60 esta bajo thr_hi pero no re-arma", dt_rearm===1'b1);
    push(10); @(negedge clk);
    check ("rearm: 10 esta bajo thr_lo y SI re-arma",    dt_rearm===1'b0);
    check ("rearm: y vuelve a poder abrir",              puede_abrir===1'b1);

    //-----------------------------------------------------------------------
    // 14c) UN PULSO QUE LLEGA EN LA ZONA BLOQUEADA. Antes desaparecia sin
    //      quedar en ningun contador (la "marca gris" de la figura 5 de
    //      docs/mca/figuras/tiempo_muerto/). Ahora va a cnt_lost_rearm.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    for (i=0;i<30;i=i+1) push(500);        // cierra en 10, queda bloqueado
    push(60); push(60);                    // baja, pero no de thr_lo
    push(500); push(500);                  // 2do pulso: cruza thr_hi bloqueado
    settle;
    checkv("zona bloqueada: 2 arribos en total",    c_cross,       2);
    checkv("zona bloqueada: 1 abrio ventana",       c_open,        1);
    checkv("zona bloqueada: 1 perdido por rearm",   c_lost_rearm,  1);
    checkv("zona bloqueada: ninguno en la ventana", c_lost_active, 0);
    checkv("zona bloqueada: ninguno bajo veto",     c_lost_veto,   0);
    // La invariante que hace exhaustiva la atribucion.
    checkv("zona bloqueada: la atribucion cierra",
           c_cross, c_open + c_lost_rearm + c_lost_active + c_lost + c_lost_veto);

    //-----------------------------------------------------------------------
    // 14d) Un arribo DENTRO de la ventana va a su propio casillero. Con la
    //      compuerta larga el 2do pulso cae adentro: baja de thr_lo (lo que
    //      arma gate_rearm) y vuelve a cruzar thr_hi.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 60;
    for (i=0;i<5;i=i+1)  push(500);
    for (i=0;i<5;i=i+1)  push(10);         // baja de thr_lo, ventana abierta
    for (i=0;i<10;i=i+1) push(500);        // 2do pulso DENTRO de la ventana
    for (i=0;i<60;i=i+1) push(0);
    settle;
    checkv("en la ventana: 2 arribos",            c_cross,       2);
    checkv("en la ventana: 1 abrio",              c_open,        1);
    checkv("en la ventana: 1 perdido adentro",    c_lost_active, 1);
    checkv("en la ventana: ninguno por rearm",    c_lost_rearm,  0);
    checkv("en la ventana: la atribucion cierra",
           c_cross, c_open + c_lost_rearm + c_lost_active + c_lost + c_lost_veto);

    //-----------------------------------------------------------------------
    // 14e) Un arribo bajo VETO tiene casillero propio y NO contamina el
    //      tiempo muerto del modulo: vetarlo es lo que se pidio.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b0;
    veto = 1'b1;
    push(0); push(0);                      // arma (el re-armado corre con veto)
    for (i=0;i<10;i=i+1) push(500);        // cruza thr_hi vetado
    for (i=0;i<5;i=i+1)  push(0);
    settle;
    veto = 1'b0;
    checkv("veto: 1 arribo",                 c_cross,      1);
    checkv("veto: no abrio ventana",          c_open,       0);
    checkv("veto: contado como vetado",       c_lost_veto,  1);
    checkv("veto: no cuenta como rearm",      c_lost_rearm, 0);
    checkv("veto: la atribucion cierra",
           c_cross, c_open + c_lost_rearm + c_lost_active + c_lost + c_lost_veto);

    //-----------------------------------------------------------------------
    // 14f) En modo HISTERESIS el contador viejo era honesto, porque la ventana
    //      cierra justo cuando la senal baja de thr_lo: el bloqueo coincide
    //      con busy_o y no hay tiempo oculto. Es la fila "modo 0" de la tabla
    //      de docs/mca/figuras/tiempo_muerto/README.md, verificada en RTL.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b0; cfg_maxlen = 1000;
    ciclos_ocultos = 0;                    // descuenta el arranque (ver 14a)
    pulse_rect(500, 20, 0);                // cierra al bajar de thr_lo
    settle;
    checkv("histeresis: un evento",              c_total,         1);
    checkv("histeresis: sin tiempo muerto oculto", ciclos_ocultos, 0);
    checkv("histeresis: 1 arribo, 1 apertura",   c_open,          1);
    checkv("histeresis: nada perdido",
           c_lost_rearm + c_lost_active + c_lost + c_lost_veto, 0);

    cfg_gate_mode = 1'b0; cfg_gate_short = 32; cfg_gate_long = 384;

    //=======================================================================
    // 15) FASE 2 — RE-ARMADO POR CONTADOR
    //
    // Es la palanca grande del tiempo muerto. Con re-armado por NIVEL el modulo
    // es paralizable: si la senal no baja de thr_lo, no reabre nunca. Con
    // re-armado por CONTADOR reabre a cfg_rearm_dly muestras del cierre, pase lo
    // que pase con la senal, y tau queda determinista.
    //
    // Los dos sub-tests usan EL MISMO estimulo —120 muestras que nunca bajan— y
    // solo cambia cfg_rearm_mode. Esa es la comparacion que importa.
    //=======================================================================

    //-----------------------------------------------------------------------
    // 15a) Por NIVEL: una sola ventana en 120 muestras, y el resto es bloqueo.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    cfg_rearm_mode = 1'b0;
    ciclos_ocultos = 0;
    for (i=0;i<120;i=i+1) push(500);
    settle;
    checkv("nivel: UNA sola ventana en 120 muestras", c_total, 1);
    check ("nivel: y el resto es bloqueo oculto", ciclos_ocultos > 80);
    $display("  [info] nivel:    ventanas=%0d  ciclos ocultos=%0d",
             c_total, ciclos_ocultos);

    //-----------------------------------------------------------------------
    // 15b) Por CONTADOR, mismo estimulo: reabre solo. tau = ventana + holdoff.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    cfg_rearm_mode = 1'b1; cfg_rearm_dly = 8;
    ciclos_ocultos = 0;
    for (i=0;i<120;i=i+1) push(500);
    settle;
    check ("contador: reabre con la senal ARRIBA de thr_lo", c_total >= 3);
    check ("contador: el bloqueo oculto queda acotado", ciclos_ocultos < 40);
    $display("  [info] contador: ventanas=%0d  ciclos ocultos=%0d",
             c_total, ciclos_ocultos);

    //-----------------------------------------------------------------------
    // 15c) LA CONTRAPARTIDA, medida y no escondida. Un pulso ANCHO con holdoff
    //      corto se trocea en varios eventos: es la sobre-cuenta de la figura 6.
    //      El filtro no es volver al nivel, es cortar por FORMA — y se ve aca,
    //      porque los pedazos tienen todos el largo de la compuerta.
    //-----------------------------------------------------------------------
    checkv("contador: los pedazos tienen el largo de la compuerta", feat(4), 10);
    check ("contador: un pulso ancho dio VARIOS eventos", ev_count >= 3);

    //-----------------------------------------------------------------------
    // 15d) El holdoff se carga tambien cuando el evento se RECHAZA, si no tau
    //      dejaria de ser determinista justo con los pulsos de ruido.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    cfg_rearm_mode = 1'b1; cfg_rearm_dly = 30;
    cfg_amp_min = 16'd9000;                // rechaza todo: pico 500 << 9000
    for (i=0;i<22;i=i+1) push(500);
    @(negedge clk);
    check ("rechazo: el holdoff corre igual", dt_rearm===1'b1);
    checkv("rechazo: no reabrio",             c_total,  1);
    checkv("rechazo: y quedo rechazado",      c_rej_amp, 1);
    cfg_amp_min = 16'd0;

    cfg_rearm_mode = 1'b0; cfg_rearm_dly = 0;

    //=======================================================================
    // 16) FASE 2 — APERTURA POR TRIGGER EXTERNO
    //=======================================================================

    //-----------------------------------------------------------------------
    // 16a) Con la fuente en EXTERNO, un cruce de thr_hi solo NO abre. Y lo que
    //      importa: queda atribuido en cnt_lost_notrig en vez de desaparecer.
    //      Este casillero no estaba en el plan y hace falta — sin el, la
    //      invariante de la Fase 1 se rompe en silencio al cambiar de fuente.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_trig_src = 2'd1;                   // solo trigger externo
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    pulse_rect(500, 20, 0);
    settle;
    checkv("ext: hubo un cruce de thr_hi",      c_cross,       1);
    checkv("ext: pero NO abrio ventana",        c_win,         0);
    checkv("ext: atribuido a lost_notrig",      c_lost_notrig, 1);
    checkv("ext: no llego ningun trigger",      c_trig,        0);
    checkv("ext: la atribucion CIERRA igual",   c_cross, c_open + perdidos());

    //-----------------------------------------------------------------------
    // 16b) Con el trigger, abre — y el cruce va a cnt_open como siempre.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_trig_src = 2'd1;
    cfg_gate_mode = 1'b1; cfg_gate_short = 4; cfg_gate_long = 10;
    trig_push(500, 1);                     // un flanco junto a la 1er muestra
    for (i=0;i<20;i=i+1) push(500);
    push(0);
    settle;
    checkv("trigger: un flanco contado",        c_trig,  1);
    checkv("trigger: abrio una ventana",        c_win,   1);
    checkv("trigger: y la cerro",               c_total, 1);
    checkv("trigger: el cruce fue a cnt_open",  c_open,  1);
    checkv("trigger: la atribucion cierra",     c_cross, c_open + perdidos());

    //-----------------------------------------------------------------------
    // 16c) POR FLANCO Y NO POR NIVEL. Un trigger sostenido 5 muestras —el largo
    //      de un sys_wen, que es el caso real que en la placa producia DOS
    //      eventos por cada trigger de software— tiene que abrir UNA ventana.
    //      Con re-armado inmediato, para que no sea el holdoff el que lo tape.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_trig_src = 2'd1;
    cfg_gate_mode = 1'b1; cfg_gate_short = 1; cfg_gate_long = 2;
    cfg_rearm_mode = 1'b1; cfg_rearm_dly = 0;
    cfg_pub_mode = 1'b1;                   // publicacion desacoplada: sin excusas
    trig_push(500, 5);                     // ALTO durante 5 muestras
    for (i=0;i<40;i=i+1) push(500);
    push(0);
    settle;
    checkv("flanco: 5 ciclos en alto = UN flanco", c_trig, 1);
    checkv("flanco: y UNA sola ventana",           c_win,  1);
    cfg_rearm_mode = 1'b0; cfg_rearm_dly = 0;
    cfg_pub_mode = 1'b0;
    cfg_trig_src = 2'd0;

    //=======================================================================
    // 17) FASE 2 — FIFO DE PUBLICACION
    //
    // Dos pulsos separados por MENOS que los 17 ciclos del divisor. Es
    // exactamente el caso que la FIFO existe para rescatar, y la comparacion se
    // hace con el mismo estimulo cambiando solo cfg_pub_mode.
    //=======================================================================

    //-----------------------------------------------------------------------
    // 17a) BLOQUEANTE: el segundo pulso se pierde con el divisor ocupado.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_pub_mode = 1'b0;
    cfg_gate_mode = 1'b1; cfg_gate_short = 2; cfg_gate_long = 4;
    pulse_rect(500, 4, 0);                 // ventana 1
    push(0); push(0); push(0); push(0);    // baja de thr_lo: re-arma
    pulse_rect(300, 4, 0);                 // ventana 2, dentro de los 17 ciclos
    settle;
    checkv("bloqueante: una sola ventana",      c_win,   1);
    checkv("bloqueante: un solo evento",        c_acc,   1);
    checkv("bloqueante: el 2do perdido en busy", c_lost,  1);
    checkv("bloqueante: sin contrapresion de FIFO", ciclos_fifo, 0);

    //-----------------------------------------------------------------------
    // 17b) FIFO: el mismo estimulo da DOS eventos. La ventana cerro y reabrio
    //      sin esperar la publicacion, que es todo lo que compra la FIFO.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_pub_mode = 1'b1;
    cfg_gate_mode = 1'b1; cfg_gate_short = 2; cfg_gate_long = 4;
    pulse_rect(500, 4, 0);
    push(0); push(0); push(0); push(0);
    pulse_rect(300, 4, 0);
    settle;
    checkv("fifo: DOS ventanas",                c_win,   2);
    checkv("fifo: DOS eventos publicados",      c_acc,   2);
    checkv("fifo: ninguno perdido",             perdidos(), 0);
    checkv("fifo: la ocupacion llego a 2",      pub_occ_max, 2);
    checkv("fifo: vacia al final",              pub_occ, 0);
    // El id de ventana viaja con el resultado: el ultimo publicado es el 2do.
    checkv("fifo: el id publicado es el de la 2da ventana", last_win_id, 2);
    $display("  [info] fifo: ventanas=%0d eventos=%0d occ_max=%0d id=%0d",
             c_win, c_acc, pub_occ_max, last_win_id);

    //-----------------------------------------------------------------------
    // 17c) Y LA CONTRAPRESION ES TIEMPO MUERTO. Con la FIFO llena el modulo no
    //      puede abrir aunque la FSM de ventana este en reposo: dt_div sube con
    //      busy_o bajo. Si esto no entrara al teselado, el tiempo muerto oculto
    //      de la Fase 1 solo se habria mudado del Schmitt al arbitro.
    //-----------------------------------------------------------------------
    check ("fifo: la contrapresion se cuenta como tiempo muerto", ciclos_fifo > 0);
    $display("  [info] fifo: %0d ciclos de contrapresion (dt_div con busy bajo)",
             ciclos_fifo);

    //-----------------------------------------------------------------------
    // 17d) Saturada: con ventanas cortas y re-armado inmediato el publicador es
    //      el cuello de botella. La FIFO se llena, y lo que se pierde por eso
    //      queda en cnt_lost_busy — el mismo casillero que el modo bloqueante,
    //      para que las dos arquitecturas se comparen con la misma vara.
    //-----------------------------------------------------------------------
    reset_dut;
    cfg_pub_mode = 1'b1;
    cfg_rearm_mode = 1'b1; cfg_rearm_dly = 0;
    cfg_gate_mode = 1'b1; cfg_gate_short = 1; cfg_gate_long = 2;
    for (i=0;i<100;i=i+1) push(500);
    push(0);
    settle;
    checkv("saturada: la FIFO toco el tope",    pub_occ_max, 2);
    check ("saturada: hubo eventos publicados", c_acc >= 4);
    check ("saturada: y contrapresion contada", ciclos_fifo > 0);
    checkv("saturada: la atribucion cierra",    c_cross, c_open + perdidos());
    $display("  [info] saturada: ventanas=%0d publicados=%0d perdidos=%0d",
             c_win, c_acc, perdidos());

    cfg_pub_mode = 1'b0; cfg_rearm_mode = 1'b0;
    cfg_gate_mode = 1'b0; cfg_gate_short = 32; cfg_gate_long = 384;

    $display("---------------------------------------------");
    $display("tb_mca_pulse_feature: %0d PASS, %0d FAIL", pass_cnt, fail_cnt);
    if (fail_cnt!=0) $display("RESULT: FAIL"); else $display("RESULT: PASS");
    $finish;
  end

  initial begin #2000000; $display("TIMEOUT"); $display("RESULT: FAIL"); $finish; end

endmodule
