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
RTL_SRCS := \
  ../rtl/mine/multitrigger_trig_src.sv \
  ../rtl/mine/trigger_shield.sv \
  ../rtl/mine/multitrigger_event_logic.v \
  ../../../rtl_250/classic/rp_bram_sm.v

TBS := tb_multitrigger_trig_src \
       tb_trigger_shield \
       tb_multitrigger_event_logic \
       tb_trig_capture

TB_SRCS := $(addsuffix .sv,$(TBS))

.PHONY: all compile clean wave $(TBS)

all: $(TBS)

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
