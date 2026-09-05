# Lint con SpyGlass. NO corre en esta maquina (no esta instalado): queda para
# la del laboratorio. El lint que corre local es `make -C modulos/mca/work lint`,
# que usa vlog -lint de Questa.
#
# Las fuentes salen del mismo files.f/extra.f que usa la simulacion, asi que no
# se pueden desincronizar.

set MOD_DIR [file normalize [file dirname [info script]]/..]
new_project mca -projectwdir ${MOD_DIR}/lint/work -force

set fh [open ${MOD_DIR}/files.f r]
foreach line [split [read $fh] "\n"] {
    set line [string trim $line]
    if {$line eq "" || [string index $line 0] eq "#"} { continue }
    read_file -type verilog ${MOD_DIR}/$line
}
close $fh

set_option enableSV09 yes
set_option top mca_top
read_file -type sgdc ${MOD_DIR}/lint/mca.sgdc
if {[file exists ${MOD_DIR}/lint/mca.swl]} {
    read_file -type waiver ${MOD_DIR}/lint/mca.swl
}

current_goal lint/lint_rtl
run_goal
current_goal cdc/cdc_verify_struct
run_goal
exit -force
