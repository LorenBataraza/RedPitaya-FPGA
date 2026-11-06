`timescale 1ns/1ps
//=============================================================================
// mca_baseline — línea de base del extractor: seguidor IIR o base fija
//
// Es la decision D3 (cfg_bl_auto) de la vista general
// (docs/mca/vista_general_mca.md). Las dos opciones conviven y la salida es un
// REGISTRO: mca_window la resta de la muestra (x = dat - base), y todo lo que
// acumulan las ranuras es relativo a la base.
//
// LÍNEA DE BASE. Seguidor IIR  bl_acc += x - (bl_acc >> k),  bl = bl_acc >> k.
// El acumulador es ancho a propósito: con la forma ingenua `bl += (x-bl)>>k`
// el incremento se cuantiza a cero cuando |x-bl| < 2^k y el seguidor se
// congela. Se congela mientras haya una ventana abierta Y durante
// cfg_bl_holdoff muestras después de cada cierre: si siguiera apenas cierra la
// compuerta, agarraría la cola y el undershoot del pulso y arrastraría la base
// hacia el lado equivocado.
//
// QUIEN DECIDE CUANDO SEGUIR es la ventana: track_i, hold_load_i y stale_set_i
// salen de mca_window porque dependen del estado de las ranuras. La resta
// x = dat - base NO esta aca sino alla, junto al registro que la reparte a las
// ranuras: el sintetizador no aplana jerarquia.
//=============================================================================

module mca_baseline #(
  parameter integer DW    = 14,  // ancho de muestra (con signo)
  parameter integer LEN_W = 16,  // ancho de los contadores de longitud
  parameter integer BL_KW = 4    // bits del exponente k del seguidor IIR
)(
  input                        clk_i            ,
  input                        rstn_i           ,

  input      signed [DW-1:0]   dat_i            ,
  input                        val_i            ,

  // --- configuración ---
  input      signed [DW-1:0]   cfg_baseline_i   ,  // base fija si cfg_bl_auto=0
  input                        cfg_bl_auto_i    ,
  input             [BL_KW-1:0] cfg_bl_k_i      ,  // alfa = 2^-k
  input             [LEN_W-1:0] cfg_bl_holdoff_i,

  // --- desde la ventana ---
  input                        track_i          ,  // ninguna ventana sobre esta muestra
  input                        hold_load_i      ,  // cierre: arranca el holdoff
  input                        stale_set_i      ,  // ventana vencida sin muestras

  output     signed [DW-1:0]   baseline_o       ,
  output reg                   baseline_stale_o
);

localparam integer BL_ACC_W = DW + (1<<BL_KW);    // acumulador del IIR

reg signed [BL_ACC_W-1:0] bl_acc;
reg        [LEN_W-1:0]    bl_hold;                // cuenta atrás del holdoff post-pulso

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
always @(posedge clk_i) begin
  if (!rstn_i) begin
    bl_acc <= {BL_ACC_W{1'b0}}; bl_hold <= {LEN_W{1'b0}};
    baseline_stale_o <= 1'b0;
  end else begin
    //--- seguidor: sólo en reposo y fuera del holdoff -----------------------
    // Ojo: track_i excluye tambien la muestra con la que se decide ABRIR, que
    // todavia no tiene ninguna ranura abierta. Sin eso el IIR se come la
    // primera muestra de CADA pulso, y a tasa alta eso arrastra la base hacia
    // arriba de forma sistemática: corre el centroide de todo el espectro.
    if (val_i) begin
      if (track_i && bl_hold == {LEN_W{1'b0}}) begin
        bl_acc <= bl_acc + $signed({{(BL_ACC_W-DW){dat_i[DW-1]}}, dat_i})
                         - bl_acc_shr;
        baseline_stale_o <= 1'b0;
      end else if (bl_hold != {LEN_W{1'b0}}) begin
        bl_hold <= bl_hold - {{(LEN_W-1){1'b0}}, 1'b1};
      end
    end

    // El cierre carga el holdoff y gana sobre la cuenta atrás de este ciclo.
    if (hold_load_i) bl_hold <= cfg_bl_holdoff_i;

    // Sin muestras válidas una ventana vencida no puede cerrar; el watchdog
    // avisa si esto se vuelve permanente. No choca con el borrado de arriba:
    // aquel exige val_i y este lo pide en bajo.
    if (stale_set_i) baseline_stale_o <= 1'b1;
  end
end

endmodule
