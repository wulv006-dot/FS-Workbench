"""Initial 183 FC role only. Preview by default; matching reruns reconcile original files."""
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
import tempfile
import time
import zipfile

CODE = Path('/opt/fs-fc-collector')
STATE = Path('/var/lib/fs-fc-collector')
UNIT = Path('/etc/systemd/system/fs-fc-collector.service')
RECEIPT = Path('/var/tmp/fs-fc-collector-setup-20261102.json')
USER = 'fs-fc-collector'
FILES = {'fc_collection/' + name for name in ('__init__.py', 'contracts.py', 'worker.py', 'adapters.py',
         'protocol.py', 'public_sources.py', 'server.py', 'lootbar.py')} | {'entry.py', 'manifest.json'}
CONTROL_FILES = {'fc_collection/' + name for name in ('__init__.py', 'contracts.py', 'coordinator.py',
                 'protocol.py', 'public_sources.py', 'ssh_client.py', 'pilot.py', 'client.py',
                 'adapters.py', 'worker.py', 'failover.py', 'lootbar.py')} | {'entry.py', 'manifest.json'}
SERVICE = b'''[Unit]
Description=FS source-limited FC collector
After=network-online.target

[Service]
Type=simple
User=fs-fc-collector
Group=fs-fc-collector
ExecStart=/usr/bin/python3 -I -B /opt/fs-fc-collector/code/entry.py service
RuntimeDirectory=fs-fc-collector
RuntimeDirectoryMode=0700
UMask=0077
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths=/var/lib/fs-fc-collector/spool /run/fs-fc-collector
InaccessiblePaths=-/opt/d4follow -/opt/g2gfollow -/opt/fs-hermes-fc -/opt/fc27-cloud-browser -/var/lib/fs-hermes-fc -/var/lib/fc27-cloud
CPUQuota=25%
MemoryMax=256M
MemorySwapMax=0
TasksMax=64
IOWeight=10
Nice=15
IOSchedulingClass=idle

[Install]
WantedBy=multi-user.target
'''


def read_bundle(path, digest, role='node'):
    if role not in ('node', 'control'):
        raise ValueError('node_role_invalid')
    allowed = FILES if role == 'node' else CONTROL_FILES
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 8388608 or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('node_bundle_hash_invalid')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (len(entries) != len(allowed) or {item.filename for item in entries} != allowed
                or any(item.file_size > 1048576 or stat.S_ISLNK(item.external_attr >> 16) for item in entries)
                or sum(item.file_size for item in entries) > 4194304):
            raise ValueError('node_bundle_files_invalid')
        files = {item.filename: archive.read(item) for item in entries}
    manifest = json.loads(files['manifest.json'])
    if (manifest.get('role') != ('limited_fc_collector' if role == 'node' else 'fc_collection_controller') or manifest.get('credentials') != []
            or manifest.get('production_consume') is not False or set(manifest.get('sha256', {})) != allowed - {'manifest.json'}):
        raise ValueError('node_manifest_invalid')
    if any(hashlib.sha256(files[name]).hexdigest() != value for name, value in manifest['sha256'].items()):
        raise ValueError('node_manifest_hash_invalid')
    return files


