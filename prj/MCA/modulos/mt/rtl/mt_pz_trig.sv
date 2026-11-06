`timescale 1ns/1ps
//=============================================================================
// mt_pz_trig — disparo con POLO-CERO: un trapecio muy corto y un Schmitt
//
// Hermano de mt_slope_trig: misma entrada (el tap mtrg_dat/mtrg_val), mismo
// Schmitt con re-armado por histeresis, un pulso de 1 ciclo por cruce. Lo que
// cambia es QUE se compara contra el umbral: la salida de un trapecio de
// Jordanov-Knoll CON polo-cero (mca_trap, el mismo del MCA), de subida k y
// meseta m chicas (k = 2, m = 1 para el pulso del Rigol).
//
// POR QUE, Y NO LA PENDIENTE. La pendiente s = sum_L x - sum_L x[n-L-G] no
// cancela el polo de la cola, asi que la cola de un pulso grande le da s < 0
// durante cientos de muestras: un pulso chico encima no llega al umbral (con
// L = 8, G = 4, uno de 300 despues de uno de 8000 queda ciego hasta Dt ~ 150).
// Y como s sube durante L + G muestras, dos pulsos a menos de ~2L + G se funden
// en un solo disparo, y el cruce corre con la amplitud (7 a 13 ciclos entre
// A = 8000 y 100). Con el polo-cero la salida de cada pulso es un trapecio que
// VUELVE A CERO a las 2k + m muestras, sobre cero aunque haya una cola debajo:
// pares desde 7-8 muestras, sin ceguera, y el cruce corre 1 muestra. Ver
// docs/mca/pruebas_banco_trapecios.md, donde se valido con este mismo mca_trap.
//
// LA CONTINUA NO SE CANCELA DEL TODO. Para una entrada constante D la salida se
// asienta en 2^MF*D*k*l >> sh (la doble integral del pulso finito que deja la
// doble diferencia): con k = 2, m = 1 es ~1.2 % de lo que da un pulso de alto
// D. 500 cuentas de offset corren el umbral efectivo unas 6 cuentas. No hace
// falta restar la base, pero el umbral se elige sobre la muestra del tap.
//
// RE-ARRANQUE. El trapecio es exacto solo con su estado consistente con las
// lineas de retardo (ver mca_trap.sv), asi que un cambio de k, m o Mq, cfg_en =
// 0 o el reset le pulsan clr. La configuracion se registra dos veces y el
// re-arranque dura mientras la viva difiera de cualquiera de las dos copias,
// igual que en mt_slope_trig; el trapecio toma la segunda.
//
// ARRANQUE. Desde el clr el trapecio ve la continua del tap como un ESCALON:
// con 500 cuentas sube a ~3900 antes de asentarse. Por eso, hasta que entraron
// k + l + LAT + 2 muestras desde el re-arranque, el Schmitt queda "disparado"
// sin flanco, y despues tiene que re-armar (y < thr - hyst) antes del primer
// pulso, igual que tras un disparo.
//
// SCHMITT, solo positivo (el MCA mide pulsos positivos):
//   dispara con y >= thr, re-arma con y < thr - hyst
// thr y hyst son magnitudes en unidades de la salida del trapecio (la ganancia
// de un pulso es 2^MF*k*(1+M) >> sh por cuenta: el software convierte). Con
// hyst >= thr no re-arma nunca en y = 0: configuracion invalida.
//
// LATENCIA. La de mca_trap (LAT = 8 muestras) mas dos registros (el Schmitt y
// el flanco): 10 ciclos desde la muestra del cruce hasta pz_p_o, 5 mas que la
// pendiente. El MCA lo absorbe en cfg_pre_dly.
//
// Todo avanza con adc_dv_i, asi que funciona igual sobre el tap nativo
// (decimado) que sobre los de 125 MSPS. El Schmitt se evalua todos los ciclos:
// entre muestras la salida del trapecio se sostiene, y evaluar dos veces el
// mismo valor no cambia el estado.
//=============================================================================

module mt_pz_trig #(
  parameter integer DW  = 14,   // ancho de la muestra
  parameter integer DAW = 5,    // lineas de 2^DAW: k y k + m hasta 2^DAW - 1
  parameter integer KW  = 5,    // ancho de los campos k y m
  parameter integer MW  = 20,   // bits de Mq (M * 16), sin signo
  parameter integer TW  = 18    // salida del trapecio, con signo; thr y hyst
)(
  input                 adc_clk_i  ,  // ADC clock
  input                 adc_rstn_i ,  // ADC reset - active low

  input      [DW-1: 0]  adc_dat_i  ,  // muestra (con signo)
  input                 adc_dv_i   ,  // muestra valida

  input                 cfg_en_i   ,  // 0 = trapecio vacio, sin pulsos
  input      [KW-1: 0]  cfg_k_i    ,  // subida (0 se toma como 1)
  input      [KW-1: 0]  cfg_m_i    ,  // meseta (k + m satura en 2^DAW - 1)
  input      [MW-1: 0]  cfg_mq_i   ,  // polo-cero: M * 16
  input      [   5: 0]  cfg_sh_i   ,  // corrimiento de la salida
  input      [TW-1: 0]  cfg_thr_i  ,  // umbral (magnitud)
  input      [TW-1: 0]  cfg_hyst_i ,  // histeresis del re-armado

  output reg            pz_p_o        // pulso de 1 ciclo
);

localparam integer LAT  = 8;                    // la de mca_trap
localparam integer XW   = DW + 1;               // la muestra extendida
localparam [DAW-1:0] LMAX = {DAW{1'b1}};        // lo mas largo que entra
localparam integer FW   = DAW + 3;              // llega a 2*LMAX + LAT + 2

//-----------------------------------------------------------------------------
// Configuracion: saturada y registrada dos veces
//-----------------------------------------------------------------------------
wire [DAW-1:0] k_c;
wire [DAW:0]   kl_c;
generate if (KW >= DAW) begin : g_k_ancho
  wire [KW:0] kk = (cfg_k_i == {KW{1'b0}}) ? {{KW{1'b0}}, 1'b1} : {1'b0, cfg_k_i};
  wire [KW+1:0] ll = {1'b0, kk} + {2'b0, cfg_m_i};
  assign k_c  = (kk > LMAX) ? LMAX : kk[DAW-1:0];
  assign kl_c = (ll > LMAX) ? {1'b0, LMAX} : ll[DAW:0];
end else begin : g_k_angosto
  wire [DAW-1:0] kk = (cfg_k_i == {KW{1'b0}}) ? {{(DAW-1){1'b0}}, 1'b1}
                                              : {{(DAW-KW){1'b0}}, cfg_k_i};
  wire [DAW:0] ll = {1'b0, kk} + {{(DAW-KW+1){1'b0}}, cfg_m_i};
  assign k_c  = kk;
  assign kl_c = (ll > LMAX) ? {1'b0, LMAX} : ll;
end endgenerate
wire [DAW-1:0] l_c = kl_c[DAW-1:0];

reg [DAW-1:0] k_q, k_q2, l_q, l_q2;
reg [MW-1:0]  mq_q, mq_q2;
reg           en_q;

always @(posedge adc_clk_i) begin
  k_q  <= k_c;   l_q  <= l_c;   mq_q  <= cfg_mq_i;  en_q <= cfg_en_i;
  k_q2 <= k_q;   l_q2 <= l_q;   mq_q2 <= mq_q;
end

wire restart = !adc_rstn_i || !en_q ||
               (k_c  != k_q ) || (l_c  != l_q ) || (cfg_mq_i != mq_q) ||
               (k_q  != k_q2) || (l_q  != l_q2) || (mq_q     != mq_q2);

//-----------------------------------------------------------------------------
// El trapecio
//-----------------------------------------------------------------------------
wire signed [TW-1:0] y;

mca_trap #(
  .XW(XW), .DAW(DAW), .MW(MW), .TW(TW), .LAT(LAT), .RAM_STYLE("distributed")
) i_trap (
  .clk_i    ( adc_clk_i                    ),
  .rstn_i   ( adc_rstn_i                   ),
  .clr_i    ( restart                      ),
  .x_i      ( {adc_dat_i[DW-1], adc_dat_i} ),
  .val_i    ( adc_dv_i                     ),
  .cfg_k_i  ( k_q2                         ),
  .cfg_l_i  ( l_q2                         ),
  .cfg_mq_i ( mq_q2                        ),
  .cfg_sh_i ( cfg_sh_i                     ),
  .trap_o   ( y                            )
);

//-----------------------------------------------------------------------------
// Muestras desde el re-arranque: el transitorio del arranque no dispara
//-----------------------------------------------------------------------------
reg [FW-1:0] fill, lleno_en;
reg          lleno;

always @(posedge adc_clk_i) begin
  lleno_en <= {{(FW-DAW){1'b0}}, k_q2} + {{(FW-DAW){1'b0}}, l_q2} + (LAT + 2);
  if (restart) begin
    fill  <= {FW{1'b0}};
    lleno <= 1'b0;
  end else begin
    if (adc_dv_i && !lleno) fill <= fill + 1'b1;
    lleno <= lleno || (fill >= lleno_en);
  end
end

//-----------------------------------------------------------------------------
// Schmitt, como el de mt_slope_trig pero solo positivo
//-----------------------------------------------------------------------------
reg signed [TW:0] thr_p, rearm_p;
reg               st, st_q;

always @(posedge adc_clk_i) begin
  thr_p   <= $signed({1'b0, cfg_thr_i});
  rearm_p <= $signed({1'b0, cfg_thr_i}) - $signed({1'b0, cfg_hyst_i});
end

wire signed [TW:0] y_x = {y[TW-1], y};

always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0) begin
  st     <= 1'b1;
  st_q   <= 1'b1;
  pz_p_o <= 1'b0;
end else begin
  if (!lleno) begin
    // arranque: "disparado" sin flanco, pide re-armar
    st   <= 1'b1;
    st_q <= 1'b1;
  end else begin
         if (y_x >= thr_p  ) st <= 1'b1;
    else if (y_x <  rearm_p) st <= 1'b0;
    st_q <= st;
  end
  pz_p_o <= st && !st_q;
end

endmodule
