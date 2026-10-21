"""Root-only, local tmpfs checkpoint for the single Admin session owner."""
import json
import os
from pathlib import Path
import stat
import time

STATE = Path('/run/secrets/fs-session-state/session.json')


def safe_token(value, optional=False):
    return ((value is None and optional) or
            isinstance(value, str) and 0 < len(value) <= 8192 and
            not any(ord(c) < 33 or ord(c) > 126 for c in value))


def write(value, path=STATE):
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o077:
        raise RuntimeError('session_state_directory_unsafe')
    if path.exists() or path.is_symlink():
        checked_file(path)
    temporary = path.with_name('.session-' + str(os.getpid()))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def checked_file(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
            info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 32768):
        raise RuntimeError('session_state_file_unsafe')


def save(manager, path=STATE):
    with manager.lock:
        if manager.status != 'ready' or not safe_token(manager.token):
            return
        if not safe_token(manager.refresh_token, optional=True):
            raise RuntimeError('session_state_refresh_invalid')
        value = {'version': 1, 'created': time.time(),
                 'api_base': manager.config['P2PAH_API_BASE'],
                 'token': manager.token, 'refresh_token': manager.refresh_token,
                 'refresh_age': max(0, time.monotonic() - manager.last_refresh),
                 'login_attempts': manager.login_attempts}
        write(value, path)


def restore(manager, path=STATE):
    if not path.exists() and not path.is_symlink():
        return False
    checked_file(path)
    value = json.loads(path.read_text())
    age = time.time() - value.get('created', 0)
    if (value.get('version') != 1 or not 0 <= age <= 1800 or
            value.get('api_base') != manager.config['P2PAH_API_BASE'] or
            not safe_token(value.get('token')) or
            not safe_token(value.get('refresh_token'), optional=True) or
            type(value.get('login_attempts')) is not int or value['login_attempts'] < 0 or
            type(value.get('refresh_age')) not in (int, float) or
            not 0 <= value['refresh_age'] <= 86400):
        raise RuntimeError('session_state_invalid')
    if not manager.identity_ok(value['token'], timeout=10):
        raise RuntimeError('session_state_identity_unverified')
    manager.token, manager.refresh_token = value['token'], value.get('refresh_token')
    manager.last_refresh = time.monotonic() - value['refresh_age'] - age
    manager.last_ok = manager.state_now()
    manager.login_attempts = value['login_attempts']
    manager.status = 'ready'
    return True
