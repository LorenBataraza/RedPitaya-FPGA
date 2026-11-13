`timescale 1ns/1ps
//============================================================================
// tb_mca_multi — las N ranuras de mca_pulse_feature contra un MODELO
//
// El modelo esta escrito aparte y a proposito de otra forma que el RTL:
// enteros y arrays en vez de flops, la ventana de amplitud evaluada DIRECTO
// sobre los acumuladores (el RTL la evalua especulativa, un ciclo antes, con
// sombras), y el publicador como una cola de indices con un temporizador. Lo
// unico que toma del DUT es la linea de base (baseline_o), que es un modulo
// aparte y no cambio.
//
// Se compara en CADA ciclo:
//   - cada evento publicado, en el ciclo exacto y con las 16 ranuras del bus;
//   - todos los contadores (cierres, rechazos, solapes, arribos y sus cuatro
//     casilleros, ventanas, flancos de trigger);
//   - los casilleros del tiempo muerto (dt_win, dt_div, puede_abrir, busy),
//     las ranuras ocupadas y la ocupacion de la cola;
//   - que la base solo siga muestras que no son de ninguna ventana.
//
// El BANCO DE TRAPECIOS tiene su propio modelo: la recursion de Jordanov-Knoll
// en enteros, una por forma, sobre un historial de muestras con v[<0] = 0 desde
// el ultimo clr, y una cola de LAT salidas que hace de latencia. Cada ranura
// suma la ventana de la meseta de cada forma, y al publicar gana la primera
// forma habilitada con antes <= dt_prev y despues <= dt_next: el evento lleva
// su F_TRAP (ranura 9) y su indice en F_FORMA (ranura 10), o F_TRAP = 0 y
// F_FORMA = 0xFFFF si ninguna alcanza.
//
// Cuatro DUT con el MISMO estimulo y parametros distintos: (N_ACC, EN_PSD,
// N_FORMAS) = (4,1,4), (1,1,1), (3,1,2), (2,0,0). cfg_n_acc y cfg_n_formas se
// sortean de 0 a 7, asi que tambien se ejercita la saturacion.
//
// El estimulo va por epocas: en cada una se sortea la configuracion, la tasa,
// el largo de la compuerta, el modo de `val`, el veto. Pulsos con cola
// exponencial que se apilan, con su trigger unas muestras despues del pie (como
// llega el del multitrigger), triggers espurios, triggers que faltan, y a mitad
// de epoca cambios de gate_long y de cfg_n_acc (los dos son seguros en
// caliente; la ventana de amplitud no, y se cambia solo entre epocas, con todo
// publicado).
//
//   vsim ... +NCYC=400000 +SEED=7 +DBG
//============================================================================

module pf_multi_pair #(
  parameter integer N_ACC  = 4,
  parameter integer EN_PSD = 1,
  parameter integer N_FORMAS = 1,
  parameter string  NOMBRE = "?"
)(
  input               clk, rstn,
  input signed [13:0] dat,
  input               val, run, veto, clr, trig,
  input        [15:0] gs, gl, amin, amax,
  input               asrc,
  input        [4:0]  qsh,
  input        [2:0]  nacc,
  input        [13:0] base_fija,
  input               bl_auto,
  input        [3:0]  bl_k,
  input        [15:0] bl_hold,
  // el banco: 4 formas (k, l = k + m, escala, ventana de la meseta, umbrales)
  // con Mq comun; el par usa las primeras N_FORMAS
  input               tclr,
  input        [4*10-1:0] tk, tl,
  input        [19:0]     tmq,
  input        [4*6-1:0]  tsh,
  input        [4*16-1:0] toff,
  input        [4*3-1:0]  tlw,
  input        [4*16-1:0] tant, tdes,
  input        [2:0]      tnf
);
  localparam integer DW = 14, QW = 32, AMP_W = 16, LEN_W = 16;
  localparam integer PSD_AW = 6, DIV_W = 16, NFEAT = 16, NW = 4;
  localparam integer OC_W = $clog2(N_ACC + 1);
  localparam integer SERV = EN_PSD ? 18 : 2;     // ciclos del arranque al fin
  localparam integer TLAT = 8;                   // latencia del trapecio, muestras
  localparam integer NF   = (N_FORMAS < 1) ? 1 : N_FORMAS;

  //--------------------------------------------------------------------------
  // DUT
  //--------------------------------------------------------------------------
  wire               ev_valid, ev_psd_ok, bl_stale, busy;
  wire [AMP_W-1:0]   ev_amp;
  wire [PSD_AW-1:0]  ev_psd;
  wire [NFEAT*AMP_W-1:0] ev_feat;
  wire signed [DW-1:0] baseline;
  wire [31:0] c_total, c_acc, c_rej_amp, c_rej_psd, c_pile, c_lbusy;
  wire [31:0] c_cross, c_open, c_lact, c_lveto, c_win, c_trig;
  wire [QW-1:0] l_qtot, l_qtail;
  wire dt_win, dt_div, puede, arribo;
  wire [OC_W-1:0] n_ocup, occ, occ_max;
  wire [15:0] l_wid;

  mca_pulse_feature #(
    .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .DIV_W(DIV_W),
    .NFEAT(NFEAT), .LEN_W(LEN_W), .EN_PSD(EN_PSD), .N_ACC(N_ACC),
    .N_FORMAS(N_FORMAS)
  ) dut (
    .clk_i(clk), .rstn_i(rstn), .dat_i(dat), .val_i(val),
    .cfg_run_i(run), .veto_i(veto), .cnt_clr_i(clr),
    .cfg_baseline_i($signed(base_fija)), .cfg_bl_auto_i(bl_auto),
    .cfg_bl_k_i(bl_k), .cfg_bl_holdoff_i(bl_hold),
    .cfg_gate_short_i(gs), .cfg_gate_long_i(gl),
    .cfg_amp_min_i(amin), .cfg_amp_max_i(amax), .cfg_amp_src_i(asrc),
    .cfg_q_shift_i(qsh), .cfg_n_acc_i(nacc), .trig_i(trig),
    .trap_clr_i(tclr), .cfg_trap_k_i(tk[NF*10-1:0]), .cfg_trap_l_i(tl[NF*10-1:0]),
    .cfg_trap_mq_i(tmq), .cfg_trap_sh_i(tsh[NF*6-1:0]), .cfg_trap_off_i(toff[NF*16-1:0]),
    .cfg_trap_lw_i(tlw[NF*3-1:0]), .cfg_trap_antes_i(tant[NF*16-1:0]),
    .cfg_trap_despues_i(tdes[NF*16-1:0]), .cfg_n_formas_i(tnf),
    .ev_valid_o(ev_valid), .ev_amp_o(ev_amp), .ev_psd_o(ev_psd),
    .ev_psd_ok_o(ev_psd_ok), .ev_feat_o(ev_feat),
    .baseline_o(baseline), .baseline_stale_o(bl_stale),
    .cnt_total_o(c_total), .cnt_accepted_o(c_acc), .cnt_rej_amp_o(c_rej_amp),
    .cnt_rej_psd_o(c_rej_psd), .cnt_pileup_o(c_pile), .cnt_lost_busy_o(c_lbusy),
    .last_qtot_o(l_qtot), .last_qtail_o(l_qtail), .busy_o(busy),
    .dt_win_o(dt_win), .dt_div_o(dt_div), .puede_abrir_o(puede),
    .n_ocup_o(n_ocup), .arribo_o(arribo),
    .cnt_cross_o(c_cross), .cnt_open_o(c_open), .cnt_lost_active_o(c_lact),
    .cnt_lost_veto_o(c_lveto), .cnt_win_o(c_win),
    .pub_occ_o(occ), .pub_occ_max_o(occ_max), .last_win_id_o(l_wid),
    .cnt_trig_o(c_trig)
  );

  //--------------------------------------------------------------------------
  // MODELO
  //--------------------------------------------------------------------------
  localparam int LIBRE = 0, ABIERTA = 1, CERRADA = 2;
  localparam int SAT16 = 16'hFFFF;

  int     est [N_ACC];
  bit     res [N_ACC];
  longint qtot[N_ACC], qtail[N_ACC];
  int     pk[N_ACC], tpk[N_ACC], len[N_ACC], g_s[N_ACC], g_l[N_ACC];
  int     wid[N_ACC], dtp[N_ACC], dtn[N_ACC], otr[N_ACC];
  bit     adn[N_ACC], prd[N_ACC];
  longint tsum[N_ACC][4]; int tn[N_ACC][4];

  // lo decidido para la muestra n, que las ranuras procesan en n+1
  int p_xc, p_x, p_abre, p_otras, p_dtprev, p_wid;
  bit p_val, p_disp, p_perd;

  // El banco: las muestras desde el clr (circular, comunes), y por forma los
  // dos integradores y la cola de salidas. tr_n es el indice de la proxima
  // muestra.
  longint tr_v[4096];
  longint tr_n, tr_p[4], tr_s[4];
  int     tr_q[4][$];

  bit t_q, pend;
  int desde, win_id;

  int cola[$];
  bit pdiv; int cur, timer; bit psd_ok_cur;

  int m_total, m_rej, m_pile, m_cross, m_open, m_lact, m_lbusy, m_lveto, m_win;
  int m_trig, m_acc, m_rejpsd;
  longint m_lqtot, m_lqtail;
  int m_occmax;

  typedef struct {
    longint ciclo;
    int amp, psd; bit psd_ok;
    int feat[NFEAT];
    int wid;
  } ev_t;
  ev_t esperados[$];

  longint ciclo;
  int errores = 0;
  // cobertura
  bit cv_lact, cv_lbusy, cv_lveto, cv_lleno, cv_dos_cierres, cv_cola_llena;
  bit cv_rej, cv_psd_mal, cv_adentro, cv_perdido, cv_otras2, cv_directo, cv_encolado;
  bit cv_dtdiv, cv_dtwin;
  bit cv_trap_ok, cv_trap_sat, cv_trap_neg, cv_trap_inc;
  // el banco: cada forma elegida, el marcado, y la forma elegida JUSTO en su
  // umbral de antes y de despues (lo que distingue <= de <)
  bit cv_forma[4], cv_marcado, cv_borde_a, cv_borde_d;

  function automatic int clampx(input int d, input int b);
    int x; x = d - b;
    return (x < 0) ? 0 : x;
  endfunction

  function automatic int n_hab();
    int n; n = nacc;
    if (n == 0) n = 1;
    if (n > N_ACC) n = N_ACC;
    return n;
  endfunction

  function automatic int amp_int_de(input longint q);
    longint s; s = q >> qsh;
    return (s > SAT16) ? SAT16 : int'(s);
  endfunction

  // floor(num * 2^16 / den), como el divisor restaurador con num < den
  function automatic int cociente(input longint num, input longint den);
    return int'((num << 16) / den);
  endfunction

  //--- el trapecio ---------------------------------------------------------
  task automatic trap_reset();
    tr_n = 0;
    for (int f = 0; f < 4; f++) begin
      tr_p[f] = 0; tr_s[f] = 0;
      tr_q[f].delete();
      for (int i = 0; i < TLAT; i++) tr_q[f].push_back(0);
    end
  endtask

  function automatic int fk (input int f); return tk  [f*10 +: 10]; endfunction
  function automatic int fl (input int f); return tl  [f*10 +: 10]; endfunction
  function automatic int fsh(input int f); return tsh [f*6  +: 6];  endfunction
  function automatic int flw(input int f); return tlw [f*3  +: 3];  endfunction
  function automatic int fof(input int f); return toff[f*16 +: 16]; endfunction
  function automatic int fan(input int f); return tant[f*16 +: 16]; endfunction
  function automatic int fde(input int f); return tdes[f*16 +: 16]; endfunction
  function automatic int nf_hab();
    int n; n = tnf;
    if (n == 0) n = 1;
    if (n > NF) n = NF;
    return n;
  endfunction

  function automatic longint tr_hist(input longint j);
    return (j < 0) ? 0 : tr_v[j % 4096];
  endfunction

  // Una muestra entra; deja en tr_sal[f] la salida que ve la ranura con ESTA
  // muestra (la de TLAT muestras antes), por forma
  int tr_sal[4];
  task automatic trap_paso(input int v);
    longint d, r, q; int t;
    tr_v[tr_n % 4096] = v;
    for (int f = 0; f < NF; f++) begin
      d = tr_hist(tr_n) - tr_hist(tr_n - fk(f)) - tr_hist(tr_n - fl(f))
        + tr_hist(tr_n - fk(f) - fl(f));
      tr_p[f] = tr_p[f] + d;
      r = tr_p[f] * 16 + longint'(tmq) * d;
      tr_s[f] = tr_s[f] + r;
      q = tr_s[f] >>> fsh(f);
      t = (q > 131071) ? 131071 : (q < -131072) ? -131072 : int'(q);
      tr_q[f].push_back((N_FORMAS != 0) ? t : 0);
      tr_sal[f] = tr_q[f].pop_front();
    end
    tr_n++;
  endtask

  function automatic int feat_trap(input longint suma, input int n, input int lw);
    longint prom;
    if (n != (1 << lw)) begin cv_trap_inc = 1; return 0; end
    prom = suma >>> lw;
    if (prom < 0)     begin cv_trap_neg = 1; return 0; end
    if (prom > SAT16) begin cv_trap_sat = 1; return SAT16; end
    if (prom > 0) cv_trap_ok = 1;
    return int'(prom);
  endfunction

  task automatic emitir(input int k);
    ev_t e; longint qt, ql; int a_int;
    qt = qtot[k]; ql = qtail[k]; a_int = amp_int_de(qt);
    e.ciclo = ciclo;           // ev_valid sube en el flanco del fin
    for (int i = 0; i < NFEAT; i++) e.feat[i] = 0;
    e.amp = asrc ? a_int : pk[k];
    e.feat[0] = pk[k] << 2;
    e.feat[1] = a_int;
    e.feat[4] = len[k];
    e.feat[5] = tpk[k];
    e.feat[6] = dtp[k];
    e.feat[7] = dtn[k];
    e.feat[8] = (prd[k] << (NW+1)) | (adn[k] << NW) | otr[k];
    // la forma del banco: la primera habilitada cuya ventana no alcanza al
    // vecino, por los dos lados
    if (N_FORMAS != 0) begin
      int fe; fe = -1;
      for (int f = 0; f < nf_hab(); f++)
        if (fe < 0 && fan(f) <= dtp[k] && fde(f) <= dtn[k]) fe = f;
      if (fe >= 0 && fan(fe) == dtp[k]) cv_borde_a = 1;
      if (fe >= 0 && fde(fe) == dtn[k]) cv_borde_d = 1;
      if (fe < 0) begin
        cv_marcado = 1;
        e.feat[9] = 0; e.feat[10] = SAT16;
      end else begin
        cv_forma[fe] = 1;
        e.feat[9] = feat_trap(tsum[k][fe], tn[k][fe], flw(fe)); e.feat[10] = fe;
      end
    end
    if (EN_PSD) begin
      // ancho inverso: P/Q, saturado si P >= Q; con Q = 0 el divisor da error
      // y el cociente vale 0
      if (qt == 0)          e.feat[3] = 0;
      else if (pk[k] >= qt) e.feat[3] = SAT16;
      else                  e.feat[3] = cociente(pk[k], qt);
    end
    e.psd_ok = EN_PSD && psd_ok_cur;
    if (e.psd_ok) begin
      e.feat[2] = cociente(ql, qt);
      e.psd     = e.feat[2] >> (DIV_W - PSD_AW);
    end else begin
      e.psd = 0;
      if (EN_PSD) begin m_rejpsd++; cv_psd_mal = 1; end
    end
    e.wid = wid[k];
    m_acc++;
    esperados.push_back(e);
  endtask

  // Casilleros del ciclo en curso, desde el estado del modelo
  task automatic clasif(output bit o_puede, output bit o_esperan,
                        output int o_ocup, output int o_abiertas, output int o_sel);
    int nh; nh = n_hab();
    o_puede = 0; o_esperan = 0; o_ocup = 0; o_abiertas = 0; o_sel = -1;
    for (int k = 0; k < N_ACC; k++) begin
      bit ocup; ocup = (est[k] != LIBRE) || res[k];
      if (ocup) o_ocup++;
      if (est[k] == ABIERTA || res[k]) o_abiertas++;
      if (k < nh) begin
        if (!ocup && o_sel < 0) o_sel = k;
        if (!ocup) o_puede = 1;
        if (est[k] == CERRADA) o_esperan = 1;
      end
    end
  endtask

  task automatic reset_modelo();
    for (int k = 0; k < N_ACC; k++) begin
      est[k] = LIBRE; res[k] = 0; qtot[k] = 0; qtail[k] = 0; pk[k] = 0; tpk[k] = 0;
      len[k] = 0; g_s[k] = 0; g_l[k] = 0; wid[k] = 0; dtp[k] = 0; dtn[k] = SAT16;
      otr[k] = 0; adn[k] = 0; prd[k] = 0;
      for (int f = 0; f < 4; f++) begin tsum[k][f] = 0; tn[k][f] = 0; end
    end
    trap_reset();
    p_xc = 0; p_x = 0; p_val = 0; p_abre = -1; p_disp = 0; p_perd = 0; p_otras = 0;
    p_dtprev = 0; p_wid = 0;
    t_q = 0; pend = 0; desde = SAT16; win_id = 0;
    cola.delete(); pdiv = 0; cur = 0; timer = 0; psd_ok_cur = 0;
    m_total = 0; m_rej = 0; m_pile = 0; m_cross = 0; m_open = 0; m_lact = 0;
    m_lbusy = 0; m_lveto = 0; m_win = 0; m_trig = 0; m_acc = 0; m_rejpsd = 0;
    m_lqtot = 0; m_lqtail = 0; m_occmax = 0;
    esperados.delete();
  endtask

  initial begin reset_modelo(); ciclo = 0; end

  always @(posedge clk) begin
    ciclo++;
    if (!rstn) reset_modelo();
    else begin : paso
      bit hpuede, hesperan; int hocup, habiertas, hsel;
      bit edge_t, disparo, abre;
      int libera, n_cierres, ult, cerradas_ahora[$];
      int tr[4], t_ini[4], t_fin[4];

      cerradas_ahora.delete();    // las variables del bloque son estaticas

      // marca de agua: la ocupacion DURANTE este ciclo
      if (cola.size() > m_occmax) m_occmax = cola.size();

      //--- 1. el publicador termina? ---------------------------------------
      libera = -1;
      if (pdiv) begin
        if (timer == 0) begin
          emitir(cur);
          libera = cur;
          void'(cola.pop_front());
          pdiv = 0;
        end else timer--;
      end

      //--- 2. el asignador, con el estado del ciclo -----------------------
      clasif(hpuede, hesperan, hocup, habiertas, hsel);
      edge_t  = trig && !t_q;
      disparo = val && run && (edge_t || pend);
      abre    = disparo && !veto && hpuede;
      if (edge_t) m_trig++;
      if (disparo) begin
        m_cross++;
        if      (veto)                    m_lveto++;
        else if (!hpuede && !hesperan) begin m_lact++;  cv_lact  = 1; end
        else if (!hpuede)              begin m_lbusy++; cv_lbusy = 1; end
        else begin m_open++; m_win++; end
        if (veto) cv_lveto = 1;
      end

      //--- 3. las ranuras, con la muestra de n-1 --------------------------
      // El trapecio: con clr la muestra no entra y el estado vuelve a cero, pero
      // las ranuras ven en este ciclo la salida de antes del clr.
      for (int f = 0; f < 4; f++) tr[f] = tr_q[f][0];
      if (tclr) trap_reset();
      else if (p_val) begin
        trap_paso(p_x);
        for (int f = 0; f < NF; f++) tr[f] = tr_sal[f];
      end
      for (int f = 0; f < NF; f++) begin
        t_ini[f] = fof(f) + TLAT;           if (t_ini[f] > SAT16) t_ini[f] = SAT16;
        t_fin[f] = t_ini[f] + (1 << flw(f)); if (t_fin[f] > SAT16) t_fin[f] = SAT16;
        if (fof(f) + TLAT > SAT16) t_fin[f] = SAT16;
      end
      n_cierres = 0; ult = -1;
      for (int k = 0; k < N_ACC; k++) begin
        if (p_abre == k) begin
          est[k] = ABIERTA; res[k] = 0;
          len[k] = 1; tpk[k] = 0; pk[k] = p_xc; qtot[k] = p_xc; qtail[k] = 0;
          g_s[k] = gs; g_l[k] = gl; wid[k] = p_wid; dtp[k] = p_dtprev;
          dtn[k] = SAT16; otr[k] = p_otras; adn[k] = 0; prd[k] = 0;
          for (int f = 0; f < 4; f++) begin tsum[k][f] = 0; tn[k][f] = 0; end
          if (p_otras >= 2) cv_otras2 = 1;
        end else if (est[k] == ABIERTA && p_val) begin
          if (len[k] >= g_l[k]) begin
            int a; bit ok;
            a  = asrc ? amp_int_de(qtot[k]) : pk[k];
            ok = (a >= amin) && (a <= amax);
            m_total++; n_cierres++;
            if (ult < 0) ult = k;
            if (!ok) begin m_rej++; cv_rej = 1; end
            if (otr[k] != 0 || adn[k]) m_pile++;
            if (adn[k]) cv_adentro = 1;
            if (prd[k]) cv_perdido = 1;
            if (ok) begin est[k] = CERRADA; cerradas_ahora.push_back(k); end
            else       est[k] = LIBRE;
          end else begin
            qtot[k] += p_xc;
            if (len[k] >= g_s[k]) qtail[k] += p_xc;
            if (p_xc > pk[k]) begin pk[k] = p_xc; tpk[k] = len[k]; end
            if (p_disp) begin adn[k] = 1; if (dtn[k] == SAT16) dtn[k] = len[k]; end
            if (p_perd) prd[k] = 1;
            for (int f = 0; f < NF; f++)
              if (len[k] >= t_ini[f] && len[k] < t_fin[f]) begin tsum[k][f] += tr[f]; tn[k][f]++; end
            len[k]++;
          end
        end else if (est[k] == CERRADA && libera == k) begin
          est[k] = LIBRE;
        end
      end
      if (n_cierres >= 2) cv_dos_cierres = 1;
      if (ult >= 0) begin m_lqtot = qtot[ult]; m_lqtail = qtail[ult]; end

      //--- 4. el publicador arranca? ---------------------------------------
      if (!pdiv && libera < 0 && (cola.size() != 0 || cerradas_ahora.size() != 0)) begin
        cur = (cola.size() != 0) ? cola[0] : cerradas_ahora[0];
        if (cola.size() != 0) cv_encolado = 1; else cv_directo = 1;
        psd_ok_cur = (qtot[cur] != 0) && (qtail[cur] < qtot[cur]);
        pdiv = 1; timer = SERV - 1;
      end
      foreach (cerradas_ahora[i]) cola.push_back(cerradas_ahora[i]);
      if (cola.size() == N_ACC) cv_cola_llena = 1;

      //--- 5. lo que se registra para la muestra n ------------------------
      for (int k = 0; k < N_ACC; k++) res[k] = 0;
      p_abre = abre ? hsel : -1;
      if (abre) res[hsel] = 1;
      p_xc   = clampx(dat, baseline);
      p_x    = dat - baseline;
      p_val  = val;
      p_disp = disparo;
      p_perd = disparo && !veto && !hpuede;
      p_otras = (habiertas > 15) ? 15 : habiertas;
      if (val) begin
        int d1; d1 = (desde == SAT16) ? SAT16 : desde + 1;
        if (disparo) begin p_dtprev = d1; desde = 0; end
        else desde = d1;
      end
      if (abre) begin win_id = (win_id + 1) & 16'hFFFF; p_wid = win_id; end
      t_q = trig;
      if      (edge_t && !val) pend = 1;
      else if (val)            pend = 0;

      if (clr) begin
        m_total = 0; m_rej = 0; m_pile = 0; m_cross = 0; m_open = 0; m_lact = 0;
        m_lbusy = 0; m_lveto = 0; m_win = 0; m_trig = 0; m_acc = 0; m_rejpsd = 0;
        m_occmax = 0;
      end
    end
  end

  //--------------------------------------------------------------------------
  // Comparacion, a mitad de ciclo
  //--------------------------------------------------------------------------
  `define CHKV(nom, dutv, modv) \
    if ((dutv) !== (modv)) begin \
      errores++; \
      if (errores <= 20) $display("  [%s] ciclo %0d: %s DUT=%0d modelo=%0d", \
                                  NOMBRE, ciclo, nom, dutv, modv); \
    end

  always @(negedge clk) if (rstn) begin : cmp
    bit hpuede, hesperan; int hocup, habiertas, hsel; bit disparo_ahora, track;
    clasif(hpuede, hesperan, hocup, habiertas, hsel);
    `CHKV("puede_abrir", puede, hpuede)
    `CHKV("dt_win", dt_win, (!hpuede && !hesperan))
    `CHKV("dt_div", dt_div, (!hpuede && hesperan))
    `CHKV("n_ocup", n_ocup, hocup)
    `CHKV("busy", busy, (hocup != 0))
    `CHKV("pub_occ", occ, cola.size())
    `CHKV("pub_occ_max", occ_max, m_occmax)
    if (!hpuede && hesperan) cv_dtdiv = 1;
    if (!hpuede && !hesperan) cv_dtwin = 1;
    if (hocup == N_ACC) cv_lleno = 1;

    // La base solo sigue muestras que no son de ninguna ventana
    disparo_ahora = val && run && ((trig && !t_q) || pend);
    track = (habiertas == 0) && !(disparo_ahora && !veto && hpuede);
    `CHKV("bl_track", dut.i_win.bl_track_o, track)

    `CHKV("cnt_total", c_total, m_total)
    `CHKV("cnt_rej_amp", c_rej_amp, m_rej)
    `CHKV("cnt_pileup", c_pile, m_pile)
    `CHKV("cnt_cross", c_cross, m_cross)
    `CHKV("cnt_open", c_open, m_open)
    `CHKV("cnt_lost_active", c_lact, m_lact)
    `CHKV("cnt_lost_busy", c_lbusy, m_lbusy)
    `CHKV("cnt_lost_veto", c_lveto, m_lveto)
    `CHKV("cnt_win", c_win, m_win)
    `CHKV("cnt_trig", c_trig, m_trig)
    `CHKV("cnt_accepted", c_acc, m_acc)
    `CHKV("cnt_rej_psd", c_rej_psd, m_rejpsd)
    `CHKV("last_qtot", l_qtot, m_lqtot)
    `CHKV("last_qtail", l_qtail, m_lqtail)

    if (ev_valid) begin
      if (esperados.size() == 0) begin
        errores++;
        if (errores <= 20) $display("  [%s] ciclo %0d: evento que el modelo no espera", NOMBRE, ciclo);
      end else begin
        ev_t e; e = esperados.pop_front();
        `CHKV("ciclo del evento", ciclo, e.ciclo)
        `CHKV("ev_amp", ev_amp, e.amp)
        `CHKV("ev_psd_ok", ev_psd_ok, e.psd_ok)
        `CHKV("ev_psd", ev_psd, e.psd)
        `CHKV("last_win_id", l_wid, e.wid)
        for (int i = 0; i < NFEAT; i++)
          `CHKV($sformatf("ev_feat[%0d]", i), ev_feat[i*AMP_W +: AMP_W], e.feat[i])
      end
    end else if (esperados.size() != 0 && esperados[0].ciclo <= ciclo) begin
      errores++;
      if (errores <= 20) $display("  [%s] ciclo %0d: falta el evento esperado en %0d",
                                  NOMBRE, ciclo, esperados[0].ciclo);
      void'(esperados.pop_front());
    end
  end

  function automatic int cobertura();
    int c; c = 0;
    c += cv_lact; c += cv_lbusy; c += cv_lveto; c += cv_lleno; c += cv_rej;
    c += cv_adentro; c += cv_directo; c += cv_dtwin;
    if (EN_PSD) c += cv_psd_mal;
    if (N_ACC > 1) begin
      c += cv_dos_cierres; c += cv_cola_llena; c += cv_perdido;
      c += cv_encolado; c += cv_dtdiv;
    end
    if (N_ACC > 2) c += cv_otras2;
    if (N_FORMAS != 0) begin
      c += cv_trap_ok; c += cv_trap_sat; c += cv_trap_neg; c += cv_trap_inc;
      c += cv_marcado; c += cv_borde_a; c += cv_borde_d;
      for (int f = 0; f < NF; f++) c += cv_forma[f];
    end
    return c;
  endfunction

  function automatic int cobertura_req();
    return 8 + (EN_PSD ? 1 : 0) + ((N_ACC > 1) ? 5 : 0) + ((N_ACC > 2) ? 1 : 0)
             + ((N_FORMAS != 0) ? 7 + NF : 0);
  endfunction

  task automatic informe();
    $display("  [%s] errores=%0d  cobertura %0d/%0d  (lact=%0d lbusy=%0d lveto=%0d lleno=%0d rej=%0d psd_mal=%0d adentro=%0d directo=%0d dtwin=%0d dos_cierres=%0d cola_llena=%0d perdido=%0d otras2=%0d encolado=%0d dtdiv=%0d trap: ok=%0d sat=%0d neg=%0d incompleta=%0d banco: formas=%0d%0d%0d%0d marcado=%0d borde antes=%0d despues=%0d)",
             NOMBRE, errores, cobertura(), cobertura_req(),
             cv_lact, cv_lbusy, cv_lveto, cv_lleno, cv_rej, cv_psd_mal, cv_adentro,
             cv_directo, cv_dtwin, cv_dos_cierres, cv_cola_llena, cv_perdido,
             cv_otras2, cv_encolado, cv_dtdiv,
             cv_trap_ok, cv_trap_sat, cv_trap_neg, cv_trap_inc,
             cv_forma[0], cv_forma[1], cv_forma[2], cv_forma[3], cv_marcado, cv_borde_a, cv_borde_d);
  endtask
