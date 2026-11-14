"""Read-only FC27 football collector for 183. No Discord or customer access."""

import datetime
import json
import os
import time
import urllib.error

from matchday_espn import fetch_scoreboard
from matchday_espn_probe import write_snapshot
from matchday_openligadb import fetch_season_window


PRIMARY_LEAGUES = ('pl', 'la1', 'bl1', 'ucl')
ESPN_LEAGUES = PRIMARY_LEAGUES + ('fr1',)


def season_for(day):
    return day.year if day.month >= 7 else day.year - 1


def collect(now=None, openliga_fetch=fetch_season_window, espn_fetch=fetch_scoreboard):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Collection time must be timezone aware')
    now = now.astimezone(datetime.timezone.utc)
    day = now.date()
    start = datetime.datetime.combine(day - datetime.timedelta(days=1),
                                      datetime.time.min, datetime.timezone.utc)
    end = datetime.datetime.combine(day + datetime.timedelta(days=8),
                                    datetime.time.min, datetime.timezone.utc)
    snapshot = {
        'schema_version': 1, 'checked_at_utc': now.isoformat(),
        'season': season_for(day),
        'window_start_utc': start.isoformat(), 'window_end_utc': end.isoformat(),
        'sources': {'openligadb': {}, 'espn': {}}, 'health': [],
    }
    for league in PRIMARY_LEAGUES:
        started = time.monotonic()
        try:
            fixtures = openliga_fetch(league, snapshot['season'], start, end)
            snapshot['sources']['openligadb'][league] = fixtures
            row = {'source': 'openligadb', 'league': league, 'ok': True, 'fixtures': len(fixtures)}
        except Exception as exc:
            cause = getattr(exc, '__cause__', None)
            row = {'source': 'openligadb', 'league': league, 'ok': False,
                   'error_type': type(cause or exc).__name__,
                   'http_status': cause.code if isinstance(cause, urllib.error.HTTPError) else None}
        row['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        snapshot['health'].append(row)
    for league in ESPN_LEAGUES:
        fixtures = []
        # Cross-check the full displayed window before publishing a fixture.
        # Ligue 1 has no OpenLigaDB coverage and uses ESPN directly.
        forward_days = 7
        for offset in range(-1, forward_days + 1):
            target_day = (day + datetime.timedelta(days=offset)).strftime('%Y%m%d')
            started = time.monotonic()
            try:
                result = espn_fetch(league, target_day)
                fixtures.extend(result)
                row = {'source': 'espn', 'league': league, 'day': target_day,
                       'ok': True, 'fixtures': len(result)}
            except Exception as exc:
                cause = getattr(exc, '__cause__', None)
                row = {'source': 'espn', 'league': league, 'day': target_day,
                       'ok': False, 'error_type': type(cause or exc).__name__,
                       'http_status': cause.code if isinstance(cause, urllib.error.HTTPError) else None}
            row['elapsed_ms'] = round((time.monotonic() - started) * 1000)
            snapshot['health'].append(row)
        snapshot['sources']['espn'][league] = fixtures
    return snapshot


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    os.makedirs(args.state_dir, mode=0o700, exist_ok=True)
    snapshot = collect()
    path = write_snapshot(os.path.join(args.state_dir, 'snapshots'), snapshot)
    with open(os.path.join(args.state_dir, 'health.jsonl'), 'a', encoding='utf-8') as stream:
        stream.write(json.dumps({'checked_at_utc': snapshot['checked_at_utc'],
            'snapshot': os.path.basename(path), 'health': snapshot['health']},
            separators=(',', ':')) + '\n')
    print(json.dumps({'snapshot': os.path.basename(path),
        'sources_ok': sum(row['ok'] for row in snapshot['health']),
        'sources_total': len(snapshot['health'])}))
    return 0 if all(row['ok'] for row in snapshot['health']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
