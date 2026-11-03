"""Syntax and deployment notebook checks; does not run hardware code."""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
count=0
for folder in ('blocks16_driver','board','tests','tools','source'):
    for path in (ROOT/folder).glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'),filename=str(path));count+=1
ast.parse((ROOT/'blocks16_runtime.py').read_text(encoding='utf-8'));count+=1
nb=json.loads((ROOT/'00_validate_blocks56.ipynb').read_text(encoding='utf-8'))
assert nb['metadata']['kernelspec']['name']=='python3'
for cell in nb['cells']:
    if cell['cell_type']=='code':ast.parse(''.join(cell['source']))
assert len([c for c in nb['cells'] if c['cell_type']=='code'])==3
result={'passed':True,'python_files':count,'notebook_code_cells':3,'scope':'Python syntax and sequential deployment notebook checks; no hardware run'}
(ROOT/'reports/source_checks.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
