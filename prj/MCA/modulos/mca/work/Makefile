MODULE := mca
TOP    := mca_top
# mca_trap vive en comun: lo comparte con el multitrigger.
DEPS   := comun

# Los parametros con los que los tops instancian mca_top (ver el i_mca de
# rtl/mine/tops/mca_red_pitaya_top.sv). Medir con los defaults del RTL daria
# H_AW=14 y 8 RAMB36 de mas, que es justo el numero del que depende cuantas
# instancias entran en la placa.
# N_ACC y N_FORMAS: 3 y 3 desde el recorte del 2026-11-09 (el default del modulo es 4 y 4).
GENERICS := H_AW=13 H2_AW=7 PSD_AW=6 N_ACC=3 N_FORMAS=3
TBS    := tb_mca_div_restore \
          tb_mca_hist \
          tb_mca_zoom \
          tb_mca_discriminator \
          tb_mca_trap \
          tb_mca_multi \
          tb_mca_pulse_feature_evt \
          tb_mca_top

# Los vectores del trapecio salen del modelo de Python: sim/vectores/gen_trap.py
PLUS_tb_mca_trap = +VEC=$(MOD_DIR)/sim/vectores/trap_ref.txt

include ../../mk/module.mk
