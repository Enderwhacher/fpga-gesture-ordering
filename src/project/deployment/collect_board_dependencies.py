"""Read-only collection of the existing board runtime; no camera/Overlay/DMA access."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import platform
import sys
import zipfile


def run(root='/home/xilinx/jupyter_notebooks'):
    root=Path(root).resolve()
    output=root/'v4_board_dependencies.zip'
    folders=('gesture_runtime_cv410','gesture_assets','gesture4_model_v2','gesture_order_demo_v2/assets')
    if not (root/'gesture_runtime_cv410').is_dir():
        raise RuntimeError('Exact deployed gesture_runtime_cv410 folder not found; do not substitute another build silently.')
    versions={}
    for name in ('pynq','numpy','opencv-python','opencv-python-headless','onnxruntime','ipykernel','jupyterlab','cffi','protobuf','flatbuffers'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    info=dict(scope='Read-only runtime snapshot, no hardware or camera access',
        python=sys.version,executable=sys.executable,machine=platform.machine(),kernel=platform.release(),
        libc=platform.libc_ver(),distribution_versions=versions,reported_image_name='pynq_zu_2022_10_07.img',
        image_name_source='user report; full SD image not included')
    runtime=root/'gesture_runtime_cv410'
    if 'cv2' not in sys.modules:sys.path.insert(0,str(runtime))
    import cv2
    info.update(opencv=cv2.__version__,opencv_file=cv2.__file__)
    info['opencv_path_matches_collected_runtime']=Path(cv2.__file__).resolve().is_relative_to(runtime)
    if not info['opencv_path_matches_collected_runtime']:
        raise RuntimeError('Another cv2 module is cached. Run in a fresh Python 3 kernel; this script has not modified hardware.')
    fingerprints={}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for folder in folders:
            base=(root/folder).resolve()
            if not base.exists():
                info.setdefault('missing_folders',[]).append(folder)
                continue
            if not base.is_relative_to(root):raise RuntimeError('Unexpected folder target')
            for path in sorted(base.rglob('*')):
                if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'):
                    continue
                if not path.resolve().is_relative_to(base):raise RuntimeError('External symlink, not followed: '+str(path))
                name=path.relative_to(root).as_posix()
                archive.write(path,name)
                h=hashlib.sha256()
                with path.open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
                fingerprints[name]=h.hexdigest()
                if len(fingerprints)%100==0:print('Collected',len(fingerprints),'files',flush=True)
        archive.writestr('environment.json',json.dumps(info,indent=2))
        archive.writestr('opencv_build_info.txt',cv2.getBuildInformation())
        archive.writestr('files_sha256.json',json.dumps(fingerprints,indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise RuntimeError('Snapshot ZIP failed CRC verification')
    print('BOARD_DEPENDENCIES_READY:',output,flush=True)
    print('No system package installed; no FPGA or camera access.',flush=True)
    try:
        from IPython.display import HTML,display
        from urllib.parse import quote
        display(HTML('<a href="/files/'+quote(output.relative_to(root).as_posix())+'" download>下载 v4_board_dependencies.zip</a>'))
    except ImportError:pass
    return output


if __name__=='__main__':run()
