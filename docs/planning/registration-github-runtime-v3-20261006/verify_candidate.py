"""Check exact reviewed runtime payload bytes; no execution or deployment."""
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / 'docs/planning/registration-approval-runtime-v3-20261006/package-manifest.json'


def main():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert manifest['releaseReady'] is False and len(manifest['files']) == 37
    for name, item in manifest['files'].items():
        path = PurePosixPath(name)
        assert not path.is_absolute() and '..' not in path.parts and '\\' not in name
        assert name.startswith(('registration_approval_runtime_v3_20261006/',
                                'docs/planning/registration-approval-runtime-v3-20261006/'))
        local = ROOT / name
        assert not local.is_symlink(), name
        data = local.read_bytes()
        assert len(data) == item['bytes'], name
        assert hashlib.sha256(data).hexdigest() == item['sha256'], name
    frozen = ROOT / 'registration_approval_runtime_v3_20261006/frozen-vendor.json'
    for name, sha in json.loads(frozen.read_text(encoding='utf-8')).items():
        data = (frozen.parent / 'vendor' / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha, name
    print('37 reviewed payload files and 6 frozen vendor hashes match; releaseReady=false')


if __name__ == '__main__':
    main()
