"""Run the generated RTL with stalls, resident weights and coefficient reload."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'build/axis_rtl_test'
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from blocks16_driver.packet import MAX_WORDS,LOAD,RUN,PING,pack_into
from export_blocks import reference,compare

def prepare():
    WORK.mkdir(parents=True,exist_ok=True)
    old_log=WORK/'xsim.log'
    if old_log.exists() and 'BLOCKS56_RTL_INTERFACE_PASS' not in old_log.read_text(errors='replace'):
        saved=WORK/'aborted_dense_attempt';saved.mkdir(exist_ok=True)
        for name in ('xsim.log','interface_report.json','output_4.hex','golden_4.npy','packet_1.hex','packet_2.hex','packet_4.hex'):
            if (WORK/name).exists():shutil.copyfile(WORK/name,saved/name)
    # Dense trained coefficients are covered by six C vectors. Here structured
    # sparse coefficients exercise every input/output channel, padding, SE and
    # both parameter banks while limiting expensive floating-point RTL events.
    blocks=[];trained=[]
    for bank in (0,1):
        p={k:np.zeros_like(v) for k,v in dict(np.load(ROOT/f'export/params/block{bank}.npz',allow_pickle=False)).items()}
        for c in range(120):
            p['expand_w'][c,(c*7+bank*3)%40,0,0]=np.float32(.3+(c%3)*.2)
            p['depthwise_w'][c,0,2,2]=np.float32(.6)
            p['depthwise_w'][c,0,0,0]=np.float32(.15)
            p['depthwise_w'][c,0,4,4]=np.float32(-.1)
            p['se2_w'][c,c%32,0,0]=np.float32(.025)
            p['se2_b'][c]=np.float32((c%7-3)*.1)
        for c in range(32):p['se1_w'][c,(c*3+bank)%120,0,0]=np.float32(.05)
        for c in range(40):
            for k in range(3):p['project_w'][c,(c*3+k+bank)%120,0,0]=np.float32(.2+(k%2)*.1)
        blocks.append(p)
        keys=('expand','depthwise','se1','se2','project')
        trained.append(np.concatenate([p[k+'_w'].ravel() for k in keys]+[p[k+'_b'].ravel() for k in keys]).astype('<f4'))
    rng=np.random.default_rng(1556)
    x=np.zeros((1,40,28,28),np.float32)
    x[0,0]=rng.normal(0,.1,(28,28))
    for c in range(40):
        x[0,c,c%28,(c*7)%28]+=np.float32((c%7-3)*.25)
        x[0,c,0,0]+=.75;x[0,c,27,27]-=.25
    other=x*np.float32(-.75)
    commands=[(PING,0,None),(LOAD,0,trained[0]),(LOAD,1,trained[1]),(PING,0,None),
              (RUN,0,x),(RUN,0,other),(LOAD,0,np.zeros_like(trained[0])),(LOAD,1,np.zeros_like(trained[1])),(RUN,0,x)]
    for i,(op,bank,payload) in enumerate(commands):
        packet=np.zeros(MAX_WORDS,np.uint32);count=pack_into(packet,op,bank,payload)//4
        np.savetxt(WORK/f'packet_{i}.hex',packet[:count],fmt='%08x')
    np.save(WORK/'golden_4.npy',reference(x,blocks),allow_pickle=False)
    np.save(WORK/'golden_5.npy',reference(other,blocks),allow_pickle=False)
    np.save(WORK/'golden_8.npy',x,allow_pickle=False)
    native=ROOT/'build/hls_workspace/gesture_blocks56_fp32_pw16/hls/sim/verilog'
    for path in native.glob('*.dat'):shutil.copyfile(path,WORK/path.name)
    lines=[]
    for line in (native/'gesture_blocks56_axis.prj').read_text().splitlines():
        m=re.fullmatch(r'\s*(vhdl|sv)\s+(\w+)\s+"([^"]+)"\s*',line)
        if not m:continue
        lang,lib,rel=m.groups();path=native/rel
        if (path.name.startswith('gesture_blocks56_axis') and path.suffix in ('.v','.vhd') and '.autotb.' not in path.name) or path.name=='glbl.v':
            assert path.exists(),path
            lines.append(f'{lang} {lib} "{path.resolve().as_posix()}"')
    assert len(lines)>5
    shutil.copyfile(ROOT/'hls/rtl_tb/axis_rtl_tb.sv',WORK/'axis_rtl_tb.sv')
    lines.append(f'sv xil_defaultlib "{(WORK/"axis_rtl_tb.sv").as_posix()}"')
    (WORK/'axis_rtl.prj').write_text('\n'.join(lines)+'\n')
    shutil.copyfile('E:/AMDDesignTools/2025.2/Vivado/data/xsim/xsim.ini',WORK/'xsim.ini')
    (WORK/'run.tcl').write_text('run all\nquit\n')
    print('RTL prepared:',len(lines),'source files; 9 commands; 3 full-size RUNs')

def verify():
    interface=json.loads((WORK/'interface_report.json').read_text())
    assert interface['interface_passed'] and len(interface['transactions'])==9
    for i,expected in ((0,0xA5010000),(1,0xA5010100),(2,0xA5010301),(3,0xA5010300),(6,0xA5010300),(7,0xA5010301)):
        assert (WORK/f'output_{i}.hex').read_text().strip()==f'{expected:08x}',i
    checks=[]
    for i,name in ((4,'structured_parameters_all_channel_impulses_and_one_dense_channel'),(5,'reused_resident_structured_parameters'),(8,'changed_zero_parameters_identity')):
        words=np.array([int(s,16) for s in (WORK/f'output_{i}.hex').read_text().splitlines()],dtype='<u4')
        actual=words.view('<f4').reshape(1,40,28,28)
        check=compare(actual,np.load(WORK/f'golden_{i}.npy',allow_pickle=False))
        checks.append({'name':name,**check})
    report={'passed':True,'board_tested':False,'kind':'Generated RTL, XSIM, AXI-Lite, input gaps and output backpressure',
            'vendor_full_design_simulation_completed':True,
            'native_hls_cosim_run':False,'scope':'Three full-size RUN transactions; reused structured sparse coefficients then zero-coefficient reload; all channels, padding, SE, residual, input gaps and output stalls. Six dense trained-model cases checked in C simulation. Initial dense-coefficient RTL attempt was stopped for simulation cost and is not counted as a pass.',
            'cases':checks,'interface':interface}
    (ROOT/'hls/reports/direct_rtl.json').write_text(json.dumps(report,indent=2)+'\n')
    summary=json.loads((ROOT/'hls/reports/summary.json').read_text());summary['rtl_simulation_passed']=True
    summary['rtl_uses_functional_fp_primitive_models']=False
    (ROOT/'hls/reports/summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','verify']);args=parser.parse_args()
    (prepare if args.stage=='prepare' else verify)()
