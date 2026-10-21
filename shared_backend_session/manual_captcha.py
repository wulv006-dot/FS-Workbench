"""OCR captcha solver for the sole Admin session owner.

替换 continuity-read90 镜像里的「人工投递」版本：仍走同一 ddddocr 模型，
但不需要人值守。识别不可读时重取验证码，最多 FC27_OCR_ATTEMPTS 次。
"""
import os
import re
import time
import uuid
from urllib.parse import urlencode

MAX_ATTEMPTS = max(1, min(10, int(os.environ.get('FC27_OCR_ATTEMPTS', '5'))))
CODE_RE = re.compile(r'^\d{4,6}$')


def _clean(value):
    if not isinstance(value, str):
        value = ''
    return re.sub(r'\D', '', value)


def take(manager):
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        captcha_id = str(uuid.uuid4())
        try:
            status, png = manager.request(
                '/api/common/captcha?' + urlencode({'server': '1', 'id': captcha_id}))
        except (OSError, ValueError, TypeError) as error:
            last_error = type(error).__name__
            manager.status = 'captcha_unavailable'
            time.sleep(1.0 * attempt)
            continue
        if status != 200 or not isinstance(png, (bytes, bytearray)) \
                or not bytes(png).startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 1048576:
            last_error = 'captcha_http_%s' % status
            manager.status = 'captcha_unavailable'
            time.sleep(1.0 * attempt)
            continue
        try:
            code = _clean(manager.ocr.classification(bytes(png)))
        except Exception as error:  # noqa: BLE001 - OCR 引擎异常不应中断登录流程
            last_error = type(error).__name__
            code = ''
        if CODE_RE.match(code):
            manager.status = 'captcha_solved'
            return captcha_id, code
        last_error = 'captcha_unreadable'
        manager.status = 'captcha_ocr_unreadable'
        time.sleep(0.6 * attempt)
    manager.status = 'captcha_ocr_failed:%s' % (last_error or 'unknown')
    return None
