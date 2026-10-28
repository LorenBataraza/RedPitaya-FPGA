`timescale 1ns/1ps
//============================================================================
// tb_mca_pulse_feature_eq — equivalencia contra la copia congelada.
//
// mca_pulse_feature se partio en submodulos (mca_baseline, mca_window,
// mca_publish) SIN cambiar el comportamiento: tiene que ser
// BIT-IDENTICO al de antes, incluidos los largos exactos de S_DIV que sostienen
// las identidades de tiempo muerto de la SVA. Este TB es lo que lo afirma.
//
// La referencia es sim/mca_pulse_feature_ref.v, la copia del modulo ANTES del
// split. Las dos corren en paralelo con el MISMO estimulo y se comparan TODAS
// las salidas en TODOS los ciclos. No hay valores esperados calculados a mano:
// el oraculo es el RTL viejo, que es justamente lo que hay que preservar.
//
// El estimulo esta hecho para recorrer las esquinas, no para parecerse a una
// medicion:
//   - pulsos de doble exponencial sumados linealmente, asi el apilamiento sale
//     solo; mas pulsos rectangulares (techo plano: la regla del pico estricto)
//     y alguno negativo (undershoot: el recorte de xc a >= 0)
//   - val_i con huecos (decimacion regular y aleatoria): trig_pend y el
//     watchdog de linea de base solo se ejercitan asi
//   - trig_i correlacionado con los pulsos y suelto, veto, cnt_clr, run=0
//   - la configuracion se re-sortea EN CALIENTE, sin parar: la equivalencia
//     tiene que valer en todo ciclo, no solo entre adquisiciones
//   - resets a mitad de corrida
//
// Cuatro pares con distintos parametros: PUB_K = 1, 2 (el instanciado), 3, y
// EN_PSD = 0. Al final se exige haber pasado por cada rama que importa: un
// verde sin cobertura no prueba nada.
//
// Plusargs: +NCYC=<ciclos> (default 1000000), +SEED=<semilla>.
//============================================================================

// Conexion de salidas de un mca_pulse_feature* a cables con prefijo.
`define PF_OUTS(p) \
  .ev_valid_o(p``_ev_valid), .ev_amp_o(p``_ev_amp), .ev_psd_o(p``_ev_psd), \
  .ev_psd_ok_o(p``_ev_psd_ok), .ev_feat_o(p``_ev_feat), \
  .baseline_o(p``_baseline), .baseline_stale_o(p``_bl_stale), \
  .cnt_total_o(p``_c_total), .cnt_accepted_o(p``_c_acc), \
  .cnt_rej_amp_o(p``_c_rej_amp), .cnt_rej_psd_o(p``_c_rej_psd), \
  .cnt_pileup_o(p``_c_pileup), .cnt_lost_busy_o(p``_c_lost), \
  .last_qtot_o(p``_last_qtot), .last_qtail_o(p``_last_qtail), \
  .busy_o(p``_busy), \
  .dt_win_o(p``_dt_win), .dt_div_o(p``_dt_div), .dt_rearm_o(p``_dt_rearm), \
  .puede_abrir_o(p``_puede_abrir), .arribo_o(p``_arribo), \
  .cnt_cross_o(p``_c_cross), .cnt_open_o(p``_c_open), \
  .cnt_lost_rearm_o(p``_c_lost_rearm), .cnt_lost_active_o(p``_c_lost_active), \
  .cnt_lost_veto_o(p``_c_lost_veto), .cnt_lost_notrig_o(p``_c_lost_notrig), \
  .cnt_win_o(p``_c_win), .pub_occ_o(p``_pub_occ), \
  .pub_occ_max_o(p``_pub_occ_max), .last_win_id_o(p``_last_win_id), \
  .cnt_trig_o(p``_c_trig)

