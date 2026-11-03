"""Audit DMA, clock and reset wiring with the exact PYNQ 3 HWH parser."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import types
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from blocks16_driver import BlocksAccelerator
parser=argparse.ArgumentParser();parser.add_argument('--hwh',type=Path,default=ROOT/'overlay/gesture_blocks56.hwh');args=parser.parse_args()
source=ROOT/'compat/pynq3_hwh_parser.py';source.parent.mkdir(exist_ok=True)
if not source.exists():shutil.copyfile(ROOT.parent/'gesture4_accel_v2/compat/pynq3_hwh_parser.py',source)
raw=source.read_bytes().replace(b'\r\n',b'\n');expected='3318efd1e2cb0697a2ef0de55859cb461eb3f80e'
assert any(hashlib.sha1(b'blob '+str(len(v)).encode()+b'\0'+v).hexdigest()==expected for v in (raw,raw[:-1]))
ps=types.ModuleType('pynq.ps');ps.CPU_ARCH=ps.ZU_ARCH='aarch64';ps.ZYNQ_ARCH='armv7l';ps.CPU_ARCH_IS_SUPPORTED=True
sys.modules['pynq']=types.ModuleType('pynq');sys.modules['pynq.ps']=ps
spec=importlib.util.spec_from_file_location('blocks56_pynq3_parser',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
hwh=args.hwh.resolve();metadata=module._HWHUltrascale(str(hwh))
BlocksAccelerator._validate_description(metadata.ip_dict)
assert metadata.ip_dict['axi_dma_0']['phys_addr']==0xA0000000
assert metadata.ip_dict['gesture_blocks56_axis_0']['phys_addr']==0xA0010000
assert metadata.clock_dict[0]=={'divisor0':15,'divisor1':1,'enable':1}
tree=ET.parse(hwh).getroot();reset=tree.find(".//MODULE[@INSTANCE='rst_pl0']")
for name in ('C_EXT_RESET_HIGH','C_AUX_RESET_HIGH'):
    assert reset.find(f"./PARAMETERS/PARAMETER[@NAME='{name}']").get('VALUE')=='0'
for name in ('ext_reset_in','aux_reset_in'):
    assert reset.find(f"./PORTS/PORT[@NAME='{name}']").get('SIGNAME')=='ps_e_0_pl_resetn0'
result={'passed':True,'board_tested':False,'scope':'Offline PYNQ 3 parser, DMA, addresses, PL0 clock and both reset inputs',
    'hwh_sha256':hashlib.sha256(hwh.read_bytes()).hexdigest(),'parser_git_blob':expected,
    'dma_address':'0xa0000000','kernel_address':'0xa0010000','both_resets_from_ps_and_active_low':True}
(ROOT/'vivado/reports/hwh_compat.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
