"""Single-guild community storage; Discord adapter enforces actor/guild identity."""
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlsplit


class CommunityError(Exception):
    pass


def text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise CommunityError('Invalid or oversized text.')
    return value.strip()


class CommunityStore:
    def __init__(self, path, staff_ids):
        self.path = path
        self.staff_ids = frozenset(str(v) for v in staff_ids)
        with self.db() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS content (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
                    body TEXT NOT NULL, source TEXT NOT NULL, season INTEGER NOT NULL,
                    author TEXT NOT NULL, created INTEGER NOT NULL,
                    reviewer TEXT, reviewed INTEGER, status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, capacity INTEGER NOT NULL,
                    closes INTEGER NOT NULL, created INTEGER NOT NULL, author TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entries (
                    event_id INTEGER NOT NULL REFERENCES events(id), user_id TEXT NOT NULL,
                    channel TEXT NOT NULL, joined INTEGER NOT NULL, active INTEGER NOT NULL,
                    PRIMARY KEY(event_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS bookmarks (
                    user_id TEXT NOT NULL, content_id INTEGER NOT NULL REFERENCES content(id),
                    PRIMARY KEY(user_id,content_id)
                );
                CREATE TABLE IF NOT EXISTS fut_ingest_metadata (
                    content_id INTEGER NOT NULL REFERENCES content(id), source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL, published_at INTEGER NOT NULL, fetched_at INTEGER NOT NULL,
                    PRIMARY KEY(source_id,external_id), UNIQUE(content_id)
                );
            ''')

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def staff(self, actor):
        if str(actor) not in self.staff_ids:
            raise CommunityError('Staff access required.')

    def draft(self, actor, title, kind, body, source, season, now):
        self.staff(actor)
        title, body, source = text(title, 100), text(body, 1500), text(source, 400)
        try:
            url = urlsplit(source)
            valid = url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
        except ValueError:
            valid = False
        if not valid:
            raise CommunityError('Use an HTTPS source without credentials.')
        if season != 27 or kind not in {'news', 'leak', 'review', 'topic', 'collection', 'sbc', 'squad', 'guide',
                                       'evolutions', 'objectives', 'store'}:
            raise CommunityError('Use a supported FC27 content category.')
        with self.db() as conn:
            cur = conn.execute('INSERT INTO content(title,kind,body,source,season,author,created,status) '
                               "VALUES(?,?,?,?,?,?,?,'draft')",
                               (title, kind, body, source, season, str(actor), now))
            return cur.lastrowid

    def approve(self, actor, item_id, now):
        self.staff(actor)
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM content WHERE id=?', (item_id,)).fetchone()
            if not row or row['status'] != 'draft':
                raise CommunityError('Draft not found.')
            conn.execute("UPDATE content SET status='approved',reviewer=?,reviewed=? WHERE id=?",
                         (str(actor), now, item_id))

    def withdraw(self, actor, item_id):
        self.staff(actor)
        with self.db() as conn:
            if not conn.execute("UPDATE content SET status='withdrawn' WHERE id=?", (item_id,)).rowcount:
                raise CommunityError('Content not found.')

    def preview(self, actor, item_id):
        self.staff(actor)
        with self.db() as conn:
            row = conn.execute('SELECT * FROM content WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise CommunityError('Content not found.')
            return dict(row)

    def latest(self):
        with self.db() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,title,kind,reviewed FROM content WHERE status='approved' AND season=27 "
                'ORDER BY reviewed DESC,id DESC LIMIT 10')]

    def feed(self, kind, limit=10):
        with self.db() as conn:
            return [dict(row) for row in conn.execute(
                'SELECT c.*,m.source_id,m.published_at FROM content c LEFT JOIN fut_ingest_metadata m ON m.content_id=c.id '
                "WHERE c.status='approved' AND c.season=27 AND c.kind=? "
                'ORDER BY c.reviewed DESC,c.id DESC LIMIT ?', (kind, max(1, min(int(limit), 10))))]

    def bookmark(self, user_id, item_id):
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT 1 FROM content WHERE id=? AND status='approved' AND season=27",
                               (item_id,)).fetchone()
            if not row:
                raise CommunityError('This content is no longer available.')
            conn.execute('INSERT OR IGNORE INTO bookmarks VALUES(?,?)', (str(user_id), item_id))

    def bookmarks(self, user_id):
        with self.db() as conn:
            return [dict(row) for row in conn.execute(
                'SELECT c.* FROM content c JOIN bookmarks b ON b.content_id=c.id '
                "WHERE b.user_id=? AND c.status='approved' AND c.season=27 ORDER BY c.id DESC LIMIT 10",
                (str(user_id),))]

    def get(self, item_id):
        with self.db() as conn:
            row = conn.execute('SELECT c.*,m.source_id,m.published_at FROM content c LEFT JOIN fut_ingest_metadata m ON m.content_id=c.id '
                               "WHERE c.id=? AND c.status='approved' AND c.season=27",
                               (item_id,)).fetchone()
            if not row:
                raise CommunityError('Reviewed FC27 content not found.')
            return dict(row)

    def create_event(self, actor, title, capacity, closes, now):
        self.staff(actor)
        title = text(title, 100)
        if type(capacity) is not int or not 1 <= capacity <= 5000 or not now < closes <= now + 90 * 86400:
            raise CommunityError('Use 1–5000 places and a deadline within 90 days.')
        with self.db() as conn:
            cur = conn.execute('INSERT INTO events(title,capacity,closes,created,author) VALUES(?,?,?,?,?)',
                               (title, capacity, closes, now, str(actor)))
            return cur.lastrowid

    def events(self, now):
        with self.db() as conn:
            return [dict(row) for row in conn.execute(
                'SELECT e.*, (SELECT COUNT(*) FROM entries j WHERE j.event_id=e.id AND j.active=1) AS joined '
                'FROM events e WHERE closes>? ORDER BY closes,id LIMIT 10', (now,))]

    def join(self, event_id, user_id, channel, now):
        user_id, channel = text(str(user_id), 100), text(str(channel), 100)
        with self.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            event = conn.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
            if not event or not event['created'] <= now < event['closes']:
                raise CommunityError('Event unavailable or registration closed.')
            existing = conn.execute('SELECT active FROM entries WHERE event_id=? AND user_id=?',
                                    (event_id, user_id)).fetchone()
            if existing and existing['active']:
                return 'Already registered.'
            count = conn.execute('SELECT COUNT(*) FROM entries WHERE event_id=? AND active=1',
                                 (event_id,)).fetchone()[0]
            if count >= event['capacity']:
                raise CommunityError('This event is full.')
            if existing:
                conn.execute('UPDATE entries SET active=1 WHERE event_id=? AND user_id=?',
                             (event_id, user_id))
            else:
                conn.execute('INSERT INTO entries VALUES(?,?,?,?,1)', (event_id, user_id, channel, now))
            return 'Registered. Use /fc leave to cancel.'

    def leave(self, event_id, user_id):
        with self.db() as conn:
            conn.execute('UPDATE entries SET active=0 WHERE event_id=? AND user_id=?',
                         (event_id, str(user_id)))

    def report(self, actor, event_id):
        self.staff(actor)
        with self.db() as conn:
            return [dict(row) for row in conn.execute(
                'SELECT channel, SUM(active) AS active, COUNT(*)-SUM(active) AS cancelled '
                'FROM entries WHERE event_id=? GROUP BY channel ORDER BY channel', (event_id,))]
