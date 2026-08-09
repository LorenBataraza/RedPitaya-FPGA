# Fuentes RTL bajo test (rutas relativas a prj/MCA/sim/).
# DUT del multitrigger (mine/) + la FSM de captura stock (rtl_250/classic/).
../rtl/mine/multitrigger_trig_src.sv
../rtl/mine/trigger_shield.sv
../rtl/mine/multitrigger_event_logic.v
../../../rtl_250/classic/rp_bram_sm.v
# --- MCA ---
../rtl/mine/mca/mca_div_restore.sv
../rtl/mine/mca/mca_hist.sv
../rtl/mine/mca/mca_pulse_feature.sv
../rtl/mine/mca/mca_top.sv
# Ecualizador + su copia congelada, para el TB de equivalencia
../rtl/osc_filter.v
osc_filter_ref.v
