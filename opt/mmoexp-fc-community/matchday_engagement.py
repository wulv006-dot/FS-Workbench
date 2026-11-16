"""Small, opt-in discussion prompts for verified public match-bot events."""

import datetime as dt
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

UNIFY_FOOTBALL_ID = 1332364544869142538
COOLDOWN_SECONDS = 900
MAX_MESSAGE_AGE_SECONDS = 180
SCORE = re.compile(r'^(.{2,60}?)\s+(\d{1,2})\s*[—–-]\s*(\d{1,2})\s+(.{2,60})$')
VERSUS = re.compile(r'^(.{2,60}?)\s+vs\.?\s+(.{2,60})$', re.IGNORECASE)
LONDON = ZoneInfo('Europe/London')


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
        channel_keys = {'source_channel_id', 'discussion_channel_id',
                        'players_channel_id', 'coins_channel_id'}
        if (not isinstance(route, dict) or not channel_keys <= set(route)
                or set(route) - channel_keys - {'provider', 'score_channel_id'}):
            raise ValueError('Invalid matchday route')
        if not all(_snowflake(route[key]) for key in channel_keys):
            raise ValueError('Invalid matchday channel')
        if 'score_channel_id' in route and not _snowflake(route['score_channel_id']):
            raise ValueError('Invalid matchday score channel')
        if route.get('provider') != 'unify_football':
            raise ValueError('Invalid matchday provider')
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
    source_name: str = 'UnifyFootball'


def _card_lines(message):
    blocks = [getattr(message, 'content', '') or '']
    for embed in getattr(message, 'embeds', ()) or ():
        blocks.extend((getattr(embed, 'title', '') or '', getattr(embed, 'description', '') or ''))
        for field in getattr(embed, 'fields', ()) or ():
            blocks.extend((getattr(field, 'name', '') or '', getattr(field, 'value', '') or ''))
    return [re.sub(r'^#{1,6}\s*', '',
                   line.replace('**', '').replace('__', '').replace('`', '').strip())
            for block in blocks for line in str(block).splitlines() if line.strip()]


def _match_line(lines):
    for line in lines:
        match = SCORE.fullmatch(line)
        if match:
            home, left, right, away = match.groups()
            return home, away, '{}–{}'.format(left, right)
    return None


def parse_unify_football(message, config, now):
    if not config.get('enabled'):
        return None
    guild = getattr(message, 'guild', None)
    channel = getattr(message, 'channel', None)
    author = getattr(message, 'author', None)
    if not guild or not channel or not author:
        return None
    route = config['routes'].get(str(guild.id))
    if (not route or route.get('provider') != 'unify_football'
            or channel.id != route.get('score_channel_id', route['source_channel_id'])
            or author.id != UNIFY_FOOTBALL_ID):
        return None
    if (author.bot is not True or getattr(message, 'webhook_id', None) is not None
            or getattr(message, 'interaction_metadata', None) is not None
            or getattr(getattr(message, 'type', None), 'value', getattr(message, 'type', None)) != 0):
        return None
    created_at = getattr(message, 'created_at', None)
    if not created_at or not -30 <= now - created_at.timestamp() <= MAX_MESSAGE_AGE_SECONDS:
        return None
    lines = _card_lines(message)
    text = '\n'.join(lines).lower()
    if any(word in text for word in ('full time', 'full-time', 'fulltime', 'final whistle')):
        kind = 'final'
    elif 'var review' in text and 'goal disallowed' in text:
        kind = 'correction'
    elif any(word in text for word in ('half time', 'half-time', 'halftime')):
        kind = 'half_time'
    elif re.search(r'\bgoa+l!', text):
        kind = 'goal'
    elif 'red card' in text:
        kind = 'red_card'
    elif any(word in text for word in ('kick off', 'kick-off', 'kickoff', 'match started')):
        kind = 'kickoff'
    else:
        return None
    match = _match_line(lines)
    if not match and kind == 'kickoff':
        for line in lines:
            teams = VERSUS.fullmatch(line)
            if teams:
                match = (*teams.groups(), '0–0')
                break
    if not match:
        return None
    home, away, score = match
    key = '{}|{}'.format(home.casefold(), away.casefold())
    return MatchPulse(guild.id, key, home, away, score, kind, message.jump_url,
                      route['discussion_channel_id'], route['players_channel_id'],
                      route['coins_channel_id'], 'UnifyFootball')


