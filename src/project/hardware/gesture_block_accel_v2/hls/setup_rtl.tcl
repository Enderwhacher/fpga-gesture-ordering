set root [file normalize [file join [file dirname [info script]] ..]]
cd [file join $root build hls_workspace]
open_component gesture_blocks56_fp32_pw16 -flow_target vivado
set_top gesture_blocks56_axis
add_files [file join $root hls src blocks56_axis.cpp] -cflags "-std=c++17"
add_files -tb [file join $root hls tb test_blocks.cpp] -cflags "-std=c++17 -I[file join $root hls src]"
cosim_design -setup -rtl verilog -trace_level none -argv [format {"%s"} $root]
puts "BLOCKS56_RTL_SETUP_PASS"
close_project
exit
