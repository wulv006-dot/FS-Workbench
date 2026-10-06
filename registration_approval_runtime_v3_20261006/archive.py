"""Local review ZIP only; no upload, deployment or account data."""
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs/planning/registration-approval-runtime-v3-20261006'


def main():
    subprocess.run([sys.executable, str(ROOT / 'registration_approval_runtime_v3_20261006/qa.py')], check=True)
    payload = {}
    for p in (ROOT / 'registration_approval_runtime_v3_20261006').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:
            payload[p.relative_to(ROOT).as_posix()] = p.read_bytes()
    for name in ('REVIEW.md', 'INTERFACES-MIGRATION.md', 'RECOVERY.md', 'portal-bridge-v2-v3.diff', 'validation.json', 'unit-tests.txt'):
        p = DOCS / name; payload[p.relative_to(ROOT).as_posix()] = p.read_bytes()
    manifest = {name: {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
        for name, content in sorted(payload.items())}
    raw = json.dumps({'files': manifest, 'releaseReady': False}, indent=2).encode()
    (DOCS / 'package-manifest.json').write_bytes(raw)
    target = DOCS / 'FS-registration-runtime-v3-review-20261006.zip'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in sorted(payload.items()): z.writestr(name, content)
        z.writestr('package-manifest.json', raw)
    with tempfile.TemporaryDirectory(prefix='fs-registration-extracted-') as scratch:
        with zipfile.ZipFile(target) as z:
            for name, item in manifest.items():
                if hashlib.sha256(z.read(name)).hexdigest() != item['sha256']: raise ValueError('archive SHA drift')
            z.extractall(scratch)
        check = subprocess.run([sys.executable, str(Path(scratch) / 'registration_approval_runtime_v3_20261006/qa.py')],
            capture_output=True, text=True)
        (DOCS / 'extracted-validation.txt').write_text(check.stdout + check.stderr, encoding='utf-8')
        if check.returncode: raise SystemExit(check.returncode)
    report = {'zip': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'bytes': target.stat().st_size, 'payload_files': len(payload), 'entries': len(payload)+1,
        'extracted_tests_exit': check.returncode, 'production_changed': False, 'releaseReady': False}
    (DOCS / 'package-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__': main()
