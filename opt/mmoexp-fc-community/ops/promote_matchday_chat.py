"""Enable the validated Smart Score discussion bridge in the official FC27 area."""

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path('/tmp/fc27-smartscore-pilot-20261114-3a5f')
EXPECTED = {
    BASE / 'chat_service.py': '085f0b3ae01e0d2af151f5e7fdb0c6b6e73a7fe6b1a4afee95d820777be4e48d',
    BASE / 'chat_brain.py': '3f23b23d7b4a40ea5af16b376f7a25f9b82de4f1745aa432bedc4f3f9f8c2316',
    BASE / 'matchday_engagement.py': 'aae0174da257669c12a2d4a4d2bc99578f7edeb1573a772b75a2058003c6c7bf',
    BASE / 'content.chat.config.json': '3e6c7ede645646622917ca5f1f13cce7013bf1cb559da5ef45d10f03efb37cbb',
    STAGE / 'chat_service.py': '6741d82cb1afa13e0ada0a2a001d716c220f682be4eadb0479f10b491950f983',
    STAGE / 'chat_brain.py': '5ab26bcceb33598dd20c58e5835d068d5f26004ae3cf7b7405945f28606eacae',
    STAGE / 'matchday_engagement.py': 'aae0174da257669c12a2d4a4d2bc99578f7edeb1573a772b75a2058003c6c7bf',
}
OFFICIAL = '1041923524601851914'
MATCHDAY = 1571043454136484082
MATCH_CHAT = 1571043570268242014
PLAYERS = 1568878333087719454
COINS = 1568663210901504041
SERVICE = 'mmoexp-fc-chat.service'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_bytes(path, data):
    temporary = path.with_name(path.name + '.smartscore-new')
    temporary.write_bytes(data)
    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.replace(str(temporary), str(path))


def main():
    with Path('/run/lock/mmoexp-fc-matchday-pilot.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=True)
        for path, expected in EXPECTED.items():
            if not path.is_file() or digest(path) != expected:
                raise RuntimeError('Source/config drift: ' + str(path))
        config = json.loads((BASE / 'content.chat.config.json').read_text(encoding='utf-8'))
        engagement = config['matchday_engagement']
        if set(engagement['routes']) != {'1565922092518613064'}:
            raise RuntimeError('Pilot route changed; reconcile first')
        engagement['routes'][OFFICIAL] = {
            'source_channel_id': MATCHDAY,
            'discussion_channel_id': MATCH_CHAT,
            'players_channel_id': PLAYERS,
            'coins_channel_id': COINS,
        }
        chat_route = config['chat_bot']['routes'][OFFICIAL]['channels']
        if str(MATCH_CHAT) in chat_route:
            raise RuntimeError('Match chat route already configured')
        chat_route[str(MATCH_CHAT)] = {}
        backup = BASE / 'backups' / ('smartscore-official-' + str(int(time.time())))
        backup.mkdir(mode=0o700)
        names = ('chat_service.py', 'chat_brain.py', 'content.chat.config.json')
        for name in names:
            shutil.copy2(BASE / name, backup / name)
        try:
            for name in ('chat_service.py', 'chat_brain.py'):
                atomic_bytes(BASE / name, (STAGE / name).read_bytes())
            atomic_bytes(BASE / 'content.chat.config.json',
                         (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            subprocess.run([str(BASE / '.venv-ssl/bin/python'), '-m', 'py_compile',
                            str(BASE / 'chat_service.py'), str(BASE / 'chat_brain.py')], check=True)
            sys.path.insert(0, str(BASE))
            import chat_service
            os.environ.setdefault(config.get('token_env', 'DISCORD_CHAT_BOT_TOKEN'), 'validation-only')
            chat_service.validate_config(config)
            subprocess.run(['systemctl', 'restart', SERVICE], check=True)
            subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=True)
        except Exception:
            for name in names:
                atomic_bytes(BASE / name, (backup / name).read_bytes())
            subprocess.run(['systemctl', 'restart', SERVICE], check=False)
            raise
        receipt = {'backup': str(backup), 'service_active': True,
                   'official_source_channel_id': MATCHDAY,
                   'official_discussion_channel_id': MATCH_CHAT,
                   'chat_service_sha256': digest(BASE / 'chat_service.py'),
                   'chat_brain_sha256': digest(BASE / 'chat_brain.py')}
        (backup / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
