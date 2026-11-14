"""Small, opt-in discussion prompts for public Smart Score match events.

Smart Score remains the source of match facts. This module reads only its public
cards in one configured channel and never reads private prediction responses.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SMART_SCORE_ID = 1496068397757366273
COOLDOWN_SECONDS = 900
MAX_MESSAGE_AGE_SECONDS = 180
SCORE = re.compile(r'^(.{2,60}?)\s+(\d{1,2})\s*[—–-]\s*(\d{1,2})\s+(.{2,60})$')


def _snowflake(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 10**20


def validate_matchday_config(config):
    if not isinstance(config, dict) or not isinstance(config.get('enabled'), bool):
        raise ValueError('Invalid matchday engagement config')
    if config.get('state_path') is not None and not isinstance(config['state_path'], str):
        raise ValueError('Invalid matchday state path')
    routes = config.get('routes')
    if not isinstance(routes, dict) or not 1 <= len(routes) <= 2:
        raise ValueError('Invalid matchday routes')
    for guild_id, route in routes.items():
        if not str(guild_id).isascii() or not str(guild_id).isdecimal() or not _snowflake(int(guild_id)):
            raise ValueError('Invalid matchday guild')
        if int(guild_id) not in (1565922092518613064, 1041923524601851914):
            raise ValueError('Matchday route must use the test or official guild')
        if not isinstance(route, dict) or set(route) != {'source_channel_id', 'discussion_channel_id',
                                                        'players_channel_id', 'coins_channel_id'}:
            raise ValueError('Invalid matchday route')
        if not all(_snowflake(value) for value in route.values()):
            raise ValueError('Invalid matchday channel')
    return config


@dataclass(frozen=True)
class MatchPulse:
    guild_id: int
    match_key: str
    home: str
    away: str
    score: str
    kind: str
    source_url: str
    discussion_channel_id: int
    players_channel_id: int
    coins_channel_id: int


def _card_lines(message):
    blocks = [getattr(message, 'content', '') or '']
    for embed in getattr(message, 'embeds', ()) or ():
        blocks.extend((getattr(embed, 'title', '') or '', getattr(embed, 'description', '') or ''))
        for field in getattr(embed, 'fields', ()) or ():
            blocks.extend((getattr(field, 'name', '') or '', getattr(field, 'value', '') or ''))
    return [line.replace('**', '').replace('__', '').replace('`', '').strip()
            for block in blocks for line in str(block).splitlines() if line.strip()]


def _match_line(lines):
    for line in lines:
        match = SCORE.fullmatch(line)
        if match:
            home, left, right, away = match.groups()
            return home, away, '{}–{}'.format(left, right)
    return None


def _event_kind(lines):
    text = '\n'.join(lines).lower()
    if any(word in text for word in ('match finished', 'full time', 'full-time')):
        return 'final'
    if any(word in text for word in ('half time', 'half-time', 'halftime')):
        return 'half_time'
    if (any(word in text for word in ('goal!', 'goal scored', 'penalty goal'))
            or re.search(r'\bg\s+o\s+a\s+l\s*!', text)):
        return 'goal'
    if 'red card' in text:
        return 'red_card'
    if any(word in text for word in ('match started', 'kick-off', 'kickoff')):
        return 'kickoff'
    return None


def parse_smart_score(message, config, now):
    if not config.get('enabled'):
        return None
    guild = getattr(message, 'guild', None)
    channel = getattr(message, 'channel', None)
    author = getattr(message, 'author', None)
    if not guild or not channel or not author:
        return None
    route = config['routes'].get(str(guild.id))
    if not route or channel.id != route['source_channel_id'] or author.id != SMART_SCORE_ID:
        return None
    if (author.bot is not True or getattr(message, 'webhook_id', None) is not None
            or getattr(message, 'interaction_metadata', None) is not None
            or getattr(getattr(message, 'type', None), 'value', getattr(message, 'type', None)) != 0):
        return None
    created_at = getattr(message, 'created_at', None)
    if not created_at or not -30 <= now - created_at.timestamp() <= MAX_MESSAGE_AGE_SECONDS:
        return None
    lines = _card_lines(message)
    match = _match_line(lines)
    kind = _event_kind(lines)
    if not match or not kind:
        return None
    home, away, score = match
    key = '{}|{}'.format(home.casefold(), away.casefold())
    return MatchPulse(guild.id, key, home, away, score, kind, message.jump_url,
                      route['discussion_channel_id'], route['players_channel_id'],
                      route['coins_channel_id'])


class MatchPulseStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS match_pulse (
                guild_id TEXT NOT NULL, match_key TEXT NOT NULL,
                last_message_id TEXT NOT NULL, last_post_at REAL NOT NULL,
                last_kind TEXT NOT NULL,
                PRIMARY KEY (guild_id, match_key))''')

    def claim(self, message_id, pulse, now):
        if not _snowflake(message_id):
            return False
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT last_message_id,last_post_at,last_kind FROM match_pulse '
                             'WHERE guild_id=? AND match_key=?',
                             (str(pulse.guild_id), pulse.match_key)).fetchone()
            if row and message_id <= int(row[0]):
                return False
            previous_kind, _, previous_score = row[2].partition('|') if row else ('', '', '')
            state = '{}|{}'.format(pulse.kind, pulse.score)
            if pulse.kind == 'goal':
                should_post = not row or pulse.score != previous_score
            elif pulse.kind == 'final':
                should_post = (not row or pulse.kind != previous_kind
                               or (previous_score and pulse.score != previous_score))
            elif pulse.kind in ('kickoff', 'half_time'):
                should_post = not row or pulse.kind != previous_kind
            else:
                should_post = (not row or (now - row[1] >= COOLDOWN_SECONDS
                                           and state != row[2]))
            if row:
                db.execute('UPDATE match_pulse SET last_message_id=?,last_post_at=?,last_kind=? '
                           'WHERE guild_id=? AND match_key=?',
                           (str(message_id), now if should_post else row[1],
                            state if should_post else row[2],
                            str(pulse.guild_id), pulse.match_key))
            else:
                db.execute('INSERT INTO match_pulse VALUES(?,?,?,?,?)',
                            (str(pulse.guild_id), pulse.match_key, str(message_id), now, state))
            return should_post


def prompt_text(pulse):
    names = '{} vs {}'.format(pulse.home, pulse.away)
    if pulse.kind == 'final':
        return 'Full time: **{} {}**. Who was your player of the match?'.format(names, pulse.score)
    if pulse.kind == 'half_time':
        return 'Half time: **{} {}**. What would you change for the second half?'.format(names, pulse.score)
    if pulse.kind == 'goal':
        return 'Goal! **{} {}**. How does that change the match?'.format(names, pulse.score)
    if pulse.kind == 'red_card':
        return 'Red card in **{}**. How does that change your prediction?'.format(names)
    return '**{}** is under way. What is your call?'.format(names)
