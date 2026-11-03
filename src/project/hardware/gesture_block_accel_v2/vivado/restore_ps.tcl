# Restore the exact board HWH baseline, omitting read-only derived properties.
proc restore_board_ps {ps root report_dir} {
    set readonly [list]
    foreach line [split [report_property -all -return_string $ps] "\n"] {
        if {[regexp {^(CONFIG\.PSU__\S+)\s+\S+\s+true\s} $line -> name]} {
            lappend readonly $name
        }
    }
    set input [open [file join $root board_baseline ps_2022_1_parameters.tsv] r]
    set settings [list]
    set skipped [list]
    while {[gets $input line] >= 0} {
        if {$line eq ""} {continue}
        lassign [split $line "\t"] name encoded
        if {![regexp {^PSU__[A-Za-z0-9_]+$} $name]} {error "Invalid PS parameter name"}
        if {[lsearch -exact $readonly CONFIG.$name] >= 0} {
            lappend skipped $name
        } else {
            lappend settings CONFIG.$name [encoding convertfrom utf-8 [binary decode base64 $encoded]]
        }
    }
    close $input
    set_property -dict $settings $ps
    set output [open [file join $report_dir ps_restore.tsv] w]
    puts $output "property\told_value_base64\tnew_value_base64"
    foreach {name old} $settings {
        set actual [get_property $name $ps]
        puts $output "$name\t[binary encode base64 -maxlen 0 $old]\t[binary encode base64 -maxlen 0 $actual]"
    }
    close $output
    set output [open [file join $report_dir ps_readonly_skipped.txt] w]
    puts $output [join $skipped "\n"]
    close $output
    puts "PS_RESTORED_WRITABLE=[expr {[llength $settings]/2}] READONLY_SKIPPED=[llength $skipped]"
}
