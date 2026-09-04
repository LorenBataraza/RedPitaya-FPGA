# Makefile del software del MCA: tests, simulaciones Monte-Carlo y campañas.
#
#   make                ayuda
#   make test           TODO lo que corre en una PC (sin placa, sin Rigol)
#   make placa          TODO lo que necesita la Red Pitaya
#   make mc             las simulaciones Monte-Carlo
#   make campana-mca    la campaña de caracterización del MCA (placa + Rigol)
#
# "testbench" es ambigua en este proyecto y acá se desambigua: los testbenches
# de RTL (SystemVerilog, QuestaSim) NO están en este fichero. Corren con
# `make -C ../sim`, o `make rtl` desde prj/MCA.

PY     ?= python3
PYTEST ?= $(PY) -m pytest
PFLAGS ?=

RAIZ   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
STAMP  := $(shell date +%Y%m%d_%H%M%S)

# Campañas: dónde guardar y con qué canales.
OUT      ?= datos/mca_$(STAMP)
DIR      ?=
CH       ?= 0
GEN_CH   ?= 1
DURACION ?= 60
THR      ?= 0.2

# Detección de placa: el módulo `rp` sólo existe en la Red Pitaya. Se mira el
# directorio en vez de importar, para no pagar el import en cada invocación.
EN_PLACA := $(shell test -d /opt/redpitaya/lib/python && echo si)
PITAYA   ?= pitaya
REMOTO   ?= /home/jupyter/RedPitaya/remote_soft

# Para los scripts que se invocan sueltos (no vía pytest): pytest resuelve la
# raíz con `pythonpath` de pyproject.toml, pero `python3 campanas/x.py` no.
export PYTHONPATH := $(RAIZ):$(PYTHONPATH)

.DEFAULT_GOAL := help

.PHONY: help test test-api test-app test-mc test-campanas test-modelo \
        compat baseline lint \
        mc mc-rapido mc-apilamiento mc-linea-base mc-pico-carga mc-figuras \
        campana-lista campana-mca campana-campana campana-resto campana-formas \
        campana-e2e campana-poisson adquirir \
        graficos-mca graficos-formas graficos-tasa analisis-estimadores \
        placa placa-mem placa-buffer placa-mca placa-diag placa-ring \
        placa-rigol placa-e2e bench exige-placa \
        gui servidor servidor-falso \
        sync remoto-test remoto-placa remoto-bench \
        clean clean-pyc distclean

# ------------------------------------------------------------------ ayuda ---
help:              ## esta ayuda
	@echo "software del MCA — objetivos disponibles:"
	@echo ""
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sort | awk 'BEGIN{FS=":.*?## "}{printf "  %-22s %s\n", $$1, $$2}'
	@echo ""
	@echo "  (P) necesita la Red Pitaya      (R) necesita además el Rigol DG4162"
	@echo "  esta máquina es placa: $(if $(EN_PLACA),SÍ,no)"
	@echo "  variables: OUT=$(OUT)"
	@echo "             CH=$(CH)  GEN_CH=$(GEN_CH)  PITAYA=$(PITAYA)"
	@echo ""
	@echo "  los testbenches de RTL (QuestaSim) van aparte:  make -C ../sim"

# --------------------------------------------------- tests que corren en PC --
test: test-api test-app test-mc test-campanas   ## toda la suite offline (PC)
	@echo "OK: suite offline completa"

test-api:          ## tests offline de API/ (driver, red, pipeline, análisis)
	$(PYTEST) $(PFLAGS) API/tests

test-app:          ## tests offline de app/ (servidor, cliente remoto, GUI headless)
	$(PYTEST) $(PFLAGS) app/tests

test-mc:           ## tests del motor Monte-Carlo (réplica vectorizada vs RTL)
	$(PYTEST) $(PFLAGS) monte-carlo

