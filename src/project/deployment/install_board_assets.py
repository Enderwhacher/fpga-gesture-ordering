"""Restore only matching original model/assets. No PL access; never replace a model."""
from pathlib import Path
import hashlib
import json
import zipfile


def install(root='/home/xilinx/jupyter_notebooks'):
    root=Path(root).resolve()
    package=root/'board_assets_v4.zip'
    with zipfile.ZipFile(package) as archive:
        manifest=json.loads(archive.read('assets_manifest.json'))
        keep=[];write=[]
        for name,expected in manifest['files'].items():
            path=(root/name).resolve()
            if not path.is_relative_to(root):raise RuntimeError('Unsafe archive path')
            data=archive.read(name)
            if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Asset archive damaged: '+name)
            if path.exists():
                if name.startswith('gesture_order_demo_v2/assets/'):
                    keep.append(name) # preserve the board's original full-resolution food images
                elif hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                    raise RuntimeError('Existing model/runtime differs. Nothing written: '+name)
            else:write.append((path,data))
        for path,data in write:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    print('BOARD_ASSETS_READY | restored',len(write),'| existing food images preserved',len(keep))
    return dict(restored=len(write),existing_food_images_preserved=keep)


if __name__=='__main__':install()
