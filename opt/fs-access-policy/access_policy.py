"""Central policy for existing authenticated business routes, without credentials."""
import re
from urllib.parse import unquote, urlsplit, parse_qs
ADMINS = frozenset(('wulv', 'chenchao', 'DY'))
CONTROL = frozenset(('apply','execute','run','start','stop','pause','resume','reset','delete','save','update','set','clear','unlock','clear-lock','clear_lock','reset-lock','reset_lock','ban','unban','deploy','publish','restart','backfill','collect','refresh-now','refresh_now'))

def authorize(user, method, uri, group=''):
    if not user:
        return 401
    if user in ADMINS:
        return 200
    parsed = urlsplit(uri or '/')
    path = parsed.path
    for _ in range(3):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    segments = set(filter(None, re.split(r'[/\\]+', path.lower())))
    if group == 'deploy' or 'admin' in segments or 'deploy' in segments:
        return 403
    if (method or 'GET').upper() not in ('GET', 'HEAD'):
        return 403
    if segments & CONTROL:
        return 403
    for key, values in parse_qs(parsed.query).items():
        if key.lower() in ('action','op','command','cmd') and any(v.lower() in CONTROL for v in values):
            return 403
    return 200
