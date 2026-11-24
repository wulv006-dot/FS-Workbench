"""Expose fresh FC27 observation receipts on the existing loopback-only price API."""

import argparse
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import runpy
from threading import Thread
import time
from uuid import uuid4

from .u4gm_browser import BROWSER_PLATFORMS, run_request, validate

OBSERVATION_PATH = '/fc27-observation'
MAX_REQUEST_BYTES = 2048
PROVIDER = 'windows_u4gm_snapshot'
_latest = None


def refresh_on_schedule():
    global _latest
    last_hour = None
    blocked_path = Path(__file__).resolve().parent.parent / 'u4gm-browser-access-hold.json'
    while True:
        now = datetime.now(timezone.utc)
        hour = now.date(), now.hour
        if now.minute == 15 and last_hour != hour and now.second >= 20:
            last_hour = hour
            if blocked_path.exists():
                receipt = {'offers': [], 'errors': ['source_blocked']}
            else:
                try:
                    receipt = run_request(dict(source='U4GM', run_id=str(uuid4()), wanted=[
                        [platform, quantity] for platform in BROWSER_PLATFORMS for quantity in ('100', '1000')]))
                except (ImportError, OSError, ValueError):
                    receipt = {'offers': [], 'errors': ['browser_runtime_unavailable']}
                if set(receipt['errors']) & {'http_401','http_403','http_429','challenge'}:
                    with blocked_path.open('x', encoding='utf-8') as blocked:
                        json.dump({'observed_at': now.isoformat(), 'errors': receipt['errors']}, blocked)
            _latest = dict(receipt, sampled_at=now.isoformat())
        time.sleep(5)


def read_snapshot(payload, latest, now):
    wanted = validate(payload)
    result = dict(source='U4GM', run_id=payload['run_id'], offers=[], errors=[], retry_after_seconds=0, provider=PROVIDER)
    if latest is None:
        return dict(result, errors=['browser_snapshot_unavailable'])
    if not 0 <= (now - datetime.fromisoformat(latest['sampled_at'])).total_seconds() <= 900:
        return dict(result, errors=['browser_snapshot_stale'])
    result['offers'] = [
        dict(offer, run_id=payload['run_id'])
        for offer in latest['offers']
        if ((offer['platform'], offer['purchase_k']) in wanted
            and 0 <= (now - datetime.fromisoformat(offer['captured_at'])).total_seconds() <= 900)
    ]
    result['errors'] = list(latest['errors'])
    if any(platform not in BROWSER_PLATFORMS for platform, _ in wanted):
        result['errors'].append('browser_platform_unavailable')
    if not result['offers'] and not result['errors']:
        result['errors'].append('browser_snapshot_unavailable')
    return result


def handler(base):
    class LocalQuoteHandler(base):
        def do_POST(self):
            if self.path != OBSERVATION_PATH:
                return self._send({'error': 'not_found'}, 404)
            if (self.headers.get('Origin') is not None
                    or self.headers.get('Host') != '127.0.0.1:' + str(self.server.server_port)
                    or self.headers.get('Content-Type') != 'application/json'):
                return self._send({'error': 'browser_observation_request_scope'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 <= size <= MAX_REQUEST_BYTES:
                    return self._send({'error': 'browser_observation_request_size'}, 400)
                payload = json.loads(self.rfile.read(size))
                receipt = read_snapshot(payload, _latest, datetime.now(timezone.utc))
            except (ValueError, TypeError, KeyError):
                return self._send({'error': 'browser_observation_request_invalid'}, 400)
            return self._send(receipt)

    return LocalQuoteHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-api', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8790)
    args = parser.parse_args()
    original = runpy.run_path(str(args.legacy_api.resolve(strict=True)))
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler(original['Handler'])) as server:
        Thread(target=refresh_on_schedule, daemon=True, name='u4gm-browser-observation').start()
        server.serve_forever()


if __name__ == '__main__':
    main()
