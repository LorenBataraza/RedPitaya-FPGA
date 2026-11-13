`timescale 1ns/1ps
//=============================================================================
// sys_bus_split — un slot del bus de sistema repartido entre dos esclavos
//
// El slot es de 1 MB (sys_addr[19:0]). Los 64 KB con sys_addr[19:16] == SEL_B
// van al esclavo B, y todo lo demas al A. Lo usa el top para el slot 2, el del
// ASG de Red Pitaya: 0x4020_0000 es del event_ring (o un stub en el top del
// MCA) y 0x4021_0000 del generador de pulsos (gen_pulsos).
//
// Combinacional, sin registros: el esclavo elegido ve el wen/ren tal cual, y su
// rdata, err y ack vuelven tal cual. El otro no ve nada. Sirve porque
// sys_bus_cdc sostiene la direccion quieta desde el wen/ren hasta el ack, asi
// que la eleccion no cambia en medio de una transaccion.
//
// La direccion pasa entera a los dos: cada esclavo decodifica sus bits.
//=============================================================================
module sys_bus_split #(
  parameter [3:0] SEL_B = 4'h1
)(
  // el slot, del lado del interconnect
  input      [31:0] s_addr,
  input      [31:0] s_wdata,
  input             s_wen,
  input             s_ren,
  output     [31:0] s_rdata,
  output            s_err,
  output            s_ack,

  // esclavo A: todo menos SEL_B
  output     [31:0] a_addr,
  output     [31:0] a_wdata,
  output            a_wen,
  output            a_ren,
  input      [31:0] a_rdata,
  input             a_err,
  input             a_ack,

  // esclavo B: sys_addr[19:16] == SEL_B
  output     [31:0] b_addr,
  output     [31:0] b_wdata,
  output            b_wen,
  output            b_ren,
  input      [31:0] b_rdata,
  input             b_err,
  input             b_ack
);

wire sel_b = (s_addr[19:16] == SEL_B);

assign a_addr  = s_addr;
assign a_wdata = s_wdata;
assign a_wen   = s_wen && !sel_b;
assign a_ren   = s_ren && !sel_b;

assign b_addr  = s_addr;
assign b_wdata = s_wdata;
assign b_wen   = s_wen &&  sel_b;
assign b_ren   = s_ren &&  sel_b;

assign s_rdata = sel_b ? b_rdata : a_rdata;
assign s_err   = sel_b ? b_err   : a_err;
assign s_ack   = sel_b ? b_ack   : a_ack;

endmodule
