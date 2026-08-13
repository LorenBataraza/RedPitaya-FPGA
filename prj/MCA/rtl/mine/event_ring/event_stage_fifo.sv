`timescale 1ns/1ps
//=============================================================================
// event_stage_fifo — buffer elastico entre la captura de ventana y el writer AXI.
//
// POR QUE EXISTE. La captura produce muestras al ritmo del ADC y no se puede
// frenar (las muestras del post-trigger llegan cuando llegan). El writer, en
// cambio, se frena: espera creditos de DDR y espera al axi_wr_fifo. Sin un
// buffer en el medio, cualquier hipo del writer corrompe la ventana en vuelo.
// Con E eventos de capacidad, la captura puede empezar el evento N+1 mientras
// el writer todavia drena el N.
//
// GARANTIA DE EVENTO ENTERO. `s_accept_o` es la respuesta a "¿entra una ventana
// COMPLETA?" y se consulta en el ciclo del trigger, antes de aceptar nada. Si
// da 0 el evento se descarta entero aguas arriba. Nunca se guarda media
// ventana: un evento parcial en el ring seria indistinguible de uno bueno del
// lado del PS.
//
// Dos colas en paralelo: una de muestras (BRAM) y una de metadatos (E entradas,
// registros). El writer las consume desacopladas — primero lee el metadato para
// armar la cabecera, despues drena las muestras.
//=============================================================================

module event_stage_fifo #(
  parameter integer SW       = 16,  // ancho de muestra
  parameter integer S_AW     = 11,  // ancho del contador de muestras/canal
  parameter integer TS_W     = 64,
  parameter integer DATA_AW  = 12,  // cola de muestras: 2^DATA_AW palabras
  parameter integer E        = 4    // eventos simultaneos en vuelo
)(
  input                    clk_i,
  input                    rstn_i,
  input                    flush_i,      // vacia todo (parada de adquisicion)

  // longitud de ventana en MUESTRAS TOTALES (pre+post)*N_CH, para el chequeo
  // de espacio en el SOF
  input      [S_AW+2:0]    win_len_i,

  // --- escritura (desde event_window_capture) -----------------------------
  output                   s_accept_o,   // ¿entra una ventana completa?
  input                    s_val_i,
  input                    s_sof_i,
  input                    s_eof_i,
  input      [SW-1:0]      s_dat_i,
  input      [TS_W-1:0]    s_ts_i,       // valido con s_sof_i
  input      [16:0]        s_snap_i,     // valido con s_sof_i
  input      [S_AW-1:0]    s_nsamp_i,    // valido con s_sof_i

  // --- lectura (hacia event_slot_writer) ----------------------------------
  output                   m_meta_val_o, // hay al menos un evento COMPLETO
  output     [TS_W-1:0]    m_ts_o,
  output     [16:0]        m_snap_o,
  output     [S_AW-1:0]    m_nsamp_o,
  input                    m_meta_rd_i,  // pop del metadato (fin del evento)

  output     [SW-1:0]      m_dat_o,
  input                    m_dat_rd_i,   // pop de una muestra

  // --- diagnostico ---------------------------------------------------------
  output     [DATA_AW:0]   lvl_o,        // ocupacion de la cola de muestras
  output     [$clog2(E+1)-1:0] ev_lvl_o  // eventos en vuelo
);

  localparam integer DATA_N = (1<<DATA_AW);
  localparam integer EAW    = $clog2(E);

  //--------------------------------------------------------------------------
  // Cola de muestras
  //--------------------------------------------------------------------------
  reg [SW-1:0]      mem [0:DATA_N-1];
  reg [DATA_AW-1:0] wr_ptr, rd_ptr;
  reg [DATA_AW:0]   lvl;

  wire push = s_val_i;
  wire pop  = m_dat_rd_i;

  always @(posedge clk_i) begin
    if (push) mem[wr_ptr] <= s_dat_i;
  end

  // Lectura registrada: m_dat_o vale el ciclo DESPUES del pop. El writer lo
  // tiene en cuenta (pipeline de 1 ciclo entre pop y palabra util).
  reg [SW-1:0] dout_r;
  always @(posedge clk_i) begin
    dout_r <= mem[rd_ptr];
  end
  assign m_dat_o = dout_r;

  always @(posedge clk_i) begin
    if (!rstn_i || flush_i) begin
      wr_ptr <= '0;
      rd_ptr <= '0;
      lvl    <= '0;
    end else begin
      if (push) wr_ptr <= wr_ptr + 1'b1;
      if (pop)  rd_ptr <= rd_ptr + 1'b1;
      case ({push, pop})
        2'b10:   lvl <= lvl + 1'b1;
        2'b01:   lvl <= lvl - 1'b1;
        default: ;
      endcase
    end
  end

  assign lvl_o = lvl;
  wire [DATA_AW:0] free = DATA_N[DATA_AW:0] - lvl;

  //--------------------------------------------------------------------------
  // Cola de metadatos. Se escribe en el SOF y se marca COMPLETA en el EOF: el
  // writer no debe ver un evento cuyas muestras todavia estan entrando, porque
  // podria drenarlas mas rapido de lo que llegan y leer basura.
  //--------------------------------------------------------------------------
  reg [TS_W-1:0]   meta_ts   [0:E-1];
  reg [16:0]       meta_snap [0:E-1];
  reg [S_AW-1:0]   meta_ns   [0:E-1];
  reg [EAW-1:0]    meta_wr, meta_rd;
  reg [$clog2(E+1)-1:0] meta_lvl;   // eventos COMPLETOS disponibles
  reg              meta_open;       // hay un evento a medio entrar

  always @(posedge clk_i) begin
    if (s_val_i && s_sof_i) begin
      meta_ts  [meta_wr] <= s_ts_i;
      meta_snap[meta_wr] <= s_snap_i;
      meta_ns  [meta_wr] <= s_nsamp_i;
    end
  end

  always @(posedge clk_i) begin
    if (!rstn_i || flush_i) begin
      meta_wr   <= '0;
      meta_rd   <= '0;
      meta_lvl  <= '0;
      meta_open <= 1'b0;
    end else begin
      if (s_val_i && s_sof_i) meta_open <= 1'b1;
      if (s_val_i && s_eof_i) begin
        meta_open <= 1'b0;
        meta_wr   <= meta_wr + 1'b1;
      end
      if (m_meta_rd_i) meta_rd <= meta_rd + 1'b1;

      case ({(s_val_i && s_eof_i), m_meta_rd_i})
        2'b10:   meta_lvl <= meta_lvl + 1'b1;
        2'b01:   meta_lvl <= meta_lvl - 1'b1;
        default: ;
      endcase
    end
  end

  assign m_meta_val_o = (meta_lvl != 0);
  assign m_ts_o       = meta_ts  [meta_rd];
  assign m_snap_o     = meta_snap[meta_rd];
  assign m_nsamp_o    = meta_ns  [meta_rd];
  assign ev_lvl_o     = meta_lvl;

  //--------------------------------------------------------------------------
  // Aceptacion: hay lugar para la ventana entera Y hay una entrada de metadato
  // libre (contando la que pudiera estar a medio llenar).
  //--------------------------------------------------------------------------
  // Comparaciones ensanchadas a 32 b a proposito: con las anchuras nativas, la
  // relacion entre DATA_AW y S_AW depende de la parametrizacion y el
  // zero-extend puede quedar de ancho negativo (no compila) o, peor, truncar.
  wire [31:0] free32    = {{(32-DATA_AW-1){1'b0}}, free};
  wire [31:0] winlen32  = {{(32-S_AW-3){1'b0}}, win_len_i};
  wire [31:0] metalvl32 = {{(32-$clog2(E+1)){1'b0}}, meta_lvl} + {31'h0, meta_open};

  wire meta_full    = (metalvl32 >= E);
  assign s_accept_o = (free32 >= winlen32) && !meta_full;

endmodule
