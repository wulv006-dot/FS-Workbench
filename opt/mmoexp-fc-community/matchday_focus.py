"""Pick one public Unify fixture card per day for the FC27 match lounge."""

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from matchday_engagement import UNIFY_FOOTBALL_ID


LONDON = ZoneInfo('Europe/London')
FIXTURE = re.compile(r'^(.{2,60}?)\s+vs\.?\s+(.{2,60}?)\s+([01]?\d|2[0-3]):([0-5]\d)$', re.I)
DATE = re.compile(r'^([A-Z][a-z]+ \d{1,2}, \d{4})\s*\(Europe/London\)$')


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
    routes = (engagement or {}).get('routes') or {}
    if (not isinstance(path, str) or not Path(path).is_absolute() or
            not isinstance(guilds, list) or not 1 <= len(guilds) <= 2 or
            any(not isinstance(g, str) or g not in routes for g in guilds) or
            len(set(guilds)) != len(guilds) or
            type(limit) is not int or not 1 <= limit <= 4):
        raise ValueError('Invalid matchday focus scope')
    return config


def _lines(block):
    return [line.replace('**', '').replace('`', '').strip(' •\t')
            for line in str(block or '').splitlines() if line.strip()]


def parse_daily_card(message, route, now):
    """Only a fresh public Unify daily card in the configured source channel counts."""
    guild = getattr(message, 'guild', None)
    channel = getattr(message, 'channel', None)
    author = getattr(message, 'author', None)
    created = getattr(message, 'created_at', None)
    embeds = getattr(message, 'embeds', ()) or ()
    if (not guild or not channel or not author or author.id != UNIFY_FOOTBALL_ID or
            author.bot is not True or channel.id != route['source_channel_id'] or
            getattr(message, 'webhook_id', None) is not None or not created or
            not -30 <= now.timestamp() - created.timestamp() <= 86400 or not embeds):
        return []
    embed = embeds[0]
    if 'today\'s matches' not in str(getattr(embed, 'title', '') or '').casefold():
        return []
    blocks = [getattr(embed, 'description', '')]
    for field in getattr(embed, 'fields', ()) or ():
        blocks.extend((getattr(field, 'name', ''), getattr(field, 'value', '')))
    lines = [line for block in blocks for line in _lines(block)]
    date_line = next((DATE.fullmatch(line) for line in lines if DATE.fullmatch(line)), None)
    if date_line is None:
        return []
    try:
        date = dt.datetime.strptime(date_line[1], '%B %d, %Y').date()
    except ValueError:
        return []
    if date != now.astimezone(LONDON).date():
        return []
    fixtures, seen, competition = [], set(), ''
    for line in lines:
        match = FIXTURE.fullmatch(line)
        if match:
            if not competition:
                continue
            home, away, hour, minute = match.groups()
            kickoff = dt.datetime.combine(date, dt.time(int(hour), int(minute)), LONDON)
            if kickoff.timestamp() <= now.timestamp() - 300:
                continue
            fixture = DailyFixture(home.strip(), away.strip(), competition, kickoff,
                                   message.jump_url)
            if fixture.key not in seen:
                fixtures.append(fixture)
                seen.add(fixture.key)
            if len(fixtures) >= 20:
                break
        elif (line != date_line[0] and len(line) <= 80 and
              any(word in line.casefold() for word in
                  ('league', 'cup', 'champions', 'europa', 'world', 'nations'))):
            competition = line
    return fixtures


def parse_choice(answer, count):
    match = re.fullmatch(r'([1-9]|1\d|20)\|([^\n\r@<>]{10,140}\?)', answer.strip())
    if answer.strip() == 'NONE':
        return None
    if not match or int(match[1]) > count:
        raise ValueError('Invalid matchday selection')
    return int(match[1]) - 1, match[2].strip()


class FocusStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS matchday_focus (
                guild_id TEXT NOT NULL, london_day TEXT NOT NULL,
                source_id TEXT NOT NULL, match_key TEXT, kickoff REAL,
                question TEXT, status TEXT NOT NULL, posted_id TEXT,
                PRIMARY KEY (guild_id, london_day))''')

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

    def skip(self, guild_id, day, source_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''INSERT OR IGNORE INTO matchday_focus
                (guild_id,london_day,source_id,status) VALUES(?,?,?,'skipped')''',
                (str(guild_id), day.isoformat(), str(source_id)))

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
        with sqlite3.connect(self.path) as db:
            return db.execute('''SELECT 1 FROM matchday_focus WHERE guild_id=?
                AND match_key=? AND status='sent' AND kickoff BETWEEN ? AND ?''',
                (str(guild_id), match_key, now - 12 * 3600, now + 24 * 3600)).fetchone() is not None