def public_key(value):
    lines = value.strip().splitlines()
    fields = lines[0].split() if len(lines) == 1 else []
    if len(fields) < 2 or fields[0] != 'ssh-ed25519':
        raise ValueError('node_public_key_invalid')
    try:
        decoded = base64.b64decode(fields[1], validate=True)
    except ValueError:
        raise ValueError('node_public_key_invalid') from None
    if len(decoded) != 51 or decoded[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00 ':
        raise ValueError('node_public_key_invalid')
    return fields[0] + ' ' + fields[1]


def write_exact(path, body, mode):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('node_target_link_invalid')
    if path.exists():
        if not path.is_file() or path.read_bytes() != body:
            raise ValueError('node_target_conflict')
        if os.name == 'posix' and (path.stat().st_uid != 0 or path.stat().st_nlink != 1):
            raise ValueError('node_target_owner_invalid')
        path.chmod(mode)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(mode)


def code_directories(root):
    root = Path(root)
    for path in (root, root / 'code', root / 'code/fc_collection'):
        if path.is_symlink() or path.exists() and not path.is_dir():
            raise ValueError('node_code_directory_invalid')
        path.mkdir(mode=0o755, parents=True, exist_ok=True)
        if os.name == 'posix' and path.stat().st_uid != os.geteuid():
            raise ValueError('node_code_owner_invalid')
        path.chmod(0o755)


def protected_status():
    return subprocess.check_output(['systemctl', 'show', 'd4follow', 'p2pah-srv-exec', 'rpg-db-lock-watch',
                                    '-p', 'Id', '-p', 'ActiveState', '-p', 'MainPID'], text=True).strip()


def install(bundle, digest, pubfile, apply=False):
    files = read_bundle(bundle, digest)
    if Path(pubfile).is_symlink() or Path(pubfile).stat().st_size > 2048:
        raise ValueError('node_public_key_file_invalid')
    key = public_key(Path(pubfile).read_text())
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    config = dict(node_id='183', spool=str(STATE / 'spool'), socket='/run/fs-fc-collector/worker.sock')
    node_json = (json.dumps(config, sort_keys=True) + '\n').encode()
    authorized = ('restrict,from="172.18.108.187",command="/usr/bin/python3 -I -B /opt/fs-fc-collector/code/entry.py relay" '
                  + key + '\n').encode()
    expected = {CODE / 'code' / name: body for name, body in files.items()}
    expected.update({CODE / 'node.json': node_json, STATE / '.ssh/authorized_keys': authorized, UNIT: SERVICE})
    if os.name != 'posix' or os.geteuid() != 0 or socket.gethostname() != 'FSHTUS01':
        raise ValueError('verified_183_root_entry_required')
    import pwd
    if RECEIPT.is_symlink():
        raise ValueError('node_receipt_link_invalid')
    if RECEIPT.exists() and (RECEIPT.stat().st_uid != 0 or RECEIPT.stat().st_nlink != 1
                            or RECEIPT.stat().st_size > 16384 or stat.S_IMODE(RECEIPT.stat().st_mode) != 0o600):
        raise ValueError('node_receipt_permissions_invalid')
    old = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else None
    if old and (old.get('bundle_sha256') != digest or old.get('public_key_sha256') != key_hash):
        raise ValueError('node_setup_requires_reconciliation')
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        account = None
    if not old and (CODE.exists() or STATE.exists() or UNIT.exists() or account):
        raise ValueError('node_initial_target_conflict')
    for path, body in expected.items():
        if path.is_symlink() or path.exists() and (not path.is_file() or path.read_bytes() != body):
            raise ValueError('node_existing_target_conflict')
    if account and (account.pw_dir != str(STATE) or account.pw_shell != '/bin/sh'
                    or os.getgrouplist(USER, account.pw_gid) != [account.pw_gid]):
        raise ValueError('node_account_conflict')
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))
    if available < 1048576 or os.statvfs('/var/tmp').f_bavail * os.statvfs('/var/tmp').f_frsize < 1073741824:
        raise ValueError('node_resource_budget_unavailable')
    before = protected_status()
    if before.count('ActiveState=active') != 3:
        raise ValueError('protected_RPG_not_active')
    result = dict(bundle_sha256=digest, public_key_sha256=key_hash, role=USER,
                  service=str(UNIT), code_root=str(CODE), state_root=str(STATE),
                  network_changes=False, shared_service_changes=False, protected_before=before,
                  phase='preview', apply=apply)
    if not apply:
        return result
    if not old:
        write_exact(RECEIPT, (json.dumps(dict(result, phase='started'), sort_keys=True) + '\n').encode(), 0o600)
    if account is None:
        subprocess.run(['useradd', '--system', '--user-group', '--home-dir', str(STATE),
                        '--no-create-home', '--shell', '/bin/sh', USER], check=True)
        account = pwd.getpwnam(USER)
    code_directories(CODE)
    for directory in (CODE, STATE, STATE / '.ssh'):
        if directory.is_symlink():
            raise ValueError('node_directory_link_invalid')
        directory.mkdir(mode=0o755, parents=True, exist_ok=True)
        os.chown(directory, 0, 0)
        directory.chmod(0o755)
    spool = STATE / 'spool'
    if spool.is_symlink():
        raise ValueError('node_spool_link_invalid')
    spool.mkdir(mode=0o700, exist_ok=True)
    os.chown(spool, account.pw_uid, account.pw_gid)
    spool.chmod(0o700)
    for path, body in expected.items():
        write_exact(path, body, 0o444 if path.is_relative_to(CODE / 'code') else 0o644)
        os.chown(path, 0, 0)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'fs-fc-collector.service'], check=True, capture_output=True)
    health = None
    for _ in range(50):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect(config['socket'])
                connection.sendall(b'{"method":"health"}\n')
                with connection.makefile('rb') as response:
                    health = json.loads(response.readline(65537))
                break
        except (FileNotFoundError, ConnectionRefusedError):
            time.sleep(.1)
    if (not health or health.get('uid') != account.pw_uid or health.get('node_id') != '183'
            or health.get('worker_digest') != hashlib.sha256(files['manifest.json']).hexdigest()):
        raise ValueError('node_health_not_verified')
    after = protected_status()
    if after.count('ActiveState=active') != 3:
        raise ValueError('protected_RPG_changed_during_setup')
    result.update(phase='installed_health_verified', uid=account.pw_uid, protected_after=after,
                  worker_digest=health['worker_digest'], source_requests=0,
                  limits=subprocess.check_output(['systemctl', 'show', 'fs-fc-collector', '-p', 'User',
                      '-p', 'MemoryMax', '-p', 'CPUQuotaPerSecUSec', '-p', 'TasksMax', '-p', 'ActiveState'], text=True).strip())
    descriptor, name = tempfile.mkstemp(prefix='.fc-node-setup-', dir=str(RECEIPT.parent))
    temporary = Path(name)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(result, stream, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, RECEIPT)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('sha256')
    parser.add_argument('public_key_file', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.bundle, args.sha256, args.public_key_file, args.apply), sort_keys=True))
