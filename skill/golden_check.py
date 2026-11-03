"""Generic CPU/accelerator golden-array comparison. No board dependency."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def compare(reference,actual,atol=1e-4,rtol=1e-4):
    if atol<0 or rtol<0:raise ValueError('Tolerances must be nonnegative')
    reference=np.asarray(reference);actual=np.asarray(actual)
    if reference.shape!=actual.shape:raise RuntimeError('Shape mismatch')
    if reference.dtype.kind not in 'fiu' or actual.dtype.kind not in 'fiu':raise RuntimeError('Numeric real arrays required')
    if not np.isfinite(reference).all() or not np.isfinite(actual).all():raise RuntimeError('Nonfinite values')
    error=np.abs(actual.astype(np.float64)-reference.astype(np.float64))
    allowed=atol+rtol*np.abs(reference.astype(np.float64))
    passed=not bool(np.any(error>allowed))
    return dict(passed=passed,shape=list(reference.shape),max_abs_error=float(error.max()) if error.size else 0.,
                atol=atol,rtol=rtol)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--actual',type=Path,required=True)
    parser.add_argument('--atol',type=float,default=1e-4)
    parser.add_argument('--rtol',type=float,default=1e-4)
    args=parser.parse_args()
    result=compare(np.load(args.reference,allow_pickle=False),np.load(args.actual,allow_pickle=False),args.atol,args.rtol)
    result.update(reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                  actual_sha256=hashlib.sha256(args.actual.read_bytes()).hexdigest())
    print(json.dumps(result,indent=2))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
