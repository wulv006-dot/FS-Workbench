"""Remove credentials while preserving authorized business identifiers."""
import re

from tools.export_fs_space import SECRET, KEY_PATH, ASSIGNMENT

AUTH_HEADER = re.compile(r'(?i)\b(?:proxy-)?authorization\s*:\s*(?:Bearer|Basic)\s+[A-Za-z0-9+/._~=-]+')
COOKIE_HEADER = re.compile(r'(?im)\b(?:set-)?cookie\s*:\s*[^\r\n]+')
CREDENTIAL_VALUE = re.compile(r'''(?ix)
    (?<!\w)["']?(?:password|password_hash|passwd|access_token|refresh_token|id_token|
    csrf|csrf_token|batoken|api[_-]?key|client_secret|secret|token|cookie|session_cookie|authorization)["']?
    \s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)
''')


def redact(text):
    for pattern in (SECRET, KEY_PATH, AUTH_HEADER, COOKIE_HEADER, CREDENTIAL_VALUE, ASSIGNMENT):
        text = pattern.sub('[凭据已移除]', text)
    return text


def redact_data(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    return value
