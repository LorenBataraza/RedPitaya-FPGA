MODULE := mca
TOP    := mca_top
DEPS   :=

# Los parametros con los que los tops instancian mca_top (ver el i_mca de
# rtl/mine/tops/mca_red_pitaya_top.sv). Medir con los defaults del RTL daria
# H_AW=14 y 8 RAMB36 de mas, que es justo el numero del que depende cuantas
# instancias entran en la placa.
GENERICS := H_AW=13 H2_AW=7 PSD_AW=6
TBS    := tb_mca_div_restore \
          tb_mca_hist \
          tb_mca_zoom \
          tb_mca_discriminator \
          tb_mca_pulse_feature \
          tb_mca_top

include ../../mk/module.mk
