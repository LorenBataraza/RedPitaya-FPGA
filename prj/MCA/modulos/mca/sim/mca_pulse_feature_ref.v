// COPIA CONGELADA de modulos/mca/rtl/mca_pulse_feature.sv ANTES de partirlo en
// submodulos (mca_baseline, mca_window, mca_publish). Solo la usa
// tb_mca_pulse_feature_eq.sv como referencia dorada: el wrapper nuevo tiene que
// dar EXACTAMENTE los mismos bits en todas las salidas, en todos los ciclos.
// No se sintetiza y no entra a files.f.
//
`timescale 1ns/1ps
//=============================================================================
// mca_pulse_feature — segmentador de pulsos y extractor de características
//
// Recibe la muestra ya calibrada/filtrada y, por cada pulso detectado, emite
// UN registro de evento coherente {amp, psd} que alimenta a todos los motores
// de histograma. Que salga de un único registro es lo que garantiza que el
// espectro 1D y el mapa 2D cuenten exactamente los mismos pulsos.
//
// LÍNEA DE BASE. Seguidor IIR  bl_acc += x - (bl_acc >> k),  bl = bl_acc >> k.
// El acumulador es ancho a propósito: con la forma ingenua `bl += (x-bl)>>k`
// el incremento se cuantiza a cero cuando |x-bl| < 2^k y el seguidor se
// congela. Se congela durante el pulso Y durante cfg_bl_holdoff muestras
// después: si se descongelara al cruzar la histéresis hacia abajo, agarraría
// el undershoot de la cola y arrastraría la base hacia el lado equivocado.
//
// SEGMENTACIÓN. Schmitt igual que rp_adc_trig.v, para que los umbrales del
// MCA y del scope sean comparables. Abre al cruzar cfg_thr hacia arriba, con
// re-armado previo por debajo de cfg_thr-cfg_hyst. Para CERRAR hay dos modos,
// seleccionables por cfg_gate_mode:
//
//   0 = HISTÉRESIS: cierra al bajar de cfg_thr-cfg_hyst, o al llegar a
//       cfg_maxlen (esto último cuenta como APILAMIENTO).
//   1 = COMPUERTAS FIJAS: cierra a cfg_gate_long muestras del disparo, y la
//       cola arranca en cfg_gate_short. Es el método de comparación de carga.
//
// El motivo del modo 1: con histéresis el largo de la ventana lo decide dónde
// la cola cruza el umbral, que es la parte más chata del pulso, así que lo
// decide el ruido. Medido offline sobre 7054 pulsos reales, la resolución de la
// integral pasa de 0.528 % (histéresis) a 0.149 % (compuerta fija). Ver
// software/API/modelo_rtl/estimadores.py.
//
// Los eventos marcados como apilamiento se cuentan pero NO se histogramean,
// porque su integral y su pico están contaminados por el segundo pulso.
//
// AMPLITUD. Seleccionable por cfg_amp_src:
//   0 = muestra de pico   -> ruido de UNA muestra, y el muestreo casi nunca
//                            cae en el máximo real: ensancha el fotopico.
//   1 = integral de carga -> el ruido blanco promedia como sigma/sqrt(N) y
//                            es inmune al jitter de muestreo. Es lo que hace
//                            cualquier MCA digital serio, y lo que justifica
//                            un eje de 16384 canales.
// Poder alternar entre ambos en el mismo bitstream ES el experimento que mide
// la contribución de jitter de muestreo.
//
// PICO con comparación ESTRICTA (>): en un techo plano con ruido gana la
// PRIMERA ocurrencia del máximo. Con >= el instante de pico se correría hasta
// el final de la meseta y el tiempo de subida saldría arbitrariamente largo.
//
// CARGA. Cada muestra se satura a >= 0 antes de acumular. Sin eso, una cola
// con undershoot resta de q_tot mientras q_tail (en la parte plana) sigue
// sumando, y se llega a q_tail > q_total, que rompe la premisa del divisor.
//
// TIEMPO MUERTO. `busy_o` NO es la condicion de bloqueo del modulo, y usarlo
// como tal es lo que hacia que el reloj de tiempo muerto de mca_top mintiera.
// La condicion real es el complemento de `open_pulse`, que exige `armed` -- una
// condicion de NIVEL: no se re-arma hasta que la senal baja de thr_lo. Mientras
// la cola del ultimo pulso siga arriba, st == S_IDLE (asi que `busy_o` esta
// bajo) pero el modulo NO PUEDE ABRIR. Ese tiempo no entraba en ningun
// contador. Por eso ademas de `busy_o` salen los cuatro casilleros dt_* y los
// contadores de atribucion de arribos; ver las dos secciones del cuerpo.
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
//     de los dos. El trigger se toma por FLANCO y nunca por nivel: un trigger
//     por software dura ~5 ciclos de bus y por nivel abriria varias ventanas
//     (es el bug que event_window_capture.sv:58-64 ya documenta en la placa).
//
//     ADVERTENCIA QUE NO SE PUEDE TAPAR: el trigger externo llega con latencia
//     respecto de la muestra que lo causo, asi que la ventana arranca unas
//     muestras TARDE y se pierde el flanco de subida -- la integral y el pico
//     salen truncados. Para que el modo 1 sirva para medir energia hace falta la
//     linea de retardo de muestras de la Fase 3 (muestreo doble correlacionado),
//     que es justamente donde el plan la puso. Sin ella, el modo 1 sirve para
//     coincidencia y para tener una base de tiempo comun, NO para espectrometria.
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

module mca_pulse_feature_ref #(
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
  output reg                  ev_valid_o       ,
  output reg [AMP_W-1:0]      ev_amp_o         ,
  output reg [PSD_AW-1:0]     ev_psd_o         ,
  output reg                  ev_psd_ok_o      ,  // 0 => no histogramear el 2D
  // Bus de features: NFEAT ranuras de AMP_W bits, todas del MISMO evento.
  // Se arma a la salida de S_DIV, no al cerrar, porque los cocientes valen
  // DIV_W ciclos mas tarde que el resto (ver F_ del cuerpo).
  output reg [NFEAT*AMP_W-1:0] ev_feat_o       ,

  // --- estado y contadores ---
  output     signed [DW-1:0]  baseline_o       ,
  output reg                  baseline_stale_o ,
  output reg [32-1:0]         cnt_total_o      ,  // pulsos cerrados
  output reg [32-1:0]         cnt_accepted_o   ,
  output reg [32-1:0]         cnt_rej_amp_o    ,  // fuera de [min,max]
  output reg [32-1:0]         cnt_rej_psd_o    ,  // q_tot=0 o q_tail>=q_tot
  output reg [32-1:0]         cnt_pileup_o     ,  // cerrado por maxlen
  output reg [32-1:0]         cnt_lost_busy_o  ,  // pulso perdido con el divisor ocupado
  output reg [QW-1:0]         last_qtot_o      ,
  output reg [QW-1:0]         last_qtail_o     ,
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
  output reg [32-1:0]         cnt_cross_o      ,  // todos los cruces de thr_hi
  output reg [32-1:0]         cnt_open_o       ,  // ...que abrieron ventana
  output reg [32-1:0]         cnt_lost_rearm_o ,  // ...perdidos esperando el re-armado
  output reg [32-1:0]         cnt_lost_active_o,  // ...llegados dentro de la ventana
  output reg [32-1:0]         cnt_lost_veto_o  ,  // ...llegados bajo veto
  // FASE 2. Con apertura por trigger externo un cruce puede encontrar al modulo
  // libre y NO abrir (porque no vino trigger), y una ventana puede abrir SIN
  // cruce (trigger sobre un pulso bajo umbral, o por software). Son dos hechos
  // distintos y necesitan dos contadores distintos:
  output reg [32-1:0]         cnt_lost_notrig_o,  // cruce libre, sin disparo habilitado
  output reg [32-1:0]         cnt_win_o        ,  // ventanas ABIERTAS (venga o no de un cruce)

  // --- FASE 2: estado del arbitro de publicacion ---
  // occ_max es el dato que decide si PUB_K alcanza: si llega a PUB_K hubo
  // contrapresion, y los eventos que se perdieron por eso estan en cnt_lost_busy.
  output     [PUB_AW:0]       pub_occ_o        ,  // lugares ocupados ahora
  output reg [PUB_AW:0]       pub_occ_max_o    ,  // maximo historico
  output reg [PUB_IDW-1:0]    last_win_id_o    ,  // id de la ultima ventana publicada
  output reg [32-1:0]         cnt_trig_o          // flancos de trigger externo
);

localparam integer XW      = DW + 1;              // x con signo
localparam integer BL_ACC_W = DW + (1<<BL_KW);    // acumulador del IIR

//-----------------------------------------------------------------------------
// Línea de base
//-----------------------------------------------------------------------------
reg signed [BL_ACC_W-1:0] bl_acc;

// El desplazamiento por cfg_bl_k_i es un barrel shifter de 30 bits x 16
// posiciones. Se saca del lazo del IIR registrandolo: el seguidor usa el valor
// desplazado del ciclo anterior. Para un promedio exponencial lento eso es
// irrelevante (sigue convergiendo al mismo DC), pero deja el lazo en una sola
// suma en vez de shifter + suma.
reg signed [BL_ACC_W-1:0] bl_acc_shr;
always @(posedge clk_i)
  if (!rstn_i) bl_acc_shr <= {BL_ACC_W{1'b0}};
  else         bl_acc_shr <= bl_acc >>> cfg_bl_k_i;

// La linea de base tambien se REGISTRA. Sin esto el camino era
//   bl_acc -> barrel shifter -> resta de 15 b -> comparacion con el umbral
//   -> logica de control
// todo combinacional en un ciclo: 10 niveles de logica y -0.674 ns a 125 MHz,
// el peor camino de todo el MCA. La base varia lentamente por construccion,
// asi que usarla un ciclo mas tarde no cambia nada observable.
reg signed [DW-1:0] baseline;
always @(posedge clk_i)
  if (!rstn_i) baseline <= {DW{1'b0}};
  else         baseline <= cfg_bl_auto_i ? bl_acc_shr[DW-1:0] : cfg_baseline_i;

assign baseline_o = baseline;

//-----------------------------------------------------------------------------
// Muestra relativa a la base, y su versión saturada a >= 0 para las cargas
//-----------------------------------------------------------------------------
// dat_i y baseline son DW bits con signo, así que x va de -(2^DW-1) a 2^DW-1:
// la parte positiva entra EXACTA en DW bits sin signo y no hace falta clamp
// superior. El clamp a >= 0 sí hace falta (ver cabecera: protege q_tail<q_tot).
wire signed [XW-1:0] x  = $signed({dat_i[DW-1], dat_i}) - $signed({baseline[DW-1], baseline});
wire        [DW-1:0] xc = x[XW-1] ? {DW{1'b0}} : x[DW-1:0];

wire signed [XW-1:0] thr_hi = $signed({cfg_thr_i[DW-1], cfg_thr_i});
wire signed [XW-1:0] thr_lo = thr_hi - $signed({1'b0, cfg_hyst_i});

//-----------------------------------------------------------------------------
// FSM
//-----------------------------------------------------------------------------
localparam [1:0] S_IDLE = 2'd0, S_ACTIVE = 2'd1, S_DIV = 2'd2;

reg [1:0]        st;
reg              armed;          // x estuvo por debajo de thr_lo
reg [LEN_W-1:0]  len;            // muestras desde el inicio del pulso
reg [LEN_W-1:0]  t_peak;         // índice de la muestra de pico
reg [DW-1:0]     peak;
reg [QW-1:0]     q_tot, q_tail;
reg [LEN_W-1:0]  bl_hold;        // cuenta atrás del holdoff post-pulso
reg [LEN_W-1:0]  rearm_cnt;      // holdoff de re-armado (modo contador)
reg [PUB_IDW-1:0] win_id;        // id de la ventana en curso

// Estado del arbitro de publicacion. Se declara ACA porque `pub_lleno` entra en
// la condicion de apertura; el resto del arbitro esta mas abajo.
reg [PUB_AW-1:0] pub_wr, pub_rd;
reg [PUB_AW:0]   pub_occ;
wire pub_vacio = (pub_occ == {(PUB_AW+1){1'b0}});
wire pub_lleno = (pub_occ >= PUB_K[PUB_AW:0]);

assign pub_occ_o = pub_occ;

//-----------------------------------------------------------------------------
// APERTURA: quien dispara, y que la habilita
//-----------------------------------------------------------------------------
// El trigger externo se toma por FLANCO. `trig_pend` lo sostiene hasta la
// muestra valida siguiente: sin eso, con cfg_dec > 1 el trigger caeria entre dos
// muestras validas y se perderia en silencio.
reg  trig_q, trig_pend;
wire trig_edge = trig_i && !trig_q;

always @(posedge clk_i)
  if (!rstn_i) begin
    trig_q    <= 1'b0;
    trig_pend <= 1'b0;
  end else begin
    trig_q <= trig_i;
    // Un trigger vale para la muestra siguiente y nada mas: si no se puede usar
    // ahi, se descarta. Un pendiente sin vencimiento abriria una ventana
    // arbitrariamente tarde, ya sin relacion con el pulso que lo causo.
    if      (trig_edge) trig_pend <= 1'b1;
    else if (val_i)     trig_pend <= 1'b0;
  end

// Decode de la fuente, REGISTRADO: deja la seleccion en una sola capa de logica
// sobre `open_pulse`, que es un camino ya ajustado al limite.
reg src_int_en, src_ext_en;
always @(posedge clk_i)
  if (!rstn_i) begin
    src_int_en <= 1'b1;
    src_ext_en <= 1'b0;
  end else begin
    src_int_en <= (cfg_trig_src_i != 2'd1);   // 0 y 2 usan el Schmitt
    src_ext_en <= (cfg_trig_src_i != 2'd0);   // 1 y 2 usan el trigger externo
  end

wire disparo_int = (x >= thr_hi);
wire disparo_ext = trig_edge || trig_pend;
wire disparo     = (src_int_en && disparo_int) || (src_ext_en && disparo_ext);

// `armed` sigue siendo la compuerta de re-armado en TODOS los modos: lo que
// cambia con cfg_rearm_mode es QUIEN lo pone, no que haga falta. Y `!pub_lleno`
// es el termino nuevo de la Fase 2: sin lugar donde publicar, no se abre.
wire open_pulse  = (st == S_IDLE) && cfg_run_i && !veto_i && armed
                   && !pub_lleno && disparo;

// CIERRE. Dos modos, seleccionables por registro:
//
//   modo 0 (histéresis): cierra al bajar de thr_lo. El largo lo decide la
//     señal... y con una cola exponencial eso significa que lo decide el RUIDO,
//     porque el cruce cae en la zona más chata del pulso. Medido offline sobre
//     7054 pulsos: el cruce tiembla ~9 muestras y cada una vale ~60 cuentas de
//     carga, y la resolución de la integral sale 0.528 %.
//   modo 1 (compuertas fijas): cierra a cfg_gate_long muestras del disparo,
//     pase lo que pase. Es el método de comparación de carga (Brooks 1959;
//     Knoll cap. 17). Medido offline sobre los MISMOS pulsos: 0.149 %, o sea
//     3.5x mejor que el modo 0 y 1.8x mejor que la muestra de pico.
//
// cfg_maxlen sólo actúa en el modo 0: en el modo 1 el largo ya está acotado por
// la compuerta, así que dejarlo activo sólo agregaría un modo de falla si
// alguien configura maxlen < gate_long.
wire close_hyst  = (st == S_ACTIVE) && !cfg_gate_mode_i && (x < thr_lo);
wire close_maxl  = (st == S_ACTIVE) && !cfg_gate_mode_i && (len >= cfg_maxlen_i);
wire close_gate  = (st == S_ACTIVE) &&  cfg_gate_mode_i && (len >= cfg_gate_long_i);
wire close_pulse = close_hyst || close_maxl || close_gate;

// APILAMIENTO en modo compuerta: un SEGUNDO pulso dentro de la compuerta, o sea
// que la señal bajó de thr_lo y volvió a cruzar thr_hi con la ventana abierta.
//
// La regla obvia —"si al cerrar la señal sigue por encima de thr_lo, hay
// apilamiento"— es INCORRECTA y se descubrió midiendo en la placa: la cola del
// PROPIO pulso tarda cientos de muestras en bajar de thr_lo (~700 con un pulso
// de 2 µs y thr_lo = 60 cuentas), así que marcaba como apilado el 100 % de los
// eventos con cualquier compuerta más corta que la cola — justo el rango útil.
// Peor: el punto de cruce cae en la parte más chata del pulso, así que se movía
// cientos de muestras con cualquier deriva de línea de base y el resultado no
// era ni siquiera reproducible entre corridas.
reg gate_rearm;      // dentro de la compuerta, la señal bajó de thr_lo
reg gate_2nd;        // ...y después volvió a cruzar thr_hi: hay un 2do pulso
wire gate_pileup = close_gate && gate_2nd;

// COLA. En modo 0 arranca cfg_tail_dly muestras después del pico: mientras el
// pulso sube, t_peak == len y la condición es falsa (con tail_dly >= 1). En
// modo 1 arranca en la compuerta corta, medida desde el DISPARO — que es lo que
// la hace inmune al jitter del instante de pico.
wire in_tail = (st == S_ACTIVE) &&
               (cfg_gate_mode_i ? (len >= cfg_gate_short_i)
                                : (len >= (t_peak + cfg_tail_dly_i)));

//-----------------------------------------------------------------------------
// Valor SIGUIENTE de los acumuladores, como cables
//-----------------------------------------------------------------------------
// Son el D de q_tot y de peak (la FSM ya no los asigna por su cuenta) y, a la
// vez, la entrada del comparador de ventana registrado de mas abajo. Nombrarlos
// es lo que permite evaluar la ventana un ciclo ANTES del cierre sin cambiar
// ni un bit de lo que se acumula.
wire acumula = (st == S_ACTIVE) && val_i && !close_pulse;

wire [QW-1:0] q_tot_d = (val_i && open_pulse) ? {{(QW-DW){1'b0}}, xc}
                      : acumula                ? q_tot + {{(QW-DW){1'b0}}, xc}
                      :                          q_tot;
// Pico con comparación ESTRICTA: gana la primera ocurrencia.
wire          nuevo_pico = acumula && (xc > peak);
wire [DW-1:0] peak_d  = (val_i && open_pulse) ? xc
                      : nuevo_pico            ? xc
                      :                         peak;

//-----------------------------------------------------------------------------
// Amplitud: pico o integral, con saturación a AMP_W bits
//-----------------------------------------------------------------------------
wire [QW-1:0]    q_shifted = q_tot >> cfg_q_shift_i;
wire             q_ovf     = |q_shifted[QW-1:AMP_W];
wire [AMP_W-1:0] amp_int   = q_ovf ? {AMP_W{1'b1}} : q_shifted[AMP_W-1:0];
wire [AMP_W-1:0] amp_peak  = {{(AMP_W-DW){1'b0}}, peak};
wire [AMP_W-1:0] amp_sel   = cfg_amp_src_i ? amp_int : amp_peak;

//-----------------------------------------------------------------------------
// Ventana de amplitud [amp_min, amp_max]: evaluada un ciclo ANTES del cierre
//-----------------------------------------------------------------------------
// ERA el camino critico de todo el bitstream (6 ps de slack en el build, y
// -0.129 ns con mca_top aislado): en el ciclo de cierre, q_tot pasaba por el
// barrel shifter, la reduccion OR de la saturacion, dos muxes y dos comparadores
// de AMP_W bits, y el resultado gateaba el clock-enable de los ~60 flops hold_*
// y el registro de estado. Ocho niveles de LUT en 8 ns.
//
// Tres hechos lo sacan del ciclo de cierre SIN agregar latencia:
//
//  1. En el ciclo de cierre q_tot NO se acumula (`acumula` incluye
//     !close_pulse), asi que su valor final es el que se escribio en el flanco
//     anterior: q_tot(cierre) == q_tot_d(cierre - 1).
//  2. Comparar la version DESPLAZADA contra [min, max] es lo mismo que comparar
//     q_tot sin desplazar contra umbrales pre-desplazados:
//         sat(q_tot >> s) >= min  <=>  q_tot >= (min << s)
//         sat(q_tot >> s) <= max  <=>  q_tot <= ((max+1) << s) - 1
//     con UNA excepcion, la saturacion: amp_int = 2^AMP_W-1 se acepta hoy solo
//     si max == 2^AMP_W-1, y en esa rama la segunda desigualdad da falso. Por
//     eso el termino sat_ok, que la restituye exactamente.
//  3. Los umbrales pre-desplazados dependen solo de registros de configuracion:
//     se calculan y se registran aparte, y un cambio de configuracion tarda un
//     ciclo mas en verse. Nada observable: la configuracion no cambia a mitad
//     de un pulso.
//
// Con eso, en el ciclo de cierre amp_ok es un mux de tres flops.
//
// LO QUE ENTRA AL COMPARADOR NO ES q_tot_d. La primera version lo usaba, y el
// camino se fue a 13 niveles (-1.5 ns): q_tot_d lleva adentro `acumula`, que
// lleva !close_pulse, que lleva x < thr_lo -- o sea el decode del cierre
// entero, ahora delante del sumador y del comparador. Pero el comparador solo
// tiene que acertar en el ciclo ANTERIOR a un cierre, y un cierre exige
// st == S_ACTIVE y val_i: en ese ciclo previo el pulso esta abierto y, si
// tiene muestra, acumula. Asi que la entrada especulativa
//
//     q_spec = (st == S_ACTIVE) ? (val_i ? q_tot + xc : q_tot) : xc
//
// coincide con q_tot_d en todos los ciclos que importan (el previo a un cierre,
// y el de apertura -- que es el previo al cierre de un pulso de una muestra) y
// difiere solo en ciclos cuyo resultado nunca se lee: el propio ciclo de cierre
// y los de reposo. Cero comparadores de umbral en el camino.
//
// Para el pico ni siquiera hace falta el mux: max(peak, xc) >= min es
// (peak >= min) || (xc >= min), y max(peak, xc) <= max es (peak <= max) &&
// (xc <= max). Cuatro comparadores EN PARALELO desde flops y una capa de
// logica, en vez de comparar-mux-comparar en serie.
//
// Y PARA LA INTEGRAL, NI SIQUIERA UN COMPARADOR. Con q_spec = q_tot + xc y un
// comparador contra min_q el camino eran TRES cadenas de carry en serie
// (dat - baseline, + q_tot, >= min_q: 15 niveles, -0.133 ns), lo mismo que
// habia antes. La tercera se elimina llevando la resta hecha: dos registros
// sombra d_min = q_tot - min_q y d_max = max_q - q_tot, que se actualizan con
// LA MISMA regla que q_tot (al abrir: xc - min_q; acumulando: += xc). Entonces
//     q_tot + xc >= min_q   <=>   d_min + xc >= 0   <=>   !signo(d_min + xc)
// y el comparador es el bit de signo de UNA suma. En reposo, para la apertura,
// la resta se hace directo sobre `x` sin recortar contra (baseline + min_q)
// registrado: una sola cadena tambien. El recorte de xc a 0 no cambia el
// resultado: si x < 0, x >= min_q es falso salvo min_q == 0 (termino aparte) y
// x <= max_q es verdadero, igual que con xc = 0.
localparam integer QX_W = AMP_W + 32;             // (max+1) << 31 sin desbordar
localparam integer DQ_W = QW + 2;                 // diferencias con signo, sin desborde

wire            en_activo = (st == S_ACTIVE);
wire [AMP_W-1:0] xc_w   = {{(AMP_W-DW){1'b0}}, xc};
wire [AMP_W-1:0] peak_w = {{(AMP_W-DW){1'b0}}, peak};
wire xc_ge_min = (xc_w   >= cfg_amp_min_i), xc_le_max = (xc_w   <= cfg_amp_max_i);
wire pk_ge_min = (peak_w >= cfg_amp_min_i), pk_le_max = (peak_w <= cfg_amp_max_i);
// max(peak, xc) con val_i, peak sin muestra, xc al abrir
wire peak_ok_spec = !en_activo ? (xc_ge_min && xc_le_max)
                  : ((pk_ge_min || (val_i && xc_ge_min)) &&
                     (pk_le_max && (!val_i || xc_le_max)));

wire [QX_W-1:0] min_q_w = {{(QX_W-AMP_W){1'b0}}, cfg_amp_min_i} << cfg_q_shift_i;
wire [QX_W-1:0] max_q_w = ({{(QX_W-AMP_W){1'b0}}, cfg_amp_max_i} + {{(QX_W-1){1'b0}}, 1'b1})
                          << cfg_q_shift_i;        // (max+1) << s

reg [QW-1:0] min_q, max_q;
reg          min_fuera;     // min << s no entra en QW: ningun q_tot alcanza
reg          min_cero;      // min << s == 0: todo q_tot cumple, aun con x < 0
reg          sat_ok;        // max == todo unos: la saturacion se acepta
reg          ge_min_r, le_max_r, peak_ok_r;

// Sombras de q_tot: siguen su misma regla de actualizacion (abrir, acumular,
// sostener) y llevan la resta contra la ventana ya hecha.
reg  signed [DQ_W-1:0] d_min, d_max;           // q_tot - min_q, max_q - q_tot
wire signed [DQ_W-1:0] xc_s    = {{(DQ_W-DW){1'b0}}, xc};
wire signed [DQ_W-1:0] min_q_s = {{(DQ_W-QW){1'b0}}, min_q};
wire signed [DQ_W-1:0] max_q_s = {{(DQ_W-QW){1'b0}}, max_q};
wire signed [DQ_W-1:0] d_min_d = (val_i && open_pulse) ? xc_s - min_q_s
                               : acumula                ? d_min + xc_s
                               :                          d_min;
wire signed [DQ_W-1:0] d_max_d = (val_i && open_pulse) ? max_q_s - xc_s
                               : acumula                ? d_max - xc_s
                               :                          d_max;

// Para la apertura (reposo): x SIN recortar contra min_q y max_q. Dos cadenas
// (la resta de la base y esta), igual que el camino activo. No se precomputa
// (baseline + min_q) porque la base cambia cada ciclo de reposo y quedaria un
// ciclo desfasada de la x que decide la apertura.
wire signed [DQ_W-1:0] x_s = {{(DQ_W-XW){x[XW-1]}}, x};
wire signed [DQ_W-1:0] x_menos_min = x_s - min_q_s;     // x - min_q
wire signed [DQ_W-1:0] max_menos_x = max_q_s - x_s;     // max_q - x
// Activo: una suma sobre la sombra, y el signo.
wire signed [DQ_W-1:0] dmin_spec = val_i ? d_min + xc_s : d_min;
wire signed [DQ_W-1:0] dmax_spec = val_i ? d_max - xc_s : d_max;

wire ge_min_spec = !en_activo ? (min_cero || !x_menos_min[DQ_W-1])
                              : !dmin_spec[DQ_W-1];
wire le_max_spec = !en_activo ? !max_menos_x[DQ_W-1]
                              : !dmax_spec[DQ_W-1];

always @(posedge clk_i) begin
  if (!rstn_i) begin
    min_q <= {QW{1'b0}}; max_q <= {QW{1'b1}}; min_fuera <= 1'b0; min_cero <= 1'b1;
    sat_ok <= 1'b1; d_min <= {DQ_W{1'b0}}; d_max <= {DQ_W{1'b0}};
    ge_min_r <= 1'b0; le_max_r <= 1'b0; peak_ok_r <= 1'b0;
  end else begin
    min_fuera <= |min_q_w[QX_W-1:QW];
    min_q     <= min_q_w[QW-1:0];
    min_cero  <= (min_q_w == {QX_W{1'b0}});
    // Si (max+1)<<s desborda QW, todo q_tot cumple: tope en todo unos.
    max_q     <= (|max_q_w[QX_W-1:QW]) ? {QW{1'b1}} : (max_q_w[QW-1:0] - {{(QW-1){1'b0}}, 1'b1});
    sat_ok    <= (cfg_amp_max_i == {AMP_W{1'b1}});

    d_min     <= d_min_d;
    d_max     <= d_max_d;

    ge_min_r  <= !min_fuera && ge_min_spec;
    le_max_r  <= le_max_spec;
    peak_ok_r <= peak_ok_spec;
  end
end

wire amp_ok = cfg_amp_src_i ? (ge_min_r && (le_max_r || sat_ok)) : peak_ok_r;

// El divisor exige q_tail < q_tot y q_tot != 0. Se verifica ACÁ, no se confía
// en la invariante: el clamp de xc la protege, pero un q_tot=0 (pulso de ruido)
// haría que el cociente saliera todo unos, o sea todos esos eventos al bin
// superior del eje de forma.
wire psd_inputs_ok = (q_tot != {QW{1'b0}}) && (q_tail < q_tot);

//-----------------------------------------------------------------------------
// Los DOS divisores de forma, en paralelo
//
// (1) PSD = Q_cola/Q_total — comparacion de carga (Brooks 1959; Knoll cap. 17).
//     Mide DONDE esta la carga: el peso de la componente lenta.
// (2) INVW = Pico/Q_total  — el ancho inverso. Mide CUANTA carga hay por unidad
//     de altura, o sea el ancho efectivo del pulso.
//
// Son ejes de forma INDEPENDIENTES: dos pulsos del mismo ancho pero distinto
// balance cabeza/cola dan el mismo INVW y distinto PSD. Y el segundo es el que
// sirve para rechazar apilamiento — medido por Monte-Carlo sobre el espectro de
// una linea a 100 kcps, PSD rechaza el 29.6 % de los apilados en modo histeresis
// y EXACTAMENTE NADA en modo compuerta, mientras que el ancho rechaza el 99.1 %.
// Ver software/monte-carlo/.
//
// Por que INVW = P/Q y no Q/P: el divisor restaurador exige num < den, y Q/P > 1
// no entra. P/Q si, porque q_tot = sum(xc) >= max(xc) = peak SIEMPRE. Es la misma
// informacion, monotona decreciente en vez de creciente.
//
// Corren EN PARALELO: los dos arrancan al cerrar y terminan juntos, asi que el
// segundo no agrega ni un ciclo de tiempo muerto. Cuestan cero DSP.
//
// DIV_W = 16 bits de cociente (antes 6). Con 6 bits el ancho inverso no tenia
// rango: los valores utiles de Q/P van de ~250 (limpio) a ~1200 (apilado), o sea
// P/Q en [0.0008, 0.004], que con 6 bits se cuantiza a CERO. Con 16 bits caen en
// [52, 262], que si separa las poblaciones.
//
// El eje del mapa 2D sigue teniendo PSD_AW bits: se toman los PSD_AW bits ALTOS
// del cociente. Eso es BIT-EXACTO respecto del comportamiento anterior, porque
// floor(floor(a*2^16/b)/2^10) == floor(a*2^6/b) para enteros positivos. O sea que
// ampliar el divisor no cambia ni un evento del mapa 2D ya caracterizado.
//-----------------------------------------------------------------------------
reg              div_start;
reg  [QW-1:0]    div_num, div_den, div2_num;
wire [DIV_W-1:0] div_q, div2_q;
wire             div_valid, div_err, div_sat, div_busy;
wire             div2_valid, div2_err, div2_sat;

generate if (EN_PSD) begin : g_div
  mca_div_restore #(.D_W(QW), .Q_W(DIV_W)) i_div (
    .clk_i(clk_i), .rstn_i(rstn_i),
    .start_i(div_start), .num_i(div_num), .den_i(div_den),
    .q_o(div_q), .valid_o(div_valid), .err_o(div_err), .sat_o(div_sat),
    .busy_o(div_busy)
  );
  // Mismo denominador, mismo arranque, misma latencia: no hace falta mirar su
  // valid_o, alcanza con el del primero.
  mca_div_restore #(.D_W(QW), .Q_W(DIV_W)) i_div_w (
    .clk_i(clk_i), .rstn_i(rstn_i),
    .start_i(div_start), .num_i(div2_num), .den_i(div_den),
    .q_o(div2_q), .valid_o(div2_valid), .err_o(div2_err), .sat_o(div2_sat),
    .busy_o()
  );
end else begin : g_nodiv
  assign div_q      = {DIV_W{1'b0}};
  assign div_valid  = 1'b0;
  assign div_err    = 1'b0;
  assign div_sat    = 1'b0;
  assign div_busy   = 1'b0;
  assign div2_q     = {DIV_W{1'b0}};
  assign div2_valid = 1'b0;
  assign div2_err   = 1'b0;
  assign div2_sat   = 1'b0;
end endgenerate

assign busy_o = (st != S_IDLE);

//-----------------------------------------------------------------------------
// TIEMPO MUERTO: los casilleros, y por que no alcanza con busy_o
//-----------------------------------------------------------------------------
// busy_o = (st != S_IDLE) cuenta la ventana y los divisores, pero NO el lapso
// en que el modulo esta en S_IDLE y todavia no se re-armo. Y ese lapso es el
// grande: medido sobre esta misma FSM (docs/mca/figuras/tiempo_muerto/,
// figuras_trigger.py), modo compuerta con gate_long = 384, el bloqueo real es
// 11.0 % a 20 kcps contra 5.5 % que informaba el contador, y 85.7 % a 318 kcps
// contra 14.0 %. Peor: lo contado NO ES MONOTONO —pasa por un maximo cerca de
// 126 kcps y despues baja— porque a tasa alta casi no se abren ventanas. Un
// tiempo muerto informado que baja al subir la tasa no corrige nada.
//
// Los casilleros son disjuntos por construccion y su union es exactamente "no
// puede abrir", asi que mca_top puede teselar realtime con ellos sin sobrantes
// ni solapes. El termino `disparo` NO entra: eso es el ARRIBO, no la capacidad
// de registrarlo.
//
// La particion, explicita:
//
//   st == S_ACTIVE                            -> dt_win    (ventana abierta)
//   st == S_DIV                               -> dt_div    (modo bloqueante)
//   st == S_IDLE && !armed                    -> dt_rearm  (sin re-armar)
//   st == S_IDLE &&  armed &&  pub_lleno      -> dt_div    (FIFO llena)
//   st == S_IDLE &&  armed && !pub_lleno      -> puede_abrir
//
// Las dos ramas de dt_div son el MISMO casillero a proposito: las dos son
// "bloqueado porque no hay donde publicar el resultado", y conservan el mismo
// registro (0x0D0) para que el modo bloqueante y el modo FIFO se comparen contra
// la misma vara. En el modo 0 la segunda rama nunca se da (la FIFO se vacia
// antes de volver a S_IDLE) y en el modo 1 la primera tampoco (no se entra a
// S_DIV), asi que no se pisan.
//
// EL DESBORDE DE LA FIFO TIENE QUE ESTAR ACA. Si quedara afuera, el tiempo
// muerto oculto que la Fase 1 saco a la luz se habria mudado del Schmitt al
// arbitro en vez de desaparecer, y ap_suma_relojes lo delataria.
assign dt_win_o      = (st == S_ACTIVE);
assign dt_div_o      = (st == S_DIV) || ((st == S_IDLE) && armed && pub_lleno);
assign dt_rearm_o    = (st == S_IDLE) && !armed;
assign puede_abrir_o = (st == S_IDLE) && armed && !pub_lleno;

//-----------------------------------------------------------------------------
// ARRIBOS: cada cruce de thr_hi hacia arriba va a exactamente un casillero
//-----------------------------------------------------------------------------
// El detector de arribos NO puede usar `armed` como lo hacia cnt_lost_busy:
// los pulsos que llegan durante el bloqueo por re-armado tienen armed == 0 POR
// DEFINICION —es justamente lo que los hacia invisibles—, y encima montan sobre
// una cola que puede estar entre thr_lo y thr_hi, asi que cruzan thr_hi sin
// haber pasado nunca por debajo de thr_lo. Hace falta un flanco de thr_hi
// independiente de la histeresis.
//
// Contrapartida honesta: un flanco crudo cuenta tambien las re-cruzadas por
// ruido del MISMO pulso, que es lo que la histeresis existe para evitar. Con
// una histeresis razonable (la campana usa thr=100, hyst=40) el ruido no vuelve
// a cruzar thr_hi y no hay diferencia; con cfg_hyst = 0 este contador
// sobrecuenta. Se elige asi porque `armed` subcuenta exactamente los eventos
// que interesan, y sobrecontar con hyst=0 es un modo de falla visible mientras
// que subcontar es silencioso.
reg  x_alto_q;                                 // thr_hi en la ultima muestra valida
wire x_alto   = (x >= thr_hi);
wire cruce_hi = val_i && x_alto && !x_alto_q && cfg_run_i;

assign arribo_o = cruce_hi;

always @(posedge clk_i)
  if (!rstn_i)   x_alto_q <= 1'b0;
  else if (val_i) x_alto_q <= x_alto;

//-----------------------------------------------------------------------------
// FIFO DE PUBLICACION — el Q_{n-1} por ventana, de 1 lugar a PUB_K
//-----------------------------------------------------------------------------
// Datos del evento retenidos mientras corren los divisores, para que el registro
// que ven los motores sea coherente. `len`, `t_peak` y `peak` se pisan apenas
// llega el pulso SIGUIENTE, asi que hay que congelarlos: sin esto el bus de
// features mezclaria features de dos eventos distintos, que es exactamente el
// modo de falla que el registro unico existe para evitar.
//
// ESTO YA EXISTIA CON PROFUNDIDAD 1 (los hold_* de antes). Llevarlo a PUB_K
// lugares con id de ventana ES el arbitraje del recurso compartido: el divisor
// es uno solo y la ventana es la que lo pide. Con K lugares la ventana cierra,
// deja su resultado y reabre, y el publicador consume a su ritmo.
//
// Se guarda tambien q_tot/q_tail porque una entrada que no alcanzo a arrancar
// los divisores los va a necesitar despues (ver `arranque_directo`), y el flag
// psd_ok ya resuelto, para no arrastrar dos comparadores de QW bits hasta el
// publicador.
reg [AMP_W-1:0]   f_amp   [0:PUB_K-1];   // el estimador SELECCIONADO
reg [AMP_W-1:0]   f_aint  [0:PUB_K-1];   // la integral, siempre: su propia ranura
reg [DW-1:0]      f_peak  [0:PUB_K-1];
reg [LEN_W-1:0]   f_len   [0:PUB_K-1];
reg [LEN_W-1:0]   f_tpk   [0:PUB_K-1];
reg [QW-1:0]      f_qtot  [0:PUB_K-1];
reg [QW-1:0]      f_qtail [0:PUB_K-1];
reg [PUB_IDW-1:0] f_id    [0:PUB_K-1];
reg               f_psd_ok[0:PUB_K-1];

// Estado del publicador. Es una FSM aparte de la del extractor: eso es todo el
// desacople.
localparam [0:0] P_IDLE = 1'd0, P_DIV = 1'd1;
reg        pst;
reg [PUB_AW-1:0] pub_cur;        // entrada que esta en los divisores

// El publicador termina en ESTE ciclo. El extractor usa esta senal para salir de
// S_DIV en el modo bloqueante, y no `pub_vacio`, que llegaria un ciclo tarde y
// alargaria S_DIV de 17 a 18 ciclos — rompiendo la identidad
// deadtime_cnt == t_win + t_div de la Fase 1 por un ciclo por evento.
wire pub_done = (pst == P_DIV) && div_valid;

// ARRANQUE DIRECTO. Si al cerrar el publicador esta libre, los divisores
// arrancan en ESE mismo flanco desde los registros vivos (q_tot/q_tail/peak),
// exactamente como antes de la FIFO. Solo las entradas que encuentran el
// publicador ocupado —que en el modo bloqueante no existen— esperan su turno y
// se cargan desde la FIFO, con un ciclo mas de latencia.
wire pub_libre = (pst == P_IDLE) && pub_vacio;

// Empuje y extraccion como CABLES, para poder actualizar la ocupacion en un
// solo lugar. Hace falta: en modo FIFO una ventana puede cerrar en el mismo
// flanco en que el publicador termina, y con dos asignaciones separadas a
// pub_occ la segunda ganaria y el empuje se perderia en silencio — una entrada
// escrita que nadie publica nunca.
wire win_acepta = (st == S_ACTIVE) && val_i && close_pulse
                  && !(close_maxl || gate_pileup) && amp_ok;
wire pub_push   = (EN_PSD != 0) && win_acepta;
wire pub_pop    = pub_done;

//-----------------------------------------------------------------------------
// Indices del bus de features. Fijos y compartidos: el selector de eje del
// histograma y el discriminador usan ESTA numeracion, asi que no se pueden
// desincronizar.
//-----------------------------------------------------------------------------
localparam integer F_PEAK  = 0;  // amplitud de pico
localparam integer F_INT   = 1;  // integral de carga (Q_total >> q_shift)
localparam integer F_PSD   = 2;  // Q_cola/Q_total   — donde esta la carga
localparam integer F_INVW  = 3;  // Pico/Q_total     — ancho inverso
localparam integer F_LEN   = 4;  // largo de la ventana, en muestras
localparam integer F_TRISE = 5;  // muestras del disparo al pico
// 6..NFEAT-1 reservadas (meseta del trapecio). Se atan a cero: la sintesis las
// borra enteras, asi que una ranura sin usar no cuesta nada.

// Normalizacion de cada ranura. El contrato del bus es "uint16 con fondo de
// escala 0xFFFF", asi que las features acotadas se alinean a la IZQUIERDA:
// extenderlas con cero dejaria una fraccion de DIV_W bits viviendo en los bits
// BAJOS, y entonces cada eje necesitaria un corrimiento distinto para decir lo
// mismo. Alineadas, un solo corrimiento sirve para todas.
//
// Excepcion honesta: F_INVW, F_LEN y F_TRISE NO se normalizan.
//   - F_LEN/F_TRISE son contadores sin fondo de escala natural (dependen de
//     cfg_gate_long).
//   - F_INVW es una fraccion pero vive cerca de CERO (P/Q ~ 0.001 para un pulso
//     de 250 muestras): alinearla a la izquierda la mandaria toda al bin 0. Su
//     escala depende del ancho del pulso, que es justo lo que mide, asi que el
//     factor no se puede fijar en tiempo de compilacion.
// Las tres se ajustan con el corrimiento del eje, y esto esta documentado en el
// mapa de registros para que no sorprenda.
function automatic [AMP_W-1:0] feat_izq(input [DIV_W-1:0] q);
  feat_izq = (AMP_W >= DIV_W) ? {q, {(AMP_W-DIV_W){1'b0}}}
                              : q[DIV_W-1 -: AMP_W];
endfunction

//-----------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (!rstn_i) begin
    st <= S_IDLE; armed <= 1'b0;
    gate_rearm <= 1'b0; gate_2nd <= 1'b0;
    len <= {LEN_W{1'b0}}; t_peak <= {LEN_W{1'b0}}; peak <= {DW{1'b0}};
    q_tot <= {QW{1'b0}}; q_tail <= {QW{1'b0}};
    bl_acc <= {BL_ACC_W{1'b0}}; bl_hold <= {LEN_W{1'b0}};
    div_start <= 1'b0; div_num <= {QW{1'b0}}; div_den <= {QW{1'b0}};
    div2_num <= {QW{1'b0}};
    // Los lugares de la FIFO no se inicializan: no se leen hasta haberse
    // escrito, y ponerlos en cero costaria PUB_K juegos de flops con reset.
    // Lo que SI tiene que arrancar en cero es el control.
    pst <= P_IDLE; pub_wr <= {PUB_AW{1'b0}}; pub_rd <= {PUB_AW{1'b0}};
    pub_occ <= {(PUB_AW+1){1'b0}}; pub_cur <= {PUB_AW{1'b0}};
    pub_occ_max_o <= {(PUB_AW+1){1'b0}};
    win_id <= {PUB_IDW{1'b0}}; last_win_id_o <= {PUB_IDW{1'b0}};
    rearm_cnt <= {LEN_W{1'b0}}; cnt_trig_o <= 32'h0;
    ev_valid_o <= 1'b0; ev_amp_o <= {AMP_W{1'b0}};
    ev_psd_o <= {PSD_AW{1'b0}}; ev_psd_ok_o <= 1'b0;
    ev_feat_o <= {(NFEAT*AMP_W){1'b0}};
    baseline_stale_o <= 1'b0;
    cnt_total_o <= 32'h0; cnt_accepted_o <= 32'h0; cnt_rej_amp_o <= 32'h0;
    cnt_rej_psd_o <= 32'h0; cnt_pileup_o <= 32'h0; cnt_lost_busy_o <= 32'h0;
    cnt_cross_o <= 32'h0; cnt_open_o <= 32'h0; cnt_lost_rearm_o <= 32'h0;
    cnt_lost_active_o <= 32'h0; cnt_lost_veto_o <= 32'h0;
    cnt_lost_notrig_o <= 32'h0; cnt_win_o <= 32'h0;
    last_qtot_o <= {QW{1'b0}}; last_qtail_o <= {QW{1'b0}};
  end else begin
    ev_valid_o <= 1'b0;
    div_start  <= 1'b0;

    // Operandos del divisor: se cargan TODOS los ciclos. Es exactamente
    // equivalente a cargarlos solo al cerrar (en ese ciclo q_tot/q_tail ya
    // tienen su valor final, porque la ultima acumulacion ocurrio en el flanco
    // anterior), pero evita un clock enable derivado de toda la decision de
    // cierre: ese CE era el ultimo camino en falla del diseno (-0.096 ns).
    // El divisor engancha sus operandos al ver div_start, asi que cargarlos de
    // mas no cambia nada.
    //
    // LA FUENTE ES LA VENTANA VIVA salvo que haya cola en la FIFO. Con la FIFO
    // vacia (el caso del modo bloqueante y el caso normal del modo FIFO) esto es
    // literalmente lo de antes: q_tot/q_tail/peak del cierre. Solo cuando una
    // entrada quedo esperando turno los operandos salen de su lugar de la FIFO.
    if (pub_vacio) begin
      div_num  <= q_tail;
      div_den  <= q_tot;
      div2_num <= {{(QW-DW){1'b0}}, peak};   // ancho inverso: P/Q
    end else begin
      div_num  <= f_qtail[pub_rd];
      div_den  <= f_qtot [pub_rd];
      div2_num <= {{(QW-DW){1'b0}}, f_peak[pub_rd]};
    end

    //--- trigger externo: solo el contador de diagnostico -------------------
    // La apertura la decide `disparo` (ver "APERTURA"); esto es para poder
    // distinguir "no llego el trigger" de "llego y no abrio".
    if (trig_edge) cnt_trig_o <= cnt_trig_o + 32'h1;

    // q_tot y peak se escriben desde sus cables de valor siguiente, todos los
    // ciclos: la FSM decide QUE vale q_tot_d/peak_d (abrir, acumular, sostener),
    // no cuando se escribe. Asi el mismo cable alimenta el comparador de
    // ventana registrado. Ver "Ventana de amplitud".
    q_tot <= q_tot_d;
    peak  <= peak_d;

    //--- seguidor de línea de base: sólo en reposo y fuera del holdoff -------
    // Ojo con `!open_pulse`: en el flanco en que se abre el pulso, `st` TODAVÍA
    // vale S_IDLE (la transición se registra en este mismo flanco). Sin esa
    // condición el IIR se come la primera muestra del flanco de subida de CADA
    // pulso, y a tasa alta eso arrastra la base hacia arriba de forma
    // sistemática: corre el centroide de todo el espectro.
    if (val_i) begin
      if (st == S_IDLE && !open_pulse && bl_hold == {LEN_W{1'b0}}) begin
        bl_acc <= bl_acc + $signed({{(BL_ACC_W-DW){dat_i[DW-1]}}, dat_i})
                         - bl_acc_shr;
        baseline_stale_o <= 1'b0;
      end else if (bl_hold != {LEN_W{1'b0}}) begin
        bl_hold <= bl_hold - {{(LEN_W-1){1'b0}}, 1'b1};
      end
    end

    //--- re-armado: por NIVEL o por CONTADOR --------------------------------
    // Las dos ramas son excluyentes y cada una gobierna `armed` entera, para que
    // no haya que razonar prioridades entre ellas. El `armed <= 1'b0` del case
    // gana sobre las dos al abrir un pulso, porque viene despues.
    if (!cfg_rearm_mode_i) begin
      //--- NIVEL (histeresis) — el comportamiento historico ---
      // Independiente del estado a propósito. Si sólo se armara en S_IDLE, una
      // señal que vuelve a la base mientras corre el divisor (16 ciclos) y sube
      // otra vez dejaría el pulso siguiente sin detectar, en silencio.
      if (val_i && (x < thr_lo)) armed <= 1'b1;

      // ...pero si la señal cruza el umbral mientras el módulo está OCUPADO, se
      // desarma. Si no, al liberarse el divisor abriría a mitad del pulso ya en
      // curso y mediría una amplitud truncada: eso metería una cola espuria de
      // baja energía en el espectro. Es preferible perder el pulso entero y
      // contarlo en cnt_lost_busy, que es un tiempo muerto medible y corregible.
      // Lo mismo bajo VETO: un pulso que sube con el veto puesto no se abre al
      // liberarlo -- se vuelve a armar recien por debajo de thr_lo. Ese no se
      // cuenta como perdido: vetarlo es lo que se pidio.
      if (val_i && ((st != S_IDLE) || veto_i) && (x >= thr_hi)) armed <= 1'b0;
    end else begin
      //--- CONTADOR (holdoff) — tau determinista ---
      // El contador se carga al cerrar la ventana y corre sin mirar la senal:
      // eso es lo que hace al modulo NO PARALIZABLE, porque un pulso que llega
      // durante el holdoff ya no lo extiende. tau = ventana + cfg_rearm_dly,
      // exacto y conocido, en vez de depender de donde cruza la cola.
      //
      // Dos consecuencias que hay que tener presentes:
      //  - Se puede reabrir con la senal TODAVIA ARRIBA de thr_lo, o sea a mitad
      //    de la cola del pulso anterior. Eso es justamente la sobre-cuenta de
      //    la figura 6: el apilamiento se trocea en pedazos del largo de la
      //    compuerta. Se filtra por FORMA (F_INVW/F_LEN), no volviendo al nivel.
      //  - El veto ya no desarma. No hace falta: `open_pulse` exige !veto_i, asi
      //    que durante el veto no se abre; al liberarse se abre en el disparo
      //    siguiente, que con holdoff vencido es inmediato.
      if (val_i && (st == S_IDLE)) begin
        if (rearm_cnt != {LEN_W{1'b0}}) rearm_cnt <= rearm_cnt - {{(LEN_W-1){1'b0}}, 1'b1};
        else                            armed     <= 1'b1;
      end
    end

    //--- atribucion de arribos ----------------------------------------------
    // La cadena if/else-if hace la particion explicita: exactamente un casillero
    // por cruce, y la rama final ES open_pulse (cruce con st==S_IDLE, armed,
    // !veto y cfg_run son las cinco condiciones de open_pulse mas val_i, que
    // cruce_hi ya trae). Por eso la invariante
    //   cnt_cross == cnt_open + lost_rearm + lost_active + lost_busy + lost_veto
    // vale en TODO ciclo, y esta como assertion en sim/sva/mca_top_sva.sv.
    //
    // El orden importa: el veto gana sobre el estado, igual que en los relojes
    // de mca_top. Un pulso que sube con el veto puesto se pierde porque se pidio
    // que se perdiera, y no tiene que contaminar el tiempo muerto del modulo.
    //
    // FASE 2, dos cambios:
    //
    //  - `pub_lleno` entra en la MISMA rama que S_DIV, no en una nueva. Las dos
    //    son "se perdio porque no habia donde publicar", y cnt_lost_busy ya se
    //    llama asi.
    //  - `!disparo` es un casillero NUEVO y hace falta: con apertura por trigger
    //    externo un cruce puede encontrar al modulo perfectamente libre y no
    //    abrir, simplemente porque no vino el trigger. Sin este casillero la
    //    invariante se rompe ahi, y lo que es peor, se rompe en silencio. En modo
    //    interno `cruce_hi` implica `disparo_int`, asi que esta rama no se toma
    //    nunca y los numeros de la Fase 1 quedan iguales.
    if (cruce_hi) begin
      cnt_cross_o <= cnt_cross_o + 32'h1;
      if      (veto_i)         cnt_lost_veto_o   <= cnt_lost_veto_o   + 32'h1;
      else if (st == S_ACTIVE) cnt_lost_active_o <= cnt_lost_active_o + 32'h1;
      else if (st == S_DIV)    cnt_lost_busy_o   <= cnt_lost_busy_o   + 32'h1;
      else if (!armed)         cnt_lost_rearm_o  <= cnt_lost_rearm_o  + 32'h1;
      else if (pub_lleno)      cnt_lost_busy_o   <= cnt_lost_busy_o   + 32'h1;
      else if (!disparo)       cnt_lost_notrig_o <= cnt_lost_notrig_o + 32'h1;
      else                     cnt_open_o        <= cnt_open_o        + 32'h1;
    end

    //--- FSM ----------------------------------------------------------------
    case (st)
      //---------------------------------------------------------------------
      S_IDLE: begin
        if (val_i && open_pulse) begin
          st     <= S_ACTIVE;
          armed  <= 1'b0;
          len    <= {{(LEN_W-1){1'b0}}, 1'b1};
          t_peak <= {LEN_W{1'b0}};
          gate_rearm <= 1'b0; gate_2nd <= 1'b0;
          // peak <= xc y q_tot <= xc los hacen peak_d/q_tot_d
          q_tail <= {QW{1'b0}};
          // Id de la ventana. Viaja con el resultado por la FIFO, asi que el
          // evento publicado se puede atar a la ventana que lo produjo aunque la
          // publicacion este desacoplada del cierre. Su utilidad concreta: un
          // salto en la secuencia de ids publicados delata un resultado perdido,
          // que de otro modo seria indistinguible de un pulso que nunca llego.
          win_id    <= win_id + {{(PUB_IDW-1){1'b0}}, 1'b1};
          cnt_win_o <= cnt_win_o + 32'h1;
        end
      end

      //---------------------------------------------------------------------
      S_ACTIVE: begin
        if (val_i) begin
          if (close_pulse) begin
            cnt_total_o <= cnt_total_o + 32'h1;
            last_qtot_o  <= q_tot;
            last_qtail_o <= q_tail;
            bl_hold      <= cfg_bl_holdoff_i;
            // Holdoff de re-armado (modo contador). Se carga en los TRES
            // caminos de cierre —apilado, rechazado por amplitud y aceptado—
            // porque tau es una propiedad de la ventana y no de si el evento
            // sirvio. Si solo se cargara al aceptar, un rechazo por amplitud
            // dejaria el contador en cero y el modulo reabriria al instante:
            // tau dejaria de ser determinista justo con los pulsos de ruido,
            // que son los mas frecuentes.
            rearm_cnt    <= cfg_rearm_dly_i;

            if (close_maxl || gate_pileup) begin
              // Apilamiento: el pulso está contaminado, se cuenta y se tira.
              // En modo compuerta lo delata que la señal siga alta al cerrar.
              cnt_pileup_o <= cnt_pileup_o + 32'h1;
              st <= S_IDLE;
            end else if (!amp_ok) begin
              cnt_rej_amp_o <= cnt_rej_amp_o + 32'h1;
              st <= S_IDLE;
            end else begin
              if (EN_PSD != 0) begin
                // Se EMPUJA el resultado a la FIFO: todas las features que el
                // pulso siguiente podria pisar, mas el id de la ventana y el
                // flag de forma ya resuelto.
                //
                // Solo se empuja si hay divisores. Sin ellos nadie saca de la
                // FIFO, asi que empujar la llenaria y el modulo quedaria
                // bloqueado para siempre; en ese caso el evento sale directo
                // desde los registros vivos, como siempre (rama de abajo).
                f_amp   [pub_wr] <= amp_sel;
                f_aint  [pub_wr] <= amp_int;
                f_peak  [pub_wr] <= peak;
                f_len   [pub_wr] <= len;
                f_tpk   [pub_wr] <= t_peak;
                f_qtot  [pub_wr] <= q_tot;
                f_qtail [pub_wr] <= q_tail;
                f_id    [pub_wr] <= win_id;
                f_psd_ok[pub_wr] <= psd_inputs_ok;
                pub_wr  <= (pub_wr == (PUB_K-1)) ? {PUB_AW{1'b0}}
                                                 : (pub_wr + {{(PUB_AW-1){1'b0}}, 1'b1});
                // pub_occ NO se toca aca: se actualiza una sola vez mas abajo,
                // desde pub_push/pub_pop.

                // ARRANQUE DIRECTO: con el publicador libre los divisores
                // arrancan en ESTE flanco y toman los registros vivos (el `if
                // (pub_vacio)` de la carga de operandos de mas arriba todavia ve
                // la FIFO vacia). Es lo que mantiene S_DIV en 17 ciclos exactos.
                if (pub_libre) begin
                  div_start <= 1'b1;
                  pst       <= P_DIV;
                  pub_cur   <= pub_wr;
                end
                // MODO BLOQUEANTE: la ventana no reabre hasta publicar. Con esto
                // `feat_busy` cubre exactamente lo mismo que antes de la FIFO.
                // MODO FIFO: se vuelve a S_IDLE y la ventana queda libre; el
                // bloqueo, si lo hay, lo pone `pub_lleno` via dt_div_o.
                st <= cfg_pub_mode_i ? S_IDLE : S_DIV;
              end else begin
                // Sin motor de forma: el evento sale directo, con las ranuras
                // de forma en cero.
                cnt_accepted_o <= cnt_accepted_o + 32'h1;
                ev_amp_o    <= amp_sel;
                ev_psd_o    <= {PSD_AW{1'b0}};
                ev_psd_ok_o <= 1'b0;
                ev_feat_o   <= {(NFEAT*AMP_W){1'b0}};
                ev_feat_o[F_PEAK *AMP_W +: AMP_W] <= {peak, {(AMP_W-DW){1'b0}}};
                ev_feat_o[F_INT  *AMP_W +: AMP_W] <= amp_int;
                ev_feat_o[F_LEN  *AMP_W +: AMP_W] <= len;
                ev_feat_o[F_TRISE*AMP_W +: AMP_W] <= t_peak;
                ev_valid_o  <= 1'b1;
                st <= S_IDLE;
              end
            end
          end else begin
            len   <= len + {{(LEN_W-1){1'b0}}, 1'b1};
            // Deteccion del 2do pulso para el modo compuerta: primero la senal
            // tiene que BAJAR de thr_lo (gate_rearm) y recien despues volver a
            // cruzar thr_hi. Sin el paso intermedio se disparia con la propia
            // subida del pulso en curso.
            if (x < thr_lo)                  gate_rearm <= 1'b1;
            else if (gate_rearm && (x >= thr_hi)) gate_2nd <= 1'b1;
            // q_tot += xc y peak = max(peak, xc) los hacen q_tot_d/peak_d
            // (`acumula` es exactamente esta rama).
            if (in_tail) q_tail <= q_tail + {{(QW-DW){1'b0}}, xc};
            if (nuevo_pico) t_peak <= len;
          end
        end else begin
          // Sin muestras válidas el pulso no puede cerrarse por histéresis;
          // el watchdog de línea de base avisa si esto se vuelve permanente.
          if (len >= cfg_maxlen_i) baseline_stale_o <= 1'b1;
        end
      end

      //---------------------------------------------------------------------
      S_DIV: begin
        // MODO BLOQUEANTE unicamente: se espera a que el publicador termine.
        // Un pulso nuevo mientras el divisor trabaja se pierde: lo cuenta la
        // atribucion de arribos de mas arriba, en cnt_lost_busy.
        //
        // CAMBIO DE DEFINICION respecto de la version anterior, que incrementaba
        // aca con `val_i && (x >= thr_hi) && armed`. Exigir `armed` subcontaba:
        // si dentro de S_DIV la senal bajaba de thr_hi pero no de thr_lo y volvia
        // a subir, ese segundo pulso no se contaba en ninguna parte. El flanco de
        // cruce_hi lo cuenta. Los dos criterios coinciden en el caso frecuente
        // (pulso que llega desde el reposo), asi que la diferencia numerica es
        // chica, pero deja de haber un agujero.
        //
        // Se sale con `pub_done` (combinacional) y NO con `pub_vacio`
        // (registrado): pub_vacio llegaria un ciclo tarde y S_DIV pasaria de 17 a
        // 18 ciclos, rompiendo por un ciclo por evento la identidad
        // deadtime_cnt == t_win + t_div que la Fase 1 dejo probada.
        if (pub_done) st <= S_IDLE;
      end

      default: st <= S_IDLE;
    endcase

    //-----------------------------------------------------------------------
    // EL PUBLICADOR — el arbitro del recurso compartido
    //-----------------------------------------------------------------------
    // Corre en paralelo a la FSM de ventana y es lo unico que toca los
    // divisores y las salidas de evento. Que sea una FSM aparte ES el desacople:
    // en modo FIFO la ventana ya cerro y puede haber reabierto mientras esto
    // publica la anterior.
    //
    // Va DESPUES del case a proposito: `pst <= P_DIV` del arranque directo (en el
    // cierre) tiene que ganar sobre el arranque por cola de aca, porque los dos
    // podrian querer disparar en el mismo flanco y el directo es el que ya cargo
    // los operandos desde los registros vivos.
    if (EN_PSD != 0) begin
      case (pst)
        P_IDLE: begin
          // Hay algo en cola que todavia no arranco (solo ocurre en modo FIFO:
          // la entrada encontro el publicador ocupado al cerrar). No puede
          // chocar con el arranque directo: ese exige pub_vacio y este !pub_vacio.
          if (!pub_vacio) begin
            div_start <= 1'b1;
            pst       <= P_DIV;
            pub_cur   <= pub_rd;
          end
        end

        P_DIV: if (div_valid) begin
          ev_amp_o <= f_amp[pub_cur];

          // --- bus de features: se arma ACA, no al cerrar ------------------
          // Es el unico instante en que TODAS las ranuras son del mismo evento:
          // pico, largo y tiempo de subida valen desde el cierre (guardados en
          // el lugar de la FIFO), y los dos cocientes recien ahora.
          ev_feat_o <= {(NFEAT*AMP_W){1'b0}};
          ev_feat_o[F_PEAK *AMP_W +: AMP_W] <= {f_peak[pub_cur], {(AMP_W-DW){1'b0}}};
          ev_feat_o[F_INT  *AMP_W +: AMP_W] <= f_aint[pub_cur];
          ev_feat_o[F_LEN  *AMP_W +: AMP_W] <= f_len [pub_cur];
          ev_feat_o[F_TRISE*AMP_W +: AMP_W] <= f_tpk [pub_cur];
          // El ancho inverso NO se alinea a la izquierda (ver feat_izq): vive
          // cerca de cero y su escala depende del ancho del pulso.
          ev_feat_o[F_INVW *AMP_W +: AMP_W] <=
              div2_sat ? {AMP_W{1'b1}} : {{(AMP_W-DIV_W){1'b0}}, div2_q};

          if (div_err || div_sat || !f_psd_ok[pub_cur]) begin
            // El evento sigue siendo bueno en amplitud: entra al espectro 1D,
            // pero no al mapa 2D. La ranura de forma queda en cero.
            cnt_rej_psd_o  <= cnt_rej_psd_o + 32'h1;
            cnt_accepted_o <= cnt_accepted_o + 32'h1;
            ev_psd_o    <= {PSD_AW{1'b0}};
            ev_psd_ok_o <= 1'b0;
          end else begin
            cnt_accepted_o <= cnt_accepted_o + 32'h1;
            // El eje del mapa 2D toma los PSD_AW bits ALTOS del cociente de
            // DIV_W. Es BIT-EXACTO respecto de un divisor de PSD_AW bits:
            // floor(floor(a*2^DIV_W/b) / 2^(DIV_W-PSD_AW)) == floor(a*2^PSD_AW/b).
            ev_psd_o    <= div_q[DIV_W-1 -: PSD_AW];
            ev_psd_ok_o <= 1'b1;
            ev_feat_o[F_PSD*AMP_W +: AMP_W] <= feat_izq(div_q);
          end
          ev_valid_o    <= 1'b1;
          last_win_id_o <= f_id[pub_cur];

          // Se libera el lugar y se vuelve a reposo. Si quedo otra entrada
          // encolada, P_IDLE la va a arrancar en el ciclo siguiente.
          pub_rd  <= (pub_rd == (PUB_K-1)) ? {PUB_AW{1'b0}}
                                           : (pub_rd + {{(PUB_AW-1){1'b0}}, 1'b1});
          // pub_occ NO se toca aca tampoco: ver la actualizacion unica de abajo.
          pst     <= P_IDLE;
        end

        default: pst <= P_IDLE;
      endcase
    end

    //--- ocupacion de la FIFO: UNA sola actualizacion -----------------------
    // Empuje y extraccion simultaneos se cancelan, que es lo correcto y lo que
    // dos asignaciones separadas no habrian hecho.
    if      (pub_push && !pub_pop) pub_occ <= pub_occ + {{PUB_AW{1'b0}}, 1'b1};
    else if (!pub_push && pub_pop) pub_occ <= pub_occ - {{PUB_AW{1'b0}}, 1'b1};

    // Marca de agua de la ocupacion. Es EL dato que dice si PUB_K alcanza: si
    // llega a PUB_K hubo contrapresion, y lo que se perdio por eso esta en
    // cnt_lost_busy.
    if (pub_occ > pub_occ_max_o) pub_occ_max_o <= pub_occ;

    if (!cfg_run_i && st == S_IDLE) armed <= 1'b0;

    //--- borrado de contadores (va último: gana sobre los incrementos de
    //    este mismo ciclo, así el conteo arranca limpio) ----------------------
    if (cnt_clr_i) begin
      cnt_total_o     <= 32'h0;
      cnt_accepted_o  <= 32'h0;
      cnt_rej_amp_o   <= 32'h0;
      cnt_rej_psd_o   <= 32'h0;
      cnt_pileup_o    <= 32'h0;
      cnt_lost_busy_o <= 32'h0;
      cnt_cross_o       <= 32'h0;
      cnt_open_o        <= 32'h0;
      cnt_lost_rearm_o  <= 32'h0;
      cnt_lost_active_o <= 32'h0;
      cnt_lost_veto_o   <= 32'h0;
      cnt_lost_notrig_o <= 32'h0;
      cnt_win_o         <= 32'h0;
      cnt_trig_o        <= 32'h0;
      // La marca de agua se borra con los contadores: es una estadistica de la
      // corrida, no estado del hardware. La ocupacion EN CURSO no se toca -- hay
      // entradas reales adentro y perderlas colgaria el publicador.
      pub_occ_max_o     <= {(PUB_AW+1){1'b0}};
    end
  end
end

endmodule
