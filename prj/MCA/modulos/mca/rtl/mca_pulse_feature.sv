`timescale 1ns/1ps
//=============================================================================
// mca_pulse_feature — segmentador de pulsos y extractor de características
//
// Recibe la muestra ya calibrada/filtrada y, por cada pulso detectado, emite
// UN registro de evento coherente {amp, psd} que alimenta a todos los motores
// de histograma. Que salga de un único registro es lo que garantiza que el
// espectro 1D y el mapa 2D cuenten exactamente los mismos pulsos.
//
//=============================================================================
// PARTICION: este modulo es solo cableado
//=============================================================================
// El extractor esta repartido en submodulos, uno por etapa de la vista general
// (docs/mca/vista_general_mca.md), de modo que cada decision Dn vive en un solo
// bloque:
//
//   mca_baseline la linea de base: seguidor IIR o base fija (D3)
//   mca_window   el nucleo: la muestra relativa a la base, quien abre (D4),
//                quien cierra (D5), el re-armado (D6), los acumuladores, la
//                ventana de amplitud (D7) y la contabilidad del tiempo muerto
//   mca_publish  la FIFO, el arbitro, los dos mca_div_restore y el armado del
//                bus de features (D8)
//
// Los puertos y los parametros son los mismos que cuando era un solo modulo,
// asi que mca_top, los testbenches y las assertions no se enteraron. Y el
// comportamiento es BIT-IDENTICO: lo verifica tb_mca_pulse_feature_eq contra
// la copia congelada sim/mca_pulse_feature_ref.v, en todas las salidas y en
// todos los ciclos.
//
// DONDE VAN LAS FRONTERAS lo decide el timing, no la prolijidad. El bitstream
// se sintetiza con -flatten_hierarchy none, asi que cada puerto es una barrera
// de optimizacion, y el camino critico (dat -> umbrales -> abrir/cerrar ->
// acumuladores) cerro con 6 ps. Las fronteras estan donde lo que cruza sale de
// un registro o entra directo a un pin de primitiva; por eso segmentacion y
// acumuladores comparten modulo.
//
// EL RE-ARMADO SE PROBO AFUERA y volvio. `armed` sale de un registro, pero abrir
// lo consume en el mismo flanco (y le gana al re-armado por nivel), asi que el
// modulo de afuera necesita el flanco de apertura como puerto. Con
// -flatten_hierarchy none Vivado arma una LUT dedicada a ese puerto y las cargas
// internas de la apertura pasan a colgar de ella: medido en la OOC, q_tot y
// q_tail cayeron a -0.131 ns y t_peak, d_min/d_max, win_id y gate_2nd perdieron
// 576 ps cada uno. No hay forma de no exportar ese flanco sin cambiar el
// comportamiento.
//
//=============================================================================
// FASE 2: las tres politicas, todas seleccionables por registro
//=============================================================================
// Las tres conviven en el MISMO bitstream y arrancan en el comportamiento
// historico, porque comparar dos politicas sobre los mismos pulsos es lo unico
// que decide entre ellas con datos (es el mismo argumento de cfg_amp_src).
//
// (1) QUIEN ABRE: cfg_trig_src. 0 = el Schmitt interno (como siempre),
//     1 = un TRIGGER EXTERNO (el trigger_event del multitrigger), 2 = cualquiera
//     de los dos. Detalle, y la advertencia de que el modo 1 no sirve para
//     espectrometria sin linea de retardo, en la cabecera de mca_window.
//
// (2) COMO SE RE-ARMA: cfg_rearm_mode. 0 = por NIVEL (la senal tiene que bajar
//     de thr_lo), 1 = por CONTADOR (cfg_rearm_dly muestras despues del cierre,
//     pase lo que pase con la senal).
//
//     ESTA ES LA PALANCA DEL TIEMPO MUERTO, y es la unica grande. Con re-armado
//     por nivel el modulo es PARALIZABLE: cada pulso que monta sobre la cola del
//     anterior extiende el bloqueo, y tau = 5.9 us. Con re-armado por contador es
//     NO PARALIZABLE y tau = 3.2 us determinista. En perdida de eventos con
//     arribos Poisson: 45.9 % -> 24.2 % a 100 kcps. El doble buffer de (3), en
//     comparacion, vale 0.7 pp.
//
//     Su contrapartida tambien esta medida y es seria: el re-armado por contador
//     SOBRE-CUENTA, porque trocea un apilamiento en pedazos del largo de la
//     compuerta y registra cada pedazo como un evento. La mitigacion no es volver
//     al nivel, es rechazar por FORMA (F_INVW / F_LEN): el ancho inverso rechaza
//     el 99.1 % de los apilados donde PSD rechaza el 0 % en modo compuerta. Los
//     contadores de la Fase 1 son los que permiten verificarlo.
//
// (3) COMO SE PUBLICA: cfg_pub_mode. 0 = BLOQUEANTE (la ventana no puede reabrir
//     hasta que los divisores terminan: st se queda en S_DIV, como siempre),
//     1 = FIFO de PUB_K lugares con id de ventana.
//
//     Lo que compra la FIFO es que la ventana cierre y REABRA sin esperar la
//     publicacion. Con UN solo juego de acumuladores desacopla la publicacion,
//     no las ventanas: K=2 alcanza, y para ventanas realmente solapadas habria
//     que duplicar acumuladores, que es otro costo.
//
//     Y EL DESBORDE DE LA FIFO ES TIEMPO MUERTO: sale en dt_pub_o y entra al
//     teselado como un casillero propio. Si no se contara, el tiempo muerto
//     oculto que la Fase 1 saco a la luz se habria mudado del Schmitt al arbitro
//     en vez de desaparecer.
//
// COMPATIBILIDAD. Con los tres registros en 0 el modulo es BIT-IDENTICO al de la
// Fase 1, incluido el largo exacto de S_DIV: por eso el cierre arranca los
// divisores desde los registros vivos cuando el publicador esta libre (ver
// `arranque_directo`) y S_DIV sale con `pub_done` y no con la FIFO vacia. Un
// ciclo de diferencia ahi no cambiaria nada fisico, pero romperia la identidad
// deadtime_cnt == t_win + t_div que la Fase 1 dejo como assertion.
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
  // Lugares de la FIFO de publicacion. K=1 reproduce exactamente la
  // arquitectura bloqueante; K=2 es el que desacopla la publicacion del cierre
  // (con UN juego de acumuladores no hace falta mas, ver cabecera).
  parameter integer PUB_K   = 2,
  parameter integer PUB_IDW = 16,  // bits del id de ventana
  // Derivado: va en la lista de parametros porque los puertos lo usan y un
  // localparam del cuerpo se declara demasiado tarde. No se sobreescribe.
  parameter integer PUB_AW  = (PUB_K <= 2) ? 1 : $clog2(PUB_K)
)(
  input                       clk_i            ,
  input                       rstn_i           ,

  // --- muestras de entrada (ya calibradas/filtradas/decimadas) ---
  input      signed [DW-1:0]  dat_i            ,
  input                       val_i            ,

  // --- configuración ---
  input                       cfg_run_i        ,
  // VETO externo (nivel): no se abren pulsos nuevos mientras vale 1. El pulso
  // en curso termina normal, y el seguidor de linea de base SIGUE corriendo
  // -- a diferencia de cfg_run=0 --, porque la base deriva igual durante el
  // veto y si se congelara arrancaria desfasada al liberarse. Viene del
  // trigger_shield del multitrigger (dst = mca).
  input                       veto_i           ,
  input                       cnt_clr_i        ,  // pulso: pone a cero los contadores
  input      signed [DW-1:0]  cfg_thr_i        ,  // umbral sobre la línea de base
  input             [DW-1:0]  cfg_hyst_i       ,  // histéresis (positiva)
  input      signed [DW-1:0]  cfg_baseline_i   ,  // base fija si cfg_bl_auto=0
  input                       cfg_bl_auto_i    ,
  input             [BL_KW-1:0] cfg_bl_k_i     ,  // alfa = 2^-k
  input             [LEN_W-1:0] cfg_bl_holdoff_i,
  input             [LEN_W-1:0] cfg_maxlen_i   ,
  input             [LEN_W-1:0] cfg_tail_dly_i ,  // >= 1
  // --- modo de ventana (ver cabecera, SEGMENTACION) ---
  input                       cfg_gate_mode_i  ,  // 0=histeresis, 1=compuertas fijas
  input             [LEN_W-1:0] cfg_gate_short_i, // compuerta corta, en muestras
  input             [LEN_W-1:0] cfg_gate_long_i ,  // compuerta larga, en muestras
  input             [AMP_W-1:0] cfg_amp_min_i  ,
  input             [AMP_W-1:0] cfg_amp_max_i  ,
  input                       cfg_amp_src_i    ,  // 0=pico, 1=integral
  input             [4:0]     cfg_q_shift_i    ,

  // --- FASE 2: apertura, re-armado y publicacion (ver cabecera) ---
  // Trigger externo. Se toma por FLANCO; `trig_pend` lo sostiene hasta la
  // muestra valida siguiente para que la decimacion no se lo coma.
  input                       trig_i           ,
  input             [1:0]     cfg_trig_src_i   ,  // 0=interno, 1=externo, 2=ambos
  input                       cfg_rearm_mode_i ,  // 0=nivel(thr_lo), 1=contador
  input             [LEN_W-1:0] cfg_rearm_dly_i,  // holdoff de re-armado
  input                       cfg_pub_mode_i   ,  // 0=bloqueante, 1=FIFO

  // --- evento de salida (pulso de 1 ciclo) ---
  output                      ev_valid_o       ,
  output     [AMP_W-1:0]      ev_amp_o         ,
  output     [PSD_AW-1:0]     ev_psd_o         ,
  output                      ev_psd_ok_o      ,  // 0 => no histogramear el 2D
  // Bus de features: NFEAT ranuras de AMP_W bits, todas del MISMO evento.
  // Se arma a la salida de S_DIV, no al cerrar, porque los cocientes valen
  // DIV_W ciclos mas tarde que el resto (ver F_ del cuerpo).
  output     [NFEAT*AMP_W-1:0] ev_feat_o       ,

  // --- estado y contadores ---
  output     signed [DW-1:0]  baseline_o       ,
  output                      baseline_stale_o ,
  output     [32-1:0]         cnt_total_o      ,  // pulsos cerrados
  output     [32-1:0]         cnt_accepted_o   ,
  output     [32-1:0]         cnt_rej_amp_o    ,  // fuera de [min,max]
  output     [32-1:0]         cnt_rej_psd_o    ,  // q_tot=0 o q_tail>=q_tot
  output     [32-1:0]         cnt_pileup_o     ,  // cerrado por maxlen
  output     [32-1:0]         cnt_lost_busy_o  ,  // pulso perdido con el divisor ocupado
  output     [QW-1:0]         last_qtot_o      ,
  output     [QW-1:0]         last_qtail_o     ,
  output                      busy_o           ,  // pulso activo o divisor ocupado

  // --- casilleros de tiempo muerto (ver "TIEMPO MUERTO" del cuerpo) ---
  // Mutuamente excluyentes. Su union es exactamente "no puede abrir", salvo los
  // terminos cfg_run/veto que los pone mca_top porque son suyos.
  output                      dt_win_o         ,  // ventana abierta
  output                      dt_div_o         ,  // bloqueado por la publicacion
  output                      dt_rearm_o       ,  // libre pero sin re-armar
  output                      puede_abrir_o    ,

  // --- atribucion de arribos: cada cruce de thr_hi va a UN casillero ---
  output                      arribo_o         ,  // flanco de thr_hi, 1 ciclo
  output     [32-1:0]         cnt_cross_o      ,  // todos los cruces de thr_hi
  output     [32-1:0]         cnt_open_o       ,  // ...que abrieron ventana
  output     [32-1:0]         cnt_lost_rearm_o ,  // ...perdidos esperando el re-armado
  output     [32-1:0]         cnt_lost_active_o,  // ...llegados dentro de la ventana
  output     [32-1:0]         cnt_lost_veto_o  ,  // ...llegados bajo veto
  // FASE 2. Con apertura por trigger externo un cruce puede encontrar al modulo
  // libre y NO abrir (porque no vino trigger), y una ventana puede abrir SIN
  // cruce (trigger sobre un pulso bajo umbral, o por software). Son dos hechos
  // distintos y necesitan dos contadores distintos:
  output     [32-1:0]         cnt_lost_notrig_o,  // cruce libre, sin disparo habilitado
  output     [32-1:0]         cnt_win_o        ,  // ventanas ABIERTAS (venga o no de un cruce)

  // --- FASE 2: estado del arbitro de publicacion ---
  // occ_max es el dato que decide si PUB_K alcanza: si llega a PUB_K hubo
  // contrapresion, y los eventos que se perdieron por eso estan en cnt_lost_busy.
  output     [PUB_AW:0]       pub_occ_o        ,  // lugares ocupados ahora
  output     [PUB_AW:0]       pub_occ_max_o    ,  // maximo historico
  output     [PUB_IDW-1:0]    last_win_id_o    ,  // id de la ultima ventana publicada
  output     [32-1:0]         cnt_trig_o          // flancos de trigger externo
);

//-----------------------------------------------------------------------------
// Lo que la ventana le pasa a la publicacion, y lo que vuelve
//-----------------------------------------------------------------------------
wire                acepta;
wire [AMP_W-1:0]    amp_sel, amp_int;
wire [DW-1:0]       peak;
wire [LEN_W-1:0]    len, t_peak;
wire [QW-1:0]       q_tot, q_tail;
wire [PUB_IDW-1:0]  win_id;
wire                pub_done;
wire signed [DW-1:0] baseline;
wire                bl_track, cierra, bl_stale_set;

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
// El nucleo de la ventana
//-----------------------------------------------------------------------------
mca_window #(
  .DW(DW), .QW(QW), .AMP_W(AMP_W), .LEN_W(LEN_W),
  .EN_PSD(EN_PSD), .PUB_K(PUB_K), .PUB_IDW(PUB_IDW)
) i_win (
  .clk_i(clk_i), .rstn_i(rstn_i),
  .dat_i(dat_i), .val_i(val_i),
  .cfg_run_i(cfg_run_i), .veto_i(veto_i), .cnt_clr_i(cnt_clr_i),
  .cfg_thr_i(cfg_thr_i), .cfg_hyst_i(cfg_hyst_i),
  .cfg_maxlen_i(cfg_maxlen_i), .cfg_tail_dly_i(cfg_tail_dly_i),
  .cfg_gate_mode_i(cfg_gate_mode_i), .cfg_gate_short_i(cfg_gate_short_i),
  .cfg_gate_long_i(cfg_gate_long_i),
  .cfg_amp_min_i(cfg_amp_min_i), .cfg_amp_max_i(cfg_amp_max_i),
  .cfg_amp_src_i(cfg_amp_src_i), .cfg_q_shift_i(cfg_q_shift_i),
  .trig_i(trig_i), .cfg_trig_src_i(cfg_trig_src_i),
  .cfg_rearm_mode_i(cfg_rearm_mode_i), .cfg_rearm_dly_i(cfg_rearm_dly_i),
  .cfg_pub_mode_i(cfg_pub_mode_i),
  .acepta_o(acepta), .amp_sel_o(amp_sel), .amp_int_o(amp_int),
  .peak_o(peak), .len_o(len), .t_peak_o(t_peak),
  .q_tot_o(q_tot), .q_tail_o(q_tail), .win_id_o(win_id),
  .pub_occ_i(pub_occ_o), .pub_done_i(pub_done),
  .baseline_i(baseline), .bl_track_o(bl_track), .cierra_o(cierra),
  .bl_stale_set_o(bl_stale_set),
  .cnt_total_o(cnt_total_o), .cnt_rej_amp_o(cnt_rej_amp_o),
  .cnt_pileup_o(cnt_pileup_o), .cnt_lost_busy_o(cnt_lost_busy_o),
  .last_qtot_o(last_qtot_o), .last_qtail_o(last_qtail_o),
  .busy_o(busy_o),
  .dt_win_o(dt_win_o), .dt_div_o(dt_div_o), .dt_rearm_o(dt_rearm_o),
  .puede_abrir_o(puede_abrir_o), .arribo_o(arribo_o),
  .cnt_cross_o(cnt_cross_o), .cnt_open_o(cnt_open_o),
  .cnt_lost_rearm_o(cnt_lost_rearm_o), .cnt_lost_active_o(cnt_lost_active_o),
  .cnt_lost_veto_o(cnt_lost_veto_o), .cnt_lost_notrig_o(cnt_lost_notrig_o),
  .cnt_win_o(cnt_win_o), .cnt_trig_o(cnt_trig_o)
);

//-----------------------------------------------------------------------------
// La publicacion
//-----------------------------------------------------------------------------
mca_publish #(
  .DW(DW), .QW(QW), .AMP_W(AMP_W), .PSD_AW(PSD_AW), .DIV_W(DIV_W),
  .NFEAT(NFEAT), .LEN_W(LEN_W), .EN_PSD(EN_PSD),
  .PUB_K(PUB_K), .PUB_IDW(PUB_IDW)
) i_pub (
  .clk_i(clk_i), .rstn_i(rstn_i), .cnt_clr_i(cnt_clr_i),
  .acepta_i(acepta), .amp_sel_i(amp_sel), .amp_int_i(amp_int),
  .peak_i(peak), .len_i(len), .t_peak_i(t_peak),
  .q_tot_i(q_tot), .q_tail_i(q_tail), .win_id_i(win_id),
  .pub_occ_o(pub_occ_o), .pub_occ_max_o(pub_occ_max_o), .pub_done_o(pub_done),
  .ev_valid_o(ev_valid_o), .ev_amp_o(ev_amp_o), .ev_psd_o(ev_psd_o),
  .ev_psd_ok_o(ev_psd_ok_o), .ev_feat_o(ev_feat_o),
  .cnt_accepted_o(cnt_accepted_o), .cnt_rej_psd_o(cnt_rej_psd_o),
  .last_win_id_o(last_win_id_o)
);

endmodule
