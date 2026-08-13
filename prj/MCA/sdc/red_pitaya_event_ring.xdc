################################################################################
# Restricciones del build v3 (event_ring_red_pitaya_top).
#
# Se agrega SOLO desde red_pitaya_vivado_Z10_v3_event_ring.tcl. El XDC
# compartido (sdc/red_pitaya.xdc) y el del MCA no se tocan.
################################################################################

################################################################################
# Registros de geometria del event_ring -> multicycle
#
# Mismo argumento que los cfg_* del MCA: son registros que escribe el software
# por el bus de sistema y que, POR CONSTRUCCION, solo latchean con la
# adquisicion parada (event_ring_top.sv los gatea con el estado STOPPED de la
# FSM global; escribirlos corriendo se ignora y levanta err_cfg).
#
# Sus destinos son caminos anchos y combinacionales:
#   - slot_shift  alimenta un barrel shifter de 32 b para derivar
#                 N_SLOTS = RING_SZ >> SLOT_SHIFT, y otro en el writer para
#                 slot_words = 1 << (slot_shift-3)
#   - ring_sz     entra al comparador de creditos (resta de 32 b) y al calculo
#                 de ctrl_stop_addr = slot_base + ring_sz - 8
#   - pre_n/post_n alimentan la resta del puntero de pre-trigger y win_len
#
# Ninguno de esos caminos necesita cerrar en un ciclo: el valor queda estable
# millones de ciclos antes de que llegue el primer trigger de la corrida.
#
# Consecuencia unica: reconfigurar EN MEDIO de una adquisicion podria usar un
# valor mezclado durante ~4 ciclos. No se puede dar, porque el RTL rechaza esas
# escrituras si no esta en STOPPED — a diferencia del MCA, donde la garantia era
# solo de convencion del software.
#
# Sin `if`: el parser de XDC de Vivado no soporta condicionales y una guarda
# anularia la restriccion en silencio. Este archivo solo se agrega desde el
# build del v3, asi que las celdas siempre existen.
################################################################################

set_multicycle_path -setup 4 -from [get_cells i_event_ring/slot_shift_reg*]
set_multicycle_path -hold  3 -from [get_cells i_event_ring/slot_shift_reg*]

set_multicycle_path -setup 4 -from [get_cells i_event_ring/ring_sz_reg*]
set_multicycle_path -hold  3 -from [get_cells i_event_ring/ring_sz_reg*]

set_multicycle_path -setup 4 -from [get_cells i_event_ring/slot_base_reg*]
set_multicycle_path -hold  3 -from [get_cells i_event_ring/slot_base_reg*]

set_multicycle_path -setup 4 -from [get_cells i_event_ring/pre_n_reg*]
set_multicycle_path -hold  3 -from [get_cells i_event_ring/pre_n_reg*]

set_multicycle_path -setup 4 -from [get_cells i_event_ring/post_n_reg*]
set_multicycle_path -hold  3 -from [get_cells i_event_ring/post_n_reg*]
