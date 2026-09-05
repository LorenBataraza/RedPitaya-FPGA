`timescale 1ns/1ps
//=============================================================================
// mca_div_restore — divisor restaurador para el factor de forma (PSD)
//
// Calcula  q = floor( num * 2^Q_W / den )  con num < den, o sea la fracción
// num/den expresada en Q_W bits. Se usa para  PSD = Q_cola / Q_total, donde
// el resultado ES directamente el índice de bin del eje de forma.
//
// Truco: como num < den, arrancando con rem = num y haciendo
//        rem = 2*rem;  if (rem >= den) { rem -= den; q |= 1; }
// se obtiene un bit de cociente por iteración, así que hacen falta
// EXACTAMENTE Q_W iteraciones sin importar el ancho de los operandos
// (no hace falta normalizar previamente). Con Q_W=6 son 6 ciclos y cero DSP.
//
// Invariante: rem < den en todo momento. Inicialmente rem=num<den; y si
// rem2=2*rem >= den entonces rem2-den < den (porque rem2 < 2*den). Por eso
// `rem` entra en D_W bits aunque el intermedio `rem2` necesite D_W+1.
//
// Latencia FIJA de Q_W ciclos para TODOS los casos, incluidos los de error.
// Es deliberado: hace predecible el tiempo muerto por evento, que es uno de
// los parámetros a caracterizar del MCA.
//
// Casos borde (los tres rompen si no se tratan explícitamente):
//   den == 0  -> err_o. Sin esta guarda `rem >= 0` da siempre true y el
//                cociente sale todo unos: todos esos eventos caerían en el
//                bin superior del eje de forma.
//   num >= den-> sat_o y q = 2^Q_W-1. Sin saturar, num==den da 2^Q_W que no
//                entra en Q_W bits y ENVUELVE A 0, o sea manda el evento al
//                extremo OPUESTO del eje. Es el modo de falla peligroso.
//   num == 0  -> q = 0, sin flags. Es un resultado válido.
//=============================================================================

module mca_div_restore #(
  parameter integer D_W = 32,   // ancho de numerador y denominador
  parameter integer Q_W = 6     // bits de cociente (= bits del eje PSD)
)(
  input                    clk_i   ,
  input                    rstn_i  ,   // reset síncrono activo-bajo

  input                    start_i ,   // pulso de arranque (ignorado si busy)
  input      [D_W-1:0]     num_i   ,   // numerador   (Q_cola)
  input      [D_W-1:0]     den_i   ,   // denominador (Q_total)

  output reg [Q_W-1:0]     q_o     ,   // cociente en Q_W bits
  output reg               valid_o ,   // pulso de 1 ciclo: q_o/err_o/sat_o válidos
  output reg               err_o   ,   // den_i == 0     -> rechazar el evento
  output reg               sat_o   ,   // num_i >= den_i -> q_o saturado
  output                   busy_o
);

localparam integer CNT_W = (Q_W > 1) ? $clog2(Q_W+1) : 1;

reg  [D_W-1:0]   rem   ;   // resto parcial, siempre < den_r
reg  [D_W-1:0]   den_r ;
reg  [Q_W-1:0]   quo   ;
reg  [CNT_W-1:0] cnt   ;   // iteraciones que faltan
reg              busy  ;
reg              err_l ;   // flags latcheados en el arranque
reg              sat_l ;

assign busy_o = busy;

// 2*rem necesita un bit más que rem
wire [D_W:0] rem2    = {rem, 1'b0};
wire         ge_den  = (rem2 >= {1'b0, den_r});

always @(posedge clk_i) begin
  if (!rstn_i) begin
    rem     <= {D_W{1'b0}};
    den_r   <= {D_W{1'b0}};
    quo     <= {Q_W{1'b0}};
    cnt     <= {CNT_W{1'b0}};
    busy    <= 1'b0;
    err_l   <= 1'b0;
    sat_l   <= 1'b0;
    q_o     <= {Q_W{1'b0}};
    valid_o <= 1'b0;
    err_o   <= 1'b0;
    sat_o   <= 1'b0;
  end else begin
    valid_o <= 1'b0;                      // valid_o es un pulso de 1 ciclo

    if (!busy) begin
      if (start_i) begin
        // Los casos borde se detectan acá y se propagan por los flags, pero
        // la iteración se corre igual para que la latencia sea constante.
        err_l <= (den_i == {D_W{1'b0}});
        sat_l <= (num_i >= den_i) && (den_i != {D_W{1'b0}});
        rem   <= num_i;
        den_r <= den_i;
        quo   <= {Q_W{1'b0}};
        cnt   <= Q_W[CNT_W-1:0];
        busy  <= 1'b1;
      end
    end else begin
      // Una iteración de división restauradora por ciclo.
      if (ge_den) begin
        rem <= rem2[D_W-1:0] - den_r;
        quo <= {quo[Q_W-2:0], 1'b1};
      end else begin
        rem <= rem2[D_W-1:0];
        quo <= {quo[Q_W-2:0], 1'b0};
      end

      if (cnt == {{(CNT_W-1){1'b0}}, 1'b1}) begin   // última iteración
        busy    <= 1'b0;
        valid_o <= 1'b1;
        err_o   <= err_l;
        sat_o   <= sat_l;
        // El cociente calculado sólo vale si no hubo caso borde.
        if (err_l)      q_o <= {Q_W{1'b0}};
        else if (sat_l) q_o <= {Q_W{1'b1}};
        else            q_o <= ge_den ? {quo[Q_W-2:0], 1'b1} : {quo[Q_W-2:0], 1'b0};
      end
      cnt <= cnt - {{(CNT_W-1){1'b0}}, 1'b1};
    end
  end
end

endmodule
