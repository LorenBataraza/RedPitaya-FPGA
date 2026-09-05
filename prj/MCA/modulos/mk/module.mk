# Reglas compartidas por todos los modulos de prj/MCA/modulos/.
#
# Cada modulo tiene un work/Makefile que declara cinco variables y hace
# `include ../../mk/module.mk`:
#
#   MODULE  nombre del modulo (= nombre de la carpeta en modulos/)
#   TOP     modulo de RTL que se sintetiza out-of-context
#   DEPS    otros modulos de modulos/ cuyo RTL hace falta para compilar
#   TBS     testbenches de sim/ que corren en batch (sin la extension .sv)
#
# El RTL de cada modulo se declara en dos archivos, no en el Makefile:
#
#   <modulo>/files.f   RTL propio, rutas relativas al modulo (rtl/mca_top.sv)
#   <modulo>/extra.f   RTL del repo raiz que necesita, rutas relativas a la
#                      raiz del repo (rtl/classic/axi_wr_fifo.v). Opcional.
#
# Los dos se leen tambien para cada DEPS, asi una dependencia arrastra sus
# propias dependencias del repo raiz sin que el modulo de arriba las repita.
#
# Opcional, por testbench:
#   PLUS_<tb>  plusargs extra para ese TB (ej: PLUS_tb_event_ring_top = +x=y).
#              Usar `=` y no `:=` si el valor referencia $(MCA_ROOT) u otra
#              ruta que module.mk define despues.
#
# Objetivos:
#   make            compila y corre todos los TB del modulo
#   make <tb>       corre uno solo
#   make wave TB=x  abre las ondas ya grabadas de un TB (vsim -view)
#   make vcd TB=x   reejecuta volcando VCD (para exportar fuera de Questa)
#   make cov        reejecuta con cobertura y arma el reporte HTML
#   make lint       lint de RTL (vlog -lint)
#   make syn        sintesis out-of-context en Vivado
#   make sweep      barrido de frecuencia -> rpt/<f>MHz/
#   make extract    junta los metrics.txt del barrido -> rpt/sweep_results.csv
#   make plot       grafica el barrido -> rpt/plots/*.png
#   make clean

ifndef MODULE
$(error MODULE no esta definido: incluir module.mk desde el work/Makefile de un modulo)
endif

# --- rutas -------------------------------------------------------------------
# Caso normal: CURDIR es modulos/<MODULE>/work, el modulo esta un nivel arriba
# y sus testbenches en <modulo>/sim/. prj/MCA/sim (los TB de integracion) pisa
# MOD_DIR, MODULOS y SIM_DIR porque no tiene esa forma.
MOD_DIR   ?= $(abspath $(CURDIR)/..)
MODULOS   ?= $(abspath $(CURDIR)/../..)
SIM_DIR   ?= $(MOD_DIR)/sim
MCA_ROOT  := $(abspath $(MODULOS)/..)
REPO_ROOT := $(abspath $(MCA_ROOT)/../..)

# --- herramientas ------------------------------------------------------------
VLIB   ?= vlib
VLOG   ?= vlog
VSIM   ?= vsim
VCOVER ?= vcover
VIVADO ?= vivado

# --- fuentes -----------------------------------------------------------------
# files.f vive en la RAIZ del modulo, no dentro de rtl/: asi el `add_files
# modulos/<m>/rtl` del TCL de Vivado no lo levanta como archivo de tipo
# desconocido. Sus rutas son relativas al modulo (ej: rtl/mca_top.sv).
# Lee un .f (comentarios con # y lineas en blanco) y prefija cada ruta.
#   $(1) directorio base al que son relativas las rutas
#   $(2) el .f a leer
read_f    = $(addprefix $(1)/,$(shell test -f $(2) && grep -v '^\#' $(2) | grep -v '^$$'))
own_f     = $(call read_f,$(1),$(1)/files.f)
extra_f   = $(call read_f,$(REPO_ROOT),$(1)/extra.f)
mod_all   = $(call extra_f,$(MODULOS)/$(1)) $(call own_f,$(MODULOS)/$(1))

# Deduplica preservando el orden. $(sort) no sirve: ordena alfabeticamente y
# eso rompe el orden de dependencias que llevan los .f.
uniq = $(if $(1),$(firstword $(1)) \
         $(call uniq,$(filter-out $(firstword $(1)),$(wordlist 2,$(words $(1)),$(1)))))

