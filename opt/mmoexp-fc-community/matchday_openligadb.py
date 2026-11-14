"""Read-only OpenLigaDB adapter for the FC27 matchday pilot.

The provider is community maintained. A score is not an authorization to
award prizes; callers must show the source and the time they fetched it.
"""

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone


SOURCE = 'OpenLigaDB'
SOURCE_CREDIT = 'Data: OpenLigaDB (ODbL 1.0)'
SOURCE_URL = 'https://www.openligadb.de/'
API_ROOT = 'https://api.openligadb.de'
USER_AGENT = 'MMOEXP-FC27-Matchday/0.1 (+https://www.mmoexp.com)'
MAX_RESPONSE = 2 * 1024 * 1024
LEAGUES = {
    'pl': 'Premier League',
    'la1': 'La Liga',
    'bl1': 'Bundesliga',
    'ucl': 'Champions League',
}


class MatchdaySourceError(Exception):
    pass


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MatchdaySourceError('Invalid ' + label)
    return value


def _league(value):
    if value not in LEAGUES:
        raise MatchdaySourceError('Unsupported league')
    return value


def _request_json(path, opener=urllib.request.urlopen):
    request = urllib.request.Request(API_ROOT + path, headers={
        'Accept': 'application/json', 'User-Agent': USER_AGENT,
    })
    try:
        with opener(request, timeout=12) as response:
            data = response.read(MAX_RESPONSE + 1)
    except (OSError, TimeoutError) as exc:
        raise MatchdaySourceError('Source request failed') from exc
    if len(data) > MAX_RESPONSE:
        raise MatchdaySourceError('Source response too large')
    try:
        return json.loads(data.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise MatchdaySourceError('Invalid source response') from exc


def fetch_group_if_changed(league, season, group_order, previous_change=None,
                           request_json=_request_json):
    """Poll the cheap change marker; load one group only after a change."""
    league = _league(league)
    season = _integer(season, 'season')
    group_order = _integer(group_order, 'group order')
    if not 2020 <= season <= 2100 or group_order > 60:
        raise MatchdaySourceError('Invalid season or group order')
    path = '/getlastchangedate/%s/%s/%s' % (league, season, group_order)
    changed_at = request_json(path)
    if not isinstance(changed_at, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT[0-9:.]+', changed_at):
        raise MatchdaySourceError('Invalid change marker')
    if changed_at == previous_change:
        return changed_at, None
    matches = request_json('/getmatchdata/%s/%s/%s' % (league, season, group_order))
    if not isinstance(matches, list) or len(matches) > 30:
        raise MatchdaySourceError('Invalid match group')
    return changed_at, [normalize_match(item, league) for item in matches]


def fetch_season_window(league, season, start_utc, end_utc, request_json=_request_json):
    """Read one season and retain only fixtures in a bounded UTC date window."""
    league = _league(league)
    season = _integer(season, 'season')
    if not 2020 <= season <= 2100:
        raise MatchdaySourceError('Invalid season')
    if (not isinstance(start_utc, datetime) or not isinstance(end_utc, datetime)
            or start_utc.tzinfo is None or end_utc.tzinfo is None
            or end_utc <= start_utc or end_utc - start_utc > timedelta(days=14)):
        raise MatchdaySourceError('Invalid fixture window')
    raw = request_json('/getmatchdata/%s/%s' % (league, season))
    if not isinstance(raw, list) or len(raw) > 450:
        raise MatchdaySourceError('Invalid season response')
    selected = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get('matchDateTimeUTC'), str):
            continue
        kickoff = datetime.fromisoformat(_utc(item['matchDateTimeUTC']))
        if start_utc <= kickoff < end_utc:
            selected.append(normalize_match(item, league))
    selected.sort(key=lambda item: (item['kickoff_utc'], item['fixture_id']))
    return selected


def _utc(value):
    if not isinstance(value, str):
        raise MatchdaySourceError('Missing kickoff')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise MatchdaySourceError('Invalid kickoff') from exc
    if parsed.tzinfo is None:
        raise MatchdaySourceError('Kickoff has no timezone')
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_match(raw, league):
    """Return minimal factual fields; do not infer that a past kickoff is live."""
    if not isinstance(raw, dict):
        raise MatchdaySourceError('Invalid match')
    league = _league(league)
    match_id = _integer(raw.get('matchID'), 'match ID')
    home = raw.get('team1') or {}
    away = raw.get('team2') or {}
    if not isinstance(home, dict) or not isinstance(away, dict):
        raise MatchdaySourceError('Invalid teams')
    home_id = _integer(home.get('teamId'), 'home team ID')
    away_id = _integer(away.get('teamId'), 'away team ID')
    home_name, away_name = home.get('teamName'), away.get('teamName')
    if (not isinstance(home_name, str) or not home_name.strip()
            or not isinstance(away_name, str) or not away_name.strip()):
        raise MatchdaySourceError('Missing team name')
    finished = raw.get('matchIsFinished')
    if type(finished) is not bool:
        raise MatchdaySourceError('Missing match status')
    goals = []
    for goal in raw.get('goals') or []:
        if not isinstance(goal, dict):
            continue
        goal_id = goal.get('goalID')
        minute = goal.get('matchMinute')
        score_home = goal.get('scoreTeam1')
        score_away = goal.get('scoreTeam2')
        if (type(goal_id) is not int or goal_id <= 0 or type(minute) is not int
                or minute < 0 or minute > 130 or type(score_home) is not int
                or type(score_away) is not int or score_home < 0 or score_away < 0
                or score_home + score_away == 0):
            continue  # Some leagues include a synthetic 0-0 entry.
        player = goal.get('goalGetterName')
        goals.append({
            'id': '%s:%s' % (match_id, goal_id), 'minute': minute,
            'home_score': score_home, 'away_score': score_away,
            'scoring_team_id': goal.get('scoringTeamId'),
            'player': player.strip() if isinstance(player, str) else '',
            'penalty': goal.get('isPenalty') is True,
            'own_goal': goal.get('isOwnGoal') is True,
        })
    goals.sort(key=lambda item: (item['minute'], int(item['id'].split(':', 1)[1])))

    score = None
    if finished:
        results = raw.get('matchResults') or []
        final = next((item for item in results if isinstance(item, dict)
                      and item.get('resultTypeKind') == 'After90Minutes'), None)
        if final and type(final.get('pointsTeam1')) is int and type(final.get('pointsTeam2')) is int:
            score = [final['pointsTeam1'], final['pointsTeam2']]
    elif goals:
        score = [goals[-1]['home_score'], goals[-1]['away_score']]

    group = raw.get('group') or {}
    if not isinstance(group, dict):
        raise MatchdaySourceError('Invalid match group')
    return {
        'provider': SOURCE, 'league': league, 'league_name': LEAGUES[league],
        'fixture_id': str(match_id), 'group_order': group.get('groupOrderID'),
        'kickoff_utc': _utc(raw.get('matchDateTimeUTC')),
        'home_team': {'id': home_id, 'name': home_name.strip()},
        'away_team': {'id': away_id, 'name': away_name.strip()},
        'finished': finished, 'score': score, 'goals': goals,
        'attribution': SOURCE_CREDIT, 'attribution_url': SOURCE_URL,
    }
