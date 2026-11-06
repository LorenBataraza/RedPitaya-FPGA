`timescale 1ns/1ps
//=============================================================================
// mca_pulse_feature — segmentador de pulsos y extractor de características
//
// Recibe la muestra ya calibrada/filtrada (y retrasada por mca_delay) y, por
// cada pulso que dispara el multitrigger, emite UN registro de evento coherente
// que alimenta a todos los motores de histograma. Que salga de un único
// registro es lo que garantiza que el espectro 1D y el mapa 2D cuenten
// exactamente los mismos pulsos.
//
//=============================================================================
// PARTICION: este modulo es solo cableado
//=============================================================================
//   mca_baseline la linea de base: seguidor IIR o base fija (D3)
//   mca_window   el nucleo: la muestra relativa a la base, el disparo, el
//                asignador de ranuras, las N_ACC ranuras (mca_slot) con sus
//                acumuladores y la ventana de amplitud (D7), el conformado
//                trapezoidal (mca_trap) y la contabilidad del tiempo muerto
//   mca_publish  la cola de ranuras cerradas, los dos mca_div_restore y el
//                armado del bus de features
//
// DONDE VAN LAS FRONTERAS lo decide el timing: el bitstream se sintetiza con
// -flatten_hierarchy none, asi que cada puerto es una barrera de optimizacion.
// Todo lo que cruza sale de un registro: la base (de mca_baseline), la muestra
// saturada (xc_q, adentro de mca_window, antes de repartirse a las ranuras) y
// los resultados de las ranuras.
//
//=============================================================================
// VARIAS VENTANAS A LA VEZ
//=============================================================================
// La ventana la abre SOLO el trigger externo (el multitrigger, con su disparo
// por pendiente): el Schmitt interno se saco porque no ve un pulso montado
// sobre la cola de otro. Con eso dejaron de existir quien abre (D4), quien
// cierra (D5: siempre compuerta fija), el re-armado (D6: lo hace el
// multitrigger) y el modo de publicacion (D8: lo reemplaza cfg_n_acc).
//
// cfg_n_acc elige cuantas ranuras se usan, de 1 a N_ACC. Con 1, una ranura que
// cierra espera a los divisores antes de poder reabrir: es la publicacion
// bloqueante de antes. Con mas, un disparo que llega con una ventana abierta
// abre otra, y la perdida de eventos pasa de ser de primer orden en la tasa a
// ~rho^N/N! (modelo M/D/N/N). Lo que se mide sobre otro pulso viene
// contaminado: se MARCA en el bus de features (F_DTPREV, F_DTNEXT, F_SOLAPE) y
// lo deciden el discriminador o el software.
//
// La CORRECCION es el conformado trapezoidal (mca_trap, D13): cancela el polo
// de la cola, asi que cada pulso sale como un trapecio que vuelve a cero en
// 2k+m muestras, y cada ranura promedia su meseta en F_TRAP. Dos pulsos
// separados k+m o mas miden limpio aunque se pisen en la entrada; F_DTPREV y
// F_DTNEXT dicen cuales son.
//
// Con el BANCO (N_FORMAS trapecios, de la forma mas larga a la mas corta) cada
// ranura suma la meseta de todas, y al publicar se elige la mas larga que el
// vecino permite, por dt_prev y dt_next contra los umbrales de cada forma; la
// elegida sale en F_FORMA. Ver mca_publish y docs/mca/pruebas_banco_trapecios.md.
//=============================================================================

module mca_pulse_feature #(
  parameter integer DW      = 14,  // ancho de muestra (con signo)
  parameter integer QW      = 32,  // ancho de los acumuladores de carga
  parameter integer AMP_W   = 16,  // ancho de la amplitud emitida
  parameter integer PSD_AW  = 6,   // bits del EJE de factor de forma (mapa 2D)
  parameter integer DIV_W   = 16,  // bits de COCIENTE de los divisores
  parameter integer NFEAT   = 16,  // ranuras del bus de features
  parameter integer LEN_W   = 16,  // ancho de los contadores de longitud
  parameter integer BL_KW   = 4,   // bits del exponente k del seguidor IIR
  parameter integer EN_PSD  = 1,   // 0: no instancia los divisores
  parameter integer N_ACC   = 4,   // ranuras de medicion
  parameter integer PUB_IDW = 16,  // bits del id de ventana
  parameter integer NA_W    = 3,   // bits de cfg_n_acc
  parameter integer N_FORMAS = 4,  // trapecios del banco; 0: sin trapecio (F_TRAP vale cero)
  parameter integer TDAW    = 10,  // log2 de la profundidad de sus lineas de retardo
  parameter integer TMW     = 20,  // bits de su constante polo-cero
  // Derivados: van en la lista de parametros porque los puertos los usan y un
  // localparam del cuerpo se declara demasiado tarde. No se sobreescriben.
  parameter integer OC_W    = $clog2(N_ACC + 1),
  parameter integer NF      = (N_FORMAS < 1) ? 1 : N_FORMAS
)(
  input                       clk_i            ,
  input                       rstn_i           ,

  // --- muestras de entrada (calibradas, filtradas, decimadas y retrasadas) ---
  input      signed [DW-1:0]  dat_i            ,
  input                       val_i            ,

  // --- configuración ---
  input                       cfg_run_i        ,
  // VETO externo (nivel): no se abren ventanas nuevas mientras vale 1. Las que
  // estan abiertas terminan normal, y el seguidor de linea de base SIGUE
  // corriendo -- a diferencia de cfg_run=0 --, porque la base deriva igual
  // durante el veto. Viene del trigger_shield del multitrigger (dst = mca).
  input                       veto_i           ,
  input                       cnt_clr_i        ,  // pulso: pone a cero los contadores
  input      signed [DW-1:0]  cfg_baseline_i   ,  // base fija si cfg_bl_auto=0
  input                       cfg_bl_auto_i    ,
  input             [BL_KW-1:0] cfg_bl_k_i     ,  // alfa = 2^-k
  input             [LEN_W-1:0] cfg_bl_holdoff_i,
  input             [LEN_W-1:0] cfg_gate_short_i, // compuerta corta (cola), en muestras
  input             [LEN_W-1:0] cfg_gate_long_i , // compuerta larga (ventana), en muestras
  input             [AMP_W-1:0] cfg_amp_min_i  ,
  input             [AMP_W-1:0] cfg_amp_max_i  ,
  input                       cfg_amp_src_i    ,  // 0=pico, 1=integral
  input             [4:0]     cfg_q_shift_i    ,
  input             [NA_W-1:0] cfg_n_acc_i     ,  // ranuras habilitadas, 1..N_ACC

  // Trigger externo, el UNICO que abre ventanas. Se toma por FLANCO.
  input                       trig_i           ,

  // --- el banco de trapecios (mca_trap): NF formas, aplanadas, y la eleccion ---
  input                       trap_clr_i       ,  // pulso: reinicia su estado
  input             [NF*TDAW-1:0]  cfg_trap_k_i   ,  // subida, >= 1
  input             [NF*TDAW-1:0]  cfg_trap_l_i   ,  // subida + meseta
  input             [TMW-1:0]      cfg_trap_mq_i  ,  // polo-cero, M * 16 (comun)
  input             [NF*6-1:0]     cfg_trap_sh_i  ,  // escala de F_TRAP
  input             [NF*LEN_W-1:0] cfg_trap_off_i ,  // inicio de la meseta, desde la apertura
  input             [NF*3-1:0]     cfg_trap_lw_i  ,  // largo de la meseta: 2^lw
  input             [NF*LEN_W-1:0] cfg_trap_antes_i,  // umbral de dt_prev de cada forma
  input             [NF*LEN_W-1:0] cfg_trap_despues_i,// umbral de dt_next de cada forma
  input             [2:0]          cfg_n_formas_i ,  // formas habilitadas (0 = 1)

  // --- evento de salida (pulso de 1 ciclo) ---
  output                      ev_valid_o       ,
  output     [AMP_W-1:0]      ev_amp_o         ,
  output     [PSD_AW-1:0]     ev_psd_o         ,
  output                      ev_psd_ok_o      ,  // 0 => no histogramear el 2D
  // Bus de features: NFEAT ranuras de AMP_W bits, todas del MISMO evento.
  output     [NFEAT*AMP_W-1:0] ev_feat_o       ,

  // --- estado y contadores ---
  output     signed [DW-1:0]  baseline_o       ,
  output                      baseline_stale_o ,
  output     [32-1:0]         cnt_total_o      ,  // ventanas cerradas
  output     [32-1:0]         cnt_accepted_o   ,
  output     [32-1:0]         cnt_rej_amp_o    ,  // fuera de [min,max]
  output     [32-1:0]         cnt_rej_psd_o    ,  // q_tot=0 o q_tail>=q_tot
  output     [32-1:0]         cnt_pileup_o     ,  // cerradas con marca de solape
  output     [32-1:0]         cnt_lost_busy_o  ,  // sin ranura, alguna esperando publicar
  output     [QW-1:0]         last_qtot_o      ,
  output     [QW-1:0]         last_qtail_o     ,
  output                      busy_o           ,  // alguna ranura ocupada

  // --- casilleros de tiempo muerto: disjuntos, y su union es "no puede abrir" ---
  output                      dt_win_o         ,  // sin ranura libre, todas midiendo
  output                      dt_div_o         ,  // sin ranura libre, alguna esperando publicar
  output                      puede_abrir_o    ,
  output     [OC_W-1:0]       n_ocup_o         ,  // ranuras ocupadas ahora

  // --- atribucion de arribos: cada disparo va a UN casillero ---
  output                      arribo_o         ,  // disparo en esta muestra, con run
  output     [32-1:0]         cnt_cross_o      ,  // todos los arribos
  output     [32-1:0]         cnt_open_o       ,  // ...que abrieron ranura
  output     [32-1:0]         cnt_lost_active_o,  // ...sin ranura libre, todas midiendo
  output     [32-1:0]         cnt_lost_veto_o  ,  // ...bajo veto
  output     [32-1:0]         cnt_win_o        ,  // ventanas abiertas

  // --- la cola de publicacion ---
  output     [OC_W-1:0]       pub_occ_o        ,  // ranuras esperando publicar
  output     [OC_W-1:0]       pub_occ_max_o    ,  // maximo historico
  output     [PUB_IDW-1:0]    last_win_id_o    ,  // id de la ultima ventana publicada
  output     [32-1:0]         cnt_trig_o          // flancos crudos de trig_i
);

localparam integer NW  = 4;                        // bits de la marca `otras`
localparam integer TW  = 18;                       // salida del trapecio
localparam integer TNW = 8;                        // cuenta de la meseta
localparam integer TSW = TW + TNW - 1;

//-----------------------------------------------------------------------------
// Las ranuras, de la ventana a la publicacion, y lo que vuelve
//-----------------------------------------------------------------------------
wire [N_ACC-1:0]          acepta, libera, adentro, perdido;
wire [N_ACC*AMP_W-1:0]    amp_sel, amp_int;
wire [N_ACC*DW-1:0]       peak;
wire [N_ACC*LEN_W-1:0]    len, t_peak, dt_prev, dt_next;
wire [N_ACC*QW-1:0]       q_tot, q_tail;
wire [N_ACC*PUB_IDW-1:0]  win_id;
wire [N_ACC*NW-1:0]       otras;
wire [N_ACC*NF*TSW-1:0]   trap_sum;
wire [N_ACC*NF*TNW-1:0]   trap_n;
wire signed [DW-1:0]      baseline;
wire                      bl_track, cierra, bl_stale_set;

assign baseline_o = baseline;

//-----------------------------------------------------------------------------
// La linea de base
//-----------------------------------------------------------------------------
mca_baseline #(.DW(DW), .LEN_W(LEN_W), .BL_KW(BL_KW)) i_bl (
  .clk_i(clk_i), .rstn_i(rstn_i),
  .dat_i(dat_i), .val_i(val_i),
  .cfg_baseline_i(cfg_baseline_i), .cfg_bl_auto_i(cfg_bl_auto_i),
  .cfg_bl_k_i(cfg_bl_k_i), .cfg_bl_holdoff_i(cfg_bl_holdoff_i),
  .track_i(bl_track), .hold_load_i(cierra), .stale_set_i(bl_stale_set),
  .baseline_o(baseline), .baseline_stale_o(baseline_stale_o)
);

//-----------------------------------------------------------------------------
// El nucleo: disparo, asignador y ranuras
//-----------------------------------------------------------------------------
mca_window #(
  .DW(DW), .QW(QW), .AMP_W(AMP_W), .LEN_W(LEN_W),
  .N_ACC(N_ACC), .PUB_IDW(PUB_IDW), .NW(NW), .NA_W(NA_W),
  .N_FORMAS(N_FORMAS), .TDAW(TDAW), .TMW(TMW), .TW(TW), .TNW(TNW)
) i_win (
  .clk_i(clk_i), .rstn_i(rstn_i),
  .dat_i(dat_i), .val_i(val_i),
  .cfg_run_i(cfg_run_i), .veto_i(veto_i), .cnt_clr_i(cnt_clr_i),
  .cfg_gate_short_i(cfg_gate_short_i), .cfg_gate_long_i(cfg_gate_long_i),
  .cfg_amp_min_i(cfg_amp_min_i), .cfg_amp_max_i(cfg_amp_max_i),
  .cfg_amp_src_i(cfg_amp_src_i), .cfg_q_shift_i(cfg_q_shift_i),
  .cfg_n_acc_i(cfg_n_acc_i), .trig_i(trig_i),
  .trap_clr_i(trap_clr_i), .cfg_trap_k_i(cfg_trap_k_i), .cfg_trap_l_i(cfg_trap_l_i),
  .cfg_trap_mq_i(cfg_trap_mq_i), .cfg_trap_sh_i(cfg_trap_sh_i),
  .cfg_trap_off_i(cfg_trap_off_i), .cfg_trap_lw_i(cfg_trap_lw_i),
  .baseline_i(baseline), .bl_track_o(bl_track), .cierra_o(cierra),
  .bl_stale_set_o(bl_stale_set),
  .acepta_o(acepta), .amp_sel_o(amp_sel), .amp_int_o(amp_int),
  .peak_o(peak), .len_o(len), .t_peak_o(t_peak),
  .q_tot_o(q_tot), .q_tail_o(q_tail), .win_id_o(win_id),
  .dt_prev_o(dt_prev), .dt_next_o(dt_next), .otras_o(otras),
  .adentro_o(adentro), .perdido_o(perdido), .libera_i(libera),
  .trap_sum_o(trap_sum), .trap_n_o(trap_n),
  .cnt_total_o(cnt_total_o), .cnt_rej_amp_o(cnt_rej_amp_o),
  .cnt_pileup_o(cnt_pileup_o),
  .last_qtot_o(last_qtot_o), .last_qtail_o(last_qtail_o),
  .busy_o(busy_o),
  .dt_win_o(dt_win_o), .dt_div_o(dt_div_o), .puede_abrir_o(puede_abrir_o),
  .n_ocup_o(n_ocup_o), .arribo_o(arribo_o),
  .cnt_cross_o(cnt_cross_o), .cnt_open_o(cnt_open_o),
  .cnt_lost_active_o(cnt_lost_active_o), .cnt_lost_busy_o(cnt_lost_busy_o),
  .cnt_lost_veto_o(cnt_lost_veto_o),
  .cnt_win_o(cnt_win_o), .cnt_trig_o(cnt_trig_o)
);

//-----------------------------------------------------------------------------
// La publicacion
//-----------------------------------------------------------------------------
mca_publish #(
  .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .DIV_W(DIV_W),
  .NFEAT(NFEAT), .LEN_W(LEN_W), .EN_PSD(EN_PSD),
  .N_ACC(N_ACC), .PUB_IDW(PUB_IDW), .NW(NW), .TW(TW), .TNW(TNW),
  .N_FORMAS(N_FORMAS)
) i_pub (
  .clk_i(clk_i), .rstn_i(rstn_i), .cnt_clr_i(cnt_clr_i),
  .acepta_i(acepta), .amp_sel_i(amp_sel), .amp_int_i(amp_int),
  .peak_i(peak), .len_i(len), .t_peak_i(t_peak),
  .q_tot_i(q_tot), .q_tail_i(q_tail), .win_id_i(win_id),
  .dt_prev_i(dt_prev), .dt_next_i(dt_next), .otras_i(otras),
  .adentro_i(adentro), .perdido_i(perdido), .libera_o(libera),
  .trap_sum_i(trap_sum), .trap_n_i(trap_n), .cfg_trap_lw_i(cfg_trap_lw_i),
  .cfg_antes_i(cfg_trap_antes_i), .cfg_despues_i(cfg_trap_despues_i),
  .cfg_n_formas_i(cfg_n_formas_i),
  .pub_occ_o(pub_occ_o), .pub_occ_max_o(pub_occ_max_o),
  .ev_valid_o(ev_valid_o), .ev_amp_o(ev_amp_o), .ev_psd_o(ev_psd_o),
  .ev_psd_ok_o(ev_psd_ok_o), .ev_feat_o(ev_feat_o),
  .cnt_accepted_o(cnt_accepted_o), .cnt_rej_psd_o(cnt_rej_psd_o),
  .last_win_id_o(last_win_id_o)
);

endmodule
