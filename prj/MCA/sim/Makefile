# Testbenches del multitrigger scope — QuestaSim (vsim)
#
#   make            corre todos los testbenches (modo batch)
#   make <tb>       corre un TB (ej: make tb_trig_capture)
#   make wave TB=tb_trig_capture   abre la GUI con ondas
#   make clean
#
# Requiere vlib/vlog/vsim en el PATH (QuestaSim). Overridable:
#   make VSIM=/home/lorenzo/questasim/questasim/linux_x86_64/vsim ...

VLIB ?= vlib
VLOG ?= vlog
VSIM ?= vsim
WORK ?= work

# Fuentes RTL (ver filelist.f) + testbenches
# Fuentes RTL: se leen de filelist.f para que no se desincronicen.
RTL_SRCS := $(shell grep -v '^\#' filelist.f | grep -v '^$$')

TBS := tb_integration_cfg \
       tb_slots_integration \
       tb_osc_cfg \
       tb_multitrigger_cfg \
       tb_multitrigger_trig_src \
       tb_trigger_shield \
       tb_multitrigger_event_logic \
       tb_trig_capture \
       tb_mca_div_restore \
       tb_mca_hist \
       tb_mca_pulse_feature \
       tb_mca_top \
       tb_osc_filter \
       tb_event_window_capture \
       tb_event_stage_fifo \
       tb_event_slot_writer \
       tb_event_ring_top

TB_SRCS := $(addsuffix .sv,$(TBS))

.PHONY: all compile clean wave help $(TBS)

all: $(TBS)

help:              ## lista los testbenches disponibles
	@echo "testbenches de RTL (QuestaSim):"
	@printf '  %s\n' $(TBS)
	@echo ""
	@echo "  make            todos            make <tb>       uno solo"
	@echo "  make wave TB=<tb>   GUI con ondas    make clean"

# Compila RTL + todos los TB en la libreria work
compile: $(WORK)/.compiled

$(WORK)/.compiled: $(RTL_SRCS) $(TB_SRCS)
	@test -d $(WORK) || $(VLIB) $(WORK)
	$(VLOG) -sv -quiet $(RTL_SRCS) $(TB_SRCS)
	@touch $(WORK)/.compiled

# Corre un TB en batch. La regla imprime "RESULT: PASS/FAIL" desde el propio TB.
$(TBS): compile
	@echo "===================== $@ ====================="
	@$(VSIM) -c -quiet $@ -do "run -all; quit -f"

# GUI con ondas: make wave TB=tb_trig_capture
wave: compile
	$(VSIM) -gui $(TB) -do "add wave -r /*; run -all"

clean:
	rm -rf $(WORK) transcript vsim.wlf *.vcd *.wlf modelsim.ini
