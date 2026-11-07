"""Public-news collector routing. No Discord publication or customer access."""
import json
import subprocess
import time
import urllib.error

MAX_WIRE = 14 * 1024 * 1024


class CollectionError(RuntimeError):
    def __init__(self, attempts):
        self.attempts = attempts
        super().__init__('News collection failed: ' + ', '.join(
            a['collector'] + ':' + a['error'] for a in attempts))


def error_code(exc):
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return 'timeout'
    if isinstance(exc, urllib.error.HTTPError):
        return 'http_' + str(exc.code)
    if isinstance(exc, urllib.error.URLError):
        return 'network'
    if isinstance(exc, ValueError):
        return 'invalid_response'
    if isinstance(exc, FileNotFoundError):
        return 'remote_unavailable'
    return 'collector_error'


def collect(source_id, mode, local_fetch, remote_fetch):
    """Callbacks accept source_id and return parsed rows; parsing must also succeed."""
    if mode not in ('187', '183', 'auto'):
        raise ValueError('Unknown collector route')
    attempts = []
    for node in (('187', '183') if mode == 'auto' else (mode,)):
        started = time.monotonic()
        try:
            rows = (local_fetch if node == '187' else remote_fetch)(source_id)
            if not isinstance(rows, list) or not rows:
                raise ValueError('No news records')
            attempts.append(dict(collector=node, ok=True,
                                 elapsed_ms=round((time.monotonic()-started)*1000)))
            return rows, dict(source=source_id, collector=node,
                              fallback=len(attempts)>1, attempts=attempts,
                              checked_at=int(time.time()))
        except Exception as exc:
            attempts.append(dict(collector=node, ok=False, error=error_code(exc),
                                 elapsed_ms=round((time.monotonic()-started)*1000)))
    raise CollectionError(attempts)


def fetch_remote_html(source_id, *, key_path, known_hosts, host='172.18.108.183',
                      user='fc27-news-fetch'):
    """Use a dedicated forced-command SSH key, NEVER the admin/root SSH key."""
    if source_id not in ('mmoexp', 'ea') or user != 'fc27-news-fetch' or host != '172.18.108.183':
        raise ValueError('Unrecognized collection target')
    command = ['ssh', '-T', '-i', str(key_path), '-o', 'BatchMode=yes',
               '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=8', '-o', 'HostKeyAlias=47.85.170.62',
               '-o', 'UserKnownHostsFile='+str(known_hosts),
               user+'@'+host]
    # Worker output is bounded; communicate timeout also bounds stalled DNS/reads.
    result = subprocess.run(command, input=json.dumps({'source': source_id})+'\n',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=40, check=False)
    if result.returncode:
        raise RuntimeError('Remote collector failed')
    if len(result.stdout.encode('utf-8')) > MAX_WIRE:
        raise ValueError('Remote response too large')
    body = json.loads(result.stdout)
    if set(body) != {'source', 'html'} or body['source'] != source_id or not isinstance(body['html'], str):
        raise ValueError('Invalid remote envelope')
    if len(body['html'].encode('utf-8')) > 2*1024*1024:
        raise ValueError('Remote HTML too large')
    return body['html']
