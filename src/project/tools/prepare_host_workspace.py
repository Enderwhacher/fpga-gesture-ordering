"""Create a separate complete layout for the archived host regressions."""
import argparse
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def prepare(destination,root=ROOT):
    root=Path(root).resolve();destination=Path(destination).resolve()
    if destination==root or destination.is_relative_to(root):
        raise RuntimeError('Choose a separate empty workspace outside the handoff directory')
    if destination.exists() and any(destination.iterdir()):raise RuntimeError('Destination must be empty; nothing overwritten')
    destination.mkdir(parents=True,exist_ok=True)
    shutil.copytree(root/'software/board/gesture_order_accel_v4',destination/'gesture_order_accel_v4')
    shutil.copytree(root/'hardware/gesture_block_accel_v2',destination/'gesture_block_accel_v2')
    shutil.copytree(root/'reference/v3_baseline',destination/'gesture_order_accel_v3')
    fixture=destination/'tmp/v3_local_root';fixture.mkdir(parents=True)
    for name in ('gesture_assets','gesture4_model_v2'):
        shutil.copytree(root/'board_assets'/name,fixture/name)
    print('HOST_WORKSPACE_READY:',destination)
    print('Run tests with the documented host Python dependencies. PL is replaced by a CPU reference in these tests.')
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();prepare(args.destination)
