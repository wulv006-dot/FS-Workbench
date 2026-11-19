"""Private versioned index of the existing main-site ordinary Order delivery captures."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import sqlite3

ROOT = Path('/var/lib/fs-channel-effects')
DATABASE = 'order-delivery-index.sqlite3'
MAIN_SITE = 'www.mmoexp.com'
TZ = timezone(timedelta(hours=8))
MAX_SOURCE_BYTES = 128 * 1024 * 1024
FIELDS = ('delivery_id', 'source', 'sn', 'genre', 'trade_at', 'trade_amended_at', 'game',
          'qty', 'gift', 'cost_unit', 'cost_total', 'sale_total', 'settle_status', 'quantity_unit')
LOG = logging.getLogger(__name__)

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS batches (
        seq INTEGER PRIMARY KEY, input_hash TEXT NOT NULL UNIQUE, revision TEXT NOT NULL UNIQUE,
        observed TEXT NOT NULL, windows TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS delivery_versions (
        identity TEXT NOT NULL, first_seq INTEGER NOT NULL, last_seq INTEGER NOT NULL DEFAULT 0,
        observed TEXT NOT NULL, trade INTEGER NOT NULL, sn TEXT, body TEXT,
        PRIMARY KEY(identity,first_seq))''',
    # The production SQLite 3.7 runtime needs ordinary indexes. last_seq=0 marks the current version.
    '''CREATE UNIQUE INDEX IF NOT EXISTS active_delivery ON delivery_versions(identity,last_seq)''',
    '''CREATE INDEX IF NOT EXISTS active_trade ON delivery_versions(last_seq,trade)''',
    '''CREATE INDEX IF NOT EXISTS delivery_order ON delivery_versions(sn,last_seq,trade,first_seq)''',
    '''CREATE TABLE IF NOT EXISTS inputs (
        id INTEGER PRIMARY KEY CHECK(id=1), signature TEXT NOT NULL, retained_rolling INTEGER NOT NULL,
        rolling_window TEXT)''',
)


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False)


def trade_second(value):
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is not None or instant.isoformat(sep=' ', timespec='seconds') != value or instant.microsecond:
        raise ValueError('invalid_delivery_trade_time')
    return int(instant.replace(tzinfo=TZ).timestamp())


def local_second(value):
    return datetime.fromtimestamp(value, TZ).strftime('%Y-%m-%d %H:%M:%S')


def capture_time(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('delivery_capture_timezone_required')
    return value.astimezone(timezone.utc)


def covered_through(windows, source, since, *, as_of):
    """Last contiguous covered Shanghai second at the requested observation cutoff."""
    try:
        first = trade_second(since)
        cutoff = capture_time(as_of)
        intervals = sorted((trade_second(w['since']), trade_second(w['until'])) for w in windows
                           if w['source'] == source and capture_time(w['capturedAt']) <= cutoff)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    next_second = first
    for lo, hi in intervals:
        if lo > next_second:
            break
        next_second = max(next_second, hi + 1)
    last = min(next_second-1, int(cutoff.timestamp()))
    return local_second(last) if first <= last else None


def covers_window(windows, source, since, until, *, as_of):
    """Check contiguous inclusive Shanghai seconds, using only captures observable at as_of."""
    try:
        if trade_second(until) < trade_second(since):
            return False
    except (TypeError,ValueError):
        return False
    covered = covered_through(windows,source,since,as_of=as_of)
    return covered is not None and until <= covered


def safe_path(path):
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('delivery_index_symlink')


def source_files(root):
    safe_path(root)
    paths = sorted((root / 'delivery-days').glob('*.json'))
    rolling = root / 'order-deliveries.json'
    safe_path(rolling)
    if rolling.is_file():
        paths.append(rolling)
    signature = {}
    for path in paths:
        safe_path(path)
        stat = path.stat()
        if not path.is_file() or stat.st_size > MAX_SOURCE_BYTES:
            raise ValueError('delivery_index_source_file')
        signature[path.relative_to(root).as_posix()] = [stat.st_mtime_ns, stat.st_ino, stat.st_size]
    return signature


def parse_capture(path):
    from channel_cache import delivery_bounds

    value = json.loads(path.read_bytes())
    if (value.get('contract') != 'channel-order-deliveries-v1' or value.get('complete') is not True
            or value.get('scope') is not None or not isinstance(value.get('rows'), list)):
        raise ValueError('invalid_delivery_index_capture')
    period = value['period']
    day = path.parent.name == 'delivery-days'
    if day and period != {'start':path.stem, 'end':path.stem}:
        raise ValueError('invalid_delivery_index_day')
    first, last = map(trade_second, delivery_bounds(period))
    observed = capture_time(value['generatedAt'])
    if not last <= observed.timestamp() <= datetime.now(timezone.utc).timestamp():
        raise ValueError('invalid_delivery_index_capture_time')
    observed = observed.isoformat(timespec='microseconds')
    first_label, last_label = local_second(first), local_second(last)
    rows = {}
    retained = False
    for raw in value['rows']:
        if not first_label <= raw['trade_at'] <= last_label:
            if day:
                raise ValueError('delivery_index_trade_outside_day')
            # Rolling archives retain earlier rows without current range evidence.
            retained = True
            continue
        identity = str(raw.get('delivery_id') or '')
        order = raw.get('sn')
        if (not identity.isascii() or not identity.isdecimal() or len(identity)>32 or identity in rows
                or raw.get('source') != MAIN_SITE or str(raw.get('genre')) != '1'
                or order is not None and (not isinstance(order, str) or len(order)>160)):
            raise ValueError('invalid_delivery_index_identity')
        body = {key:raw[key] for key in FIELDS if key in raw}
        if any(type(item) not in (str, int, float, type(None)) for item in body.values()):
            raise ValueError('invalid_delivery_index_field')
        trade = trade_second(raw['trade_at'])
        rows[identity] = (trade, order, encode(body))
    digest = sha256(encode([first, last, observed, rows]).encode()).hexdigest()
    return observed, first, last, digest, rows, retained


def bind_windows(previous, first, last, seq, observed):
    kept = []
    additions = [(first, last)]
    for lo, hi, old_seq, old_at in previous:
        if hi < first or last < lo:
            kept.append((lo, hi, old_seq, old_at))
        elif old_at >= observed:
            if old_at == observed:
                raise ValueError('delivery_capture_revision_conflict')
            kept.append((lo, hi, old_seq, old_at))
            pieces = []
            for a, b in additions:
                if b < lo or hi < a:
                    pieces.append((a, b))
                else:
                    if a < lo:
                        pieces.append((a, lo-1))
                    if hi < b:
                        pieces.append((hi+1, b))
            additions = pieces
        else:
            if lo < first:
                kept.append((lo, first-1, old_seq, old_at))
            if last < hi:
                kept.append((last+1, hi, old_seq, old_at))
    return sorted(kept + [(lo, hi, seq, observed) for lo, hi in additions]), additions


def apply_capture(db, capture, head):
    observed, first, last, digest, rows, _ = capture
    if db.execute('SELECT 1 FROM batches WHERE input_hash=?', (digest,)).fetchone():
        return head
    seq, previous, windows = head
    seq += 1
    revision = sha256(encode([previous, digest]).encode()).hexdigest()
    windows, additions = bind_windows(windows, first, last, seq, observed)
    incoming = {key:row for key,row in rows.items() if any(lo <= row[0] <= hi for lo,hi in additions)}
    prior = {}
    for lo, hi in additions:
        prior.update((row[0],row[1:]) for row in db.execute(
            '''SELECT identity,observed,trade,sn,body FROM delivery_versions
               WHERE last_seq=0 AND body IS NOT NULL AND trade BETWEEN ? AND ?''', (lo,hi)))
    extra = sorted(incoming.keys()-prior.keys())
    for offset in range(0, len(extra), 400):
        keys = extra[offset:offset+400]
        prior.update((row[0],row[1:]) for row in db.execute(
            'SELECT identity,observed,trade,sn,body FROM delivery_versions WHERE last_seq=0 AND identity IN ('
            + ','.join('?' for _ in keys) + ')', keys))
    retire, touch, insert = [], [], []
    for key in prior.keys() | incoming.keys():
        old = prior.get(key)
        new = incoming.get(key)
        if old and old[0] > observed:
            continue
        if new is None:
            new = (old[1], old[2], None)
        if old and old[0] == observed and old[1:] != new:
            raise ValueError('delivery_identity_revision_conflict')
        if old and old[1:] == new:
            touch.append((observed,key))
            continue
        if old:
            retire.append((seq,key))
        insert.append((key,seq,observed,*new))
    db.executemany('UPDATE delivery_versions SET last_seq=? WHERE identity=? AND last_seq=0', retire)
    db.executemany('UPDATE delivery_versions SET observed=? WHERE identity=? AND last_seq=0', touch)
    db.executemany('INSERT INTO delivery_versions(identity,first_seq,observed,trade,sn,body) VALUES(?,?,?,?,?,?)', insert)
    db.execute('INSERT INTO batches VALUES(?,?,?,?,?)', (seq,digest,revision,observed,encode(windows)))
    return seq, revision, windows


def sync(root=ROOT):
    """Publish the existing archived sources atomically. Performs no upstream reads."""
    root = Path(root)
    signature = source_files(root)
    if not signature:
        return None
    path = root / DATABASE
    safe_path(path)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    with closing(sqlite3.connect(path, timeout=0.25)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for statement in SCHEMA:
            db.execute(statement)
        stored = db.execute('SELECT signature,retained_rolling,rolling_window FROM inputs WHERE id=1').fetchone()
        before = json.loads(stored[0]) if stored else {}
        retained = stored[1] if stored else False
        rolling = stored[2] if stored else None
        if before.keys() - signature.keys():
            raise ValueError('indexed_delivery_source_removed')
        last = db.execute('SELECT seq,revision,windows FROM batches ORDER BY seq DESC LIMIT 1').fetchone()
        head = (last[0],last[1],json.loads(last[2])) if last else (0,None,[])
        changed = [name for name,info in signature.items() if info != before.get(name)]
        if not changed:
            return head[1]
        candidates = {name:parse_capture(root/name) for name in changed}
        if 'order-deliveries.json' in candidates:
            stamp, first, last, _, _, retained = candidates['order-deliveries.json']
            rolling = encode(dict(source=MAIN_SITE,since=local_second(first),until=local_second(last),capturedAt=stamp))
        for capture in sorted(candidates.values(), key=lambda item:item[:4]):
            head = apply_capture(db,capture,head)
        if source_files(root) != signature:
            raise ValueError('delivery_source_changed_during_index')
        db.execute('INSERT OR REPLACE INTO inputs VALUES(1,?,?,?)', (encode(signature),int(retained),rolling))
        return head[1]


def sync_after_publish(root=ROOT):
    """Keep the original producer usable if indexing needs a later retry."""
    try:
        return sync(root)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
        LOG.warning('Order delivery index pending: %s', type(error).__name__)
        return None


def read_orders(order_keys, *, root=ROOT, since=None, until=None, revision=None):
    """Read private Order keys and exact source windows from a single pinned transaction."""
    empty = dict(status='unavailable', rows=[], revision=None, generatedAt=None, windows=[],
                 legacyCompatible=False,legacyReason='index_unavailable',rollingWindow=None)
    keys = set()
    for source, order in order_keys:
        if source != MAIN_SITE:
            return dict(empty,reason='unsupported_source')
        if not isinstance(order, str) or not 0 < len(order) <= 160:
            raise ValueError('invalid_delivery_order_key')
        keys.add(order)
    limit_start = trade_second(since) if since is not None else None
    limit_end = trade_second(until) if until is not None else None
    if limit_start is not None and limit_end is not None and limit_start > limit_end:
        raise ValueError('invalid_delivery_read_window')
    root = Path(root)
    path = root / DATABASE
    try:
        safe_path(path)
        if not path.is_file():
            return dict(empty,reason='index_missing')
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=0.15)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            legacy_reason = 'historical_revision'
            rolling = None
            if revision is None:
                stored = db.execute('SELECT signature,retained_rolling,rolling_window FROM inputs WHERE id=1').fetchone()
                if stored is None or json.loads(stored[0]) != source_files(root):
                    return dict(empty,status='stale',reason='source_revision_changed')
                supplements = root/'order-supplements.json'
                legacy_reason = ('rolling_retained_rows' if stored[1] else
                                 'order_supplements_present' if supplements.exists() or supplements.is_symlink() else None)
                rolling = json.loads(stored[2]) if stored[2] else None
                batch = db.execute('SELECT seq,revision,windows FROM batches ORDER BY seq DESC LIMIT 1').fetchone()
            else:
                batch = db.execute('SELECT seq,revision,windows FROM batches WHERE revision=?', (revision,)).fetchone()
            if not batch:
                return dict(empty,reason='revision_missing')
            seq, revision, window_doc = batch
            versions = json.loads(window_doc)
            refs = sorted({item[2] for item in versions})
            revisions = {}
            for offset in range(0,len(refs),400):
                group = refs[offset:offset+400]
                revisions.update(db.execute('SELECT seq,revision FROM batches WHERE seq IN ('
                    + ','.join('?' for _ in group) + ')', group))
            windows = [dict(source=MAIN_SITE,since=local_second(lo),until=local_second(hi),
                            capturedAt=stamp,revision=revisions[ref]) for lo,hi,ref,stamp in versions]
            where = ['body IS NOT NULL']
            args = []
            if batch[1] == db.execute('SELECT revision FROM batches ORDER BY seq DESC LIMIT 1').fetchone()[0]:
                where.append('last_seq=0')
            else:
                where.append('first_seq<=? AND (last_seq=0 OR last_seq>?)')
                args.extend((seq,seq))
            if limit_start is not None:
                where.append('trade>=?')
                args.append(limit_start)
            if limit_end is not None:
                where.append('trade<=?')
                args.append(limit_end)
            rows = []
            ordered = sorted(keys)
            for offset in range(0,len(ordered),400):
                group = ordered[offset:offset+400]
                sql = ('SELECT body FROM delivery_versions INDEXED BY delivery_order WHERE ' + ' AND '.join(where)
                       + ' AND sn IN (' + ','.join('?' for _ in group) + ')')
                rows.extend(json.loads(body) for body, in db.execute(sql,(*args,*group)))
            rows.sort(key=lambda row:(row['trade_at'], str(row['delivery_id'])))
            return dict(status='available',rows=rows,revision=revision,
                        generatedAt=max((w['capturedAt'] for w in windows),default=None),windows=windows,
                        legacyCompatible=legacy_reason is None,legacyReason=legacy_reason,rollingWindow=rolling)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        return dict(empty,reason=type(error).__name__)
