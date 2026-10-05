"""Pure FC-only read scope from the archived nginx/backend contract, not portal membership."""
import re
from urllib.parse import urlsplit

PLAYERS_STATIC=frozenset(('', 'index.html','models.html','app.css','app.js','images.js'))
PLAYERS_READ=frozenset(('api/bootstrap','api/status','api/candidates','api/models','api/tags','api/jobs'))

def allowed_fc_read(uri, method):
    if method not in ('GET','HEAD') or not isinstance(uri,str) or len(uri)>4096:
        return False
    if any(ord(c)<32 for c in uri) or any(c in uri for c in ('\\','#')):
        return False
    parsed=urlsplit(uri)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
        return False
    path=parsed.path
    if '%' in path:return False
    if any(x in ('.','..') for x in path.split('/')) or '//' in path:
        return False
    ops='/s/wulv/fc27-ops/'
    players='/tools/fc27-players/'
    if path.startswith(ops):
        suffix=path[len(ops):]
        if suffix.startswith('api/'):
            return suffix=='api/health' or bool(re.fullmatch(r'api/jobs/[0-9a-f]{32}',suffix))
        return not suffix or (not any(x.startswith('.') for x in suffix.split('/'))
            and bool(re.fullmatch(r'[A-Za-z0-9_./-]+\.(?:html|js|css|json|png|jpg|jpeg|svg|webp|ico)',suffix)))
    if path.startswith(players):
        suffix=path[len(players):]
        return (suffix in PLAYERS_STATIC or suffix in PLAYERS_READ
            or bool(re.fullmatch(r'api/(?:plans|jobs)/[0-9a-f]{32}',suffix))
            or bool(re.fullmatch(r'api/auth/challenge/[0-9a-f]{32}/image',suffix)))
    return False
