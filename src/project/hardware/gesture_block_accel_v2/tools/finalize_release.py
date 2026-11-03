"""Publish only after actual RTL, routed timing and host checks pass."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    result=dict(s.split('\t',1) for s in (ROOT/'vivado/reports/build_result.tsv').read_text().splitlines())
    assert float(result['setup_slack_ns'])>=0 and float(result['hold_slack_ns'])>=0
    assert 'Complete' in result['synthesis_status'] and 'write_bitstream Complete' in result['implementation_status']
    summary=read('hls/reports/summary.json')
    assert all(summary[k] for k in ('csim_passed','hls_synthesis_passed','rtl_simulation_passed','parameter_reload_identity_test_passed'))
    for name in ('export/validation_report.json','hls/reports/direct_rtl.json','reports/driver_host_tests.json','reports/runtime_host_tests.json','reports/source_checks.json','vivado/reports/hwh_compat.json'):
        assert read(name)['passed'],name
    assert digest(ROOT/'hls/ip/gesture_blocks56_axis.zip')==summary['ip_sha256']
    rtl=read('hls/reports/direct_rtl.json')
    if summary.get('rtl_uses_functional_fp_primitive_models'):
        assert read('hls/reports/fp_equivalence.json')['bitwise_cycle_checks']>=1000
    pair=[ROOT/'overlay/gesture_blocks56.bit',ROOT/'overlay/gesture_blocks56.hwh']
    artifacts={p.name:{'sha256':digest(p),'bytes':p.stat().st_size} for p in pair}
    assert artifacts['gesture_blocks56.hwh']['sha256']==read('vivado/reports/hwh_compat.json')['hwh_sha256']
    util=(ROOT/'vivado/reports/utilization.rpt').read_text();resources={}
    for name in ('CLB LUTs','CLB Registers','Block RAM Tile','URAM','DSPs'):
        match=re.search(r'^\|\s*'+re.escape(name)+r'\*?\s*\|\s*([\d.]+)',util,re.M)
        if match:resources[name]=float(match.group(1))
    manifest={'release':'gesture_blocks56_fp32_pw16_v2','part':result['part'],'vivado':result['vivado'],
        'implementation_passed':True,'csim_passed':True,'rtl_simulation_passed':True,'native_hls_cosim_run':False,
        'rtl_simulation_kind':rtl['kind'],
        'rtl_uses_functional_fp_primitive_models':summary.get('rtl_uses_functional_fp_primitive_models',False),
        'vendor_full_design_simulation_completed':rtl.get('vendor_full_design_simulation_completed',True),
        'board_tested':False,'input_shape':[1,40,28,28],'output_shape':[1,40,28,28],'dtype':'float32',
        'model_sha256':read('export/block_params.json')['source_model_sha256'],'blocks':[5,6],'onnx_nodes':24,
        'hardware_top':'gesture_blocks56_axis','clock_mhz_nominal':100,
        'pointwise_input_lanes':16,'pointwise_output_lanes':8,'depthwise_lanes':2,
        'weight_storage':'FP32 pairs in BRAM; feature tensors in URAM',
        'setup_slack_ns':float(result['setup_slack_ns']),'hold_slack_ns':float(result['hold_slack_ns']),
        'input_bytes_per_run':125456,'output_bytes_per_run':125440,'parameter_bytes_per_bank':82848,
        'weight_residency':'two banks loaded once; intermediate tensors remain on chip',
        'resources':resources,'artifacts':artifacts,'hls_ip_sha256':summary['ip_sha256'],
        'scope':'PS + DMA + complete features.5 and features.6; no board HDMI; no board speedup claim before validation'}
    (ROOT/'overlay/build_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    files=[]
    for folder in ('source','export','overlay','blocks16_driver','board','hls/src','hls/tb','hls/rtl_tb','hls/ip','hls/reports','vivado','board_baseline','compat','tools','tests','reports'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.jou','.pb') and 'results' not in p.relative_to(ROOT).parts:
                files.append(p)
    files.extend(ROOT/name for name in ('blocks16_runtime.py','README_操作说明.md','optimization_plan.json','hls/run_hls.tcl','hls/setup_rtl.tcl'))
    files=sorted(set(files))
    package={'release':'gesture_blocks56_fp32_pw16_v2','board_tested':False,'sha256':{p.relative_to(ROOT).as_posix():digest(p) for p in files}}
    (ROOT/'package_manifest.json').write_text(json.dumps(package,indent=2)+'\n')
    files.append(ROOT/'package_manifest.json')
    archive=ROOT.parent/'output/gesture_blocks56_pw16_hw_v2.zip';archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,ROOT.name+'/'+p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    release={'release':manifest['release'],'archive':str(archive),'sha256':digest(archive),'bytes':archive.stat().st_size,
        'files':len(files),'board_tested':False,'implementation_passed':True,'rtl_simulation_passed':True}
    (ROOT.parent/'output/gesture_blocks56_pw16_release.json').write_text(json.dumps(release,indent=2)+'\n')
    shutil.copyfile(ROOT/'README_操作说明.md',ROOT.parent/'output/PW16_FPGA_v2_guide.md')
    print(json.dumps(release,indent=2))

if __name__=='__main__':main()
