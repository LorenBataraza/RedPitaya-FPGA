
// Este es un módulo combinacional con el que determinamos la salida de eventos
// Análogo al rp_trig_src.v pero requiero areg (salida adc_trig registrada).

// Este módulo trabaja por canal de datos.

// Selección de fuentes de 8 bits como MÁSCARA OR:
//   cada bit habilita una clase de fuente y la salida es el OR de las
//   habilitadas. Setear varios bits da el OR entre todas / pares / ternas.

module mt_trig_src #(
  parameter integer CHN   = 0,          // Channel number (interfaz; el cableado decide el par)
  parameter integer SRC_W = 32          // Ancho de la máscara de fuentes
)(
  // ADC
  input                 adc_clk_i       ,  // ADC clock
  input                 adc_rstn_i      ,  // ADC reset - active low

  input                 adc_rst_do_i    , //
  input                 adc_dly_do_i    , // Delay asociado al arm_do?
  input                 trig_dis_clr_i  , // Trigger disable clear
  input                 adc_we_keep_i   , // modo continuo: 1 = ARM se mantiene tras trigger

  //  Fuentes de trigger
  input  [ SRC_W-1: 0]  set_trg_src_i   , // Máscara de fuentes a tener en cuenta
  input                 set_trg_new_i   , // Senal de actualización de trigger de entrada
  input                 dly_valp_i      , // delay valid - immediate pulse

   // Triggers externos
  input                 adc_trig_sw_i   , // Salida manual del trigger

  // Tengo senales posedge (p) y negedge (n)
  input  [ 4-1: 0]      adc_trig_p_i    , // Senales específicas de cada uno de los trigger
  input  [ 4-1: 0]      adc_trig_n_i    ,
  input                 ext_trig_p_i    ,
  input                 ext_trig_n_i    ,
  input                 asg_trig_p_i    , // Externos, no de chainig
  input                 asg_trig_n_i    ,
  input  [ 4-1: 0]      trig_ch_i       , // Triggers de la cadena (otro par)
  input  [ 4-1: 0]      slope_p_i       , // pendiente positiva por canal (mt_slope_trig)
  input  [ 4-1: 0]      slope_n_i       , // pendiente negativa por canal
  input  [ 4-1: 0]      pz_p_i          , // polo-cero por canal (mt_pz_trig)

   // Salidas
  output [ SRC_W-1: 0]  trg_state_o     , // máscara activa (set_trig_src), 32 b
  output                adc_trg_dis_o   , // bit de disable (separado)
  output                adc_trig_o        // trigger en sí (registrado)
);

reg   [ SRC_W-1: 0] set_trig_src  ;
reg                 adc_trg_dis   ;      // Trigger Disable
reg                 adc_trig      ;
wire                adc_trig_sw   ;
reg                 adc_trig_sw_r ;
reg                 adc_trig_sw_d ;

assign adc_trig_sw = (adc_trig_sw_r) && dly_valp_i;

