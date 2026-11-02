"""187 shadow controller setup, with a new capability-limited FC identity. Preview first."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_collection_node import code_directories, public_key, read_bundle, write_exact

CODE = Path('/opt/fs-fc-control')
ACCESS = Path('/var/lib/fc27-cloud/collection-access')
EXPECTED_HOST_KEY = 'SHA256:75r9ZQ1NAHwfrmKnFQOMRXiJzQm7aqfh/ET8lXMEXhk'


def host_key(value):
    key = public_key(value)
    raw = base64.b64decode(key.split()[1], validate=True)
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
    if fingerprint != EXPECTED_HOST_KEY:
        raise ValueError('183_trusted_host_key_mismatch')
    return key


def prepare(bundle, digest, host_key_file, worker_digest, apply=False):
    if os.name != 'posix' or os.geteuid() != 0 or socket.gethostname() != 'play187':
        raise ValueError('verified_187_root_entry_required')
    files = read_bundle(bundle, digest, 'control')
    if Path(host_key_file).is_symlink() or Path(host_key_file).stat().st_size > 2048:
        raise ValueError('host_key_transfer_invalid')
    key = host_key(Path(host_key_file).read_text())
    if not re.fullmatch('[a-f0-9]{64}', worker_digest):
        raise ValueError('worker_digest_invalid')
    private = ACCESS / 'id_ed25519'
    public = ACCESS / 'id_ed25519.pub'
    receipt = ACCESS / 'setup.json'
    known = ACCESS / 'known_hosts'
    config = dict(host='172.18.108.183', user='fs-fc-collector', identity_file=str(private),
                  known_hosts=str(known), worker_digest=worker_digest)
    expected = {CODE / 'code' / name: body for name, body in files.items()}
    expected.update({known: ('fs-fc-183 ' + key + '\n').encode(),
                     ACCESS / 'access.json': (json.dumps(config, sort_keys=True) + '\n').encode()})
    for path in (CODE, ACCESS, receipt, private, public):
        if path.is_symlink():
            raise ValueError('control_path_link_invalid')
    if receipt.exists() and (receipt.stat().st_uid != 0 or receipt.stat().st_nlink != 1
                            or receipt.stat().st_size > 16384 or stat.S_IMODE(receipt.stat().st_mode) != 0o600):
        raise ValueError('control_receipt_permissions_invalid')
    old = json.loads(receipt.read_text()) if receipt.exists() else None
    if not old and (CODE.exists() or ACCESS.exists()):
        raise ValueError('control_initial_target_conflict')
    if old and (old.get('bundle_sha256') != digest or old.get('worker_digest') != worker_digest):
        raise ValueError('control_setup_requires_reconciliation')
    for path, body in expected.items():
        if path.is_symlink() or path.exists() and (not path.is_file() or path.read_bytes() != body):
            raise ValueError('control_existing_target_conflict')
    result = dict(phase='preview', apply=apply, bundle_sha256=digest, worker_digest=worker_digest,
                  code_root=str(CODE), access_root=str(ACCESS), public_key_file=str(public),
                  host_key_verified=True, business_configuration_changes=False, source_requests=0)
    if not apply:
        return result
    ACCESS.mkdir(mode=0o700, parents=True, exist_ok=True)
    if ACCESS.stat().st_uid != 0:
        raise ValueError('control_access_owner_invalid')
    ACCESS.chmod(0o700)
    if not old:
        write_exact(receipt, (json.dumps(dict(result, phase='started'), sort_keys=True) + '\n').encode(), 0o600)
    if not private.exists():
        if public.exists():
            raise ValueError('control_identity_requires_reconciliation')
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'fs-fc-187-to-183', '-f', str(private)],
                       stdin=subprocess.DEVNULL, check=True, capture_output=True)
    info = private.stat()
    if info.st_uid != 0 or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('control_identity_permissions_invalid')
    derived = subprocess.check_output(['ssh-keygen', '-y', '-f', str(private)], stdin=subprocess.DEVNULL, text=True)
    public_line = public_key(derived)
    if public.exists() and public_key(public.read_text()) != public_line:
        raise ValueError('control_identity_public_mismatch')
    if not public.exists():
        write_exact(public, (public_line + '\n').encode(), 0o644)
    code_directories(CODE)
    if CODE.stat().st_uid != 0:
        raise ValueError('control_code_owner_invalid')
    for path, body in expected.items():
        write_exact(path, body, 0o444 if path.is_relative_to(CODE / 'code') else 0o600 if path.name == 'access.json' else 0o644)
        os.chown(path, 0, 0)
    result.update(phase='prepared', identity_ready=True)
    descriptor, name = tempfile.mkstemp(prefix='.setup-', dir=str(ACCESS))
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(result, stream, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(name, receipt)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('sha256')
    parser.add_argument('host_key_file', type=Path)
    parser.add_argument('worker_digest')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.bundle, args.sha256, args.host_key_file, args.worker_digest, args.apply), sort_keys=True))
