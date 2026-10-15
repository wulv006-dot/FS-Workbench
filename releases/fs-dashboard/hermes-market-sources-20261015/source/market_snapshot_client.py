"""Native Desktop entry; the existing Desktop identity never enters the result."""
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
import json
import re


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read():
    token = Path('/profile/.desktop-management/token').read_text('ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,80}', token):
        raise ValueError('desktop_identity_unavailable')
    request = Request('http://127.0.0.1:8940/fc/market-snapshot', json.dumps({'profile': 'FC27'}).encode(),
                      {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        raw = response.read(1000001)
    if len(raw) > 1000000:
        raise ValueError('market_response_size')
    data = json.loads(raw)
    if data.get('contract') != 'fc27-existing-market-readonly-v1':
        raise ValueError('market_response_contract')
    return data


if __name__ == '__main__':
    try:
        print(json.dumps(read(), ensure_ascii=False, allow_nan=False))
    except Exception:
        print(json.dumps({'status': 'not_available', 'reason': 'market_bridge_unavailable'}))
        raise SystemExit(1)
