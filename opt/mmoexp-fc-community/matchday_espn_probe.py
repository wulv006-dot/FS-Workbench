"""Isolated read-only ESPN scoreboard probe. Never publishes to Discord."""

import argparse
import datetime
import json
import os
import tempfile
import time
import urllib.error

from matchday_espn import LEAGUES, fetch_scoreboard


def collect(day, leagues):
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows = []
    snapshots = {}
    for league in leagues:
        started = time.monotonic()
        row = {'league': league, 'checked_at_utc': checked_at, 'day': day}
        try:
            fixtures = fetch_scoreboard(league, day)
            snapshots[league] = fixtures
            row.update({
                'result': 'ok', 'http_status': 200,
                'fixtures': len(fixtures),
                'live': sum(item['state'] == 'in' for item in fixtures),
                'finished': sum(item['finished'] for item in fixtures),
                'goals': sum(sum(event['type'] == 'goal' for event in item['important_events']) for item in fixtures),
                'red_cards': sum(sum(event['type'] == 'red-card' for event in item['important_events']) for item in fixtures),
            })
        except Exception as exc:
            cause = getattr(exc, '__cause__', None)
            row.update({
                'result': 'error',
                'http_status': cause.code if isinstance(cause, urllib.error.HTTPError) else None,
                'error_type': type(cause or exc).__name__,
            })
        row['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        rows.append(row)
    return rows, {'provider': 'ESPN', 'checked_at_utc': checked_at,
                  'day': day, 'fixtures_by_league': snapshots}


def write_snapshot(directory, snapshot):
    os.makedirs(directory, mode=0o700, exist_ok=True)
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = os.path.join(directory, run_id + '.json')
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix='.probe-', dir=directory)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(snapshot, stream, ensure_ascii=False, separators=(',', ':'))
            stream.write('\n')
        os.replace(temporary, target)
        temporary = None
        return target
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', default=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d'))
    parser.add_argument('--league', action='append', choices=sorted(LEAGUES))
    parser.add_argument('--log', default='')
    parser.add_argument('--snapshot-dir', default='')
    args = parser.parse_args()
    os.umask(0o077)
    rows, snapshot = collect(args.day, args.league or list(LEAGUES))
    if args.snapshot_dir:
        write_snapshot(args.snapshot_dir, snapshot)
    for row in rows:
        line = json.dumps(row, sort_keys=True, separators=(',', ':'))
        print(line)
        if args.log:
            with open(args.log, 'a', encoding='utf-8') as stream:
                stream.write(line + '\n')
    return 0 if all(row['result'] == 'ok' for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
