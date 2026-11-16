"""Pick one public Unify fixture card per day for the FC27 match lounge."""

import datetime as dt
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from matchday_engagement import UNIFY_FOOTBALL_ID


LONDON = ZoneInfo('Europe/London')
DEFAULT_SETTLE_SECONDS = 300
FIXTURE = re.compile(r'^(.{2,60}?)\s+vs\.?\s+(.{2,60}?)\s+([01]?\d|2[0-3]):([0-5]\d)$', re.I)
DATE = re.compile(r'^([A-Z][a-z]+ \d{1,2}, \d{4})\s*\(Europe/London\)$')
CLUB_ALIASES = {
    'ajax': ('AFC Ajax',), 'atletico': ('Atletico Madrid', 'Atletico de Madrid'),
    'barcelona': ('FC Barcelona',), 'benfica': ('SL Benfica',),
    'bayern': ('Bayern Munich', 'Bayern München'), 'dortmund': ('Borussia Dortmund',),
    'bournemouth': ('AFC Bournemouth',), 'brighton': ('Brighton & Hove Albion',),
    'celtic': ('Celtic FC',), 'coventry': ('Coventry City',),
    'hull': ('Hull City',), 'inter': ('Inter Milan', 'Internazionale'),
    'ipswich': ('Ipswich Town',), 'leeds': ('Leeds United',),
    'leicester': ('Leicester City',),
    'leverkusen': ('Bayer Leverkusen', 'Bayer 04 Leverkusen'),
    'lyon': ('Olympique Lyonnais',),
    'man_city': ('Manchester City',), 'man_united': ('Manchester United',),
    'marseille': ('Olympique Marseille', 'Olympique de Marseille'),
    'milan': ('AC Milan',), 'newcastle': ('Newcastle United',),
    'nottingham_forest': ('Nottingham Forest',),
    'psg': ('Paris Saint-Germain', 'Paris SG'), 'psv': ('PSV Eindhoven',),
    'rangers': ('Rangers FC',), 'roma': ('AS Roma',),
    'tottenham': ('Tottenham Hotspur', 'Tottenham', 'Spurs'),
    'west_ham': ('West Ham United',),
}


@dataclass(frozen=True)
class DailyFixture:
    home: str
    away: str
    competition: str
    kickoff: dt.datetime
    source_url: str

    @property
    def key(self):
        return '{}|{}'.format(self.home.casefold(), self.away.casefold())


def validate_config(config, engagement):
    if not isinstance(config, dict) or type(config.get('enabled')) is not bool:
        raise ValueError('Invalid matchday focus config')
    if not config['enabled']:
        return config
    path = config.get('state_path')
    guilds = config.get('guild_ids')
    limit = config.get('weekly_limit', 2)
    settle = config.get('settle_seconds', DEFAULT_SETTLE_SECONDS)
    routes = (engagement or {}).get('routes') or {}
    if (not isinstance(path, str) or not Path(path).is_absolute() or
            not isinstance(guilds, list) or not 1 <= len(guilds) <= 2 or
            any(not isinstance(g, str) or g not in routes for g in guilds) or
            len(set(guilds)) != len(guilds) or
            type(limit) is not int or not 1 <= limit <= 4 or
            type(settle) is not int or not 0 <= settle <= 900):
        raise ValueError('Invalid matchday focus scope')
    return config


def _lines(block, field_heading=False):
    return [(re.sub(r'^[^\w]+', '', re.sub(r'[*_`#🕒]', '', line)).strip(' •\t'),
             field_heading or bool(re.match(r'^\s*#{3}\s', line)))
            for line in str(block or '').splitlines() if line.strip()]


def _component_text(payload):
    if payload.get('type') == 10:
        yield payload.get('content', '')
    for child in payload.get('components', ()):
        yield from _component_text(child)


def _trusted_daily_source(message, route, now):
    guild = getattr(message, 'guild', None)
    channel = getattr(message, 'channel', None)
    author = getattr(message, 'author', None)
    created = getattr(message, 'created_at', None)
    return bool(guild and channel and author and
                author.id == UNIFY_FOOTBALL_ID and author.bot is True and
                channel.id == route['source_channel_id'] and
                getattr(message, 'webhook_id', None) is None and created and
                -30 <= now.timestamp() - created.timestamp() <= 86400)


def is_empty_daily_card(message, route, now):
    """Recognize only Unify's explicit no-fixtures placeholder in our feed."""
    if not _trusted_daily_source(message, route, now):
        return False
    embeds = getattr(message, 'embeds', ()) or ()
    if len(embeds) != 1 or getattr(message, 'components', ()):
        return False
    title = re.sub(r'^[^A-Za-z]+', '', getattr(embeds[0], 'title', '') or '')
    description = (getattr(embeds[0], 'description', '') or '').casefold()
    return (title.startswith('No matches today in ') and
            'no matches lined up in ' in description)


