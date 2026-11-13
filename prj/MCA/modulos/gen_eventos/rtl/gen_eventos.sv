`timescale 1ns/1ps
//=============================================================================
// gen_eventos — generador de disparos y de un dato conocido, para probar el
// event_ring a la tasa que se quiera sin el estimulo analogico.
//
// Va entre la cadena del scope y la captura del ring (event_ring_top lo
// instancia con EN_GEN = 1). APAGADO ES UN CABLE: el dato, el valid, el
// disparo y el snapshot pasan por un mux combinacional, sin registro, asi el
// ring es identico al de antes y sus testbenches corren sin cambios. Prendido
// reemplaza dos cosas, cada una por su bit de CTRL:
//
//   DISPAROS (bit en). Periodicos (cada PERIODO ciclos) o aleatorios (un
//   Poisson discreto con tiempo muerto DT_MIN): los decide gen_disparos.sv, el
//   motor que comparte con gen_pulsos. Ver su cabecera.
//
//   DATO (bit patron). Cada canal lleva el reloj del ring (ts_i) del mismo
//   ciclo, el impar complementado: ch0 = ts[DW-1:0], ch1 = ~ts[DW-1:0]. Como el ring
//   escribe ese mismo reloj en la cabecera, cada muestra de cada ventana se
//   verifica contra el timestamp del evento (docs/event_ring/generador.md).
//
// QUE SE CUENTA. GEN_CNT cuenta los pulsos que SALEN, y solo salen con el ring
// en RUNNING (run_i): en DRAINING la captura ya no acepta, y un disparo ahi no
// lo contaria nadie. Asi cierra exacto
//       EV_CNT + DROP_BUSY + DROP_FULL == GEN_CNT
// El snapshot de cada disparo generado es {1, k[15:0]}, con k el indice del
// disparo desde el arranque: el lector sabe cuales se perdieron, uno por uno.
//
// EL RELOJ DEL GENERADOR. El estado (xorshift, contador del periodo, GEN_CNT)
// se reinicia al arrancar el ring y al prender en, y avanza solo mientras el
// ring esta en RUNNING. Con la misma SEMILLA, los disparos caen siempre en el
// mismo ts: el modelo (modelos/python_model) los predice.
//
// La captura toma el disparo por FLANCO: dos pulsos seguidos serian uno. Por
// eso PERIODO y DT_MIN valen 2 como minimo (si se escribe menos, se usa 2;
// lo hace gen_disparos).
//
// Registros (sys_addr[7:0]; event_ring_top lo pone en 0x100 del slot 2):
//   0x00 RW CTRL     [0] en  [1] aleatorio  [2] patron
//   0x04 RW PERIODO  ciclos entre disparos, modo periodico (>= 2)
//   0x08 RW UMBRAL   probabilidad por ciclo * 2^32, modo aleatorio
//   0x0C RW DT_MIN   ciclos minimos entre disparos, modo aleatorio (>= 2; 16 bits)
//   0x10 RW N        cuantos disparos; 0 = sin fin
//   0x14 RW SEMILLA  del xorshift; 0 usa 0x2545F491 (el xorshift no sale del 0)
//   0x18 R  GEN_CNT  disparos que salieron desde el arranque
//   0x1C R  ESTADO   [0] generando  [1] llego a N
//   0x20 R  MAGIC    "GEN1"
//=============================================================================
module gen_eventos #(
  parameter integer N_CH = 2,
  parameter integer DW   = 14,
  parameter integer TS_W = 64
)(
  input                      clk_i,
  input                      rstn_i,

  // lo que llega de la cadena del scope
  input      [N_CH*DW-1:0]   dat_i,
  input                      dv_i,
  input                      trig_i,
  input      [16:0]          snap_i,

  // del ring
  input      [TS_W-1:0]      ts_i,      // su reloj libre: el de la cabecera
  input                      run_i,     // RUNNING: solo ahi salen disparos generados

  // hacia la captura del ring (combinacional: ver arriba)
  output     [N_CH*DW-1:0]   dat_o,
  output                     dv_o,
  output                     trig_o,
  output     [16:0]          snap_o,

  // bus de sistema
  input      [32-1:0]        sys_addr,
  input      [32-1:0]        sys_wdata,
  input                      sys_wen,
  input                      sys_ren,
  output reg [32-1:0]        sys_rdata,
  output reg                 sys_err,
  output reg                 sys_ack
);

localparam [31:0] MAGIC      = 32'h4745_4E31;   // "GEN1"

//-----------------------------------------------------------------------------
// Registros
//-----------------------------------------------------------------------------
reg        cfg_en, cfg_aleat, cfg_patron;
reg [31:0] cfg_periodo, cfg_umbral, cfg_n, cfg_semilla;
reg [15:0] cfg_dt_min;

wire [7:0] a = sys_addr[7:0];

always @(posedge clk_i) begin
  if (!rstn_i) begin
    cfg_en      <= 1'b0;
    cfg_aleat   <= 1'b0;
    cfg_patron  <= 1'b0;
    cfg_periodo <= 32'd1000;
    cfg_umbral  <= 32'd0;
    cfg_dt_min  <= 16'd2;
    cfg_n       <= 32'd0;
    cfg_semilla <= 32'd0;
  end else if (sys_wen) begin
    case (a)
      8'h00: {cfg_patron, cfg_aleat, cfg_en} <= sys_wdata[2:0];
      8'h04: cfg_periodo <= sys_wdata;
      8'h08: cfg_umbral  <= sys_wdata;
      8'h0C: cfg_dt_min  <= sys_wdata[15:0];
      8'h10: cfg_n       <= sys_wdata;
      8'h14: cfg_semilla <= sys_wdata;
      default: ;
    endcase
  end
end

//-----------------------------------------------------------------------------
// Los disparos: el motor compartido con gen_pulsos (gen_disparos.sv)
//-----------------------------------------------------------------------------
wire        disp_c;     // el disparo decidido en este ciclo
wire        trig_gen;   // el decidido el ciclo anterior, sin el gateo de run_i
wire        pulso;      // el que sale: trig_gen con el ring en RUNNING
wire        hecho, activo;
wire [31:0] gen_cnt;
wire [15:0] hold;

gen_disparos u_disp (
  .clk_i      (clk_i),       .rstn_i    (rstn_i),
  .en_i       (cfg_en),      .run_i     (run_i),
  .aleat_i    (cfg_aleat),   .periodo_i (cfg_periodo), .umbral_i (cfg_umbral),
  .dt_min_i   (cfg_dt_min),  .n_i       (cfg_n),       .semilla_i(cfg_semilla),
  .arranque_o (),            .disp_o    (disp_c),      .pulso_o  (pulso),
  .cnt_o      (gen_cnt),     .activo_o  (activo),      .hecho_o  (hecho),
  .hold_o     (hold),        .trig_gen_o(trig_gen)
);

// El pulso sale un ciclo despues de decidirse, y solo con el ring en RUNNING
// en ESE ciclo: es la misma condicion con la que la captura lo acepta.
assign trig_o = cfg_en ? pulso : trig_i;

//-----------------------------------------------------------------------------
// Dato y snapshot
//-----------------------------------------------------------------------------
genvar c;
wire [N_CH*DW-1:0] patron;
generate for (c = 0; c < N_CH; c = c + 1) begin : g_patron
  assign patron[c*DW +: DW] = (c % 2) ? ~ts_i[DW-1:0] : ts_i[DW-1:0];
end endgenerate

assign dat_o = cfg_patron ? patron : dat_i;
assign dv_o  = dv_i;

// En el ciclo del pulso, gen_cnt todavia no lo conto: es el indice k.
assign snap_o = cfg_en ? {1'b1, gen_cnt[15:0]} : snap_i;

//-----------------------------------------------------------------------------
// Lectura y ack (latencia fija, como el ring)
//-----------------------------------------------------------------------------
always @(posedge clk_i) begin
  sys_err <= 1'b0;
  case (a)
    8'h00:   sys_rdata <= {29'h0, cfg_patron, cfg_aleat, cfg_en};
    8'h04:   sys_rdata <= cfg_periodo;
    8'h08:   sys_rdata <= cfg_umbral;
    8'h0C:   sys_rdata <= {16'h0, cfg_dt_min};
    8'h10:   sys_rdata <= cfg_n;
    8'h14:   sys_rdata <= cfg_semilla;
    8'h18:   sys_rdata <= gen_cnt;
    8'h1C:   sys_rdata <= {30'h0, hecho, activo};
    8'h20:   sys_rdata <= MAGIC;
    default: sys_rdata <= 32'h0;
  endcase
end

reg [2:0] ack_sr;
always @(posedge clk_i) begin
  if (!rstn_i) begin ack_sr <= 3'h0; sys_ack <= 1'b0; end
  else begin
    ack_sr  <= {ack_sr[1:0], (sys_wen || sys_ren)};
    sys_ack <= ack_sr[1];
  end
end

endmodule
