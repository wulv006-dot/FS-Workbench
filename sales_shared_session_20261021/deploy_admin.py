"""Prepare or apply the exact inventoried Admin source patch, with stopped-login checks."""
import argparse
import json
from pathlib import Path
import stat
import subprocess
import urllib.request

from deploy_sales import atomic, sha
from unify_admin import BASELINES, kind_for, transform

RELEASE = Path('/var/backups/fs-admin-single-owner-20261021-v1')
SHARED = Path('/opt/fs-shared-session/shared_admin.py')


def require_cooling():
    result = subprocess.run(['systemctl', 'is-active', 'fc27-p2pah-session'], capture_output=True, text=True)
    assert result.stdout.strip() in {'inactive', 'failed'}, 'global_session_must_remain_stopped'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'apply'])
    args = parser.parse_args()
    require_cooling()
    receipt = RELEASE / 'receipt.json'
    if args.phase == 'prepare':
        assert not RELEASE.exists(), 'existing_operation_inspect_receipt'
        assert not SHARED.exists(), 'existing_shared_helper_requires_review'
        prepared = []
        for index, (name, before) in enumerate(BASELINES.items()):
            path = Path(name)
            raw = path.read_bytes()
            assert sha(raw) == before, 'baseline_changed:' + name
            candidate = transform(raw.decode(), kind_for(name)).encode()
            prepared.append((index, name, before, raw, candidate))
        RELEASE.mkdir(mode=0o700)
        entries = []
        for index, name, before, raw, candidate in prepared:
            atomic(RELEASE / (str(index) + '.before.py'), raw, 0o600)
            dest = RELEASE / (str(index) + '.candidate.py')
            atomic(dest, candidate, 0o600)
            subprocess.run(['/opt/python39/bin/python3.9', '-m', 'py_compile', str(dest)], check=True)
            entries.append({'index': index, 'path': name, 'before': before, 'after': sha(candidate)})
        helper = Path(__file__).with_name('shared_admin.py').read_bytes()
        atomic(RELEASE / 'shared_admin.py', helper, 0o600)
        value = {'state': 'PREPARED', 'entries': entries, 'helper': sha(helper), 'login_requests': 0}
        atomic(receipt, json.dumps(value).encode(), 0o600)
        print(json.dumps(value))
        return
    value = json.loads(receipt.read_text())
    assert value['state'] == 'PREPARED', 'inspect_existing_operation_do_not_replay'
    # Do not interrupt an in-memory SBC job or a persisted pack write.
    with urllib.request.urlopen('http://127.0.0.1:8793/health', timeout=5) as response:
        health = json.load(response)
    assert health.get('busy') is False and not health.get('running'), 'sbc_busy'
    history = json.loads(Path('/opt/fc27-pack-bundles/data/history.json').read_text())
    assert isinstance(history, list), 'unexpected_pack_history_contract'
    assert not any(x.get('status') in {'running', 'pending', 'RUNNING', 'PENDING'} for x in history), 'pack_busy'
    for entry in value['entries']:
        assert sha(Path(entry['path']).read_bytes()) == entry['before'], 'baseline_changed:' + entry['path']
        assert sha((RELEASE / (str(entry['index']) + '.candidate.py')).read_bytes()) == entry['after']
    assert not SHARED.exists(), 'unexpected_shared_helper'
    # These are the only resident consumers requiring a reload; their dependencies exclude 8767.
    for unit in ['fc27-sbc-tool.service', 'fc27-pack-bundles.service']:
        deps = subprocess.check_output(['systemctl', 'show', unit, '-p', 'Requires', '-p', 'Wants'], text=True)
        assert 'fc27-p2pah-session' not in deps, 'unsafe_service_dependency'
    value['state'] = 'APPLYING'
    atomic(receipt, json.dumps(value).encode(), 0o600)
    subprocess.run(['systemctl', 'disable', '--now', 'dashboard-collect.service'], check=True, capture_output=True)
    for unit in ['fc27-sbc-tool.service', 'fc27-pack-bundles.service']:
        subprocess.run(['systemctl', 'stop', unit], check=True, capture_output=True)
    SHARED.parent.mkdir(mode=0o755)
    helper = (RELEASE / 'shared_admin.py').read_bytes()
    assert sha(helper) == value['helper']
    atomic(SHARED, helper, 0o644)
    for entry in value['entries']:
        dest = Path(entry['path'])
        assert sha(dest.read_bytes()) == entry['before'], 'changed_before_replace:' + str(dest)
        raw = (RELEASE / (str(entry['index']) + '.candidate.py')).read_bytes()
        atomic(dest, raw, stat.S_IMODE(dest.stat().st_mode))
        assert sha(dest.read_bytes()) == entry['after']
    for unit in ['fc27-sbc-tool.service', 'fc27-pack-bundles.service']:
        subprocess.run(['systemctl', 'start', unit], check=True, capture_output=True)
    require_cooling()
    value['state'] = 'DEPLOYED_CENTRAL_HELD_STOPPED'
    atomic(receipt, json.dumps(value).encode(), 0o600)
    print(json.dumps(value))


if __name__ == '__main__':
    main()
