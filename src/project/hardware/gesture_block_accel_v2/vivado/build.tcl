# Vivado 2025.2: PYNQ-ZU PS + AXI DMA + two complete FP32 residual blocks.
# Run in Vivado batch mode. No board connection or PS reinitialization is performed.
set root [file normalize [file join [file dirname [info script]] ..]]
set stage [expr {$argc ? [lindex $argv 0] : "bitstream"}]
if {$stage ni {create bitstream reports}} {error "Stage must be create, bitstream or reports"}
set jobs [expr {$argc > 1 ? [lindex $argv 1] : 4}]
if {![string is integer -strict $jobs] || $jobs < 1 || $jobs > 16} {error "Invalid jobs"}
set build_name [expr {$argc > 2 ? [lindex $argv 2] : "vivado_gesture_v1"}]
if {![regexp {^[A-Za-z0-9_-]+$} $build_name]} {error "Invalid build directory name"}
set work [file normalize [file join $root .. b3w]]
set project_file [file join $work gblock gblock.xpr]
set reports [file join $root vivado reports]
set deliver [file join $root overlay]
file mkdir $work $reports $deliver
cd $work
set_param general.maxThreads $jobs

if {[file exists $project_file]} {
    if {$stage eq "create"} {error "Project already exists; open it or use bitstream stage to resume"}
    open_project $project_file
} else {
    if {$stage eq "reports"} {error "No project to report"}
    if {![file exists [file join $work ip_repo component.xml]]} {error "Run prepare_ip.py first"}
    create_project gblock [file join $work gblock] -part xczu5eg-sfvc784-1-e
    # Reuse matching, verified OOC IP synthesis results when available. Vivado
    # keys entries by tool/part/configuration; top-level wiring is rebuilt.
    set previous_cache [file join $root build vivado gblock gblock.cache ip]
    if {[file isdirectory $previous_cache]} {config_ip_cache -use_cache_location $previous_cache}
    set_property target_language Verilog [current_project]
    set_property ip_repo_paths [list [file join $work ip_repo]] [current_project]
    update_ip_catalog
    create_bd_design gblock
    set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 ps_e_0]
    source [file join $root vivado restore_ps.tcl]
    restore_board_ps $ps $root $reports
    # Keep the board's DDR/MIO/boot configuration and PL clocks. Expose only the
    # AXI ports used here. GP2 slave = HP0_FPD, GP0 master = HPM0_FPD.
    set_property -dict [list \
        CONFIG.PSU__USE__M_AXI_GP0 {1} CONFIG.PSU__USE__M_AXI_GP1 {0} \
        CONFIG.PSU__USE__M_AXI_GP2 {0} \
        CONFIG.PSU__USE__S_AXI_GP0 {0} CONFIG.PSU__USE__S_AXI_GP1 {0} \
        CONFIG.PSU__USE__S_AXI_GP2 {1} CONFIG.PSU__USE__S_AXI_GP3 {0} \
        CONFIG.PSU__USE__S_AXI_GP4 {0} CONFIG.PSU__USE__S_AXI_GP5 {0} \
        CONFIG.PSU__USE__S_AXI_GP6 {0} \
        CONFIG.PSU__SAXIGP2__DATA_WIDTH {128}] $ps
    set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_0]
    set_property -dict [list \
        CONFIG.c_include_sg {0} CONFIG.c_micro_dma {0} \
        CONFIG.c_include_mm2s {1} CONFIG.c_include_s2mm {1} \
        CONFIG.c_addr_width {64} CONFIG.c_sg_length_width {26} \
        CONFIG.c_m_axi_mm2s_data_width {64} CONFIG.c_m_axi_s2mm_data_width {64} \
        CONFIG.c_m_axis_mm2s_tdata_width {32} CONFIG.c_s_axis_s2mm_tdata_width {32} \
        CONFIG.c_include_mm2s_dre {0} CONFIG.c_include_s2mm_dre {0} \
        CONFIG.c_mm2s_burst_size {16} CONFIG.c_s2mm_burst_size {16}] $dma
    set conv [create_bd_cell -type ip -vlnv hand:hls:gesture_blocks56_axis:2.0 gesture_blocks56_axis_0]
    set ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 control_interconnect]
    set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2}] $ctrl
    set mem [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 memory_interconnect]
    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $mem
    set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_pl0]
    set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_one]
    set_property CONFIG.CONST_VAL {1} $one
    set zero [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_zero]
    set_property CONFIG.CONST_VAL {0} $zero
    # Reset polarity is derived from the connected PS pl_resetn0 pin. This is a
    # read-only IP parameter in 2025.2; the HWH compatibility check verifies 0.
    connect_bd_net [get_bd_pins const_one/dout] [get_bd_pins rst_pl0/dcm_locked]
    connect_bd_net [get_bd_pins const_zero/dout] [get_bd_pins rst_pl0/mb_debug_sys_rst]
    # Both reset inputs inherit ACTIVE_LOW polarity. A constant zero on aux
    # would hold the entire AXI path in reset. Drive both from the PS reset.
    connect_bd_net [get_bd_pins ps_e_0/pl_resetn0] [get_bd_pins rst_pl0/ext_reset_in] [get_bd_pins rst_pl0/aux_reset_in]
    connect_bd_net [get_bd_pins ps_e_0/pl_clk0] \
        [get_bd_pins ps_e_0/maxihpm0_fpd_aclk] [get_bd_pins ps_e_0/saxihp0_fpd_aclk] \
        [get_bd_pins axi_dma_0/s_axi_lite_aclk] [get_bd_pins axi_dma_0/m_axi_mm2s_aclk] \
        [get_bd_pins axi_dma_0/m_axi_s2mm_aclk] [get_bd_pins gesture_blocks56_axis_0/ap_clk] \
        [get_bd_pins control_interconnect/aclk] [get_bd_pins memory_interconnect/aclk] \
        [get_bd_pins rst_pl0/slowest_sync_clk]
    connect_bd_net [get_bd_pins rst_pl0/peripheral_aresetn] \
        [get_bd_pins axi_dma_0/axi_resetn] [get_bd_pins gesture_blocks56_axis_0/ap_rst_n] \
        [get_bd_pins control_interconnect/aresetn] [get_bd_pins memory_interconnect/aresetn]
    connect_bd_intf_net [get_bd_intf_pins ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins control_interconnect/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins control_interconnect/M00_AXI] [get_bd_intf_pins axi_dma_0/S_AXI_LITE]
    connect_bd_intf_net [get_bd_intf_pins control_interconnect/M01_AXI] [get_bd_intf_pins gesture_blocks56_axis_0/s_axi_control]
    connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] [get_bd_intf_pins memory_interconnect/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_S2MM] [get_bd_intf_pins memory_interconnect/S01_AXI]
    connect_bd_intf_net [get_bd_intf_pins memory_interconnect/M00_AXI] [get_bd_intf_pins ps_e_0/S_AXI_HP0_FPD]
    connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] [get_bd_intf_pins gesture_blocks56_axis_0/s_axis]
    connect_bd_intf_net [get_bd_intf_pins gesture_blocks56_axis_0/m_axis] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]
    assign_bd_address
    set_property offset 0xA0000000 [get_bd_addr_segs ps_e_0/Data/SEG_axi_dma_0_Reg]
    set_property range 64K [get_bd_addr_segs ps_e_0/Data/SEG_axi_dma_0_Reg]
    set_property offset 0xA0010000 [get_bd_addr_segs ps_e_0/Data/SEG_gesture_blocks56_axis_0_Reg]
    set_property range 64K [get_bd_addr_segs ps_e_0/Data/SEG_gesture_blocks56_axis_0_Reg]
    validate_bd_design
    if {[get_property CONFIG.C_EXT_RESET_HIGH $rst] ne "0" || [get_property CONFIG.C_AUX_RESET_HIGH $rst] ne "0"} {
        error "Reset polarity must match PS pl_resetn0"
    }
    foreach pin {ext_reset_in aux_reset_in} {
        if {[get_bd_nets -of_objects [get_bd_pins rst_pl0/$pin]] ne [get_bd_nets -of_objects [get_bd_pins ps_e_0/pl_resetn0]]} {
            error "Reset $pin must be driven by the PS reset; no asserted constant permitted"
        }
    }
    save_bd_design
    report_property -all -file [file join $reports ps_final_properties.txt] $ps
    write_bd_tcl -force [file join $reports gblock_generated.tcl]
    set bd [get_files */gblock.bd]
    generate_target all $bd
    set wrapper [make_wrapper -files $bd -top]
    add_files -norecurse $wrapper
    set_property top gblock_wrapper [current_fileset]
    update_compile_order -fileset sources_1
}
if {$stage eq "create"} {close_project; exit}
if {$stage eq "bitstream"} {
    if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
        launch_runs synth_1 -jobs $jobs
        wait_on_run synth_1
        if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
    }
    if {![string match "*write_bitstream Complete*" [get_property STATUS [get_runs impl_1]]]} {
        launch_runs impl_1 -to_step write_bitstream -jobs $jobs
        wait_on_run impl_1
        if {![string match "*write_bitstream Complete*" [get_property STATUS [get_runs impl_1]]]} {error "Implementation failed"}
    }
}
open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file [file join $reports timing_summary.rpt]
report_utilization -file [file join $reports utilization.rpt]
report_drc -file [file join $reports drc.rpt]
report_methodology -file [file join $reports methodology.rpt]
set setup_paths [get_timing_paths -delay_type max -max_paths 1]
set hold_paths [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup_paths] == 0 || [llength $hold_paths] == 0} {error "Missing timing paths"}
set wns [get_property SLACK [lindex $setup_paths 0]]
set whs [get_property SLACK [lindex $hold_paths 0]]
if {$wns < 0 || $whs < 0} {error "Timing failed: setup=$wns hold=$whs; do not deploy"}
set bit [file join $work gblock gblock.runs impl_1 gblock_wrapper.bit]
set hwh [file join $work gblock gblock.gen sources_1 bd gblock hw_handoff gblock.hwh]
if {![file exists $bit] || ![file exists $hwh]} {error "Missing bitstream/HWH"}
file copy -force $bit [file join $deliver gesture_blocks56.bit]
file copy -force $hwh [file join $deliver gesture_blocks56.hwh]
set output [open [file join $reports build_result.tsv] w]
puts $output "vivado\t[version -short]"
puts $output "part\t[get_property PART [current_project]]"
puts $output "setup_slack_ns\t$wns"
puts $output "hold_slack_ns\t$whs"
puts $output "synthesis_status\t[get_property STATUS [get_runs synth_1]]"
puts $output "implementation_status\t[get_property STATUS [get_runs impl_1]]"
puts $output "board_tested\tfalse"
close $output
puts "BLOCKS56_OVERLAY_BUILD_PASS setup=$wns hold=$whs"
close_project
exit
