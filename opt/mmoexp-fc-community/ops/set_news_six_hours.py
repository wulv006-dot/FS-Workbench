"""One-time authorized news interval update; preserves all other settings."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

root = Path('/opt/mmoexp-fc-community')
sys.path.insert(0, str(root))
from content_bot import validate_config

path = root / 'content.config.json'
original = path.read_bytes()
config = json.loads(original)
before = config['news_publish']['poll_seconds']
assert config['news_publish']['guild_id'] == 1041923524601851914
assert config['news_publish']['channel_id'] == '1501757710381748254'
config['news_publish']['poll_seconds'] = 21600
validate_config(config)
stamp = str(int(time.time()))
backup = root / 'backups' / ('news-six-hours-' + stamp + '.json')
shutil.copy2(str(path), str(backup))
os.chmod(str(backup), 0o600)
stat = path.stat()
temp = path.with_name('content.config.news-six-hours-' + stamp + '.tmp')
try:
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(str(temp), stat.st_mode & 0o777)
    os.chown(str(temp), stat.st_uid, stat.st_gid)
    if path.read_bytes() != original:
        raise RuntimeError('Configuration changed concurrently; aborting')
    os.replace(str(temp), str(path))
finally:
    if temp.exists():
        temp.unlink()
subprocess.run(['systemctl', 'restart', 'mmoexp-fc-community'], check=True)
for attempt in range(20):
    pid = subprocess.check_output(['systemctl', 'show', 'mmoexp-fc-community', '-p', 'MainPID']).decode().strip().split('=')[-1]
    try:
        ready = json.loads((root / 'var/ready.json').read_text())
    except (OSError, ValueError):
        ready = {}
    if ready.get('connected') and str(ready.get('pid')) == pid and pid != '0':
        print(json.dumps({'previous_seconds': before, 'poll_seconds': 21600,
                          'ready': True, 'pid': pid, 'backup': str(backup)}))
        break
    time.sleep(1)
else:
    raise RuntimeError('New process readiness not confirmed; config and backup retained')
