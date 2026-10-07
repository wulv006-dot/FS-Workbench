"""Repeatable local evidence; never deploys or imports a production module."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOCS = ROOT / 'docs/planning/registration-approval-runtime-v3-20261006'


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(HERE), '-p', 'test_*.py', '-v'],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    (DOCS / 'unit-tests.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    frozen = {}
    baseline = json.loads((HERE / 'frozen-vendor.json').read_text(encoding='utf-8'))
    for path in (HERE / 'vendor').glob('*.py'):
        original = ROOT / 'registration_approval_candidate_v5_20261006' / path.name
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        frozen[path.name] = {'sha256': sha, 'matches_frozen_v5': sha == baseline[path.name],
            'local_original_compared': original.exists()}
        if original.exists():
            frozen[path.name]['matches_frozen_v5'] &= path.read_bytes() == original.read_bytes()
    files = {}
    for path in sorted(HERE.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'at': datetime.now(timezone.utc).isoformat(), 'tests_exit': result.returncode,
        'frozen_vendor': frozen, 'files': files, 'releaseReady': False,
        'production_changed': False, 'real_role_acceptance': False,
        'desktop_only': True, 'mobile_gate': False,
        'independent_review': 'pending', 'linux_runtime_acceptance': 'pending'}
    old = ROOT / 'registration_approval_runtime_20261006'
    baseline_v1 = json.loads((HERE / 'frozen-runtime-v1.json').read_text(encoding='utf-8'))
    report['frozen_runtime_v1_compared'] = old.exists()
    report['frozen_runtime_v1_unchanged'] = all((old / name).is_file() and
        hashlib.sha256((old / name).read_bytes()).hexdigest() == value
        for name,value in baseline_v1.items()) if old.exists() else None
    old_v2 = ROOT / 'registration_approval_runtime_v2_20261006'
    baseline_v2 = json.loads((HERE / 'frozen-runtime-v2.json').read_text(encoding='utf-8'))
    report['frozen_runtime_v2_compared'] = old_v2.exists()
    report['frozen_runtime_v2_unchanged'] = all((old_v2/name).is_file() and
        hashlib.sha256((old_v2/name).read_bytes()).hexdigest()==value
        for name,value in baseline_v2.items()) if old_v2.exists() else None
    (DOCS / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if result.returncode or not all(item['matches_frozen_v5'] for item in frozen.values()) or report['frozen_runtime_v1_unchanged'] is False or report['frozen_runtime_v2_unchanged'] is False:
        raise SystemExit(1)
    print('Synthetic local tests passed; 6 frozen vendor files match v5; releaseReady=false')


if __name__ == '__main__': main()
