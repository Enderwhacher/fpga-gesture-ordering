"""Local-only Vivado build/resume, audit and release. No board access.

Use after HLS and direct RTL checks. Existing projects are only resumed when
their IP repository is byte-for-byte identical to the packaged IP archive.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vivado',type=Path,default=Path('E:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat'))
    parser.add_argument('--jobs',type=int,choices=range(1,17),default=4)
    args=parser.parse_args();work=ROOT.parent/'b3w';repo=work/'ip_repo';project=work/'gblock/gblock.xpr'
    with zipfile.ZipFile(ROOT/'hls/ip/gesture_blocks56_axis.zip') as z:
        for name in z.namelist():
            path=(repo/name).resolve()
            if not path.is_relative_to(repo.resolve()):raise RuntimeError('Invalid IP archive path')
            if not name.endswith('/') and project.exists():
                if not path.is_file() or hashlib.sha256(path.read_bytes()).digest()!=hashlib.sha256(z.read(name)).digest():
                    raise RuntimeError('Existing Vivado project uses different IP. Build in a new workspace instead of resuming stale hardware.')
        if not project.exists():repo.mkdir(parents=True,exist_ok=True);z.extractall(repo)
    reports=ROOT/'vivado/reports';reports.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(args.vivado),'-mode','batch','-log',str(reports/'build.log'),'-journal',str(reports/'build.jou'),
                    '-source',str(ROOT/'vivado/build.tcl'),'-tclargs','bitstream',str(args.jobs)],cwd=ROOT,check=True)
    for name in ('audit_hwh.py','finalize_release.py'):
        subprocess.run([sys.executable,str(ROOT/'tools'/name)],cwd=ROOT,check=True)
if __name__=='__main__':main()