test-campanas:     ## tests offline de los drivers de campaña (MCA simulado)
	$(PYTEST) $(PFLAGS) campanas/tests

test-modelo:       ## sólo los modelos de referencia del RTL (estimadores, ring)
	$(PYTEST) $(PFLAGS) API/tests/test_estimadores.py API/tests/test_ring_format.py

compat:            ## el baseline de compatibilidad sigue valiendo (no escribe)
	$(PY) API/tests/test_compat_api.py

baseline:          ## REGENERA el baseline de compatibilidad (revisar el diff!)
	$(PY) API/tests/gen_compat_baseline.py

lint:              ## compila todo y pasa pyflakes si está instalado
	$(PY) -m compileall -q API app campanas monte-carlo *.py
	@command -v pyflakes >/dev/null 2>&1 \
	  && pyflakes API app campanas monte-carlo *.py \
	  || echo "(pyflakes no instalado, salteado)"

# ------------------------------------------------------------- Monte-Carlo ---
mc: mc-apilamiento mc-linea-base mc-pico-carga   ## todas las simulaciones (~15 min)
	@echo "OK: simulaciones Monte-Carlo completas"

mc-rapido:         ## barrido de apilamiento corto, para ver que corre
	$(PY) monte-carlo/montecarlo.py --n-eventos 5000

mc-apilamiento:    ## Monte-Carlo de apilamiento: barrido de tasa (~5 min)
	$(PY) monte-carlo/montecarlo.py

mc-linea-base:     ## Monte-Carlo del seguidor de línea de base
	$(PY) monte-carlo/linea_base.py

mc-pico-carga:     ## Monte-Carlo pico-vs-carga para dobles y triples
	$(PY) monte-carlo/pico_vs_carga.py

mc-figuras:        ## rehace las figuras del MC desde los .npz guardados. DIR=
	$(PY) monte-carlo/graficar.py $(DIR)
	$(PY) monte-carlo/graficar_base.py $(DIR)

# ---------------------------------------------------------------- campañas ---
campana-lista:     ## lista los tests de campaña disponibles
	$(PY) campanas/testbench_mca.py --list

campana-mca: exige-placa       ## (P,R) campaña completa del MCA -> OUT=
	$(PY) campanas/testbench_mca.py all --outdir $(OUT) --channel $(CH) --gen-ch $(GEN_CH)

campana-mca-%: exige-placa     ## (P,R) un test suelto: make campana-mca-sweep_gate
	$(PY) campanas/testbench_mca.py $* --outdir $(OUT) --channel $(CH) --gen-ch $(GEN_CH)

campana-campana: exige-placa   ## (P,R) campaña con bl_k primero (el orden importa)
	$(PY) campanas/run_campana.py $(OUT)

campana-resto: exige-placa     ## (P,R) amplitud, umbral, par-pulso, tasa. OUT=
	$(PY) campanas/run_resto.py $(OUT)
	$(PY) campanas/run_resto2.py $(OUT)

campana-formas: exige-placa    ## (P,R) INL vs familia de forma de pulso (~20 min)
	$(PY) campanas/run_formas.py $(OUT)

campana-e2e: exige-placa       ## (P,R) espectro HW contra espectro SW, mismo estímulo
	$(PY) campanas/e2e_espectro.py --acquire --duration 20

campana-poisson: exige-placa   ## (P,R) pérdidas del lector con arribos Poisson
	$(PY) campanas/run_poisson_loss.py

adquirir: exige-placa          ## (P) adquisición continua a chunks. DURACION= THR=
	$(PY) campanas/run_acquire.py --duration $(DURACION) --thr $(THR)

# --- regraficado de campañas ya medidas: NO necesita placa -------------------
graficos-mca:      ## regrafica una campaña del MCA sin placa. DIR=datos/mca_...
	$(PY) campanas/testbench_mca.py --plot-only --outdir $(DIR)

graficos-formas:   ## catálogo de formas de pulso en volts vs microsegundos
	$(PY) campanas/graficar_formas.py

