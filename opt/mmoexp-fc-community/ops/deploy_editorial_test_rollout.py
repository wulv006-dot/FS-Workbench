"""CAS release of the source-verified editorial scheduler to the test guild.

The plan and ledger already contain one confirmed D4 VIP pilot card. This
release deliberately does not grant the editorial worker an official route.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time


BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path('/tmp/mmoexp-fc-editorial-stage-20261115-6ef4')
SERVICE = 'mmoexp-fc-chat.service'
GUILD = '1565922092518613064'
FIXTURE = 'anderlechtw-clubbruggew-20261114'
MESSAGE_ID = '1571211465317163021'
PLAN = BASE / 'var' / 'matchday-editorial-test-plan.json'
STATE = BASE / 'var' / 'matchday-editorial-test.sqlite3'
EXPECTED_LIVE = {
    'chat_service.py': 'e0bd0780046fb5e83a015146d84d67e3b1b96afbc76782849d2a24ef3bc217a6',
    'content.chat.config.json': '88c12735ba0bb17048cc518d6a9a2154ad00f1afed38d7696ce428fa09678fd3',
    'matchday_engagement.py': 'aae0174da257669c12a2d4a4d2bc99578f7edeb1573a772b75a2058003c6c7bf',
}
EXPECTED_STAGE = {
    'chat_service.py': '9955ca27e6d547fdac0fda8746b307ec95cfe8383f5e21fb6a5b5f6a13f1bed9',
    'matchday_editorial.py': '43a712641471ebf4026465cf72f1b6fce3844ab20b8e36e992441098d47c5732',
    'editorial-pilot-plan.json': '44f13f936bfb33ad71e7c85dea09626101908cc9a375c979a8a10deff73b6440',
    'editorial-pilot.sqlite3': '7e47b7bfb211c86000ba6ba73508eca6490b5c13df64dd86b521e128d23d9c5e',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_hashes(root, expected):
    for name, wanted in expected.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or digest(path) != wanted:
            raise RuntimeError('File drift: ' + str(path))


def active():
    return subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0


def atomic_bytes(path, data, mode=None):
    temporary = path.with_name('.' + path.name + '.editorial-new')
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError('Unresolved temporary file: ' + str(temporary))
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode if mode is not None else path.stat().st_mode & 0o777)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def preflight():
    if os.geteuid() != 0 or STAGE.is_symlink() or not STAGE.is_dir():
        raise RuntimeError('Exact root stage required')
    if not active():
        raise RuntimeError('FC Chat service is inactive')
    check_hashes(BASE, EXPECTED_LIVE)
    check_hashes(STAGE, EXPECTED_STAGE)
    if any(path.exists() or path.is_symlink() for path in
           (BASE / 'matchday_editorial.py', PLAN, STATE)):
        raise RuntimeError('Editorial files already exist; reconcile before replay')
    plan = json.loads((STAGE / 'editorial-pilot-plan.json').read_text(encoding='utf-8'))
    if (plan.get('version') != 1 or len(plan.get('matches', [])) != 1 or
            plan['matches'][0].get('guild_id') != GUILD or
            plan['matches'][0].get('fixture_id') != FIXTURE):
        raise RuntimeError('Pilot plan drift')
    with sqlite3.connect(str(STAGE / 'editorial-pilot.sqlite3')) as db:
        rows = db.execute('''SELECT guild_id,fixture_id,phase,status,message_id
                             FROM matchday_editorial_post''').fetchall()
    if rows != [(GUILD, FIXTURE, 'kickoff_soon', 'sent', MESSAGE_ID)]:
        raise RuntimeError('Pilot ledger drift')
    original = (BASE / 'content.chat.config.json').read_bytes()
    config = json.loads(original)
    if 'matchday_editorial' in config:
        raise RuntimeError('Editorial already configured')
    if GUILD not in config.get('matchday_engagement', {}).get('routes', {}):
        raise RuntimeError('Test route unavailable')
    config['matchday_editorial'] = {
        'enabled': True,
        'allowed_guild_ids': [GUILD],
        'plan_path': str(PLAN),
        'state_path': str(STATE),
        'max_matches_per_london_week': 2,
    }
    sys.path.insert(0, str(STAGE))
    from matchday_editorial import validate_config
    validate_config(config['matchday_editorial'], config['matchday_engagement'])
    for name in ('chat_service.py', 'matchday_editorial.py'):
        compile((STAGE / name).read_text(encoding='utf-8'), name, 'exec')
    tests = subprocess.run(
        [str(BASE / '.venv-ssl/bin/python'), '-m', 'unittest', 'discover',
         '-s', str(STAGE / 'tests'), '-p', 'test_matchday*.py', '-q'],
        cwd=str(STAGE), capture_output=True, text=True, timeout=30)
    if tests.returncode or 'Ran 13 tests' not in tests.stderr or not tests.stderr.rstrip().endswith('OK'):
        raise RuntimeError('Isolated Linux tests failed')
    return original, (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def deploy(original_config, new_config):
    check_hashes(BASE, EXPECTED_LIVE)
    if any(path.exists() or path.is_symlink() for path in
           (BASE / 'matchday_editorial.py', PLAN, STATE)):
        raise RuntimeError('Editorial state changed after preflight')
    backup = BASE / 'backups' / ('editorial-test-' + str(int(time.time())))
    backup.mkdir(mode=0o700)
    shutil.copy2(BASE / 'chat_service.py', backup / 'chat_service.py')
    shutil.copy2(BASE / 'content.chat.config.json', backup / 'content.chat.config.json')
    try:
        atomic_bytes(PLAN, (STAGE / 'editorial-pilot-plan.json').read_bytes(), 0o600)
        atomic_bytes(STATE, (STAGE / 'editorial-pilot.sqlite3').read_bytes(), 0o600)
        atomic_bytes(BASE / 'matchday_editorial.py',
                     (STAGE / 'matchday_editorial.py').read_bytes(), 0o644)
        atomic_bytes(BASE / 'chat_service.py', (STAGE / 'chat_service.py').read_bytes())
        atomic_bytes(BASE / 'content.chat.config.json', new_config)
        subprocess.run(['systemctl', 'restart', SERVICE], check=True)
        time.sleep(2)
        if not active() or digest(BASE / 'chat_service.py') != EXPECTED_STAGE['chat_service.py']:
            raise RuntimeError('FC Chat readback failed')
        if digest(BASE / 'matchday_editorial.py') != EXPECTED_STAGE['matchday_editorial.py']:
            raise RuntimeError('Editorial module readback failed')
        live_config = json.loads((BASE / 'content.chat.config.json').read_text(encoding='utf-8'))
        if live_config['matchday_editorial']['allowed_guild_ids'] != [GUILD]:
            raise RuntimeError('Editorial guild allowlist readback failed')
    except Exception:
        atomic_bytes(BASE / 'chat_service.py', (backup / 'chat_service.py').read_bytes())
        atomic_bytes(BASE / 'content.chat.config.json', original_config)
        (BASE / 'matchday_editorial.py').unlink(missing_ok=True)
        subprocess.run(['systemctl', 'restart', SERVICE], check=False)
        raise
    receipt = {'service': SERVICE, 'backup': str(backup),
               'test_guild_only': GUILD, 'pilot_message_id': MESSAGE_ID,
               'chat_sha256': digest(BASE / 'chat_service.py'),
               'editorial_sha256': digest(BASE / 'matchday_editorial.py'),
               'service_active': active()}
    (backup / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    lock_path = Path('/run/lock/mmoexp-fc-editorial-release.lock')
    with lock_path.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_config, new_config = preflight()
        print(json.dumps(deploy(original_config, new_config) if args.apply else
                         {'status': 'checked', 'test_guild_only': GUILD,
                          'service_active': active()}))


if __name__ == '__main__':
    main()
