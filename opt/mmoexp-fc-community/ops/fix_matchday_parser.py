"""Replace only the test-pilot parser after live-card format verification."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path('/tmp/fc27-smartscore-pilot-20261114-3a5f')
OLD = '77fa5a7e99e540e42ff1a739626ad3c623c9d9e160e98a495ec4cd82825eb19d'
NEW = 'aae0174da257669c12a2d4a4d2bc99578f7edeb1573a772b75a2058003c6c7bf'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    live = BASE / 'matchday_engagement.py'
    candidate = STAGE / 'matchday_engagement.py'
    if digest(live) != OLD or digest(candidate) != NEW:
        raise RuntimeError('Parser version drift')
    config = json.loads((BASE / 'content.chat.config.json').read_text(encoding='utf-8'))
    routes = config.get('matchday_engagement', {}).get('routes', {})
    if set(routes) != {'1565922092518613064'}:
        raise RuntimeError('Pilot route drift')
    backup = BASE / 'backups' / ('smartscore-parser-' + str(int(time.time())))
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
    print(json.dumps({'backup': str(backup), 'module_sha256': digest(live), 'service_active': True}))


if __name__ == '__main__':
    main()
