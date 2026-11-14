"""Select a small number of source-linked football fixtures for Matchday Host.

This module never queries a fixture provider or invents a match. A caller must
pass public Smart Score messages it is authorized to read. No public post is
made here; the existing editorial worker verifies the source again at send.
"""

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from matchday_engagement import SMART_SCORE_ID


UTC = dt.timezone.utc
LONDON = ZoneInfo('Europe/London')
NEW_YORK = ZoneInfo('America/New_York')
LOS_ANGELES = ZoneInfo('America/Los_Angeles')
SOURCE_MAX_AGE = dt.timedelta(hours=6)
HORIZON = dt.timedelta(hours=48)
MIN_LEAD = dt.timedelta(minutes=15)
LEAGUE_WEIGHTS = {
    'premier league': 100,
    'uefa champions league': 95,
    'la liga': 85,
    'bundesliga': 80,
    'serie a': 78,
    'ligue 1': 75,
    'uefa nations league': 70,
}
# Smart Score's visible league picker contains several identical "Premier
# League" entries. Only a club name that identifies the English competition
# can turn that otherwise ambiguous label into an editorial candidate.
ENGLISH_FOCUS_CLUBS = frozenset({
    'arsenal', 'aston villa', 'chelsea', 'liverpool', 'manchester city',
    'manchester united', 'newcastle united', 'tottenham hotspur',
})
FOCUS_CLUBS_BY_LEAGUE = {
    'premier league': ENGLISH_FOCUS_CLUBS,
    'la liga': frozenset({'real madrid', 'barcelona', 'atletico madrid'}),
    'bundesliga': frozenset({'bayern munich', 'borussia dortmund',
                             'bayer leverkusen'}),
    'serie a': frozenset({'juventus', 'inter milan', 'ac milan', 'napoli'}),
    'ligue 1': frozenset({'paris saint-germain', 'marseille', 'lyon'}),
}
PLAN_NAME = re.compile(r"[\w .&'()/-]+\Z")
TEAM_LINE = re.compile(r'\*\*([^*\n]+)\*\*\s+vs\s+\*\*([^*\n]+)\*\*', re.I)
LEAGUE_LINE = re.compile(r'\*\*League\*\*:\s*([^\n]+)')
STATUS_LINE = re.compile(r'\*\*Status\*\*:\s*([^\n]+)')
KICKOFF_LINE = re.compile(r'\*\*Kickoff\*\*:\s*<t:(\d{9,11}):[tTdDfFR]>')


@dataclass(frozen=True)
class Candidate:
    guild_id: int
    home: str
    away: str
    competition: str
    kickoff_at: dt.datetime
    source_url: str
    source_message_id: int
    source_created_at: dt.datetime

    @property
    def identity(self):
        return (self.home.casefold(), self.away.casefold(), self.competition.casefold())


def parse_upcoming(message, guild_id, channel_id, now):
    """Return zero or more independently verified fields from one app card."""
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    now = now.astimezone(UTC)
    author = getattr(message, 'author', None)
    guild = getattr(message, 'guild', None)
    channel = getattr(message, 'channel', None)
    created = getattr(message, 'created_at', None)
    if (not author or author.id != SMART_SCORE_ID or author.bot is not True or
            not guild or guild.id != guild_id or not channel or channel.id != channel_id or
            (getattr(message, 'webhook_id', None) is not None and
             (getattr(message, 'application_id', None) != SMART_SCORE_ID or
              getattr(getattr(message, 'type', None), 'value', None) != 20)) or
            not created or created.tzinfo is None or
            not isinstance(getattr(message, 'id', None), int) or
            not isinstance(getattr(message, 'jump_url', None), str)):
        return []
    created = created.astimezone(UTC)
    if not -dt.timedelta(seconds=30) <= now - created <= SOURCE_MAX_AGE:
        return []
    expected_url = 'https://discord.com/channels/{}/{}/{}'.format(
        guild_id, channel_id, message.id)
    if message.jump_url != expected_url:
        return []
    found = []
    for embed in getattr(message, 'embeds', ()) or ():
        if getattr(embed, 'title', None) != 'Upcoming Matches':
            continue
        for field in getattr(embed, 'fields', ()) or ():
            name = str(getattr(field, 'name', ''))
            value = str(getattr(field, 'value', ''))
            teams = TEAM_LINE.search(name)
            league = LEAGUE_LINE.search(value)
            status = STATUS_LINE.search(value)
            kickoff = KICKOFF_LINE.search(value)
            if not (teams and league and status and kickoff):
                continue
            home, away = teams[1].strip(), teams[2].strip()
            competition = league[1].strip()
            if (not 2 <= len(home) <= 60 or not 2 <= len(away) <= 60 or
                    not 2 <= len(competition) <= 60 or
                    not all(PLAN_NAME.fullmatch(value) for value in
                            (home, away, competition)) or
                    status[1].strip() != 'Not Started'):
                continue
            time = dt.datetime.fromtimestamp(int(kickoff[1]), UTC)
            if not MIN_LEAD <= time - now <= HORIZON:
                continue
            found.append(Candidate(guild_id, home, away, competition, time,
                                   expected_url, message.id, created))
    return found


