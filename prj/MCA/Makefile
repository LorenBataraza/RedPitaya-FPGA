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
#   make bitstream          sintetiza el MCA para la placa del banco (Z10_2CH)
#   make bitstreams         todos los tops: el MCA y el event_ring
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

# Síntesis del bitstream completo. El script de Vivado de cada top vive en la
# raíz del repo (red_pitaya_vivado_Z10_*.tcl) y se corre DESDE ahí. Los
# artefactos llevan la placa y los canales en el nombre
# (out/mca_red_pitaya_Z10_2CH.bit.bin): un .bit.bin no dice para qué placa es
# y cargar uno de 7z010 en una 7z020 traba el FPGA manager hasta reiniciar.
# Hoy sólo existe la variante Z10_2CH (STEMlab 125-14): la placa la fija el
# script, no una variable de acá. Vivado 2020.1 es el que generó ip/systemZ10;
# con otro, el block design pide upgrade.
REPO   := ../..
VIVADO ?= vivado

# Módulos con RTL propio. Es la misma lista que consume rtl_files.tcl para
# armar el bitstream; si agregás uno, va en los dos lados.
MODS := comun osc multitrigger mca event_ring

.DEFAULT_GOAL := help
.PHONY: help rtl rtl-todos $(addprefix rtl-,$(MODS)) wave verificar verificar-placa \
        montecarlo campanas app app-demo placa-estado ring-dump todo limpiar \
        bitstream bitstream-event-ring bitstreams

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

# ~35 min cada uno. El log queda en out/ al lado del bitstream; el script
# aborta solo si bootgen no regeneró el .bit.bin (quedaría el viejo en la placa).
bitstream:         ## sintetiza el MCA: out/mca_red_pitaya_Z10_2CH.bit.bin (~35 min)
	cd $(REPO) && $(VIVADO) -nojournal -nolog -mode batch \
	  -source red_pitaya_vivado_Z10_mca.tcl -tclargs MCA 2>&1 | tee out/build_Z10_2CH.log
	@grep -q "bootgen OK" out/build_Z10_2CH.log
	@grep -A3 "WNS(ns)" out/post_route_timing_summary.rpt | tail -1 | awk '{print "  WNS " $$1 " ns  (endpoints que fallan: " $$3 ")"}'

bitstream-event-ring:  ## sintetiza el top con event_ring: out/v3_event_ring/event_ring_red_pitaya_Z10_2CH.bit.bin
	cd $(REPO) && $(VIVADO) -nojournal -nolog -mode batch \
	  -source red_pitaya_vivado_Z10_v3_event_ring.tcl -tclargs MCA 2>&1 | tee out/v3_event_ring/build_Z10_2CH.log
	@grep -q "bootgen OK" out/v3_event_ring/build_Z10_2CH.log
	@grep -A3 "WNS(ns)" out/v3_event_ring/post_route_timing_summary.rpt | tail -1 | awk '{print "  WNS " $$1 " ns  (endpoints que fallan: " $$3 ")"}'

# En serie a propósito: los dos generan el block design en el mismo .srcs/.
bitstreams: bitstream bitstream-event-ring  ## todos los bitstreams que entran en la release

limpiar:           ## limpia los módulos, sim/ y software/
	@for m in $(MODS); do $(MAKE) --no-print-directory -C $(MODULOS)/$$m/work clean; done
	$(MAKE) -C $(SIM) clean
	$(MAKE) -C $(SW) limpiar
