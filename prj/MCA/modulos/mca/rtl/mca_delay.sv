`timescale 1ns/1ps
//=============================================================================
// mca_delay — linea de retardo de muestras, para alinear la ventana con trig_i
//
// La ventana la abre el trigger externo (el trigger_event del multitrigger), y
// ese trigger llega TARDE respecto de la muestra que lo causo: el disparo por
// pendiente necesita del orden de L muestras para cruzar su umbral, mas los
// registros de mt_trig_src y mt_event_logic. Si la ventana mirara la muestra
// en vivo arrancaria despues del pie del pulso y perderia el flanco de subida:
// el pico y la integral saldrian truncados. Retrasando la MUESTRA
// cfg_dly_i ciclos, el trigger llega cuando la muestra retrasada todavia esta
// en el pie, y la ventana ve el pulso entero.
//
// El retardo es en CICLOS de adc_clk, no en muestras validas: la latencia del
// trigger es de hardware y no depende de la decimacion propia del MCA. `val`
// viaja con el dato, asi que la decimacion sigue funcionando igual del otro
// lado.
//
// Se infiere en SRL (SRLC32E en cascada, con direccion dinamica): la linea no
// tiene reset, y por eso tiene valor inicial en cero, que Vivado lleva al INIT
// de los SRL. La salida se registra: el clock-to-out de un SRL es lento y esto
// es el comienzo del camino de la muestra. Latencia total: cfg_dly_i + 1.
//
// UNA LINEA POR BIT, como la plantilla de SRL dinamico de UG901 (un vector que
// se corre y una toma `sr[d-1]`). La version anterior, un arreglo de palabras
// corrido con un for, NO se inferia en SRL: daba 510 LUT y 1920 FF, tambien en
// el bitstream. Por bit son 4 SRLC32E en cascada: 60 SRL, ~83 LUT, 15 FF.
//=============================================================================

module mca_delay #(
  parameter integer W    = 15,           // ancho de lo que se retrasa ({val, dat})
  parameter integer DLW  = 7,            // bits de cfg_dly_i
  // Derivado: la linea cubre todo el rango de dly_i. No se sobreescribe.
  parameter integer DMAX = (1 << DLW) - 1
)(
  input              clk_i ,
  input  [W-1:0]     dat_i ,
  input  [DLW-1:0]   dly_i ,      // 0 = sin retardo extra
  output reg [W-1:0] dat_o
);

initial dat_o = {W{1'b0}};

wire [DLW-1:0] toma = dly_i - {{(DLW-1){1'b0}}, 1'b1};
wire [W-1:0]   tap;

genvar gb;
generate for (gb = 0; gb < W; gb = gb + 1) begin : g_bit
  reg [DMAX-1:0] sr = {DMAX{1'b0}};
  always @(posedge clk_i) sr <= {sr[DMAX-2:0], dat_i[gb]};
  // sr[d-1] es la entrada de hace d ciclos; con el registro de salida, d + 1.
  assign tap[gb] = sr[toma];
end endgenerate

always @(posedge clk_i)
  dat_o <= (dly_i == {DLW{1'b0}}) ? dat_i : tap;

endmodule
