"""Forced-command read-only SSH worker on 183; exposes only latest matchday snapshot."""

import glob
import datetime
import json
import os
import sys


STATE_DIR = '/var/lib/fc27-matchday-collector'
MAX_SNAPSHOT = 2 * 1024 * 1024


def read_latest(state_dir, request, now=None):
    if len(request) > 128 or json.loads(request) != {'action': 'latest'}:
        raise ValueError('Invalid request')
    directory = os.path.join(state_dir, 'snapshots')
    paths = sorted(glob.glob(os.path.join(directory, '*.json')))
    if not paths:
        raise FileNotFoundError('No snapshot')
    path = paths[-1]
    if os.path.getsize(path) > MAX_SNAPSHOT:
        raise ValueError('Snapshot too large')
    with open(path, 'rb') as stream:
        content = stream.read(MAX_SNAPSHOT + 1)
    if len(content) > MAX_SNAPSHOT:
        raise ValueError('Snapshot too large')
    data = json.loads(content)
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or not isinstance(data.get('sources'), dict)
            or not isinstance(data.get('checked_at_utc'), str)):
        raise ValueError('Invalid snapshot')
    live_path = os.path.join(state_dir, 'live.json')
    if os.path.exists(live_path) and os.path.getsize(live_path) <= MAX_SNAPSHOT:
        try:
            with open(live_path, encoding='utf-8') as stream:
                live = json.load(stream)
            checked = datetime.datetime.fromisoformat(live['checked_at_utc'])
            current = now or datetime.datetime.now(datetime.timezone.utc)
            age = current.astimezone(datetime.timezone.utc) - checked.astimezone(datetime.timezone.utc)
            if (live.get('schema_version') == 1 and isinstance(live.get('fixtures'), list)
                    and datetime.timedelta(minutes=-1) <= age <= datetime.timedelta(minutes=2)):
                data['live'] = live
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            pass
    combined = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(combined) > MAX_SNAPSHOT:
        raise ValueError('Snapshot too large')
    return combined


def main():
    try:
        payload = read_latest(STATE_DIR, sys.stdin.buffer.read(129))
    except (ValueError, OSError, json.JSONDecodeError):
        print('snapshot_unavailable', file=sys.stderr)
        return 1
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
