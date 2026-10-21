"""One-shot sales authentication deployment. Never starts a service or logs in."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

from prepare_patch import BASE_SHA, patch

ROOT = Path('/opt/sales-dashboard/collector')
RELEASE = Path('/var/backups/sales-shared-session-20261021-v1')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path, raw, mode):
    temp = path.with_name(path.name + '.sales-shared.tmp')
    with temp.open('xb') as stream:
        os.chmod(temp, mode)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def main():
    with open('/run/lock/sales-shared-session.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt_path = RELEASE / 'receipt.json'
        if RELEASE.exists():
            raise SystemExit('existing_operation: inspect receipt and actual hashes; do not replay')
        source = ROOT / 'p2pah_auth.py'
        raw = source.read_bytes()
        assert sha(raw) == BASE_SHA, 'baseline_changed'
        config = Path('/etc/sales-dashboard.env')
        assert config.stat().st_uid == 0 and stat.S_IMODE(config.stat().st_mode) == 0o600
        keys = {line.partition('=')[0] for line in config.read_text().splitlines()}
        assert 'P2PAH_PASSWORD' in keys and keys & {'P2PAH_USERNAME', 'P2PAH_USER'}
        helper = ROOT / 'shared_admin.py'
        assert not helper.exists(), 'unexpected_existing_helper'
        candidate = patch(raw.decode()).encode()
        helper_raw = Path(__file__).with_name('shared_admin.py').read_bytes()
        RELEASE.mkdir(mode=0o700)
        atomic(RELEASE / 'p2pah_auth.before.py', raw, 0o600)
        atomic(RELEASE / 'p2pah_auth.candidate.py', candidate, 0o600)
        atomic(RELEASE / 'shared_admin.py', helper_raw, 0o600)
        receipt = {'operation': RELEASE.name, 'state': 'PREPARED', 'time_epoch': time.time(),
                   'before': BASE_SHA, 'after': sha(candidate), 'helper': sha(helper_raw)}
        atomic(receipt_path, json.dumps(receipt).encode(), 0o600)
        subprocess.run(['/opt/python39/bin/python3.9', '-m', 'py_compile',
                        str(RELEASE / 'p2pah_auth.candidate.py'), str(RELEASE / 'shared_admin.py')], check=True)
        subprocess.run(['systemctl', 'disable', '--now', 'sales-dashboard-sync.timer'], check=True, capture_output=True)
        subprocess.run(['systemctl', 'stop', 'sales-dashboard-sync.service'], check=True, capture_output=True)
        assert sha(source.read_bytes()) == BASE_SHA, 'baseline_changed_before_replace'
        atomic(helper, helper_raw, stat.S_IMODE(source.stat().st_mode))
        assert sha(source.read_bytes()) == BASE_SHA, 'baseline_changed_before_auth_replace'
        atomic(source, candidate, stat.S_IMODE(source.stat().st_mode))
        assert sha(source.read_bytes()) == receipt['after']
        assert sha(helper.read_bytes()) == receipt['helper']
        receipt['state'] = 'DEPLOYED_HELD_STOPPED'
        receipt['login_requests'] = 0
        receipt['config_reused'] = str(config)
        atomic(receipt_path, json.dumps(receipt).encode(), 0o600)
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
