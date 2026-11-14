"""Source-linked, low-volume prematch cards for selected FC27 watch parties.

The selection file is an input from an editorial worker, not a fixture source.
Smart Score remains the factual source; malformed or stale plans post nothing.
"""

import datetime as dt
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from matchday_engagement import SMART_SCORE_ID

UTC = dt.timezone.utc
LONDON = ZoneInfo('Europe/London')
FIXTURE_ID = re.compile(r'^[A-Za-z0-9._-]{6,80}$')
PHASES = {
    'day_before': (24 * 3600, 2 * 3600),
    'kickoff_soon': (60 * 60, -10 * 60),
}


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    guild_id: int
    source_channel_id: int
    discussion_channel_id: int
    home: str
    away: str
    competition: str
    kickoff_at: dt.datetime
    source_url: str
    source_message_id: int
    status: str = 'scheduled'


def validate_config(config, matchday_config):
    if not isinstance(config, dict) or not isinstance(config.get('enabled'), bool):
        raise ValueError('Invalid matchday editorial config')
    if not config['enabled']:
        return config
    if not isinstance(matchday_config, dict) or not matchday_config.get('enabled'):
        raise ValueError('Matchday engagement must be enabled for editorial cards')
    for key in ('plan_path', 'state_path'):
        value = config.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('Editorial {} must be an absolute path'.format(key))
    if config.get('scout_path') is not None and (
            not isinstance(config['scout_path'], str) or
            not Path(config['scout_path']).is_absolute()):
        raise ValueError('Editorial scout_path must be an absolute path')
    weekly = config.get('max_matches_per_london_week', 2)
    if type(weekly) is not int or not 1 <= weekly <= 4:
        raise ValueError('Editorial weekly match capacity must be 1 to 4')
    allowed = config.get('allowed_guild_ids')
    routes = matchday_config.get('routes') or {}
    if (not isinstance(allowed, list) or not 1 <= len(allowed) <= 2 or
            any(not isinstance(guild, str) or guild not in routes for guild in allowed) or
            len(set(allowed)) != len(allowed)):
        raise ValueError('Editorial allowed guilds must be an explicit route subset')
    return config


def _source_url(value, guild_id, source_channel_id):
    if not isinstance(value, str):
        raise ValueError('Missing Smart Score source URL')
    parsed = urlparse(value)
    match = re.fullmatch(r'/channels/(\d{16,20})/(\d{16,20})/(\d{16,20})', parsed.path)
    if (parsed.scheme != 'https' or parsed.netloc != 'discord.com' or parsed.params or
            parsed.query or parsed.fragment or not match or
            int(match[1]) != guild_id or int(match[2]) != source_channel_id):
        raise ValueError('Source must be a public Smart Score message in the configured channel')
    return value, int(match[3])


def _name(value):
    if (not isinstance(value, str) or not 2 <= len(value.strip()) <= 60 or
            not re.fullmatch(r"[\w .&'()/-]+", value.strip())):
        raise ValueError('Invalid fixture name')
    return value.strip()


