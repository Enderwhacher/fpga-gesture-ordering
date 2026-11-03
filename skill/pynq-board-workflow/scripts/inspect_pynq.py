"""Read-only environment and optional BIT/HWH inventory; never accesses PL."""
import argparse
import glob
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def inventory(bit=None):
    versions = {}
    for name in ('pynq', 'numpy', 'opencv-python', 'opencv-python-headless', 'onnxruntime'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    report = {
        'hardware_accessed': False,
        'python': sys.version.split()[0], 'executable': sys.executable,
        'os': platform.system(), 'release': platform.release(),
        'architecture': platform.machine(), 'distributions': versions,
        'camera_nodes': sorted(glob.glob('/dev/video*')) if sys.platform.startswith('linux') else [],
        'notes': ['Missing distribution metadata does not prove a module is absent.',
                  'Static HWH inspection does not prove board compatibility or loaded hardware.'],
    }
    if bit is not None:
        bit = Path(bit).expanduser().resolve()
        if bit.suffix.lower() != '.bit':
            raise ValueError('Expected a .bit path')
        hwh = bit.with_suffix('.hwh')
        for path in (bit, hwh):
            if not path.is_file():
                raise FileNotFoundError(str(path))
        if hwh.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('HWH exceeds the inventory size limit')
        xml_data = hwh.read_bytes()
        if b'<!DOCTYPE' in xml_data.upper() or b'<!ENTITY' in xml_data.upper():
            raise ValueError('DTD/entity declarations are not accepted')
        tree = ET.fromstring(xml_data)
        modules, ranges = [], []
        for element in tree.iter():
            tag = element.tag.rsplit('}', 1)[-1]
            if tag == 'MODULE':
                modules.append(dict(element.attrib))
            elif tag == 'MEMRANGE':
                ranges.append(dict(element.attrib))
        report['overlay'] = {
            'bit': str(bit), 'hwh': str(hwh),
            'bit_sha256': digest(bit), 'hwh_sha256': digest(hwh),
            'modules': modules, 'memory_ranges': ranges,
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bit', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.bit)
    # Exclusive creation prevents replacing existing evidence.
    with args.output.open('x', encoding='utf-8') as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write('\n')
    print('INVENTORY_WRITTEN:', args.output)


if __name__ == '__main__':
    main()
