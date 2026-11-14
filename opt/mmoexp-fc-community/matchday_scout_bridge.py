"""Add Hermes picks to the editorial plan when a public Smart Score card agrees."""

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from matchday_selector import parse_upcoming


UTC = dt.timezone.utc
LONDON = ZoneInfo('Europe/London')


def load_scout(path, now):
    if now.tzinfo is None:
        raise ValueError('Scout clock must be timezone-aware')
    source = Path(path)
    if source.stat().st_size > 65536:
        raise ValueError('Scout output too large')
    data = json.loads(source.read_text(encoding='utf-8'))
    generated = dt.datetime.fromisoformat(data['generated_at_utc'].replace('Z', '+00:00'))
    if generated.tzinfo is None:
        raise ValueError('Scout timestamp must be timezone-aware')
    age = now.astimezone(UTC) - generated.astimezone(UTC)
    if not dt.timedelta(seconds=-30) <= age <= dt.timedelta(hours=30):
        raise ValueError('Scout output is stale')
    matches = data['matches']
    if not isinstance(matches, list) or len(matches) > 2:
        raise ValueError('Invalid scout shortlist')
    for item in matches:
        if (not isinstance(item, dict) or
                any(not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ('home', 'away', 'date')) or
                item['date'] not in ((now.astimezone(LONDON).date() +
                                     dt.timedelta(days=days)).isoformat()
                                    for days in (0, 1, 2))):
            raise ValueError('Invalid scout fixture')
        question = item.get('question', '')
        if (not isinstance(question, str) or len(question) > 160 or
                '\n' in question or '\r' in question):
            raise ValueError('Invalid scout question')
    return matches


def _key(home, away, day):
    return (' '.join(home.casefold().split()),
            ' '.join(away.casefold().split()), day)


def merge_plan(matches, messages, plan, guild_id, channel_id, now, weekly_limit=2):
    """Preserve existing decisions and fill only verified weekly vacancies."""
    if plan.get('version') != 1 or not isinstance(plan.get('matches'), list):
        raise ValueError('Invalid existing editorial plan')
    current_week = now.astimezone(LONDON).isocalendar()[:2]
    existing = []
    for item in plan['matches']:
        kickoff = dt.datetime.fromisoformat(item['kickoff_utc'].replace('Z', '+00:00'))
        if kickoff.astimezone(LONDON).isocalendar()[:2] >= current_week:
            existing.append(item)
    available = {}
    for message in messages:
        for candidate in parse_upcoming(message, guild_id, channel_id, now):
            day = candidate.kickoff_at.astimezone(LONDON).date().isoformat()
            key = _key(candidate.home, candidate.away, day)
            previous = available.get(key)
            if previous is None or candidate.source_created_at > previous.source_created_at:
                available[key] = candidate
    receipt = {'added': [], 'unmatched': [], 'already_planned': [],
               'needs_review': [], 'capacity': []}
    for item in matches:
        key = _key(item['home'], item['away'], item['date'])
        candidate = available.get(key)
        label = '{} vs {}'.format(item['home'], item['away'])
        if candidate is None:
            receipt['unmatched'].append(label)
            continue
        same_teams = next((old for old in existing
                           if str(old.get('guild_id')) == str(guild_id) and
                           _key(old['home'], old['away'], '')[:2] == key[:2]), None)
        if same_teams is not None:
            old_kickoff = dt.datetime.fromisoformat(same_teams['kickoff_utc'].replace(
                'Z', '+00:00')).astimezone(UTC)
            (receipt['already_planned'] if
             same_teams.get('status') != 'hold' and
             old_kickoff == candidate.kickoff_at and
             same_teams['competition'].casefold() == candidate.competition.casefold()
             else receipt['needs_review']).append(label)
            continue
        week = candidate.kickoff_at.astimezone(LONDON).isocalendar()[:2]
        count = sum(1 for old in existing if str(old.get('guild_id')) == str(guild_id) and
                    dt.datetime.fromisoformat(old['kickoff_utc'].replace(
                        'Z', '+00:00')).astimezone(LONDON).isocalendar()[:2] == week)
        if count >= weekly_limit or len(existing) >= 8:
            receipt['capacity'].append(label)
            continue
        identity = '{}|{}|{}|{}'.format(guild_id, *key)
        selected = {
            'fixture_id': 'scout-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20],
            'guild_id': str(guild_id),
            'home': candidate.home,
            'away': candidate.away,
            'competition': candidate.competition,
            'kickoff_utc': candidate.kickoff_at.isoformat().replace('+00:00', 'Z'),
            'smart_score_message_url': candidate.source_url,
        }
        if isinstance(item.get('question'), str):
            selected['question'] = item['question']
        existing.append(selected)
        receipt['added'].append(label)
    return {'version': 1, 'matches': existing}, receipt


def replace_plan(path, expected_stat, plan):
    """Keep an operator edit made during the scan instead of overwriting it."""
    target = Path(path)
    current = target.stat()
    if (current.st_mtime_ns, current.st_size) != expected_stat:
        return False
    serialized = json.dumps(plan, ensure_ascii=False, indent=2) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(target.parent),
                                     prefix='.matchday-plan-', delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(serialized)
    try:
        os.chmod(temporary, current.st_mode & 0o777)
        if (target.stat().st_mtime_ns, target.stat().st_size) != expected_stat:
            return False
        os.replace(str(temporary), str(target))
        return True
    finally:
        temporary.unlink(missing_ok=True)
