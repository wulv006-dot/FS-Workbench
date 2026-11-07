"""One-time restricted worker installer. Does not modify any existing service."""
import os
import pwd
import subprocess
from pathlib import Path

target = Path('/opt/fc27-news-fetch')
home = Path('/var/lib/fc27-news-fetch')
if target.exists() or home.exists():
    raise SystemExit('Refusing to overwrite existing worker paths')
try:
    pwd.getpwnam('fc27-news-fetch')
except KeyError:
    pass
else:
    raise SystemExit('Refusing existing account')
subprocess.run(['useradd', '--system', '--home-dir', str(home), '--shell', '/bin/sh',
                'fc27-news-fetch'], check=True)
target.mkdir(mode=0o755)
home.mkdir(mode=0o755)
(home/'.ssh').mkdir(mode=0o755)
worker = target/'worker.py'
worker.write_bytes(Path('/tmp/fc27-news-router-20261108/worker.py').read_bytes())
worker.chmod(0o644)
authorized = home/'.ssh/authorized_keys'
authorized.write_text('restrict,from="172.18.108.187",command="/usr/bin/python3 -I -B /opt/fc27-news-fetch/worker.py" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMJ2yo+UH4XvBisG4Rxa1n0APHxIo+KHa6xqCr8plQKq fc27-news-only\n')
authorized.chmod(0o644)
print('Installed root-owned fixed-source worker and restricted public key; no services changed')
