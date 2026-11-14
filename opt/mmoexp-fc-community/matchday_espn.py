"""ESPN scoreboard shape adapter for an isolated FC27 source trial.

Do not enable automated Discord publication until the partnership's data-use
scope and the specific access method have been verified by the owner.
"""

import hashlib
import json
import re
import urllib.request

from matchday_openligadb import MatchdaySourceError, _utc


API_ROOT = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
LEAGUES = {
    'pl': 'eng.1',
    'la1': 'esp.1',
    'bl1': 'ger.1',
    'ucl': 'uefa.champions',
    'fr1': 'fra.1',
}
MAX_RESPONSE = 2 * 1024 * 1024


def _positive_id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,17}', value):
        raise MatchdaySourceError('Invalid ' + label)
    return value


def fetch_scoreboard(league, day, opener=urllib.request.urlopen):
    """Fetch one league/day, never arbitrary URLs or unrestricted date ranges."""
    if league not in LEAGUES or not isinstance(day, str) or not re.fullmatch(r'20[2-9][0-9][01][0-9][0-3][0-9]', day):
        raise MatchdaySourceError('Invalid league or day')
    url = '%s/%s/scoreboard?dates=%s' % (API_ROOT, LEAGUES[league], day)
    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with opener(request, timeout=12) as response:
            data = response.read(MAX_RESPONSE + 1)
    except (OSError, TimeoutError) as exc:
        raise MatchdaySourceError('ESPN request failed') from exc
    if len(data) > MAX_RESPONSE:
        raise MatchdaySourceError('ESPN response too large')
    try:
        payload = json.loads(data.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise MatchdaySourceError('Invalid ESPN response') from exc
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise MatchdaySourceError('Missing ESPN events')
    if len(payload['events']) > 100:
        raise MatchdaySourceError('Too many ESPN events')
    return [normalize_event(event, league) for event in payload['events']]


def _score(value):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,2}', value):
        return int(value)
    raise MatchdaySourceError('Invalid score')


def normalize_event(raw, league):
    """Use scoreboard details only; large summary articles are unnecessary."""
    if league not in LEAGUES or not isinstance(raw, dict):
        raise MatchdaySourceError('Invalid ESPN match')
    event_id = _positive_id(raw.get('id'), 'ESPN event ID')
    competitions = raw.get('competitions')
    if not isinstance(competitions, list) or len(competitions) != 1:
        raise MatchdaySourceError('Invalid ESPN competition')
    competition = competitions[0]
    if not isinstance(competition, dict):
        raise MatchdaySourceError('Invalid ESPN competition')
    competitors = competition.get('competitors')
    if not isinstance(competitors, list) or len(competitors) != 2:
        raise MatchdaySourceError('Invalid ESPN competitors')
    sides = {item.get('homeAway'): item for item in competitors if isinstance(item, dict)}
    if set(sides) != {'home', 'away'}:
        raise MatchdaySourceError('Invalid ESPN sides')
    teams = {}
    for side in ('home', 'away'):
        team = sides[side].get('team')
        if not isinstance(team, dict) or not isinstance(team.get('displayName'), str):
            raise MatchdaySourceError('Invalid ESPN team')
        teams[side] = {
            'id': _positive_id(team.get('id'), 'ESPN team ID'),
            'name': team['displayName'].strip(),
        }
        if not teams[side]['name']:
            raise MatchdaySourceError('Missing ESPN team name')

    status = raw.get('status') or competition.get('status') or {}
    status_type = status.get('type') if isinstance(status, dict) else None
    state = status_type.get('state') if isinstance(status_type, dict) else None
    if state not in ('pre', 'in', 'post'):
        raise MatchdaySourceError('Unknown ESPN match state')
    score = None if state == 'pre' else [_score(sides['home'].get('score')), _score(sides['away'].get('score'))]
    details = competition.get('details') or []
    if not isinstance(details, list):
        raise MatchdaySourceError('Invalid ESPN event details')
    important = []
    duplicates = {}
    for detail in details:
        if not isinstance(detail, dict) or not (detail.get('scoringPlay') is True or detail.get('redCard') is True):
            continue
        kind = 'goal' if detail.get('scoringPlay') is True else 'red-card'
        clock = detail.get('clock') or {}
        team = detail.get('team') or {}
        athletes = detail.get('athletesInvolved') or []
        athlete = athletes[0] if athletes and isinstance(athletes[0], dict) else {}
        minute = clock.get('displayValue') if isinstance(clock, dict) else None
        if not isinstance(minute, str) or len(minute) > 24:
            continue
        team_id = team.get('id') if isinstance(team, dict) else None
        player_id = athlete.get('id') if isinstance(athlete, dict) else None
        stable = (event_id, kind, str(clock.get('value')), str(team_id), str(player_id))
        duplicate_index = duplicates.get(stable, 0)
        duplicates[stable] = duplicate_index + 1
        digest = hashlib.sha256(('|'.join(stable) + '|' + str(duplicate_index)).encode('utf-8')).hexdigest()[:20]
        player = athlete.get('displayName') if isinstance(athlete, dict) else None
        important.append({
            'id': event_id + ':' + digest, 'type': kind, 'minute': minute,
            'team_id': team_id, 'player': player.strip() if isinstance(player, str) else '',
            'penalty': detail.get('penaltyKick') is True,
            'own_goal': detail.get('ownGoal') is True,
        })

    source_url = ''
    for link in raw.get('links') or []:
        if isinstance(link, dict) and 'summary' in (link.get('rel') or []) and isinstance(link.get('href'), str):
            candidate = link['href']
            if candidate.startswith('https://www.espn.com/soccer/match/'):
                source_url = candidate
                break
    return {
        'provider': 'ESPN', 'league': league, 'fixture_id': event_id,
        'kickoff_utc': _utc(raw.get('date')),
        'home_team': teams['home'], 'away_team': teams['away'],
        'finished': status_type.get('completed') is True,
        'state': state, 'clock': status.get('displayClock'),
        'score': score, 'important_events': important,
        'source_url': source_url,
    }
