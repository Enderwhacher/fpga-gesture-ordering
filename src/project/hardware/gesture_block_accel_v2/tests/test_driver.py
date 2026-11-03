"""Host-only protocol/lifetime tests; simulated bus is not FPGA evidence."""
import json
from pathlib import Path
import sys
import types
import unittest
import tempfile
import hashlib
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from blocks16_driver import BlocksAccelerator,AcceleratorError
from blocks16_driver.packet import *

class Buffer(np.ndarray):
    def __new__(cls,shape,dtype):
        obj=np.zeros(shape,dtype).view(cls)
        obj.physical_address=0x800100000;obj.freed=False;obj.flushed=False;obj.invalidated=False
        return obj
    def freebuffer(self):self.freed=True

class Bus:
    def __init__(self):self.values={0:1,0x30:1,4:0,0x34:0};self.reset_ok=True;self.accesses=0
    def read(self,offset):self.accesses+=1;return self.values.get(offset,0)
    def write(self,offset,value):
        self.accesses+=1
        if offset==0 and value==4 and self.reset_ok:self.values.update({0:0,0x30:0,4:1,0x34:1})

class Core:
    def __init__(self,events):self.done=False;self.events=events
    def read(self,offset):result=2 if self.done else 4;self.done=False;return result
    def write(self,offset,value):self.events.append('start')

class Channel:
    def __init__(self,dma,direction):self.dma=dma;self.direction=direction;self.transferred=0
    def transfer(self,buffer,nbytes):
        self.dma.events.append(self.direction);self.buffer=buffer;self.length=nbytes
        if self.direction=='tx':buffer.flushed=True;self.dma.launch()
    def wait(self):
        assert self.dma.mmio.read(4 if self.direction=='tx' else 0x34)&2,'Unbounded wait before idle'
        self.transferred=self.length-(4 if self.direction=='rx' and self.dma.behavior=='short' else 0)
        if self.direction=='rx':self.buffer.invalidated=True
        self.dma.events.append('wait_'+self.direction)

class DMA:
    def __init__(self,core):
        self.events=core.events;self.core=core;self.mmio=Bus();self.behavior='normal';self.flags=0
        self.sendchannel=Channel(self,'tx');self.recvchannel=Channel(self,'rx')
    def launch(self):
        if self.behavior=='stall':self.mmio.values.update({4:0,0x34:0});return
        if self.behavior=='error':self.mmio.values[4]=0x20;return
        packet=self.sendchannel.buffer;op,bank=int(packet[1]),int(packet[2]);out=self.recvchannel.buffer
        if op==LOAD:self.flags|=1<<bank
        if op==RUN:
            out[:FRAME_WORDS]=packet[4:4+FRAME_WORDS]
            if self.behavior=='nonfinite':out[0]=0x7fc00000
        else:out[0]=0xA5010000|(self.flags<<8)|(bank if op==LOAD else 0)
        if self.behavior=='badack':out[0]=0xE1000001
        self.mmio.values.update({4:2,0x34:2,0x28:self.sendchannel.length,0x58:self.recvchannel.length})
        self.core.done=True

def fake_accel():
    obj=BlocksAccelerator.__new__(BlocksAccelerator)
    obj.timeout=.005;obj._pending=obj._closed=obj._faulted=obj._overlay_lost=False
    obj._token=0;obj._tx=Buffer((MAX_WORDS,),np.uint32);obj._rx=Buffer((FRAME_WORDS,),np.uint32)
    obj.overlay=types.SimpleNamespace(is_loaded=lambda:True)
    obj.conv=Core([]);obj.dma=DMA(obj.conv);obj.last_timing=None;obj.loaded_banks=set();obj.completed_frames=0
    return obj

def loaded():
    obj=fake_accel()
    for bank in (0,1):obj.load_parameters(bank,np.zeros(PARAM_WORDS,np.float32))
    obj.dma.events.clear();return obj