endmodule

//============================================================================
module tb_mca_multi;
  reg clk = 0;
  always #4 clk = ~clk;

  reg               rstn = 0;
  reg signed [13:0] dat  = 0;
  reg               val = 0, run = 0, veto = 0, clr = 0, trig = 0;
  reg        [15:0] gs = 4, gl = 20, amin = 0, amax = 16'hFFFF;
  reg               asrc = 0;
  reg        [4:0]  qsh = 0;
  reg        [2:0]  nacc = 4;
  reg        [13:0] base_fija = 0;
  reg               bl_auto = 0;
  reg        [3:0]  bl_k = 4;
  reg        [15:0] bl_hold = 0;
  reg               tclr = 0;
  reg        [4*10-1:0] tk = {4{10'd8}}, tl = {4{10'd12}};
  reg        [19:0]     tmq = 0;
  reg        [4*6-1:0]  tsh = {4{6'd4}};
  reg        [4*16-1:0] toff = {4{16'd10}};
  reg        [4*3-1:0]  tlw = {4{3'd2}};
  reg        [4*16-1:0] tant = 0, tdes = 0;
  reg        [2:0]      tnf = 4;

  `define PAR(inst, cad, n, p, t) \
    pf_multi_pair #(.N_ACC(n), .EN_PSD(p), .N_FORMAS(t), .NOMBRE(cad)) inst ( \
      .clk(clk), .rstn(rstn), .dat(dat), .val(val), .run(run), .veto(veto), \
      .clr(clr), .trig(trig), .gs(gs), .gl(gl), .amin(amin), .amax(amax), \
      .asrc(asrc), .qsh(qsh), .nacc(nacc), .base_fija(base_fija), \
      .bl_auto(bl_auto), .bl_k(bl_k), .bl_hold(bl_hold), \
      .tclr(tclr), .tk(tk), .tl(tl), .tmq(tmq), .tsh(tsh), .toff(toff), .tlw(tlw), \
      .tant(tant), .tdes(tdes), .tnf(tnf));

  `PAR(p4, "N=4, 4 formas", 4, 1, 4)
  `PAR(p1, "N=1, 1 forma", 1, 1, 1)
  `PAR(p3, "N=3, 2 formas", 3, 1, 2)
  `PAR(p33, "N=3, 3 formas (la de los tops)", 3, 1, 3)
  `PAR(p2, "N=2 sin PSD ni trapecio", 2, 0, 0)

  integer NCYC, SEED, DBG;

  // Pulsos activos: amplitud, constante de cola, edad
  real    pa[$], ptau[$];
  integer pedad[$];
  integer trig_en[$];             // cuenta atras para levantar trig
  integer trig_ancho;

  real    tasa, p_espurio, p_falta;
  integer lat, modo_val, dec_n, dec_c, epoca_fin, n_epoca;
  // escenario dirigido de la epoca: 0 aleatorio, 1 ventanas vacias,
  // 2 dos cierres en el mismo ciclo, 3 rafaga que llena la cola, 4 ventana de
  // amplitud en medio de la distribucion (decisiones al borde, con huecos de
  // val: es lo que ejercita la evaluacion especulativa de la ventana),
  // 5 integrales que saturan los 16 bits de la amplitud
  integer esc, fase;
  real    a_borde;
  integer n_esc [0:5];
  integer veto_rest, run_rest, trig_rest;

  function automatic real urand();
    return $urandom() / 4294967296.0;
  endfunction

  task automatic sortear_epoca(input integer largo);
    integer r;
    r = $urandom_range(0, 9);
    // la compuerta: corta y con tasa alta para llenar las ranuras, o larga
    gl = (r < 6) ? $urandom_range(1, 40) : $urandom_range(40, 160);
    gs = $urandom_range(0, gl);
    nacc = $urandom_range(0, 7);
    asrc = $urandom_range(0, 1);
    qsh  = $urandom_range(0, 6);
    // corrimientos grandes: min << s y (max+1) << s desbordan los 32 bits
    if ($urandom_range(0, 9) == 0) qsh = $urandom_range(14, 24);
    if ($urandom_range(0, 2) == 0) begin amin = 0; amax = 16'hFFFF; end
    else begin
      amin = $urandom_range(0, 600);
      amax = amin + $urandom_range(0, 4000);
      if ($urandom_range(0, 4) == 0) amax = 16'hFFFF;
    end
    bl_auto  = $urandom_range(0, 1);
    bl_k     = $urandom_range(2, 8);
    bl_hold  = $urandom_range(0, 20);
    base_fija = $urandom_range(0, 40);
    tasa     = (r < 6) ? 0.002 + urand() * 0.08 : 0.0005 + urand() * 0.01;
    p_espurio = (urand() < 0.3) ? urand() * 0.004 : 0.0;
    p_falta   = (urand() < 0.3) ? urand() * 0.3   : 0.0;
    lat      = $urandom_range(0, 3);
    trig_ancho = $urandom_range(1, 5);
    modo_val = $urandom_range(0, 2);     // 0 siempre, 1 huecos, 2 decimado
    dec_n    = $urandom_range(2, 4); dec_c = 0;
    epoca_fin = largo;
    n_epoca++;
    esc = 0; fase = 0;
    r = $urandom_range(0, 8);
    if (r == 0) begin
      // ventanas sin carga o con toda la carga en la cola: forma invalida
      esc = 1; bl_auto = 0; base_fija = 60; p_espurio = 0.02; tasa = 0.0005;
      amin = 0; amax = 16'hFFFF;
      if ($urandom_range(0, 1)) gs = 0;
    end else if (r == 1) begin
      // dos ventanas que cierran en la misma muestra (gate_long cambiado)
      esc = 2; nacc = 4; modo_val = 0; tasa = 0.0; p_espurio = 0.0; p_falta = 0.0;
      amin = 0; amax = 16'hFFFF; lat = 0; trig_ancho = 1;
    end else if (r == 2) begin
      // rafagas de disparos con compuerta corta: llenan la cola
      esc = 3; nacc = 4; tasa = 0.0; p_espurio = 0.0; p_falta = 0.0;
      amin = 0; amax = 16'hFFFF; lat = 0; trig_ancho = 1; gl = 6; gs = 2;
    end else if (r == 3 || r == 4) begin
      esc = 4; nacc = 4; modo_val = 2; tasa = 0.004;
      p_espurio = 0.0; p_falta = 0.0; gl = 12; gs = 4; asrc = $urandom_range(0, 1);
      qsh = $urandom_range(3, 5);
      if (asrc) begin amin = 150 + $urandom_range(0, 150); amax = amin + $urandom_range(20, 200); end
      else      begin amin = 300 + $urandom_range(0, 400); amax = amin + $urandom_range(10, 300); end
      // la amplitud de los pulsos, centrada en el umbral de abajo: con tau = 10
      // y 12 muestras la carga es ~7 veces la amplitud
      a_borde = asrc ? ((amin << qsh) / 7.0) : amin;
    end else if (r == 5) begin
      esc = 5; asrc = 1; qsh = $urandom_range(0, 1); amin = 0;
      amax = $urandom_range(0, 1) ? 16'hFFFF : 16'hFF00;
      gl = $urandom_range(120, 200); gs = 30; tasa = 0.003; p_espurio = 0.0;
      // min << s que no entra en 32 bits y cuyos bits bajos son CERO: si el
      // RTL no mirara min_fuera aceptaria todo, y lo correcto es no aceptar nada
      if ($urandom_range(0, 2) == 0) begin qsh = 24; amin = 256; end
    end
    // El banco. La forma se cambia con clr, como lo hace mca_top al escribir
    // k, m o M. Por forma, una vez de cada tres larga (lineas de retardo
    // hondas); si no, corta y con la ventana de la meseta dentro de la
    // compuerta, para que haya F_TRAP de verdad. M es comun.
    for (int f = 0; f < 4; f++) begin
      integer kk, ll;
      r = $urandom_range(0, 2);
      kk = (r == 0) ? $urandom_range(1, 700) : $urandom_range(1, 24);
      ll = kk + ((r == 0) ? $urandom_range(0, 1023 - kk) : $urandom_range(0, 24));
      tk[f*10 +: 10] = kk; tl[f*10 +: 10] = ll;
      tsh[f*6 +: 6] = $urandom_range(0, 1) ? $urandom_range(6, 16) : $urandom_range(0, 40);
      toff[f*16 +: 16] = (r == 0) ? $urandom_range(0, 2000) : $urandom_range(0, (gl > 10) ? gl - 10 : 0);
      tlw[f*3 +: 3] = $urandom_range(0, 7);
    end
    // M de la cola de los pulsos (tau = 3..43) o cualquiera
    tmq = $urandom_range(0, 1) ? $urandom_range(0, 16 * 45) : $urandom();
    // Una vez de cada tres, un banco como el de verdad: formas que se acortan a
    // la mitad, cada ventana dentro de la meseta y de la compuerta, el M de una
    // cola tipica y una escala que satura solo con los pulsos mas grandes (sh
    // de 8 a 11 en la forma 0). Asi F_TRAP casi nunca es cero y
    // un error en la ventana o en la escala de UNA forma se ve en muchos
    // eventos, no en dos o tres.
    if ($urandom_range(0, 2) == 0) begin
      tmq = 16 * $urandom_range(5, 40);
      if (gl < 48) gl = $urandom_range(48, 120);
      if (gs > gl) gs = gl;
      for (int f = 0; f < 4; f++) begin
        integer kk, mm;
        kk = 16 >> f; mm = (12 >> f) + 1;
        tk[f*10 +: 10] = kk; tl[f*10 +: 10] = kk + mm;
        tlw[f*3 +: 3] = (f < 3) ? 2 - (f > 0) : 0;
        toff[f*16 +: 16] = kk + $urandom_range(0, 2);
        tsh[f*6 +: 6] = 11 - f - $urandom_range(0, 3);
      end
    end
    // Los umbrales: en cero una vez de cada cinco (siempre gana la forma 0,
    // el MCA de un trapecio); si no, al azar, decrecientes como en el banco de
    // verdad, o chicos, del orden de la distancia entre disparos con la tasa
    // alta: es lo que pone a la forma elegida justo en su umbral.
    r = $urandom_range(0, 5);
    for (int f = 0; f < 4; f++) begin
      if (r == 0) begin tant[f*16 +: 16] = 0; tdes[f*16 +: 16] = 0; end
      else if (r == 1) begin
        tant[f*16 +: 16] = $urandom_range(0, 2000);
        tdes[f*16 +: 16] = $urandom_range(0, 2000);
      end else if (r == 2) begin
        tant[f*16 +: 16] = $urandom_range(0, 60) * (4 - f);
        tdes[f*16 +: 16] = $urandom_range(0, 60) * (4 - f);
      end else begin
        tant[f*16 +: 16] = $urandom_range(1, 10);
        tdes[f*16 +: 16] = $urandom_range(1, 10);
      end
    end
    tnf = $urandom_range(0, 7);
    // En las rafagas (un disparo cada 3 muestras), la mitad de las veces la
    // forma 0 con los umbrales en 3: la elegida queda justo en los dos umbrales
    // aunque haya una sola ranura, que pierde los disparos cercanos.
    if (esc == 3 && $urandom_range(0, 1)) begin
      modo_val = 0; tant[0 +: 16] = 3; tdes[0 +: 16] = 3;
    end
    tclr = 1;
    n_esc[esc] = n_esc[esc] + 1;
    if (DBG) $display("epoca %0d: gl=%0d gs=%0d nacc=%0d asrc=%0d qsh=%0d amin=%0d amax=%0d tasa=%f modo_val=%0d",
                      n_epoca, gl, gs, nacc, asrc, qsh, amin, amax, tasa, modo_val);
  endtask

  integer c, i, quieto, total_err, cob_ok;
  real    s;

  initial begin
    if (!$value$plusargs("NCYC=%d", NCYC)) NCYC = 300000;
    if (!$value$plusargs("SEED=%d", SEED)) SEED = 1;
    DBG = $test$plusargs("DBG");
    for (i = 0; i < 6; i = i + 1) n_esc[i] = 0;
    process::self().srandom(SEED);
    $display("tb_mca_multi: %0d ciclos, semilla %0d", NCYC, SEED);
    n_epoca = 0; veto_rest = 0; run_rest = 0; trig_rest = 0;

    repeat (5) @(posedge clk);
    #1 rstn = 1; run = 1;
    sortear_epoca($urandom_range(500, 4000));
    quieto = 0;

    for (c = 0; c < NCYC; c = c + 1) begin
      @(posedge clk); #1;
      clr = 0;
      tclr = 0;
      // el clr del trapecio tambien a mitad de epoca, con ventanas abiertas
      if ($urandom_range(0, 2999) == 0) tclr = 1;

      // fin de epoca: se deja de disparar y se espera a que todo publique,
      // asi la configuracion de amplitud cambia sin ventanas en vuelo
      if (epoca_fin > 0) epoca_fin = epoca_fin - 1;
      if (epoca_fin == 0) begin
        quieto = quieto + 1;
        if (quieto > 400 + 4 * 300) begin
          quieto = 0;
          if ($urandom_range(0, 9) == 0) clr = 1;
          if ($urandom_range(0, 30) == 0) begin rstn = 0; @(posedge clk); #1 rstn = 1; end
          sortear_epoca($urandom_range(500, 6000));
        end
      end

      // cambios en caliente que si son seguros
      if (epoca_fin > 0 && $urandom_range(0, 1999) == 0) gl = $urandom_range(1, 80);
      if (epoca_fin > 0 && $urandom_range(0, 1999) == 0) nacc = $urandom_range(0, 7);
      if ($urandom_range(0, 4999) == 0) clr = 1;

      // veto y run, en rachas
      if (veto_rest > 0) veto_rest = veto_rest - 1;
      else if ($urandom_range(0, 2999) == 0) veto_rest = $urandom_range(5, 200);
      veto = (veto_rest > 0);
      if (run_rest > 0) run_rest = run_rest - 1;
      else if ($urandom_range(0, 9999) == 0) run_rest = $urandom_range(5, 100);
      run = (run_rest == 0);

      // muestra valida
      case (modo_val)
        0: val = 1;
        1: val = ($urandom_range(0, 9) < 7);
        default: begin dec_c = (dec_c + 1) % dec_n; val = (dec_c == 0); end
      endcase

      // escenarios dirigidos
      if (epoca_fin > 0 && esc == 2) begin
        fase = (fase + 1) % 120;
        if (fase == 1)  begin gl = 40; gs = 10; end
        if (fase == 21) gl = 20;
        if (fase == 1 || fase == 21) begin
          pa.push_back(400.0); ptau.push_back(20.0); pedad.push_back(0);
          trig_en.push_back(0);
        end
      end
      if (epoca_fin > 0 && esc == 3) begin
        fase = (fase + 1) % 150;
        if (fase == 1 || fase == 4 || fase == 7 || fase == 10 || fase == 13) begin
          pa.push_back(300.0 + urand() * 500.0); ptau.push_back(10.0); pedad.push_back(0);
          trig_en.push_back(0);
        end
      end

      // pulsos nuevos (solo dentro de la epoca)
      if (epoca_fin > 0 && urand() < tasa) begin
        pa.push_back((esc == 4) ? a_borde * (0.6 + 0.8 * urand())
                   : (esc == 5) ? 2000.0 + urand() * 3000.0
                   : 50.0 + urand() * 3000.0);
        ptau.push_back((esc == 4) ? 10.0 : (esc == 5) ? 60.0 : 3.0 + urand() * 40.0);
        pedad.push_back(0);
        if (urand() >= p_falta) trig_en.push_back(lat);
      end
      if (epoca_fin > 0 && urand() < p_espurio) trig_en.push_back(0);

      // la senal: base + pulsos + ruido
      s = 0.0;
      for (i = pa.size() - 1; i >= 0; i = i - 1) begin
        if (pedad[i] == 0) s = s + pa[i] * 0.5;
        else               s = s + pa[i] * $exp(-(pedad[i] - 1) / ptau[i]);
        pedad[i] = pedad[i] + 1;
        if (pedad[i] > 12 * ptau[i] + 5) begin
          pa.delete(i); ptau.delete(i); pedad.delete(i);
        end
      end
      // ruido de +-3 cuentas. OJO: $urandom_range es SIN SIGNO, y restarle 3
      // sin convertir da 2^32 - 3 en vez de -3.
      s = s + 20.0 + (int'($urandom_range(0, 6)) - 3);
      if (s > 8000.0) s = 8000.0;
      dat = $rtoi(s);
      // Con val = 0 el dato no vale nada, y el DUT lo tiene que ignorar: se le
      // pone basura la mitad de las veces. Es lo que hace visible una regla
      // que se olvida de val (la ventana especulativa, sobre todo).
      if (!val && (esc == 4 || $urandom_range(0, 1))) dat = $urandom_range(0, 8000);

      // el trigger: un pulso de trig_ancho ciclos, `lat` despues del pie
      for (i = trig_en.size() - 1; i >= 0; i = i - 1) begin
        if (trig_en[i] == 0) begin trig_rest = trig_ancho; trig_en.delete(i); end
        else trig_en[i] = trig_en[i] - 1;
      end
      if (trig_rest > 0) begin trig = 1; trig_rest = trig_rest - 1; end
      else trig = 0;
    end

    repeat (2000) @(posedge clk);
    total_err = p4.errores + p1.errores + p3.errores + p33.errores + p2.errores;
    p4.informe(); p1.informe(); p3.informe(); p33.informe(); p2.informe();
    $display("  epocas: %0d aleatorias, %0d vacias, %0d con dos cierres, %0d en rafaga, %0d al borde, %0d saturadas",
             n_esc[0], n_esc[1], n_esc[2], n_esc[3], n_esc[4], n_esc[5]);
    cob_ok = (p4.cobertura() == p4.cobertura_req()) && (p1.cobertura() == p1.cobertura_req())
          && (p3.cobertura() == p3.cobertura_req()) && (p33.cobertura() == p33.cobertura_req())
          && (p2.cobertura() == p2.cobertura_req());
    if (total_err == 0 && cob_ok) $display("RESULT: PASS");
    else begin
      if (!cob_ok) $display("  cobertura incompleta");
      $display("RESULT: FAIL");
    end
    $finish;
  end
endmodule