DEP_SRCS   := $(foreach d,$(DEPS),$(call mod_all,$(d)))
OWN_SRCS   := $(call extra_f,$(MOD_DIR)) $(call own_f,$(MOD_DIR))
RTL_SRCS   := $(strip $(call uniq,$(DEP_SRCS) $(OWN_SRCS)))

# Los propios .f son prerequisitos: editar un filelist tiene que recompilar,
# igual que editar un .sv.
FLISTS := $(wildcard $(MOD_DIR)/files.f $(MOD_DIR)/extra.f \
            $(foreach d,$(DEPS),$(MODULOS)/$(d)/files.f $(MODULOS)/$(d)/extra.f))

TB_SRCS  := $(addprefix $(SIM_DIR)/,$(addsuffix .sv,$(TBS)))
# Auxiliares de simulacion: modelos de referencia congelados (.v en sim/) y
# las assertions por bind. Nunca entran a files.f, asi Vivado ni las ve.
SIM_SRCS := $(wildcard $(SIM_DIR)/*.v) $(wildcard $(SIM_DIR)/sva/*.sv)

# --- directorios de salida ---------------------------------------------------
WAVES  := $(CURDIR)/waves
LOGS   := $(CURDIR)/logs
COVDIR := $(CURDIR)/cov
RPT    := $(CURDIR)/rpt

# +acc mantiene la visibilidad de las senales: sin esto vopt las optimiza y el
# `log -r /*` de abajo no encuentra nada, con lo cual los .wlf salen vacios.
VSIM_FLAGS += -voptargs=+acc

# Cobertura: libreria y flags aparte, para no invalidar la compilacion normal.
ifdef COV
  WORK       := $(CURDIR)/questa_cov
  VLOG_FLAGS += +cover=bcesxf
  VSIM_FLAGS += -coverage
  COV_SAVE    = coverage save $(COVDIR)/$@.ucdb;
else
  WORK := $(CURDIR)/questa
endif
STAMP := $(WORK)/.compiled

.PHONY: all help compile lint syn sweep extract plot cov wave vcd clean $(TBS)

.DEFAULT_GOAL := all

help:              ## esta ayuda
	@echo "modulo $(MODULE)  (top: $(TOP))"
	@echo ""
	@grep -hE '^[a-zA-Z0-9_%-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sort | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'
	@echo ""
	@echo "  testbenches:"
	@printf '    %s\n' $(TBS)

# --- compilacion -------------------------------------------------------------
compile: $(STAMP)   ## compila RTL + TB en la libreria del modulo

$(STAMP): $(RTL_SRCS) $(TB_SRCS) $(SIM_SRCS) $(FLISTS)
	@test -d $(WORK) || $(VLIB) $(WORK)
	$(VLOG) -sv -quiet -work $(WORK) $(VLOG_FLAGS) $(RTL_SRCS) $(SIM_SRCS) $(TB_SRCS)
	@touch $@

# --- simulacion --------------------------------------------------------------
# Las ondas se graban SIEMPRE en batch (WLF es barato): cuando un TB falla, el
# tiempo que hay que mirar ya paso, asi que no sirve volcar recien ahi.
# Se abren despues con `make wave TB=<tb>`.
#
# A diferencia del sim/Makefile viejo, aca se CHEQUEA el "RESULT: PASS" que
# imprime el TB: antes make salia con 0 aunque un testbench fallara.
$(TBS): compile
	@mkdir -p $(WAVES) $(LOGS) $(COVDIR)
	@echo "===================== $@ ====================="
	@$(VSIM) -c -quiet -work $(WORK) -wlf $(WAVES)/$@.wlf $(VSIM_FLAGS) $@ $(PLUS_$@) \
	    -do "log -r /*; run -all; $(COV_SAVE) quit -f" 2>&1 | tee $(LOGS)/$@.log
	@if grep -q 'RESULT: PASS' $(LOGS)/$@.log; then \
	    echo "  -> $@ PASS"; \
	 else \
	    echo "  -> $@ FAIL  (log: $(LOGS)/$@.log)"; exit 1; \
	 fi

# Corre todos aunque alguno falle, y recien al final devuelve el estado.
all:               ## compila y corre todos los TB del modulo
	@fail=""; for tb in $(TBS); do \
	    $(MAKE) --no-print-directory $$tb || fail="$$fail $$tb"; \
	 done; \
	 echo ""; \
	 if [ -n "$$fail" ]; then echo "[$(MODULE)] FALLARON:$$fail"; exit 1; \
	 else echo "[$(MODULE)] $(words $(TBS)) testbenches OK"; fi

wave:              ## abre las ondas grabadas: make wave TB=tb_mca_top
	@test -n "$(TB)" || { echo "uso: make wave TB=<tb>"; exit 1; }
	$(VSIM) -view $(WAVES)/$(TB).wlf -do "add wave -r /*" &

vcd:               ## reejecuta volcando VCD (exportable fuera de Questa)
	@test -n "$(TB)" || { echo "uso: make vcd TB=<tb>"; exit 1; }
	@$(MAKE) --no-print-directory compile
	@mkdir -p $(WAVES)
	$(VSIM) -c -quiet -work $(WORK) $(TB) \
	    -do "vcd file $(WAVES)/$(TB).vcd; vcd add -r /*; run -all; quit -f"

cov:               ## reejecuta con cobertura y arma el reporte HTML
	@$(MAKE) --no-print-directory COV=1 all
	$(VCOVER) merge -out $(COVDIR)/merged.ucdb $(COVDIR)/*.ucdb
	$(VCOVER) report -html -htmldir $(COVDIR)/html $(COVDIR)/merged.ucdb
	@echo "-> $(COVDIR)/html/index.html"

# --- lint --------------------------------------------------------------------
# SpyGlass no esta instalado en esta maquina; lint/run_spyglass.tcl queda para
# la del laboratorio. Esto es lo que corre aca.
lint:              ## lint de RTL con vlog -lint
	@mkdir -p $(LOGS)
	@test -d $(WORK)_lint || $(VLIB) $(WORK)_lint
	$(VLOG) -sv -quiet -lint -work $(WORK)_lint $(RTL_SRCS) 2>&1 | tee $(LOGS)/lint.log

# --- sintesis out-of-context (Vivado) ----------------------------------------
FREQS_MHZ ?= 100 125 150 175 200 225 250
PERIOD_NS ?= 8.0

# El syn_ooc.tcl es unico y compartido: lo propio de cada modulo es su
# syn/inputs/<top>_ooc.xdc.
syn:               ## sintesis out-of-context en Vivado
	@test -n "$(TOP)" || { echo "este modulo no declara TOP: nada que sintetizar"; exit 1; }
	@mkdir -p $(MOD_DIR)/syn/outputs $(MOD_DIR)/syn/logs
	cd $(MOD_DIR)/syn && \
	  MODULE=$(MODULE) SYN_TOP=$(TOP) MOD_DIR=$(MOD_DIR) \
	  SYN_SRCS="$(RTL_SRCS)" PERIOD_NS=$(PERIOD_NS) \
	  $(VIVADO) -nojournal -mode batch -source $(MODULOS)/mk/syn_ooc.tcl \
	    -log $(MOD_DIR)/syn/logs/syn.log -tempDir $(MOD_DIR)/syn/logs

sweep:             ## barrido de frecuencia -> rpt/<f>MHz/
	@for f in $(FREQS_MHZ); do \
	  p=$$(awk -v f=$$f 'BEGIN{printf "%.4f", 1000.0/f}'); \
	  echo "============ $(MODULE) @ $${f} MHz (periodo $${p} ns) ============"; \
	  $(MAKE) --no-print-directory syn PERIOD_NS=$$p || exit 1; \
	  d=$(RPT)/$${f}MHz; mkdir -p $$d; \
	  cp $(MOD_DIR)/syn/outputs/*.rpt $(MOD_DIR)/syn/outputs/metrics.txt $$d/ 2>/dev/null || true; \
	done

extract:           ## junta los metrics.txt del barrido -> rpt/sweep_results.csv
	python3 $(MODULOS)/mk/extract_metrics.py --rpt-dir $(RPT)

plot:              ## grafica el barrido -> rpt/plots/*.png
	python3 $(MODULOS)/mk/plot_sweep.py --rpt-dir $(RPT)

sweep-all: sweep extract plot   ## barrido + extraccion + graficos

clean:             ## borra librerias, ondas, logs, cobertura y reportes
	rm -rf $(CURDIR)/questa $(CURDIR)/questa_cov $(CURDIR)/questa_lint \
	       $(WAVES) $(LOGS) $(COVDIR) $(RPT) \
	       $(CURDIR)/transcript $(CURDIR)/vsim.wlf $(CURDIR)/modelsim.ini \
	       $(MOD_DIR)/syn/outputs $(MOD_DIR)/syn/logs
