`timescale 1ns/1ps
//=============================================================================
// event_slot_writer — serializa un evento a un slot del ring en DDR.
//
// Emite EXACTAMENTE 2^(slot_shift-3) palabras de 64 b por evento, en orden de
// direccion creciente, para que el generador lineal del axi_wr_fifo las coloque
// sin saltos:
//
//   w0            timestamp[63:0]
//   w1            {flags[7:0], n_ch[7:0], n_samp[15:0], seq[31:0]}
//   w2            {event_id[31:0], 15'b0, snapshot[16:0]}
//   w3            0 (reservado)
//   w4 ..         muestras int16, 4 por palabra, canales intercalados:
//                 [15:0]=ch0[k] [31:16]=ch1[k] [47:32]=ch0[k+1] [63:48]=ch1[k+1]
//   .. relleno    ceros hasta la anteultima palabra
//   ultima        FOOTER {~seq[31:0], seq[31:0]}
//
// COMO SE SABE QUE EL SLOT ESTA COMPLETO — y por que NO hace falta el BRESP.
//
// El plan original decia "incrementar wr_slot recien con el BRESP del ultimo
// burst". Es correcto pero inaplicable: ni axi_wr_fifo ni axi_master exponen el
// canal B (axi_wr_fifo.v solo saca werr/wrdy), asi que no hay forma de
// observarlo sin tocar RTL compartido.
//
// La solucion estandar de descriptor-ring es mejor y ademas mas barata: se
// escribe una MARCA AL FINAL. Todas las escrituras salen por un unico master
// con un unico ID hacia el mismo esclavo, y AXI garantiza que las escrituras
// con el mismo ID se observan en orden. Entonces, si el PS ve el footer del
// slot i con el `seq` esperado, todo lo que esta antes del footer YA esta en
// DDR. El footer es el commit.
//
// Ventaja adicional: el PS no necesita leer NINGUN registro por GP0 para saber
// que hay un evento nuevo. Polea el footer del proximo slot directamente en
// DDR, que es mas rapido que una lectura de registro (2.3 us) y saca el bus GP0
// del lazo caliente por completo. `wr_slot_o` queda como diagnostico.
//
// El footer lleva {~seq, seq}: una lectura rota o vieja se detecta comparando
// las dos mitades, sin depender de que el valor "0" sea especial.
//
// CONTROL DE FLUJO. Sin creditos el writer NO descarta: se frena. La
// contrapresion sube al stage y el descarte ocurre arriba de todo, en la
// captura, donde se puede descartar el evento ENTERO y contarlo. Descartar a
// mitad del slot dejaria basura indistinguible de un evento bueno.
//=============================================================================

module event_slot_writer #(
  parameter integer SW    = 16,
  parameter integer S_AW  = 11,
  parameter integer TS_W  = 64,
  parameter integer N_CH  = 2,
  parameter integer WCW   = 16   // ancho del contador de palabras por slot
)(
  input                    clk_i,
  input                    rstn_i,
  // flush_i: vacia la FSM y el dato en vuelo (parada de adquisicion).
  // clr_cnt_i: resetea wr_slot_o/seq_o. SEPARADO de flush_i a proposito —
  // wr_slot vive en pareja con el rd_slot que publica el PS, y resetear uno
  // solo deja la resta de creditos en underflow (ocupados ~ 2^32) y el ring
  // descartando todo. Un stop/start NO tiene por que invalidar el ring: los
  // contadores solo se reinician cuando el PS pide clr explicitamente, y ahi
  // el top resetea los DOS al mismo tiempo.
  input                    flush_i,
  input                    clr_cnt_i,

  // geometria del slot (latcheada por el top con la adquisicion parada)
  input      [4:0]         slot_shift_i,   // log2(bytes por slot), >= 6

  // --- stage ---------------------------------------------------------------
  input                    s_meta_val_i,
  input      [TS_W-1:0]    s_ts_i,
  input      [16:0]        s_snap_i,
  input      [S_AW-1:0]    s_nsamp_i,      // muestras POR CANAL
  output reg               s_meta_rd_o,
  input      [SW-1:0]      s_dat_i,
  output reg               s_dat_rd_o,

  // --- creditos ------------------------------------------------------------
  input                    credit_ok_i,    // hay al menos un slot libre en DDR

  // --- stream de 64 b hacia el axi_wr_fifo --------------------------------
  output reg [63:0]        wr_dat_o,
  output reg               wr_val_o,
  input                    wr_rdy_i,

  // --- estado --------------------------------------------------------------
  output reg [31:0]        wr_slot_o,      // contador LIBRE de slots escritos
  output reg [31:0]        seq_o,          // secuencia del proximo evento
  output                   no_credit_o,    // 1 = frenado por falta de creditos
  output                   busy_o,
  // Sticky: la ventana no entra en el slot configurado. Sin este guard, un
  // slot_shift demasiado chico pisa el slot siguiente y el PS lee eventos
  // corruptos sin ninguna indicacion.
  output reg               err_slot_ovf_o
);

  localparam [2:0] W_IDLE = 3'd0,
                   W_HDR  = 3'd1,
                   W_DATA = 3'd2,
                   W_PAD  = 3'd3,
                   W_FOOT = 3'd4,
                   W_DONE = 3'd5;

  reg [2:0]        st;
  reg [WCW-1:0]    word_idx;      // palabra dentro del slot
  reg [WCW-1:0]    slot_words;    // 2^(slot_shift-3), latcheado al empezar
  reg [1:0]        hdr_idx;
  reg [TS_W-1:0]   ts_r;
  reg [16:0]       snap_r;
  reg [S_AW-1:0]   nsamp_r;
  reg [S_AW+2:0]   samp_left;     // muestras TOTALES que faltan leer del stage
  reg [63:0]       acc;
  reg [2:0]        pack_cnt;      // 0..4 muestras acumuladas en acc
  reg              word_rdy;      // acc listo para emitir
  reg              rd_d;          // s_dat_rd_o retrasado 1 ciclo (latencia BRAM)

  assign busy_o      = (st != W_IDLE);
  assign no_credit_o = (st == W_IDLE) && s_meta_val_i && !credit_ok_i;

  // Emision efectiva este ciclo
  wire fire = wr_val_o && wr_rdy_i;

  // Contadores de slot: NO se tocan con flush_i (ver la nota del puerto).
  always @(posedge clk_i) begin
    if (!rstn_i || clr_cnt_i) begin
      wr_slot_o <= 32'h0;
      seq_o     <= 32'h0;
    end else if (st == W_DONE && !wr_val_o) begin
      wr_slot_o <= wr_slot_o + 1'b1;
      seq_o     <= seq_o + 1'b1;
    end
  end

  always @(posedge clk_i) begin
    if (!rstn_i || flush_i) begin
      st          <= W_IDLE;
      word_idx    <= '0;
      slot_words  <= '0;
      hdr_idx     <= 2'd0;
      samp_left   <= '0;
      acc         <= 64'h0;
      pack_cnt    <= 3'd0;
      word_rdy    <= 1'b0;
      rd_d        <= 1'b0;
      s_dat_rd_o  <= 1'b0;
      s_meta_rd_o <= 1'b0;
      wr_val_o    <= 1'b0;
      wr_dat_o    <= 64'h0;
      ts_r        <= '0;
      snap_r      <= 17'h0;
      nsamp_r     <= '0;
      err_slot_ovf_o <= 1'b0;
    end else begin
      // Guard de geometria: la cabecera + los datos nunca pueden pasarse de la
      // anteultima palabra (la ultima es del footer). Si se pasan, el slot
      // siguiente queda pisado -> se marca sticky y se corta el evento.
      if ((st == W_HDR || st == W_DATA) && (word_idx >= slot_words - 1'b1))
        err_slot_ovf_o <= 1'b1;

      s_meta_rd_o <= 1'b0;
      s_dat_rd_o  <= 1'b0;
      rd_d        <= s_dat_rd_o;

      // wr_val_o se baja cuando la palabra fue aceptada; si no, se sostiene.
      if (fire) wr_val_o <= 1'b0;

      case (st)

        //-------------------------------------------------------------------
        W_IDLE: begin
          word_idx <= '0;
          hdr_idx  <= 2'd0;
          pack_cnt <= 3'd0;
          word_rdy <= 1'b0;
          // !s_meta_rd_o: el pop del metadato anterior recien se refleja en
          // s_meta_val_i un ciclo DESPUES. Sin este guard, al volver de W_DONE
          // se vuelve a leer el MISMO evento y se escribe dos veces — el slot
          // duplicado es indistinguible de uno legitimo del lado del PS.
          if (s_meta_val_i && credit_ok_i && !s_meta_rd_o) begin
            ts_r       <= s_ts_i;
            snap_r     <= s_snap_i;
            nsamp_r    <= s_nsamp_i;
            samp_left  <= s_nsamp_i * N_CH;
            slot_words <= {{(WCW-1){1'b0}}, 1'b1} << (slot_shift_i - 5'd3);
            st         <= W_HDR;
          end
        end

        //-------------------------------------------------------------------
        W_HDR: begin
          if (!wr_val_o || fire) begin
            wr_val_o <= 1'b1;
            case (hdr_idx)
              2'd0: wr_dat_o <= ts_r;
              2'd1: wr_dat_o <= {8'h00, N_CH[7:0],
                                 {{(16-S_AW){1'b0}}, nsamp_r}, seq_o};
              2'd2: wr_dat_o <= {32'h0, 15'h0, snap_r};
              2'd3: wr_dat_o <= 64'h0;
            endcase
            hdr_idx  <= hdr_idx + 1'b1;
            word_idx <= word_idx + 1'b1;
            if (hdr_idx == 2'd3) st <= W_DATA;
          end
        end

        //-------------------------------------------------------------------
        // Empaquetado: 4 muestras de 16 b por palabra. La primera muestra queda
        // en [15:0] (little-endian, para que el PS haga un frombuffer directo).
        W_DATA: begin
          if (word_idx >= slot_words - 1'b1) begin
            // Geometria mal configurada: se trunca el evento acá y se cierra el
            // slot con su footer. Preferible a pisar el slot siguiente; el bit
            // err_slot_ovf_o ya quedó levantado.
            st <= W_FOOT;
          end else if (word_rdy) begin
            if (!wr_val_o || fire) begin
              wr_val_o <= 1'b1;
              wr_dat_o <= acc;
              word_idx <= word_idx + 1'b1;
              word_rdy <= 1'b0;
              pack_cnt <= 3'd0;
              if (samp_left == 0) st <= W_PAD;
            end
          end else if (rd_d) begin
            // dato valido del stage (1 ciclo despues del pop)
            acc      <= {s_dat_i, acc[63:16]};
            pack_cnt <= pack_cnt + 1'b1;
            if (pack_cnt == 3'd3) word_rdy <= 1'b1;
          end else if (samp_left != 0) begin
            s_dat_rd_o <= 1'b1;
            samp_left  <= samp_left - 1'b1;
          end else if (pack_cnt != 3'd0) begin
            // ventana no multiplo de 4: rellenar la palabra con ceros
            acc      <= {16'h0, acc[63:16]};
            pack_cnt <= pack_cnt + 1'b1;
            if (pack_cnt == 3'd3) word_rdy <= 1'b1;
          end else begin
            st <= W_PAD;
          end
        end

        //-------------------------------------------------------------------
        // Relleno hasta la anteultima palabra. Se paga ancho de banda que sobra
        // (el ring usa ~5% de la DDR) a cambio de que el generador de
        // direcciones siga siendo lineal y el layout, aritmetica pura.
        W_PAD: begin
          if (word_idx >= slot_words - 1'b1) begin
            st <= W_FOOT;
          end else if (!wr_val_o || fire) begin
            wr_val_o <= 1'b1;
            wr_dat_o <= 64'h0;
            word_idx <= word_idx + 1'b1;
          end
        end

        //-------------------------------------------------------------------
        W_FOOT: begin
          if (!wr_val_o || fire) begin
            wr_val_o <= 1'b1;
            wr_dat_o <= {~seq_o, seq_o};
            word_idx <= word_idx + 1'b1;
            st       <= W_DONE;
          end
        end

        //-------------------------------------------------------------------
        // El slot se da por cerrado cuando el footer fue ACEPTADO aguas abajo.
        W_DONE: begin
          if (!wr_val_o) begin
            s_meta_rd_o <= 1'b1;
            st          <= W_IDLE;
          end
        end

        default: st <= W_IDLE;
      endcase
    end
  end

endmodule
