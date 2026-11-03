"""Read-only setup and exclusive ownership for the standalone FPGA test."""
from contextlib import contextmanager
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
def load_cv():
    runtime=ROOT.parent/'gesture_runtime_cv410'
    if 'cv2' not in sys.modules and (runtime/'cv2').is_dir():sys.path.insert(0,str(runtime))
    import cv2
    numbers=tuple(map(int,re.findall(r'\d+',cv2.__version__)[:2]))
    if numbers<(4,10):raise RuntimeError('OpenCV 4.10 required. Restart the kernel and run from the first cell. Existing runtime: '+str(runtime))
    return cv2

@contextmanager
def exclusive_board():
    if platform.system()!='Linux' or platform.machine().lower() not in ('aarch64','arm64'):
        raise RuntimeError('Run this test on the PYNQ-ZU board, not the laptop')
    # The working ordering app reserves this port before loading its overlay.
    # Holding it for the test prevents accidental concurrent app startup.
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:sock.bind(('0.0.0.0',8765));sock.listen(1)
        except OSError as error:raise RuntimeError('Port 8765 is occupied. Stop the ordering server before FPGA validation.') from error
        fuser=shutil.which('fuser')
        if fuser and Path('/dev/video0').exists():
            result=subprocess.run([fuser,'/dev/video0'],capture_output=True,text=True,timeout=3)
            if result.returncode==0 and result.stdout.strip():
                raise RuntimeError('Camera is still owned by PID(s) '+result.stdout.strip()+'. Stop that program before changing the overlay.')
            if result.returncode not in (0,1):raise RuntimeError('Could not check camera ownership: '+result.stderr)
        yield
    finally:sock.close()

def preflight():
    import runpy
    runpy.run_path(str(ROOT/'board/verify_package.py'),run_name='verify_blocks_package')
    cv=load_cv()
    with exclusive_board():pass
    print('BLOCKS56_PREFLIGHT_OK | OpenCV',cv.__version__,'| no bitstream downloaded',flush=True)

if __name__=='__main__':preflight()