graficos-tasa:     ## tasas medidas contra los tres modelos de tiempo muerto
	$(PY) campanas/plot_modelos_tasa.py

analisis-estimadores:  ## compara los estimadores sobre pulsos reales guardados
	$(PY) campanas/analizar_estimadores.py

# ------------------------------------------------------------- en la placa ---
exige-placa:
	@test -n "$(EN_PLACA)" || { \
	  echo "ERROR: esto necesita la Red Pitaya (no está /opt/redpitaya/lib/python)."; \
	  echo "       desde la PC:  make sync && make remoto-placa"; \
	  exit 1; }

placa: placa-mem placa-buffer placa-mca placa-ring  ## (P) toda la batería de placa
	@echo "OK: batería de placa completa"

placa-mem: exige-placa     ## (P) regresión del SIGBUS al escribir /dev/mem
	$(PY) API/tests/placa/test_rw_dev_mem.py

placa-buffer: exige-placa  ## (P) capture_window_np contra el buffer completo
	$(PY) API/tests/placa/test_capture_window_np.py

placa-mca: exige-placa     ## (P) smoke test del bus y los registros del MCA
	$(PY) API/tests/placa/test_mca_hw.py

placa-diag: exige-placa    ## (P) diagnóstico incremental, un paso por invocación
	$(PY) API/tests/placa/diag_mca_hw.py

placa-ring: exige-placa    ## (P) plumbing PL->DDR del event_ring + trigger por SW
	$(PY) API/tests/placa/hw_ring_plumbing.py all
	$(PY) API/tests/placa/hw_ring_swtrig.py

placa-rigol: exige-placa   ## (P,R) camino de datos del MCA con señal real
	$(PY) API/tests/placa/test_mca_datapath.py

placa-e2e: exige-placa     ## (P,R) adquisición end-to-end, deja datos en datos/
	$(PY) API/tests/placa/test_mca_e2e.py

bench: exige-placa         ## (P) benchmarks de lectura del buffer (no son pass/fail)
	$(PY) API/bench/bench_buffer_read.py
	$(PY) API/bench/bench_read_vs_length.py
	$(PY) API/bench/bench_reader_budget.py

# ------------------------------------------------------------------- la app --
gui:               ## abre mcamon (GUI). SERVIDOR=host para modo cliente
	$(PY) app/mcamon.py $(if $(SERVIDOR),--host $(SERVIDOR),)

servidor: exige-placa   ## (P) levanta mca_server en la placa
	$(PY) app/mca_server.py

servidor-falso:    ## servidor con MCA falso, para probar cliente y GUI sin placa
	$(PY) app/mca_server.py --fake

# -------------------------------------------------------- PC -> Red Pitaya ---
sync:              ## rsync del árbol a la Pitaya (sin datos/, sin notebooks)
	rsync -az --delete \
	  --exclude 'datos/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
	  --exclude '*.ipynb' --exclude '*.npz' \
	  $(RAIZ)/ $(PITAYA):$(REMOTO)/

remoto-test: sync  ## corre la suite offline EN la Pitaya (sanity del deploy)
	ssh $(PITAYA) 'make -C $(REMOTO) test'

remoto-placa: sync ## corre la batería de placa EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) placa'

remoto-bench: sync ## corre los benchmarks EN la Pitaya
	ssh $(PITAYA) 'make -C $(REMOTO) bench'

# ---------------------------------------------------------------- limpieza ---
clean-pyc:         ## borra __pycache__ y .pyc
	@find $(RAIZ) -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

clean: clean-pyc   ## limpieza normal (NO toca datos/)
	rm -rf $(RAIZ)/.pytest_cache

distclean: clean   ## además borra las salidas de las simulaciones
	rm -rf $(RAIZ)/monte-carlo/_out_* $(RAIZ)/campanas/tests/_out_*