class Tests(unittest.TestCase):
    def setUp(self):self.x=np.arange(FRAME_WORDS,dtype=np.float32).reshape(SHAPE)/1000
    def test_header_bits_and_noncontiguous_input(self):
        dst=np.zeros(MAX_WORDS,np.uint32);x=self.x[:,:,:,::-1]
        self.assertEqual(pack_into(dst,RUN,0,x),FRAME_BYTES+16)
        np.testing.assert_array_equal(dst[:4],[MAGIC,RUN,0,1])
        np.testing.assert_array_equal(dst[4:].view(np.float32).reshape(SHAPE),x)
    def test_invalid_input_never_starts_dma(self):
        obj=loaded()
        for x in (self.x[0],self.x.astype(np.float64),np.full(SHAPE,np.inf,np.float32)):
            with self.assertRaises(ValueError):obj.run(x)
        with self.assertRaises(ValueError):obj._begin(True)
        self.assertFalse(obj._pending);self.assertEqual(obj.dma.events,[]);obj.close()
    def test_initialization_and_resident_banks(self):
        obj=fake_accel();self.assertEqual(obj.ping(),0xA5010000)
        with self.assertRaises(AcceleratorError):obj.run(self.x)
        for b in (0,1):obj.load_parameters(b,np.zeros(PARAM_WORDS,np.float32))
        self.assertEqual(obj.ping(),0xA5010300)
        obj.dma.events.clear();actual=obj.run(self.x)
        self.assertEqual(obj.dma.events,['rx','start','tx','wait_tx','wait_rx'])
        self.assertEqual(obj.dma.sendchannel.length,125456)
        np.testing.assert_array_equal(actual,self.x)
        self.assertTrue(obj._tx.flushed and obj._rx.invalidated)
        self.assertFalse(np.shares_memory(actual,obj._rx))
        obj.run(-self.x);np.testing.assert_array_equal(actual,self.x)
        self.assertEqual(obj.completed_frames,2);obj.close()
    def test_inflight_token_validation(self):
        obj=loaded();token=obj.begin(self.x)
        with self.assertRaises(AcceleratorError):obj.begin(self.x)
        with self.assertRaises(AcceleratorError):obj.wait(token+1)
        obj.wait(token)
        with self.assertRaises(AcceleratorError):obj.wait(token)
        obj.close()
    def test_faults_do_not_count_or_free_active_buffers(self):
        for behavior in ('stall','error','short','nonfinite'):
            with self.subTest(behavior=behavior):
                obj=loaded();obj.dma.behavior=behavior;tx,rx=obj._tx,obj._rx
                with self.assertRaises(AcceleratorError):obj.run(self.x)
                self.assertEqual(obj.completed_frames,0);self.assertFalse(tx.freed or rx.freed)
                with self.assertRaises(AcceleratorError):obj.run(self.x)
                obj.close();self.assertTrue(tx.freed and rx.freed)
    def test_bad_ack_does_not_mark_bank_loaded(self):
        obj=fake_accel();obj.dma.behavior='badack'
        with self.assertRaises(AcceleratorError):obj.load_parameters(0,np.zeros(PARAM_WORDS,np.float32))
        self.assertEqual(obj.loaded_banks,set());obj.close()
    def test_overlay_replaced_never_touches_old_mmio(self):
        obj=loaded();obj.begin(self.x);accesses=obj.dma.mmio.accesses;tx,rx=obj._tx,obj._rx
        obj.overlay.is_loaded=lambda:False
        with self.assertRaisesRegex(AcceleratorError,'replaced'):obj.wait(obj._token)
        with self.assertRaisesRegex(AcceleratorError,'Restart board'):obj.close()
        self.assertEqual(obj.dma.mmio.accesses,accesses);self.assertFalse(tx.freed or rx.freed)
        obj.close()
    def test_unconfirmed_reset_quarantines_buffers(self):
        obj=loaded();obj._faulted=True;obj.dma.mmio.reset_ok=False;tx,rx=obj._tx,obj._rx
        with self.assertRaisesRegex(AcceleratorError,'buffers retained'):obj.close()
        self.assertFalse(tx.freed or rx.freed)
    def test_closed_and_invalid_dma_description(self):
        obj=loaded();obj.close()
        with self.assertRaises(AcceleratorError):obj.run(self.x)
        with self.assertRaises(AcceleratorError):BlocksAccelerator._validate_description({})
    def test_clock_guard_before_dma_object_access(self):
        accesses=[]
        class Overlay:
            def __init__(self,*a,**kw):self.ip_dict={};self.device=None
            def download(self):pass
            def __getattr__(self,name):accesses.append(name);raise AssertionError(name)
        pynq=types.ModuleType('pynq');pynq.Overlay=Overlay;pynq.Clocks=types.SimpleNamespace(fclk0_mhz=0)
        pynq.allocate=lambda **kw:None;pynq.lib=types.ModuleType('pynq.lib');pynq.lib.dma=types.ModuleType('pynq.lib.dma')
        with patch.dict(sys.modules,{'pynq':pynq,'pynq.lib':pynq.lib,'pynq.lib.dma':pynq.lib.dma}),patch.object(BlocksAccelerator,'_validate_artifacts'),patch.object(BlocksAccelerator,'_validate_description'):
            with self.assertRaisesRegex(AcceleratorError,'clock'):BlocksAccelerator('x.bit',[np.zeros(PARAM_WORDS,np.float32)]*2)
        self.assertEqual(accesses,[])
    def test_constructor_loads_exactly_two_banks_once(self):
        overlay=types.SimpleNamespace(ip_dict={},device=None,download=lambda:None,is_loaded=lambda:True)
        overlay.gesture_blocks56_axis_0=Core([]);overlay.axi_dma_0=DMA(overlay.gesture_blocks56_axis_0)
        pynq=types.ModuleType('pynq');pynq.Overlay=lambda *a,**kw:overlay;pynq.Clocks=types.SimpleNamespace(fclk0_mhz=98.8879)
        pynq.allocate=lambda shape,dtype,**kw:Buffer(shape,dtype)
        pynq.lib=types.ModuleType('pynq.lib');pynq.lib.dma=types.ModuleType('pynq.lib.dma')
        with patch.dict(sys.modules,{'pynq':pynq,'pynq.lib':pynq.lib,'pynq.lib.dma':pynq.lib.dma}),patch.object(BlocksAccelerator,'_validate_artifacts'),patch.object(BlocksAccelerator,'_validate_description'):
            obj=BlocksAccelerator('x.bit',[np.zeros(PARAM_WORDS,np.float32)]*2)
        self.assertEqual(obj._token,4);self.assertEqual(obj.loaded_banks,{0,1});self.assertEqual(obj.completed_frames,0)
        obj.run(self.x);self.assertEqual(obj._token,5);self.assertEqual(obj.completed_frames,1);obj.close()
    def test_release_pair_hash_and_pass_flags(self):
        temporary=ROOT/'build/host_tests';temporary.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as directory:
            root=Path(directory);bit=root/'test.bit';hwh=root/'test.hwh';bit.write_bytes(b'bit');hwh.write_bytes(b'hwh')
            info={'release':'gesture_blocks56_fp32_pw16_v2','implementation_passed':True,'rtl_simulation_passed':True,
                  'input_shape':list(SHAPE),'output_shape':list(SHAPE),
                  'artifacts':{p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (bit,hwh)}}
            manifest=root/'build_manifest.json';manifest.write_text(json.dumps(info))
            BlocksAccelerator._validate_artifacts(bit)
            info['rtl_simulation_passed']=False;manifest.write_text(json.dumps(info))
            with self.assertRaisesRegex(AcceleratorError,'RTL'):BlocksAccelerator._validate_artifacts(bit)
            info['rtl_simulation_passed']=True;manifest.write_text(json.dumps(info));hwh.write_bytes(b'wrong')
            with self.assertRaisesRegex(AcceleratorError,'hash mismatch'):BlocksAccelerator._validate_artifacts(bit)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    out=ROOT/'reports/driver_host_tests.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'passed':result.wasSuccessful(),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'board_tested':False,'scope':'Mock DMA/MMIO protocol, ownership, fault, cache and lifetime checks'},indent=2)+'\n')
    sys.exit(not result.wasSuccessful())