`define PF_DECL(p) \
  wire              p``_ev_valid, p``_ev_psd_ok, p``_bl_stale, p``_busy; \
  wire              p``_dt_win, p``_dt_div, p``_dt_rearm, p``_puede_abrir, p``_arribo; \
  wire [15:0]       p``_ev_amp, p``_last_win_id; \
  wire [5:0]        p``_ev_psd; \
  wire [16*16-1:0]  p``_ev_feat; \
  wire signed [13:0] p``_baseline; \
  wire [31:0]       p``_c_total, p``_c_acc, p``_c_rej_amp, p``_c_rej_psd; \
  wire [31:0]       p``_c_pileup, p``_c_lost, p``_last_qtot, p``_last_qtail; \
  wire [31:0]       p``_c_cross, p``_c_open, p``_c_lost_rearm, p``_c_lost_active; \
  wire [31:0]       p``_c_lost_veto, p``_c_lost_notrig, p``_c_win, p``_c_trig; \
  wire [PUB_AW:0]   p``_pub_occ, p``_pub_occ_max;

// Una salida distinta cuenta como error y se informa (las primeras 20).
`define CHK(n) \
  if (r_``n !== d_``n) begin \
    n_err = n_err + 1; \
    if (n_err <= 20) \
      $display("[%0t] PUB_K=%0d EN_PSD=%0d  %s: ref=%h dut=%h", \
               $time, PUB_K, EN_PSD, `"n`", r_``n, d_``n); \
  end

//----------------------------------------------------------------------------
// Un par ref/dut con los mismos parametros y las mismas entradas.
//----------------------------------------------------------------------------
module pf_eq_pair #(
  parameter integer PUB_K  = 2,
  parameter integer EN_PSD = 1
)(
  input                    clk_i, rstn_i,
  input  signed [13:0]     dat_i,
  input                    val_i, cfg_run_i, veto_i, cnt_clr_i,
  input  signed [13:0]     cfg_thr_i,
  input         [13:0]     cfg_hyst_i,
  input  signed [13:0]     cfg_baseline_i,
  input                    cfg_bl_auto_i,
  input         [3:0]      cfg_bl_k_i,
  input         [15:0]     cfg_bl_holdoff_i, cfg_maxlen_i, cfg_tail_dly_i,
  input                    cfg_gate_mode_i,
  input         [15:0]     cfg_gate_short_i, cfg_gate_long_i,
  input         [15:0]     cfg_amp_min_i, cfg_amp_max_i,
  input                    cfg_amp_src_i,
  input         [4:0]      cfg_q_shift_i,
  input                    trig_i,
  input         [1:0]      cfg_trig_src_i,
  input                    cfg_rearm_mode_i,
  input         [15:0]     cfg_rearm_dly_i,
  input                    cfg_pub_mode_i,
  output integer           n_err,
  output reg    [16:0]     cov
);

  localparam integer PUB_AW = (PUB_K <= 2) ? 1 : $clog2(PUB_K);

  `PF_DECL(r)
  `PF_DECL(d)

  mca_pulse_feature_ref #(
    .DW(14), .QW(32), .AMP_W(16), .PSD_AW(6), .DIV_W(16), .NFEAT(16),
    .LEN_W(16), .EN_PSD(EN_PSD), .PUB_K(PUB_K), .PUB_IDW(16)
  ) i_ref (.clk_i, .rstn_i, .dat_i, .val_i, .cfg_run_i, .veto_i, .cnt_clr_i,
           .cfg_thr_i, .cfg_hyst_i, .cfg_baseline_i, .cfg_bl_auto_i,
           .cfg_bl_k_i, .cfg_bl_holdoff_i, .cfg_maxlen_i, .cfg_tail_dly_i,
           .cfg_gate_mode_i, .cfg_gate_short_i, .cfg_gate_long_i,
           .cfg_amp_min_i, .cfg_amp_max_i, .cfg_amp_src_i, .cfg_q_shift_i,
           .trig_i, .cfg_trig_src_i, .cfg_rearm_mode_i, .cfg_rearm_dly_i,
           .cfg_pub_mode_i, `PF_OUTS(r));

  mca_pulse_feature #(
    .DW(14), .QW(32), .AMP_W(16), .PSD_AW(6), .DIV_W(16), .NFEAT(16),
    .LEN_W(16), .EN_PSD(EN_PSD), .PUB_K(PUB_K), .PUB_IDW(16)
  ) i_dut (.clk_i, .rstn_i, .dat_i, .val_i, .cfg_run_i, .veto_i, .cnt_clr_i,
           .cfg_thr_i, .cfg_hyst_i, .cfg_baseline_i, .cfg_bl_auto_i,
           .cfg_bl_k_i, .cfg_bl_holdoff_i, .cfg_maxlen_i, .cfg_tail_dly_i,
           .cfg_gate_mode_i, .cfg_gate_short_i, .cfg_gate_long_i,
           .cfg_amp_min_i, .cfg_amp_max_i, .cfg_amp_src_i, .cfg_q_shift_i,
           .trig_i, .cfg_trig_src_i, .cfg_rearm_mode_i, .cfg_rearm_dly_i,
           .cfg_pub_mode_i, `PF_OUTS(d));

  // Se compara en el flanco de BAJADA: los registros ya se actualizaron y las
  // entradas (que el TB cambia despues de esto) siguen siendo las del ciclo, asi
  // que las salidas combinacionales (dt_*, arribo, busy) tambien valen.
  initial n_err = 0;
  always @(negedge clk_i) begin
    `CHK(ev_valid)      `CHK(ev_amp)        `CHK(ev_psd)       `CHK(ev_psd_ok)
    `CHK(ev_feat)       `CHK(baseline)      `CHK(bl_stale)     `CHK(c_total)
    `CHK(c_acc)         `CHK(c_rej_amp)     `CHK(c_rej_psd)    `CHK(c_pileup)
    `CHK(c_lost)        `CHK(last_qtot)     `CHK(last_qtail)   `CHK(busy)
    `CHK(dt_win)        `CHK(dt_div)        `CHK(dt_rearm)     `CHK(puede_abrir)
    `CHK(arribo)        `CHK(c_cross)       `CHK(c_open)       `CHK(c_lost_rearm)
    `CHK(c_lost_active) `CHK(c_lost_veto)   `CHK(c_lost_notrig) `CHK(c_win)
    `CHK(pub_occ)       `CHK(pub_occ_max)   `CHK(last_win_id)  `CHK(c_trig)
  end

  //--------------------------------------------------------------------------
  // Cobertura, sobre las salidas de la REFERENCIA. Un contador "incremento" es
  // valor == anterior + 1, asi el borrado no cuenta como evento.
  //--------------------------------------------------------------------------
  reg [31:0] p_pileup, p_rej_amp, p_rej_psd, p_lost, p_lrearm, p_lactive;
  reg [31:0] p_lveto, p_lnotrig, p_trig, p_win, p_open;
  reg        p_stale;
  initial cov = '0;
  always @(posedge clk_i) begin
    if (r_ev_valid)                                cov[0]  <= 1'b1;
    if (r_ev_valid && !r_ev_psd_ok)                cov[1]  <= 1'b1;
    if (r_c_pileup     == p_pileup  + 1)           cov[2]  <= 1'b1;
    if (r_c_rej_amp    == p_rej_amp + 1)           cov[3]  <= 1'b1;
    if (r_c_rej_psd    == p_rej_psd + 1)           cov[4]  <= 1'b1;
    if (r_c_lost       == p_lost    + 1)           cov[5]  <= 1'b1;
    if (r_c_lost_rearm == p_lrearm  + 1)           cov[6]  <= 1'b1;
    if (r_c_lost_active== p_lactive + 1)           cov[7]  <= 1'b1;
    if (r_c_lost_veto  == p_lveto   + 1)           cov[8]  <= 1'b1;
    if (r_c_lost_notrig== p_lnotrig + 1)           cov[9]  <= 1'b1;
    if (r_c_trig       == p_trig    + 1)           cov[10] <= 1'b1;
    if (r_dt_div)                                  cov[11] <= 1'b1;
    if (r_dt_rearm)                                cov[12] <= 1'b1;
    if (r_pub_occ == PUB_K)                        cov[13] <= 1'b1;
    if (r_bl_stale && !p_stale)                    cov[14] <= 1'b1;
    if (r_dt_div && !r_busy)                       cov[15] <= 1'b1;  // FIFO llena en reposo
    if (r_c_win == p_win + 1 && r_c_open == p_open) cov[16] <= 1'b1; // ventana sin cruce
    p_pileup <= r_c_pileup;  p_rej_amp <= r_c_rej_amp; p_rej_psd <= r_c_rej_psd;
    p_lost   <= r_c_lost;    p_lrearm  <= r_c_lost_rearm;
    p_lactive<= r_c_lost_active; p_lveto <= r_c_lost_veto;
    p_lnotrig<= r_c_lost_notrig; p_trig  <= r_c_trig;
    p_win    <= r_c_win;     p_open    <= r_c_open;
    p_stale  <= r_bl_stale;
  end

  // Diagnostico (+DBG): ciclos en S_DIV y arribos que caen ahi.
  integer n_sdiv = 0, n_arr_sdiv = 0, n_arr_div = 0;
  always @(posedge clk_i) begin
    if (r_dt_div && r_busy)                n_sdiv     <= n_sdiv + 1;
    if (r_arribo && r_dt_div && r_busy)    n_arr_sdiv <= n_arr_sdiv + 1;
    if (r_arribo && r_dt_div)              n_arr_div  <= n_arr_div + 1;
  end
  final if ($test$plusargs("DBG"))
    $display("  [dbg] K=%0d PSD=%0d: ciclos S_DIV=%0d, arribos en S_DIV=%0d, en dt_div=%0d",
             PUB_K, EN_PSD, n_sdiv, n_arr_sdiv, n_arr_div);

