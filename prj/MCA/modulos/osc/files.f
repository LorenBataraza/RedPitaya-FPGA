# OSC (slot 1): registros de configuracion + ecualizador del datapath.
rtl/osc_cfg.sv
rtl/osc_filter.v
# El datapath del scope (rp_scope_com + multitrigger), que integra las tres
# regiones. Instancia mt_top (el multitrigger): por eso osc tiene DEPS := mt.
rtl/rp_scope_mt_com.sv
# Mapa de registros legacy: se conserva para el TB diferencial contra osc_cfg
# (prj/MCA/sim/tb_osc_cfg.sv).
rtl/mt_rp_scope_cfg.sv
