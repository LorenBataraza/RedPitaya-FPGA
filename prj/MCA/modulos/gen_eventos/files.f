# RTL propio de gen_eventos, en orden de dependencia (hojas primero).
# Rutas relativas a la raiz del modulo.
#
# Este archivo vive en la raiz del modulo y NO dentro de rtl/, a proposito: el
# `add_files modulos/<m>/rtl` del TCL de Vivado levantaria un .f suelto como
# archivo de tipo desconocido.
rtl/gen_disparos.sv
rtl/gen_eventos.sv
rtl/gen_pulsos.sv
