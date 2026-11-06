// Assertions de mca_top, enganchadas por `bind` desde sim/sva/bind_mca.sv.
//
// Van aparte del RTL a proposito: el RTL sintetizable no se toca, no hace falta
// un `ifndef SYNTHESIS`, y estas propiedades nunca entran a files.f, asi que
// Vivado ni las ve. Se compilan solo en el flujo de simulacion.
//
// El modulo replica los puertos del DUT que quiere observar; el bind con `.*`
// los conecta por nombre. `.*` alcanza tambien las senales INTERNAS de mca_top,
// que es lo que permite verificar el teselado de los relojes sin exponerlo al
// bus.
//
// QUE SE PRUEBA ACA, Y POR QUE IMPORTA
//
// El seguimiento del tiempo muerto es "exhaustivo" en un sentido preciso y
// verificable: cada ciclo de adc_clk se atribuye a exactamente un casillero de
// tiempo, y cada disparo a exactamente un casillero de eventos. Las dos cosas
// son INVARIANTES, no mediciones que haya que creer, y estan abajo como
// ap_suma_relojes y ap_atribucion_arribos. Con ranuras se suma una tercera: la
// ocupacion (cuantas ranuras hay ocupadas en cada ciclo) tambien tesela el
// tiempo vivo mas el muerto, ap_suma_ocupacion.
//
// Es la diferencia entre agregar contadores y poder afirmar que no falta
// ninguno. El bug que motivo todo esto —deadtime_cnt contaba `feat_busy`, que
// no es la condicion de bloqueo— habria sido imposible con ap_suma_relojes
// puesta: el tiempo de re-armado no cerraba la cuenta.

