"""Optional same-board recovery of historical V4 evidence; not a new board test."""
from pathlib import Path
import hashlib
import json
import zipfile


def restore(root='/home/xilinx/jupyter_notebooks'):
    root=Path(root);app=root/'gesture_order_accel_v4'
    package=root/'validated_report_v4.zip'
    existing=list((app/'results').glob('v4_*/report.json'))
    if existing:
        print('Existing board reports preserved. No historical report restored.')
        return False
    with zipfile.ZipFile(package) as archive:
        report=json.loads(archive.read('report.json'))
    current=hashlib.sha256((app/'manifest.json').read_bytes()).hexdigest()
    if report['package_manifest_sha256']!=current or not report['passed']:
        raise RuntimeError('Historical report does not match this exact app build')
    if report['selected_config']!='serial_cv1_t3':raise RuntimeError('Unexpected frozen config')
    target=app/'results/v4_95d5373fa6ae/report.json';target.parent.mkdir(parents=True)
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (target.parent/'historical_restore_notice.json').write_text(json.dumps(dict(
        historical_evidence=True,new_board_test=False,
        use='Same physical board/image recovery only; on a new board run full validation first.'),indent=2)+'\n',encoding='utf-8')
    print('HISTORICAL_V4_REPORT_RESTORED. This is not a new board validation.')
    return True


if __name__=='__main__':restore()
