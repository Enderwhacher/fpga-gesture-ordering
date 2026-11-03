# Archive the exact existing PW16 project. No synthesis or implementation rerun.
open_project D:/hand/b3w/gblock/gblock.xpr
if {[get_property PART [current_project]] ne "xczu5eg-sfvc784-1-e"} {
    error "Unexpected target part; refusing to archive as the validated project"
}
archive_project -force D:/hand/output/vivado_blocks56_pw16_v2_archive.zip
close_project
exit
