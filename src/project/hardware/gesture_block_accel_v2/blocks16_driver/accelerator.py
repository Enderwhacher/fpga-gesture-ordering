"""Bounded PYNQ DMA owner for the two complete residual blocks.

Weights are initialized once. All inference outputs are copied into CPU-owned
arrays. No camera, display, fallback classifier or cross-frame DMA queue lives
here. RX, kernel and TX overlap within each single transaction.
"""
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from .packet import FRAME_BYTES,FRAME_WORDS,MAX_WORDS,PARAM_WORDS,SHAPE,LOAD,RUN,PING,pack_into,checked


class AcceleratorError(RuntimeError): pass
_QUARANTINED=[]


class BlocksAccelerator:
    def __init__(self,bitfile,parameters,timeout=5.):
        if not np.isfinite(timeout) or timeout<=0: raise ValueError('Positive finite timeout required')
        if sys.byteorder!='little': raise RuntimeError('Little-endian host required')
        self._validate_artifacts(Path(bitfile))
        if len(parameters)!=2: raise ValueError('Two parameter banks required')
        params=[checked(p,(PARAM_WORDS,)).copy() for p in parameters]
        self.timeout=float(timeout); self._pending=False; self._faulted=False; self._closed=False; self._overlay_lost=False
        self._token=0; self._tx=self._rx=None; self.last_timing=None
        self.loaded_banks=set(); self.completed_frames=0
        from pynq import Overlay,allocate,Clocks
        import pynq.lib.dma
        self.overlay=Overlay(str(Path(bitfile).resolve()),download=False)
        self._validate_description(self.overlay.ip_dict)
        self.overlay.download()
        if not 95.<=float(Clocks.fclk0_mhz)<=105.:
            raise AcceleratorError('PL0 clock must be near 100 MHz; abort before DMA MMIO')
        self.dma=self.overlay.axi_dma_0; self.conv=self.overlay.gesture_blocks56_axis_0
        self._tx=allocate(shape=(MAX_WORDS,),dtype=np.uint32,target=self.overlay.device,cacheable=True)
        try: self._rx=allocate(shape=(FRAME_WORDS,),dtype=np.uint32,target=self.overlay.device,cacheable=True)
        except BaseException:
            self._tx.freebuffer(); self._tx=None; raise
        try:
            if self._tx.physical_address%8 or self._rx.physical_address%8: raise AcceleratorError('Unaligned DMA allocation')
            cold=self.ping()
            if cold!=0xA5010000: raise AcceleratorError('Unexpected cold hardware signature: '+hex(cold))
            for bank,p in enumerate(params): self.load_parameters(bank,p)
            if self.ping()!=0xA5010300: raise AcceleratorError('Hardware did not retain both parameter banks')
        except BaseException:
            self.close(); raise

    @staticmethod
    def _validate_artifacts(bitfile):
        bitfile=bitfile.resolve(); manifest=bitfile.parent/'build_manifest.json'
        info=json.loads(manifest.read_text(encoding='utf-8'))
        if info.get('release')!='gesture_blocks56_fp32_pw16_v2' or info.get('input_shape')!=list(SHAPE) or info.get('output_shape')!=list(SHAPE):
            raise AcceleratorError('Wrong blocks56 release or tensor shape')
        if not info.get('implementation_passed') or not info.get('rtl_simulation_passed'):
            raise AcceleratorError('Hardware release has not passed implementation and RTL checks')
        for path in (bitfile,bitfile.with_suffix('.hwh')):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=info['artifacts'][path.name]['sha256']:
                raise AcceleratorError('Bitstream/HWH hash mismatch: '+path.name)

    @staticmethod
    def _validate_description(ip):
        if ip.get('gesture_blocks56_axis_0',{}).get('type')!='hand:hls:gesture_blocks56_axis:2.0':
            raise AcceleratorError('Missing/wrong blocks56 IP')
        dma=ip.get('axi_dma_0',{})
        if dma.get('type')!='xilinx.com:ip:axi_dma:7.1': raise AcceleratorError('Wrong DMA type')
        expected={'c_include_sg':0,'c_micro_dma':0,'c_addr_width':64,'c_include_mm2s':1,'c_include_s2mm':1,
                  'c_m_axi_mm2s_data_width':64,'c_m_axi_s2mm_data_width':64,
                  'c_m_axis_mm2s_tdata_width':32,'c_s_axis_s2mm_tdata_width':32}
        p=dma.get('parameters',{})
        if any(int(p.get(k,-1))!=v for k,v in expected.items()): raise AcceleratorError('DMA parameters differ')
        if (1<<int(p['c_sg_length_width']))-1<MAX_WORDS*4: raise AcceleratorError('DMA length field too small')

    def _ensure_usable(self):
        if self._closed: raise AcceleratorError('Accelerator is closed')
        if self._faulted: raise AcceleratorError('Previous hardware fault; close and reload')
        if not self.overlay.is_loaded():
            self._faulted=True; self._overlay_lost=True
            raise AcceleratorError('Computation overlay was replaced; no further MMIO is permitted')

    def diagnostics(self):
        self._ensure_usable()
        return {'mm2s_status':hex(self.dma.mmio.read(0x04)),'s2mm_status':hex(self.dma.mmio.read(0x34)),
                'mm2s_length':self.dma.mmio.read(0x28),'s2mm_length':self.dma.mmio.read(0x58),
                'pending':self._pending,'faulted':self._faulted}

    def _begin(self,op,bank=0,payload=None):
        self._ensure_usable()
        if self._pending: raise AcceleratorError('One command is already in flight')
        if op==RUN and self.loaded_banks!={0,1}: raise AcceleratorError('Load both parameter banks before RUN')
        start=time.perf_counter(); nbytes=pack_into(self._tx,op,bank,payload)
        self._pack_ms=(time.perf_counter()-start)*1000
        self._token+=1; self._pending=True; self._done_seen=False
        self._command=op; self._output_bytes=FRAME_BYTES if op==RUN else 4
        self._started=time.perf_counter()
        try:
            self.conv.read(0)
            self.dma.recvchannel.transfer(self._rx,nbytes=self._output_bytes)
            self.conv.write(0,1)
            self.dma.sendchannel.transfer(self._tx,nbytes=nbytes)
        except BaseException:
            self._faulted=True; raise
        return self._token

    def _wait(self,token):
        self._ensure_usable()
        if not self._pending or token!=self._token: raise AcceleratorError('Invalid/consumed transaction token')
        deadline=self._started+self.timeout
        try:
            while True:
                tx=self.dma.mmio.read(0x04); rx=self.dma.mmio.read(0x34)
                self._done_seen|=bool(self.conv.read(0)&2)
                if (tx|rx)&0x770 or (tx|rx)&1: raise AcceleratorError('DMA error/halt: '+json.dumps(self.diagnostics()))
                if tx&2 and rx&2 and self._done_seen: break
                if time.perf_counter()>=deadline: raise AcceleratorError('DMA/IP timeout: '+json.dumps(self.diagnostics()))
                time.sleep(.0001)
            self.dma.sendchannel.wait(); self.dma.recvchannel.wait()
            if self.dma.recvchannel.transferred!=self._output_bytes: raise AcceleratorError('Unexpected response length: '+str(self.dma.recvchannel.transferred))
            transferred=time.perf_counter()
            if self._command==RUN:
                value=np.empty(SHAPE,dtype=np.float32)
                memoryview(value).cast('B')[:]=memoryview(self._rx).cast('B')[:FRAME_BYTES]
                if not np.isfinite(value).all(): raise AcceleratorError('Nonfinite blocks56 output')
                self.completed_frames+=1
            else: value=int(self._rx[0])
            finished=time.perf_counter()
            self.last_timing={'pack_ms':self._pack_ms,'dma_kernel_wait_ms':(transferred-self._started)*1000,
                             'output_copy_check_ms':(finished-transferred)*1000,
                             'total_ms':self._pack_ms+(finished-self._started)*1000,
                             'command':self._command,'note':'Includes packing, DMA, cache maintenance and owned output copy; not pure kernel cycles'}
            self._pending=False
            return value
        except BaseException:
            self._faulted=True; raise

    def ping(self): return self._wait(self._begin(PING))

    def load_parameters(self,bank,parameters):
        result=self._wait(self._begin(LOAD,bank,parameters))
        expected=0xA5010000|(((sum(1<<b for b in self.loaded_banks)|(1<<bank)))<<8)|bank
        if result!=expected:
            self._faulted=True; raise AcceleratorError('Parameter acknowledgement mismatch: '+hex(result))
        self.loaded_banks.add(bank)

    def begin(self,x): return self._begin(RUN,0,x)
    def wait(self,token): return self._wait(token)
    def run(self,x): return self.wait(self.begin(x))

    def close(self):
        if self._closed: return
        # A different bitstream can remove these addresses entirely. Never read
        # or reset stale PL registers, even while trying to clean up a fault.
        if not self.overlay.is_loaded(): self._overlay_lost=True
        safe=not(self._pending or self._faulted or self._overlay_lost)
        if not safe and not self._overlay_lost:
            try:
                self.dma.mmio.write(0,4); deadline=time.perf_counter()+.5
                while time.perf_counter()<deadline:
                    a,b=self.dma.mmio.read(0),self.dma.mmio.read(0x30)
                    tx,rx=self.dma.mmio.read(0x04),self.dma.mmio.read(0x34)
                    if not(a|b)&4 and tx&1 and rx&1: safe=True; break
                    time.sleep(.001)
            except BaseException: safe=False
        for buffer in (self._tx,self._rx):
            if buffer is not None:
                if safe: buffer.freebuffer()
                else: _QUARANTINED.append(buffer)
        self._tx=self._rx=None; self._closed=True
        if not safe: raise AcceleratorError('DMA reset unconfirmed; buffers retained. Restart board before reuse')

    def __enter__(self): return self
    def __exit__(self,kind,value,tb):
        try: self.close()
        except BaseException:
            if kind is None: raise
