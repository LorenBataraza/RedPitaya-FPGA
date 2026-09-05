# RTL del repo raiz que necesita rp_scope_multitrigger_com (el datapath del
# scope). Rutas relativas a la raiz del repo.
#
# OJO con rp_bram_sm.v: antes se compilaba la copia de rtl_250/classic/, pero
# Vivado sintetiza la de rtl/classic/ (el TCL hace `add_files ../../rtl`, nunca
# rtl_250). Son funcionalmente identicas -el diff son comentarios- pero divergen
# apenas alguien toque una. Se compila la que se sintetiza.
rtl/divide.v
rtl/classic/rp_scope_calib.v
rtl/classic/rp_decim.v
rtl/classic/rp_delay.v
rtl/classic/rp_adc_trig.v
rtl/classic/rp_acq_bram.v
rtl/classic/rp_axi_sm.v
# rp_axi_sm instancia axi_wr_fifo. event_ring tambien lo pide; el .f duplicado
# no molesta, module.mk deduplica preservando el orden.
rtl/classic/axi_wr_fifo.v
rtl/classic/rp_ext_trig.v
rtl/classic/rp_bram_sm.v
