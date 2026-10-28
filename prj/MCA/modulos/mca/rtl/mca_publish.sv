`timescale 1ns/1ps
//=============================================================================
// mca_publish — publicacion del evento: FIFO, arbitro, divisores de forma y
// armado del bus de features. Es la decision D8 (cfg_pub_mode) de la vista
// general (docs/mca/vista_general_mca.md).
//
// Recibe, en el ciclo de cierre de una ventana ACEPTADA, los valores vivos de
// los acumuladores de mca_window, y devuelve un registro de evento coherente
// {ev_amp, ev_psd, ev_feat} que alimenta a todos los motores de histograma.
//
// Las dos politicas de publicacion conviven en el mismo bitstream:
//   - BLOQUEANTE (cfg_pub_mode = 0): la ventana no reabre hasta que el
//     publicador termina. Eso NO se decide aca: lo decide mca_window, que se
//     queda en S_DIV hasta ver pub_done_o.
//   - FIFO (cfg_pub_mode = 1): la ventana cierra, deja su resultado en un
//     lugar de la FIFO y reabre; el publicador consume a su ritmo. El bloqueo,
//     si lo hay, es la FIFO llena, y mca_window lo ve en pub_occ_o.
//
// Por eso este modulo no tiene la entrada cfg_pub_mode: su comportamiento es
// el mismo en los dos modos, y la diferencia esta toda en cuando lo deja de
// esperar la ventana.
//
// FRONTERA. El sintetizador del bitstream no aplana jerarquia
// (-flatten_hierarchy none), asi que cada puerto es una barrera de
// optimizacion. Esta frontera es gratis porque todo lo que entra sale de un
// registro de mca_window o va directo a un pin de primitiva: `acepta_i` es la
// WE de los LUTRAM de la FIFO y el CE de pub_wr, sin logica de por medio. La
// WE de f_qtail/f_peak esta entre los 100 peores caminos del build; agregarle
// una LUT de este lado lo habria roto.
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
  parameter integer PUB_K   = 2,   // lugares de la FIFO de publicacion
  parameter integer PUB_IDW = 16,  // bits del id de ventana
  // Derivado: lo usan los puertos. No se sobreescribe.
  parameter integer PUB_AW  = (PUB_K <= 2) ? 1 : $clog2(PUB_K)
)(
  input                        clk_i          ,
  input                        rstn_i         ,
  input                        cnt_clr_i      ,  // pulso: pone a cero los contadores

  // --- la ventana que cierra ACEPTADA (pulso de 1 ciclo) y sus valores vivos ---
  input                        acepta_i       ,
  input      [AMP_W-1:0]       amp_sel_i      ,  // el estimador SELECCIONADO
  input      [AMP_W-1:0]       amp_int_i      ,  // la integral, siempre
  input      [DW-1:0]          peak_i         ,
  input      [LEN_W-1:0]       len_i          ,
  input      [LEN_W-1:0]       t_peak_i       ,
  input      [QW-1:0]          q_tot_i        ,
  input      [QW-1:0]          q_tail_i       ,
  input      [PUB_IDW-1:0]     win_id_i       ,

  // --- estado del arbitro, hacia la ventana y el banco de registros ---
  output     [PUB_AW:0]        pub_occ_o      ,  // lugares ocupados ahora
  output reg [PUB_AW:0]        pub_occ_max_o  ,  // maximo historico
  output                       pub_done_o     ,  // el publicador termina en ESTE ciclo

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

// El divisor exige q_tail < q_tot y q_tot != 0. Se verifica ACÁ, no se confía
// en la invariante: el clamp de xc la protege, pero un q_tot=0 (pulso de ruido)
// haría que el cociente saliera todo unos, o sea todos esos eventos al bin
// superior del eje de forma.
wire psd_inputs_ok = (q_tot_i != {QW{1'b0}}) && (q_tail_i < q_tot_i);

//-----------------------------------------------------------------------------
// Los DOS divisores de forma, en paralelo
//
// (1) PSD = Q_cola/Q_total — comparacion de carga (Brooks 1959; Knoll cap. 17).
//     Mide DONDE esta la carga: el peso de la componente lenta.
// (2) INVW = Pico/Q_total  — el ancho inverso. Mide CUANTA carga hay por unidad
//     de altura, o sea el ancho efectivo del pulso.
//
// Son ejes de forma INDEPENDIENTES: dos pulsos del mismo ancho pero distinto
// balance cabeza/cola dan el mismo INVW y distinto PSD. Y el segundo es el que
// sirve para rechazar apilamiento — medido por Monte-Carlo sobre el espectro de
// una linea a 100 kcps, PSD rechaza el 29.6 % de los apilados en modo histeresis
// y EXACTAMENTE NADA en modo compuerta, mientras que el ancho rechaza el 99.1 %.
// Ver software/monte-carlo/.
//
// Por que INVW = P/Q y no Q/P: el divisor restaurador exige num < den, y Q/P > 1
// no entra. P/Q si, porque q_tot = sum(xc) >= max(xc) = peak SIEMPRE. Es la misma
// informacion, monotona decreciente en vez de creciente.
//
// Corren EN PARALELO: los dos arrancan al cerrar y terminan juntos, asi que el
// segundo no agrega ni un ciclo de tiempo muerto. Cuestan cero DSP.
//
// DIV_W = 16 bits de cociente (antes 6). Con 6 bits el ancho inverso no tenia
// rango: los valores utiles de Q/P van de ~250 (limpio) a ~1200 (apilado), o sea
// P/Q en [0.0008, 0.004], que con 6 bits se cuantiza a CERO. Con 16 bits caen en
// [52, 262], que si separa las poblaciones.
//
// El eje del mapa 2D sigue teniendo PSD_AW bits: se toman los PSD_AW bits ALTOS
// del cociente. Eso es BIT-EXACTO respecto del comportamiento anterior, porque
// floor(floor(a*2^16/b)/2^10) == floor(a*2^6/b) para enteros positivos. O sea que
// ampliar el divisor no cambia ni un evento del mapa 2D ya caracterizado.
//-----------------------------------------------------------------------------
reg              div_start;
reg  [QW-1:0]    div_num, div_den, div2_num;
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
  // Mismo denominador, mismo arranque, misma latencia: no hace falta mirar su
  // valid_o, alcanza con el del primero.
  mca_div_restore #(.D_W(QW), .Q_W(DIV_W)) i_div_w (
    .clk_i(clk_i), .rstn_i(rstn_i),
    .start_i(div_start), .num_i(div2_num), .den_i(div_den),
    .q_o(div2_q), .valid_o(div2_valid), .err_o(div2_err), .sat_o(div2_sat),
    .busy_o()
  );
end else begin : g_nodiv
  assign div_q      = {DIV_W{1'b0}};
  assign div_valid  = 1'b0;
  assign div_err    = 1'b0;
  assign div_sat    = 1'b0;
  assign div_busy   = 1'b0;
  assign div2_q     = {DIV_W{1'b0}};
  assign div2_valid = 1'b0;
  assign div2_err   = 1'b0;
  assign div2_sat   = 1'b0;
end endgenerate

//-----------------------------------------------------------------------------
// FIFO DE PUBLICACION — el Q_{n-1} por ventana, de 1 lugar a PUB_K
//-----------------------------------------------------------------------------
// Datos del evento retenidos mientras corren los divisores, para que el registro
// que ven los motores sea coherente. `len`, `t_peak` y `peak` se pisan apenas
// llega el pulso SIGUIENTE, asi que hay que congelarlos: sin esto el bus de
// features mezclaria features de dos eventos distintos, que es exactamente el
// modo de falla que el registro unico existe para evitar.
//
// ESTO YA EXISTIA CON PROFUNDIDAD 1 (los hold_* de antes). Llevarlo a PUB_K
// lugares con id de ventana ES el arbitraje del recurso compartido: el divisor
// es uno solo y la ventana es la que lo pide. Con K lugares la ventana cierra,
// deja su resultado y reabre, y el publicador consume a su ritmo.
//
// Se guarda tambien q_tot/q_tail porque una entrada que no alcanzo a arrancar
// los divisores los va a necesitar despues (ver `arranque_directo`), y el flag
// psd_ok ya resuelto, para no arrastrar dos comparadores de QW bits hasta el
// publicador.
reg [AMP_W-1:0]   f_amp   [0:PUB_K-1];   // el estimador SELECCIONADO
reg [AMP_W-1:0]   f_aint  [0:PUB_K-1];   // la integral, siempre: su propia ranura
reg [DW-1:0]      f_peak  [0:PUB_K-1];
reg [LEN_W-1:0]   f_len   [0:PUB_K-1];
reg [LEN_W-1:0]   f_tpk   [0:PUB_K-1];
reg [QW-1:0]      f_qtot  [0:PUB_K-1];
reg [QW-1:0]      f_qtail [0:PUB_K-1];
reg [PUB_IDW-1:0] f_id    [0:PUB_K-1];
reg               f_psd_ok[0:PUB_K-1];

reg [PUB_AW-1:0] pub_wr, pub_rd;
reg [PUB_AW:0]   pub_occ;
wire pub_vacio = (pub_occ == {(PUB_AW+1){1'b0}});

assign pub_occ_o = pub_occ;

// Estado del publicador. Es una FSM aparte de la del extractor: eso es todo el
// desacople.
localparam [0:0] P_IDLE = 1'd0, P_DIV = 1'd1;
reg        pst;
reg [PUB_AW-1:0] pub_cur;        // entrada que esta en los divisores

// El publicador termina en ESTE ciclo. La ventana usa esta senal para salir de
// S_DIV en el modo bloqueante, y no `pub_vacio`, que llegaria un ciclo tarde y
// alargaria S_DIV de 17 a 18 ciclos — rompiendo la identidad
// deadtime_cnt == t_win + t_div de la Fase 1.
wire pub_done = (pst == P_DIV) && div_valid;
assign pub_done_o = pub_done;

// ARRANQUE DIRECTO. Si al cerrar el publicador esta libre, los divisores
// arrancan en ESE mismo flanco desde los registros vivos (q_tot/q_tail/peak),
// exactamente como antes de la FIFO. Solo las entradas que encuentran el
// publicador ocupado —que en el modo bloqueante no existen— esperan su turno y
// se cargan desde la FIFO, con un ciclo mas de latencia.
wire pub_libre = (pst == P_IDLE) && pub_vacio;

// Empuje y extraccion como CABLES, para poder actualizar la ocupacion en un
// solo lugar. Hace falta: en modo FIFO una ventana puede cerrar en el mismo
// flanco en que el publicador termina, y con dos asignaciones separadas a
// pub_occ la segunda ganaria y el empuje se perderia en silencio — una entrada
// escrita que nadie publica nunca.
wire pub_push   = (EN_PSD != 0) && acepta_i;
wire pub_pop    = pub_done;

//-----------------------------------------------------------------------------
// Indices del bus de features. Fijos y compartidos: el selector de eje del
// histograma y el discriminador usan ESTA numeracion, asi que no se pueden
// desincronizar.
//-----------------------------------------------------------------------------
localparam integer F_PEAK  = 0;  // amplitud de pico
localparam integer F_INT   = 1;  // integral de carga (Q_total >> q_shift)
localparam integer F_PSD   = 2;  // Q_cola/Q_total   — donde esta la carga
localparam integer F_INVW  = 3;  // Pico/Q_total     — ancho inverso
localparam integer F_LEN   = 4;  // largo de la ventana, en muestras
localparam integer F_TRISE = 5;  // muestras del disparo al pico
// 6..NFEAT-1 reservadas (meseta del trapecio). Se atan a cero: la sintesis las
// borra enteras, asi que una ranura sin usar no cuesta nada.

// Normalizacion de cada ranura. El contrato del bus es "uint16 con fondo de
// escala 0xFFFF", asi que las features acotadas se alinean a la IZQUIERDA:
// extenderlas con cero dejaria una fraccion de DIV_W bits viviendo en los bits
// BAJOS, y entonces cada eje necesitaria un corrimiento distinto para decir lo
// mismo. Alineadas, un solo corrimiento sirve para todas.
//
// Excepcion honesta: F_INVW, F_LEN y F_TRISE NO se normalizan.
//   - F_LEN/F_TRISE son contadores sin fondo de escala natural (dependen de
//     cfg_gate_long).
//   - F_INVW es una fraccion pero vive cerca de CERO (P/Q ~ 0.001 para un pulso
//     de 250 muestras): alinearla a la izquierda la mandaria toda al bin 0. Su
//     escala depende del ancho del pulso, que es justo lo que mide, asi que el
//     factor no se puede fijar en tiempo de compilacion.
// Las tres se ajustan con el corrimiento del eje, y esto esta documentado en el
// mapa de registros para que no sorprenda.
function automatic [AMP_W-1:0] feat_izq(input [DIV_W-1:0] q);
  feat_izq = (AMP_W >= DIV_W) ? {q, {(AMP_W-DIV_W){1'b0}}}
                              : q[DIV_W-1 -: AMP_W];
endfunction

//-----------------------------------------------------------------------------
always @(posedge clk_i) begin
  if (!rstn_i) begin
    div_start <= 1'b0; div_num <= {QW{1'b0}}; div_den <= {QW{1'b0}};
    div2_num <= {QW{1'b0}};
    // Los lugares de la FIFO no se inicializan: no se leen hasta haberse
    // escrito, y ponerlos en cero costaria PUB_K juegos de flops con reset.
    // Lo que SI tiene que arrancar en cero es el control.
    pst <= P_IDLE; pub_wr <= {PUB_AW{1'b0}}; pub_rd <= {PUB_AW{1'b0}};
    pub_occ <= {(PUB_AW+1){1'b0}}; pub_cur <= {PUB_AW{1'b0}};
    pub_occ_max_o <= {(PUB_AW+1){1'b0}};
    last_win_id_o <= {PUB_IDW{1'b0}};
    ev_valid_o <= 1'b0; ev_amp_o <= {AMP_W{1'b0}};
    ev_psd_o <= {PSD_AW{1'b0}}; ev_psd_ok_o <= 1'b0;
    ev_feat_o <= {(NFEAT*AMP_W){1'b0}};
    cnt_accepted_o <= 32'h0; cnt_rej_psd_o <= 32'h0;
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
    //
    // LA FUENTE ES LA VENTANA VIVA salvo que haya cola en la FIFO. Con la FIFO
    // vacia (el caso del modo bloqueante y el caso normal del modo FIFO) esto es
    // literalmente lo de antes: q_tot/q_tail/peak del cierre. Solo cuando una
    // entrada quedo esperando turno los operandos salen de su lugar de la FIFO.
    if (pub_vacio) begin
      div_num  <= q_tail_i;
      div_den  <= q_tot_i;
      div2_num <= {{(QW-DW){1'b0}}, peak_i};   // ancho inverso: P/Q
    end else begin
      div_num  <= f_qtail[pub_rd];
      div_den  <= f_qtot [pub_rd];
      div2_num <= {{(QW-DW){1'b0}}, f_peak[pub_rd]};
    end

    //--- cierre aceptado ----------------------------------------------------
    if (acepta_i) begin
      if (EN_PSD != 0) begin
        // Se EMPUJA el resultado a la FIFO: todas las features que el pulso
        // siguiente podria pisar, mas el id de la ventana y el flag de forma
        // ya resuelto.
        //
        // Solo se empuja si hay divisores. Sin ellos nadie saca de la FIFO, asi
        // que empujar la llenaria y el modulo quedaria bloqueado para siempre;
        // en ese caso el evento sale directo desde los registros vivos, como
        // siempre (rama de abajo).
        f_amp   [pub_wr] <= amp_sel_i;
        f_aint  [pub_wr] <= amp_int_i;
        f_peak  [pub_wr] <= peak_i;
        f_len   [pub_wr] <= len_i;
        f_tpk   [pub_wr] <= t_peak_i;
        f_qtot  [pub_wr] <= q_tot_i;
        f_qtail [pub_wr] <= q_tail_i;
        f_id    [pub_wr] <= win_id_i;
        f_psd_ok[pub_wr] <= psd_inputs_ok;
        pub_wr  <= (pub_wr == (PUB_K-1)) ? {PUB_AW{1'b0}}
                                         : (pub_wr + {{(PUB_AW-1){1'b0}}, 1'b1});
        // pub_occ NO se toca aca: se actualiza una sola vez mas abajo, desde
        // pub_push/pub_pop.

        // ARRANQUE DIRECTO: con el publicador libre los divisores arrancan en
        // ESTE flanco y toman los registros vivos (el `if (pub_vacio)` de la
        // carga de operandos de mas arriba todavia ve la FIFO vacia). Es lo que
        // mantiene S_DIV en 17 ciclos exactos.
        if (pub_libre) begin
          div_start <= 1'b1;
          pst       <= P_DIV;
          pub_cur   <= pub_wr;
        end
      end else begin
        // Sin motor de forma: el evento sale directo, con las ranuras de forma
        // en cero.
        cnt_accepted_o <= cnt_accepted_o + 32'h1;
        ev_amp_o    <= amp_sel_i;
        ev_psd_o    <= {PSD_AW{1'b0}};
        ev_psd_ok_o <= 1'b0;
        ev_feat_o   <= {(NFEAT*AMP_W){1'b0}};
        ev_feat_o[F_PEAK *AMP_W +: AMP_W] <= {peak_i, {(AMP_W-DW){1'b0}}};
        ev_feat_o[F_INT  *AMP_W +: AMP_W] <= amp_int_i;
        ev_feat_o[F_LEN  *AMP_W +: AMP_W] <= len_i;
        ev_feat_o[F_TRISE*AMP_W +: AMP_W] <= t_peak_i;
        ev_valid_o  <= 1'b1;
      end
    end

    //-----------------------------------------------------------------------
    // EL PUBLICADOR — el arbitro del recurso compartido
    //-----------------------------------------------------------------------
    // Corre en paralelo a la FSM de ventana y es lo unico que toca los
    // divisores y las salidas de evento. Que sea una FSM aparte ES el desacople:
    // en modo FIFO la ventana ya cerro y puede haber reabierto mientras esto
    // publica la anterior.
    //
    // Va DESPUES del cierre a proposito: `pst <= P_DIV` del arranque directo
    // tiene que ganar sobre el arranque por cola de aca, porque los dos podrian
    // querer disparar en el mismo flanco y el directo es el que ya cargo los
    // operandos desde los registros vivos.
    if (EN_PSD != 0) begin
      case (pst)
        P_IDLE: begin
          // Hay algo en cola que todavia no arranco (solo ocurre en modo FIFO:
          // la entrada encontro el publicador ocupado al cerrar). No puede
          // chocar con el arranque directo: ese exige pub_vacio y este !pub_vacio.
          if (!pub_vacio) begin
            div_start <= 1'b1;
            pst       <= P_DIV;
            pub_cur   <= pub_rd;
          end
        end

        P_DIV: if (div_valid) begin
          ev_amp_o <= f_amp[pub_cur];

          // --- bus de features: se arma ACA, no al cerrar ------------------
          // Es el unico instante en que TODAS las ranuras son del mismo evento:
          // pico, largo y tiempo de subida valen desde el cierre (guardados en
          // el lugar de la FIFO), y los dos cocientes recien ahora.
          ev_feat_o <= {(NFEAT*AMP_W){1'b0}};
          ev_feat_o[F_PEAK *AMP_W +: AMP_W] <= {f_peak[pub_cur], {(AMP_W-DW){1'b0}}};
          ev_feat_o[F_INT  *AMP_W +: AMP_W] <= f_aint[pub_cur];
          ev_feat_o[F_LEN  *AMP_W +: AMP_W] <= f_len [pub_cur];
          ev_feat_o[F_TRISE*AMP_W +: AMP_W] <= f_tpk [pub_cur];
          // El ancho inverso NO se alinea a la izquierda (ver feat_izq): vive
          // cerca de cero y su escala depende del ancho del pulso.
          ev_feat_o[F_INVW *AMP_W +: AMP_W] <=
              div2_sat ? {AMP_W{1'b1}} : {{(AMP_W-DIV_W){1'b0}}, div2_q};

          if (div_err || div_sat || !f_psd_ok[pub_cur]) begin
            // El evento sigue siendo bueno en amplitud: entra al espectro 1D,
            // pero no al mapa 2D. La ranura de forma queda en cero.
            cnt_rej_psd_o  <= cnt_rej_psd_o + 32'h1;
            cnt_accepted_o <= cnt_accepted_o + 32'h1;
            ev_psd_o    <= {PSD_AW{1'b0}};
            ev_psd_ok_o <= 1'b0;
          end else begin
            cnt_accepted_o <= cnt_accepted_o + 32'h1;
            // El eje del mapa 2D toma los PSD_AW bits ALTOS del cociente de
            // DIV_W. Es BIT-EXACTO respecto de un divisor de PSD_AW bits:
            // floor(floor(a*2^DIV_W/b) / 2^(DIV_W-PSD_AW)) == floor(a*2^PSD_AW/b).
            ev_psd_o    <= div_q[DIV_W-1 -: PSD_AW];
            ev_psd_ok_o <= 1'b1;
            ev_feat_o[F_PSD*AMP_W +: AMP_W] <= feat_izq(div_q);
          end
          ev_valid_o    <= 1'b1;
          last_win_id_o <= f_id[pub_cur];

          // Se libera el lugar y se vuelve a reposo. Si quedo otra entrada
          // encolada, P_IDLE la va a arrancar en el ciclo siguiente.
          pub_rd  <= (pub_rd == (PUB_K-1)) ? {PUB_AW{1'b0}}
                                           : (pub_rd + {{(PUB_AW-1){1'b0}}, 1'b1});
          // pub_occ NO se toca aca tampoco: ver la actualizacion unica de abajo.
          pst     <= P_IDLE;
        end

        default: pst <= P_IDLE;
      endcase
    end

    //--- ocupacion de la FIFO: UNA sola actualizacion -----------------------
    // Empuje y extraccion simultaneos se cancelan, que es lo correcto y lo que
    // dos asignaciones separadas no habrian hecho.
    if      (pub_push && !pub_pop) pub_occ <= pub_occ + {{PUB_AW{1'b0}}, 1'b1};
    else if (!pub_push && pub_pop) pub_occ <= pub_occ - {{PUB_AW{1'b0}}, 1'b1};

    // Marca de agua de la ocupacion. Es EL dato que dice si PUB_K alcanza: si
    // llega a PUB_K hubo contrapresion, y lo que se perdio por eso esta en
    // cnt_lost_busy.
    if (pub_occ > pub_occ_max_o) pub_occ_max_o <= pub_occ;

    //--- borrado de contadores (va último: gana sobre los incrementos de
    //    este mismo ciclo, así el conteo arranca limpio) ----------------------
    if (cnt_clr_i) begin
      cnt_accepted_o  <= 32'h0;
      cnt_rej_psd_o   <= 32'h0;
      // La marca de agua se borra con los contadores: es una estadistica de la
      // corrida, no estado del hardware. La ocupacion EN CURSO no se toca -- hay
      // entradas reales adentro y perderlas colgaria el publicador.
      pub_occ_max_o   <= {(PUB_AW+1){1'b0}};
    end
  end
end

endmodule
