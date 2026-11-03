"""FP32 command packets for resident two-block parameters and NCHW frames."""
import struct
import numpy as np

MAGIC=0x47534232
VERSION=1
LOAD=1
RUN=2
PING=3
SHAPE=(1,40,28,28)
FRAME_WORDS=31360
PARAM_WORDS=20712
MAX_WORDS=FRAME_WORDS+4
FRAME_BYTES=FRAME_WORDS*4


def checked(value,shape):
    value=np.asarray(value)
    if value.shape!=shape or value.dtype!=np.dtype('<f4') or not np.isfinite(value).all():
        raise ValueError('Expected finite little-endian float32 '+str(shape))
    return np.ascontiguousarray(value)


def pack_into(destination,op,bank=0,payload=None):
    if type(op) is not int or op not in (LOAD,RUN,PING) or type(bank) is not int or bank not in (0,1):
        raise ValueError('Invalid command/bank')
    if destination.shape!=(MAX_WORDS,) or destination.dtype!=np.dtype('<u4') or not destination.flags.c_contiguous:
        raise ValueError('Invalid command buffer')
    if op==LOAD: values=checked(payload,(PARAM_WORDS,))
    elif op==RUN: values=checked(payload,SHAPE)
    else:
        if payload is not None: raise ValueError('PING takes no payload')
        values=None
    target=memoryview(destination).cast('B')
    target[:16]=struct.pack('<4I',MAGIC,op,bank,VERSION)
    if values is not None:
        raw=memoryview(values).cast('B'); target[16:16+len(raw)]=raw
        return 16+len(raw)
    return 16