def load_plan(path, routes, now=None, weekly_limit=2):
    """Validate a worker-authored snapshot before returning any due fixtures."""
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    source = Path(path)
    if source.stat().st_size > 65536:
        raise ValueError('Editorial plan too large')
    data = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('matches'), list):
        raise ValueError('Invalid editorial plan')
    if len(data['matches']) > 8:
        raise ValueError('Too many fixtures in editorial plan')
    fixtures, seen, weeks = [], set(), {}
    required = {'fixture_id', 'guild_id', 'home', 'away', 'competition',
                'kickoff_utc', 'smart_score_message_url'}
    for item in data['matches']:
        if (not isinstance(item, dict) or
                set(item) not in (required, required | {'status'}) or
                item.get('status', 'scheduled') not in ('scheduled', 'hold')):
            raise ValueError('Invalid editorial fixture fields')
        guild = str(item['guild_id'])
        route = routes.get(guild)
        if route is None:
            raise ValueError('Editorial fixture is outside configured guilds')
        fixture_id = item['fixture_id']
        if not isinstance(fixture_id, str) or not FIXTURE_ID.fullmatch(fixture_id):
            raise ValueError('Invalid fixture ID')
        unique = (guild, fixture_id)
        if unique in seen:
            raise ValueError('Duplicate editorial fixture ID')
        seen.add(unique)
        try:
            kickoff = dt.datetime.fromisoformat(item['kickoff_utc'].replace('Z', '+00:00'))
        except (AttributeError, ValueError):
            raise ValueError('Invalid kickoff time')
        if kickoff.tzinfo is None or kickoff.utcoffset() != dt.timedelta(0):
            raise ValueError('Kickoff must be UTC')
        kickoff = kickoff.astimezone(UTC)
        until = (kickoff - now).total_seconds()
        if until < -2 * 3600:
            continue
        if until > 48 * 3600:
            raise ValueError('Fixture outside current 48-hour editorial window')
        week = (guild,) + kickoff.astimezone(LONDON).isocalendar()[:2]
        weeks[week] = weeks.get(week, 0) + 1
        if weeks[week] > weekly_limit:
            raise ValueError('Weekly editorial match capacity exceeded')
        source_url, source_message_id = _source_url(
            item['smart_score_message_url'], int(guild), route['source_channel_id'])
        fixtures.append(Fixture(fixture_id, int(guild), route['source_channel_id'],
                                route['discussion_channel_id'], _name(item['home']),
                                _name(item['away']), _name(item['competition']),
                                kickoff, source_url, source_message_id,
                                item.get('status', 'scheduled')))
    return fixtures


def due_cards(fixtures, now=None):
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    due = []
    for fixture in fixtures:
        if fixture.status != 'scheduled':
            continue
        until = (fixture.kickoff_at - now).total_seconds()
        for phase, (open_seconds, close_seconds) in PHASES.items():
            if close_seconds <= until <= open_seconds:
                due.append((fixture, phase))
    return due


def verify_smart_score_source(message, fixture):
    """Match teams, league, status and kickoff in one Smart Score fixture field."""
    author = getattr(message, 'author', None)
    channel = getattr(message, 'channel', None)
    guild = getattr(message, 'guild', None)
    if (not author or author.id != SMART_SCORE_ID or author.bot is not True or
            not channel or channel.id != fixture.source_channel_id or
            not guild or guild.id != fixture.guild_id or
            getattr(message, 'id', None) != fixture.source_message_id):
        return False
    for embed in getattr(message, 'embeds', ()) or ():
        if getattr(embed, 'title', '') != 'Upcoming Matches':
            continue
        for field in getattr(embed, 'fields', ()) or ():
            name, value = str(getattr(field, 'name', '')), str(getattr(field, 'value', ''))
            teams = re.search(r'\*\*([^*\n]+)\*\*\s+vs\s+\*\*([^*\n]+)\*\*',
                              name, re.IGNORECASE)
            if (not teams or teams[1].strip().casefold() != fixture.home.casefold() or
                    teams[2].strip().casefold() != fixture.away.casefold()):
                continue
            league = re.search(r'\*\*League\*\*:\s*([^\n]+)', value)
            status = re.search(r'\*\*Status\*\*:\s*([^\n]+)', value)
            kickoff = re.search(r'\*\*Kickoff\*\*:\s*<t:(\d{9,11}):[tTdDfFR]>', value)
            if (league and league[1].strip().casefold() == fixture.competition.casefold() and
                    status and status[1].strip() == 'Not Started' and kickoff and
                    abs(int(kickoff[1]) - fixture.kickoff_at.timestamp()) <= 900):
                return True
    return False


