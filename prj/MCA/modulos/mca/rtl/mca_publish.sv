`timescale 1ns/1ps
//=============================================================================
// mca_publish — publicacion del evento: cola de ranuras, divisores de forma y
// armado del bus de features
//
// Las ranuras de mca_window SON la cola de publicacion: una ranura que cierra
// aceptada se queda con su resultado (estado CERRADA) hasta que este modulo lo
// toma. Aca solo se guarda el ORDEN en que cerraron, como una cola de indices
// de N_ACC lugares, y el publicador las atiende de a una: carga los operandos
// de la mas vieja en los dos divisores, arma el bus de features cuando terminan
// y libera la ranura. Con N_ACC = 1 la ranura no puede reabrir hasta publicar:
// es el modo bloqueante de antes. Con mas, la ventana sigue midiendo mientras
// el publicador trabaja.
//
// ARRANQUE DIRECTO. Si la cola esta vacia y el publicador libre, los divisores
// arrancan en el MISMO flanco del cierre, desde los registros de la ranura que
// cierra (que en ese ciclo ya tienen su valor final: la muestra de cierre no se
// acumula). Asi una ranura espera exactamente 18 ciclos por evento: el del
// arranque, el de carga, las 16 iteraciones y el de valid.
//
// FRONTERA. Todo lo que entra de mca_window sale de los registros de las
// ranuras, y el mux N:1 de operandos va a un registro: con
// -flatten_hierarchy none la frontera no le agrega logica a ningun camino.
//
// EL BANCO DE TRAPECIOS: QUE FORMA SE PUBLICA. Cada ranura trae la meseta de
// las NF formas del banco, ordenadas de la mas larga a la mas corta, y la
// distancia al disparo anterior (dt_prev) y al siguiente dentro de la ventana
// (dt_next). Gana la PRIMERA forma f < n_formas con
//     antes[f] <= dt_prev   y   despues[f] <= dt_next
// o sea la mas larga (la de menos ruido) cuya ventana no alcanza al vecino. Si
// ninguna cumple, el pulso queda MARCADO: F_TRAP vale cero (cae en el canal 0,
// donde se ve, como una ventana incompleta) y F_FORMA vale 0xFFFF. Los umbrales
// en cero, que es lo del reset, hacen ganar siempre a la forma 0: es el MCA de
// un solo trapecio. La eleccion se registra en el ciclo en que los divisores
// enganchan los operandos, desde `cur`, asi que no agrega latencia: los 18
// ciclos por evento siguen iguales (y sin divisores, 2).
//=============================================================================

module mca_publish #(
  parameter integer DW      = 14,  // ancho de muestra
  parameter integer QW      = 32,  // ancho de los acumuladores de carga
  parameter integer AMP_W   = 16,  // ancho de una ranura del bus de features
  parameter integer PSD_AW  = 6,   // bits del EJE de factor de forma (mapa 2D)
  parameter integer DIV_W   = 16,  // bits de COCIENTE de los divisores
  parameter integer NFEAT   = 16,  // ranuras del bus de features
  parameter integer LEN_W   = 16,  // ancho de los contadores de longitud
  parameter integer EN_PSD  = 1,   // 0: no instancia los divisores
  parameter integer N_ACC   = 4,   // ranuras de medicion
  parameter integer PUB_IDW = 16,  // bits del id de ventana
  parameter integer NW      = 4,   // bits de la marca `otras`
  parameter integer TW      = 18,  // salida del trapecio
  parameter integer TNW     = 8,   // bits de la cuenta de la meseta
  parameter integer N_FORMAS = 4,  // formas del banco; 0: sin trapecio
  // Derivados: los usan los puertos. No se sobreescriben.
  parameter integer OC_W    = $clog2(N_ACC + 1),
  parameter integer TSW     = TW + TNW - 1,
  parameter integer NF      = (N_FORMAS < 1) ? 1 : N_FORMAS
)(
  input                        clk_i          ,
  input                        rstn_i         ,
  input                        cnt_clr_i      ,  // pulso: pone a cero los contadores

  // --- las ranuras de mca_window, aplanadas ---
  input      [N_ACC-1:0]          acepta_i    ,  // cierra aceptada en este ciclo
  input      [N_ACC*AMP_W-1:0]    amp_sel_i   ,  // el estimador SELECCIONADO
  input      [N_ACC*AMP_W-1:0]    amp_int_i   ,  // la integral, siempre
  input      [N_ACC*DW-1:0]       peak_i      ,
  input      [N_ACC*LEN_W-1:0]    len_i       ,
  input      [N_ACC*LEN_W-1:0]    t_peak_i    ,
  input      [N_ACC*QW-1:0]       q_tot_i     ,
  input      [N_ACC*QW-1:0]       q_tail_i    ,
  input      [N_ACC*PUB_IDW-1:0]  win_id_i    ,
  input      [N_ACC*LEN_W-1:0]    dt_prev_i   ,
  input      [N_ACC*LEN_W-1:0]    dt_next_i   ,
  input      [N_ACC*NW-1:0]       otras_i     ,
  input      [N_ACC-1:0]          adentro_i   ,
  input      [N_ACC-1:0]          perdido_i   ,
  input      [N_ACC*NF*TSW-1:0]   trap_sum_i  ,  // suma sobre cada meseta: (k*NF + f)
  input      [N_ACC*NF*TNW-1:0]   trap_n_i    ,  // ...y cuantas muestras sumo
  input      [NF*3-1:0]           cfg_trap_lw_i, // la ventana de la forma f: 2^lw muestras
  input      [NF*LEN_W-1:0]       cfg_antes_i ,  // umbral de dt_prev de cada forma
  input      [NF*LEN_W-1:0]       cfg_despues_i, // umbral de dt_next de cada forma
  input      [2:0]                cfg_n_formas_i,// formas habilitadas (0 = 1)
  output     [N_ACC-1:0]          libera_o    ,  // publicada: la ranura queda libre

  // --- estado de la cola, hacia el banco de registros ---
  output     [OC_W-1:0]        pub_occ_o      ,  // ranuras esperando publicar
  output reg [OC_W-1:0]        pub_occ_max_o  ,  // maximo historico

  // --- evento de salida (pulso de 1 ciclo) ---
  output reg                   ev_valid_o     ,
  output reg [AMP_W-1:0]       ev_amp_o       ,
  output reg [PSD_AW-1:0]      ev_psd_o       ,
  output reg                   ev_psd_ok_o    ,  // 0 => no histogramear el 2D
  output reg [NFEAT*AMP_W-1:0] ev_feat_o      ,
  output reg [32-1:0]          cnt_accepted_o ,
  output reg [32-1:0]          cnt_rej_psd_o  ,  // q_tot=0 o q_tail>=q_tot
  output reg [PUB_IDW-1:0]     last_win_id_o     // id de la ultima ventana publicada
);

localparam integer IW = (N_ACC <= 1) ? 1 : $clog2(N_ACC);

//-----------------------------------------------------------------------------
// Indices del bus de features. Fijos y compartidos: el selector de eje del
// histograma y el discriminador usan ESTA numeracion.
//-----------------------------------------------------------------------------
localparam integer F_PEAK   = 0;  // amplitud de pico
localparam integer F_INT    = 1;  // integral de carga (Q_total >> q_shift)
localparam integer F_PSD    = 2;  // Q_cola/Q_total   — donde esta la carga
localparam integer F_INVW   = 3;  // Pico/Q_total     — ancho inverso
localparam integer F_LEN    = 4;  // largo de la ventana, en muestras
localparam integer F_TRISE  = 5;  // muestras del disparo al pico
localparam integer F_DTPREV = 6;  // muestras desde el disparo anterior
localparam integer F_DTNEXT = 7;  // muestras hasta el siguiente disparo adentro
localparam integer F_SOLAPE = 8;  // {perdido, adentro, otras[NW-1:0]}
localparam integer F_TRAP   = 9;  // altura de la meseta del trapecio elegido
localparam integer F_FORMA  = 10; // la forma del banco que se publico, 0xFFFF = marcado
// 11..NFEAT-1 reservadas. Se atan a cero: la sintesis las borra enteras, asi
// que una ranura sin usar no cuesta nada.

// Normalizacion de cada ranura. El contrato del bus es "uint16 con fondo de
// escala 0xFFFF", asi que las features acotadas se alinean a la IZQUIERDA.
// Excepcion honesta: F_INVW, F_LEN, F_TRISE, F_DTPREV y F_DTNEXT NO se
// normalizan (contadores sin fondo de escala natural, o una fraccion que vive
// cerca de cero), y F_SOLAPE es un campo de bits.
function automatic [AMP_W-1:0] feat_izq(input [DIV_W-1:0] q);
  feat_izq = (AMP_W >= DIV_W) ? {q, {(AMP_W-DIV_W){1'b0}}}
                              : q[DIV_W-1 -: AMP_W];
endfunction

// F_TRAP: el PROMEDIO sobre la meseta (la suma >>> lw), saturado a [0, 2^AMP_W).
// Ya viene escalado por cfg_trap_sh, que el software elige para que la altura
// quede alineada a la izquierda como F_PEAK. Si la ranura no sumo las 2^lw
// muestras —la compuerta cerro antes de que terminara la ventana— vale CERO: un
// promedio parcial caeria en cualquier lugar del espectro sin avisar, el cero
// cae en el canal 0, donde se ve.
function automatic [AMP_W-1:0] feat_trap(input signed [TSW-1:0] suma,
                                         input [TNW-1:0] n, input [2:0] lw);
  reg signed [TSW-1:0] prom;
  begin
    prom = suma >>> lw;
    if (n != ({{(TNW-1){1'b0}}, 1'b1} << lw) || prom[TSW-1])
      feat_trap = {AMP_W{1'b0}};
    else if (|prom[TSW-2:AMP_W])
      feat_trap = {AMP_W{1'b1}};
    else
      feat_trap = prom[AMP_W-1:0];
  end
endfunction

//-----------------------------------------------------------------------------
// Los DOS divisores de forma, en paralelo
//
// (1) PSD = Q_cola/Q_total — comparacion de carga (Brooks 1959; Knoll cap. 17).
//     Mide DONDE esta la carga: el peso de la componente lenta.
// (2) INVW = Pico/Q_total  — el ancho inverso. Mide CUANTA carga hay por unidad
//     de altura, o sea el ancho efectivo del pulso. Es el que separa los
//     apilados (99.1 % contra 29.6 % de PSD, ver software/monte-carlo/).
//
// Por que P/Q y no Q/P: el divisor restaurador exige num < den, y Q/P > 1 no
// entra. P/Q si, porque q_tot = sum(xc) >= max(xc) = peak SIEMPRE.
//
// Corren EN PARALELO, mismo denominador y mismo arranque: el segundo no agrega
// ni un ciclo. Cero DSP. DIV_W = 16 bits de cociente; el eje del mapa 2D toma
// los PSD_AW bits ALTOS, que es bit-exacto respecto de un divisor de PSD_AW bits.
//-----------------------------------------------------------------------------
reg              div_start;
wire [QW-1:0]    div_num, div_den, div2_num;
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
  mca_div_restore #(.D_W(QW), .Q_W(DIV_W)) i_div_w (
    .clk_i(clk_i), .rstn_i(rstn_i),
    .start_i(div_start), .num_i(div2_num), .den_i(div_den),
    .q_o(div2_q), .valid_o(div2_valid), .err_o(div2_err), .sat_o(div2_sat),
    .busy_o()
  );
end else begin : g_nodiv
  // Sin divisores el publicador igual atiende la cola, pero termina en el
  // ciclo siguiente al arranque y con las ranuras de forma en cero.
  reg fin;
  always @(posedge clk_i)
    if (!rstn_i) fin <= 1'b0;
    else         fin <= div_start;
  assign div_q      = {DIV_W{1'b0}};
  assign div_valid  = fin;
  assign div_err    = 1'b1;
  assign div_sat    = 1'b0;
  assign div_busy   = 1'b0;
  assign div2_q     = {DIV_W{1'b0}};
  assign div2_valid = fin;
  assign div2_err   = 1'b0;
  assign div2_sat   = 1'b0;
end endgenerate

//-----------------------------------------------------------------------------
// La cola de ranuras cerradas, en orden de cierre
//-----------------------------------------------------------------------------
// Varias ranuras pueden cerrar en el mismo ciclo (si se toco gate_long a mitad
// de corrida): se encolan todas, en orden de indice. No puede desbordar: cada
// ranura esta en la cola a lo sumo una vez, y hay N_ACC.
reg [IW-1:0]   cola [0:N_ACC-1];
reg [OC_W-1:0] n_cola;
wire           vacia = (n_cola == {OC_W{1'b0}});
wire [IW-1:0]  cabeza = cola[0];

// La de menor indice entre las que cierran ahora: la del arranque directo.
reg [IW-1:0] idx_cierre;
integer kc;
always @* begin
  idx_cierre = {IW{1'b0}};
  for (kc = N_ACC - 1; kc >= 0; kc = kc - 1)
    if (acepta_i[kc]) idx_cierre = kc[IW-1:0];
end
wire hay_cierre = |acepta_i;

assign pub_occ_o = n_cola;

// Estado del publicador
localparam [0:0] P_IDLE = 1'd0, P_DIV = 1'd1;
reg          pst;
reg [IW-1:0] cur;            // ranura que esta en los divisores
reg          psd_ok_cur;     // q_tot != 0 y q_tail < q_tot, de `cur`

// La forma del banco que publica `cur`, y si quedo marcado (ninguna alcanza)
localparam integer FW = (NF <= 1) ? 1 : $clog2(NF);
reg [FW-1:0] forma_cur;
reg          marcado_cur;

wire [2:0] nf_hab = (cfg_n_formas_i == 3'd0) ? 3'd1
                  : (cfg_n_formas_i > NF[2:0]) ? NF[2:0] : cfg_n_formas_i;
wire [LEN_W-1:0] dtp_cur = dt_prev_i[cur*LEN_W +: LEN_W];
wire [LEN_W-1:0] dtn_cur = dt_next_i[cur*LEN_W +: LEN_W];
reg  [FW-1:0] forma_d;
reg           marcado_d;
integer kf;
always @* begin
  forma_d = {FW{1'b0}}; marcado_d = 1'b1;
  for (kf = NF - 1; kf >= 0; kf = kf - 1)
    if ((kf < nf_hab) &&
        (cfg_antes_i  [kf*LEN_W +: LEN_W] <= dtp_cur) &&
        (cfg_despues_i[kf*LEN_W +: LEN_W] <= dtn_cur)) begin
      forma_d = kf[FW-1:0]; marcado_d = 1'b0;
    end
end

// F_TRAP de la forma elegida, de `cur`
wire [AMP_W-1:0] f_trap_cur = feat_trap(trap_sum_i[(cur*NF + forma_cur)*TSW +: TSW],
                                        trap_n_i  [(cur*NF + forma_cur)*TNW +: TNW],
                                        cfg_trap_lw_i[forma_cur*3 +: 3]);

wire pub_done = (pst == P_DIV) && div_valid;

genvar gk;
generate for (gk = 0; gk < N_ACC; gk = gk + 1) begin : g_lib
  assign libera_o[gk] = pub_done && (cur == gk);
end endgenerate

// Que ranura arranca: la cabeza de la cola, o la que cierra si la cola esta
// vacia (arranque directo). En el ciclo del arranque se decide SOLO el indice.
//
// LOS OPERANDOS SALEN DE `cur`, NO DE ESTA DECISION. El divisor engancha num y
// den recien en el ciclo siguiente a div_start, y para entonces `cur` ya es un
// registro: el mux de 32 bits y las comparaciones cuelgan de un flop. La
// primera version los registraba en el mismo flanco del arranque, desde el
// indice recien decidido, y la OOC dio -0.734 ns: cierre de la ranura
// (len >= gate_long) -> aceptacion -> prioridad -> mux de 32 bits -> comparador
// de 32 bits -> psd_ok, trece niveles en un ciclo.
wire [IW-1:0] op = vacia ? idx_cierre : cabeza;
assign div_den  = q_tot_i [cur*QW +: QW];
assign div_num  = q_tail_i[cur*QW +: QW];
assign div2_num = {{(QW-DW){1'b0}}, peak_i[cur*DW +: DW]};   // ancho inverso: P/Q

// La siguiente cola: sale la cabeza si se publico, entran las que cierran.
reg [IW-1:0]   cola_d [0:N_ACC-1];
reg [OC_W-1:0] n_cola_d;
integer ki, kp;
always @* begin
  for (ki = 0; ki < N_ACC; ki = ki + 1) cola_d[ki] = cola[ki];
  n_cola_d = n_cola;
  if (pub_done) begin
    for (ki = 0; ki < N_ACC - 1; ki = ki + 1) cola_d[ki] = cola[ki+1];
    n_cola_d = n_cola - {{(OC_W-1){1'b0}}, 1'b1};
  end
  for (kp = 0; kp < N_ACC; kp = kp + 1)
    if (acepta_i[kp]) begin
      cola_d[n_cola_d] = kp[IW-1:0];
      n_cola_d = n_cola_d + {{(OC_W-1){1'b0}}, 1'b1};
    end
end

//-----------------------------------------------------------------------------
integer kr;
always @(posedge clk_i) begin
  if (!rstn_i) begin
    div_start <= 1'b0;
    for (kr = 0; kr < N_ACC; kr = kr + 1) cola[kr] <= {IW{1'b0}};
    n_cola <= {OC_W{1'b0}};
    pst <= P_IDLE; cur <= {IW{1'b0}}; psd_ok_cur <= 1'b0;
    forma_cur <= {FW{1'b0}}; marcado_cur <= 1'b0;
    pub_occ_max_o <= {OC_W{1'b0}};
    last_win_id_o <= {PUB_IDW{1'b0}};
    ev_valid_o <= 1'b0; ev_amp_o <= {AMP_W{1'b0}};
    ev_psd_o <= {PSD_AW{1'b0}}; ev_psd_ok_o <= 1'b0;
    ev_feat_o <= {(NFEAT*AMP_W){1'b0}};
    cnt_accepted_o <= 32'h0; cnt_rej_psd_o <= 32'h0;
  end else begin
    ev_valid_o <= 1'b0;
    div_start  <= 1'b0;

    // El divisor exige q_tail < q_tot y q_tot != 0. Se verifica ACA, no se
    // confia en la invariante: un q_tot = 0 (ventana sin carga) haria que el
    // cociente saliera todo unos, o sea al bin superior del eje. Se evalua en
    // el ciclo en que el divisor engancha los operandos, desde `cur`.
    if (div_start) psd_ok_cur <= (div_den != {QW{1'b0}}) && (div_num < div_den);
    // la forma, en el mismo ciclo y desde el mismo `cur`
    if (div_start) begin forma_cur <= forma_d; marcado_cur <= marcado_d; end

    for (kr = 0; kr < N_ACC; kr = kr + 1) cola[kr] <= cola_d[kr];
    n_cola <= n_cola_d;

    case (pst)
      P_IDLE: if (!vacia || hay_cierre) begin
        div_start  <= 1'b1;
        pst        <= P_DIV;
        cur        <= op;
      end

      P_DIV: if (div_valid) begin
        ev_amp_o <= amp_sel_i[cur*AMP_W +: AMP_W];

        // --- bus de features: se arma ACA, no al cerrar ------------------
        ev_feat_o <= {(NFEAT*AMP_W){1'b0}};
        ev_feat_o[F_PEAK  *AMP_W +: AMP_W] <= {peak_i[cur*DW +: DW], {(AMP_W-DW){1'b0}}};
        ev_feat_o[F_INT   *AMP_W +: AMP_W] <= amp_int_i[cur*AMP_W +: AMP_W];
        ev_feat_o[F_LEN   *AMP_W +: AMP_W] <= len_i    [cur*LEN_W +: LEN_W];
        ev_feat_o[F_TRISE *AMP_W +: AMP_W] <= t_peak_i [cur*LEN_W +: LEN_W];
        ev_feat_o[F_DTPREV*AMP_W +: AMP_W] <= dt_prev_i[cur*LEN_W +: LEN_W];
        ev_feat_o[F_DTNEXT*AMP_W +: AMP_W] <= dt_next_i[cur*LEN_W +: LEN_W];
        ev_feat_o[F_SOLAPE*AMP_W +: AMP_W] <=
            {{(AMP_W-NW-2){1'b0}}, perdido_i[cur], adentro_i[cur], otras_i[cur*NW +: NW]};
        if (N_FORMAS != 0) begin
          ev_feat_o[F_TRAP *AMP_W +: AMP_W] <= marcado_cur ? {AMP_W{1'b0}} : f_trap_cur;
          ev_feat_o[F_FORMA*AMP_W +: AMP_W] <= marcado_cur ? {AMP_W{1'b1}}
                                             : {{(AMP_W-FW){1'b0}}, forma_cur};
        end
        // El ancho inverso NO se alinea a la izquierda: vive cerca de cero y
        // su escala depende del ancho del pulso.
        ev_feat_o[F_INVW  *AMP_W +: AMP_W] <=
            div2_sat ? {AMP_W{1'b1}} : {{(AMP_W-DIV_W){1'b0}}, div2_q};

        cnt_accepted_o <= cnt_accepted_o + 32'h1;
        if (div_err || div_sat || !psd_ok_cur) begin
          // El evento sigue siendo bueno en amplitud: entra al espectro 1D,
          // pero no al mapa 2D. La ranura de forma queda en cero.
          if (EN_PSD != 0) cnt_rej_psd_o <= cnt_rej_psd_o + 32'h1;
          ev_psd_o    <= {PSD_AW{1'b0}};
          ev_psd_ok_o <= 1'b0;
        end else begin
          ev_psd_o    <= div_q[DIV_W-1 -: PSD_AW];
          ev_psd_ok_o <= 1'b1;
          ev_feat_o[F_PSD*AMP_W +: AMP_W] <= feat_izq(div_q);
        end
        ev_valid_o    <= 1'b1;
        last_win_id_o <= win_id_i[cur*PUB_IDW +: PUB_IDW];
        pst           <= P_IDLE;
      end

      default: pst <= P_IDLE;
    endcase

    // Marca de agua de la cola. Llegar a N_ACC quiere decir que el publicador
    // no dio abasto y hubo ranuras esperando: lo perdido por eso esta en
    // cnt_lost_busy.
    if (n_cola > pub_occ_max_o) pub_occ_max_o <= n_cola;

    //--- borrado de contadores (va último) ------------------------------------
    if (cnt_clr_i) begin
      cnt_accepted_o <= 32'h0;
      cnt_rej_psd_o  <= 32'h0;
      // La cola EN CURSO no se toca: hay resultados reales adentro y perderlos
      // dejaria ranuras CERRADAS para siempre.
      pub_occ_max_o  <= {OC_W{1'b0}};
    end
  end
end

endmodule