def parse_match_event(message, config, now):
    return parse_unify_football(message, config, now)


def followup_due_at(now):
    local = dt.datetime.fromtimestamp(now, dt.timezone.utc).astimezone(LONDON)
    due = (local + dt.timedelta(days=1)).replace(hour=10, minute=0,
                                                 second=0, microsecond=0)
    return due.astimezone(dt.timezone.utc).timestamp()


def followup_text(pulse):
    return ('Match to Squad: **{} {} {}**. One FC27 pick for your XI—who makes it? '
            'Share your choice below.').format(pulse.home, pulse.score, pulse.away)


class MatchPulseStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS match_pulse (
                guild_id TEXT NOT NULL, match_key TEXT NOT NULL,
                last_message_id TEXT NOT NULL, last_post_at REAL NOT NULL,
                last_kind TEXT NOT NULL,
                PRIMARY KEY (guild_id, match_key))''')
            db.execute('''CREATE TABLE IF NOT EXISTS match_followup (
                event_key TEXT PRIMARY KEY, due_at REAL NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL,
                message_id TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS match_followup_alert (
                event_key TEXT PRIMARY KEY, message_id TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS match_pulse_delivery (
                source_message_id TEXT PRIMARY KEY, guild_id TEXT NOT NULL,
                match_key TEXT NOT NULL, payload TEXT NOT NULL,
                first_seen REAL NOT NULL, retry_after REAL NOT NULL,
                status TEXT NOT NULL, sent_message_id TEXT)''')

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
            elif pulse.kind == 'correction':
                should_post = bool(row and pulse.score != previous_score)
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
            if should_post:
                db.execute('''UPDATE match_pulse_delivery SET status='superseded'
                    WHERE guild_id=? AND match_key=? AND status='pending' ''',
                    (str(pulse.guild_id), pulse.match_key))
                db.execute('''INSERT OR IGNORE INTO match_pulse_delivery
                    (source_message_id,guild_id,match_key,payload,first_seen,retry_after,status)
                    VALUES(?,?,?,?,?,?,'pending')''',
                    (str(message_id), str(pulse.guild_id), pulse.match_key,
                     json.dumps(asdict(pulse), ensure_ascii=False), now, now + 15))
            return should_post

    def due_deliveries(self, now):
        with sqlite3.connect(self.path, timeout=5) as db:
            # Discord only guarantees nonce deduplication for a short period.
            expired = db.execute('''SELECT source_message_id FROM match_pulse_delivery
                WHERE status='pending' AND first_seen<=?''', (now - 120,)).fetchall()
            db.execute('''UPDATE match_pulse_delivery SET status='unknown'
                WHERE status='pending' AND first_seen<=?''', (now - 120,))
            rows = db.execute('''SELECT source_message_id,payload,first_seen FROM match_pulse_delivery
                WHERE status='pending' AND retry_after<=?
                ORDER BY first_seen LIMIT 3''', (now,)).fetchall()
        return [(int(mid), MatchPulse(**json.loads(payload)), first_seen)
                for mid, payload, first_seen in rows], \
            [int(row[0]) for row in expired]

    def delivery_failed(self, source_message_id, now):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE match_pulse_delivery SET retry_after=?
                WHERE source_message_id=? AND status='pending' ''',
                (now + 30, str(source_message_id)))

    def delivery_sent(self, source_message_id, sent_message_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE match_pulse_delivery SET status='sent',sent_message_id=?
                WHERE source_message_id=? AND status IN ('pending','superseded')''',
                (str(sent_message_id), str(source_message_id)))

    def queue_followup(self, pulse, now):
        if pulse.kind != 'final':
            return
        local_day = dt.datetime.fromtimestamp(now, dt.timezone.utc).astimezone(LONDON).date()
        key = '{}:{}:{}'.format(pulse.guild_id, pulse.match_key, local_day)
        payload = json.dumps(asdict(pulse), ensure_ascii=False)
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''INSERT OR IGNORE INTO match_followup
                (event_key,due_at,payload,status) VALUES(?,?,?,'pending')''',
                (key, followup_due_at(now), payload))
            db.execute('''UPDATE match_followup SET payload=?
                WHERE event_key=? AND status='pending' ''', (payload, key))

    def due_followups(self, now):
        with sqlite3.connect(self.path) as db:
            rows = db.execute('''SELECT event_key,payload FROM match_followup
                WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT 2''', (now,)).fetchall()
        return [(key, MatchPulse(**json.loads(payload))) for key, payload in rows]

    def reserve_followup(self, key):
        with sqlite3.connect(self.path, timeout=5) as db:
            return db.execute('''UPDATE match_followup SET status='sending'
                WHERE event_key=? AND status='pending' ''', (key,)).rowcount == 1

    def finish_followup(self, key, message_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE match_followup SET status='sent',message_id=?
                WHERE event_key=? AND status='sending' ''', (str(message_id), key))

    def unknown_followup(self, key):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE match_followup SET status='unknown'
                WHERE event_key=? AND status='sending' ''', (key,))

    def overdue_followups(self, now, guild_id):
        with sqlite3.connect(self.path) as db:
            rows = db.execute('''SELECT f.event_key,f.payload FROM match_followup f
                LEFT JOIN match_followup_alert a ON a.event_key=f.event_key
                WHERE f.event_key LIKE ? AND f.status!='sent' AND f.due_at<=?
                AND a.event_key IS NULL ORDER BY f.due_at LIMIT 3''',
                ('{}:%'.format(guild_id), now - 600)).fetchall()
        return [(key, MatchPulse(**json.loads(payload))) for key, payload in rows]

    def claim_followup_alert(self, key):
        with sqlite3.connect(self.path, timeout=5) as db:
            return db.execute('''INSERT OR IGNORE INTO match_followup_alert
                (event_key) VALUES(?)''', (key,)).rowcount == 1

    def finish_followup_alert(self, key, message_id):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('''UPDATE match_followup_alert SET message_id=?
                WHERE event_key=?''', (str(message_id), key))


def prompt_text(pulse):
    names = '{} vs {}'.format(pulse.home, pulse.away)
    if pulse.kind == 'correction':
        return 'VAR: goal disallowed. **{} {}** is the corrected score. What did you make of the call?'.format(names, pulse.score)
    if pulse.kind == 'final':
        return 'Full time: **{} {}**. Who was your player of the match?'.format(names, pulse.score)
    if pulse.kind == 'half_time':
        return 'Half time: **{} {}**. What would you change for the second half?'.format(names, pulse.score)
    if pulse.kind == 'goal':
        home_goals, away_goals = (int(value) for value in pulse.score.split('–'))
        leader, trailer = ((pulse.home, pulse.away) if home_goals > away_goals
                           else (pulse.away, pulse.home))
        scoreline = '**{} {}**'.format(names, pulse.score)
        if home_goals == away_goals:
            return '⚽ Level at {}. Who finds the winner?'.format(scoreline)
        margin = abs(home_goals - away_goals)
        if min(home_goals, away_goals) == 0 and margin == 1:
            return '⚽ {} strike first: {}. How should {} respond?'.format(leader, scoreline, trailer)
        if min(home_goals, away_goals) == 0 and margin >= 3:
            return '⚽ {} have opened up a big lead: {}. Who can spark a response for {}?'.format(
                leader, scoreline, trailer)
        if margin == 1:
            return '⚽ One goal in it: {}. Who makes the next big play?'.format(scoreline)
        return '⚽ {} lead by {}: {}. Can {} find a way back?'.format(
            leader, margin, scoreline, trailer)
    if pulse.kind == 'red_card':
        return 'Red card in **{}**. How does that change your prediction?'.format(names)
    return '**{}** is under way. What is your call?'.format(names)
