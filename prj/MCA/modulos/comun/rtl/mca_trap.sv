`timescale 1ns/1ps
//=============================================================================
// mca_trap — conformado trapezoidal de Jordanov-Knoll, en enteros EXACTOS
//
//     d[n] = v[n] - v[n-k] - v[n-l] + v[n-k-l]          l = k + m
//     p[n] = p[n-1] + d[n]
//     r[n] = p[n]*2^MF + Mq*d[n]                         Mq = M * 2^MF
//     s[n] = s[n-1] + r[n]
//
// Es estimadores.trapecio (software/API/modelo_rtl) multiplicado por 2^MF: con
// M = Mq/2^MF la cuenta en punto flotante es exacta mientras s < 2^53, asi que
// el modelo de Python es la referencia bit a bit.
//
// QUE HACE. Un pulso exponencial A*e^(-n/tau) sale como un trapecio de subida k,
// meseta m y bajada k, de altura 2^MF*A*k*(1+M), si M = 1/(e^(1/tau) - 1): el
// termino M*d cancela el polo de la cola (polo-cero). La salida VUELVE A CERO
// 2k+m muestras despues del pie, aunque la cola de la entrada dure mucho mas.
// Por eso dos pulsos separados k+m o mas tienen mesetas limpias aunque se pisen
// en la entrada: es la correccion de lo que las ranuras de mca_window solo
// marcan. Con M = 0 el trapecio es el de un impulso: el area del pulso.
//
// POR QUE ENTEROS EXACTOS, Y EL CLR. La forma recursiva es un FIR solo si el
// estado (p, s) es consistente con lo que hay en las lineas de retardo. Si no lo
// es —al salir del reset, al cambiar k, m o M— a p le queda un escalon
// PERMANENTE y s, que lo integra, deriva sin fin hasta desbordar. Por eso:
//   - nada se redondea: la recursion en enteros reproduce el FIR exacto;
//   - clr_i (lo pulsa mca_top al escribir k, m o M y con el clear del MCA)
//     pone a cero el estado, y hasta que cada linea se llena su salida cuenta
//     como CERO. Es la convencion v[<0] = 0 del modelo, aplicada desde el clr:
//     el contenido viejo de la BRAM no entra nunca a la cuenta.
//
// LAS LINEAS DE RETARDO VAN EN BRAM (tres RAMB18 de 1024 x XW): v por k, v por
// l, y v por l retrasada otra vez por k. Con SRL, 1024 muestras de profundidad
// variable serian ~700 LUT de memoria mas los multiplexores.
//
// LO COMPARTEN EL MCA Y EL MULTITRIGGER (por eso vive en comun/). El MCA lo usa
// para F_TRAP y el banco de formas, con lineas de 1024 en BRAM; mt_pz_trig lo
// usa como disparo (k = 2, m = 1), con lineas de 32 en LUT: RAM_STYLE elige.
//
// TODO AVANZA CON val_i. Cada etapa es un registro con habilitacion, y la BRAM
// sostiene su salida entre lecturas, asi que la latencia es de LAT MUESTRAS sea
// cual sea la decimacion: con la muestra n en la entrada, trap_o vale s[n-LAT].
// mca_window usa LAT para alinear la meseta con la ventana de cada ranura.
//=============================================================================

module mca_trap #(
  parameter integer XW  = 15,   // muestra relativa a la base, con signo
  parameter integer DAW = 10,   // log2 de la profundidad de las lineas de retardo
  parameter integer MW  = 20,   // bits de Mq, sin signo
  parameter integer MF  = 4,    // ...de los cuales fraccionarios
  parameter integer SW  = 48,   // acumulador s
  parameter integer TW  = 18,   // salida, con signo y saturada
  parameter integer LAT = 8,    // latencia en muestras: NO se elige, se declara
  parameter         RAM_STYLE = "block"  // lineas en BRAM, o "distributed" (LUT)
)(
  input                       clk_i    ,
  input                       rstn_i   ,
  input                       clr_i    ,   // reinicia el estado (pulso)

  input      signed [XW-1:0]  x_i      ,   // muestra relativa a la base, registrada
  input                       val_i    ,

  input             [DAW-1:0] cfg_k_i  ,   // subida, 1 .. 2^DAW-1
  input             [DAW-1:0] cfg_l_i  ,   // k + meseta, k .. 2^DAW-1
  input             [MW-1:0]  cfg_mq_i ,   // constante polo-cero, M * 2^MF
  input             [5:0]     cfg_sh_i ,   // corrimiento aritmetico de la salida

  output     signed [TW-1:0]  trap_o       // s[n-LAT] >>> sh, saturada a TW bits
);

localparam integer D   = 1 << DAW;
localparam integer CW  = DAW + 1;               // indice desde el clr: llega a k+l
localparam integer DXW = XW + 2;                // d: suma de cuatro muestras
localparam integer PW  = XW + DAW + 1;          // |p| <= 2*k*2^(XW-1)
localparam integer MLW = MW + 1 + DXW;          // Mq*d con signo
localparam integer RW  = ((PW + MF > MLW) ? PW + MF : MLW) + 1;

// La latencia que resulta de las etapas de abajo. Si alguien agrega una, el
// elaborador lo dice en vez de desalinear la meseta en silencio.
localparam integer ETAPAS = 8;
generate if (LAT != ETAPAS) begin : g_lat_mal
  LAT_no_coincide_con_las_etapas_de_mca_trap u_error ();
end endgenerate

//-----------------------------------------------------------------------------
// Lineas de retardo
//-----------------------------------------------------------------------------
// Las tres comparten el puntero de escritura. En el flanco de la muestra n:
//   mem_k[wp]  <= v[n]          rd_k  <= v[n-k]
//   mem_l[wp]  <= v[n]          rd_l  <= v[n-l]
//   mem_kl[wp] <= rd_l (la de la muestra n-1)   rd_kl <= v[n-1-l-k]
// y la etapa 2 junta lo de la etapa 1 de n-1 (v - v[n-k] y v[n-l]) con rd_kl:
// las cuatro de la MISMA muestra. Lectura y escritura nunca chocan: k y l
// valen al menos 1.
//
// El atributo de estilo va en cada rama del generate: Vivado no toma un
// parametro como valor de ram_style.
reg        [DAW-1:0] wp;
reg signed [XW-1:0]  rd_k, rd_l, rd_kl;

wire [DAW-1:0] a_k = wp - cfg_k_i;
wire [DAW-1:0] a_l = wp - cfg_l_i;

generate if (RAM_STYLE == "distributed") begin : g_lut
  (* ram_style = "distributed" *) reg signed [XW-1:0] mem_k  [0:D-1];
  (* ram_style = "distributed" *) reg signed [XW-1:0] mem_l  [0:D-1];
  (* ram_style = "distributed" *) reg signed [XW-1:0] mem_kl [0:D-1];
  always @(posedge clk_i)
    if (val_i) begin
      mem_k [wp] <= x_i;
      mem_l [wp] <= x_i;
      mem_kl[wp] <= rd_l;
      rd_k  <= mem_k [a_k];
      rd_l  <= mem_l [a_l];
      rd_kl <= mem_kl[a_k];
    end
end else begin : g_bram
  (* ram_style = "block" *) reg signed [XW-1:0] mem_k  [0:D-1];
  (* ram_style = "block" *) reg signed [XW-1:0] mem_l  [0:D-1];
  (* ram_style = "block" *) reg signed [XW-1:0] mem_kl [0:D-1];
  always @(posedge clk_i)
    if (val_i) begin
      mem_k [wp] <= x_i;
      mem_l [wp] <= x_i;
      mem_kl[wp] <= rd_l;
      rd_k  <= mem_k [a_k];
      rd_l  <= mem_l [a_l];
      rd_kl <= mem_kl[a_k];
    end
end endgenerate

//-----------------------------------------------------------------------------
// La cuenta
//-----------------------------------------------------------------------------
// v[n-j] con n-j < 0 vale cero: la linea todavia no se lleno desde el clr. Las
// tres comparaciones del indice se hacen en la ENTRADA y viajan como banderas
// registradas junto con la muestra, y v - v[n-k] se resta en la etapa 2: asi a
// d le queda una sola suma ternaria antes del DSP. Con las comparaciones en la
// etapa 3 el camino k -> comparador -> mux -> suma -> DSP no cerraba
// (-0.201 ns en la OOC, 12 niveles).
reg        [CW-1:0]  cnt;                        // indice de la muestra desde el clr
reg        [CW-1:0]  kl;                         // k + l, registrado
reg                  fk1, fl1, fkl1, fkl2;       // v[n-k], v[n-l], v[n-k-l] existen
reg signed [XW-1:0]  v1, l2;
reg signed [XW:0]    e2;                         // v - v[n-k]
reg signed [DXW-1:0] d3, d4;
reg signed [PW-1:0]  p4;
reg signed [RW-1:0]  r5;
reg signed [SW-1:0]  s6, q7;
reg signed [TW-1:0]  t8;

wire signed [XW-1:0] gk  = fk1  ? rd_k  : {XW{1'b0}};
wire signed [XW-1:0] gkl = fkl2 ? rd_kl : {XW{1'b0}};

wire signed [XW:0]    e_n = $signed({v1[XW-1], v1}) - $signed({gk[XW-1], gk});
wire signed [DXW-1:0] d_n = $signed({e2[XW], e2}) - $signed({{2{l2[XW-1]}}, l2})
                          + $signed({{2{gkl[XW-1]}}, gkl});

wire signed [MW:0]    mq_s  = $signed({1'b0, cfg_mq_i});
wire signed [RW-1:0]  p_esc = $signed(p4) <<< MF;
wire signed [RW-1:0]  r_n   = p_esc + mq_s * d4;

// Saturacion a TW bits: los bits por encima del de signo de la salida tienen
// que ser todos iguales a el.
wire [SW-TW:0] alto = q7[SW-1:TW-1];
wire           sat  = !((&alto) || !(|alto));
wire signed [TW-1:0] t_n = !sat    ? q7[TW-1:0]
                         : q7[SW-1] ? {1'b1, {(TW-1){1'b0}}}
                         :            {1'b0, {(TW-1){1'b1}}};

// kl arranca en TODO UNOS, no en cero: en el primer flanco despues del reset
// todavia vale lo del reset, y con cero `cnt >= kl` daba verdadero con cnt = 0,
// asi que entraba a p lo que hubiera en la BRAM sin escribir (en simulacion, X;
// en la placa, un escalon permanente en p). Con todo unos da falso, y al flanco
// siguiente kl ya es k + l. cnt no llega a todo unos antes: tarda 2^CW muestras.
always @(posedge clk_i)
  if (!rstn_i) kl <= {CW{1'b1}};
  else         kl <= {1'b0, cfg_k_i} + {1'b0, cfg_l_i};

always @(posedge clk_i) begin
  if (!rstn_i || clr_i) begin
    wp  <= {DAW{1'b0}};
    cnt <= {CW{1'b0}};
    fk1 <= 1'b0; fl1 <= 1'b0; fkl1 <= 1'b0; fkl2 <= 1'b0;
    v1  <= {XW{1'b0}}; l2 <= {XW{1'b0}}; e2 <= {(XW+1){1'b0}};
    d3  <= {DXW{1'b0}}; d4 <= {DXW{1'b0}};
    p4  <= {PW{1'b0}}; r5 <= {RW{1'b0}};
    s6  <= {SW{1'b0}}; q7 <= {SW{1'b0}}; t8 <= {TW{1'b0}};
  end else if (val_i) begin
    wp  <= wp + {{(DAW-1){1'b0}}, 1'b1};
    cnt <= (&cnt) ? cnt : cnt + {{(CW-1){1'b0}}, 1'b1};
    // etapa 1: la muestra, y cuales de sus retrasadas existen; las lecturas
    // de la BRAM, arriba
    v1   <= x_i;
    fk1  <= (cnt >= {1'b0, cfg_k_i});
    fl1  <= (cnt >= {1'b0, cfg_l_i});
    fkl1 <= (cnt >= kl);
    // etapa 2: v - v[n-k] y v[n-l]; v[n-k-l] sale de la BRAM en esta etapa
    e2   <= e_n;
    l2   <= fl1 ? rd_l : {XW{1'b0}};
    fkl2 <= fkl1;
    // etapa 3: la doble diferencia
    d3 <= d_n;
    // etapa 4: el primer integrador
    p4 <= p4 + {{(PW-DXW){d3[DXW-1]}}, d3};
    d4 <= d3;
    // etapa 5: polo-cero (un DSP48: Mq*d mas el corrimiento de p por C)
    r5 <= r_n;
    // etapa 6: el segundo integrador
    s6 <= s6 + {{(SW-RW){r5[RW-1]}}, r5};
    // etapas 7 y 8: corrimiento y saturacion, separados por timing
    q7 <= s6 >>> cfg_sh_i;
    t8 <= t_n;
  end
end

assign trap_o = t8;

endmodule
