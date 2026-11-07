"""Forced-command, public fixed-source fetcher. No credentials, DB or publication."""
import json
import sys
import urllib.request

SOURCES = {'mmoexp': 'https://www.mmoexp.com/News/game/fc-27.html',
           'ea': 'https://www.ea.com/games/ea-sports-fc/fc-27/news'}
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect_disabled')


def fetch(request):
    if not isinstance(request, dict) or set(request) != {'source'} or request['source'] not in SOURCES:
        raise ValueError('source_not_allowed')
    url = SOURCES[request['source']]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 MMOEXP-FC27-News/1.0'})
    with opener.open(req, timeout=25) as response:
        if response.geturl() != url:
            raise ValueError('unexpected_url')
        raw = response.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError('response_too_large')
    return {'source': request['source'], 'html': raw.decode('utf-8')}


if __name__ == '__main__':
    try:
        line = sys.stdin.buffer.readline(257)
        if len(line) > 256:
            raise ValueError('request_too_large')
        print(json.dumps(fetch(json.loads(line)), ensure_ascii=True))
    except Exception as exc:
        # No upstream response bodies, environment or URL query strings in errors.
        print(type(exc).__name__, file=sys.stderr)
        sys.exit(1)
