# Fuentes RTL bajo test (rutas relativas a prj/MCA/sim/).
#
# OJO con rp_bram_sm.v: antes se compilaba la copia de ../../../rtl_250/classic/,
# pero Vivado sintetiza la de ../../../rtl/classic/ (el TCL hace `add_files ../../rtl`,
# nunca rtl_250). Hoy son funcionalmente identicas —el diff son comentarios— pero
# divergen apenas alguien toque una. Se compila la que se sintetiza.

# --- integracion (region de TOP, slot 6) ---
../rtl/mine/integration/integration_cfg.sv
../rtl/mine/integration/dsp_tap_mux.sv

# --- multitrigger ---
../rtl/mine/multitrigger/multitrigger_trig_src.sv
../rtl/mine/multitrigger/trigger_shield.sv
../rtl/mine/multitrigger/multitrigger_event_logic.v
../rtl/mine/multitrigger/multitrigger_cfg.sv
../rtl/mine/multitrigger/multitrigger_rp_scope_cfg.sv

# --- OSC (slot 1) ---
../rtl/mine/osc/osc_cfg.sv

# --- datapath del scope (integracion de las tres regiones) ---
../rtl/mine/multitrigger/rp_scope_multitrigger_com.sv
../../../rtl/divide.v
../../../rtl/classic/rp_scope_calib.v
../../../rtl/classic/rp_decim.v
../../../rtl/classic/rp_delay.v
../../../rtl/classic/rp_adc_trig.v
../../../rtl/classic/rp_acq_bram.v
../../../rtl/classic/rp_axi_sm.v
../../../rtl/classic/rp_ext_trig.v
../../../rtl/classic/rp_bram_sm.v

# --- MCA ---
../rtl/mine/mca/mca_div_restore.sv
../rtl/mine/mca/mca_hist.sv
../rtl/mine/mca/mca_zoom.sv
../rtl/mine/mca/mca_discriminator.sv
../rtl/mine/mca/mca_pulse_feature.sv
../rtl/mine/mca/mca_top.sv

# --- event_ring (Fase 1: ring de slots de evento en DDR) ---
../rtl/mine/event_ring/event_window_capture.sv
../rtl/mine/event_ring/event_stage_fifo.sv
../rtl/mine/event_ring/event_slot_writer.sv
../rtl/mine/event_ring/event_ring_top.sv
../../../rtl/classic/axi_wr_fifo.v

# Ecualizador + su copia congelada, para el TB de equivalencia
../rtl/osc_filter.v
osc_filter_ref.v