endmodule

//----------------------------------------------------------------------------
module tb_mca_pulse_feature_eq;

  reg clk = 0, rstn = 0;
  always #4 clk = ~clk;

  // --- entradas compartidas por todos los pares ---
  reg signed [13:0] dat = 0;
  reg               val = 0, cfg_run = 1, veto = 0, cnt_clr = 0, trig = 0;
  reg signed [13:0] cfg_thr = 100, cfg_baseline = 0;
  reg        [13:0] cfg_hyst = 50;
  reg               cfg_bl_auto = 0, cfg_gate_mode = 0, cfg_amp_src = 0;
  reg               cfg_rearm_mode = 0, cfg_pub_mode = 0;
  reg        [3:0]  cfg_bl_k = 4;
  reg        [15:0] cfg_bl_holdoff = 0, cfg_maxlen = 1000, cfg_tail_dly = 1;
  reg        [15:0] cfg_gate_short = 32, cfg_gate_long = 384;
  reg        [15:0] cfg_amp_min = 0, cfg_amp_max = 16'hFFFF, cfg_rearm_dly = 0;
  reg        [4:0]  cfg_q_shift = 0;
  reg        [1:0]  cfg_trig_src = 0;

  localparam integer NP = 4;
  integer    n_err [0:NP-1];
  wire [16:0] cov  [0:NP-1];

