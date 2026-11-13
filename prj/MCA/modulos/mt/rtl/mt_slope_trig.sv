`timescale 1ns/1ps
//=============================================================================
// mt_slope_trig — disparo por PENDIENTE con un trapezoidal rápido
//
// Hermano de rp_adc_trig: misma entrada (el tap mtrg_dat/mtrg_val), mismo
// Schmitt a la salida, mismos dos pulsos de 1 ciclo (p = flanco de subida,
// n = flanco de bajada). Lo que cambia es QUÉ se compara contra el umbral: no
// la muestra x, sino la salida de un filtro trapezoidal rápido
//
//   s[n] = Σ_{i=0}^{L-1} x[n-i]  -  Σ_{i=0}^{L-1} x[n-L-G-i]
//
// es decir, la suma de las últimas L muestras menos la suma de L muestras
// G muestras más atrás: una DERIVADA SUAVIZADA. Es el "fast filter" con el que
// disparan los procesadores digitales de pulsos (Jordanov & Knoll 1994; es la
// rama rápida de XIA, Amptek y del DPP-PHA de CAEN).
//
// POR QUÉ Y NO UN UMBRAL DE NIVEL. La suma de coeficientes es cero, así que s
// RECHAZA LA CONTINUA: un offset o una deriva lenta de la línea de base no
// mueve el umbral efectivo, que en el disparo de nivel sí se mueve (y la
// deriva es el límite real del MCA, ver docs/mca/limites_resolucion_y_deriva).
//
// QUÉ MIDE s:
//   - un escalón de alto A (más rápido que L+G) da un TRAPECIO de alto L·A,
//     subida L y techo G+1 muestras;
//   - una rampa de pendiente m da s = L·(L+G)·m: la pendiente, escalada;
//   - ruido blanco σ da σ_s = σ·√(2L). Subir L mejora la relación señal/ruido
//     como √L para escalones, a costa de latencia. Con L=1, G=k-1 queda la
//     diferencia de k muestras x[n]-x[n-k].
//
// IMPLEMENTACIÓN. Recursiva y exacta en enteros (no deriva):
//
//   s[n] = s[n-1] + (x[n] - x[n-L]) - (x[n-L-G] - x[n-2L-G])
//
// con TRES líneas de retardo en cascada (L, G, L muestras), cada una con UNA
// toma dinámica: es el patrón que Vivado lleva a SRLC32E. Una sola línea de
// 2·LMAX+GMAX con tres tomas sale en flip-flops y muxes: medido OOC, 3 veces
// más LUT y 5 veces más FF (docs/mt/trigger_pendiente.md §6). Las líneas no tienen reset (si no, no hay SRL); en su lugar, el
// contador `fill` cuenta cuántas muestras válidas entraron desde el último
// re-arranque, y una toma más vieja que eso lee 0. Así s es exactamente el
// filtro aplicado a la señal con historia en cero, sin offset fantasma.
//
// RE-ARRANQUE. Cualquier cambio de L o G, cfg_en=0 o el reset vacían el filtro
// (s=0, fill=0). Mientras la ventana completa (2L+G muestras) no esté llena,
// el Schmitt queda en "disparado" y no sale ningún pulso: el arranque desde
// historia cero es un escalón falso y no debe disparar. Por la misma razón el
// primer pulso pide re-armar antes (s < thr-hyst), igual que tras un disparo.
//
// SCHMITT. Igual que rp_adc_trig, simétrico en los dos signos:
//   p: dispara con s >=  thr, re-arma con s <  thr-hyst
//   n: dispara con s <= -thr, re-arma con s > -thr+hyst
// thr y hyst son magnitudes (sin signo). Con hyst >= thr no re-arma nunca en
// s=0: es configuración inválida, igual que en el disparo de nivel.
//
// LATENCIA. 5 ciclos de pipeline desde la muestra hasta el pulso, más lo que
// tarde s en cruzar thr (del orden de L muestras para un escalón).
//
// Todo avanza solo con adc_dv_i, así que funciona igual sobre el tap nativo
// (decimado) que sobre los taps de 125 MSPS.
//=============================================================================

module mt_slope_trig #(
  parameter integer DW   = 14,                     // ancho de la muestra
  parameter integer LMAX = 16,                     // L máximo (ventana de suma)
  parameter integer GMAX = 31,                     // G máximo (separación)
  parameter integer LW   = 5,                      // ancho del campo L
  parameter integer GW   = 5,                      // ancho del campo G
  parameter integer SW   = DW + $clog2(LMAX) + 1,  // ancho de s (con signo)
  parameter integer TW   = SW - 1                  // ancho de thr/hyst (magnitud)
)(
  input                 adc_clk_i  ,  // ADC clock
  input                 adc_rstn_i ,  // ADC reset - active low

  input      [DW-1: 0]  adc_dat_i  ,  // muestra (con signo)
  input                 adc_dv_i   ,  // muestra válida

  input                 cfg_en_i   ,  // 0 = filtro vacío, sin pulsos
  input      [LW-1: 0]  cfg_len_i  ,  // L (0 se toma como 1, >LMAX satura)
  input      [GW-1: 0]  cfg_gap_i  ,  // G (>GMAX satura)
  input      [TW-1: 0]  cfg_thr_i  ,  // umbral sobre |s|
  input      [TW-1: 0]  cfg_hyst_i ,  // histéresis del re-armado

  output reg            slope_p_o  ,  // pendiente positiva, 1 ciclo
  output reg            slope_n_o  ,  // pendiente negativa, 1 ciclo
  // 1 = re-armado: el próximo cruce de thr (o de -thr) dispara. Es el estado
  // del Schmitt, sin registro extra; lo usa mt_event_logic para el tiempo de
  // re-armado del MCA. Vale 0 mientras la ventana no está llena.
  output                armado_p_o ,
  output                armado_n_o
);

localparam integer DEPTH = 2*LMAX + GMAX;          // toma más vieja
localparam integer IW    = $clog2(DEPTH + 1);      // índice de toma

localparam [LW-1:0] LMAX_V  = LMAX;
localparam [GW-1:0] GMAX_V  = GMAX;
localparam [IW-1:0] DEPTH_V = DEPTH;

//-----------------------------------------------------------------------------
// Configuración: saturada, registrada dos veces. El re-arranque dura mientras
// la config viva difiera de cualquiera de las dos copias, así las tomas (que
// salen de la segunda) ya son las nuevas cuando fill empieza a contar.
//-----------------------------------------------------------------------------
wire [LW-1:0] len_c = (cfg_len_i == {LW{1'b0}}) ? {{LW-1{1'b0}}, 1'b1} :
                      (cfg_len_i > LMAX_V)       ? LMAX_V : cfg_len_i;
wire [GW-1:0] gap_c = (cfg_gap_i > GMAX_V)       ? GMAX_V : cfg_gap_i;

reg [LW-1:0] len_q, len_q2;
reg [GW-1:0] gap_q, gap_q2;
reg          en_q;
reg [IW-1:0] tap_a, tap_b, tap_c;   // edad de cada toma: L, L+G, 2L+G
reg [LW-1:0] adr_l;                 // dirección de las líneas de L: L-1
reg [GW-1:0] adr_g;                 // dirección de la línea de G:  G-1
reg          g_zero;                // G=0: la línea del medio se puentea

always @(posedge adc_clk_i) begin
  len_q  <= len_c;  gap_q  <= gap_c;  en_q <= cfg_en_i;
  len_q2 <= len_q;  gap_q2 <= gap_q;
  tap_a  <= len_q;
  tap_b  <= len_q + gap_q;
  tap_c  <= {len_q, 1'b0} + gap_q;
  adr_l  <= len_q - 1'b1;
  adr_g  <= gap_q - 1'b1;
  g_zero <= (gap_q == {GW{1'b0}});
end

wire restart = !adc_rstn_i || !en_q ||
               (len_c != len_q) || (gap_c != gap_q) ||
               (len_q != len_q2) || (gap_q != gap_q2);

//-----------------------------------------------------------------------------
// Líneas de retardo en cascada (sin reset) y contador de llenado
//
//   x --[L]--> xa = x[n-L] --[G]--> xb = x[n-L-G] --[L]--> xc = x[n-2L-G]
//
// Antes del corrimiento de la muestra n, srX[k] tiene la entrada de hace k+1
// muestras, así que la toma en la dirección D-1 da el retardo D.
//-----------------------------------------------------------------------------
wire signed [DW-1:0] x = adc_dat_i;

reg signed [DW-1:0] sr_l1 [0:LMAX-1];   // x  -> xa
reg signed [DW-1:0] sr_g  [0:GMAX-1];   // xa -> xb
reg signed [DW-1:0] sr_l2 [0:LMAX-1];   // xb -> xc

wire signed [DW-1:0] xa = sr_l1[adr_l];
wire signed [DW-1:0] xb = g_zero ? xa : sr_g[adr_g];
wire signed [DW-1:0] xc = sr_l2[adr_l];

integer k1, kg, k2;
always @(posedge adc_clk_i)
  if (adc_dv_i) begin
    sr_l1[0] <= x;
    for (k1 = 1; k1 < LMAX; k1 = k1 + 1) sr_l1[k1] <= sr_l1[k1-1];
  end

always @(posedge adc_clk_i)
  if (adc_dv_i) begin
    sr_g[0] <= xa;
    for (kg = 1; kg < GMAX; kg = kg + 1) sr_g[kg] <= sr_g[kg-1];
  end

always @(posedge adc_clk_i)
  if (adc_dv_i) begin
    sr_l2[0] <= xb;
    for (k2 = 1; k2 < LMAX; k2 = k2 + 1) sr_l2[k2] <= sr_l2[k2-1];
  end

reg [IW-1:0] fill;                  // muestras válidas en la línea
always @(posedge adc_clk_i)
  if (restart)
    fill <= {IW{1'b0}};
  else if (adc_dv_i && (fill != DEPTH_V))
    fill <= fill + 1'b1;

//-----------------------------------------------------------------------------
// Pipeline: tomas -> diferencia -> acumulador
//-----------------------------------------------------------------------------
reg signed [DW-1:0] p1_x0, p1_xa, p1_xb, p1_xc;
reg                 p1_v, p1_full;
reg signed [SW-1:0] p2_d;
reg                 p2_v, p2_full;
reg signed [SW-1:0] s;
reg                 p3_v, p3_full;

always @(posedge adc_clk_i)
if (restart) begin
  p1_v <= 1'b0;  p1_full <= 1'b0;
  p2_v <= 1'b0;  p2_full <= 1'b0;
  p3_v <= 1'b0;  p3_full <= 1'b0;
  s    <= {SW{1'b0}};
end else begin
  // 1: tomas. Una toma más vieja que lo que entró desde el re-arranque lee 0.
  p1_v <= adc_dv_i;
  if (adc_dv_i) begin
    p1_x0   <= x;
    p1_xa   <= (fill >= tap_a) ? xa : {DW{1'b0}};
    p1_xb   <= (fill >= tap_b) ? xb : {DW{1'b0}};
    p1_xc   <= (fill >= tap_c) ? xc : {DW{1'b0}};
    p1_full <= (fill >= tap_c);
  end

  // 2: (x[n]-x[n-L]) - (x[n-L-G]-x[n-2L-G])
  p2_v <= p1_v;
  if (p1_v) begin
    p2_d    <= (p1_x0 - p1_xa) - (p1_xb - p1_xc);
    p2_full <= p1_full;
  end

  // 3: acumulador
  p3_v <= p2_v;
  if (p2_v) begin
    s       <= s + p2_d;
    p3_full <= p2_full;
  end
end

//-----------------------------------------------------------------------------
// Schmitt simétrico, como rp_adc_trig
//-----------------------------------------------------------------------------
reg signed [SW-1:0] thr_p, rearm_p, thr_n, rearm_n;
reg        [ 2-1:0] scht_p, scht_n;

always @(posedge adc_clk_i) begin
  thr_p   <=   $signed({1'b0, cfg_thr_i});
  rearm_p <=   $signed({1'b0, cfg_thr_i}) - $signed({1'b0, cfg_hyst_i});
  thr_n   <= - $signed({1'b0, cfg_thr_i});
  rearm_n <= - $signed({1'b0, cfg_thr_i}) + $signed({1'b0, cfg_hyst_i});
end

always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0) begin
  scht_p    <= 2'b11 ;
  scht_n    <= 2'b11 ;
  slope_p_o <= 1'b0  ;
  slope_n_o <= 1'b0  ;
end else begin
  if (!p3_full) begin
    // ventana incompleta: "disparado" sin flanco, pide re-armar
    scht_p <= 2'b11 ;
    scht_n <= 2'b11 ;
  end else begin
    if (p3_v) begin
           if (s >= thr_p  ) scht_p[0] <= 1'b1 ;  // pendiente positiva
      else if (s <  rearm_p) scht_p[0] <= 1'b0 ;  // re-arma bajo la histéresis
           if (s <= thr_n  ) scht_n[0] <= 1'b1 ;  // pendiente negativa
      else if (s >  rearm_n) scht_n[0] <= 1'b0 ;  // re-arma sobre la histéresis
    end
    scht_p[1] <= scht_p[0] ;
    scht_n[1] <= scht_n[0] ;
  end

  slope_p_o <= scht_p[0] && !scht_p[1] ;  // pulso de 1 ciclo
  slope_n_o <= scht_n[0] && !scht_n[1] ;
end

assign armado_p_o = !scht_p[0] ;
assign armado_n_o = !scht_n[0] ;

endmodule
