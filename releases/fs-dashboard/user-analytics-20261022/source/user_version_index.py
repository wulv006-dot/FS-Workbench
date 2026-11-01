"""Opt-in revision range index. Build only on an isolated, consistent copy first.

The original orders/revisions remain authoritative. A stale/incomplete index is
never used. No schema migration runs at service startup or on a cache miss.
"""
import json

COLUMNS = 'order_key,site,gid,customer_id,paid_at,valid,body,revision'
CONTRACT = 'user-version-range-v1'


def state(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_version_index_state'").fetchone():
        return None
    return db.execute('SELECT contract,target,checkpoint,ready FROM user_version_index_state WHERE id=1').fetchone()


def ready(db, current):
    value = state(db)
    return bool(value and value[0] == CONTRACT and value[1] == current and value[3] == 1)


def insert_old(db, rows, superseded):
    for row in rows:
        if not 0 <= int(row['revision']) < superseded:
            raise ValueError('version_index_revision_interval')
        db.execute('INSERT OR IGNORE INTO user_order_versions (' + COLUMNS + ',superseded) VALUES(?,?,?,?,?,?,?,?,?)',
                   tuple(row[k] for k in COLUMNS.split(',')) + (superseded,))
        previous = db.execute('SELECT ' + COLUMNS + ',superseded FROM user_order_versions WHERE order_key=? AND revision=?',
                              (row['order_key'], row['revision'])).fetchone()
        if tuple(previous) != tuple(row[k] for k in COLUMNS.split(',')) + (superseded,):
            raise ValueError('version_index_conflicting_history')


def build_batch(db, limit=100):
    """Resumable migration; caller owns one transaction on an isolated copy.

    A revision JSON is the original indivisible unit, so its peak size must be
    measured before production migration. This function never copies current rows.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('version_index_batch_limit')
    current = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
    if state(db) is None:
        db.execute('CREATE TABLE user_version_index_state(id INTEGER PRIMARY KEY,contract TEXT,target INTEGER,checkpoint INTEGER,ready INTEGER)')
        db.execute('CREATE TABLE user_order_versions(order_key TEXT,site TEXT,gid TEXT,customer_id TEXT,paid_at TEXT,valid INTEGER,body TEXT,revision INTEGER,superseded INTEGER,PRIMARY KEY(order_key,revision))')
        db.execute('CREATE INDEX user_version_date ON user_order_versions(paid_at,revision,superseded)')
        db.execute('CREATE INDEX user_version_scope_date ON user_order_versions(site,gid,paid_at,revision,superseded)')
        db.execute('CREATE INDEX user_version_customer ON user_order_versions(customer_id,revision,superseded)')
        db.execute('CREATE INDEX IF NOT EXISTS user_order_scope_date ON orders(site,gid,paid_at,revision)')
        db.execute('INSERT INTO user_version_index_state VALUES(1,?,?,0,0)', (CONTRACT, current))
    value = state(db)
    if value[0] != CONTRACT or value[1] != current:
        raise ValueError('version_index_source_changed')
    if value[3]:
        return dict(ready=True, checkpoint=value[2], target=current, processed=0)
    processed, checkpoint = 0, value[2]
    for revision, body in db.execute('SELECT id,body FROM revisions WHERE id>? AND id<=? ORDER BY id LIMIT ?',
                                     (checkpoint, current, limit)).fetchall():
        insert_old(db, json.loads(body), revision)
        checkpoint, processed = revision, processed + 1
    done = not db.execute('SELECT 1 FROM revisions WHERE id>? AND id<=? LIMIT 1', (checkpoint, current)).fetchone()
    db.execute('UPDATE user_version_index_state SET checkpoint=?,ready=? WHERE id=1', (checkpoint, int(done)))
    return dict(ready=done, checkpoint=checkpoint, target=current, processed=processed)


def advance(db, previous, current, changes):
    """Same transaction as the authoritative revision; rollback preserves both."""
    if ready(db, previous):
        insert_old(db, changes, current)
        db.execute('UPDATE user_version_index_state SET target=?,checkpoint=? WHERE id=1', (current, current))


def statements(target, start=None, end=None, customer_id=None, scope=None):
    if (start is None) != (end is None) or start is not None and start >= end:
        raise ValueError('analytics_period_required')
    filters, args = [], []
    if start is not None:
        filters.extend(['paid_at>=?', 'paid_at<?']); args.extend([start, end])
    if customer_id is not None:
        filters.append('customer_id=?'); args.append(customer_id)
    if scope is not None:
        filters.extend(['site=?', 'gid=?']); args.extend(scope)
    suffix = (' AND ' + ' AND '.join(filters)) if filters else ''
    return [
        ('SELECT ' + COLUMNS + ' FROM orders WHERE revision<=?' + suffix, [target] + args),
        ('SELECT ' + COLUMNS + ' FROM user_order_versions WHERE revision<=? AND superseded>?' + suffix, [target, target] + args),
    ]


def read(db, target, **kwargs):
    # At most one interval per key is valid at target; never filter current dates
    # to choose historical keys. Every old row is filtered on its own date/scope.
    for sql, args in statements(target, **kwargs):
        for row in db.execute(sql, args):
            yield dict(row)