`define PAIR(i, K, P) \
  pf_eq_pair #(.PUB_K(K), .EN_PSD(P)) u_p``i ( \
    .clk_i(clk), .rstn_i(rstn), .dat_i(dat), .val_i(val), .cfg_run_i(cfg_run), \
    .veto_i(veto), .cnt_clr_i(cnt_clr), .cfg_thr_i(cfg_thr), .cfg_hyst_i(cfg_hyst), \
    .cfg_baseline_i(cfg_baseline), .cfg_bl_auto_i(cfg_bl_auto), .cfg_bl_k_i(cfg_bl_k), \
    .cfg_bl_holdoff_i(cfg_bl_holdoff), .cfg_maxlen_i(cfg_maxlen), \
    .cfg_tail_dly_i(cfg_tail_dly), .cfg_gate_mode_i(cfg_gate_mode), \
    .cfg_gate_short_i(cfg_gate_short), .cfg_gate_long_i(cfg_gate_long), \
    .cfg_amp_min_i(cfg_amp_min), .cfg_amp_max_i(cfg_amp_max), \
    .cfg_amp_src_i(cfg_amp_src), .cfg_q_shift_i(cfg_q_shift), .trig_i(trig), \
    .cfg_trig_src_i(cfg_trig_src), .cfg_rearm_mode_i(cfg_rearm_mode), \
    .cfg_rearm_dly_i(cfg_rearm_dly), .cfg_pub_mode_i(cfg_pub_mode), \
    .n_err(n_err[i]), .cov(cov[i]));

  `PAIR(0, 2, 1)   // el que instancia mca_top
  `PAIR(1, 1, 1)   // K=1: la arquitectura bloqueante pura
  `PAIR(2, 3, 1)   // K=3: PUB_AW=2, punteros que no son de 1 bit
  `PAIR(3, 2, 0)   // sin divisores: el evento sale directo del cierre

  // Ramas exigidas por par. Sin divisores no hay S_DIV ni FIFO, asi que
  // tampoco hay lost_busy, rej_psd ni dt_div.
  localparam [16:0] REQ_PSD   = 17'h1_FFFF;
  localparam [16:0] REQ_NOPSD = 17'b1_0101_0111_1100_1101;

  //--------------------------------------------------------------------------
  // Generador de senal: doble exponencial por superposicion lineal
  //--------------------------------------------------------------------------
  real    s_d = 0.0, s_r = 0.0, a_d = 0.99, a_r = 0.8, bl = 0.0, bl_drift = 0.0;
  real    noise_amp = 4.0, v;
  integer rect_len = 0, rect_amp = 0;
  integer p_ppm = 200;            // probabilidad de arribo por ciclo, en ppm
  integer val_mode = 0, val_n = 1, val_cnt = 0, val_ppc = 100;
  integer trig_mode = 0, trig_left = 0, trig_at = -1, veto_left = 0, run_left = 0;
  integer cyc = 0, ncyc = 1000000, seed = 1, epoch_left = 0;
  integer escenario = 0;
  integer n_esc [0:6] = '{default: 0};

  function automatic real gauss();
    // Suma de cuatro uniformes centradas, con cola acotada. La suma va a un
    // integer ANTES de restar: $urandom_range es sin signo y la resta envolveria.
    integer s;
    s = $urandom_range(0, 1000) + $urandom_range(0, 1000) +
        $urandom_range(0, 1000) + $urandom_range(0, 1000);
    gauss = (s - 2000) / 577.0;
  endfunction

  function automatic bit chance(input integer ppm);
    chance = ($urandom_range(0, 999999) < ppm);
  endfunction

  // Re-sorteo de toda la configuracion. Los rangos incluyen a proposito valores
  // que el software no usaria (hyst=0, tail_dly=0, min>max, q_shift=31,
  // trig_src=3): la equivalencia tiene que valer en todo el espacio.
  task automatic sortear_cfg();
    cfg_thr        = chance(50000) ? $urandom_range(0, 8) : $urandom_range(20, 600);
    cfg_hyst       = chance(80000) ? 0 : $urandom_range(5, 300);
    cfg_baseline   = $signed($urandom_range(0, 200)) - 100;
    cfg_bl_auto    = $urandom_range(0, 1);
    cfg_bl_k       = $urandom_range(0, 15);
    cfg_bl_holdoff = chance(300000) ? 0 : $urandom_range(1, 800);
    cfg_maxlen     = chance(200000) ? $urandom_range(2, 40) : $urandom_range(40, 3000);
    cfg_tail_dly   = chance(50000) ? 0 : $urandom_range(1, 40);
    cfg_gate_mode  = $urandom_range(0, 1);
    cfg_gate_short = $urandom_range(0, 120);
    cfg_gate_long  = chance(100000) ? $urandom_range(0, 8) : $urandom_range(8, 900);
    cfg_amp_src    = $urandom_range(0, 1);
    cfg_q_shift    = chance(100000) ? $urandom_range(0, 31) : $urandom_range(0, 10);
    if (chance(300000)) begin
      cfg_amp_min = 0; cfg_amp_max = 16'hFFFF;
    end else begin
      cfg_amp_min = chance(500000) ? $urandom_range(0, 300) : $urandom_range(0, 65535);
      cfg_amp_max = chance(300000) ? 16'hFFFF : $urandom_range(0, 65535);
    end
    cfg_trig_src   = $urandom_range(0, 3);
    cfg_rearm_mode = $urandom_range(0, 1);
    cfg_rearm_dly  = chance(300000) ? 0 : $urandom_range(1, 1500);
    cfg_pub_mode   = $urandom_range(0, 1);

    // Escenarios dirigidos. Al azar puro estas ramas casi no salen, y son
    // justamente las que el split toca: la FIFO llena y el arbitro.
    escenario = $urandom_range(0, 6);
    n_esc[escenario] = n_esc[escenario] + 1;
    case (escenario)
      // Ventanas mas cortas que el divisor, re-armado inmediato, modo FIFO:
      // dos cierres dentro de los 17 ciclos de S_DIV llenan la FIFO.
      0: begin
        cfg_pub_mode = 1; cfg_gate_mode = 1; cfg_rearm_mode = 1;
        cfg_gate_long = $urandom_range(1, 14); cfg_rearm_dly = $urandom_range(0, 3);
        cfg_thr = $urandom_range(0, 60); cfg_amp_min = 0; cfg_amp_max = 16'hFFFF;
        cfg_trig_src = 0; val_mode = 0; p_ppm = $urandom_range(500, 5000);
        cfg_bl_auto = 1; cfg_bl_k = $urandom_range(3, 8); cfg_bl_holdoff = 0;
        cfg_hyst = cfg_thr / 2;
      end
      // El mismo, en modo BLOQUEANTE, con pulsos CORTOS y seguidos: la senal
      // tiene que bajar del umbral y volver a cruzarlo dentro de los 17 ciclos
      // de S_DIV (cnt_lost_busy por la rama de st == S_DIV). Con colas largas
      // eso no pasa nunca.
      3: begin
        cfg_pub_mode = 0; cfg_gate_mode = 1; cfg_rearm_mode = 1;
        cfg_gate_long = $urandom_range(1, 6); cfg_rearm_dly = $urandom_range(0, 3);
        cfg_thr = $urandom_range(30, 200); cfg_amp_min = 0; cfg_amp_max = 16'hFFFF;
        cfg_trig_src = 0; val_mode = 0; p_ppm = $urandom_range(2000, 8000);
        a_d = 1.0 - 1.0 / $urandom_range(2, 8); a_r = 0.3; noise_amp = $urandom_range(0, 5);
        cfg_bl_auto = 1; cfg_bl_k = $urandom_range(3, 8); cfg_bl_holdoff = 0;
        cfg_hyst = cfg_thr / 2;
      end
      // Solo trigger externo: cruces que encuentran el modulo libre y no abren
      // (lost_notrig) y ventanas abiertas sin cruce, sobre la base.
      1: begin
        cfg_trig_src = 1; cfg_gate_mode = 1; cfg_gate_short = 0;
        cfg_gate_long = $urandom_range(1, 200);
      end
      // Trigger suelto sobre la base, con la cola desde la primera muestra: si
      // la ventana abre con x <= 0, q_tail == q_tot (o q_tot == 0) al cerrar.
      // Es el rechazo de forma (rej_psd), con el evento igual en el 1D. Hace
      // falta que la base se re-arme (thr_lo arriba del ruido) y que el
      // trigger venga sin pulso: por eso fuerza tambien la senal.
      2: begin
        cfg_trig_src = 1; cfg_hyst = 0; cfg_thr = $urandom_range(60, 300);
        cfg_gate_mode = 1; cfg_gate_short = 0;
        cfg_gate_long = $urandom_range(1, 40); cfg_bl_auto = 1;
        cfg_amp_min = 0; cfg_amp_max = 16'hFFFF;
        trig_mode = 1; p_ppm = $urandom_range(5, 100); noise_amp = $urandom_range(2, 20);
      end
      // Ventana de amplitud angosta sobre pulsos de toda altura: rechazos por
      // amplitud (cnt_rej_amp) con los dos estimadores, incluida la saturacion.
      4: begin
        cfg_thr = $urandom_range(30, 200); cfg_amp_min = $urandom_range(20, 600);
        cfg_amp_max = chance(300000) ? 16'hFFFF : cfg_amp_min + $urandom_range(0, 3000);
        p_ppm = $urandom_range(50, 800);
        cfg_bl_auto = 1; cfg_bl_k = $urandom_range(3, 8); cfg_bl_holdoff = 0;
        cfg_hyst = cfg_thr / 2;
      end
      default: ;   // configuracion libre
    endcase
  endtask

  task automatic sortear_senal();
    a_d       = 1.0 - 1.0 / $urandom_range(10, 900);
    a_r       = 1.0 - 1.0 / $urandom_range(1, 25);
    noise_amp = $urandom_range(0, 30);
    // En real ANTES de restar: $urandom_range es sin signo y la resta entera
    // envolveria a ~4e9 (la base saltaria a fondo de escala cada ciclo).
    bl_drift  = ($urandom_range(0, 200) * 1.0 - 100.0) / 20000.0;
    case ($urandom_range(0, 4))
      0: p_ppm = $urandom_range(5, 50);        // tasa baja: pulsos aislados
      1, 2: p_ppm = $urandom_range(50, 1500);  // la zona util
      default: p_ppm = $urandom_range(1500, 20000); // apilamiento fuerte
    endcase
    val_mode  = $urandom_range(0, 2);
    val_n     = $urandom_range(2, 8);
    val_ppc   = $urandom_range(40, 95);
    trig_mode = $urandom_range(0, 2);
  endtask

  // Un cambio de un solo campo a mitad de epoca.
  task automatic tocar_un_campo();
    case ($urandom_range(0, 7))
      0: cfg_trig_src   = $urandom_range(0, 3);
      1: cfg_rearm_mode = ~cfg_rearm_mode;
      2: cfg_pub_mode   = ~cfg_pub_mode;
      3: cfg_gate_mode  = ~cfg_gate_mode;
      4: cfg_amp_src    = ~cfg_amp_src;
      5: cfg_bl_auto    = ~cfg_bl_auto;
      6: cfg_q_shift    = $urandom_range(0, 31);
      default: cfg_thr  = $urandom_range(0, 600);
    endcase
  endtask

  //--------------------------------------------------------------------------
  // Estimulo: todo se cambia en el flanco de bajada, despues de que los pares
  // comparan (su always de negedge va antes por orden de elaboracion no
  // garantizado, asi que las entradas se cambian con #1).
  //--------------------------------------------------------------------------
  always @(negedge clk) begin
    #1;
    // La semilla se aplica a ESTE hilo: cada proceso tiene su propio generador,
    // y sembrar el del initial no cambia el estimulo.
    if (cyc == 0) process::self().srandom(seed);
    cyc = cyc + 1;

    // --- reset: al principio y, raramente, a mitad de corrida ---
    if (cyc < 8 || chance(3))  rstn = 0;
    else                       rstn = 1;

    // --- epocas ---
    if (epoch_left <= 0) begin
      if ($test$plusargs("DBG") && cyc > 1)
        $display("  [dbg] epoca esc=%0d pub=%0d gate=%0d gl=%0d thr=%0d: cross=%0d win=%0d total=%0d pileup=%0d acc=%0d rej_amp=%0d lost_busy=%0d veto=%0d rearm=%0d act=%0d",
                 escenario, cfg_pub_mode, cfg_gate_mode, cfg_gate_long, cfg_thr,
                 u_p0.r_c_cross, u_p0.r_c_win, u_p0.r_c_total, u_p0.r_c_pileup,
                 u_p0.r_c_acc, u_p0.r_c_rej_amp, u_p0.r_c_lost, u_p0.r_c_lost_veto,
                 u_p0.r_c_lost_rearm, u_p0.r_c_lost_active);
      // La senal primero: los escenarios de sortear_cfg pueden pisarla.
      sortear_senal();
      sortear_cfg();
      epoch_left = $urandom_range(3000, 60000);
    end else begin
      epoch_left = epoch_left - 1;
      // Los cambios en caliente solo en las epocas libres: en las dirigidas
      // desarman justo la condicion que el escenario busca.
      if (escenario >= 5 && chance(80)) tocar_un_campo();
    end

    // --- senal ---
    s_d = s_d * a_d;
    s_r = s_r * a_r;
    if (chance(p_ppm)) begin
      // amplitud: mayormente positiva, a veces chica (bajo umbral) o negativa
      v = chance(100000) ? -1.0 * $urandom_range(20, 800)
        : chance(150000) ?  $urandom_range(5, 150)
        :                   $urandom_range(150, 7000);
      s_d = s_d + v * 1.3;
      s_r = s_r + v * 1.3;
      if (trig_mode == 2) trig_at = cyc + $urandom_range(0, 12);
      if (chance(80000)) begin
        rect_len = $urandom_range(1, 60);
        rect_amp = $urandom_range(50, 3000);
      end
    end
    bl = bl + bl_drift;
    if (bl > 300.0 || bl < -300.0) bl_drift = -bl_drift;
    v = bl + s_d - s_r + noise_amp * gauss();
    if (rect_len > 0) begin v = v + rect_amp; rect_len = rect_len - 1; end
    if (v >  8191.0) v =  8191.0;
    if (v < -8192.0) v = -8192.0;
    dat = $rtoi(v);

    // --- val_i: continuo, decimacion regular o huecos aleatorios ---
    case (val_mode)
      0: val = 1'b1;
      1: begin val = (val_cnt == 0); val_cnt = (val_cnt + 1) % val_n; end
      default: val = ($urandom_range(0, 99) < val_ppc);
    endcase

    // --- trig_i: apagado, suelto, o correlacionado con el arribo ---
    if (trig_mode == 1 && chance(400)) trig_left = $urandom_range(1, 8);
    if (trig_mode == 2 && cyc == trig_at) trig_left = $urandom_range(1, 6);
    trig = (trig_left > 0);
    if (trig_left > 0) trig_left = trig_left - 1;

    // --- veto, run y borrado de contadores ---
    if (veto_left == 0 && chance(60)) veto_left = $urandom_range(5, 6000);
    veto = (veto_left > 0);
    if (veto_left > 0) veto_left = veto_left - 1;
    if (run_left == 0 && chance(20)) run_left = $urandom_range(5, 3000);
    cfg_run = (run_left == 0);
    if (run_left > 0) run_left = run_left - 1;
    cnt_clr = chance(15);
  end

  //--------------------------------------------------------------------------
  integer i, total;
  initial begin
    if (!$value$plusargs("NCYC=%d", ncyc)) ncyc = 1000000;
    if (!$value$plusargs("SEED=%d", seed)) seed = 1;
    $display("tb_mca_pulse_feature_eq: %0d ciclos, semilla %0d", ncyc, seed);

    wait (cyc >= ncyc);
    @(posedge clk); @(posedge clk);

    $display("  epocas por escenario (0..3 dirigidos, 4 amplitud, 5..6 libres): %0d %0d %0d %0d %0d %0d %0d",
             n_esc[0], n_esc[1], n_esc[2], n_esc[3], n_esc[4], n_esc[5], n_esc[6]);
    total = 0;
    for (i = 0; i < NP; i = i + 1) total = total + n_err[i];
    for (i = 0; i < NP; i = i + 1) begin
      automatic logic [16:0] req = (i == 3) ? REQ_NOPSD : REQ_PSD;
      $display("  par %0d: %0d diferencias, cobertura %b (exigida %b)",
               i, n_err[i], cov[i], req);
      if ((cov[i] & req) != req) begin
        $display("  [FAIL] par %0d: faltan ramas %b", i, req & ~cov[i]);
        total = total + 1;
      end
    end
    $display("---------------------------------------------");
    if (total == 0) $display("RESULT: PASS");
    else            $display("RESULT: FAIL (%0d)", total);
    $finish;
  end

endmodule
