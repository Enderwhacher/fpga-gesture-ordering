"""Extract the exact verified hardware package; no Overlay or DMA calls."""
from pathlib import Path
import hashlib
import zipfile

EXPECTED='8fbe457d717db78673674c90edd92247765e7b70c749dd7c779de329a4242100'


def install(root='/home/xilinx/jupyter_notebooks'):
    root=Path(root).resolve();target=root/'gesture_block_accel_v2'
    package=root/'gesture_blocks56_pw16_hw_v2.zip'
    if hashlib.sha256(package.read_bytes()).hexdigest()!=EXPECTED:raise RuntimeError('Hardware ZIP hash mismatch')
    pending=[]
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            if info.is_dir():continue
            path=(root/info.filename).resolve()
            if not path.is_relative_to(target.resolve()):raise RuntimeError('Unsafe hardware archive member')
            data=archive.read(info)
            if path.exists():
                if path.read_bytes()!=data:raise RuntimeError('Existing hardware file differs; nothing written: '+info.filename)
            else:pending.append((path,data))
        for path,data in pending:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    print('HARDWARE_FILES_READY:',target,'| new files',len(pending),'| FPGA not loaded')
    return len(pending)


if __name__=='__main__':install()
