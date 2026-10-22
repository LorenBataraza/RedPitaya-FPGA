# Testbenches de INTEGRACION: los que cruzan modulos.
#
# Los testbenches unitarios viven en modulos/<m>/sim/ y se corren desde
# modulos/<m>/work/. Aca quedan solo los que instancian RTL de mas de un
# modulo a la vez (o del repo raiz), y que por eso no pertenecen a ninguno:
#
#   tb_slots_integration  integration_cfg + rp_scope_multitrigger_com + mca_top
#   tb_trig_capture       multitrigger_event_logic + rp_bram_sm (repo raiz)
#   tb_osc_cfg            osc_cfg contra multitrigger_rp_scope_cfg (diferencial)
#   tb_sys_bus_proto      sys_bus_interconnect + sys_bus_cdc + mca_top: el
#                         protocolo del bus con el RTL de verdad, no con un BFM
#
# Reusa las mismas reglas que los modulos. Esta carpeta hace de modulo y de
# work a la vez, asi que pisa las tres rutas que module.mk deduciria del CURDIR.

MODULE  := integracion
MOD_DIR := $(CURDIR)
SIM_DIR := $(CURDIR)
MODULOS := $(CURDIR)/../modulos

TOP    :=
DEPS   := comun osc multitrigger mca
TBS    := tb_slots_integration \
          tb_trig_capture \
          tb_osc_cfg \
          tb_sys_bus_proto

include ../modulos/mk/module.mk
