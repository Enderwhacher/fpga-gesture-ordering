"""Install isolated V4 final candidate without touching PL/system packages/old apps."""
from pathlib import Path
import hashlib,json,zipfile
ROOT=Path('/home/xilinx/jupyter_notebooks')
ARCHIVE=ROOT/'gesture_order_accel_v4_r1.zip'
EXPECTED='861dc87c22a27077d2752208e5e6c069f607a08723f8f91b212a8298a2b0888e'
if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()!=EXPECTED:raise RuntimeError('ZIP mismatch; upload original complete ZIP again.')
target=ROOT/'gesture_order_accel_v4'
with zipfile.ZipFile(ARCHIVE) as archive:
    if archive.testzip() is not None:raise RuntimeError('ZIP CRC failed')
    if target.exists():
        manifest=json.loads(archive.read('gesture_order_accel_v4/manifest.json'))
        for n,expected in manifest['files'].items():
            p=(target/n).resolve()
            if not p.is_relative_to(target.resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
                raise RuntimeError('Existing V4 differs. Rename it to preserve logs before installing. Nothing overwritten.')
    else:
        for info in archive.infolist():
            if not (ROOT/info.filename).resolve().is_relative_to(target.resolve()):raise RuntimeError('Unsafe ZIP member')
        target.mkdir()
        for info in archive.infolist():
            p=(ROOT/info.filename).resolve()
            if info.is_dir():p.mkdir(parents=True,exist_ok=True)
            else:
                p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(archive.read(info))
for name in ('logs','results'):(target/name).mkdir(exist_ok=True)
print('V4_APP_INSTALLED:',target)
print('Open 01_one_run_v4.ipynb in a fresh Python 3 kernel (recommended).')
