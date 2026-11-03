set root [file normalize [file join [file dirname [info script]] ..]]
file mkdir [file join $root build hls_workspace] [file join $root hls ip]
cd [file join $root build hls_workspace]
open_component gesture_blocks56_fp32_pw16 -flow_target vivado
set_top gesture_blocks56_axis
add_files [file join $root hls src blocks56_axis.cpp] -cflags "-std=c++17"
add_files -tb [file join $root hls tb test_blocks.cpp] -cflags "-std=c++17 -I[file join $root hls src]"
set_part xczu5eg-sfvc784-1-e
create_clock -period 10.0 -name default
config_compile -pipeline_loops 0
csim_design -clean -argv [format {"%s"} $root]
csynth_design
export_design -format ip_catalog -rtl verilog -vendor hand -library hls -version 2.0 -ipname gesture_blocks56_axis -output [file join $root hls ip gesture_blocks56_axis.zip]
puts "BLOCKS56_HLS_EXPORT_PASS"
close_project
exit