always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0) begin
   adc_trg_dis   <= 1'b0 ;
   set_trig_src  <= {SRC_W{1'b0}} ;
   adc_trig_sw_r <= 1'b0 ;
   adc_trig_sw_d <= 1'b0 ;
end else begin
   if (set_trg_new_i)
      set_trig_src <= set_trg_src_i ;                 // Máscara de fuentes
   // En modo continuo (adc_we_keep_i=1) NO se limpia por dly_do/adc_trig:
   // la máscara persiste para que el FSM pueda re-disparar sin que el SW
   // tenga que re-escribirla. El reset de SW (adc_rst_do_i) siempre limpia.
   else if (adc_rst_do_i || (!adc_we_keep_i && (adc_dly_do_i || adc_trig)))
      set_trig_src <= {SRC_W{1'b0}} ;

   // trig_dis_clr_i: clear del disable
   if (trig_dis_clr_i)
      adc_trg_dis <= 1'b0 ;
   else if (adc_trig)
      adc_trg_dis <= 1'b1 ;

   // Por flanco: una escritura es un disparo. El pulso dura lo que la transacción
   // del bus (6 ciclos, ver mt_cfg), y por nivel, con auto-rearme y holdoff 0,
   // adc_trg_dis se limpia con el pulso todavía arriba y sale un segundo trigger.
   adc_trig_sw_d <= adc_trig_sw_i;
   if (adc_trig_sw_i && !adc_trig_sw_d)  // extend wait for next valid sample
      adc_trig_sw_r <= 1'b1;
   else if (dly_valp_i)
      adc_trig_sw_r <= 1'b0;
end

// Vector de fuentes: 1 bit por entrada de trigger (sin OR colapsado).
// 29 fuentes individuales, bits 31:29 reservados (0).
wire [ SRC_W-1: 0] trg_src_bits;
assign trg_src_bits[0]  = adc_trig_sw   ; // SW manual
assign trg_src_bits[1]  = adc_trig_p_i[0] ; // ADC ch0 posedge
assign trg_src_bits[2]  = adc_trig_n_i[0] ; // ADC ch0 negedge
assign trg_src_bits[3]  = adc_trig_p_i[1] ; // ADC ch1 posedge
assign trg_src_bits[4]  = adc_trig_n_i[1] ; // ADC ch1 negedge
assign trg_src_bits[5]  = adc_trig_p_i[2] ; // ADC ch2 posedge
assign trg_src_bits[6]  = adc_trig_n_i[2] ; // ADC ch2 negedge
assign trg_src_bits[7]  = adc_trig_p_i[3] ; // ADC ch3 posedge
assign trg_src_bits[8]  = adc_trig_n_i[3] ; // ADC ch3 negedge
assign trg_src_bits[9]  = ext_trig_p_i  ; // externo posedge
assign trg_src_bits[10] = ext_trig_n_i  ; // externo negedge
assign trg_src_bits[11] = asg_trig_p_i  ; // ASG posedge
assign trg_src_bits[12] = asg_trig_n_i  ; // ASG negedge
assign trg_src_bits[13] = trig_ch_i[0]  ; // cadena 0
assign trg_src_bits[14] = trig_ch_i[1]  ; // cadena 1
assign trg_src_bits[15] = trig_ch_i[2]  ; // cadena 2
assign trg_src_bits[16] = trig_ch_i[3]  ; // cadena 3
assign trg_src_bits[17] = slope_p_i[0]  ; // pendiente ch0 positiva
assign trg_src_bits[18] = slope_p_i[1]  ; // pendiente ch1 positiva
assign trg_src_bits[19] = slope_p_i[2]  ; // pendiente ch2 positiva
assign trg_src_bits[20] = slope_p_i[3]  ; // pendiente ch3 positiva
assign trg_src_bits[21] = slope_n_i[0]  ; // pendiente ch0 negativa
assign trg_src_bits[22] = slope_n_i[1]  ; // pendiente ch1 negativa
assign trg_src_bits[23] = slope_n_i[2]  ; // pendiente ch2 negativa
assign trg_src_bits[24] = slope_n_i[3]  ; // pendiente ch3 negativa
assign trg_src_bits[25] = pz_p_i[0]     ; // polo-cero ch0
assign trg_src_bits[26] = pz_p_i[1]     ; // polo-cero ch1
assign trg_src_bits[27] = pz_p_i[2]     ; // polo-cero ch2
assign trg_src_bits[28] = pz_p_i[3]     ; // polo-cero ch3
assign trg_src_bits[SRC_W-1:29] = {(SRC_W-29){1'b0}} ; // reservado

// Máscara enmascarada por el disable (igual idea que el original, ahora SRC_W)
wire [ SRC_W-1: 0] src_mask = set_trig_src & {SRC_W{!adc_trg_dis}};
wire [ SRC_W-1: 0] src_hit  = src_mask & trg_src_bits;
wire               trig_comb = |src_hit;

always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0)
   adc_trig <= 1'b0 ;
else
   adc_trig <= trig_comb ;

assign adc_trig_o    = adc_trig;       // trigger registrado
assign trg_state_o   = set_trig_src;   // máscara activa (32 b)
assign adc_trg_dis_o = adc_trg_dis;    // bit de disable

endmodule
