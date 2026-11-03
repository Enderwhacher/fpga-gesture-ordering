from pathlib import Path
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'gesture4_accel_v2'
work=ROOT.parent/'b3w'
for folder in ('vivado/reports','board_baseline','overlay','hls/reports'): (ROOT/folder).mkdir(parents=True,exist_ok=True)
archive=ROOT/'hls/ip/gesture_blocks56_axis.zip'
report=ROOT/'build/hls_workspace/gesture_blocks56_fp32_pw16/hls/syn/report/gesture_blocks56_axis_csynth.xml'
xml=ET.parse(report).getroot()
resources={node.tag:int(node.text) for node in xml.findall('./AreaEstimates/Resources/*')}
estimated=float(xml.findtext('./PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod'))
assert estimated<=10
assert resources['DSP']<1100 and resources['LUT']<117120 and resources.get('URAM',0)<=64,resources
logs=list((ROOT/'build/hls_workspace/gesture_blocks56_fp32_pw16/hls/csim').rglob('*csim.log'))
assert any('BLOCKS56_CSIM_PASS' in p.read_text(errors='replace') for p in logs)
target=work/'ip_repo'; target.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for name in z.namelist(): assert (target/name).resolve().is_relative_to(target.resolve())
    z.extractall(target)
for name in ('vivado/restore_ps.tcl','board_baseline/ps_2022_1_parameters.tsv'):
    if not (ROOT/name).exists():shutil.copyfile(OLD/name,ROOT/name)
template=ROOT/'vivado/build.tcl'
if not template.exists():template=OLD/'vivado/build.tcl'
text=template.read_text(encoding='utf-8')
text=text.replace('gesture4_accel','gblock').replace('gesture_dw5x5_axis','gesture_blocks56_axis').replace('.. g4w','.. b2w')
text=text.replace('[file join $deliver gblock.bit]','[file join $deliver gesture_blocks56.bit]')
text=text.replace('[file join $deliver gblock.hwh]','[file join $deliver gesture_blocks56.hwh]')
text=text.replace('GESTURE_OVERLAY_BUILD_PASS','BLOCKS56_OVERLAY_BUILD_PASS')
text=text.replace('standalone PYNQ-ZU PS + AXI DMA + FP32 depthwise convolution.','PYNQ-ZU PS + AXI DMA + two complete FP32 residual blocks.')
text=text.replace('# Run via run_vivado.ps1. No board connection or PS reinitialization is performed.','# Run in Vivado batch mode. No board connection or PS reinitialization is performed.')
(ROOT/'vivado/build.tcl').write_text(text,encoding='utf-8')
summary={'csim_passed':True,'csim_block_vectors':6,'parameter_reload_identity_test_passed':True,
         'hls_synthesis_passed':True,'rtl_simulation_passed':False,'board_tested':False,
         'estimated_clock_period_ns':estimated,'resources':resources,
         'ip_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
(ROOT/'hls/reports/summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
