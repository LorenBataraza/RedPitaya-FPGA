`timescale 1ns/1ps
//=============================================================================
// mca_slot — una ranura de medicion: un juego entero de acumuladores
//
// mca_window instancia N_ACC de estas. Cada una mide UNA ventana: la abre el
// asignador con un disparo, acumula la muestra mientras dura la compuerta y,
// al cerrar, se queda con el resultado hasta que el publicador lo toma. O sea
// que la ranura es a la vez el juego de acumuladores y el lugar de la cola de
// publicacion: con N_ACC = 1 se tiene el modo bloqueante de antes, y con mas
// ranuras se miden pulsos solapados.
//
//   LIBRE ──abre──► ABIERTA ──cierra (len = gate_long)──► CERRADA ──libera──► LIBRE
//                      └──── fuera de [amp_min, amp_max] ───────────────────► LIBRE
//
// LA MUESTRA LLEGA REGISTRADA (xc_i sale de un flop de mca_window). Es lo que
// hace gratis esta frontera con -flatten_hierarchy none: la suma de cada
// acumulador arranca de un registro, y las N copias no le cuelgan logica al
// camino de la resta de la base.
//
// LA COMPUERTA SE RETIENE AL ABRIR. La ventana que ya estaba abierta mide lo que
// se configuro cuando abrio, no una mezcla, aunque se toque gate_long a mitad de
// una corrida. Cada ranura cierra sola, con su len contra su g_long: no mira a
// las otras. Con la compuerta quieta dos ranuras cierran en muestras distintas,
// porque abren en muestras distintas (el asignador abre a lo sumo una por
// muestra); si gate_long cambia entre dos aperturas pueden cerrar en la MISMA,
// y mca_publish encola las dos (lo ejercita tb_mca_multi).
//
// Las reglas de acumulacion son las de la ventana unica de antes, una por una
// (ver la historia de cada una en git: mca_window.sv antes de las ranuras):
//
//   PICO con comparacion ESTRICTA (>): en un techo plano gana la PRIMERA
//   ocurrencia del maximo. Con >= el instante de pico se correria al final de la
//   meseta y el tiempo de subida saldria arbitrariamente largo.
//
//   CARGA. La muestra ya viene saturada a >= 0. Sin eso una cola con undershoot
//   resta de q_tot mientras q_tail sigue sumando, y se llega a q_tail > q_tot,
//   que rompe la premisa del divisor.
//
//   COLA. Arranca en la compuerta corta, medida desde el DISPARO: es lo que la
//   hace inmune al jitter del instante de pico.
//
//   VENTANA DE AMPLITUD evaluada un ciclo ANTES del cierre, con las restas
//   contra [min, max] llevadas en sombras (d_min, d_max). Era el camino critico
//   del bitstream; el razonamiento entero esta en el comentario del cuerpo.
//
// MARCAS DE SOLAPE. Una ventana que abre con otras abiertas, o dentro de la
// cual llega otro disparo, mide un pulso montado sobre otro: su carga esta
// contaminada. La ranura no lo corrige; lo deja escrito en el resultado para
// que el discriminador o el software decidan:
//   otras        ranuras abiertas cuando se decidio abrir esta
//   dt_prev      muestras desde el disparo anterior (haya abierto o no)
//   dt_next      muestras hasta el siguiente disparo DENTRO de la ventana, o
//                todo unos si no hubo
//   adentro      llego otro disparo dentro de la ventana
//   perdido      ...y al menos uno no encontro ranura libre
//
// LA MESETA DEL TRAPECIO, UNA POR FORMA DEL BANCO. mca_window corre NF
// trapecios (comunes a todas las ranuras), y la ranura suma la salida de cada
// uno sobre su propia ventana: las muestras con indice en [trap_ini, trap_fin)
// de esa forma, que mca_window ya corrio por la latencia del trapecio. Por forma
// tambien cuenta cuantas sumo: si la compuerta cerro antes de completar la
// ventana, el publicador lo ve y no publica un promedio parcial. Las NF sumas
// corren siempre en paralelo: la forma se elige al publicar, cuando ya se sabe
// si llego otro disparo adentro (dt_next).
//=============================================================================

module mca_slot #(
  parameter integer DW      = 14,  // ancho de muestra
  parameter integer QW      = 32,  // ancho de los acumuladores de carga
  parameter integer AMP_W   = 16,  // ancho de la amplitud emitida
  parameter integer LEN_W   = 16,  // ancho de los contadores de longitud
  parameter integer PUB_IDW = 16,  // bits del id de ventana
  parameter integer NW      = 4,   // bits de `otras`
  parameter integer TW      = 18,  // salida del trapecio, con signo
  parameter integer TNW     = 8,   // bits de la cuenta de la meseta (hasta 2^(TNW-1))
  parameter integer NF      = 1,   // formas del banco (>= 1 en los puertos)
  // Derivado: lo usan los puertos. No se sobreescribe.
  parameter integer TSW     = TW + TNW - 1
)(
  input                        clk_i            ,
  input                        rstn_i           ,

  // --- la muestra, relativa a la base y saturada a >= 0, REGISTRADA ---
  input             [DW-1:0]   xc_i             ,
  input                        val_i            ,

  // --- desde el asignador, alineado con la muestra ---
  input                        abre_i           ,  // esta ranura abre con ESTA muestra
  input                        disparo_i        ,  // hubo un disparo en esta muestra
  input                        perdido_i        ,  // ...y no encontro ranura libre
  input             [NW-1:0]   otras_i          ,  // ranuras abiertas al decidir abrir
  input             [LEN_W-1:0] dt_prev_i       ,  // muestras desde el disparo anterior
  input             [PUB_IDW-1:0] win_id_i      ,
  input                        libera_i         ,  // el publicador termino con esta

  // --- los trapecios, alineados con la muestra, y sus ventanas en la de la
  //     ranura: NF de cada uno, aplanados ---
  input             [NF*TW-1:0]    trap_i       ,
  input             [NF*LEN_W-1:0] trap_ini_i   ,
  input             [NF*LEN_W-1:0] trap_fin_i   ,

  // --- configuracion ---
  input             [LEN_W-1:0] cfg_gate_short_i,
  input             [LEN_W-1:0] cfg_gate_long_i ,
  input                        cfg_amp_src_i    ,  // 0=pico, 1=integral
  input             [4:0]      cfg_q_shift_i    ,
  input             [AMP_W-1:0] cfg_amp_min_i   ,
  input             [AMP_W-1:0] cfg_amp_max_i   ,
  // la ventana de amplitud ya pre-desplazada: la calcula mca_window una vez
  // para todas las ranuras, a partir de registros de configuracion
  input             [QW-1:0]   min_q_i          ,
  input             [QW-1:0]   max_q_i          ,
  input                        min_fuera_i      ,
  input                        sat_ok_i         ,

  // --- estado ---
  output                       libre_o          ,
  output                       abierta_o        ,
  output                       cerrada_o        ,
  output                       cierra_o         ,  // cierra con esta muestra (pulso)
  output                       acepta_o         ,  // ...y pasa la ventana de amplitud
  output                       solapada_o       ,  // la que cierra tiene marca de solape
  output                       estancada_o      ,  // abierta, vencida y sin muestras

  // --- resultado: vale desde el cierre hasta libera_i ---
  output            [AMP_W-1:0] amp_sel_o       ,
  output            [AMP_W-1:0] amp_int_o       ,
  output            [DW-1:0]   peak_o           ,
  output            [LEN_W-1:0] len_o           ,
  output            [LEN_W-1:0] t_peak_o        ,
  output            [QW-1:0]   q_tot_o          ,
  output            [QW-1:0]   q_tail_o         ,
  output            [PUB_IDW-1:0] win_id_o      ,
  output            [LEN_W-1:0] dt_prev_o       ,
  output            [LEN_W-1:0] dt_next_o       ,
  output            [NW-1:0]   otras_o          ,
  output                       adentro_o        ,
  output                       perdido_o        ,
  output            [NF*TSW-1:0] trap_sum_o     ,  // suma sobre cada meseta (con signo)
  output            [NF*TNW-1:0] trap_n_o          // ...y cuantas muestras sumo cada una
);

localparam [1:0] L_LIBRE = 2'd0, L_ABIERTA = 2'd1, L_CERRADA = 2'd2;

reg [1:0]         est;
reg [LEN_W-1:0]   len;            // muestras desde el disparo
reg [LEN_W-1:0]   t_peak;         // indice de la muestra de pico
reg [LEN_W-1:0]   g_short, g_long;
reg [DW-1:0]      peak;
reg [QW-1:0]      q_tot, q_tail;
reg [PUB_IDW-1:0] win_id;
reg [LEN_W-1:0]   dt_prev, dt_next;
reg [NW-1:0]      otras;
reg               adentro, perdido;

wire abierta = (est == L_ABIERTA);
wire abre    = abre_i && val_i;
wire cierre  = abierta && val_i && (len >= g_long);
wire acumula = abierta && val_i && !cierre;
wire in_tail = abierta && (len >= g_short);

//-----------------------------------------------------------------------------
// Valor SIGUIENTE de los acumuladores, como cables
//-----------------------------------------------------------------------------
// Son el D de los registros y, a la vez, la entrada del comparador de ventana
// registrado de mas abajo.
//
// LAS SUMAS VAN CON KEEP. Sin el atributo Vivado pliega la apertura DENTRO del
// sumador, como (abre ? 0 : q_tot) + xc, y el decode de apertura pasa a
// recorrer la cadena de carry entera (q_tot fue de +0.470 a -0.148 ns en la OOC
// cuando paso por primera vez). Con el sumador fijado, la apertura vuelve a ser
// un mux despues de la suma.
(* keep = "true" *) wire [QW-1:0] q_sum      = q_tot  + {{(QW-DW){1'b0}}, xc_i};
(* keep = "true" *) wire [QW-1:0] q_tail_sum = q_tail + {{(QW-DW){1'b0}}, xc_i};
wire [QW-1:0] q_tail_d = abre                 ? {QW{1'b0}}
                       : (acumula && in_tail) ? q_tail_sum
                       :                        q_tail;
wire [QW-1:0] q_tot_d  = abre    ? {{(QW-DW){1'b0}}, xc_i}
                       : acumula ? q_sum
                       :           q_tot;
wire          nuevo_pico = acumula && (xc_i > peak);
wire [DW-1:0] peak_d   = (abre || nuevo_pico) ? xc_i : peak;

// Las mesetas, una por forma: con `len` = indice de la muestra que se esta
// acumulando. Se escriben todos los ciclos, como los acumuladores de carga.
genvar gf;
generate for (gf = 0; gf < NF; gf = gf + 1) begin : g_meseta
  wire signed [TW-1:0]  t_f   = trap_i    [gf*TW    +: TW];
  wire        [LEN_W-1:0] ini_f = trap_ini_i[gf*LEN_W +: LEN_W];
  wire        [LEN_W-1:0] fin_f = trap_fin_i[gf*LEN_W +: LEN_W];
  reg  signed [TSW-1:0] suma;
  reg         [TNW-1:0] cuenta;
  wire en_meseta = acumula && (len >= ini_f) && (len < fin_f);
  always @(posedge clk_i)
    if (!rstn_i) begin
      suma <= {TSW{1'b0}}; cuenta <= {TNW{1'b0}};
    end else if (abre) begin
      suma <= {TSW{1'b0}}; cuenta <= {TNW{1'b0}};
    end else if (en_meseta) begin
      suma   <= suma + {{(TSW-TW){t_f[TW-1]}}, t_f};
      cuenta <= cuenta + {{(TNW-1){1'b0}}, 1'b1};
    end
  assign trap_sum_o[gf*TSW +: TSW] = suma;
  assign trap_n_o  [gf*TNW +: TNW] = cuenta;
end endgenerate

//-----------------------------------------------------------------------------
// Amplitud: pico o integral, con saturacion a AMP_W bits
//-----------------------------------------------------------------------------
wire [QW-1:0]    q_shifted = q_tot >> cfg_q_shift_i;
wire             q_ovf     = |q_shifted[QW-1:AMP_W];
wire [AMP_W-1:0] amp_int   = q_ovf ? {AMP_W{1'b1}} : q_shifted[AMP_W-1:0];
wire [AMP_W-1:0] amp_peak  = {{(AMP_W-DW){1'b0}}, peak};
assign amp_int_o = amp_int;
assign amp_sel_o = cfg_amp_src_i ? amp_int : amp_peak;

//-----------------------------------------------------------------------------
// Ventana de amplitud [amp_min, amp_max]: evaluada un ciclo ANTES del cierre
//-----------------------------------------------------------------------------
// Tres hechos la sacan del ciclo de cierre sin agregar latencia:
//
//  1. En el ciclo de cierre q_tot NO se acumula (`acumula` incluye !cierre), asi
//     que su valor final es el que se escribio en el flanco anterior.
//  2. Comparar la version DESPLAZADA contra [min, max] es lo mismo que comparar
//     q_tot sin desplazar contra umbrales pre-desplazados:
//         sat(q_tot >> s) >= min  <=>  q_tot >= (min << s)
//         sat(q_tot >> s) <= max  <=>  q_tot <= ((max+1) << s) - 1
//     con UNA excepcion, la saturacion: amp_int = 2^AMP_W-1 se acepta solo si
//     max == 2^AMP_W-1, y en esa rama la segunda desigualdad da falso. Por eso
//     sat_ok, que la restituye exactamente.
//  3. Los umbrales pre-desplazados dependen solo de registros de configuracion:
//     los calcula mca_window una vez, registrados, para todas las ranuras.
//
// La entrada del comparador es especulativa: coincide con el valor siguiente de
// q_tot en los ciclos que importan (el previo a un cierre, y el de apertura,
// que es el previo al cierre de una ventana de una muestra) y difiere solo en
// ciclos cuyo resultado nunca se lee. Y para la integral ni siquiera hay
// comparador: las sombras d_min = q_tot - min_q y d_max = max_q - q_tot siguen
// la misma regla que q_tot, y el comparador es el bit de signo de UNA suma.
//
// Al abrir, la muestra ya viene saturada a >= 0. No cambia el resultado: si la
// muestra relativa a la base era negativa, x >= min es falso salvo min == 0 y
// x <= max es verdadero, igual que con 0. Y con la muestra >= 0 el caso min == 0
// sale solo de la resta (xc - 0 >= 0): no hace falta el termino aparte que
// tenia la ventana unica, que comparaba la muestra sin saturar.
localparam integer DQ_W = QW + 2;                 // diferencias con signo, sin desborde

wire [AMP_W-1:0] xc_w   = {{(AMP_W-DW){1'b0}}, xc_i};
wire [AMP_W-1:0] peak_w = {{(AMP_W-DW){1'b0}}, peak};
wire xc_ge_min = (xc_w   >= cfg_amp_min_i), xc_le_max = (xc_w   <= cfg_amp_max_i);
wire pk_ge_min = (peak_w >= cfg_amp_min_i), pk_le_max = (peak_w <= cfg_amp_max_i);
// max(peak, xc) con val_i, peak sin muestra, xc al abrir
wire peak_ok_spec = !abierta ? (xc_ge_min && xc_le_max)
                  : ((pk_ge_min || (val_i && xc_ge_min)) &&
                     (pk_le_max && (!val_i || xc_le_max)));

reg  signed [DQ_W-1:0] d_min, d_max;
reg                    ge_min_r, le_max_r, peak_ok_r;
wire signed [DQ_W-1:0] xc_s    = {{(DQ_W-DW){1'b0}}, xc_i};
wire signed [DQ_W-1:0] min_q_s = {{(DQ_W-QW){1'b0}}, min_q_i};
wire signed [DQ_W-1:0] max_q_s = {{(DQ_W-QW){1'b0}}, max_q_i};
wire signed [DQ_W-1:0] xc_menos_min = xc_s - min_q_s;
wire signed [DQ_W-1:0] max_menos_xc = max_q_s - xc_s;
wire signed [DQ_W-1:0] d_min_d = abre    ? xc_menos_min
                               : acumula ? d_min + xc_s
                               :           d_min;
wire signed [DQ_W-1:0] d_max_d = abre    ? max_menos_xc
                               : acumula ? d_max - xc_s
                               :           d_max;
wire signed [DQ_W-1:0] dmin_spec = val_i ? d_min + xc_s : d_min;
wire signed [DQ_W-1:0] dmax_spec = val_i ? d_max - xc_s : d_max;

wire ge_min_spec = !abierta ? !xc_menos_min[DQ_W-1]
                            : !dmin_spec[DQ_W-1];
wire le_max_spec = !abierta ? !max_menos_xc[DQ_W-1]
                            : !dmax_spec[DQ_W-1];

wire amp_ok = cfg_amp_src_i ? (ge_min_r && (le_max_r || sat_ok_i)) : peak_ok_r;

//-----------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (!rstn_i) begin
    est <= L_LIBRE;
    len <= {LEN_W{1'b0}}; t_peak <= {LEN_W{1'b0}};
    g_short <= {LEN_W{1'b0}}; g_long <= {LEN_W{1'b0}};
    peak <= {DW{1'b0}}; q_tot <= {QW{1'b0}}; q_tail <= {QW{1'b0}};
    win_id <= {PUB_IDW{1'b0}};
    dt_prev <= {LEN_W{1'b0}}; dt_next <= {LEN_W{1'b1}};
    otras <= {NW{1'b0}}; adentro <= 1'b0; perdido <= 1'b0;
    d_min <= {DQ_W{1'b0}}; d_max <= {DQ_W{1'b0}};
    ge_min_r <= 1'b0; le_max_r <= 1'b0; peak_ok_r <= 1'b0;
  end else begin
    // Los acumuladores se escriben desde sus cables de valor siguiente, todos
    // los ciclos: el estado decide QUE valen, no cuando se escriben.
    q_tot  <= q_tot_d;
    q_tail <= q_tail_d;
    peak   <= peak_d;
    d_min  <= d_min_d;
    d_max  <= d_max_d;
    ge_min_r  <= !min_fuera_i && ge_min_spec;
    le_max_r  <= le_max_spec;
    peak_ok_r <= peak_ok_spec;

    case (est)
      L_LIBRE: if (abre) begin
        est     <= L_ABIERTA;
        len     <= {{(LEN_W-1){1'b0}}, 1'b1};
        t_peak  <= {LEN_W{1'b0}};
        g_short <= cfg_gate_short_i;
        g_long  <= cfg_gate_long_i;
        win_id  <= win_id_i;
        dt_prev <= dt_prev_i;
        dt_next <= {LEN_W{1'b1}};
        otras   <= otras_i;
        adentro <= 1'b0;
        perdido <= 1'b0;
      end

      L_ABIERTA: if (val_i) begin
        if (cierre) begin
          est <= amp_ok ? L_CERRADA : L_LIBRE;
        end else begin
          len <= len + {{(LEN_W-1){1'b0}}, 1'b1};
          if (nuevo_pico) t_peak <= len;
          // Otro disparo DENTRO de la ventana (la muestra de cierre ya no es
          // de la ventana, y el disparo que abrio esta ranura llega con la
          // ranura todavia libre: ninguno de los dos entra aca).
          if (disparo_i) begin
            adentro <= 1'b1;
            if (dt_next == {LEN_W{1'b1}}) dt_next <= len;
          end
          if (perdido_i) perdido <= 1'b1;
        end
      end

      L_CERRADA: if (libera_i) est <= L_LIBRE;

      default: est <= L_LIBRE;
    endcase
  end
end

assign libre_o     = (est == L_LIBRE);
assign abierta_o   = abierta;
assign cerrada_o   = (est == L_CERRADA);
assign cierra_o    = cierre;
assign acepta_o    = cierre && amp_ok;
assign solapada_o  = (otras != {NW{1'b0}}) || adentro;
// Una ventana vencida que no cierra porque no llegan muestras: el watchdog de
// linea de base avisa si esto se vuelve permanente.
assign estancada_o = abierta && !val_i && (len >= g_long);

assign peak_o    = peak;
assign len_o     = len;
assign t_peak_o  = t_peak;
assign q_tot_o   = q_tot;
assign q_tail_o  = q_tail;
assign win_id_o  = win_id;
assign dt_prev_o = dt_prev;
assign dt_next_o = dt_next;
assign otras_o   = otras;
assign adentro_o = adentro;
assign perdido_o = perdido;

endmodule