def score(candidate, preferred_clubs=()):
    """Give a deterministic explanation; the source remains authoritative."""
    league = candidate.competition.casefold()
    base = LEAGUE_WEIGHTS.get(league)
    if base is None:
        return None
    if (league in FOCUS_CLUBS_BY_LEAGUE and
            not ({candidate.home.casefold(), candidate.away.casefold()} &
                 FOCUS_CLUBS_BY_LEAGUE[league])):
        return None
    preferred = {club.casefold() for club in preferred_clubs}
    clubs = [club for club in (candidate.home, candidate.away)
             if club.casefold() in preferred]
    reasons = ['competition:{}'.format(candidate.competition)]
    points = base + 25 * len(clubs)
    if clubs:
        reasons.append('editorial_club:{}'.format(','.join(clubs)))
    for zone, label, bonus, start, end in (
            (LONDON, 'london', 8, 12, 23),
            (NEW_YORK, 'new_york', 6, 8, 23),
            (LOS_ANGELES, 'los_angeles', 4, 8, 23)):
        hour = candidate.kickoff_at.astimezone(zone).hour
        if start <= hour < end:
            points += bonus
            reasons.append('viewing_window:' + label)
    return points, reasons


def select(messages, guild_id, channel_id, now, preferred_clubs=(),
           weekly_limit=2, existing_matches=()):
    """Return a strict editorial plan and an explainable selection receipt.

    A caller must not replace an existing plan when `had_source` is false.
    Existing IDs are retained for a rescheduled fixture with the same clubs
    and competition. A date/competition conflict is left for human review.
    """
    if not 1 <= weekly_limit <= 4:
        raise ValueError('weekly_limit must be 1 to 4')
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    now = now.astimezone(UTC)
    newest = {}
    source_count = 0
    for message in messages:
        parsed = parse_upcoming(message, guild_id, channel_id, now)
        if parsed:
            source_count += 1
        for candidate in parsed:
            old = newest.get(candidate.identity)
            if old is None or (candidate.source_created_at, candidate.source_message_id) > (
                    old.source_created_at, old.source_message_id):
                newest[candidate.identity] = candidate
    ranked = []
    excluded = []
    for candidate in newest.values():
        result = score(candidate, preferred_clubs)
        if result is None:
            excluded.append({'fixture': '{} vs {}'.format(candidate.home, candidate.away),
                             'reason': ('ambiguous_competition_or_nonfocus_clubs' if
                                        candidate.competition.casefold() in FOCUS_CLUBS_BY_LEAGUE
                                        else 'competition_not_in_focus_list')})
        else:
            ranked.append((result[0], candidate, result[1]))
    ranked.sort(key=lambda row: (-row[0], row[1].kickoff_at,
                                 row[1].home.casefold(), row[1].away.casefold()))
    existing = {}
    for item in existing_matches:
        if str(item.get('guild_id')) == str(guild_id):
            key = (str(item.get('home', '')).casefold(),
                   str(item.get('away', '')).casefold(),
                   str(item.get('competition', '')).casefold())
            existing[key] = item
    chosen = []
    chosen_scores = []
    by_week = {}
    for points, candidate, reasons in ranked:
        week = candidate.kickoff_at.astimezone(LONDON).isocalendar()[:2]
        if by_week.get(week, 0) >= weekly_limit:
            excluded.append({'fixture': '{} vs {}'.format(candidate.home, candidate.away),
                             'reason': 'weekly_capacity'})
            continue
        previous = existing.get(candidate.identity)
        if previous and previous.get('status') == 'hold':
            excluded.append({'fixture': '{} vs {}'.format(candidate.home, candidate.away),
                             'reason': 'existing_hold_requires_review'})
            continue
        if previous:
            fixture_id = previous['fixture_id']
        else:
            identity = '|'.join(candidate.identity)
            fixture_id = 'smartscore-' + hashlib.sha256(
                ('{}|{}|{}'.format(identity, week[0], week[1])).encode('utf-8')).hexdigest()[:20]
        chosen.append({'fixture_id': fixture_id, 'guild_id': str(guild_id),
                       'home': candidate.home, 'away': candidate.away,
                       'competition': candidate.competition,
                       'kickoff_utc': candidate.kickoff_at.isoformat().replace('+00:00', 'Z'),
                       'smart_score_message_url': candidate.source_url})
        chosen_scores.append((points, reasons))
        by_week[week] = by_week.get(week, 0) + 1
    receipt = {'had_source': source_count > 0, 'source_cards': source_count,
               'candidates': len(newest), 'selected': [
                   {'fixture_id': item['fixture_id'], 'fixture': '{} vs {}'.format(item['home'], item['away']),
                    'score': points, 'reasons': reasons, 'source_url': item['smart_score_message_url']}
                   for item, (points, reasons) in zip(chosen, chosen_scores)
               ], 'excluded': excluded}
    return {'version': 1, 'matches': chosen}, receipt
