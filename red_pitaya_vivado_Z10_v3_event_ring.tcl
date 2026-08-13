################################################################################
# red_pitaya_vivado_Z10_v3_event_ring.tcl — build v3: MCA + event_ring
#
# COPIA de red_pitaya_vivado_Z10_mca.tcl con las diferencias minimas para
# construir event_ring_red_pitaya_top (Fase 1: ring de slots de evento en DDR)
# sin pisar NADA del build del MCA. El original no se toca.
#
#   1. synth_design -top event_ring_red_pitaya_top
#   2. path_out = out/v3_event_ring  <- directorio propio: si compartiera out/,
#      los reportes (post_route_util.rpt, timing, ...) del MCA quedarian
#      pisados y se perderia la referencia contra la cual comparar.
#   3. artefactos con nombre v3_event_ring.*
#   4. hp2_clk_freq 125 MHz (era 250): HP2 ahora lo maneja el event_ring, que
#      vive entero en adc_clk. Ver la nota de dominios abajo.
#   5. XDC propio del v3, ademas del del MCA (el MCA sigue en el diseno, slot 7)
#
# DOMINIOS DE RELOJ — la razon del punto 4.
# axi2_sys estaba declarado con .clk(dac_axi_clk) (fclk1, 250 MHz) porque HP2
# era del ASG. El event_ring maneja wvalid/waddr/wdata desde adc_clk y lee wrdy
# de vuelta, asi que dejarlo en 250 MHz seria un CDC sin sincronizar: datos
# corruptos sin sintoma. En event_ring_red_pitaya_top.sv axi2_sys pasa a
# adc_clk, igual que axi0/axi1, y aca se configura el PS7 en consecuencia.
#
# Uso:
#   vivado -nojournal -mode batch \
#          -source red_pitaya_vivado_Z10_v3_event_ring.tcl -tclargs MCA
################################################################################

set prj_name [lindex $argv 0]
set prj_defs [lindex $argv 1]
puts "Project name: $prj_name"
puts "Defines: $prj_defs"
cd prj/$prj_name

################################################################################
# install UltraFast Design Methodology from TCL Store
################################################################################

tclapp::install -quiet ultrafast

################################################################################
# define paths
################################################################################

set path_brd ../../brd
set path_rtl rtl
set path_ip      ip
set path_ip_top  ../../ip
set path_bd  .srcs/sources_1/bd/system/hdl
set path_sdc ../../sdc
set path_sdc_prj sdc

# 2) directorio de salida propio
set path_out out/v3_event_ring
set path_sdk sdk

file mkdir $path_out
file mkdir $path_sdk

################################################################################
# list board files
################################################################################

set_param board.repoPaths [list $path_brd]
set_param iconstr.diffPairPulltype {opposite}

################################################################################
# setup an in memory project
################################################################################

set part xc7z010clg400-1

create_project -in_memory -part $part

################################################################################
# create PS BD (processing system block design)
################################################################################

set ::gpio_width 24
set ::hp0_clk_freq 125000000
set ::hp1_clk_freq 125000000
# 4) HP2 baja a 125 MHz: lo maneja el event_ring desde adc_clk
set ::hp2_clk_freq 125000000
set ::hp3_clk_freq 250000000

set_property verilog_define [concat Z10 $prj_defs] [current_fileset]

source                            $path_ip/systemZ10.tcl

generate_target all [get_files    system.bd]
write_hwdef -force       -file    $path_sdk/v3_event_ring.hwdef

################################################################################
# read files
################################################################################

