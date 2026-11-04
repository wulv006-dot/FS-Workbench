"""Verified immutable SQLite packages; read paths never import sources or Hermes."""
import contextlib
import datetime as dt
import hashlib
import json
import itertools
import os
import re
import sqlite3
import uuid
from pathlib import Path

from .contracts import GAMES, SCHEMA, game
from .metrics import compute_metrics
from .store import encode


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as inp:
        for chunk in iter(lambda: inp.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8') as out:
            out.write(encode(value))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        if os.name != 'nt':
            fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def batch_lock(root):
    with (Path(root) / 'batch.lock').open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            if lock.read(1) == b'':
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def current(root):
    path = Path(root) / 'current.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def build(store, context, source_names=()):
    directory = store.root / 'snapshots'
    directory.mkdir(exist_ok=True)
    ident = 'seo-' + context.publication_date
    candidate = directory / (ident + '.' + uuid.uuid4().hex + '.tmp')
    connection = sqlite3.connect(str(candidate))
    try:
        with store.db() as db:
            db.backup(connection)
        with connection:
            for table in ('facts', 'coverage'):
                connection.execute('DELETE FROM ' + table + ' WHERE source_date<? OR source_date>?',
                                   (context.history_start, context.report_date))
            for table in ('stages', 'cursors', 'settings'):
                connection.execute('DROP TABLE ' + table)
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('INVALID_SNAPSHOT_DB')
            unknown = connection.execute('SELECT DISTINCT game FROM facts').fetchall()
            if any(row[0] not in GAMES for row in unknown):
                raise ValueError('INVALID_SNAPSHOT_SCOPE')
            facts = hashlib.sha256()
            for table in ('facts', 'coverage'):
                for row in connection.execute('SELECT * FROM ' + table + ' ORDER BY source,game,source_date' + (',row_key' if table == 'facts' else '')):
                    # Collection timestamps and transient attempt errors do not define business facts.
                    projection = list(row[:5]) if table == 'facts' else [row[0], row[1], row[2], row[3], row[4], json.loads(row[6])]
                    facts.update((encode(projection) + '\n').encode('utf-8'))
            status = 'partial' if connection.execute("SELECT 1 FROM coverage WHERE status NOT IN ('available','provisional') LIMIT 1").fetchone() else 'available'
            if not {'gsc', 'ga4', 'orders'} <= set(source_names):
                status = 'partial'
    except BaseException:
        connection.close()
        candidate.unlink(missing_ok=True)
        raise
    connection.close()
    with candidate.open('r+b') as inp:
        os.fsync(inp.fileno())
    manifest = dict(schema_version=SCHEMA, snapshot_id=ident, publication_date=context.publication_date,
                    report_date=context.report_date, history_start=context.history_start, history_end=context.report_date,
                    business_timezone='Asia/Shanghai', games=list(GAMES), facts_hash=facts.hexdigest(),
                    data_status=status, frozen=True, daytime_collection_enabled=False, sha256=digest_file(candidate),
                    sources={name:('configured' if name in source_names else 'not_configured') for name in ('gsc','ga4','orders','serp','pages')})
    return candidate, manifest


def publish_once(root, candidate, manifest):
    root = Path(root)
    target = root / 'snapshots' / (manifest['snapshot_id'] + '.sqlite')
    meta = target.with_suffix('.json')
    if meta.exists():
        candidate.unlink(missing_ok=True)
        return json.loads(meta.read_text(encoding='utf-8'))
    if digest_file(candidate) != manifest['sha256']:
        raise ValueError('CANDIDATE_HASH_MISMATCH')
    os.replace(candidate, target)
    atomic_json(meta, manifest)
    atomic_json(root / 'current.json', manifest)
    return manifest


def open_snapshot(root, ident):
    if not re.fullmatch(r'seo-\d{4}-\d{2}-\d{2}', ident):
        raise ValueError('INVALID_SNAPSHOT_ID')
    target = Path(root) / 'snapshots' / (ident + '.sqlite')
    if target.is_symlink():
        raise ValueError('SNAPSHOT_SYMLINK')
    meta = json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
    if meta['snapshot_id'] != ident or digest_file(target) != meta['sha256']:
        raise ValueError('SNAPSHOT_HASH_MISMATCH')
    db = sqlite3.connect(target.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    return db, meta


def read(root, ident, kind, scope, cursor=0, limit=100):
    game(scope)
    if kind == 'rules':
        from .rules import evaluate
        history = read(root, ident, 'history', scope)
        return dict(snapshot_id=ident, facts_hash=history['facts_hash'], game=scope, rows=evaluate(history['rows']), next_cursor=None)
    if kind not in ('summary', 'history', 'sources', 'rankings', 'pages', 'orders') or not 0 <= cursor or not 1 <= limit <= 100:
        raise ValueError('INVALID_SNAPSHOT_QUERY')
    db, meta = open_snapshot(root, ident)
    try:
        if kind == 'sources':
            rows = [dict(r, quality=json.loads(r['quality'])) for r in db.execute(
                'SELECT * FROM coverage WHERE game=? ORDER BY source,source_date LIMIT ? OFFSET ?', (scope, limit + 1, cursor))]
        elif kind in ('summary', 'history'):
            rows = []
            day = dt.date.fromisoformat(meta['history_start'])
            while day.isoformat() <= meta['history_end']:
                measures = {}
                for source in ('gsc', 'ga4', 'orders'):
                    values = (json.loads(r[0])['metrics'] for r in db.execute(
                        'SELECT payload FROM facts WHERE game=? AND source=? AND source_date=? ORDER BY row_key', (scope, source, day.isoformat())))
                    first = next(values, None)
                    measures[source] = compute_metrics(itertools.chain([first], values), source) if first is not None else None
                rows.append(dict(source_date=day.isoformat(), metrics=measures))
                day += dt.timedelta(days=1)
            if kind == 'summary':
                rows = rows[-1:]
            rows = rows[cursor:cursor+limit+1]
        else:
            source = dict(rankings='serp', pages='pages', orders='orders')[kind]
            rows = [dict(source_date=r['source_date'], **json.loads(r['payload'])) for r in db.execute(
                'SELECT source_date,payload FROM facts WHERE game=? AND source=? ORDER BY source_date DESC,row_key LIMIT ? OFFSET ?',
                (scope, source, limit + 1, cursor))]
        return dict(snapshot_id=ident, facts_hash=meta['facts_hash'], game=scope, rows=rows[:limit],
                    next_cursor=cursor+limit if len(rows) > limit else None)
    finally:
        db.close()
