MODULE := osc
TOP    := osc_cfg
# rp_scope_mt_com (el datapath del scope) instancia mt_top (el multitrigger)
# y los bloques classic del repo raiz (extra.f).
# (mt arrastra a comun: mt_pz_trig usa su mca_trap).
DEPS   := comun mt
TBS    := tb_osc_filter

include ../../mk/module.mk