add_files -quiet                  [glob -nocomplain ../../$path_rtl/*_pkg.sv]
add_files -quiet                  [glob -nocomplain       $path_rtl/*_pkg.sv]

if {$prj_name != "pyrpl"} {
add_files                         ../../$path_rtl
add_files -fileset constrs_1      $path_sdc/red_pitaya.xdc
}

add_files                               $path_rtl
add_files                               $path_bd

set ip_files [glob -nocomplain $path_ip/*.xci]
if {$ip_files != ""} {
add_files                         $ip_files
}

if {[file isdirectory $path_ip_top/asg_dat_fifo]} {
add_files $path_ip_top/asg_dat_fifo/asg_dat_fifo.xci
}

if {[file isdirectory $path_ip_top/sync_fifo]} {
add_files $path_ip_top/sync_fifo/sync_fifo.xci
}

add_files -fileset constrs_1      $path_sdc_prj/red_pitaya.xdc

# El MCA sigue instanciado (slot 7), asi que su XDC sigue haciendo falta.
add_files -fileset constrs_1      $path_sdc_prj/red_pitaya_mca.xdc
# 5) restricciones propias del event_ring
add_files -fileset constrs_1      $path_sdc_prj/red_pitaya_event_ring.xdc

################################################################################
# set parameter containing Git hash
################################################################################

set gith [exec git log -1 --format="%H"]
set_property generic "GITH=160'h$gith" [current_fileset]

################################################################################
# synthesis
################################################################################

# 1) top del v3
synth_design -top event_ring_red_pitaya_top -flatten_hierarchy none -bufg 16 -keep_equivalent_registers

write_checkpoint         -force   $path_out/post_synth
report_timing_summary    -file    $path_out/post_synth_timing_summary.rpt
report_utilization       -file    $path_out/post_synth_util.rpt
report_power             -file    $path_out/post_synth_power.rpt

################################################################################
# place
################################################################################

opt_design
power_opt_design
place_design
phys_opt_design
write_checkpoint         -force   $path_out/post_place
report_timing_summary    -file    $path_out/post_place_timing_summary.rpt

################################################################################
# route
################################################################################

route_design
write_checkpoint         -force   $path_out/post_route
report_timing_summary    -file    $path_out/post_route_timing_summary.rpt
report_timing            -file    $path_out/post_route_timing.rpt -sort_by group -max_paths 100 -path_type summary
report_clock_utilization -file    $path_out/clock_util.rpt
report_utilization       -file    $path_out/post_route_util.rpt
report_power             -file    $path_out/post_route_power.rpt
report_drc               -file    $path_out/post_imp_drc.rpt
report_io                -file    $path_out/post_imp_io.rpt

xilinx::ultrafast::report_io_reg -verbose -file $path_out/post_route_iob.rpt

################################################################################
# bitstream
################################################################################

set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]

write_bitstream -force            $path_out/v3_event_ring.bit
write_bitstream -force -bin_file  $path_out/v3_event_ring

# .bit.bin para fpgautil. bootgen resuelve el nombre del bitstream contra SU
# directorio de trabajo, no contra la ubicacion del .bif, asi que hay que
# ejecutarlo DESDE el directorio de salida. Y su error NO aborta el script: sin
# el chequeo de mtime quedaria el .bit nuevo con el .bit.bin VIEJO, o sea la
# placa cargando el bitstream anterior sin que nada lo avise.
set here [pwd]
cd $path_out
set bif [open v3_event_ring.bif w]
puts -nonewline $bif "all:{ v3_event_ring.bit }"
close $bif
exec bootgen -image v3_event_ring.bif -arch zynq -process_bitstream bin \
             -o v3_event_ring.bit.bin -w
if {[file mtime v3_event_ring.bit.bin] < [file mtime v3_event_ring.bit]} {
  cd $here
  error "bootgen no regenero el .bit.bin: la placa cargaria el bitstream VIEJO"
}
puts "bootgen OK: v3_event_ring.bit.bin ([file size v3_event_ring.bit.bin] bytes)"
cd $here

################################################################################
# system definition
################################################################################

write_sysdef -force      -hwdef   $path_sdk/v3_event_ring.hwdef \
                         -bitfile $path_out/v3_event_ring.bit \
                         -file    $path_sdk/v3_event_ring.sysdef

exit
