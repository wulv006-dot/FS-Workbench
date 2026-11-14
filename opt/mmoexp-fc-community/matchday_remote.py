"""Read the 183 matchday snapshot over a pinned, forced-command SSH route."""

import datetime
import json
import subprocess


MAX_WIRE = 2 * 1024 * 1024
HOST = '172.18.108.183'
USER = 'fc27-match-fetch'


class SnapshotUnavailable(RuntimeError):
    pass


def fetch_latest(key_path, known_hosts, runner=subprocess.run, now=None):
    if not key_path or not known_hosts:
        raise SnapshotUnavailable('Matchday transport not configured')
    command = [
        'ssh', '-T', '-i', str(key_path), '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=8', '-o', 'HostKeyAlias=47.85.170.62',
        '-o', 'UserKnownHostsFile=' + str(known_hosts), USER + '@' + HOST,
    ]
    try:
        result = runner(command, input=b'{"action":"latest"}\n', stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotUnavailable('Matchday transport unavailable') from exc
    if result.returncode or len(result.stdout) > MAX_WIRE:
        raise SnapshotUnavailable('Matchday snapshot unavailable')
    try:
        payload = json.loads(result.stdout)
        checked = datetime.datetime.fromisoformat(payload['checked_at_utc'])
        current = now or datetime.datetime.now(datetime.timezone.utc)
        age = current.astimezone(datetime.timezone.utc) - checked.astimezone(datetime.timezone.utc)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SnapshotUnavailable('Invalid matchday snapshot') from exc
    if (payload.get('schema_version') != 1 or not isinstance(payload.get('sources'), dict)
            or age < datetime.timedelta(minutes=-5) or age > datetime.timedelta(hours=9)):
        raise SnapshotUnavailable('Stale matchday snapshot')
    return payload
