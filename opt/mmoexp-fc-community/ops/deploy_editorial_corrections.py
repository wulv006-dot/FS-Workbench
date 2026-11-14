"""Guarded FC Chat correction update; keeps the test-only plan and ledger."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time


BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path('/tmp/mmoexp-fc-editorial-stage-20261115-6ef4')
SERVICE = 'mmoexp-fc-chat.service'
GUILD = '1565922092518613064'
PILOT_MESSAGE = '1571211465317163021'
BEFORE = {
    'chat_service.py': '9955ca27e6d547fdac0fda8746b307ec95cfe8383f5e21fb6a5b5f6a13f1bed9',
    'matchday_editorial.py': '43a712641471ebf4026465cf72f1b6fce3844ab20b8e36e992441098d47c5732',
    'content.chat.config.json': '9e58b6b2702d6fa12c4d692a5728baf39e7289674d5710c26009f2970b6eae31',
}
AFTER = {
    'chat_service.py': 'e074e46a7d6612f1a68e757b52da3230af629ff63ca0ae7d81720387169d6a90',
    'matchday_editorial.py': 'be8b4d664dadbadea8ea4ea0ad77f0f1c384aca7f31431cd5c2dd23c67d7c5af',
}
PLAN_SHA = '44f13f936bfb33ad71e7c85dea09626101908cc9a375c979a8a10deff73b6440'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root, expected):
    for name, wanted in expected.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or digest(path) != wanted:
            raise RuntimeError('File drift: ' + str(path))


def service_active():
    return subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0


def atomic_replace(target, data):
    temporary = target.with_name('.' + target.name + '.correction-new')
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError('Unresolved temporary file: ' + str(temporary))
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, target.stat().st_mode & 0o777)
    os.replace(temporary, target)
    fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check():
    if os.geteuid() != 0 or STAGE.is_symlink() or not STAGE.is_dir():
        raise RuntimeError('Exact root stage required')
    if not service_active():
        raise RuntimeError('FC Chat service inactive')
    verify(BASE, BEFORE)
    verify(STAGE, AFTER)
    config = json.loads((BASE / 'content.chat.config.json').read_text(encoding='utf-8'))
    editorial = config.get('matchday_editorial') or {}
    if (not editorial.get('enabled') or editorial.get('allowed_guild_ids') != [GUILD] or
            editorial.get('plan_path') != str(BASE / 'var' / 'matchday-editorial-test-plan.json') or
            editorial.get('state_path') != str(BASE / 'var' / 'matchday-editorial-test.sqlite3')):
        raise RuntimeError('Test-only editorial config drift')
    if digest(Path(editorial['plan_path'])) != PLAN_SHA:
        raise RuntimeError('Pilot plan drift')
    with sqlite3.connect(editorial['state_path']) as db:
        rows = db.execute('''SELECT guild_id,fixture_id,phase,status,message_id
            FROM matchday_editorial_post''').fetchall()
    if rows != [(GUILD, 'anderlechtw-clubbruggew-20261114',
                 'kickoff_soon', 'sent', PILOT_MESSAGE)]:
        raise RuntimeError('Pilot ledger drift')
    for name in AFTER:
        compile((STAGE / name).read_text(encoding='utf-8'), name, 'exec')
    tests = subprocess.run([
        str(BASE / '.venv-ssl/bin/python'), '-m', 'unittest', 'discover',
        '-s', str(STAGE / 'tests'), '-p', 'test_matchday*.py', '-q'],
        cwd=str(STAGE), capture_output=True, text=True, timeout=30)
    if tests.returncode or 'Ran 16 tests' not in tests.stderr or not tests.stderr.rstrip().endswith('OK'):
        raise RuntimeError('Isolated Linux tests failed')
    return editorial


def apply():
    editorial = check()
    verify(BASE, BEFORE)
    backup = BASE / 'backups' / ('editorial-corrections-' + str(int(time.time())))
    backup.mkdir(mode=0o700)
    for name in AFTER:
        shutil.copy2(BASE / name, backup / name)
    with sqlite3.connect(editorial['state_path']) as source:
        with sqlite3.connect(str(backup / 'editorial-ledger-before.sqlite3')) as destination:
            source.backup(destination)
    try:
        for name in AFTER:
            atomic_replace(BASE / name, (STAGE / name).read_bytes())
        subprocess.run(['systemctl', 'restart', SERVICE], check=True)
        time.sleep(2)
        if not service_active():
            raise RuntimeError('FC Chat restart failed')
        verify(BASE, AFTER)
        with sqlite3.connect(editorial['state_path']) as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(matchday_editorial_post)')}
        if not {'kickoff_ts', 'display_status'} <= columns:
            raise RuntimeError('Editorial ledger migration not visible')
    except Exception:
        for name in AFTER:
            atomic_replace(BASE / name, (backup / name).read_bytes())
        subprocess.run(['systemctl', 'restart', SERVICE], check=False)
        raise
    receipt = {'service': SERVICE, 'backup': str(backup),
               'test_guild_only': GUILD, 'pilot_message_id': PILOT_MESSAGE,
               'files': {name: digest(BASE / name) for name in AFTER},
               'service_active': service_active()}
    (backup / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with Path('/run/lock/mmoexp-fc-editorial-release.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = apply() if args.apply else {'status': 'checked',
                                              'test_guild_only': GUILD,
                                              'service_active': bool(check()) and service_active()}
        print(json.dumps(result))


if __name__ == '__main__':
    main()
