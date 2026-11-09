"""Guarded first deployment; --check is read-only apart from temporary tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

BASE = Path('/opt/mmoexp-fc-community')
STAGE = Path(__file__).resolve().parents[1]
SERVICE = 'mmoexp-fc-community'
BEFORE_SHA256 = '1ecf9c261d875d4e7a9fba5baddea4e1046435afd20c7c463691e4f73f23985e'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_stage(stage):
    manifest = json.loads((stage / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not {'content_bot.py', 'game_picker.py',
                                               'game-picker.config.json'} <= set(manifest):
        raise RuntimeError('Incomplete staging manifest')
    for name, expected in manifest.items():
        path = stage / name
        if (not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts
                or path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected):
            raise RuntimeError('Staged source drift: ' + str(name))
    return manifest


def verify_live(base, expected):
    if digest((base / 'content_bot.py').read_bytes()) != expected:
        raise RuntimeError('Live content_bot.py drift')
    if (base / 'game_picker.py').exists():
        raise RuntimeError('Live game_picker.py already exists')
    raw = (base / 'content.config.json').read_bytes()
    config = json.loads(raw)
    if not isinstance(config, dict) or 'game_picker' in config:
        raise RuntimeError('Live game picker configuration already exists or is invalid')
    return raw, config


def run(*args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=60).stdout


def atomic(path, data, reference):
    st = reference.stat()
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, st.st_mode & 0o777)
        os.chown(temporary, st.st_uid, st.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def test_stage(stage):
    sys.path.insert(0, str(stage))
    def cases(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                yield from cases(item)
            elif 'test_token_save.' not in item.id():
                yield item
    suite = unittest.TestSuite(cases(unittest.defaultTestLoader.discover(str(stage / 'tests'))))
    if not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful():
        raise RuntimeError('Isolated target tests failed')


def wait_ready(base, started_at):
    for _ in range(45):
        try:
            pid = int(run('systemctl', 'show', SERVICE, '-p', 'MainPID').split('=', 1)[1])
            ready = json.loads((base / 'var' / 'ready.json').read_text(encoding='utf-8'))
            if (pid > 0 and ready.get('pid') == pid and ready.get('connected')
                    and ready.get('test_guild_present') and ready.get('ready_at', 0) >= started_at):
                run('systemctl', 'is-active', SERVICE)
                return pid
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
        time.sleep(1)
    raise RuntimeError('Community service did not become ready')


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='Read-only preflight and isolated tests')
    action.add_argument('--apply', action='store_true', help='Install after successful preflight')
    args = parser.parse_args()
    verify_stage(STAGE)
    run('systemctl', 'is-active', SERVICE)
    original_config, config = verify_live(BASE, BEFORE_SHA256)
    os.chdir(STAGE)
    test_stage(STAGE)
    from game_picker import validate_game_config
    from content_bot import validate_config
    from ops.publish_game_picker import OFFICIAL, preflight_roles
    from ops.discord_ops import identity, request
    picker = validate_game_config(json.loads((STAGE / 'game-picker.config.json').read_text(encoding='utf-8')))
    if (str(picker['guild_id']), str(picker['channel_id'])) != OFFICIAL:
        raise RuntimeError('Picker config does not match the approved official route')
    identity()
    count = preflight_roles(picker, request)
    config['game_picker'] = picker
    validate_config(config)
    candidate_config = (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode()
    verify_stage(STAGE)
    raw, _ = verify_live(BASE, BEFORE_SHA256)
    if raw != original_config:
        raise RuntimeError('Live configuration drift')
    print(json.dumps({'preflight': 'ok', 'roles_checked': count, 'apply': args.apply}), flush=True)
    if not args.apply:
        return
    backup = BASE / 'backups' / ('game-picker-' + str(time.time_ns()))
    backup.mkdir(mode=0o700, parents=True)
    shutil.copy2(BASE / 'content_bot.py', backup / 'content_bot.py')
    shutil.copy2(BASE / 'content.config.json', backup / 'content.config.json')
    (backup / 'absent-files.txt').write_text('game_picker.py was absent\n')
    changed = []
    stopped = False
    try:
        run('systemctl', 'stop', SERVICE)
        stopped = True
        verify_stage(STAGE)
        raw, _ = verify_live(BASE, BEFORE_SHA256)
        if raw != original_config:
            raise RuntimeError('Live configuration drift after stop')
        for name in ('game_picker.py', 'content_bot.py'):
            path = BASE / name
            reference = BASE / 'content_bot.py'
            atomic(path, (STAGE / name).read_bytes(), reference)
            changed.append(name)
        atomic(BASE / 'content.config.json', candidate_config, BASE / 'content.config.json')
        changed.append('content.config.json')
        started_at = int(time.time())
        run('systemctl', 'start', SERVICE)
        pid = wait_ready(BASE, started_at)
    except BaseException:
        if stopped:
            subprocess.run(['systemctl', 'stop', SERVICE])
            for name in reversed(changed):
                path = BASE / name
                expected = candidate_config if name == 'content.config.json' else (STAGE / name).read_bytes()
                if not path.exists() or path.read_bytes() != expected:
                    raise RuntimeError('Rollback requires manual reconciliation; changed ' + name)
                if name == 'game_picker.py':
                    path.unlink()
                else:
                    atomic(path, (backup / name).read_bytes(), backup / name)
            subprocess.run(['systemctl', 'start', SERVICE])
        raise
    print(json.dumps({'deployed': True, 'pid': pid, 'backup': str(backup)}), flush=True)


if __name__ == '__main__':
    main()
