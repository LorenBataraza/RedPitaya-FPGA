# Sintesis out-of-context de un modulo, en Vivado modo no-proyecto.
#
# Lo lanza `make syn` (o `make sweep`) desde modulos/<m>/work, con el CWD en
# modulos/<m>/syn y estas variables de entorno:
#
#   MODULE     nombre del modulo
#   SYN_TOP    modulo de RTL a sintetizar
#   MOD_DIR    ruta absoluta a modulos/<m>
#   SYN_SRCS   lista de fuentes, ya resuelta y ordenada por module.mk
#   PERIOD_NS  periodo de reloj objetivo (el barrido lo pisa por frecuencia)
#
# Es un script generico: lo comparten los cinco modulos. Lo unico propio de
# cada uno es syn/inputs/<top>_ooc.xdc.

set MODULE  $::env(MODULE)
set TOP     $::env(SYN_TOP)
set MOD_DIR $::env(MOD_DIR)
set SRCS    $::env(SYN_SRCS)
set PART    xc7z010clg400-1

set OUT ${MOD_DIR}/syn/outputs
file mkdir $OUT

puts "=== sintesis OOC: $MODULE / $TOP @ $::env(PERIOD_NS) ns ==="

create_project -in_memory -part $PART

foreach f $SRCS {
    if {[string match "*.sv" $f]} {
        read_verilog -sv $f
    } else {
        read_verilog $f
    }
}

set xdc ${MOD_DIR}/syn/inputs/${TOP}_ooc.xdc
if {![file exists $xdc]} {
    error "falta $xdc: la sintesis OOC necesita las restricciones del modulo"
}
read_xdc $xdc

# -mode out_of_context: no inserta buffers de IO, asi los puertos del modulo no
# se confunden con pines del chip. Es lo que hace comparable el costo entre
# modulos y entre frecuencias.
synth_design -top $TOP -mode out_of_context -part $PART -flatten_hierarchy none
opt_design

report_utilization    -file ${OUT}/utilization.rpt
report_timing_summary -file ${OUT}/timing.rpt
report_power          -file ${OUT}/power.rpt
write_checkpoint -force ${OUT}/${TOP}_synth.dcp

################################################################################
# Metricas
#
# El script emite un metrics.txt en CLAVE=VALOR leyendo las properties, en vez
# de que un parser de Python regexee los .rpt: el formato de los reportes cambia
# entre versiones de Vivado, las properties no.
################################################################################

# Conteo por PRIMITIVE_GROUP. Los nombres son los que usa Vivado de verdad
# (verificados sobre el netlist de mca_top): BMEM para los RAMB, no "BLOCKRAM".
# Un nombre mal escrito devuelve 0 en silencio, asi que metrics.txt incluye
# ademas el histograma completo de grupos (clave `groups`) para poder notarlo.
proc n_prims {grp} {
    return [llength [get_cells -quiet -hier -filter "PRIMITIVE_GROUP == $grp"]]
}

proc n_ref {pat} {
    return [llength [get_cells -quiet -hier -filter "REF_NAME =~ $pat"]]
}

proc group_histogram {} {
    set h [dict create]
    foreach c [get_cells -quiet -hier -filter {IS_PRIMITIVE}] {
        dict incr h [get_property PRIMITIVE_GROUP $c]
    }
    set out {}
    foreach {k v} $h { lappend out "$k:$v" }
    return [join [lsort $out] ","]
}

set paths [get_timing_paths -quiet -delay_type max -max_paths 1 -nworst 1]
if {[llength $paths] > 0} {
    set wns   [get_property SLACK $paths]
    set src   [get_property STARTPOINT_PIN $paths]
    set dst   [get_property ENDPOINT_PIN   $paths]
    set logic [get_property LOGIC_LEVELS   $paths]
} else {
    set wns ""; set src ""; set dst ""; set logic ""
}

set period $::env(PERIOD_NS)
# Camino critico = periodo - slack. Fmax = 1000 / camino critico.
if {$wns ne ""} {
    set crit [expr {$period - $wns}]
    set fmax [expr {$crit > 0 ? 1000.0 / $crit : 0.0}]
} else {
    set crit ""; set fmax ""
}

set fh [open ${OUT}/metrics.txt w]
puts $fh "module=$MODULE"
puts $fh "top=$TOP"
puts $fh "part=$PART"
puts $fh "period_ns=$period"
puts $fh "freq_mhz=[expr {1000.0 / $period}]"
puts $fh "wns_ns=$wns"
puts $fh "crit_path_ns=$crit"
puts $fh "fmax_mhz=$fmax"
puts $fh "logic_levels=$logic"
# OJO: `lut` cuenta PRIMITIVAS LUT, no los "Slice LUTs" del report_utilization.
# Son distintos: dos LUT5 que comparten O5/O6 ocupan un solo sitio de slice, asi
# que el reporte da menos (para mca_top: 2628 primitivas -> 2115 sitios). Para
# comparar entre frecuencias y entre modulos conviene la primitiva, que no
# depende de decisiones de empaquetado.
puts $fh "lut=[n_prims LUT]"
puts $fh "ff=[n_prims FLOP_LATCH]"
puts $fh "dsp=[n_ref DSP48*]"
puts $fh "bram=[n_prims BMEM]"
puts $fh "carry=[n_prims CARRY]"
puts $fh "muxf=[n_prims MUXFX]"
puts $fh "startpoint=$src"
puts $fh "endpoint=$dst"
puts $fh "groups=[group_histogram]"
close $fh

puts "=== metrics.txt ==="
puts [read [open ${OUT}/metrics.txt r]]
puts "=== sintesis OOC terminada: $MODULE ==="
