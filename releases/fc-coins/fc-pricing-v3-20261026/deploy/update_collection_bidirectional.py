"""Pinned bidirectional collection-role update; reuse the original atomic swap and rollback. Preview default; no source or business task dispatch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone

if not __debug__:
    raise ValueError('validation_checks_required')

OLD = {'node':'55eeff178d37e4747c1fe5b4f3d49b9a258b4d5cf7eeb75a6cbf6493cba5b14d',
       'control':'53e1e8fa7719d57e35a7dc33a200948827ef06e8479e70922379479834f913ec'}
NEW = {'node':'2360f21883ae0a823810b44255ca7e31808c7d942bdaff8c22c0ff9f09f9dabd',
       'control':'1236c157e31415ac60b404e980c03adf631bbdc5bb8fa1e1e4236502c2f0928a'}
WORKER = '49ac963bb2744c3f54ed0383d6570781ef709c4eb9374a4e850e3cab77dd5085'
OLD_WORKER = '0665b89d7d6e074f1a06c10672c1f2f4c5d55ea86bea6b214bb1e434a0fc5a7e'
OLD_NAMES = {'node':'node-3f4aa53f.zip','control':'control-6d395242.zip'}
STAGE = Path('/var/tmp/fs-fc-bidirectional-20261107')
CHANGED = {role:{'fc_collection/' + name for name in ('contracts.py','public_sources.py','adapters.py','worker.py')} | {'manifest.json'}
           | ({'fc_collection/client.py'} if role == 'control' else set()) for role in ('node','control')}


def read_bundle(path, digest, role):
    path=Path(path)
    assert role in OLD and not path.is_symlink() and path.stat().st_size<=8388608
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    node={'fc_collection/'+n for n in ('__init__.py','contracts.py','worker.py','adapters.py','protocol.py','public_sources.py','server.py')}|{'entry.py','manifest.json'}
    control={'fc_collection/'+n for n in ('__init__.py','contracts.py','coordinator.py','protocol.py','ssh_client.py','public_sources.py','pilot.py','client.py','adapters.py','worker.py','failover.py')}|{'entry.py','manifest.json'}
    allowed=node if role=='node' else control
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist()
        assert len(members)==len(allowed) and {m.filename for m in members}==allowed
        assert sum(m.file_size for m in members)<=4194304
        assert all(m.file_size<=1048576 and not stat.S_ISLNK(m.external_attr>>16) for m in members)
        files={m.filename:archive.read(m) for m in members}
    manifest=json.loads(files['manifest.json'])
    assert manifest['schema_version']==1 and manifest['role']==('limited_fc_collector' if role=='node' else 'fc_collection_controller')
    assert manifest['credentials']==[] and manifest['business_runtime'] is False and manifest['production_consume'] is False
    assert manifest['sources']==['ArabUT'] and set(manifest['sha256'])==allowed-{'manifest.json'}
    assert all(hashlib.sha256(files[k]).hexdigest()==v for k,v in manifest['sha256'].items())
    return files


def atomic(path, body, mode):
    fd, name = tempfile.mkstemp(prefix='.bidirectional-', dir=str(path.parent))
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(name, mode)
    os.replace(name, path)

def update(bundle, digest, worker_digest, apply):
    assert os.geteuid() == 0
    host = socket.gethostname()
    role = {'FSHTUS01': 'node', 'play187': 'control'}[host]
    assert digest == NEW[role] and worker_digest == WORKER
    root = Path('/opt/fs-fc-collector' if role == 'node' else '/opt/fs-fc-control')
    previous = read_bundle(STAGE / OLD_NAMES[role], OLD[role], role)
    files = read_bundle(bundle, digest, role)
    assert {name for name in files if files[name] != previous[name]} == CHANGED[role]
    receipt = root/'bidirectional-update-20261107.json'
    reference = files if receipt.exists() else previous
    expected = root / 'code'
    assert not root.is_symlink() and root.stat().st_uid == 0
    assert not expected.is_symlink() and expected.is_dir()
    actual = set()
    for path in expected.rglob('*'):
        assert not path.is_symlink() and path.stat().st_uid == 0
        if path.is_file():
            actual.add(path.relative_to(expected).as_posix())
            assert path.read_bytes() == reference[path.relative_to(expected).as_posix()]
    assert actual == set(reference)
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        assert saved['phase']=='updated' and saved['new_bundle_sha256']==digest and saved['worker_digest']==WORKER
        if role=='control':
            access=Path('/var/lib/fc27-cloud/collection-access/access.json')
            assert not access.is_symlink() and access.stat().st_uid==0 and access.stat().st_nlink==1
            assert stat.S_IMODE(access.stat().st_mode)==0o600 and json.loads(access.read_text())['worker_digest']==WORKER
        return dict(saved, phase='already_updated')
    backup = root / 'code-before-bidirectional-20261107'
    assert not backup.exists() and not backup.is_symlink()
    failed = root / ('code-bidirectional-failed-' + uuid.uuid4().hex)
    assert not failed.exists() and not failed.is_symlink()
    old_config = None
    access = Path('/var/lib/fc27-cloud/collection-access/access.json')
    if role == 'control':
        assert not access.is_symlink() and access.stat().st_uid == 0 and access.stat().st_nlink == 1
        assert stat.S_IMODE(access.stat().st_mode) == 0o600
        old_config = access.read_bytes()
        config = json.loads(old_config)
        assert config['worker_digest'] == OLD_WORKER
        config['worker_digest'] = worker_digest
    else:
        assert hashlib.sha256(files['manifest.json']).hexdigest() == worker_digest
        assert not list(Path('/var/lib/fs-fc-collector/spool').iterdir())
    result = dict(host=host, role=role, old_bundle_sha256=OLD[role], new_bundle_sha256=digest,
                  worker_digest=worker_digest, phase='preview')
    if not apply:
        return result
    candidate = Path(tempfile.mkdtemp(prefix='.code-bidirectional-', dir=str(root)))
    candidate.chmod(0o755)
    for relative, body in files.items():
        target = candidate / relative
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        target.parent.chmod(0o755)
        target.write_bytes(body)
        target.chmod(0o444)
    switched = False
    try:
        if role == 'node':
            subprocess.run(['systemctl', 'stop', 'fs-fc-collector.service'], check=True)
        expected.rename(backup)
        candidate.rename(expected)
        switched = True
        if role == 'control':
            atomic(access, (json.dumps(config, sort_keys=True) + '\n').encode(), 0o600)
        else:
            subprocess.run(['systemctl', 'start', 'fs-fc-collector.service'], check=True)
            health = None
            for _ in range(50):
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                        connection.settimeout(2)
                        connection.connect('/run/fs-fc-collector/worker.sock')
                        connection.sendall(b'{"method":"health"}\n')
                        with connection.makefile('rb') as response:
                            health = json.loads(response.readline(65537))
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    time.sleep(.1)
            assert health and health['worker_digest'] == worker_digest and health['uid'] == 999
        result.update(phase='updated', backup=str(backup), updated_at=datetime.now(timezone.utc).isoformat())
        atomic(receipt, (json.dumps(result, sort_keys=True) + '\n').encode(), 0o600)
        return result
    except BaseException:
        if switched:
            if role == 'node':
                subprocess.run(['systemctl', 'stop', 'fs-fc-collector.service'], check=True)
            expected.rename(failed)
            backup.rename(expected)
        elif backup.exists() and not expected.exists():
            backup.rename(expected)
        if old_config is not None:
            atomic(access, old_config, 0o600)
        if role == 'node':
            subprocess.run(['systemctl', 'start', 'fs-fc-collector.service'], check=True)
        raise

if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('sha256')
    parser.add_argument('worker_digest')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(update(args.bundle, args.sha256, args.worker_digest, args.apply), sort_keys=True))
