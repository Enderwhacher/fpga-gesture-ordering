"""Functional FP primitive binding for efficient generated-control RTL checks.

The vendor primitive models are tested separately for bit/cycle equivalence.
This is simulation only; the synthesized IP archive is never modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'build/fast_rtl_test'
NATIVE=ROOT/'build/hls_workspace/gesture_blocks56_fp32_pw16/hls/sim/verilog'
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from blocks16_driver.packet import MAX_WORDS,LOAD,RUN,PING,pack_into
from export_blocks import compare

def prepare():
    WORK.mkdir(parents=True,exist_ok=True)
    models=ROOT/'hls/rtl_tb/fp_functional_models.sv'
    lines=[f'sv xil_defaultlib "{models.as_posix()}"'];primitive=[]
    for line in (NATIVE/'gesture_blocks56_axis.prj').read_text().splitlines():
        m=re.fullmatch(r'\s*(vhdl|sv)\s+(\w+)\s+"([^"]+)"\s*',line)
        if not m:continue
        lang,lib,rel=m.groups();p=NATIVE/rel
        if p.suffix=='.vhd' and p.name.endswith('_ip.vhd'):
            primitive.append(f'{lang} {lib} "{p.resolve().as_posix()}"');continue
        if not ((p.name.startswith('gesture_blocks56_axis') and p.suffix=='.v' and '.autotb.' not in p.name) or p.name=='glbl.v'):continue
        if re.search(r'_f(add|mul|cmp)_',p.name):
            match=re.search(r'_f(add|mul|cmp)_',p.name);kind=match.group(1)
            text=p.read_text();original=p.stem+'_ip'
            # Only simulation binding changes, not HLS pipeline/RTL logic.
            text=text.replace(original+' ',f'model_f{kind} ')
            local=WORK/p.name;local.write_text(text);p=local
        lines.append(f'{lang} {lib} "{p.resolve().as_posix()}"')
    assert len(primitive)==3 and len(lines)>40
    (WORK/'fast_rtl.prj').write_text('\n'.join(lines+[f'sv xil_defaultlib "{(ROOT/"hls/rtl_tb/axis_rtl_tb.sv").as_posix()}"'])+'\n')
    (WORK/'fp_equivalence.prj').write_text('\n'.join(primitive+[f'sv xil_defaultlib "{models.as_posix()}"',f'sv xil_defaultlib "{(ROOT/"hls/rtl_tb/fp_equivalence_tb.sv").as_posix()}"'])+'\n')
    for p in NATIVE.glob('*.dat'):shutil.copyfile(p,WORK/p.name)
    shutil.copyfile('E:/AMDDesignTools/2025.2/Vivado/data/xsim/xsim.ini',WORK/'xsim.ini')
    (WORK/'run.tcl').write_text('run all\nquit\n')
    params=[np.fromfile(ROOT/f'export/params/block{b}.bin',dtype='<f4') for b in (0,1)]
    x=np.load(ROOT/'export/cases/real_frame/input.npy',allow_pickle=False)
    other=np.random.default_rng(5656).normal(0,.2,x.shape).astype(np.float32)
    second=np.load(ROOT/'export/cases/random/input.npy',allow_pickle=False)
    commands=[(PING,0,None),(LOAD,0,params[0]),(LOAD,1,params[1]),(PING,0,None),(RUN,0,x),(RUN,0,second),
              (LOAD,0,np.zeros_like(params[0])),(LOAD,1,np.zeros_like(params[1])),(RUN,0,other)]
    for i,(op,bank,payload) in enumerate(commands):
        packet=np.zeros(MAX_WORDS,np.uint32);n=pack_into(packet,op,bank,payload)//4
        np.savetxt(WORK/f'packet_{i}.hex',packet[:n],fmt='%08x')
    np.save(WORK/'golden_4.npy',np.load(ROOT/'export/cases/real_frame/golden_output.npy',allow_pickle=False),allow_pickle=False)
    np.save(WORK/'golden_5.npy',np.load(ROOT/'export/cases/random/golden_output.npy',allow_pickle=False),allow_pickle=False)
    np.save(WORK/'golden_8.npy',other,allow_pickle=False)
    summary=json.loads((ROOT/'hls/reports/summary.json').read_text());summary['rtl_simulation_passed']=False
    (ROOT/'hls/reports/summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('Fast RTL project and vendor-primitive equivalence project prepared')

def verify():
    equivalence=json.loads((WORK/'fp_equivalence.json').read_text());assert equivalence['passed']
    interface=json.loads((WORK/'interface_report.json').read_text());assert interface['interface_passed'] and len(interface['transactions'])==9
    for i,expected in ((0,0xA5010000),(1,0xA5010100),(2,0xA5010301),(3,0xA5010300),(6,0xA5010300),(7,0xA5010301)):
        assert (WORK/f'output_{i}.hex').read_text().strip()==f'{expected:08x}'
    checks=[]
    for i,name in ((4,'dense_real_frame_trained_coefficients'),(5,'second_dense_frame_reuses_resident_trained_coefficients'),(8,'dense_changed_zero_coefficients_identity')):
        actual=np.array([int(s,16) for s in (WORK/f'output_{i}.hex').read_text().splitlines()],dtype='<u4').view('<f4').reshape(1,40,28,28)
        checks.append({'case':name,**compare(actual,np.load(WORK/f'golden_{i}.npy',allow_pickle=False))})
    summary=json.loads((ROOT/'hls/reports/summary.json').read_text())
    assert hashlib.sha256((ROOT/'hls/ip/gesture_blocks56_axis.zip').read_bytes()).hexdigest()==summary['ip_sha256']
    report={'passed':True,'board_tested':False,'kind':'Generated HLS RTL with cycle-matched functional FP32 primitive simulation models',
        'native_hls_cosim_run':False,'vendor_full_design_simulation_completed':False,
        'scope':'Actual generated control, RAM, addressing, pipelines and AXIS/AXI-Lite. Only three vendor floating-point primitive simulation bindings replaced; model arithmetic/latency checked separately against original vendor IP. Does not constitute full vendor-model end-to-end simulation.',
        'primitive_equivalence':equivalence,'cases':checks,'interface':interface,
        'simulation_models_sha256':hashlib.sha256((ROOT/'hls/rtl_tb/fp_functional_models.sv').read_bytes()).hexdigest()}
    report['vendor_primitive_sources_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (NATIVE/'ip/xil_defaultlib').glob('*_ip.vhd')}
    (ROOT/'hls/reports/direct_rtl.json').write_text(json.dumps(report,indent=2)+'\n')
    shutil.copyfile(WORK/'fp_equivalence.json',ROOT/'hls/reports/fp_equivalence.json')
    summary['rtl_simulation_passed']=True;summary['rtl_uses_functional_fp_primitive_models']=True
    (ROOT/'hls/reports/summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','verify'));args=p.parse_args()
    (prepare if args.stage=='prepare' else verify)()