def card_text(fixture, phase):
    stamp = int(fixture.kickoff_at.timestamp())
    if phase == 'day_before':
        question = 'One match, one chat. What matchup are you watching most closely?'
    elif phase == 'kickoff_soon':
        question = 'Kickoff is close. What is your one call before it starts?'
    else:
        raise ValueError('Unknown editorial phase')
    return ('**{} vs {}** · {}\nKickoff: <t:{}:F> (<t:{}:R>)\n\n{}\n'
            'Fixture details: Smart Score.').format(
                fixture.home, fixture.away, fixture.competition, stamp, stamp, question)


class EditorialPostStore:
    """At-most-once send intent; unknown results require reconciliation, not retry."""

    def __init__(self, path):
        self.path = str(Path(path))
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS matchday_editorial_post (
                guild_id TEXT NOT NULL, fixture_id TEXT NOT NULL, phase TEXT NOT NULL,
                source_url TEXT NOT NULL, status TEXT NOT NULL,
                message_id TEXT, reserved_at REAL NOT NULL,
                PRIMARY KEY (guild_id, fixture_id, phase))''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(matchday_editorial_post)')}
            if 'kickoff_ts' not in columns:
                db.execute('ALTER TABLE matchday_editorial_post ADD COLUMN kickoff_ts INTEGER')
            if 'display_status' not in columns:
                db.execute("ALTER TABLE matchday_editorial_post ADD COLUMN display_status TEXT NOT NULL DEFAULT 'normal'")

    def reserve(self, fixture, phase, now):
        if phase not in PHASES:
            raise ValueError('Unknown editorial phase')
        with sqlite3.connect(self.path, timeout=5) as db:
            result = db.execute('''INSERT OR IGNORE INTO matchday_editorial_post
                (guild_id,fixture_id,phase,source_url,status,reserved_at,kickoff_ts)
                VALUES(?,?,?,?,?,?,?)''', (str(fixture.guild_id), fixture.fixture_id,
                                          phase, fixture.source_url, 'sending', now,
                                          int(fixture.kickoff_at.timestamp())))
            return result.rowcount == 1

    def finish(self, fixture, phase, message_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE matchday_editorial_post SET status=?,message_id=?
                WHERE guild_id=? AND fixture_id=? AND phase=?''',
                ('sent', str(message_id), str(fixture.guild_id), fixture.fixture_id, phase))

    def unknown(self, fixture, phase):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE matchday_editorial_post SET status=?
                WHERE guild_id=? AND fixture_id=? AND phase=? AND status=?''',
                ('unknown', str(fixture.guild_id), fixture.fixture_id, phase, 'sending'))

    def status(self, fixture, phase):
        with sqlite3.connect(self.path) as db:
            row = db.execute('''SELECT status,message_id FROM matchday_editorial_post
                WHERE guild_id=? AND fixture_id=? AND phase=?''',
                (str(fixture.guild_id), fixture.fixture_id, phase)).fetchone()
            return row

    def records(self, fixture):
        with sqlite3.connect(self.path) as db:
            return db.execute('''SELECT phase,status,message_id,source_url,kickoff_ts,display_status
                FROM matchday_editorial_post WHERE guild_id=? AND fixture_id=?''',
                (str(fixture.guild_id), fixture.fixture_id)).fetchall()

    def mark_display(self, fixture, phase, message_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            if fixture.status == 'hold':
                result = db.execute('''UPDATE matchday_editorial_post SET display_status='hold'
                    WHERE guild_id=? AND fixture_id=? AND phase=? AND status='sent' AND message_id=?''',
                    (str(fixture.guild_id), fixture.fixture_id, phase, str(message_id)))
            else:
                result = db.execute('''UPDATE matchday_editorial_post
                    SET display_status='normal',source_url=?,kickoff_ts=?
                    WHERE guild_id=? AND fixture_id=? AND phase=? AND status='sent' AND message_id=?''',
                    (fixture.source_url, int(fixture.kickoff_at.timestamp()),
                     str(fixture.guild_id), fixture.fixture_id, phase, str(message_id)))
            if result.rowcount != 1:
                raise RuntimeError('Editorial display row changed during edit')
