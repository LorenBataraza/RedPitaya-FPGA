# Multitrigger (slot 3): fuentes de disparo, escudo, logica de eventos y
# registros, juntos en mt_top. El datapath del scope que lo instancia vive en
# modulos/osc.
rtl/mt_trig_src.sv
rtl/mt_slope_trig.sv
rtl/mt_pz_trig.sv
rtl/trigger_shield.sv
rtl/mt_event_logic.v
rtl/mt_cfg.sv
# El multitrigger entero: instancia todo lo de arriba, mas rp_adc_trig y
# rp_ext_trig del repo raiz (extra.f).
rtl/mt_top.sv
