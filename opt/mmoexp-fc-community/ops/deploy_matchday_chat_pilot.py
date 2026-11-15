"""Deploy the reviewed Smart Score discussion bridge to the test guild only.

Run on 187 after staging the two source files and testing them in isolation.
No Discord token or provider credential is read or printed by this script.
"""

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path('/tmp/fc27-smartscore-pilot-20261114-3a5f')
SERVICE = 'mmoexp-fc-chat.service'
EXPECTED = {
    BASE / 'chat_service.py': '5f3070c38a5e058d1571f5c48891233ab65bcec23fd131aac30a0e0dff5b8928',
    BASE / 'content.chat.config.json': 'b70a70b2a2e2de5bc5aab2f3ced84dde5fb806228b02dbdae12ef43b905054ed',
    STAGE / 'chat_service.py': '085f0b3ae01e0d2af151f5e7fdb0c6b6e73a7fe6b1a4afee95d820777be4e48d',
    STAGE / 'matchday_engagement.py': 'd1071343c471ea666b29bafdae849e391a9dbd6655d8df071a5a3f29eb1eca81',
}
PILOT = {
    'enabled': True,
    'state_path': str(BASE / 'var' / 'match-pulse.sqlite3'),
    'routes': {
        '1565922092518613064': {
            'source_channel_id': 1568260661010497627,
            'discussion_channel_id': 1568260661010497627,
            'players_channel_id': 1568260661010497627,
            'coins_channel_id': 1568260661010497627,
        },
    },
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_bytes(path, data):
    temporary = path.with_name(path.name + '.smartscore-new')
    temporary.write_bytes(data)
    os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o644)
    os.replace(str(temporary), str(path))


def service_ok():
    return subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0


def main():
    lock_path = Path('/run/lock/mmoexp-fc-matchday-pilot.lock')
    with lock_path.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not service_ok():
            raise RuntimeError('Chat service is not active')
        if (BASE / 'matchday_engagement.py').exists():
            raise RuntimeError('Matchday module already exists; reconcile before applying')
        for path, expected in EXPECTED.items():
            if not path.is_file() or digest(path) != expected:
                raise RuntimeError('Source/config drift: ' + str(path))
        config = json.loads((BASE / 'content.chat.config.json').read_text(encoding='utf-8'))
        if 'matchday_engagement' in config:
            raise RuntimeError('Matchday config already exists')
        config['matchday_engagement'] = PILOT
        backup = BASE / 'backups' / ('smartscore-pilot-' + str(int(time.time())))
        backup.mkdir(mode=0o700)
        for name in ('chat_service.py', 'content.chat.config.json'):
            shutil.copy2(BASE / name, backup / name)
        new_config = (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        try:
            atomic_bytes(BASE / 'matchday_engagement.py', (STAGE / 'matchday_engagement.py').read_bytes())
            atomic_bytes(BASE / 'chat_service.py', (STAGE / 'chat_service.py').read_bytes())
            atomic_bytes(BASE / 'content.chat.config.json', new_config)
            subprocess.run([str(BASE / '.venv-ssl/bin/python'), '-m', 'py_compile',
                            str(BASE / 'chat_service.py'), str(BASE / 'matchday_engagement.py')],
                           check=True)
            subprocess.run(['systemctl', 'restart', SERVICE], check=True)
            if not service_ok():
                raise RuntimeError('Chat service did not become active')
        except Exception:
            for name in ('chat_service.py', 'content.chat.config.json'):
                atomic_bytes(BASE / name, (backup / name).read_bytes())
            (BASE / 'matchday_engagement.py').unlink(missing_ok=True)
            subprocess.run(['systemctl', 'restart', SERVICE], check=False)
            raise
        receipt = {'service': SERVICE, 'backup': str(backup), 'pilot_guild': '1565922092518613064',
                   'live_chat_sha256': digest(BASE / 'chat_service.py'),
                   'live_module_sha256': digest(BASE / 'matchday_engagement.py'),
                   'service_active': service_ok()}
        (backup / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
