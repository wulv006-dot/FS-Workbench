"""Persist and coalesce trusted EasySBC updates without storing message content."""
import sqlite3
from contextlib import closing


EASYSBC_AUTHOR = 1167033335256731658
KINDS = frozenset(('sbc', 'packs', 'gallery', 'evolutions', 'boosting'))
MERGE_SECONDS = 300  # Trailing quiet window: reset on every content card.
COOLDOWN_SECONDS = 600
MAX_AGE_SECONDS = 300


def _id(value):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdecimal():
        raise ValueError('invalid id')
    value = int(value)
    if value <= 0 or value >= 10**20:
        raise ValueError('invalid id')
    return value


class RelayStore:
    def __init__(self, path, routes, guild_id, author_id=EASYSBC_AUTHOR, self_id=None, require_content=True):
        self.require_content = require_content
        self.path = str(path)
        self.guild_id = _id(guild_id)
        self.author_id = _id(author_id)
        self.self_id = None if self_id is None else _id(self_id)
        self.routes = {_id(channel): kind for channel, kind in routes.items()}
        if (not 1 <= len(self.routes) <= 5 or any(kind not in KINDS for kind in self.routes.values())
                or len(set(self.routes.values())) != len(self.routes)):
            raise ValueError('invalid routes')
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS relay_state (
                channel TEXT PRIMARY KEY, highwater TEXT NOT NULL,
                pending_id TEXT, pending_kind TEXT, due_at REAL,
                sending_id TEXT, claimed_at REAL, last_sent REAL)''')

    def accept(self, message, now):
        try:
            channel = _id(message.channel.id)
            author = _id(message.author.id)
            mid = _id(message.id)
            kind = self.routes.get(channel)
            msg_type = getattr(message.type, 'value', message.type)
            age = float(now) - message.created_at.timestamp()
            if (kind is None or _id(message.guild.id) != self.guild_id
                    or author != self.author_id or author == self.self_id
                    or message.author.bot is not True or msg_type != 0
                    or getattr(message, 'interaction_metadata', None) is not None
                    or getattr(message, 'interaction', None) is not None
                    or getattr(message, 'webhook_id', None) is not None
                    or (self.require_content and not (getattr(message, 'embeds', None) or getattr(message, 'attachments', None)))
                    or not -30 <= age <= MAX_AGE_SECONDS):
                return False
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT highwater, pending_id, pending_kind, due_at, last_sent '
                             'FROM relay_state WHERE channel=?', (str(channel),)).fetchone()
            if row and mid <= int(row[0]):
                return False
            deadline = float(now) + MERGE_SECONDS
            if row and row[4] is not None:
                deadline = max(deadline, row[4] + COOLDOWN_SECONDS)
            if row:
                db.execute('UPDATE relay_state SET highwater=?,pending_id=?,pending_kind=?,due_at=? '
                           'WHERE channel=?', (str(mid), str(mid), kind, deadline, str(channel)))
            else:
                db.execute('INSERT INTO relay_state(channel,highwater,pending_id,pending_kind,due_at) '
                           'VALUES(?,?,?,?,?)', (str(channel), str(mid), str(mid), kind, deadline))
            return True

    def due(self, now):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            rows = db.execute('SELECT channel,pending_kind,pending_id FROM relay_state '
                              'WHERE pending_id IS NOT NULL AND due_at<=? '
                              'AND (sending_id IS NULL OR claimed_at+?<=?) ORDER BY due_at,channel',
                              (float(now), COOLDOWN_SECONDS, float(now))).fetchall()
        return [{'channel_id': int(channel), 'kind': kind, 'message_id': int(mid)}
                for channel, kind, mid in rows if self.routes.get(int(channel)) == kind]

    def claim(self, channel, now):
        channel = _id(channel)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT pending_id,pending_kind,due_at,sending_id,claimed_at '
                             'FROM relay_state WHERE channel=?', (str(channel),)).fetchone()
            if (not row or row[0] is None or row[1] != self.routes.get(channel)
                    or row[2] > float(now)
                    or (row[3] is not None and row[4] + COOLDOWN_SECONDS > float(now))):
                return None
            db.execute('UPDATE relay_state SET sending_id=?,claimed_at=?,last_sent=?,'
                       'pending_id=NULL,pending_kind=NULL,due_at=NULL WHERE channel=?',
                       (row[0], float(now), float(now), str(channel)))
            return {'channel_id': channel, 'kind': row[1], 'message_id': int(row[0])}

    def complete(self, channel, message_id, now):
        channel, message_id = _id(channel), _id(message_id)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT sending_id,claimed_at,pending_id,due_at '
                             'FROM relay_state WHERE channel=?', (str(channel),)).fetchone()
            if not row or row[0] != str(message_id):
                raise ValueError('claim mismatch')
            sent_at = max(float(now), row[1])
            next_due = max(row[3], sent_at + COOLDOWN_SECONDS) if row[2] is not None else None
            db.execute('UPDATE relay_state SET sending_id=NULL,claimed_at=NULL,last_sent=?,due_at=? '
                       'WHERE channel=?', (sent_at, next_due, str(channel)))

    def fail(self, channel, message_id, now):
        # A send failure may be ambiguous; consume the claim rather than replaying it.
        self.complete(channel, message_id, now)
