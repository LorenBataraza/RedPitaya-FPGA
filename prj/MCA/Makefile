# Punto de entrada del proyecto MCA: RTL (QuestaSim) + software (Python).
#
#   make rtl                todos los testbenches de RTL
#   make rtl-mca            todos los de un modulo
#   make rtl-tb_mca_top     uno solo (busca solo en que modulo esta)
#   make verificar          los tests de software que corren en la PC
#   make app                la sesión entera: servidor + generador + GUI
#   make app-demo           la GUI del MCA contra un MCA falso, sin placa
#   make placa-estado       ¿responde la placa? ¿qué bitstream tiene?
#   make ring-dump          regenera ring_dump.hex desde el RTL y revalida el decoder
#
# "testbench" significa dos cosas distintas en este proyecto y acá se separan:
#
#   rtl*        los 19 testbenches de SystemVerilog que corren en QuestaSim
#   campana-*   las corridas de caracterización de campanas/testbench_mca.py,
#               que necesitan la placa y el generador
#
# El RTL está repartido en modulos/<m>/, cada uno autocontenido (rtl, sim, syn,
# lint, modelos, uvm) y con su propio punto de entrada en modulos/<m>/work.
# En sim/ quedan sólo los testbenches que cruzan módulos.
# La ayuda detallada de cada mitad:  make -C software help

SIM := sim
SW  := software
MODULOS := modulos

# Módulos con RTL propio. Es la misma lista que consume rtl_files.tcl para
# armar el bitstream; si agregás uno, va en los dos lados.
MODS := comun osc multitrigger mca event_ring

.DEFAULT_GOAL := help
.PHONY: help rtl rtl-todos $(addprefix rtl-,$(MODS)) wave verificar verificar-placa \
        montecarlo campanas app app-demo placa-estado ring-dump todo limpiar

help:              ## esta ayuda
	@echo "prj/MCA — objetivos:"
	@echo ""
	@# Se separa el nombre antes de ordenar: con la línea entera, `rtl:` cae
	@# después de `rtl-integracion:` porque el '-' precede al ':' en ASCII.
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sed 's/:.*## /\t/' | LC_ALL=C sort \
	  | awk -F'\t' '{printf "  %-18s %s\n", $$1, $$2}'
	@echo ""
	@echo "  módulos:  $(MODS)"
	@echo "  ayuda detallada:  make -C $(SW) help    |    make -C $(MODULOS)/mca/work help"

# Corre todos los módulos y después los TB de integración. No corta en el
# primer módulo que falle: interesa el panorama completo.
rtl:               ## todos los testbenches de RTL (QuestaSim, batch)
	@fail=""; \
	 for m in $(MODS); do \
	   $(MAKE) --no-print-directory -C $(MODULOS)/$$m/work || fail="$$fail $$m"; \
	 done; \
	 $(MAKE) --no-print-directory -C $(SIM) || fail="$$fail integracion"; \
	 echo ""; \
	 if [ -n "$$fail" ]; then echo "MODULOS CON FALLAS:$$fail"; exit 1; \
	 else echo "TODO OK: $(words $(MODS)) módulos + integración"; fi

$(addprefix rtl-,$(MODS)):   ## un módulo entero: make rtl-mca
	$(MAKE) -C $(MODULOS)/$(patsubst rtl-%,%,$@)/work

rtl-integracion:   ## sólo los testbenches que cruzan módulos
	$(MAKE) -C $(SIM)

# Un TB suelto sin tener que acordarse de en qué módulo quedó.
rtl-%:             ## un testbench: make rtl-tb_event_ring_top
	@d=$$(for m in $(MODS); do \
	        test -f $(MODULOS)/$$m/sim/$*.sv && echo $(MODULOS)/$$m/work; \
	      done; test -f $(SIM)/$*.sv && echo $(SIM)); \
	 test -n "$$d" || { echo "no encontré $*.sv en ningún módulo ni en $(SIM)/"; exit 1; }; \
	 $(MAKE) -C $$d $*

wave:              ## GUI de ondas ya grabadas: make wave TB=tb_trig_capture
	@d=$$(for m in $(MODS); do \
	        test -f $(MODULOS)/$$m/sim/$(TB).sv && echo $(MODULOS)/$$m/work; \
	      done; test -f $(SIM)/$(TB).sv && echo $(SIM)); \
	 test -n "$$d" || { echo "uso: make wave TB=<tb>"; exit 1; }; \
	 $(MAKE) -C $$d wave TB=$(TB)

verificar:         ## tests de software que corren en la PC
	$(MAKE) -C $(SW) verificar

verificar-placa:   ## tests de software que necesitan la Red Pitaya
	$(MAKE) -C $(SW) verificar-placa

montecarlo:        ## simulaciones Monte-Carlo
	$(MAKE) -C $(SW) montecarlo

campanas:          ## lista las campañas de caracterización disponibles
	$(MAKE) -C $(SW) campana-lista

app:               ## la sesión entera: servidor en la placa + generador + GUI acá
	$(MAKE) -C $(SW) app

app-demo:          ## la GUI del MCA andando contra un MCA falso, sin placa
	$(MAKE) -C $(SW) app-demo

placa-estado:      ## ¿responde la placa? ¿qué PL tiene? ¿hay servidor?
	$(MAKE) -C $(SW) placa-estado

# El único acople real entre los dos mundos: el TB del event_ring ESCRIBE el
# volcado que decodifica API/tests/test_ring_format.py, y lo hace con el mismo
# código que usa el lector real (API/modelo_rtl/ring_format.py). Correr los dos
# seguidos es lo que prueba que el formato no se separó del hardware.
ring-dump:         ## regenera ring_dump.hex desde el RTL y revalida el decoder
	$(MAKE) -C $(MODULOS)/event_ring/work tb_event_ring_top
	$(MAKE) -C $(SW) verificar-modelo

todo: rtl verificar  ## RTL + software offline (todo lo que corre sin placa)

limpiar:           ## limpia los módulos, sim/ y software/
	@for m in $(MODS); do $(MAKE) --no-print-directory -C $(MODULOS)/$$m/work clean; done
	$(MAKE) -C $(SIM) clean
	$(MAKE) -C $(SW) limpiar
