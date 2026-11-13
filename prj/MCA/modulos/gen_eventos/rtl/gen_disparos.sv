`timescale 1ns/1ps
//=============================================================================
// gen_disparos — el motor de disparos de los dos generadores:
//   gen_eventos (dentro del event_ring, para medir el ring) y
//   gen_pulsos  (en el lugar del ASG, para el multitrigger y el MCA).
//
// Decide en cada ciclo si dispara, de una de dos maneras:
//
//   PERIODICO (aleat_i = 0): uno cada PERIODO ciclos.
//   ALEATORIO (aleat_i = 1): con probabilidad UMBRAL / 2^32 por ciclo, y despues
//   espera DT_MIN - 1 ciclos. Los intervalos son geometricos, o sea un Poisson
//   discreto con tiempo muerto no paralizable:
//       intervalo medio = (DT_MIN - 1) + 2^32 / UMBRAL   ciclos
//   El numero aleatorio es un xorshift32 (Marsaglia 2003), un paso por ciclo.
//   NO un LFSR de Fibonacci: dos estados seguidos de un LFSR son la misma
//   palabra corrida un bit, y comparar contra un umbral daria rafagas.
//
// El disparo decidido en un ciclo (disp_o) SALE en el siguiente (pulso_o), y
// solo si run_i esta alto en ESE ciclo: es lo que necesita el ring, que en
// DRAINING ya no acepta disparos. cnt_o cuenta los que salen.
//
// El estado (xorshift, contador del periodo, cnt_o) se reinicia al prender
// en_i y al subir run_i, y avanza solo con los dos altos y sin haber llegado a
// N: con la misma SEMILLA, los disparos caen siempre en el mismo ciclo. El
// modelo (modelos/python_model/gen_eventos_model.py, `disparos`) los predice.
//
// La captura del ring y el multitrigger toman el disparo por FLANCO: dos pulsos
// seguidos serian uno. Por eso PERIODO y DT_MIN valen 2 como minimo.
//
// Los puertos hold_o y trig_gen_o son para las assertions y los testbenches:
// la sintesis los poda si nadie los usa.
//=============================================================================
module gen_disparos (
  input             clk_i,
  input             rstn_i,

  input             en_i,         // el generador prendido
  input             run_i,        // el consumidor acepta disparos (1 si no importa)

  // configuracion
  input             aleat_i,
  input      [31:0] periodo_i,
  input      [31:0] umbral_i,
  input      [15:0] dt_min_i,
  input      [31:0] n_i,          // cuantos disparos; 0 = sin fin
  input      [31:0] semilla_i,    // 0 usa 0x2545F491 (el xorshift no sale del 0)

  output            arranque_o,   // el ciclo en que se reinicia el estado
  output            disp_o,       // el disparo decidido en este ciclo
  output            pulso_o,      // el disparo que sale (decidido el ciclo anterior)
  output reg [31:0] cnt_o,        // disparos que salieron desde el arranque
  output            activo_o,     // generando
  output            hecho_o,      // llego a N

  output reg [15:0] hold_o,       // ciclos de espera que quedan (modo aleatorio)
  output reg        trig_gen_o    // el decidido el ciclo anterior, sin el gateo de run_i
);

localparam [31:0] SEMILLA_0 = 32'h2545_F491;

// Los minimos de 2, menos 1, registrados: asi la comparacion y la resta no
// quedan en el camino del contador. Un cambio de configuracion entra un ciclo
// mas tarde.
reg [31:0] per_m1;      // max(PERIODO, 2) - 1
reg [15:0] dtm_m1;      // max(DT_MIN, 2) - 1
always @(posedge clk_i) begin
  per_m1 <= (periodo_i < 32'd2) ? 32'd1 : periodo_i - 32'd1;
  dtm_m1 <= (dt_min_i  < 16'd2) ? 16'd1 : dt_min_i  - 16'd1;
end

//-----------------------------------------------------------------------------
// Arranque: al prender en_i o al subir run_i
//-----------------------------------------------------------------------------
reg en_d, run_d;
always @(posedge clk_i) begin
  if (!rstn_i) begin en_d <= 1'b0; run_d <= 1'b0; end
  else         begin en_d <= en_i; run_d <= run_i; end
end
assign arranque_o = (en_i && !en_d) || (run_i && !run_d);

//-----------------------------------------------------------------------------
// El motor
//-----------------------------------------------------------------------------
reg  [31:0] x;          // xorshift32
reg  [31:0] per_cnt;    // ciclos que faltan, modo periodico

wire [31:0] x1 = x  ^ (x  << 13);
wire [31:0] x2 = x1 ^ (x1 >> 17);
wire [31:0] xn = x2 ^ (x2 << 5);

assign hecho_o  = (n_i != 32'd0) && (cnt_o >= n_i);
assign activo_o = en_i && run_i && !hecho_o;
assign disp_o   = activo_o && (aleat_i ? ((hold_o == 16'd0) && (x < umbral_i))
                                       : (per_cnt == 32'd0));

// El pulso sale un ciclo despues de decidirse, y solo con run_i en ESE ciclo.
assign pulso_o = en_i && trig_gen_o && run_i;

always @(posedge clk_i) begin
  if (!rstn_i || arranque_o) begin
    x          <= (semilla_i == 32'd0) ? SEMILLA_0 : semilla_i;
    per_cnt    <= per_m1;
    hold_o     <= 16'd0;
    trig_gen_o <= 1'b0;
    cnt_o      <= 32'd0;
  end else begin
    trig_gen_o <= disp_o;
    if (pulso_o) cnt_o <= cnt_o + 32'd1;

    if (activo_o) begin
      x <= xn;
      if (aleat_i) begin
        // dt_min - 1 ciclos sin disparar: el siguiente puede caer a dt_min
        if (disp_o)                hold_o <= dtm_m1;
        else if (hold_o != 16'd0)  hold_o <= hold_o - 16'd1;
      end else begin
        per_cnt <= (per_cnt == 32'd0) ? per_m1 : per_cnt - 32'd1;
      end
    end
  end
end

endmodule
