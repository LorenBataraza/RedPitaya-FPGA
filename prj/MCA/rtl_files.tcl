# RTL propio del MCA, repartido en modulos/<m>/rtl/.
#
# Lo sourcean los red_pitaya_vivado_Z10*.tcl con una linea guardada por
# `file exists`, despues de su `add_files $path_rtl`. El CWD en ese punto es
# prj/MCA (los TCL hacen `cd prj/$prj_name` al principio).
#
# Se agrega SOLO la subcarpeta rtl/ de cada modulo. NUNCA `add_files modulos`:
# add_files recursa, y barreria sim/, uvm/, modelos/, lint/, syn/ y work/ —
# incluida la libreria de QuestaSim y los .wlf/.vcd.
#
# Los tops (rtl/mine/tops/) y red_pitaya_ps.sv siguen entrando por el
# `add_files rtl` del TCL, que no cambia.
#
# Esta lista es la misma que MODS en prj/MCA/Makefile: si agregas un modulo,
# va en los dos lados.

set rtl_modules {comun osc multitrigger mca event_ring}

# Los paquetes primero, como hace el TCL con los de rtl/.
foreach m $rtl_modules {
    add_files -quiet [glob -nocomplain modulos/$m/rtl/*_pkg.sv]
}

foreach m $rtl_modules {
    if {![file isdirectory modulos/$m/rtl]} {
        error "rtl_files.tcl: falta modulos/$m/rtl"
    }
    add_files modulos/$m/rtl
}

puts "rtl_files.tcl: agregados [llength $rtl_modules] modulos de RTL"
