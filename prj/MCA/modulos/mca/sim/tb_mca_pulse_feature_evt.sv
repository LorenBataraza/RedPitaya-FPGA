`timescale 1ns/1ps
//============================================================================
// tb_mca_pulse_feature_evt — una ranura contra la ventana unica de antes
//
// Las ranuras cambiaron el comportamiento a proposito (no hay Schmitt, no hay
// re-armado, hay varias ventanas), asi que ya no hay equivalencia de ciclo con
// el modulo viejo. Pero hay una que SI tiene que valer, y es la que protege las
// mediciones: para pulsos AISLADOS, una ranura mide exactamente lo mismo que
// la ventana unica configurada como lo que la reemplaza.
//
//   referencia: sim/mca_pulse_feature_ref.v (la copia congelada), con
//               apertura por trigger externo, compuerta fija, re-armado por
//               contador sin holdoff y publicacion bloqueante, y un umbral
//               fuera de rango para que el Schmitt no intervenga
//   DUT:        mca_pulse_feature con una ranura
//
// Se comparan los EVENTOS, no los ciclos (la ranura publica uno mas tarde,
// por el registro de la muestra): la misma cantidad, y en cada uno la
// amplitud, el eje de forma y las seis features que existian (0..5). Base fija:
// con el seguidor IIR la base difiere en una muestra por ventana (la ranura deja
// de seguir un ciclo mas), y eso es una diferencia de diseno, no un error.
//
//   vsim ... +NEV=4000 +SEED=3
//============================================================================
module tb_mca_pulse_feature_evt;
  localparam integer DW = 14, QW = 32, AMP_W = 16, LEN_W = 16, NFEAT = 16;
  localparam integer PSD_AW = 6, DIV_W = 16;

  reg clk = 0;
  always #4 clk = ~clk;

  reg               rstn = 0;
  reg signed [13:0] dat = 0;
  reg               val = 0, trig = 0;
  reg        [15:0] gs = 4, gl = 20, amin = 0, amax = 16'hFFFF;
  reg               asrc = 0;
  reg        [4:0]  qsh = 0;
  reg        [13:0] base = 0;

  wire r_ev, d_ev, r_psd_ok, d_psd_ok;
  wire [AMP_W-1:0] r_amp, d_amp;
  wire [PSD_AW-1:0] r_psd, d_psd;
  wire [NFEAT*AMP_W-1:0] r_feat, d_feat;

  mca_pulse_feature_ref #(.PUB_K(2)) ref_ (
    .clk_i(clk), .rstn_i(rstn), .dat_i(dat), .val_i(val),
    .cfg_run_i(1'b1), .veto_i(1'b0), .cnt_clr_i(1'b0),
    .cfg_thr_i(14'sd8000), .cfg_hyst_i(14'd0),
    .cfg_baseline_i($signed(base)), .cfg_bl_auto_i(1'b0), .cfg_bl_k_i(4'd4),
    .cfg_bl_holdoff_i(16'd0), .cfg_maxlen_i(16'hFFFF), .cfg_tail_dly_i(16'd1),
    .cfg_gate_mode_i(1'b1), .cfg_gate_short_i(gs), .cfg_gate_long_i(gl),
    .cfg_amp_min_i(amin), .cfg_amp_max_i(amax), .cfg_amp_src_i(asrc),
    .cfg_q_shift_i(qsh), .trig_i(trig), .cfg_trig_src_i(2'd1),
    .cfg_rearm_mode_i(1'b1), .cfg_rearm_dly_i(16'd0), .cfg_pub_mode_i(1'b0),
    .ev_valid_o(r_ev), .ev_amp_o(r_amp), .ev_psd_o(r_psd), .ev_psd_ok_o(r_psd_ok),
    .ev_feat_o(r_feat),
    .baseline_o(), .baseline_stale_o(), .cnt_total_o(), .cnt_accepted_o(),
    .cnt_rej_amp_o(), .cnt_rej_psd_o(), .cnt_pileup_o(), .cnt_lost_busy_o(),
    .last_qtot_o(), .last_qtail_o(), .busy_o(),
    .dt_win_o(), .dt_div_o(), .dt_rearm_o(), .puede_abrir_o(), .arribo_o(),
    .cnt_cross_o(), .cnt_open_o(), .cnt_lost_rearm_o(), .cnt_lost_active_o(),
    .cnt_lost_veto_o(), .cnt_lost_notrig_o(), .cnt_win_o(),
    .pub_occ_o(), .pub_occ_max_o(), .last_win_id_o(), .cnt_trig_o()
  );

  mca_pulse_feature #(.N_ACC(1)) dut (
    .clk_i(clk), .rstn_i(rstn), .dat_i(dat), .val_i(val),
    .cfg_run_i(1'b1), .veto_i(1'b0), .cnt_clr_i(1'b0),
    .cfg_baseline_i($signed(base)), .cfg_bl_auto_i(1'b0), .cfg_bl_k_i(4'd4),
    .cfg_bl_holdoff_i(16'd0),
    .cfg_gate_short_i(gs), .cfg_gate_long_i(gl),
    .cfg_amp_min_i(amin), .cfg_amp_max_i(amax), .cfg_amp_src_i(asrc),
    .cfg_q_shift_i(qsh), .cfg_n_acc_i(3'd1), .trig_i(trig),
    // el trapecio no entra en esta comparacion (la referencia no lo tiene)
    .trap_clr_i(1'b0), .cfg_trap_k_i(10'd8), .cfg_trap_l_i(10'd12),
    .cfg_trap_mq_i(20'd0), .cfg_trap_sh_i(6'd0), .cfg_trap_off_i(16'd0),
    .cfg_trap_lw_i(3'd0),
    .ev_valid_o(d_ev), .ev_amp_o(d_amp), .ev_psd_o(d_psd), .ev_psd_ok_o(d_psd_ok),
    .ev_feat_o(d_feat),
    .baseline_o(), .baseline_stale_o(), .cnt_total_o(), .cnt_accepted_o(),
    .cnt_rej_amp_o(), .cnt_rej_psd_o(), .cnt_pileup_o(), .cnt_lost_busy_o(),
    .last_qtot_o(), .last_qtail_o(), .busy_o(),
    .dt_win_o(), .dt_div_o(), .puede_abrir_o(), .n_ocup_o(), .arribo_o(),
    .cnt_cross_o(), .cnt_open_o(), .cnt_lost_active_o(), .cnt_lost_veto_o(),
    .cnt_win_o(), .pub_occ_o(), .pub_occ_max_o(), .last_win_id_o(), .cnt_trig_o()
  );

  // Los eventos de cada lado, en orden
  typedef struct { int amp, psd; bit ok; int f[6]; } ev_t;
  ev_t cola_r[$], cola_d[$];
  int n_cmp = 0, errores = 0, n_ok = 0, n_rej = 0;

  always @(negedge clk) begin
    if (r_ev) begin
      ev_t e; e.amp = r_amp; e.psd = r_psd; e.ok = r_psd_ok;
      for (int i = 0; i < 6; i++) e.f[i] = r_feat[i*AMP_W +: AMP_W];
      cola_r.push_back(e);
    end
    if (d_ev) begin
      ev_t e; e.amp = d_amp; e.psd = d_psd; e.ok = d_psd_ok;
      for (int i = 0; i < 6; i++) e.f[i] = d_feat[i*AMP_W +: AMP_W];
      cola_d.push_back(e);
    end
    while (cola_r.size() != 0 && cola_d.size() != 0) begin
      ev_t a, b; bit igual;
      a = cola_r.pop_front(); b = cola_d.pop_front();
      igual = (a.amp == b.amp) && (a.psd == b.psd) && (a.ok == b.ok);
      for (int i = 0; i < 6; i++) igual = igual && (a.f[i] == b.f[i]);
      n_cmp++;
      if (a.ok) n_ok++;
      if (!igual) begin
        errores++;
        if (errores <= 10)
          $display("  evento %0d distinto: ref amp=%0d psd=%0d ok=%0d f=%p | dut amp=%0d psd=%0d ok=%0d f=%p",
                   n_cmp, a.amp, a.psd, a.ok, a.f, b.amp, b.psd, b.ok, b.f);
      end
    end
  end

  function automatic real urand(); return $urandom() / 4294967296.0; endfunction

  integer NEV, SEED, k, j, sep, modo_val;
  real a, tau, s;

  task automatic muestra(input real v);
    @(posedge clk); #1;
    case (modo_val)
      0: val = 1;
      1: val = ($urandom_range(0, 9) < 7);
      default: val = ($urandom_range(0, 2) == 0);
    endcase
    // el dato de una muestra no valida es basura: los dos lo tienen que ignorar
    dat = val ? $rtoi(v) : $urandom_range(0, 8000);
  endtask

  initial begin
    if (!$value$plusargs("NEV=%d", NEV))   NEV = 3000;
    if (!$value$plusargs("SEED=%d", SEED)) SEED = 1;
    process::self().srandom(SEED);
    $display("tb_mca_pulse_feature_evt: %0d pulsos, semilla %0d", NEV, SEED);
    repeat (5) @(posedge clk);
    #1 rstn = 1;

    for (k = 0; k < NEV; k = k + 1) begin
      // la configuracion cambia solo con todo publicado (al final del hueco)
      if (k % 50 == 0) begin
        gl   = $urandom_range(1, 200);
        gs   = $urandom_range(0, gl);
        asrc = $urandom_range(0, 1);
        qsh  = $urandom_range(0, 8);
        base = $urandom_range(0, 60);
        modo_val = $urandom_range(0, 2);
        if ($urandom_range(0, 2) == 0) begin amin = 0; amax = 16'hFFFF; end
        else begin amin = $urandom_range(0, 800); amax = amin + $urandom_range(0, 3000); end
        repeat (10) @(posedge clk);
      end
      a   = 30.0 + urand() * 7000.0;
      tau = 2.0 + urand() * 60.0;
      // el trigger sube con el pie del pulso y dura 1 a 5 muestras
      sep = $urandom_range(1, 5);
      for (j = 0; j < 4 * gl + 300; j = j + 1) begin
        if (j == 0)      s = a * 0.5;
        else             s = a * $exp(-(j - 1) / tau);
        s = s + 20.0 + (int'($urandom_range(0, 6)) - 3);
        if (s > 8000.0) s = 8000.0;
        muestra(s);
        trig = (j < sep);
      end
    end
    repeat (500) @(posedge clk);

    $display("  eventos: ref=%0d dut=%0d comparados=%0d (con forma valida %0d), distintos=%0d",
             n_cmp + cola_r.size(), n_cmp + cola_d.size(), n_cmp, n_ok, errores);
    if (errores == 0 && cola_r.size() == 0 && cola_d.size() == 0 && n_cmp > NEV / 3)
      $display("RESULT: PASS");
    else $display("RESULT: FAIL");
    $finish;
  end
endmodule
