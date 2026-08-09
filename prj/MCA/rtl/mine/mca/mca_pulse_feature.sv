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
// MCA y del scope sean comparables. Abre al cruzar cfg_thr hacia arriba
// (con re-armado previo por debajo de cfg_thr-cfg_hyst) y cierra al bajar de
// ese nivel. Si llega a cfg_maxlen se cierra igual y se marca APILAMIENTO:
// ese evento se cuenta pero NO se histogramea, porque su integral y su pico
// están contaminados por el segundo pulso.
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
//=============================================================================

module mca_pulse_feature #(
  parameter integer DW      = 14,  // ancho de muestra (con signo)
  parameter integer QW      = 32,  // ancho de los acumuladores de carga
  parameter integer AMP_W   = 16,  // ancho de la amplitud emitida
  parameter integer PSD_AW  = 6,   // bits del eje de factor de forma
  parameter integer LEN_W   = 16,  // ancho de los contadores de longitud
  parameter integer BL_KW   = 4,   // bits del exponente k del seguidor IIR
  parameter integer EN_PSD  = 1    // 0: no instancia el divisor
)(
  input                       clk_i            ,
  input                       rstn_i           ,

  // --- muestras de entrada (ya calibradas/filtradas/decimadas) ---
  input      signed [DW-1:0]  dat_i            ,
  input                       val_i            ,

  // --- configuración ---
  input                       cfg_run_i        ,
  input                       cnt_clr_i        ,  // pulso: pone a cero los contadores
  input      signed [DW-1:0]  cfg_thr_i        ,  // umbral sobre la línea de base
  input             [DW-1:0]  cfg_hyst_i       ,  // histéresis (positiva)
  input      signed [DW-1:0]  cfg_baseline_i   ,  // base fija si cfg_bl_auto=0
  input                       cfg_bl_auto_i    ,
  input             [BL_KW-1:0] cfg_bl_k_i     ,  // alfa = 2^-k
  input             [LEN_W-1:0] cfg_bl_holdoff_i,
  input             [LEN_W-1:0] cfg_maxlen_i   ,
  input             [LEN_W-1:0] cfg_tail_dly_i ,  // >= 1
  input             [AMP_W-1:0] cfg_amp_min_i  ,
  input             [AMP_W-1:0] cfg_amp_max_i  ,
  input                       cfg_amp_src_i    ,  // 0=pico, 1=integral
  input             [4:0]     cfg_q_shift_i    ,

  // --- evento de salida (pulso de 1 ciclo) ---
  output reg                  ev_valid_o       ,
  output reg [AMP_W-1:0]      ev_amp_o         ,
  output reg [PSD_AW-1:0]     ev_psd_o         ,
  output reg                  ev_psd_ok_o      ,  // 0 => no histogramear el 2D

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
  output                      busy_o              // pulso activo o divisor ocupado
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

wire open_pulse  = (st == S_IDLE) && cfg_run_i && armed && (x >= thr_hi);
wire close_hyst  = (st == S_ACTIVE) && (x < thr_lo);
wire close_maxl  = (st == S_ACTIVE) && (len >= cfg_maxlen_i);
wire close_pulse = close_hyst || close_maxl;

// La cola arranca cfg_tail_dly muestras después del pico. Mientras el pulso
// sube, t_peak == len y la condición es falsa (con tail_dly >= 1); recién
// cuando el pico queda atrás y se congela, empieza a acumular.
wire in_tail = (st == S_ACTIVE) && (len >= (t_peak + cfg_tail_dly_i));

//-----------------------------------------------------------------------------
// Amplitud: pico o integral, con saturación a AMP_W bits
//-----------------------------------------------------------------------------
wire [QW-1:0]    q_shifted = q_tot >> cfg_q_shift_i;
wire             q_ovf     = |q_shifted[QW-1:AMP_W];
wire [AMP_W-1:0] amp_int   = q_ovf ? {AMP_W{1'b1}} : q_shifted[AMP_W-1:0];
wire [AMP_W-1:0] amp_peak  = {{(AMP_W-DW){1'b0}}, peak};
wire [AMP_W-1:0] amp_sel   = cfg_amp_src_i ? amp_int : amp_peak;

wire amp_ok = (amp_sel >= cfg_amp_min_i) && (amp_sel <= cfg_amp_max_i);

// El divisor exige q_tail < q_tot y q_tot != 0. Se verifica ACÁ, no se confía
// en la invariante: el clamp de xc la protege, pero un q_tot=0 (pulso de ruido)
// haría que el cociente saliera todo unos, o sea todos esos eventos al bin
// superior del eje de forma.
wire psd_inputs_ok = (q_tot != {QW{1'b0}}) && (q_tail < q_tot);

//-----------------------------------------------------------------------------
// Divisor del factor de forma
//-----------------------------------------------------------------------------
reg              div_start;
reg  [QW-1:0]    div_num, div_den;
wire [PSD_AW-1:0] div_q;
wire             div_valid, div_err, div_sat, div_busy;

generate if (EN_PSD) begin : g_div
  mca_div_restore #(.D_W(QW), .Q_W(PSD_AW)) i_div (
    .clk_i(clk_i), .rstn_i(rstn_i),
    .start_i(div_start), .num_i(div_num), .den_i(div_den),
    .q_o(div_q), .valid_o(div_valid), .err_o(div_err), .sat_o(div_sat),
    .busy_o(div_busy)
  );
end else begin : g_nodiv
  assign div_q     = {PSD_AW{1'b0}};
  assign div_valid = 1'b0;
  assign div_err   = 1'b0;
  assign div_sat   = 1'b0;
  assign div_busy  = 1'b0;
end endgenerate

assign busy_o = (st != S_IDLE);

// Datos del evento retenidos mientras corre el divisor, para que el registro
// que ven los motores sea coherente.
reg [AMP_W-1:0] hold_amp;

//-----------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (!rstn_i) begin
    st <= S_IDLE; armed <= 1'b0;
    len <= {LEN_W{1'b0}}; t_peak <= {LEN_W{1'b0}}; peak <= {DW{1'b0}};
    q_tot <= {QW{1'b0}}; q_tail <= {QW{1'b0}};
    bl_acc <= {BL_ACC_W{1'b0}}; bl_hold <= {LEN_W{1'b0}};
    div_start <= 1'b0; div_num <= {QW{1'b0}}; div_den <= {QW{1'b0}};
    hold_amp <= {AMP_W{1'b0}};
    ev_valid_o <= 1'b0; ev_amp_o <= {AMP_W{1'b0}};
    ev_psd_o <= {PSD_AW{1'b0}}; ev_psd_ok_o <= 1'b0;
    baseline_stale_o <= 1'b0;
    cnt_total_o <= 32'h0; cnt_accepted_o <= 32'h0; cnt_rej_amp_o <= 32'h0;
    cnt_rej_psd_o <= 32'h0; cnt_pileup_o <= 32'h0; cnt_lost_busy_o <= 32'h0;
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
    div_num <= q_tail;
    div_den <= q_tot;

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

    //--- re-armado Schmitt --------------------------------------------------
    // Independiente del estado a propósito. Si sólo se armara en S_IDLE, una
    // señal que vuelve a la base mientras corre el divisor (6 ciclos) y sube
    // otra vez dejaría el pulso siguiente sin detectar, en silencio.
    // El `armed <= 1'b0` del case gana sobre esta línea al abrir un pulso.
    if (val_i && (x < thr_lo)) armed <= 1'b1;

    // ...pero si la señal cruza el umbral mientras el módulo está OCUPADO, se
    // desarma. Si no, al liberarse el divisor abriría a mitad del pulso ya en
    // curso y mediría una amplitud truncada: eso metería una cola espuria de
    // baja energía en el espectro. Es preferible perder el pulso entero y
    // contarlo en cnt_lost_busy, que es un tiempo muerto medible y corregible.
    if (val_i && (st != S_IDLE) && (x >= thr_hi)) armed <= 1'b0;

    //--- FSM ----------------------------------------------------------------
    case (st)
      //---------------------------------------------------------------------
      S_IDLE: begin
        if (val_i && open_pulse) begin
          st     <= S_ACTIVE;
          armed  <= 1'b0;
          len    <= {{(LEN_W-1){1'b0}}, 1'b1};
          t_peak <= {LEN_W{1'b0}};
          peak   <= xc;
          q_tot  <= {{(QW-DW){1'b0}}, xc};
          q_tail <= {QW{1'b0}};
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

            if (close_maxl) begin
              // Apilamiento: el pulso está contaminado, se cuenta y se tira.
              cnt_pileup_o <= cnt_pileup_o + 32'h1;
              st <= S_IDLE;
            end else if (!amp_ok) begin
              cnt_rej_amp_o <= cnt_rej_amp_o + 32'h1;
              st <= S_IDLE;
            end else begin
              hold_amp <= amp_sel;
              if (EN_PSD != 0) begin
                // div_num/div_den se cargan incondicionalmente mas abajo: aca
                // solo se dispara el arranque.
                div_start <= 1'b1;
                st        <= S_DIV;
              end else begin
                // Sin motor de forma: el evento sale directo.
                cnt_accepted_o <= cnt_accepted_o + 32'h1;
                ev_amp_o    <= amp_sel;
                ev_psd_o    <= {PSD_AW{1'b0}};
                ev_psd_ok_o <= 1'b0;
                ev_valid_o  <= 1'b1;
                st <= S_IDLE;
              end
            end
          end else begin
            len   <= len + {{(LEN_W-1){1'b0}}, 1'b1};
            q_tot <= q_tot + {{(QW-DW){1'b0}}, xc};
            if (in_tail) q_tail <= q_tail + {{(QW-DW){1'b0}}, xc};
            // Pico con comparación ESTRICTA: gana la primera ocurrencia.
            if (xc > peak) begin
              peak   <= xc;
              t_peak <= len;
            end
          end
        end else begin
          // Sin muestras válidas el pulso no puede cerrarse por histéresis;
          // el watchdog de línea de base avisa si esto se vuelve permanente.
          if (len >= cfg_maxlen_i) baseline_stale_o <= 1'b1;
        end
      end

      //---------------------------------------------------------------------
      S_DIV: begin
        // Un pulso nuevo mientras el divisor trabaja se pierde: se cuenta.
        if (val_i && (x >= thr_hi) && armed)
          cnt_lost_busy_o <= cnt_lost_busy_o + 32'h1;

        if (div_valid) begin
          ev_amp_o <= hold_amp;
          if (div_err || div_sat || !psd_inputs_ok) begin
            // El evento sigue siendo bueno en amplitud: entra al espectro 1D,
            // pero no al mapa 2D.
            cnt_rej_psd_o  <= cnt_rej_psd_o + 32'h1;
            cnt_accepted_o <= cnt_accepted_o + 32'h1;
            ev_psd_o    <= {PSD_AW{1'b0}};
            ev_psd_ok_o <= 1'b0;
          end else begin
            cnt_accepted_o <= cnt_accepted_o + 32'h1;
            ev_psd_o    <= div_q;
            ev_psd_ok_o <= 1'b1;
          end
          ev_valid_o <= 1'b1;
          st <= S_IDLE;
        end
      end

      default: st <= S_IDLE;
    endcase

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
    end
  end
end

endmodule
