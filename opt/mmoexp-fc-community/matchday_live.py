"""Low-frequency idle, 30-second focus-match collection on 183."""

import datetime
import json
import os
import re
import tempfile

from matchday_espn import fetch_scoreboard
from matchday_openligadb import fetch_group_if_changed


STATE_DIR = '/var/lib/fc27-matchday-collector'
MAX_FOCUS = 5


def _latest_base(state_dir):
    folder = os.path.join(state_dir, 'snapshots')
    names = sorted(name for name in os.listdir(folder) if name.endswith('.json'))
    if not names:
        raise ValueError('No base snapshot')
    with open(os.path.join(folder, names[-1]), encoding='utf-8') as stream:
        return json.load(stream)


def _focus_config(state_dir):
    path = os.path.join(state_dir, 'focus.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as stream:
        payload = json.load(stream)
    items = payload.get('fixtures') if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) > MAX_FOCUS:
        raise ValueError('Invalid focus list')
    for item in items:
        if (not isinstance(item, dict) or set(item) != {'league', 'openliga_id', 'espn_id'}
                or item['league'] not in ('pl', 'la1', 'bl1', 'ucl')
                or any(not isinstance(item[key], str) or not re.fullmatch(r'[1-9][0-9]{0,17}', item[key])
                       for key in ('openliga_id', 'espn_id'))):
            raise ValueError('Invalid focus mapping')
    return items


def _atomic_json(path, payload):
    folder = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.live-', dir=folder)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(',', ':'))
            stream.write('\n')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def collect_live(state_dir=STATE_DIR, now=None,
                 group_fetch=fetch_group_if_changed, espn_fetch=fetch_scoreboard):
    now = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(datetime.timezone.utc)
    base = _latest_base(state_dir)
    focus = _focus_config(state_dir)
    prior_path = os.path.join(state_dir, 'live.json')
    with open(prior_path, encoding='utf-8') if os.path.exists(prior_path) else open(os.devnull) as stream:
        try:
            prior = json.load(stream)
        except ValueError:
            prior = {}
    previous = {item['openliga_id']: item for item in prior.get('fixtures', [])}
    output = {'schema_version': 1, 'checked_at_utc': now.isoformat(),
              'fixtures': [], 'health': []}
    groups, scoreboards = {}, {}
    for item in focus:
        league, primary_id, backup_id = item['league'], item['openliga_id'], item['espn_id']
        candidate = next((fixture for fixture in base['sources']['openligadb'].get(league, [])
                          if fixture['fixture_id'] == primary_id), None)
        if not candidate:
            output['health'].append({'fixture_id': primary_id, 'error': 'missing_base_fixture'})
            continue
        kickoff = datetime.datetime.fromisoformat(candidate['kickoff_utc'])
        if not (kickoff - datetime.timedelta(minutes=45) <= now <= kickoff + datetime.timedelta(hours=4)):
            continue
        group = candidate.get('group_order')
        if type(group) is not int or group <= 0:
            output['health'].append({'fixture_id': primary_id, 'error': 'missing_group'})
            continue
        prior_item = previous.get(primary_id, {})
        marker = prior_item.get('marker')
        key = (league, group)
        if key not in groups:
            try:
                groups[key] = group_fetch(league, base['season'], group, marker)
            except Exception:
                groups[key] = (marker, None)
                output['health'].append({'fixture_id': primary_id, 'error': 'openliga_unavailable'})
        new_marker, matches = groups[key]
        primary = next((match for match in matches or [] if match['fixture_id'] == primary_id), None)
        if primary is None:
            primary = prior_item.get('openligadb') or candidate
        day = kickoff.strftime('%Y%m%d')
        key = (league, day)
        if key not in scoreboards:
            try:
                scoreboards[key] = espn_fetch(league, day)
            except Exception:
                scoreboards[key] = []
                output['health'].append({'fixture_id': primary_id, 'error': 'espn_unavailable'})
        backup = next((match for match in scoreboards[key] if match['fixture_id'] == backup_id), None)
        output['fixtures'].append({'league': league, 'openliga_id': primary_id,
            'espn_id': backup_id, 'marker': new_marker,
            'openligadb': primary, 'espn': backup})
    _atomic_json(prior_path, output)
    return output


if __name__ == '__main__':
    result = collect_live()
    print(json.dumps({'active': len(result['fixtures']), 'errors': len(result['health'])}))
