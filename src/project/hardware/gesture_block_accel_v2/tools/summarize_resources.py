from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
paths=[ROOT/'vivado/reports/utilization.rpt',ROOT.parent/'b2w/gblock/gblock.runs/gblock_gesture_blocks56_axis_0_0_synth_1/gblock_gesture_blocks56_axis_0_0_utilization_synth.rpt']
for path in paths:
    if path.exists():
        print(path)
        for line in path.read_text(errors='replace').splitlines():
            if any(key in line for key in ('CLB LUTs','CLB Registers','Block RAM Tile','URAM','DSPs')):print(line)
