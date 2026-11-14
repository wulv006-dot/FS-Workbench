"""Discord matchday card rendering from verified 183 snapshots."""

import datetime
import difflib
import re


LEAGUE_NAMES = {'pl': 'Premier League', 'la1': 'La Liga',
                'bl1': 'Bundesliga', 'ucl': 'Champions League', 'fr1': 'Ligue 1'}


def _safe(value):
    value = str(value or '').replace('@', '@\u200b')
    return re.sub(r'([*_`~|>])', r'\\\1', value)[:120]


def _timestamp(value):
    return int(datetime.datetime.fromisoformat(value).timestamp())


def _fixtures(snapshot):
    result = []
    espn = snapshot.get('sources', {}).get('espn', {})
    for league, items in snapshot.get('sources', {}).get('openligadb', {}).items():
        if league not in LEAGUE_NAMES or not isinstance(items, list):
            continue
        for item in items:
            if (isinstance(item, dict) and isinstance(item.get('kickoff_utc'), str)
                    and any(_same_fixture(item, other) for other in espn.get(league, []))):
                result.append(item)
    # OpenLigaDB has no Ligue 1 coverage; use ESPN for that league only.
    for item in snapshot.get('sources', {}).get('espn', {}).get('fr1', []):
        if isinstance(item, dict) and isinstance(item.get('kickoff_utc'), str):
            result.append(item)
    return result


def _team_name(value):
    return re.sub(r'\b(fc|cf|afc|sc|club|football)\b', '',
                  re.sub(r'[^a-z0-9 ]', ' ', str(value).lower())).strip()


def _same_fixture(primary, backup):
    if not isinstance(backup, dict) or primary.get('league') != backup.get('league'):
        return False
    try:
        gap = abs(datetime.datetime.fromisoformat(primary['kickoff_utc']) -
                  datetime.datetime.fromisoformat(backup['kickoff_utc']))
        names = [(primary['home_team']['name'], backup['home_team']['name']),
                 (primary['away_team']['name'], backup['away_team']['name'])]
    except (KeyError, TypeError, ValueError):
        return False
    return gap <= datetime.timedelta(minutes=90) and all(
        difflib.SequenceMatcher(None, _team_name(a), _team_name(b)).ratio() >= 0.72
        for a, b in names)


def render_card(snapshot, *, guild_id, discuss_channel_id, players_channel_id, now=None):
    if snapshot.get('schema_version') != 1:
        raise ValueError('Invalid matchday snapshot')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    fixtures = _fixtures(snapshot)
    live = {item.get('openliga_id'): item for item in snapshot.get('live', {}).get('fixtures', [])
            if isinstance(item, dict)}
    upcoming = []
    for fixture in fixtures:
        kickoff = datetime.datetime.fromisoformat(fixture['kickoff_utc'])
        if kickoff < now - datetime.timedelta(hours=4) or fixture.get('finished'):
            continue
        upcoming.append((kickoff, fixture))
    # A live focus match must not disappear behind five later fixtures.
    upcoming.sort(key=lambda pair: (0 if pair[1]['fixture_id'] in live else 1,
                                     pair[0], pair[1]['fixture_id']))
    lines = []
    for kickoff, fixture in upcoming[:5]:
        league = fixture['league']
        title = '%s vs %s' % (_safe(fixture['home_team']['name']),
                              _safe(fixture['away_team']['name']))
        overlay = live.get(fixture['fixture_id'])
        score_text = ''
        if overlay:
            primary = overlay.get('openligadb') or {}
            backup = overlay.get('espn') or {}
            pscore, bscore = primary.get('score'), backup.get('score')
            if pscore is not None and bscore is not None and pscore != bscore:
                score_text = ' · **%s–%s** (OpenLigaDB, checking)' % tuple(pscore)
            elif pscore is not None:
                score_text = ' · **%s–%s**' % tuple(pscore)
            elif bscore is not None:
                score_text = ' · **%s–%s** (ESPN)' % tuple(bscore)
        lines.append('**%s** · %s%s\n<t:%s:f>' %
                     (_safe(LEAGUE_NAMES[league]), title, score_text, int(kickoff.timestamp())))
    description = ('🏟️ **Next fixtures**\n\n' + '\n\n'.join(lines) if lines else
                   '🏟️ No selected league fixtures in the next week. Check back soon.')
    checked = _timestamp(snapshot['checked_at_utc'])
    description += '\n\n🕒 Updated <t:%s:R> · Times display in your local timezone.' % checked
    buttons = [
        {'type': 2, 'style': 5, 'label': '💬 Match chat',
         'url': 'https://discord.com/channels/%s/%s' % (guild_id, discuss_channel_id)},
    ]
    if players_channel_id:
        buttons.append({'type': 2, 'style': 5, 'label': '🃏 FC27 Players',
                        'url': 'https://discord.com/channels/%s/%s' % (guild_id, players_channel_id)})
    components = [{'type': 1, 'components': buttons}]
    return {'embeds': [{'title': '⚽ MMOEXP · FC27 Matchday', 'description': description,
                        'color': 0x137BDF,
                        'footer': {'text': 'OpenLigaDB (ODbL 1.0) · ESPN backup · No betting'}}],
            'components': components, 'allowed_mentions': {'parse': []}}
