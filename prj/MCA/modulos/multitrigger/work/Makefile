MODULE := multitrigger
TOP    := multitrigger_cfg
# rp_scope_multitrigger_com instancia el ecualizador de osc y los bloques
# classic del repo raiz; por eso arrastra osc como DEPS y tiene extra.f.
DEPS   := osc
TBS    := tb_multitrigger_cfg \
          tb_multitrigger_trig_src \
          tb_multitrigger_event_logic \
          tb_trigger_shield

include ../../mk/module.mk
