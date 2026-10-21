"""Real closed-period reads, concurrent health/token checks; no business records saved."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time
import urllib.parse
import urllib.request


def fetch(path, body=None, timeout=900):
    request = urllib.request.Request('http://127.0.0.1:8767' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json'})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise RuntimeError('verification_response_too_large')
        length = response.getheader('Content-Length')
        if length is not None and int(length) != len(raw):
            raise RuntimeError('verification_response_truncated')
        return json.loads(raw), round(time.monotonic() - started, 3), len(raw)


def main():
    before, _, _ = fetch('/health', timeout=15)
    assert before['ready']
    token_before, _, _ = fetch('/session/admin-token', timeout=15)
    samples = []
    stop = threading.Event()
    def monitor():
        while not stop.is_set():
            sample = {}
            for name, path in (('health', '/health'), ('token', '/session/admin-token')):
                try:
                    value, duration, _ = fetch(path, timeout=5)
                    sample[name] = {'ready': value.get('ready'), 'seconds': duration}
                except Exception as error:
                    sample[name] = {'ready': False, 'error_type': type(error).__name__}
            samples.append(sample)
            stop.wait(1)
    watcher = threading.Thread(target=monitor, daemon=True); watcher.start()
    report = {'started_at_epoch': time.time(), 'queries': []}
    try:
        for name, params in (
            ('fc_closed_34_day_summary', {'game': '1327', 'start': '2026-09-17 00:00', 'end': '2026-10-21 00:00'}),
            ('all_games_closed_112_day_summary', {'game': '', 'start': '2026-07-01 00:00', 'end': '2026-10-21 00:00'})):
            result, seconds, size = fetch('/business/summary?' + urllib.parse.urlencode(params), timeout=120)
            report['queries'].append({'name': name, 'query': params,
                'status': result.get('status'), 'seconds': seconds, 'response_bytes': size,
                'content_length_verified': True, 'period_matches': result.get('period') == {'start': params['start'], 'end': params['end']}})
            assert result.get('status') == 'available'
            assert report['queries'][-1]['period_matches']
    except Exception as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        stop.set(); watcher.join(timeout=12)
        report['concurrent_samples'] = samples
        after, _, _ = fetch('/health', timeout=15)
        token_after, _, _ = fetch('/session/admin-token', timeout=15)
        report['login_attempts_before'] = before['login_attempts']
        report['login_attempts_after'] = after['login_attempts']
        report['same_access_token'] = token_before.get('token') == token_after.get('token')
        report['health_ready'] = after.get('ready')
        report['concurrent_all_ready'] = bool(samples) and all(
            item[name]['ready'] for item in samples for name in ('health', 'token'))
        path = Path('/var/backups/fs-admin-continuity-20261021-v1/live-verification.json')
        path.write_text(json.dumps(report, indent=2)); path.chmod(0o600)
        print(json.dumps({k: v for k, v in report.items() if k != 'concurrent_samples'}), flush=True)
        print(json.dumps({'samples': len(samples), 'max_health_seconds': max(
            (v['health'].get('seconds', 0) for v in samples), default=None),
            'max_token_seconds': max((v['token'].get('seconds', 0) for v in samples), default=None)}), flush=True)
    assert report['concurrent_all_ready'] and report['health_ready']
    assert report['login_attempts_before'] == report['login_attempts_after']


if __name__ == '__main__':
    main()