module mca_top_sva #(
    parameter integer N_ACC = 4,
    parameter integer N_FORMAS = 4,
    parameter integer AMP_W = 16,
    parameter integer NFEAT = 16
)(
    input logic adc_clk_i,
    input logic adc_rstn_i,

    // --- control y veto ---
    input logic        cfg_run,
    input logic        veto_i,
    input logic        clr_pulse,
    input logic [2:0]  cfg_n_acc,

    // --- casilleros de tiempo muerto, del extractor ---
    input logic        dt_win,
    input logic        dt_div,
    input logic        puede_abrir,
    input logic        arribo,
    input logic        feat_busy,
    input logic [$clog2(N_ACC+1)-1:0] n_ocup,
    input logic [$clog2(N_ACC+1)-1:0] pub_occ,

    // --- relojes ---
    input logic [63:0] realtime_cnt,
    input logic [63:0] livetime_cnt,
    input logic [63:0] deadtime_cnt,
    input logic [63:0] vetotime_cnt,
    input logic [63:0] t_win_cnt,
    input logic [63:0] t_div_cnt,
    input logic [63:0] t_ocup_cnt [0:N_ACC],

    // --- distribucion del periodo muerto ---
    input logic        bloqueado,
    input logic [31:0] dead_len,
    input logic [31:0] max_dead_len,
    input logic [31:0] cnt_dead_periods,
    input logic [31:0] cnt_dead_ext,

    // --- atribucion de arribos ---
    input logic [31:0] c_cross,
    input logic [31:0] c_open,
    input logic [31:0] c_lost_active,
    input logic [31:0] c_lost,          // cnt_lost_busy: sin ranura, alguna esperando publicar
    input logic [31:0] c_lost_veto,
    input logic [31:0] c_total,
    input logic [31:0] c_win,
    input logic [31:0] c_trig,

    // --- el evento publicado y el banco de trapecios ---
    input logic                   ev_valid,
    input logic [NFEAT*AMP_W-1:0] ev_feat,
    input logic [2:0]             cfg_n_formas
);

  default clocking cb @(posedge adc_clk_i); endclocking
  default disable iff (!adc_rstn_i);

  //---------------------------------------------------------------------------
  // 0. Cambio de cfg_n_acc a mitad de una cuenta
  //---------------------------------------------------------------------------
  // Los relojes son ACUMULATIVOS. La identidad "una ranura: ocupacion = tiempo
  // muerto" solo vale si hubo UNA ranura habilitada desde el ultimo borrado; si
  // cfg_n_acc cambia a mitad de una cuenta, la cuenta mezcla dos arquitecturas y
  // la identidad no vale sin que haya ningun bug. Una assertion que grita en un
  // caso legitimo se termina desactivando, asi que se dice explicitamente.
  logic       modo_mixto;
  logic [2:0] nacc_q;
  wire        una = (cfg_n_acc <= 3'd1) || (N_ACC == 1);
  always @(posedge adc_clk_i)
    if (!adc_rstn_i) begin
      modo_mixto <= 1'b0;
      nacc_q     <= cfg_n_acc;
    end else begin
      if      (clr_pulse)             modo_mixto <= 1'b0;
      else if (cfg_n_acc != nacc_q)   modo_mixto <= 1'b1;
      nacc_q <= cfg_n_acc;
    end
  wire modo_sucio = modo_mixto || (cfg_n_acc != nacc_q);

  //---------------------------------------------------------------------------
  // 1. El teselado del TIEMPO
  //---------------------------------------------------------------------------
  // Los dos casilleros son disjuntos y su union es exactamente "no puede abrir".
  ap_dt_disjuntos: assert property (
    !(dt_win && dt_div)
  ) else $error("casilleros de tiempo muerto solapados");

  ap_puede_abrir_complemento: assert property (
    puede_abrir == !(dt_win || dt_div)
  ) else $error("puede_abrir no es el complemento de los casilleros");

  // LA INVARIANTE CENTRAL. Cada ciclo con cfg_run suma a exactamente uno de los
  // cuatro relojes, asi que la suma cierra en todo ciclo.
  ap_suma_relojes: assert property (
    realtime_cnt == vetotime_cnt + t_win_cnt + t_div_cnt + livetime_cnt
  ) else $error("los relojes no teselan realtime: rt=%0d vt=%0d win=%0d div=%0d lt=%0d",
                realtime_cnt, vetotime_cnt, t_win_cnt, t_div_cnt, livetime_cnt);

  // La OCUPACION tambien tesela: cada ciclo con run y sin veto suma a
  // exactamente un t_ocup[j], el de las ranuras ocupadas en ese ciclo.
  logic [63:0] suma_ocup, ocup_alguna;
  always_comb begin
    suma_ocup = 64'h0;
    for (int j = 0; j <= N_ACC; j++) suma_ocup += t_ocup_cnt[j];
    ocup_alguna = suma_ocup - t_ocup_cnt[0];
  end
  ap_suma_ocupacion: assert property (
    suma_ocup == realtime_cnt - vetotime_cnt
  ) else $error("la ocupacion no tesela el tiempo sin veto: suma=%0d rt-vt=%0d",
                suma_ocup, realtime_cnt - vetotime_cnt);

  // deadtime_cnt (0x078) es la ocupacion de ALGUNA ranura: lo que no es t_ocup[0].
  ap_deadtime_es_ocupacion: assert property (
    deadtime_cnt == ocup_alguna
  ) else $error("deadtime_cnt (%0d) != ciclos con alguna ranura ocupada (%0d)",
                deadtime_cnt, ocup_alguna);

  ap_busy_es_ocupacion: assert property (
    feat_busy == (n_ocup != '0)
  ) else $error("feat_busy no coincide con las ranuras ocupadas");

  // Con UNA ranura, ocupada == no puede abrir: la ocupacion es el tiempo muerto,
  // como en la arquitectura de una ventana.
  ap_una_ranura: assert property (
    (una && !modo_sucio) |-> deadtime_cnt == (t_win_cnt + t_div_cnt)
  ) else $error("una ranura: deadtime_cnt (%0d) != t_win + t_div (%0d)",
                deadtime_cnt, t_win_cnt + t_div_cnt);

  // Todas las ranuras ocupadas implica que no se puede abrir.
  ap_llenas_no_abre: assert property (
    (n_ocup == N_ACC) |-> !puede_abrir
  ) else $error("todas las ranuras ocupadas y puede_abrir en 1");

  ap_cola_acotada: assert property (
    pub_occ <= N_ACC
  ) else $error("la cola de publicacion tiene %0d > N_ACC", pub_occ);

  //---------------------------------------------------------------------------
  // 2. El teselado de los EVENTOS
  //---------------------------------------------------------------------------
  // Cada disparo va a exactamente un casillero.
  ap_atribucion_arribos: assert property (
    c_cross == c_open + c_lost_active + c_lost + c_lost_veto
  ) else $error("arribos sin atribuir: cross=%0d open=%0d active=%0d busy=%0d veto=%0d",
                c_cross, c_open, c_lost_active, c_lost, c_lost_veto);

  // Con el disparo como unica fuente, cada ventana viene de un disparo.
  ap_open_es_win: assert property (
    c_open == c_win
  ) else $error("cnt_open (%0d) != cnt_win (%0d)", c_open, c_win);

  // Toda ventana que abre termina cerrandose, y hay a lo sumo N_ACC en vuelo.
  ap_win_vs_total: assert property (
    (c_win >= c_total) && ((c_win - c_total) <= N_ACC)
  ) else $error("win=%0d y total=%0d difieren en mas que las ranuras", c_win, c_total);

  // Un arribo con alguna ranura libre y sin veto TIENE que abrir.
  ap_arribo_libre_abre: assert property (
    (arribo && puede_abrir && !veto_i && !clr_pulse) |=> $changed(c_open)
  ) else $error("arribo con una ranura libre que no abrio ventana");

  //---------------------------------------------------------------------------
  // 3. La distribucion del periodo muerto
  //---------------------------------------------------------------------------
  ap_periodos_acotados: assert property (
    64'(cnt_dead_periods) <= (t_win_cnt + t_div_cnt)
  ) else $error("mas periodos muertos (%0d) que ciclos muertos", cnt_dead_periods);

  ap_ext_acotado_por_periodos: assert property (
    cnt_dead_ext <= cnt_dead_periods
  ) else $error("periodos con arribo (%0d) > periodos (%0d)", cnt_dead_ext, cnt_dead_periods);

  // Un arribo durante el bloqueo es un pulso perdido por falta de ranura.
  ap_ext_acotado_por_perdidas: assert property (
    cnt_dead_ext <= (c_lost_active + c_lost)
  ) else $error("periodos con arribo (%0d) > perdidos sin ranura (%0d)",
                cnt_dead_ext, c_lost_active + c_lost);

  ap_max_len_acotado: assert property (
    64'(max_dead_len) <= (t_win_cnt + t_div_cnt)
  ) else $error("max_dead_len (%0d) > ciclos muertos totales", max_dead_len);

  ap_dead_len_congelado: assert property (
    (!bloqueado && !clr_pulse) |=> $stable(dead_len)
  ) else $error("dead_len cambio sin bloqueo");

  //---------------------------------------------------------------------------
  // 3b. El banco de trapecios: la forma publicada es una de las habilitadas o
  //     la marca de "ninguna alcanza", y un pulso marcado no lleva altura
  //---------------------------------------------------------------------------
  localparam integer F_TRAP = 9, F_FORMA = 10;
  logic [AMP_W-1:0] f_forma, f_trap;
  int               nf_hab;
  assign f_forma = ev_feat[F_FORMA*AMP_W +: AMP_W];
  assign f_trap  = ev_feat[F_TRAP *AMP_W +: AMP_W];
  // Las formas habilitadas cuando se ELIGIO, que fue unos ciclos antes del
  // evento: cfg_n_formas solo se cambia sin eventos en vuelo, asi que alcanza
  // con la de ahora.
  assign nf_hab = (cfg_n_formas == 0) ? 1 : (cfg_n_formas > N_FORMAS) ? N_FORMAS : cfg_n_formas;

  if (N_FORMAS != 0) begin : g_banco
    ap_forma_valida: assert property (
      ev_valid |-> (f_forma == {AMP_W{1'b1}}) || (int'(f_forma) < nf_hab)
    ) else $error("F_FORMA = %0d con %0d formas habilitadas", f_forma, nf_hab);

    ap_marcado_sin_altura: assert property (
      (ev_valid && f_forma == {AMP_W{1'b1}}) |-> (f_trap == '0)
    ) else $error("pulso marcado con F_TRAP = %0d", f_trap);

    cp_marcado:   cover property (ev_valid && f_forma == {AMP_W{1'b1}});
    cp_forma_ult: cover property (ev_valid && int'(f_forma) == N_FORMAS - 1);
  end else begin : g_sin_banco
    ap_sin_banco: assert property (
      ev_valid |-> (f_forma == '0) && (f_trap == '0)
    ) else $error("sin trapecio, F_FORMA = %0d y F_TRAP = %0d", f_forma, f_trap);
  end

  //---------------------------------------------------------------------------
  // 4. Cobertura
  //---------------------------------------------------------------------------
  cp_llenas:      cover property (n_ocup == N_ACC);
  cp_varias:      cover property (n_ocup >= 2);
  cp_dt_win:      cover property (dt_win);
  cp_dt_div:      cover property (dt_div);
  cp_lost_active: cover property ($changed(c_lost_active));
  cp_lost_busy:   cover property ($changed(c_lost));
  cp_lost_veto:   cover property ($changed(c_lost_veto));
  cp_ext:         cover property ($changed(cnt_dead_ext));
  cp_periodo:     cover property ($changed(cnt_dead_periods));
  cp_cola_llena:  cover property (pub_occ == N_ACC);
  cp_flanco:      cover property ($changed(c_trig));

endmodule
