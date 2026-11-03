"""Install offline wheels into this app only; never change system NumPy/PYNQ."""
import hashlib
import json
import platform
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_app():
    manifest = json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (HERE/name).resolve()
        if not path.is_relative_to(HERE) or not path.is_file() or digest(path) != expected:
            raise RuntimeError('App package mismatch: '+name)
    return manifest


def prepare(root='/home/xilinx/jupyter_notebooks'):
    verify_app()
    if platform.system() != 'Linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        raise RuntimeError('Run on PYNQ-ZU, not on the laptop.')
    if sys.version_info[:2] != (3, 10):
        raise RuntimeError('Offline runtime targets the verified Python 3.10 board image.')
    libc, version = platform.libc_ver()
    if libc != 'glibc' or tuple(map(int, version.split('.')[:2])) < (2, 27):
        raise RuntimeError('ONNX Runtime wheel requires glibc >= 2.27.')
    target = HERE/'vendor'
    marker = target/'installed.json'
    if marker.exists():
        for name, expected in json.loads(marker.read_text(encoding='utf-8')).items():
            if digest(target/name) != expected:
                raise RuntimeError('Local runtime changed; reinstall in a fresh directory: '+name)
    else:
        if target.exists():
            raise RuntimeError('Incomplete local runtime. Rename vendor to vendor_old, then retry.')
        target.mkdir()
        hashes = {}
        for wheel in sorted((HERE/'wheels').glob('*.whl')):
            with zipfile.ZipFile(wheel) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    parts = list(Path(info.filename).parts)
                    if any(p in ('..', '') for p in parts):
                        raise RuntimeError('Unsafe wheel member')
                    if parts[0].endswith('.data'):
                        if len(parts) < 3 or parts[1] not in ('purelib', 'platlib'):
                            continue
                        parts = parts[2:]
                    path = target.joinpath(*parts).resolve()
                    if not path.is_relative_to(target.resolve()) or parts[0] == 'numpy':
                        raise RuntimeError('Invalid wheel installation target')
                    data = archive.read(info)
                    if path.exists() and path.read_bytes() != data:
                        raise RuntimeError('Wheel file collision: '+str(path))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    hashes[path.relative_to(target).as_posix()] = hashlib.sha256(data).hexdigest()
        marker.write_text(json.dumps(hashes, indent=2)+'\n', encoding='utf-8')
    if 'onnxruntime' in sys.modules:
        loaded = Path(sys.modules['onnxruntime'].__file__).resolve()
        if not loaded.is_relative_to(target.resolve()):
            raise RuntimeError('Another ONNX Runtime is cached; restart this notebook kernel.')
    sys.path.insert(0, str(target))
    import numpy as np
    import onnxruntime as ort
    if ort.__version__ != '1.23.2':
        raise RuntimeError('Unexpected ONNX Runtime version')
    cv_path = Path(root)/'gesture_runtime_cv410'
    if 'cv2' not in sys.modules:
        sys.path.insert(0, str(cv_path))
    from board_server import load_cv
    cv = load_cv(root)
    print('V4_RUNTIME_READY | ORT', ort.__version__, '| NumPy', np.__version__, '| OpenCV', cv.__version__)
    print('Runtime isolated in', target, '| system packages and bitstreams unchanged')
    return dict(onnxruntime=ort.__version__, numpy=np.__version__, opencv=cv.__version__)
