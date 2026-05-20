/**
 * $Id: rp_trig_src.v 2024-03-15
 *
 * @brief Red Pitaya trigger selector logic
 *
 * @Author Jure Trnovec
 *
 * (c) Red Pitaya  http://www.redpitaya.com
 *
 * This part of code is written in Verilog hardware description language (HDL).
 * Please visit http://en.wikipedia.org/wiki/Verilog
 * for more details on the language used herein.
 */


/*
GENERAL DESCRIPTION:
This module selects the trigger source for acquisition. 
Also includes trigger protection logic.
*/

module rp_trig_src #(
  parameter CHN   = 0
)(
  // ADC
  input                 adc_clk_i       ,  // ADC clock
  input                 adc_rstn_i      ,  // ADC reset - active low

  input                 adc_rst_do_i    , // 
  input                 adc_dly_do_i    , // Delay asociado al arm_do?  
  input                 trig_dis_clr_i  , // Trigger disable 

  //  Fuentes de trigger
  input       [ 4-1: 0] set_trg_src_i   , // Sources a tener en cuenta
  input                 set_trg_new_i   , // Senal de actualización de trigger de entrada
  input                 dly_valp_i      , // delay valid - immediate pulse


   // Triggers externos
  input                 adc_trig_sw_i   , // Salida manual del trigger, esta puesta como la primer source de todas.

  // Tengo senales posedge (p) y negedge (n)
  input       [ 4-1: 0] adc_trig_p_i    , // Senales específicas de cada uno de los  trigger 
  input       [ 4-1: 0] adc_trig_n_i    ,
  input                 ext_trig_p_i    ,
  input                 ext_trig_n_i    ,
  input                 asg_trig_p_i    , // Externos
  input                 asg_trig_n_i    ,
  input       [ 4-1: 0] trig_ch_i       , // Parecería que canales llegar a tener en cuenta

   // Salidas  
  output      [ 8-1: 0] trg_state_o     , // Estado de la salida
  output                adc_trig_o        // trigger en sí.
);

reg   [   4-1: 0] set_trig_src     ;
reg               adc_trg_dis      ;      // Trigger Disable
reg               adc_trig         ;
wire              adc_trig_sw      ;
reg               adc_trig_sw_r    ;

assign adc_trig_sw   = (adc_trig_sw_r) && dly_valp_i; // 

always @(posedge adc_clk_i)
if (adc_rstn_i == 1'b0) begin
   adc_trg_dis   <= 1'b0 ;
   set_trig_src  <= 4'h0 ;
   adc_trig_sw_r <= 1'b0 ;
end else begin
   if (set_trg_new_i)
      set_trig_src <= set_trg_src_i ;                 // Tipo de sources a tener en cuenta? 
   else if (adc_dly_do_i || adc_trig || adc_rst_do_i) //delay reached or reset
      set_trig_src <= 4'h0 ;

   // trig_dis_clr_i: Es un clear 
   if (trig_dis_clr_i)
      adc_trg_dis <= 1'b0 ;
   else if (adc_trig)
      adc_trg_dis <= 1'b1 ;


   if (adc_trig_sw_i)// extend wait for next valid sample 
      adc_trig_sw_r <= 1'b1; 
   else if (dly_valp_i)
      adc_trig_sw_r <= 1'b0; 

end

genvar GV;
generate
// Canaliza el trigger a alguna de las fuentes individuales.
if(CHN == 0) begin // Si tnemeos somos el canal cero al parecer tenemos diferentes números
always @(posedge adc_clk_i) begin
   case (set_trig_src & ({4{!adc_trg_dis}}))
       4'd1 : adc_trig <= adc_trig_sw   ; // manual
       4'd2 : adc_trig <= adc_trig_p_i[0] ; // A ch rising edge
       4'd3 : adc_trig <= adc_trig_n_i[0] ; // A ch falling edge
       4'd4 : adc_trig <= adc_trig_p_i[1] ; // B ch rising edge
       4'd5 : adc_trig <= adc_trig_n_i[1] ; // B ch falling edge
       4'd6 : adc_trig <= ext_trig_p_i  ; // external - rising edge
       4'd7 : adc_trig <= ext_trig_n_i  ; // external - falling edge
       4'd8 : adc_trig <= asg_trig_p_i  ; // ASG - rising edge
       4'd9 : adc_trig <= asg_trig_n_i  ; // ASG - falling edge
       4'd10: adc_trig <= trig_ch_i[0] ; // from the other two ADC channels: C ch rising edge
       4'd11: adc_trig <= trig_ch_i[1] ; // from the other two ADC channels: C ch falling edge
       4'd12: adc_trig <= trig_ch_i[2] ; // from the other two ADC channels: D ch rising edge
       4'd13: adc_trig <= trig_ch_i[3] ; // from the other two ADC channels: D ch falling edge
       
       // Multiple trigger source
       4'd14: adc_trig <= adc_trig_p_i[0] | adc_trig_p_i[1]; // A-ch posedge or B-ch posedge  
       4'd15: adc_trig <= adc_trig_n_i[0] | adc_trig_n_i[1]; // A-ch negedge or B-ch negedge
    default : adc_trig <= 1'b0          ; 
   endcase
end

end else begin

always @(posedge adc_clk_i) begin
   case (set_trig_src & ({4{!adc_trg_dis}})) // Hacemos máscara con registro adc_trg_dis
       4'd1 : adc_trig <= adc_trig_sw   ; // manual
       4'd2 : adc_trig <= trig_ch_i[0] ; // A ch rising edge
       4'd3 : adc_trig <= trig_ch_i[1] ; // A ch falling edge
       4'd4 : adc_trig <= trig_ch_i[2] ; // B ch rising edge
       4'd5 : adc_trig <= trig_ch_i[3] ; // B ch falling edge
       4'd6 : adc_trig <= ext_trig_p_i  ; // external - rising edge
       4'd7 : adc_trig <= ext_trig_n_i  ; // external - falling edge
       4'd8 : adc_trig <= asg_trig_p_i  ; // ASG - rising edge
       4'd9 : adc_trig <= asg_trig_n_i  ; // ASG - falling edge
       4'd10: adc_trig <= adc_trig_p_i[0] ; // from the other two ADC channels: C ch rising edge
       4'd11: adc_trig <= adc_trig_n_i[0] ; // from the other two ADC channels: C ch falling edge
       4'd12: adc_trig <= adc_trig_p_i[1] ; // from the other two ADC channels: D ch rising edge
       4'd13: adc_trig <= adc_trig_n_i[1] ; // from the other two ADC channels: D ch falling edge
       
       // Multiple trigger source
       4'd14: adc_trig <= adc_trig_p_i[0] | adc_trig_p_i[1]; // A-ch posedge or B-ch posedge  
       4'd15: adc_trig <= adc_trig_n_i[0] | adc_trig_n_i[1]; // A-ch negedge or B-ch negedge

    default : adc_trig <= 1'b0          ; 
   endcase
end

end
endgenerate


assign adc_trig_o    = adc_trig; // Indica que tipo de trigger tenemos
assign trg_state_o   = {3'h0, adc_trg_dis, set_trig_src}; // 

endmodule