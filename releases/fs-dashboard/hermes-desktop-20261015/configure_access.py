"""Provision only the dedicated local-forward SSH identity; never prints secrets."""
import argparse
import hashlib
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--public-key', type=Path, required=True)
args = parser.parse_args()
public = args.public_key.read_text().strip()
if not re.fullmatch(r'(?:ssh-ed25519|ssh-rsa) [A-Za-z0-9+/=]{50,1000}(?: [^\r\n]{0,100})?', public):
    raise ValueError('expected_desktop_public_key')
name = 'fs-hermes-desktop'
try:
    account = pwd.getpwnam(name)
except KeyError:
    subprocess.run(['useradd', '--create-home', '--shell', '/bin/false', name], check=True)
    account = pwd.getpwnam(name)
if account.pw_dir != '/home/' + name or account.pw_shell != '/bin/false' or account.pw_uid == 0:
    raise ValueError('desktop_identity_drift')
ssh = Path(account.pw_dir) / '.ssh'
ssh.mkdir(mode=0o700, exist_ok=True)
os.chown(ssh, account.pw_uid, account.pw_gid)
authorized = ssh / 'authorized_keys'
line = 'restrict,port-forwarding,permitopen="127.0.0.1:8942",command="/bin/false" ' + public + '\n'
if authorized.exists() and authorized.read_text() != line:
    raise ValueError('existing_desktop_key_differs')
authorized.write_text(line)
authorized.chmod(0o600)
os.chown(authorized, account.pw_uid, account.pw_gid)
config = Path('/etc/ssh/sshd_config')
marker = '# >>> fs-hermes-desktop-20261015 >>>'
block = '\n' + marker + '''
Match User fs-hermes-desktop
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:8942
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    PasswordAuthentication no
    AuthenticationMethods publickey
    ForceCommand /bin/false
# <<< fs-hermes-desktop-20261015 <<<
'''
before = config.read_text()
backup = Path('/var/backups/fs-hermes-desktop-access-20261015')
backup.mkdir(mode=0o700, exist_ok=True)
if marker not in before:
    saved = backup / ('sshd_config-' + hashlib.sha256(before.encode()).hexdigest())
    if not saved.exists():
        shutil.copy2(config, saved)
    config.write_text(before + block)
    try:
        subprocess.run(['sshd', '-t'], check=True)
    except Exception:
        config.write_text(before)
        raise
    subprocess.run(['systemctl', 'reload', 'sshd'], check=True)
else:
    if not before.endswith(block):
        raise ValueError('existing_desktop_ssh_match_differs')
print('Dedicated desktop tunnel identity ready; key and token values withheld.')
