"""Deploy the in-place alert acknowledgement after isolated tests."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time

base = Path('/opt/mmoexp-fc-community')
stage = Path('/opt/mmoexp-fc-relay-fix-20261108')
target = base / 'alert_panel.py'
expected = 'e07355a7d2322a582177602b1fe6b83bc4c0593ad0d3ba0162933a56ec0afdf1'
if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
    raise SystemExit('Live alert source changed; inspect before deploying')
backup = base / 'backups' / ('alert-reply-' + str(int(time.time())))
backup.mkdir()
shutil.copy2(target, backup / target.name)
temporary = target.with_suffix('.new')
shutil.copy2(stage / target.name, temporary)
os.chown(temporary, target.stat().st_uid, target.stat().st_gid)
os.replace(temporary, target)
try:
    subprocess.run(['systemctl', 'restart', 'mmoexp-fc-community'], check=True)
except BaseException:
    shutil.copy2(backup / target.name, target)
    subprocess.run(['systemctl', 'restart', 'mmoexp-fc-community'], check=True)
    raise
print('Backup:', backup)
print('SHA256:', hashlib.sha256(target.read_bytes()).hexdigest())
