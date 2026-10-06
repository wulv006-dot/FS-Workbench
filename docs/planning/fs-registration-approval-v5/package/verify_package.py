"""Standalone package verification; stdlib only, relative files, no external reads."""
import hashlib
import json
from pathlib import Path

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    m=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
    expected=set(m['files'])|{'package-manifest.json'}
    actual={str(p.relative_to(root)).replace('\\','/') for p in root.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts}
    assert actual==expected, 'missing or unexpected payload files'
    for name,item in m['files'].items():
        p=root/name;assert not p.is_symlink();b=p.read_bytes()
        assert len(b)==item['bytes'] and hashlib.sha256(b).hexdigest()==item['sha256'],name
    assert m['releaseReady'] is False and m['productionAction'] is False
    print(json.dumps({'files_verified':len(m['files']),'releaseReady':False,'external_reads':False}))
