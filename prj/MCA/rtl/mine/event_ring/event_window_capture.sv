`timescale 1ns/1ps
//=============================================================================
// event_window_capture — extrae una ventana (pre + post) por trigger y la emite
// como stream de muestras de 16 b.
//
// Reemplaza el rol de rp_bram_sm en el camino de eventos. La diferencia
// estructural: rp_bram_sm CONGELA un buffer de 16384 muestras y no puede
// capturar de nuevo hasta que el PS re-arma (K=1, ~252 us de tiempo muerto).
// Acá la ventana se copia a un stream aguas abajo y el bloque vuelve a estar
// listo en pre+post ciclos (~256 ns con S=32), sin intervencion del PS.
//
// UNA SOLA MEMORIA. El pre-trigger vive en un buffer circular que se escribe
// siempre; la lectura de la ventana sale del MISMO buffer, arrancando `pre`
// muestras atras del trigger. El puntero de lectura queda rezagado y, como se
// consume 1 muestra/ciclo y se produce <=1 muestra/ciclo, el rezago nunca
// crece: alcanza al productor y despues va en lock-step durante el post.
// Por eso la profundidad sólo tiene que cubrir `pre`, no `pre+post`.
//
// DOS CAUSAS DE PERDIDA, contadas por separado porque son diagnosticos
// distintos (ver docs/multitrigger/):
//   drop_busy_o  el trigger cayo mientras se drenaba la ventana anterior.
//                Es el tiempo muerto INTRINSECO del PL: pre+post ciclos.
//   drop_full_o  aguas abajo no acepto el evento (stage llena, o sin creditos
//                de DDR porque el PS no drena). Es tiempo muerto del CONSUMIDOR.
//
// El handshake de aceptacion es en el SOF: si el consumidor no puede recibir la
// ventana entera en el momento del trigger, el evento se descarta ENTERO. Nunca
// se emite media ventana — un evento parcial en el ring seria indistinguible de
// uno bueno del lado del PS.
//=============================================================================

module event_window_capture #(
  parameter integer DW      = 14,   // ancho de la muestra del ADC
  parameter integer N_CH    = 2,    // canales capturados por evento
  parameter integer SW      = 16,   // ancho de la muestra en el stream (sign-ext)
  parameter integer PRE_AW  = 9,    // buffer circular de pre-trigger: 2^PRE_AW
  parameter integer S_AW    = 11,   // ancho de los contadores de muestras
  parameter integer TS_W    = 64    // ancho del timestamp
)(
  input                      clk_i,
  input                      rstn_i,

  // --- control -------------------------------------------------------------
  // run_i mantiene vivo el pre-buffer y el drenaje de la ventana en vuelo.
  // accept_trig_i habilita ACEPTAR triggers nuevos. Estan separados a proposito:
  // en la parada ordenada (DRAINING) se baja accept_trig_i pero se deja run_i,
  // asi el evento en vuelo termina en vez de quedar truncado a mitad de ventana.
  input                      run_i,
  input                      accept_trig_i,
  input      [S_AW-1:0]      pre_i,        // muestras antes del trigger
  input      [S_AW-1:0]      post_i,       // muestras desde el trigger (incl.)

  // --- muestras (ya decimadas) --------------------------------------------
  input      [N_CH*DW-1:0]   dat_i,
  input                      dv_i,         // muestra valida este ciclo

  // --- trigger -------------------------------------------------------------
  input                      trig_i,       // pulso de 1 ciclo
  input      [16:0]          snapshot_i,   // que fuente disparo
  input      [TS_W-1:0]      ts_i,         // reloj libre de adquisicion

  // --- stream de salida ----------------------------------------------------
  // m_val_o/m_dat_o: una muestra de 16 b por ciclo, canales INTERCALADOS:
  //   ch0[k], ch1[k], ch0[k+1], ch1[k+1], ...
  // El consumidor recibe (pre+post)*N_CH muestras entre sof y eof inclusive.
  output reg                 m_sof_o,      // coincide con la primera m_val_o
  output reg                 m_eof_o,      // coincide con la ultima m_val_o
  output reg                 m_val_o,
  output reg [SW-1:0]        m_dat_o,
  // Aceptacion: se muestrea SOLO en el ciclo del trigger. 1 = hay lugar para
  // la ventana completa.
  input                      m_accept_i,
  // Metadatos del evento, validos junto con m_sof_o.
  output reg [TS_W-1:0]      m_ts_o,
  output reg [16:0]          m_snap_o,
  output reg [S_AW-1:0]      m_nsamp_o,    // pre+post, muestras POR CANAL

  // --- diagnostico ---------------------------------------------------------
  output reg                 drop_busy_o,  // pulso
  output reg                 drop_full_o,  // pulso
  output                     busy_o
);

  localparam integer PRE_N = (1<<PRE_AW);

  //--------------------------------------------------------------------------
  // Buffer circular de pre-trigger. Se escribe SIEMPRE que corre, pase lo que
  // pase con la FSM de lectura: si dejara de escribirse durante el drenaje,
  // el pre-trigger del evento siguiente tendria un hueco.
  //--------------------------------------------------------------------------
  reg [N_CH*SW-1:0] pre_buf [0:PRE_N-1];
  reg [PRE_AW-1:0]  wr_ptr;
  reg [PRE_AW-1:0]  rd_ptr;

  // sign-extend de DW a SW, canal por canal
  wire [N_CH*SW-1:0] dat_sx;
  genvar gc;
  generate
    for (gc = 0; gc < N_CH; gc = gc + 1) begin : g_sx
      assign dat_sx[(gc+1)*SW-1 : gc*SW] =
             {{(SW-DW){dat_i[(gc+1)*DW-1]}}, dat_i[(gc+1)*DW-1 : gc*DW]};
    end
  endgenerate

  always @(posedge clk_i) begin
    if (run_i && dv_i) pre_buf[wr_ptr] <= dat_sx;
  end

  always @(posedge clk_i) begin
    if (!rstn_i || !run_i) wr_ptr <= {PRE_AW{1'b0}};
    else if (dv_i)         wr_ptr <= wr_ptr + 1'b1;
  end

  //--------------------------------------------------------------------------
  // FSM de ventana
  //--------------------------------------------------------------------------
  localparam [1:0] ST_IDLE  = 2'd0,  // corriendo, esperando trigger
                   ST_DRAIN = 2'd1,  // emitiendo la ventana
                   ST_TAIL  = 2'd2;  // ultimo ciclo (eof ya emitido)

  reg [1:0]      st;
  reg [S_AW:0]   samp_left;    // muestras POR CANAL que faltan emitir
  reg [$clog2(N_CH+1)-1:0] ch_idx;
  reg [N_CH*SW-1:0] word_r;    // palabra leida del buffer, se serializa por canal
  reg            word_val;

  assign busy_o = (st != ST_IDLE);

  // Hay dato disponible para leer mientras el puntero de lectura no alcance al
  // de escritura. Durante el pre siempre hay (arrancamos `pre` atras); durante
  // el post esto es lo que sincroniza con la llegada de muestras nuevas.
  wire rd_avail = (rd_ptr != wr_ptr);
  // Se lee una palabra nueva cuando terminamos de serializar la anterior.
  wire want_word = (st == ST_DRAIN) && (samp_left != 0) &&
                   (!word_val || (ch_idx == N_CH-1));

  wire do_read = want_word && rd_avail;

  always @(posedge clk_i) begin
    if (!rstn_i) begin
      st          <= ST_IDLE;
      samp_left   <= {(S_AW+1){1'b0}};
      ch_idx      <= '0;
      rd_ptr      <= {PRE_AW{1'b0}};
      word_val    <= 1'b0;
      m_val_o     <= 1'b0;
      m_sof_o     <= 1'b0;
      m_eof_o     <= 1'b0;
      m_dat_o     <= {SW{1'b0}};
      m_ts_o      <= {TS_W{1'b0}};
      m_snap_o    <= 17'h0;
      m_nsamp_o   <= {S_AW{1'b0}};
      drop_busy_o <= 1'b0;
      drop_full_o <= 1'b0;
    end else begin
      m_val_o     <= 1'b0;
      m_sof_o     <= 1'b0;
      m_eof_o     <= 1'b0;
      drop_busy_o <= 1'b0;
      drop_full_o <= 1'b0;

      if (!run_i) begin
        st       <= ST_IDLE;
        word_val <= 1'b0;
      end else case (st)

        //-------------------------------------------------------------------
        ST_IDLE: begin
          if (trig_i && accept_trig_i) begin
            if (!m_accept_i) begin
              // Aguas abajo no tiene lugar para la ventana ENTERA. Se descarta
              // el evento completo; nunca se emite una ventana parcial.
              drop_full_o <= 1'b1;
            end else begin
              // Arrancar `pre` muestras atras del puntero de escritura actual.
              rd_ptr    <= wr_ptr - pre_i[PRE_AW-1:0];
              samp_left <= {1'b0, pre_i} + {1'b0, post_i};
              m_nsamp_o <= pre_i + post_i;
              m_ts_o    <= ts_i;
              m_snap_o  <= snapshot_i;
              ch_idx    <= '0;
              word_val  <= 1'b0;
              st        <= ST_DRAIN;
            end
          end
        end

        //-------------------------------------------------------------------
        ST_DRAIN: begin
          // Un trigger durante el drenaje es el tiempo muerto intrinseco.
          if (trig_i) drop_busy_o <= 1'b1;

          if (do_read) begin
            word_r   <= pre_buf[rd_ptr];
            word_val <= 1'b1;
            rd_ptr   <= rd_ptr + 1'b1;
          end

          // Serializacion por canal de la palabra ya cargada.
          if (word_val) begin
            m_val_o <= 1'b1;
            m_dat_o <= word_r[ch_idx*SW +: SW];
            // sof: primerisima muestra del evento
            m_sof_o <= (samp_left == ({1'b0, m_nsamp_o})) && (ch_idx == 0);
            // eof: ultima muestra del ultimo canal
            m_eof_o <= (samp_left == 1) && (ch_idx == N_CH-1);

            if (ch_idx == N_CH-1) begin
              ch_idx    <= '0;
              samp_left <= samp_left - 1'b1;
              // OJO: do_read puede dispararse en ESTE mismo ciclo (want_word lo
              // permite cuando ch_idx==N_CH-1). Si acá se forzara 0 a secas, el
              // `word_val <= 1` de la rama de lectura quedaría pisado y se
              // perdería la palabra recién cargada: un off-by-one silencioso de
              // una muestra por evento.
              word_val  <= do_read;
              if (samp_left == 1) st <= ST_TAIL;
            end else begin
              ch_idx <= ch_idx + 1'b1;
            end
          end
        end

        //-------------------------------------------------------------------
        ST_TAIL: begin
          // Un ciclo de gracia para que m_eof_o salga por el registro antes de
          // aceptar un trigger nuevo.
          st <= ST_IDLE;
          if (trig_i) drop_busy_o <= 1'b1;
        end

        default: st <= ST_IDLE;
      endcase
    end
  end

endmodule
