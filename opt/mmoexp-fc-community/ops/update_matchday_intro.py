"""Publish the one-time official Match Chat navigation card with the live chat bot."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path('/tmp/fc27-smartscore-pilot-20261114-3a5f')
OLD = '6741d82cb1afa13e0ada0a2a001d716c220f682be4eadb0479f10b491950f983'
NEW = 'e0bd0780046fb5e83a015146d84d67e3b1b96afbc76782849d2a24ef3bc217a6'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    live, candidate = BASE / 'chat_service.py', STAGE / 'chat_service.py'
    if digest(live) != OLD or digest(candidate) != NEW:
        raise RuntimeError('Chat service version drift')
    config = json.loads((BASE / 'content.chat.config.json').read_text(encoding='utf-8'))
    if set(config.get('matchday_engagement', {}).get('routes', {})) != {
            '1565922092518613064', '1041923524601851914'}:
        raise RuntimeError('Matchday routes not ready')
    backup = BASE / 'backups' / ('smartscore-intro-' + str(int(time.time())))
    backup.mkdir(mode=0o700)
    shutil.copy2(live, backup / live.name)
    temporary = live.with_name(live.name + '.smartscore-new')
    try:
        shutil.copy2(candidate, temporary)
        os.replace(str(temporary), str(live))
        subprocess.run([str(BASE / '.venv-ssl/bin/python'), '-m', 'py_compile', str(live)], check=True)
        subprocess.run(['systemctl', 'restart', 'mmoexp-fc-chat.service'], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'mmoexp-fc-chat.service'], check=True)
    except Exception:
        os.replace(str(backup / live.name), str(live))
        subprocess.run(['systemctl', 'restart', 'mmoexp-fc-chat.service'], check=False)
        raise
    print(json.dumps({'backup': str(backup), 'chat_service_sha256': digest(live),
                      'service_active': True}))


if __name__ == '__main__':
    main()