def parse_daily_card(message, route, now, include_started=False):
    """Only a fresh public Unify daily card in the configured source channel counts."""
    embeds = getattr(message, 'embeds', ()) or ()
    if not _trusted_daily_source(message, route, now):
        return []
    blocks = []
    if embeds:
        embed = embeds[0]
        blocks = [(getattr(embed, 'title', ''), False),
                  (getattr(embed, 'description', ''), False)]
        for field in getattr(embed, 'fields', ()) or ():
            blocks.extend(((getattr(field, 'name', ''), True),
                           (getattr(field, 'value', ''), False)))
    else:
        for component in getattr(message, 'components', ()) or ():
            blocks.extend((text, False) for text in _component_text(component.to_dict()))
    lines = [item for block, heading in blocks for item in _lines(block, heading)]
    if not any("today's matches" in line.casefold() for line, _ in lines):
        return []
    date_line = next((DATE.fullmatch(line) for line, _ in lines if DATE.fullmatch(line)), None)
    if date_line is None:
        return []
    try:
        date = dt.datetime.strptime(date_line[1], '%B %d, %Y').date()
    except ValueError:
        return []
    if date != now.astimezone(LONDON).date():
        return []
    fixtures, seen, competition = [], set(), ''
    for line, heading in lines:
        match = FIXTURE.fullmatch(line)
        if match:
            if not competition:
                continue
            home, away, hour, minute = match.groups()
            kickoff = dt.datetime.combine(date, dt.time(int(hour), int(minute)), LONDON)
            if not include_started and kickoff.timestamp() <= now.timestamp() - 300:
                continue
            fixture = DailyFixture(home.strip(), away.strip(), competition, kickoff,
                                   message.jump_url)
            if fixture.key not in seen:
                fixtures.append(fixture)
                seen.add(fixture.key)
            if len(fixtures) >= 20:
                break
        elif heading and line != date_line[0] and len(line) <= 80:
            competition = line
    return fixtures


def club_fixtures(slug, fixtures):
    """Match a selected club exactly, including common official-name variants."""
    def key(value):
        plain = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
        return re.sub(r'[^a-z0-9]+', ' ', plain.casefold()).strip()

    names = {key(slug.replace('_', ' '))}
    names.update(key(alias) for alias in CLUB_ALIASES.get(slug, ()))
    return [fixture for fixture in fixtures
            if key(fixture.home) in names or key(fixture.away) in names]


def parse_choice(answer, count):
    match = re.fullmatch(r'(?:N\|)?([1-9]\d{0,2})(?:\s*\|\s*[^\n\r@<>]{10,140}\?)?',
                         answer.strip(), re.I)
    if answer.strip() == 'NONE':
        return None
    if not match or int(match[1]) > count:
        raise ValueError('Invalid matchday selection')
    return int(match[1]) - 1


class FocusStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS matchday_focus (
                guild_id TEXT NOT NULL, london_day TEXT NOT NULL,
                source_id TEXT NOT NULL, match_key TEXT, kickoff REAL,
                question TEXT, status TEXT NOT NULL, posted_id TEXT,
                PRIMARY KEY (guild_id, london_day))''')
            db.execute('''CREATE TABLE IF NOT EXISTS matchday_focus_reviewed (
                guild_id TEXT NOT NULL, source_id TEXT NOT NULL,
                PRIMARY KEY (guild_id, source_id))''')

    def may_select(self, guild_id, day, weekly_limit):
        start = day - dt.timedelta(days=day.weekday())
        end = start + dt.timedelta(days=7)
        with sqlite3.connect(self.path) as db:
            seen = db.execute('SELECT 1 FROM matchday_focus WHERE guild_id=? AND london_day=?',
                              (str(guild_id), day.isoformat())).fetchone()
            count = db.execute('''SELECT COUNT(*) FROM matchday_focus WHERE guild_id=?
                AND london_day>=? AND london_day<? AND status!='skipped' ''',
                (str(guild_id), start.isoformat(), end.isoformat())).fetchone()[0]
        return not seen and count < weekly_limit

    def reserve(self, guild_id, day, source_id, fixture, question, weekly_limit):
        if not self.may_select(guild_id, day, weekly_limit):
            return False
        with sqlite3.connect(self.path, timeout=5) as db:
            return db.execute('''INSERT OR IGNORE INTO matchday_focus
                (guild_id,london_day,source_id,match_key,kickoff,question,status)
                VALUES(?,?,?,?,?,?,'sending')''',
                (str(guild_id), day.isoformat(), str(source_id), fixture.key,
                 fixture.kickoff.timestamp(), question)).rowcount == 1

    def skip_source(self, guild_id, source_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''INSERT OR IGNORE INTO matchday_focus_reviewed
                (guild_id,source_id) VALUES(?,?)''', (str(guild_id), str(source_id)))

    def reviewed(self, guild_id, source_id):
        with sqlite3.connect(self.path) as db:
            return db.execute('''SELECT 1 FROM matchday_focus_reviewed
                WHERE guild_id=? AND source_id=?''',
                (str(guild_id), str(source_id))).fetchone() is not None

    def finish(self, guild_id, day, posted_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE matchday_focus SET status='sent', posted_id=?
                WHERE guild_id=? AND london_day=? AND status='sending' ''',
                (str(posted_id), str(guild_id), day.isoformat()))

    def unknown(self, guild_id, day):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE matchday_focus SET status='unknown'
                WHERE guild_id=? AND london_day=? AND status='sending' ''',
                (str(guild_id), day.isoformat()))

    def selected(self, guild_id, match_key, now):
        return self.selected_source_id(guild_id, match_key, now) is not None

    def selected_source_id(self, guild_id, match_key, now):
        with sqlite3.connect(self.path) as db:
            row = db.execute('''SELECT source_id FROM matchday_focus WHERE guild_id=?
                AND match_key=? AND status='sent' AND kickoff BETWEEN ? AND ?''',
                (str(guild_id), match_key, now - 12 * 3600, now + 24 * 3600)).fetchone()
        return row[0] if row else None
