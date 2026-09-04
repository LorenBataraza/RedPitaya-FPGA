# Punto de entrada del proyecto MCA: RTL (QuestaSim) + software (Python).
#
#   make rtl                todos los testbenches de RTL
#   make rtl-tb_mca_top     uno solo
#   make test               los tests de software que corren en la PC
#   make gui-demo           la GUI del MCA contra un MCA falso, sin placa
#   make ring-dump          regenera ring_dump.hex desde el RTL y revalida el decoder
#
# "testbench" significa dos cosas distintas en este proyecto y acá se separan:
#
#   rtl*        los 17 testbenches de SystemVerilog que corren en QuestaSim
#   campana-*   las corridas de caracterización de campanas/testbench_mca.py,
#               que necesitan la placa y el generador
#
# La ayuda detallada de cada mitad:  make -C software help

SIM := sim
SW  := software

.DEFAULT_GOAL := help
.PHONY: help rtl wave test placa mc campanas gui-demo ring-dump todo clean

help:              ## esta ayuda
	@echo "prj/MCA — objetivos:"
	@echo ""
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sort | awk 'BEGIN{FS=":.*?## "}{printf "  %-18s %s\n", $$1, $$2}'
	@echo ""
	@echo "  ayuda detallada:  make -C $(SW) help    |    make -C $(SIM) help"

rtl:               ## todos los testbenches de RTL (QuestaSim, batch)
	$(MAKE) -C $(SIM)

rtl-%:             ## un testbench de RTL: make rtl-tb_event_ring_top
	$(MAKE) -C $(SIM) $*

wave:              ## GUI de ondas: make wave TB=tb_trig_capture
	$(MAKE) -C $(SIM) wave TB=$(TB)

test:              ## tests de software que corren en la PC
	$(MAKE) -C $(SW) test

placa:             ## tests de software que necesitan la Red Pitaya
	$(MAKE) -C $(SW) placa

mc:                ## simulaciones Monte-Carlo
	$(MAKE) -C $(SW) mc

campanas:          ## lista las campañas de caracterización disponibles
	$(MAKE) -C $(SW) campana-lista

gui-demo:          ## la GUI del MCA andando contra un MCA falso, sin placa
	$(MAKE) -C $(SW) gui-demo

# El único acople real entre los dos mundos: el TB del event_ring ESCRIBE el
# volcado que decodifica API/tests/test_ring_format.py, y lo hace con el mismo
# código que usa el lector real (API/modelo_rtl/ring_format.py). Correr los dos
# seguidos es lo que prueba que el formato no se separó del hardware.
ring-dump:         ## regenera ring_dump.hex desde el RTL y revalida el decoder
	$(MAKE) -C $(SIM) tb_event_ring_top
	$(MAKE) -C $(SW) test-modelo

todo: rtl test     ## RTL + software offline (todo lo que corre sin placa)

clean:             ## limpia sim/ y software/
	$(MAKE) -C $(SIM) clean
	$(MAKE) -C $(SW) clean
