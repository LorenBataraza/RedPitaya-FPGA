# Restricciones para la sintesis out-of-context de event_ring_top.
#
# Vivado evalua el XDC como Tcl, asi que el periodo puede venir del entorno:
# eso es lo que hace posible el barrido en frecuencia (make sweep) sin generar
# un XDC por punto. Default 8 ns = 125 MHz, el adc_clk real de la Red Pitaya.
set PERIOD [expr {[info exists ::env(PERIOD_NS)] ? $::env(PERIOD_NS) : 8.0}]

create_clock -period $PERIOD -name adc_clk [get_ports adc_clk_i]

# 10% del periodo de margen en los bordes. En OOC los puertos del modulo no son
# pines del chip: esto modela el resto del diseno, no el pad.
set D [expr {$PERIOD * 0.10}]
set_input_delay  -clock adc_clk $D [remove_from_collection [all_inputs] [get_ports adc_clk_i]]
set_output_delay -clock adc_clk $D [all_outputs]

