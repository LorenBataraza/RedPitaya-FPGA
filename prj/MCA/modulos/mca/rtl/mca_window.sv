`timescale 1ns/1ps
//=============================================================================
// mca_window — el nucleo: la muestra relativa a la base, el disparo, el
// asignador de ranuras y la contabilidad del tiempo muerto
//
// QUIEN ABRE: solo el TRIGGER EXTERNO (trig_i, el trigger_event del
// multitrigger, con su disparo por pendiente). El Schmitt interno se saco: no
// puede ver un pulso montado sobre la cola de otro, porque la senal nunca baja
// del umbral entre los dos, y ver esos pulsos es para lo que estan las ranuras.
// La latencia del trigger la compensa la linea de retardo de mca_top
// (mca_delay): la muestra que llega aca ya esta retrasada, y la ventana abre en
// el pie del pulso.
//
// N_ACC RANURAS (mca_slot), cada una un juego entero de acumuladores. Un disparo
// abre la ranura libre de menor indice; si no hay, el pulso se pierde y se
// cuenta. Con cfg_n_acc = 1 es la arquitectura de una sola ventana con
// publicacion bloqueante; con mas, el modulo mide pulsos que se solapan, y la
// perdida pasa de ser de primer orden en la tasa (~rho) a ~rho^N/N!, el modelo
// M/D/N/N de Erlang. Lo que una ranura mide sobre otro pulso viene contaminado:
// no se corrige aca, se MARCA (ver mca_slot, "marcas de solape").
//
// QUIEN CIERRA: solo la compuerta fija, cfg_gate_long muestras desde el disparo,
// con la cola desde cfg_gate_short. La histeresis no tiene sentido con ventanas
// solapadas: el cruce de bajada es de la senal sumada y las cerraria juntas.
//
// LA MUESTRA SE REGISTRA ANTES DE REPARTIRSE. x = dat - base es el comienzo del
// camino de datos, y el sintetizador no aplana jerarquia: una frontera es
// gratis solo si lo que cruza sale de un registro. Por eso xc_q es un flop, y
// todo lo que el asignador decide para la muestra n (abrir, que ranura, las
// marcas) se registra junto con ella y llega a las ranuras en el mismo ciclo.
// Ese ciclo de latencia lo absorbe la linea de retardo.
//
// RESERVA. La ranura elegida para la muestra n recien pasa a ABIERTA en el
// flanco de n+1, asi que en el ciclo n+1 todavia figura libre. `reserva_q` la
// marca ocupada ese ciclo; sin eso un disparo en la muestra siguiente elegiria
// la misma ranura.
//
// EL BANCO DE TRAPECIOS: N_FORMAS mca_trap corren sobre la misma muestra
// registrada, CON signo, cada uno con su forma (k, l) y su escala (sh), y el M
// y el clr en comun. Su salida es comun a todas las ranuras: cada una la suma
// sobre su propia ventana, una por forma, y el publicador elige despues cual
// publica (ver mca_publish). Como el trapecio llega TRAP_LAT muestras tarde, la
// ventana que se le pasa a las ranuras ya esta corrida por esa latencia: el off
// de cada forma se cuenta en muestras del trapecio desde la apertura, como si
// no hubiera latencia.
//=============================================================================

module mca_window #(
  parameter integer DW      = 14,  // ancho de muestra (con signo)
  parameter integer QW      = 32,  // ancho de los acumuladores de carga
  parameter integer AMP_W   = 16,  // ancho de la amplitud emitida
  parameter integer LEN_W   = 16,  // ancho de los contadores de longitud
  parameter integer N_ACC   = 4,   // ranuras de medicion
  parameter integer PUB_IDW = 16,  // bits del id de ventana
  parameter integer NW      = 4,   // bits de la marca `otras`
  parameter integer NA_W    = 3,   // bits de cfg_n_acc
  parameter integer N_FORMAS = 4,  // trapecios del banco; 0: sin trapecio (F_TRAP vale cero)
  parameter integer TDAW    = 10,  // log2 de la profundidad de sus lineas de retardo
  parameter integer TMW     = 20,  // bits de su constante polo-cero
  parameter integer TW      = 18,  // salida del trapecio
  parameter integer TNW     = 8,   // bits de la cuenta de la meseta
  // Derivados: los usan los puertos. No se sobreescriben.
  parameter integer OC_W    = $clog2(N_ACC + 1),
  parameter integer TSW     = TW + TNW - 1,
  parameter integer NF      = (N_FORMAS < 1) ? 1 : N_FORMAS   // ancho de los puertos
)(
  input                       clk_i            ,
  input                       rstn_i           ,

  // --- la muestra, ya retrasada por mca_delay ---
  input      signed [DW-1:0]  dat_i            ,
  input                       val_i            ,

  // --- configuracion ---
  input                       cfg_run_i        ,
  input                       veto_i           ,
  input                       cnt_clr_i        ,
  input             [LEN_W-1:0] cfg_gate_short_i,
  input             [LEN_W-1:0] cfg_gate_long_i ,
  input             [AMP_W-1:0] cfg_amp_min_i  ,
  input             [AMP_W-1:0] cfg_amp_max_i  ,
  input                       cfg_amp_src_i    ,
  input             [4:0]     cfg_q_shift_i    ,
  input             [NA_W-1:0] cfg_n_acc_i     ,  // ranuras habilitadas (0 = 1)
  input                       trig_i           ,

  // --- el banco de trapecios: NF formas, aplanadas ---
  input                       trap_clr_i       ,  // reinicia su estado (pulso)
  input             [NF*TDAW-1:0]  cfg_trap_k_i   ,  // subida, >= 1
  input             [NF*TDAW-1:0]  cfg_trap_l_i   ,  // subida + meseta
  input             [TMW-1:0]      cfg_trap_mq_i  ,  // polo-cero, M * 16 (comun)
  input             [NF*6-1:0]     cfg_trap_sh_i  ,
  input             [NF*LEN_W-1:0] cfg_trap_off_i ,  // inicio de la ventana de la meseta
  input             [NF*3-1:0]     cfg_trap_lw_i  ,  // su largo: 2^lw muestras

  // --- linea de base (mca_baseline): entra registrada ---
  input      signed [DW-1:0]  baseline_i       ,
  output                      bl_track_o       ,  // ninguna ventana sobre esta muestra
  output                      cierra_o         ,  // alguna ranura cierra: holdoff
  output                      bl_stale_set_o   ,  // ventana vencida sin muestras

  // --- hacia mca_publish: las N ranuras, aplanadas ---
  output     [N_ACC-1:0]          acepta_o     ,  // cierra aceptada en este ciclo
  output     [N_ACC*AMP_W-1:0]    amp_sel_o    ,
  output     [N_ACC*AMP_W-1:0]    amp_int_o    ,
  output     [N_ACC*DW-1:0]       peak_o       ,
  output     [N_ACC*LEN_W-1:0]    len_o        ,
  output     [N_ACC*LEN_W-1:0]    t_peak_o     ,
  output     [N_ACC*QW-1:0]       q_tot_o      ,
  output     [N_ACC*QW-1:0]       q_tail_o     ,
  output     [N_ACC*PUB_IDW-1:0]  win_id_o     ,
  output     [N_ACC*LEN_W-1:0]    dt_prev_o    ,
  output     [N_ACC*LEN_W-1:0]    dt_next_o    ,
  output     [N_ACC*NW-1:0]       otras_o      ,
  output     [N_ACC-1:0]          adentro_o    ,
  output     [N_ACC-1:0]          perdido_o    ,
  input      [N_ACC-1:0]          libera_i     ,  // el publicador termino con estas
  output     [N_ACC*NF*TSW-1:0]   trap_sum_o   ,  // ranura k, forma f: (k*NF + f)
  output     [N_ACC*NF*TNW-1:0]   trap_n_o     ,

  // --- contadores ---
  output reg [32-1:0]         cnt_total_o      ,  // ventanas cerradas
  output reg [32-1:0]         cnt_rej_amp_o    ,  // ...fuera de [min,max]
  output reg [32-1:0]         cnt_pileup_o     ,  // ...con marca de solape
  output reg [QW-1:0]         last_qtot_o      ,
  output reg [QW-1:0]         last_qtail_o     ,
  output                      busy_o           ,  // alguna ranura ocupada

  // --- casilleros de tiempo muerto ---
  output                      dt_win_o         ,  // sin ranura libre, todas abiertas
  output                      dt_div_o         ,  // sin ranura libre, alguna esperando publicar
  output                      puede_abrir_o    ,
  output     [OC_W-1:0]       n_ocup_o         ,  // ranuras ocupadas ahora

  // --- atribucion de arribos: cada disparo va a UN casillero ---
  output                      arribo_o         ,  // disparo en esta muestra, con run
  output reg [32-1:0]         cnt_cross_o      ,  // todos los arribos
  output reg [32-1:0]         cnt_open_o       ,  // ...que abrieron ranura
  output reg [32-1:0]         cnt_lost_active_o,  // ...sin ranura libre, todas abiertas
  output reg [32-1:0]         cnt_lost_busy_o  ,  // ...sin ranura libre, alguna esperando publicar
  output reg [32-1:0]         cnt_lost_veto_o  ,  // ...bajo veto
  output reg [32-1:0]         cnt_win_o        ,  // ventanas abiertas
  output reg [32-1:0]         cnt_trig_o          // flancos crudos de trig_i
);

localparam integer XW = DW + 1;
localparam integer IW = (N_ACC <= 1) ? 1 : $clog2(N_ACC);

//-----------------------------------------------------------------------------
// Muestra relativa a la base, saturada a >= 0, y REGISTRADA
//-----------------------------------------------------------------------------
// dat_i y baseline son DW bits con signo, asi que x va de -(2^DW-1) a 2^DW-1:
// la parte positiva entra EXACTA en DW bits sin signo.
wire signed [XW-1:0] x  = $signed({dat_i[DW-1], dat_i}) - $signed({baseline_i[DW-1], baseline_i});
wire        [DW-1:0] xc = x[XW-1] ? {DW{1'b0}} : x[DW-1:0];

reg [DW-1:0]          xc_q;
reg signed [XW-1:0]   x_q;              // para el trapecio, que necesita el signo
reg                   val_q;

//-----------------------------------------------------------------------------
// El disparo
//-----------------------------------------------------------------------------
// Por FLANCO y nunca por nivel: un trigger por software dura ~5 ciclos de bus y
// por nivel abriria varias ventanas (event_window_capture.sv:58-64 ya documenta
// ese bug medido en la placa). `trig_pend` lo sostiene hasta la muestra valida
// siguiente, para que la decimacion no se lo coma; un flanco que cae en una
// muestra valida se usa ahi mismo y NO deja pendiente, si no el mismo trigger
// abriria dos ranuras.
reg  trig_q, trig_pend;
wire trig_edge = trig_i && !trig_q;
wire disparo   = val_i && cfg_run_i && (trig_edge || trig_pend);

always @(posedge clk_i)
  if (!rstn_i) begin
    trig_q    <= 1'b0;
    trig_pend <= 1'b0;
  end else begin
    trig_q <= trig_i;
    if      (trig_edge && !val_i) trig_pend <= 1'b1;
    else if (val_i)               trig_pend <= 1'b0;
  end

assign arribo_o = disparo;

//-----------------------------------------------------------------------------
// Las ranuras: su estado, y el asignador
//-----------------------------------------------------------------------------
wire [N_ACC-1:0] s_libre, s_abierta, s_cerrada, s_cierra, s_acepta;
wire [N_ACC-1:0] s_solapada, s_estancada;
reg  [N_ACC-1:0] reserva_q;            // elegida en el ciclo anterior, abre ahora

// Ranuras habilitadas: las cfg_n_acc primeras. 0 se toma como 1 y lo que pasa
// de N_ACC satura: el modulo nunca queda sin ninguna.
wire [NA_W-1:0] n_hab = (cfg_n_acc_i == {NA_W{1'b0}}) ? {{(NA_W-1){1'b0}}, 1'b1}
                      : (cfg_n_acc_i > N_ACC[NA_W-1:0]) ? N_ACC[NA_W-1:0]
                      : cfg_n_acc_i;
wire [N_ACC-1:0] habil;
genvar gk;
generate for (gk = 0; gk < N_ACC; gk = gk + 1) begin : g_habil
  assign habil[gk] = (gk < n_hab);
end endgenerate

wire [N_ACC-1:0] ocupada  = ~s_libre | reserva_q;
wire [N_ACC-1:0] libre_h  = ~ocupada & habil;
wire             puede    = |libre_h;
wire             esperan  = |(s_cerrada & habil);

// La libre de menor indice
reg  [IW-1:0] sel;
integer ks;
always @* begin
  sel = {IW{1'b0}};
  for (ks = N_ACC - 1; ks >= 0; ks = ks - 1)
    if (libre_h[ks]) sel = ks[IW-1:0];
end

wire abre = disparo && !veto_i && puede;

// Cuantas ranuras ABIERTAS hay cuando se decide abrir: la marca `otras`.
// Las cerradas no cuentan: su ventana ya termino y no se solapa con esta.
reg [OC_W-1:0] n_abiertas, n_ocup;
integer ka;
always @* begin
  n_abiertas = {OC_W{1'b0}};
  n_ocup     = {OC_W{1'b0}};
  for (ka = 0; ka < N_ACC; ka = ka + 1) begin
    n_abiertas = n_abiertas + {{(OC_W-1){1'b0}}, (s_abierta[ka] | reserva_q[ka])};
    n_ocup     = n_ocup     + {{(OC_W-1){1'b0}}, ocupada[ka]};
  end
end
assign n_ocup_o = n_ocup;

// Muestras desde el disparo anterior, haya abierto o no. Satura en todo unos,
// que es tambien lo que vale antes del primer disparo.
reg [LEN_W-1:0] desde_disparo;
wire [LEN_W-1:0] desde_mas1 = (desde_disparo == {LEN_W{1'b1}}) ? desde_disparo
                            : desde_disparo + {{(LEN_W-1){1'b0}}, 1'b1};

// La marca satura en NW bits (con N_ACC <= 15 no hace falta, pero no cuesta).
wire [31:0] n_ab32 = {{(32-OC_W){1'b0}}, n_abiertas};

// Lo que el asignador decide para la muestra n, registrado junto con ella
reg [N_ACC-1:0]   abre_q;
reg               disparo_q, perdido_q;
reg [NW-1:0]      otras_q;
reg [LEN_W-1:0]   dt_prev_q;
reg [PUB_IDW-1:0] win_id, win_id_q;

always @(posedge clk_i)
  if (!rstn_i) begin
    xc_q <= {DW{1'b0}}; x_q <= {XW{1'b0}}; val_q <= 1'b0;
    abre_q <= {N_ACC{1'b0}}; reserva_q <= {N_ACC{1'b0}};
    disparo_q <= 1'b0; perdido_q <= 1'b0;
    otras_q <= {NW{1'b0}}; dt_prev_q <= {LEN_W{1'b0}};
    win_id <= {PUB_IDW{1'b0}}; win_id_q <= {PUB_IDW{1'b0}};
    desde_disparo <= {LEN_W{1'b1}};
  end else begin
    xc_q  <= xc;
    x_q   <= x;
    val_q <= val_i;
    abre_q    <= abre ? ({{(N_ACC-1){1'b0}}, 1'b1} << sel) : {N_ACC{1'b0}};
    reserva_q <= abre ? ({{(N_ACC-1){1'b0}}, 1'b1} << sel) : {N_ACC{1'b0}};
    disparo_q <= disparo;
    perdido_q <= disparo && !veto_i && !puede;
    otras_q   <= (n_ab32 > ((1 << NW) - 1)) ? {NW{1'b1}} : n_ab32[NW-1:0];
    if (val_i) begin
      if (disparo) begin
        dt_prev_q     <= desde_mas1;
        desde_disparo <= {LEN_W{1'b0}};
      end else begin
        desde_disparo <= desde_mas1;
      end
    end
    // Id de la ventana. Viaja con el resultado, asi que el evento publicado se
    // puede atar a la ventana que lo produjo: un salto en la secuencia de ids
    // delata un resultado perdido.
    if (abre) begin
      win_id   <= win_id + {{(PUB_IDW-1){1'b0}}, 1'b1};
      win_id_q <= win_id + {{(PUB_IDW-1){1'b0}}, 1'b1};
    end
  end

//-----------------------------------------------------------------------------
// Ventana de amplitud pre-desplazada, una sola vez para todas las ranuras
//-----------------------------------------------------------------------------
localparam integer QX_W = AMP_W + 32;             // (max+1) << 31 sin desbordar

wire [QX_W-1:0] min_q_w = {{(QX_W-AMP_W){1'b0}}, cfg_amp_min_i} << cfg_q_shift_i;
wire [QX_W-1:0] max_q_w = ({{(QX_W-AMP_W){1'b0}}, cfg_amp_max_i} + {{(QX_W-1){1'b0}}, 1'b1})
                          << cfg_q_shift_i;        // (max+1) << s

reg [QW-1:0] min_q, max_q;
reg          min_fuera;     // min << s no entra en QW: ningun q_tot alcanza
reg          sat_ok;        // max == todo unos: la saturacion se acepta

always @(posedge clk_i)
  if (!rstn_i) begin
    min_q <= {QW{1'b0}}; max_q <= {QW{1'b1}};
    min_fuera <= 1'b0; sat_ok <= 1'b1;
  end else begin
    min_fuera <= |min_q_w[QX_W-1:QW];
    min_q     <= min_q_w[QW-1:0];
    // Si (max+1)<<s desborda QW, todo q_tot cumple: tope en todo unos.
    max_q     <= (|max_q_w[QX_W-1:QW]) ? {QW{1'b1}}
                                       : (max_q_w[QW-1:0] - {{(QW-1){1'b0}}, 1'b1});
    sat_ok    <= (cfg_amp_max_i == {AMP_W{1'b1}});
  end

//-----------------------------------------------------------------------------
// El banco de trapecios, y la ventana de cada uno en el marco de las ranuras
//-----------------------------------------------------------------------------
// Con la muestra j de la ventana en la entrada, el trapecio entrega el de la
// muestra j - TRAP_LAT: la ventana [off, off + 2^lw) del trapecio es la
// [off + TRAP_LAT, off + TRAP_LAT + 2^lw) de la ranura. Se calcula una vez por
// forma, registrada, y satura: una ventana que no entra en LEN_W no se alcanza
// nunca, la cuenta no se completa y esa forma no se publica.
localparam integer TRAP_LAT = 8;
wire [NF*TW-1:0]    trap;
reg  [NF*LEN_W-1:0] trap_ini, trap_fin;

genvar gf;
generate for (gf = 0; gf < NF; gf = gf + 1) begin : g_forma
  if (N_FORMAS != 0) begin : g_trap
    wire signed [TW-1:0] t;
    mca_trap #(
      .XW(XW), .DAW(TDAW), .MW(TMW), .TW(TW), .LAT(TRAP_LAT)
    ) i_trap (
      .clk_i(clk_i), .rstn_i(rstn_i), .clr_i(trap_clr_i),
      .x_i(x_q), .val_i(val_q),
      .cfg_k_i(cfg_trap_k_i[gf*TDAW +: TDAW]), .cfg_l_i(cfg_trap_l_i[gf*TDAW +: TDAW]),
      .cfg_mq_i(cfg_trap_mq_i), .cfg_sh_i(cfg_trap_sh_i[gf*6 +: 6]),
      .trap_o(t)
    );
    assign trap[gf*TW +: TW] = t;
  end else begin : g_sin_trap
    assign trap[gf*TW +: TW] = {TW{1'b0}};
  end

  wire [LEN_W:0] t_ini_w = {1'b0, cfg_trap_off_i[gf*LEN_W +: LEN_W]} + TRAP_LAT;
  wire [LEN_W:0] t_fin_w = t_ini_w + ({{LEN_W{1'b0}}, 1'b1} << cfg_trap_lw_i[gf*3 +: 3]);

  always @(posedge clk_i)
    if (!rstn_i) begin
      trap_ini[gf*LEN_W +: LEN_W] <= {LEN_W{1'b1}};
      trap_fin[gf*LEN_W +: LEN_W] <= {LEN_W{1'b1}};
    end else begin
      trap_ini[gf*LEN_W +: LEN_W] <= t_ini_w[LEN_W] ? {LEN_W{1'b1}} : t_ini_w[LEN_W-1:0];
      trap_fin[gf*LEN_W +: LEN_W] <= t_fin_w[LEN_W] ? {LEN_W{1'b1}} : t_fin_w[LEN_W-1:0];
    end
end endgenerate

//-----------------------------------------------------------------------------
// Las N ranuras
//-----------------------------------------------------------------------------
wire [N_ACC*QW-1:0] s_qtot, s_qtail;

generate for (gk = 0; gk < N_ACC; gk = gk + 1) begin : g_slot
  mca_slot #(
    .DW(DW), .QW(QW), .AMP_W(AMP_W), .LEN_W(LEN_W), .PUB_IDW(PUB_IDW), .NW(NW),
    .TW(TW), .TNW(TNW), .NF(NF)
  ) i_slot (
    .clk_i(clk_i), .rstn_i(rstn_i),
    .xc_i(xc_q), .val_i(val_q),
    .abre_i(abre_q[gk]), .disparo_i(disparo_q), .perdido_i(perdido_q),
    .otras_i(otras_q), .dt_prev_i(dt_prev_q), .win_id_i(win_id_q),
    .libera_i(libera_i[gk]),
    .trap_i(trap), .trap_ini_i(trap_ini), .trap_fin_i(trap_fin),
    .cfg_gate_short_i(cfg_gate_short_i), .cfg_gate_long_i(cfg_gate_long_i),
    .cfg_amp_src_i(cfg_amp_src_i), .cfg_q_shift_i(cfg_q_shift_i),
    .cfg_amp_min_i(cfg_amp_min_i), .cfg_amp_max_i(cfg_amp_max_i),
    .min_q_i(min_q), .max_q_i(max_q), .min_fuera_i(min_fuera),
    .sat_ok_i(sat_ok),
    .libre_o(s_libre[gk]), .abierta_o(s_abierta[gk]), .cerrada_o(s_cerrada[gk]),
    .cierra_o(s_cierra[gk]), .acepta_o(s_acepta[gk]),
    .solapada_o(s_solapada[gk]), .estancada_o(s_estancada[gk]),
    .amp_sel_o(amp_sel_o[gk*AMP_W +: AMP_W]), .amp_int_o(amp_int_o[gk*AMP_W +: AMP_W]),
    .peak_o(peak_o[gk*DW +: DW]),
    .len_o(len_o[gk*LEN_W +: LEN_W]), .t_peak_o(t_peak_o[gk*LEN_W +: LEN_W]),
    .q_tot_o(s_qtot[gk*QW +: QW]), .q_tail_o(s_qtail[gk*QW +: QW]),
    .win_id_o(win_id_o[gk*PUB_IDW +: PUB_IDW]),
    .dt_prev_o(dt_prev_o[gk*LEN_W +: LEN_W]), .dt_next_o(dt_next_o[gk*LEN_W +: LEN_W]),
    .otras_o(otras_o[gk*NW +: NW]),
    .adentro_o(adentro_o[gk]), .perdido_o(perdido_o[gk]),
    .trap_sum_o(trap_sum_o[gk*NF*TSW +: NF*TSW]), .trap_n_o(trap_n_o[gk*NF*TNW +: NF*TNW])
  );
end endgenerate

assign q_tot_o  = s_qtot;
assign q_tail_o = s_qtail;
assign acepta_o = s_acepta;

//-----------------------------------------------------------------------------
// TIEMPO MUERTO: los casilleros
//-----------------------------------------------------------------------------
// El modulo NO PUEDE ABRIR exactamente cuando no hay ranura habilitada libre, y
// eso se parte en dos casilleros disjuntos segun la causa:
//
//   sin libre, ninguna esperando publicar   -> dt_win  (todas midiendo)
//   sin libre, alguna esperando publicar    -> dt_div  (el publicador no da abasto)
//   hay alguna libre                        -> puede_abrir
//
// Con una sola ranura son la ventana abierta y S_DIV de la arquitectura de una
// ventana. Ya no hay casillero de re-armado: lo re-arma el multitrigger.
assign dt_win_o      = !puede && !esperan;
assign dt_div_o      = !puede &&  esperan;
assign puede_abrir_o =  puede;
assign busy_o        = |ocupada;

//-----------------------------------------------------------------------------
// Hacia la linea de base
//-----------------------------------------------------------------------------
// Se sigue la base solo con muestras que no son de ninguna ventana: ninguna
// ranura abierta, ninguna reservada y nadie abriendo con ESTA muestra. Sin el
// ultimo termino el IIR se comeria la primera muestra de cada pulso, y a tasa
// alta eso arrastra la base hacia arriba.
assign bl_track_o     = !(|s_abierta) && !(|reserva_q) && !abre;
assign cierra_o       = |s_cierra;
assign bl_stale_set_o = |s_estancada;

//-----------------------------------------------------------------------------
// Contadores
//-----------------------------------------------------------------------------
// Varias ranuras pueden cerrar en el mismo ciclo (con la compuerta cambiada a
// mitad de corrida), asi que los cierres se suman, no se incrementan.
reg [OC_W-1:0] n_cierra, n_rechaza, n_solapa;
reg [IW-1:0]   ult;                        // la de menor indice que cierra
integer kc;
always @* begin
  n_cierra = {OC_W{1'b0}}; n_rechaza = {OC_W{1'b0}}; n_solapa = {OC_W{1'b0}};
  ult = {IW{1'b0}};
  for (kc = N_ACC - 1; kc >= 0; kc = kc - 1) begin
    n_cierra  = n_cierra  + {{(OC_W-1){1'b0}}, s_cierra[kc]};
    n_rechaza = n_rechaza + {{(OC_W-1){1'b0}}, (s_cierra[kc] & ~s_acepta[kc])};
    n_solapa  = n_solapa  + {{(OC_W-1){1'b0}}, (s_cierra[kc] & s_solapada[kc])};
    if (s_cierra[kc]) ult = kc[IW-1:0];
  end
end

always @(posedge clk_i) begin
  if (!rstn_i) begin
    cnt_total_o <= 32'h0; cnt_rej_amp_o <= 32'h0; cnt_pileup_o <= 32'h0;
    last_qtot_o <= {QW{1'b0}}; last_qtail_o <= {QW{1'b0}};
    cnt_cross_o <= 32'h0; cnt_open_o <= 32'h0; cnt_lost_active_o <= 32'h0;
    cnt_lost_busy_o <= 32'h0; cnt_lost_veto_o <= 32'h0;
    cnt_win_o <= 32'h0; cnt_trig_o <= 32'h0;
  end else begin
    if (trig_edge) cnt_trig_o <= cnt_trig_o + 32'h1;

    cnt_total_o   <= cnt_total_o   + {{(32-OC_W){1'b0}}, n_cierra};
    cnt_rej_amp_o <= cnt_rej_amp_o + {{(32-OC_W){1'b0}}, n_rechaza};
    cnt_pileup_o  <= cnt_pileup_o  + {{(32-OC_W){1'b0}}, n_solapa};
    if (|s_cierra) begin
      last_qtot_o  <= s_qtot [ult*QW +: QW];
      last_qtail_o <= s_qtail[ult*QW +: QW];
    end

    //--- atribucion de arribos ----------------------------------------------
    // La cadena if/else-if hace la particion explicita: exactamente un
    // casillero por disparo, y la rama final ES `abre`. Por eso
    //   cnt_cross == cnt_open + lost_active + lost_busy + lost_veto
    // vale en TODO ciclo (assertion en sim/sva/mca_top_sva.sv). El veto gana
    // sobre el estado, igual que en los relojes de mca_top.
    if (disparo) begin
      cnt_cross_o <= cnt_cross_o + 32'h1;
      if      (veto_i)  cnt_lost_veto_o   <= cnt_lost_veto_o   + 32'h1;
      else if (!puede && !esperan) cnt_lost_active_o <= cnt_lost_active_o + 32'h1;
      else if (!puede)  cnt_lost_busy_o   <= cnt_lost_busy_o   + 32'h1;
      else begin
        cnt_open_o <= cnt_open_o + 32'h1;
        cnt_win_o  <= cnt_win_o  + 32'h1;
      end
    end

    //--- borrado de contadores (va ultimo: gana sobre los incrementos de
    //    este mismo ciclo, asi el conteo arranca limpio) ----------------------
    if (cnt_clr_i) begin
      cnt_total_o <= 32'h0; cnt_rej_amp_o <= 32'h0; cnt_pileup_o <= 32'h0;
      cnt_cross_o <= 32'h0; cnt_open_o <= 32'h0; cnt_lost_active_o <= 32'h0;
      cnt_lost_busy_o <= 32'h0; cnt_lost_veto_o <= 32'h0;
      cnt_win_o <= 32'h0; cnt_trig_o <= 32'h0;
    end
  end
end

endmodule
