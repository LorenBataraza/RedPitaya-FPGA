# Testbenches de INTEGRACION: los que cruzan modulos.
#
# Los testbenches unitarios viven en modulos/<m>/sim/ y se corren desde
# modulos/<m>/work/. Aca quedan solo los que instancian RTL de mas de un
# modulo a la vez (o del repo raiz), y que por eso no pertenecen a ninguno:
#
#   tb_slots_integration  integration_cfg + rp_scope_mt_com + mca_top
#   tb_trig_capture       mt_event_logic + rp_bram_sm (repo raiz)
#   tb_osc_cfg            osc_cfg contra mt_rp_scope_cfg (diferencial)
#   tb_sys_bus_proto      sys_bus_interconnect + sys_bus_cdc + mca_top: el
#                         protocolo del bus con el RTL de verdad, no con un BFM
#   tb_mca_mt_latencia    mt_top + mca_top: la latencia del disparo
#   tb_mca2_volcado       mt_top + mca_top sobre un estimulo: el volcado contra el
#                         que se compara la replica del Monte Carlo
#   tb_pulsos_mca         gen_pulsos (por sys_bus_split) + mt_top + mca_top: el
#                         generador como estimulo, contra su modelo y la replica
#   tb_ring_sistema       scope + multitrigger + event_ring + axi_master, sin MCA,
#                         manejado por el script de placa hw_ring_swtrig.py
#
# Reusa las mismas reglas que los modulos. Esta carpeta hace de modulo y de
# work a la vez, asi que pisa las tres rutas que module.mk deduciria del CURDIR.

MODULE  := integracion
MOD_DIR := $(CURDIR)
SIM_DIR := $(CURDIR)
MODULOS := $(CURDIR)/../modulos

TOP    :=
DEPS   := comun mt osc mca gen_eventos event_ring
TBS    := tb_slots_integration \
          tb_trig_capture \
          tb_osc_cfg \
          tb_sys_bus_proto \
          tb_mca_mt_latencia \
          tb_mca2_volcado \
          tb_pulsos_mca \
          tb_ring_sistema

# El volcado del MCA2 para la replica del Monte Carlo (ver el TB). Lee el
# estimulo de software/monte-carlo/datos_ref/ y escribe ahi el volcado.
PLUS_tb_mca2_volcado := +ESTIM=$(CURDIR)/../software/monte-carlo/datos_ref/mca2_estimulo.txt \
                        +VOLCADO=$(CURDIR)/../software/monte-carlo/datos_ref/mca2_volcado.txt

# El generador de pulsos manejando el MCA (ver el TB). Lee la configuracion de
# software/monte-carlo/datos_ref/ y escribe ahi el volcado.
PLUS_tb_pulsos_mca := +ESTIM=$(CURDIR)/../software/monte-carlo/datos_ref/pulsos_estimulo.txt \
                      +VOLCADO=$(CURDIR)/../software/monte-carlo/datos_ref/pulsos_volcado.txt

# El TB lanza al script de placa y lo atiende por dos FIFOs (ver el TB).
PLUS_tb_ring_sistema := +CLIENTE=$(CURDIR)/correr_hw_ring_swtrig.py \
                        +FIFO=$(CURDIR)/logs/ring_sistema

include ../modulos/mk/module.mk
