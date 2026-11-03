"""Repair only V3's mutable-notebook manifest entry; preserve benchmark evidence."""
import copy
import hashlib
import json
from pathlib import Path

ORIGINAL_MANIFEST_SHA = '5804bd043fddfde1b1a01c03385c838f008091defd286cb43b5b770398ad063e'
NOTEBOOK = '00_start_v3.ipynb'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def repair(report, root='/home/xilinx/jupyter_notebooks'):
    app = Path(root)/'gesture_order_accel_v3'
    path = app/'manifest.json'
    original_bytes = path.read_bytes()
    manifest = json.loads(original_bytes)
    already_fixed = manifest.get('integrity_revision') == 'notebook_output_fix_v1'
    if already_fixed:
        if manifest.get('previous_manifest_sha256') != ORIGINAL_MANIFEST_SHA or NOTEBOOK in manifest['files']:
            raise RuntimeError('Unexpected repair provenance. Export logs for review.')
        backup = app/'logs/manifest_before_notebook_fix.json'
        if not backup.is_file() or sha(backup.read_bytes()) != ORIGINAL_MANIFEST_SHA:
            raise RuntimeError('Original manifest backup missing or changed')
        expected = json.loads(backup.read_bytes())
        expected['files'].pop(NOTEBOOK)
        expected.update(mutable_files=[NOTEBOOK], integrity_revision='notebook_output_fix_v1',
                        previous_manifest_sha256=ORIGINAL_MANIFEST_SHA)
        if manifest != expected:
            raise RuntimeError('Manifest contains other changes')
    elif sha(original_bytes) != ORIGINAL_MANIFEST_SHA:
        raise RuntimeError('This repair targets the original V3 package only. Export logs for review.')

    # Only this notebook is mutable. All executable files, models/samples and wheels
    # must still match the original release before any repair can take place.
    for name, expected in manifest['files'].items():
        if name == NOTEBOOK:
            continue
        source = (app/name).resolve()
        if not source.is_relative_to(app.resolve()) or not source.is_file() or sha(source.read_bytes()) != expected:
            raise RuntimeError('Another file changed; no repair applied: '+name)
    if not isinstance(report, dict) or not report.get('passed') or report.get('kernel_restart_required'):
        raise RuntimeError('Successful V3 benchmark required; no repair applied.')
    current_sha = sha(original_bytes)
    if report.get('package_manifest_sha256') not in (ORIGINAL_MANIFEST_SHA, current_sha):
        raise RuntimeError('Benchmark belongs to another package; no repair applied.')

    logs = app/'logs'
    logs.mkdir(exist_ok=True)
    # Keep the on-disk numeric/benchmark reports untouched. Preserve this exact
    # in-memory report too, before deriving a manifest-policy-migrated copy.
    evidence = logs/'v3_report_before_notebook_fix.json'
    if not evidence.exists():
        evidence.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    if not already_fixed:
        backup = logs/'manifest_before_notebook_fix.json'
        if backup.exists() and backup.read_bytes() != original_bytes:
            raise RuntimeError('Conflicting backup; no repair applied.')
        backup.write_bytes(original_bytes)
        manifest['files'].pop(NOTEBOOK)
        manifest.update(mutable_files=[NOTEBOOK], integrity_revision='notebook_output_fix_v1',
                        previous_manifest_sha256=ORIGINAL_MANIFEST_SHA)
        payload = json.dumps(manifest, indent=2)+'\n'
        temporary = path.with_suffix('.repair_tmp')
        temporary.write_text(payload, encoding='utf-8')
        temporary.replace(path)
    new_sha = sha(path.read_bytes())
    result = copy.deepcopy(report)
    result['package_manifest_sha256'] = new_sha
    result['notebook_integrity_repair'] = dict(
        previous_manifest_sha256=ORIGINAL_MANIFEST_SHA, current_manifest_sha256=new_sha,
        policy='Notebook outputs editable; all other original file hashes verified unchanged.',
        computation_changed=False, benchmark_rerun=False)
    (logs/'notebook_check_fix.json').write_text(json.dumps(result['notebook_integrity_repair'], indent=2)+'\n', encoding='utf-8')
    print('V3_NOTEBOOK_CHECK_FIXED')
    print('All original executable/sample/wheel hashes verified. Existing benchmark preserved.')
    print('Continue the server-start cell; no kernel restart or benchmark rerun needed.')
    return result
