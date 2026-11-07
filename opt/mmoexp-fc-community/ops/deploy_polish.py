"""Exact three-file polish release; execute only after explicit production approval."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

STAGE = Path('/opt/mmoexp-fc-stage-20261108-polish-20261107T170128Z-De4qi8')
BOT = Path('/opt/mmoexp-fc-community')
NAMES = ('content_bot.py', 'quote_panel.py', 'club_panel.py')
MARKERS = ('quote-static-panel.json', 'club-panels.json', 'quote-panels-v2.json')
sys.path.insert(0, str(STAGE / 'mmoexp-fc-pilot'))
from content_bot import validate_config


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, data):
    info = path.stat()
    fd, temporary = tempfile.mkstemp(prefix='.polish-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, info.st_uid, info.st_gid)
        os.chmod(temporary, info.st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=40, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(args[:3]))
    return result.stdout.strip()


def main():
    if sys.argv[1:] != ['--approved-release']:
        raise SystemExit('Preparation only: production execution requires the authorized release command.')
    before = json.loads((STAGE / 'receipts/preparation.json').read_text())['production_hashes']
    reviewed = json.loads((STAGE / 'receipts/preview-verification.json').read_text())['candidate_hashes']
    for name in NAMES:
        if digest(BOT / name) != before[name] or digest(STAGE / 'mmoexp-fc-pilot' / name) != reviewed[name]:
            raise SystemExit('Source drift: ' + name)
    path = BOT / 'content.config.json'
    original_config = path.read_bytes()
    if hashlib.sha256(original_config).hexdigest() != before['content.config.json']:
        raise SystemExit('Configuration drift; merge must be reviewed again')
    config = json.loads(original_config)
    if config['news_publish']['poll_seconds'] != 21600:
        raise SystemExit('Six-hour news interval must be preserved')
    icons = json.loads((STAGE / 'presentation-icons.json').read_text())['icons']
    config.setdefault('quote_presentation', {})['icons'] = icons
    validate_config(config)
    markers = {name: (BOT / 'var' / name).read_bytes() for name in MARKERS}
    if any('pending' in value.decode() for value in markers.values()):
        raise SystemExit('Existing panel marker needs reconciliation')
    originals = {name: (BOT / name).read_bytes() for name in NAMES}
    backup = BOT / 'backups' / ('polish-final-' + str(int(time.time())))
    backup.mkdir(mode=0o700)
    for name in NAMES + ('content.config.json',):
        shutil.copy2(BOT / name, backup / name)
    for name in MARKERS:
        shutil.copy2(BOT / 'var' / name, backup / name)
    print(json.dumps({'phase': 'preflight_verified', 'backup': str(backup)}), flush=True)
    changed = False
    try:
        command('systemctl', 'stop', 'mmoexp-fc-community')
        if path.read_bytes() != original_config or any((BOT / 'var' / name).read_bytes() != data for name, data in markers.items()):
            raise RuntimeError('Configuration or marker drift during stop')
        changed = True
        for name in NAMES:
            atomic(BOT / name, (STAGE / 'mmoexp-fc-pilot' / name).read_bytes())
        atomic(path, (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode())
        command('systemctl', 'start', 'mmoexp-fc-community')
        for _ in range(40):
            pid = int(command('systemctl', 'show', 'mmoexp-fc-community', '-p', 'MainPID').split('=', 1)[1])
            ready = json.loads((BOT / 'var/ready.json').read_text())
            if ready.get('connected') and ready.get('pid') == pid and ready.get('test_guild_present'):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Bounded readiness failed')
        if any((BOT / 'var' / name).read_bytes() != data for name, data in markers.items()):
            raise RuntimeError('Panel marker changed unexpectedly; do not reset it blindly')
        report = {'status': 'ready', 'backup': str(backup), 'pid': pid, 'source_hashes': {name: digest(BOT / name) for name in NAMES},
                  'icons_count': len(icons), 'news_poll_seconds': config['news_publish']['poll_seconds'],
                  'markers_unchanged': True, 'quote_bridge': command('systemctl', 'is-active', 'mmoexp-fc-quotes'),
                  'fs_console': command('systemctl', 'is-active', 'bot-console')}
        (STAGE / 'receipts/deployment.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    except Exception as error:
        if changed:
            command('systemctl', 'stop', 'mmoexp-fc-community')
            for name, data in originals.items():
                atomic(BOT / name, data)
            atomic(path, original_config)
        # Markers are never restored or deleted: on_ready only reuses the existing IDs.
        command('systemctl', 'start', 'mmoexp-fc-community')
        report = {'status': 'rolled_back' if changed else 'unchanged', 'error_code': type(error).__name__,
                  'reason': str(error), 'backup': str(backup), 'markers_reset': False}
        (STAGE / 'receipts/deployment.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
