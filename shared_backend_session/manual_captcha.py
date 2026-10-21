"""Human-entered challenge inbox for the sole Admin session owner. Never uses OCR."""
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
from urllib.parse import urlencode

ROOT = Path('/run/secrets/fs-manual-captcha')


def write(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    temp = path.with_suffix('.tmp')
    with temp.open('xb') as stream:
        os.chmod(temp, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def take(manager):
    info = ROOT.lstat()
    if not stat.S_ISDIR(info.st_mode) or (os.name == 'posix' and
            (info.st_uid != os.geteuid() or info.st_mode & 0o077)):
        raise PermissionError('manual_captcha_directory_permissions')
    pending = getattr(manager, '_manual_challenge', None)
    if pending is None:
        captcha_id = str(uuid.uuid4())
        status, png = manager.request('/api/common/captcha?' + urlencode({'server': '1', 'id': captcha_id}))
        if status != 200 or not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 1048576:
            manager.status = 'captcha_unavailable'
            return None
        pending = {'captcha_id': captcha_id, 'created': time.monotonic()}
        manager._manual_challenge = pending
        write(ROOT / 'captcha.png', png)
        write(ROOT / 'challenge.json', {'captcha_id': captcha_id, 'status': 'AWAITING_HUMAN',
                                        'created_epoch': time.time(), 'ocr_used': False})
    inbox = ROOT / 'input.json'
    if not inbox.exists():
        manager.status = 'manual_captcha_required'
        return None
    info = inbox.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 or (os.name == 'posix' and
            (info.st_uid != os.geteuid() or info.st_mode & 0o077)):
        raise PermissionError('manual_captcha_input_permissions')
    value = json.loads(inbox.read_text())
    inbox.unlink()
    if (not isinstance(value, dict) or set(value) != {'captcha_id', 'code'}
            or value['captcha_id'] != pending['captcha_id']
            or not isinstance(value['code'], str) or not re.fullmatch(r'\d{4,6}', value['code'])):
        manager.status = 'manual_captcha_invalid'
        return None
    if time.monotonic() - pending['created'] > 300:
        manager._manual_challenge = None
        manager.status = 'manual_captcha_expired'
        return None
    manager._manual_challenge = None
    write(ROOT / 'challenge.json', {'captcha_id': pending['captcha_id'], 'status': 'CONSUMED',
                                    'ocr_used': False})
    return pending['captcha_id'], value['code']
