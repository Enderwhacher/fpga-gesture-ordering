"""Recover interrupted offline extraction atomically; no app/manifest/PL changes."""
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repair(root='/home/xilinx/jupyter_notebooks'):
    app=(Path(root)/'gesture_order_accel_v4').resolve()
    manifest=json.loads((app/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('release')!='gesture_order_accel_v4':
        raise RuntimeError('Expected the V4 application directory')
    # The unmodified application verification still applies to every critical file.
    for name,expected in manifest['files'].items():
        path=(app/name).resolve()
        if not path.is_relative_to(app) or not path.is_file() or digest(path)!=expected:
            raise RuntimeError('Application file changed; no recovery applied: '+name)
    target=app/'vendor'
    if target.resolve().parent!=app or target.is_symlink():
        raise RuntimeError('Unexpected vendor location; no directory moved')
    marker=target/'installed.json'
    if marker.is_file():
        for name,expected in json.loads(marker.read_text(encoding='utf-8')).items():
            path=(target/name).resolve()
            if not path.is_relative_to(target.resolve()) or not path.is_file() or digest(path)!=expected:
                raise RuntimeError('Existing completed runtime differs: '+name)
        print('V4_RUNTIME_ALREADY_READY',flush=True)
        return target
    # A loaded native library must not be moved under a running kernel.
    for name,module in tuple(sys.modules.items()):
        source=getattr(module,'__file__',None)
        if source:
            try:inside=Path(source).resolve().is_relative_to(target.resolve())
            except (OSError,ValueError):inside=False
            if inside:
                raise RuntimeError('Restart this notebook kernel first; a partial runtime module is loaded: '+name)
    wheels=sorted((app/'wheels').glob('*.whl'))
    if len(wheels)!=8 or not any(p.name.startswith('onnxruntime-1.23.2-') for p in wheels):
        raise RuntimeError('Offline wheel set incomplete; no recovery applied')
    token=str(time.time_ns())
    staging=app/('vendor_staging_'+token)
    if staging.resolve().parent!=app:
        raise RuntimeError('Unexpected staging path')
    staging.mkdir()
    hashes={}
    try:
        print('V4_RUNTIME_RECOVERY_START | keep this cell running; extraction progress follows',flush=True)
        for index,wheel in enumerate(wheels,1):
            print('Wheel',index,'/',len(wheels),wheel.name,flush=True)
            with zipfile.ZipFile(wheel) as archive:
                for info in archive.infolist():
                    if info.is_dir():continue
                    parts=list(Path(info.filename).parts)
                    if not parts or any(part in ('..','') for part in parts):
                        raise RuntimeError('Unsafe wheel member')
                    if parts[0].endswith('.data'):
                        if len(parts)<3 or parts[1] not in ('purelib','platlib'):continue
                        parts=parts[2:]
                    path=staging.joinpath(*parts).resolve()
                    if not path.is_relative_to(staging.resolve()) or parts[0]=='numpy':
                        raise RuntimeError('Unsafe wheel destination')
                    data=archive.read(info)
                    if path.exists() and path.read_bytes()!=data:
                        raise RuntimeError('Wheel collision: '+info.filename)
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(data)
                    hashes[path.relative_to(staging).as_posix()]=hashlib.sha256(data).hexdigest()
                    if len(hashes)%200==0:
                        print('Extracted',len(hashes),'files',flush=True)
        # Verify the finished staging tree before activating it.
        for name,expected in hashes.items():
            if digest(staging/name)!=expected:raise RuntimeError('Staging file write verification failed: '+name)
        temporary=staging/'installed.json.tmp'
        temporary.write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
        temporary.replace(staging/'installed.json')
        backup=None
        if target.exists():
            backup=app/('vendor_incomplete_'+token)
            if backup.resolve().parent!=app or target.resolve().parent!=app:
                raise RuntimeError('Unexpected backup target')
            target.rename(backup)
        staging.rename(target)
        logs=app/'logs';logs.mkdir(exist_ok=True)
        (logs/'runtime_recovery.json').write_text(json.dumps(dict(
            passed=True,files=len(hashes),vendor=str(target),backup=str(backup) if backup else None,
            app_source_changed=False,manifest_changed=False,hardware_loaded=False),indent=2)+'\n',encoding='utf-8')
        print('V4_RUNTIME_RECOVERED:',target,flush=True)
        if backup:print('Incomplete directory preserved:',backup,flush=True)
        return target
    except BaseException as error:
        logs=app/'logs';logs.mkdir(exist_ok=True)
        (logs/'runtime_recovery_failure.json').write_text(json.dumps(dict(
            error=repr(error),traceback=traceback.format_exc(),staging=str(staging)),indent=2)+'\n',encoding='utf-8')
        print('Recovery stopped; incomplete staging preserved at',staging,flush=True)
        raise
