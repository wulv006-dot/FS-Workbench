"""Internal binding workflow. Not a public API or proof of email ownership.

Only an authenticated adapter may supply IDs. member_id must include site
scope (e.g. '266:123'); never pass client-supplied member/staff IDs directly.
"""
import re
import sqlite3
import uuid
from contextlib import contextmanager


class BindingError(Exception):
    """Safe, non-PII workflow rejection."""


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,100}', value):
        raise BindingError('invalid_identifier')
    return value


class BindingStore:
    def __init__(self, path, guild_id, staff_ids):
        self.path = path
        self.guild_id = _identifier(guild_id)
        self.staff_ids = frozenset(_identifier(v) for v in staff_ids)
        with self._db() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, guild TEXT NOT NULL,
                    user_id TEXT NOT NULL, member_id TEXT NOT NULL,
                    created INTEGER NOT NULL, expires INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','superseded','approved'))
                );
                CREATE TABLE IF NOT EXISTS bindings (
                    guild TEXT NOT NULL, user_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    PRIMARY KEY(guild,user_id), UNIQUE(guild,member_id)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    request_id TEXT PRIMARY KEY, staff_id TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL, approved_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS pending_user ON requests(guild,user_id,status);
            ''')

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _guild(self, guild_id):
        if guild_id != self.guild_id:
            raise BindingError('guild_not_allowed')

    @staticmethod
    def _time(now):
        if type(now) is not int or now < 0:
            raise BindingError('invalid_time')

    def request(self, guild_id, user_id, member_id, now):
        self._guild(guild_id)
        _identifier(user_id)
        _identifier(member_id)
        if not re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', member_id):
            raise BindingError('site_scoped_member_required')
        self._time(now)
        request_id = uuid.uuid4().hex
        with self._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM bindings WHERE guild=? AND user_id=?',
                            (guild_id, user_id)).fetchone():
                raise BindingError('already_bound')
            conn.execute("UPDATE requests SET status='superseded' "
                         "WHERE guild=? AND user_id=? AND status='pending'", (guild_id, user_id))
            conn.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)',
                         (request_id, guild_id, user_id, member_id, now, now + 86400, 'pending'))
        return request_id

    def approve(self, guild_id, request_id, staff_id, evidence_ref, now):
        self._guild(guild_id)
        if staff_id not in self.staff_ids:
            raise BindingError('staff_required')
        _identifier(evidence_ref)
        _identifier(request_id)
        self._time(now)
        with self._db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM requests WHERE id=? AND guild=?',
                               (request_id, guild_id)).fetchone()
            if row is None:
                raise BindingError('request_not_found')
            if row['user_id'] == staff_id:
                raise BindingError('self_approval_forbidden')
            if row['status'] == 'approved':
                return row['member_id']
            if row['status'] != 'pending' or not row['created'] <= now < row['expires']:
                raise BindingError('request_inactive')
            try:
                conn.execute('INSERT INTO bindings VALUES(?,?,?)',
                             (guild_id, row['user_id'], row['member_id']))
            except sqlite3.IntegrityError:
                raise BindingError('binding_conflict') from None
            conn.execute('INSERT INTO approvals VALUES(?,?,?,?)',
                         (request_id, staff_id, evidence_ref, now))
            conn.execute("UPDATE requests SET status='approved' WHERE id=?", (request_id,))
            return row['member_id']

    def member_for(self, guild_id, user_id):
        """Trusted internal lookup; callers must enforce the Discord actor identity."""
        self._guild(guild_id)
        _identifier(user_id)
        with self._db() as conn:
            row = conn.execute('SELECT member_id FROM bindings WHERE guild=? AND user_id=?',
                               (guild_id, user_id)).fetchone()
            return row['member_id'] if row else None
