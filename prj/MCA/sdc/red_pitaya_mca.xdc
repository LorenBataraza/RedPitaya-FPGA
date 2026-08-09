################################################################################
# Restricciones especificas del build del MCA (mca_red_pitaya_top).
#
# Se agrega SOLO desde red_pitaya_vivado_Z10_mca.tcl: el XDC compartido
# (sdc/red_pitaya.xdc) no se toca, asi que el build del scope no se entera.
################################################################################

################################################################################
# Registros de configuracion del MCA -> multicycle
#
# Los escribe el software por el bus de sistema y cambian, a lo sumo, una vez
# por adquisicion. El caso que motiva esto es cfg_q_shift: alimenta un barrel
# shifter de 32 bits (q_tot >> cfg_q_shift) seguido de los comparadores de la
# ventana de amplitud y de la logica de control del segmentador. Son 8 niveles
# de logica y no entra en 8 ns: aportaba 91 de los 106 endpoints en falla, con
# el peor en -0.313 ns.
#
# Pero ese camino NO necesita cerrar en un ciclo. El valor queda estable
# millones de ciclos antes de que llegue un pulso; darle 4 periodos es
# holgadamente correcto.
#
# La unica consecuencia: si se reconfigura EN MEDIO de una adquisicion, los
# eventos de los ~4 ciclos siguientes a la escritura pueden usar un valor
# mezclado. En la practica se configura con run=0 y despues se arranca, asi que
# no se da. mca_utils.MCA.configure() sigue ese orden.
#
# Nota: esto es distinto del caso de osc_filter, donde el registro de
# coeficiente aparecia como origen pero el camino real era el lazo RECURSIVO
# del IIR (que si necesita cerrar en un ciclo y por eso no se pudo relajar).
################################################################################

# Sin `if`: el parser de XDC de Vivado NO soporta condicionales
# ("CRITICAL WARNING: [Designutils 20-1307] Command 'if' is not supported in
# the xdc constraint file"), y una guarda condicional anula la restriccion en
# silencio. Este archivo solo se agrega desde el build del MCA, asi que las
# celdas siempre existen.
set_multicycle_path -setup 4 -from [get_cells i_mca/cfg_*_reg*]
set_multicycle_path -hold  3 -from [get_cells i_mca/cfg_*_reg*]
