"""SEO-owned working database. Pages commit without retaining raw responses."""
import contextlib
import json
import sqlite3
from pathlib import Path

from .contracts import game


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError('SEO_ROOT_SYMLINK')
        if not (self.root/'core.db').exists() and (self.root/'current.json').exists():
            raise ValueError('CORE_RESTORE_REQUIRED')
        if (self.root/'core.db').is_symlink():
            raise ValueError('SEO_DATABASE_SYMLINK')
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS facts(source TEXT, game TEXT, source_date TEXT,
                    row_key TEXT, payload TEXT, PRIMARY KEY(source, game, source_date, row_key));
                CREATE TABLE IF NOT EXISTS stages(source TEXT, game TEXT, source_date TEXT,
                    row_key TEXT, payload TEXT, PRIMARY KEY(source, game, source_date, row_key));
                CREATE TABLE IF NOT EXISTS coverage(source TEXT, game TEXT, source_date TEXT,
                    source_timezone TEXT, status TEXT, collected_at TEXT, quality TEXT,
                    error TEXT, PRIMARY KEY(source, game, source_date));
                CREATE TABLE IF NOT EXISTS cursors(source TEXT, game TEXT, source_date TEXT,
                    cursor INTEGER, PRIMARY KEY(source, game, source_date));
            ''')

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(str(self.root / 'core.db'), timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initial_window(self, start, end):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('initial_window', encode([start, end])))
            return json.loads(db.execute('SELECT value FROM settings WHERE key=?', ('initial_window',)).fetchone()[0])

    def ingest_page(self, source, scope, day, page, collected_at):
        game(scope)
        key = (source, scope, day)
        if not page['rows'] and page['status'] == 'no_rows':
            with self.db() as db:
                staged = db.execute('SELECT 1 FROM stages WHERE source=? AND game=? AND source_date=? LIMIT 1', key).fetchone()
            if not staged:
                self.mark(source, scope, day, page['source_timezone'], 'no_rows', collected_at, 'SOURCE_NO_ROWS')
                return
            page = dict(page, status='provisional' if source == 'ga4' else 'available')
        with self.db() as db:
            for row in page['rows']:
                db.execute('INSERT OR REPLACE INTO stages VALUES (?,?,?,?,?)', (*key, row['key'], encode(row)))
            cursor = page['next_cursor']
            if cursor is not None:
                db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?,?)', (*key, cursor))
                return
            db.execute('DELETE FROM facts WHERE source=? AND game=? AND source_date=?', key)
            db.execute('INSERT INTO facts SELECT * FROM stages WHERE source=? AND game=? AND source_date=?', key)
            db.execute('DELETE FROM stages WHERE source=? AND game=? AND source_date=?', key)
            db.execute('DELETE FROM cursors WHERE source=? AND game=? AND source_date=?', key)
            db.execute('INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?,?)',
                       (*key, page['source_timezone'], page['status'], collected_at, encode(page['quality']), None))

    def mark(self, source, scope, day, timezone, status, collected_at, error):
        with self.db() as db:
            key = source, scope, day
            old = db.execute('SELECT status,quality FROM coverage WHERE source=? AND game=? AND source_date=?', key).fetchone()
            # Failed refresh preserves the last successful facts and their source date.
            quality = json.loads(old['quality']) if old else {}
            if old and old['status'] in ('available', 'partial', 'provisional', 'stale'):
                quality['last_attempt_error'] = error
                status = 'stale'
            db.execute('INSERT OR REPLACE INTO coverage VALUES (?,?,?,?,?,?,?,?)',
                       (*key, timezone, status, collected_at, encode(quality), error))

    def slices(self, source, scope, context):
        import datetime as dt
        start, end = self.initial_window(context.history_start, context.report_date)
        days = set()
        # Correct small daily aggregates for fourteen days, resume the fixed initial backfill.
        for n in range(14):
            days.add((dt.date.fromisoformat(context.report_date) - dt.timedelta(days=n)).isoformat())
        with self.db() as db:
            day = dt.date.fromisoformat(max(start, context.history_start))
            while day.isoformat() <= context.report_date:
                old = db.execute('SELECT status FROM coverage WHERE source=? AND game=? AND source_date=?',
                                 (source, scope, day.isoformat())).fetchone()
                if not old or old['status'] not in ('available', 'provisional', 'not_available_historically'):
                    days.add(day.isoformat())
                day += dt.timedelta(days=1)
            slices = []
            for day in sorted(days, reverse=True):
                row = db.execute('SELECT cursor FROM cursors WHERE source=? AND game=? AND source_date=?', (source, scope, day)).fetchone()
                if row is None:
                    db.execute('DELETE FROM stages WHERE source=? AND game=? AND source_date=?', (source, scope, day))
                slices.append((day, row[0] if row else 0))
        return slices
