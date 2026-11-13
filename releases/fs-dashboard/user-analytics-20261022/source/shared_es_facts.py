"""Private, publication-pinned ES facts inside the existing customer database."""
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3

from user_contract import canonical, digest, stamp

DB = Path('/var/lib/fs-user-analytics/customers.sqlite3')
CONTRACT = 'shared-es-order-facts-v1'
META = 'shared_es_publication'
FIELDS = ('id', 'order_no', 'site_id', 'gid', 'game_format', 'paytime', 'pay_status',
          'status_format', 'amount_usd_format', 'amount_rmb_format', 'discount_code',
          'recommend_uid', 'country_code', 'country', 'paytype_display', 'paytype')
DAY = timedelta(days=1)
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS shared_es_slices (
           day TEXT NOT NULL, revision TEXT NOT NULL, manifest_key TEXT NOT NULL,
           body TEXT NOT NULL, PRIMARY KEY(day,revision))''',
    '''CREATE INDEX IF NOT EXISTS shared_es_stage
       ON shared_es_slices(day,manifest_key)''',
    '''CREATE TABLE IF NOT EXISTS shared_es_native (
           day TEXT NOT NULL, revision TEXT NOT NULL, site TEXT NOT NULL, gid TEXT NOT NULL,
           order_hash TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(day,revision,site,order_hash))''',
    '''CREATE INDEX IF NOT EXISTS shared_es_native_scope
       ON shared_es_native(day,revision,site,gid)''',
    '''CREATE INDEX IF NOT EXISTS shared_es_native_hash
       ON shared_es_native(day,revision,order_hash)''',
    '''CREATE TABLE IF NOT EXISTS shared_es_lines (
           day TEXT NOT NULL, revision TEXT NOT NULL, order_hash TEXT NOT NULL,
           signature TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(day,revision,signature))''',
    '''CREATE INDEX IF NOT EXISTS shared_es_lines_hash
       ON shared_es_lines(day,revision,order_hash)''',
    '''CREATE TABLE IF NOT EXISTS shared_es_publications (
           publication_id TEXT PRIMARY KEY, data_revision TEXT NOT NULL, captured_at TEXT NOT NULL,
           cutoff TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS shared_es_publication_days (
           publication_id TEXT NOT NULL, day TEXT NOT NULL, revision TEXT NOT NULL,
           PRIMARY KEY(publication_id,day))''',
)


def _days(start, end):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if end < start:
        raise ValueError('shared_es_period')
    while start <= end:
        yield start.isoformat()
        start += DAY


def _exists(db):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_es_publication_days'").fetchone() is not None


def _order_hash(order_no):
    return hashlib.sha256(order_no.encode()).hexdigest()


def coupon_tracking(rows, logs, clean, gaps=()):
    out = {}
    for row in rows:
        key = (str(row['site_id']), row['order_no'])
        coupons = None if key in gaps else [dict(id=str(log['id']), templateId=str(log.get('coupon_id') or 'unknown'),
                        title=clean(log.get('title')) or '未命名优惠券',
                        batch=clean((log.get('memberCoupon') or {}).get('grant_batch_no')) or '批次未提供')
                   for log in logs.get(key, ())]
        out[key] = dict(code=clean(row.get('discount_code')), promoterUid=clean(row.get('recommend_uid')),
                        country=clean(row.get('country_code') or row.get('country')),
                        payment=clean(row.get('paytype_display') or row.get('paytype')), coupons=coupons)
    return out


def _native(rows, day, tracking):
    projected = []
    identities = set()
    for raw in rows:
        site, gid, order_no = str(raw.get('site_id') or ''), str(raw.get('gid') or ''), raw.get('order_no')
        title = (raw.get('site') or {}).get('full_title')
        paid = str(raw.get('paytime') or '')
        if (not site.isdecimal() or not gid.isdecimal() or not isinstance(order_no, str)
                or not order_no or len(order_no) > 160 or not isinstance(title, str) or not title.strip()
                or not day + ' 00:00:00' <= paid <= day + ' 23:59:59'
                or str(raw.get('pay_status')) not in ('1', '2') or (site, order_no) in identities):
            raise ValueError('shared_es_native_identity')
        identities.add((site, order_no))
        body = {field: raw[field] for field in FIELDS if field in raw}
        body['site'] = {'full_title': title}
        if (site, order_no) in tracking:
            body['tracking'] = tracking[site, order_no]
        projected.append((site, gid, _order_hash(order_no), canonical(body)))
    return sorted(projected)


def _lines(rows, day):
    projected = []
    seen = set()
    for raw in rows:
        signature, order_hash = raw.get('_signature'), raw.get('订单号') or ''
        if (str(raw.get('付款时间', '')).replace('/', '-')[:10] != day
                or not isinstance(signature, str) or len(signature) != 64):
            raise ValueError('shared_es_line_identity')
        if signature not in seen:
            body = dict(raw)
            attribution = dict(body.get('marketing_attribution') or {})
            attribution.pop('source_revision', None)
            attribution.pop('available_at', None)
            body['marketing_attribution'] = attribution
            projected.append((order_hash, signature, canonical(body)))
            seen.add(signature)
    return sorted(projected)


def stage_day(store, day, manifest_key, dataset, native_rows, tracking, captured_at):
    """Write only a complete archive/day identity observation, outside public visibility."""
    day = date.fromisoformat(day).isoformat()
    if (dataset.get('_private_dataset') is not True or dataset.get('revision_selection') != 'published_pins'
            or dataset.get('failed_files') != 0 or dataset.get('parse_failures') != 0
            or not dataset.get('hashes') or dataset.get('status') not in ('available', 'partial')):
        raise ValueError('shared_es_archive_incomplete')
    native = _native(native_rows, day, tracking)
    lines = _lines(dataset['rows'], day)
    meta = dict(contract=CONTRACT, hashes=dataset['hashes'], status=dataset['status'],
                revision_conflicts=dataset.get('revision_conflicts', []),
                captured_at=captured_at, native_rows=len(native), es_lines=len(lines))
    revision = digest(dict(day=day, native=native, lines=lines, hashes=meta['hashes']))
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for statement in SCHEMA:
            db.execute(statement)
        prior = db.execute('SELECT manifest_key FROM shared_es_slices WHERE day=? AND revision=?',
                           (day, revision)).fetchone()
        if prior:
            if prior[0] != manifest_key:
                db.execute('UPDATE shared_es_slices SET manifest_key=? WHERE day=? AND revision=?',
                           (manifest_key, day, revision))
            return revision
        db.execute('INSERT INTO shared_es_slices VALUES(?,?,?,?)', (day, revision, manifest_key, canonical(meta)))
        db.executemany('INSERT INTO shared_es_native VALUES(?,?,?,?,?,?)',
                       ((day, revision, *row) for row in native))
        db.executemany('INSERT INTO shared_es_lines VALUES(?,?,?,?,?)',
                       ((day, revision, *row) for row in lines))
    return revision


def staged(store, day, manifest_key):
    with store.db() as db:
        if not _exists(db):
            return None
        rows = db.execute('SELECT revision FROM shared_es_slices WHERE day=? AND manifest_key=?',
                          (day, manifest_key)).fetchall()
    if len(rows) > 1:
        raise ValueError('shared_es_stage_conflict')
    return rows[0][0] if rows else None


def prepare_publication(store, value, start, end, *, reader=None, archive=None, checkpoint=None):
    """Parse only newly covered/reviewed dates, once per batch, from existing archive pins."""
    if reader is None:
        from user_source import shared_es_native_day
        reader = shared_es_native_day
    if archive is None:
        from es_order_structure import archived_dataset
        archive = archived_dataset
    days = list(_days(start, end))
    if len(days) > 31:
        raise ValueError('shared_es_stage_period_limit')
    manifest_key = digest(value['flag_manifests'])
    revisions = {day: staged(store, day, manifest_key) for day in days}
    if all(revisions.values()):
        return revisions
    dataset = archive(dict(profile='ALL', start=start, end=end), publication=value)
    per_day = defaultdict(list)
    for row in dataset['rows']:
        day = str(row.get('付款时间') or '').replace('/', '-')[:10]
        if day not in revisions:
            raise ValueError('shared_es_archive_scope')
        per_day[day].append(row)
    for day, revision in revisions.items():
        if revision:
            continue
        if checkpoint is not None and checkpoint():
            return None
        native_rows, tracking = reader(day)
        revisions[day] = stage_day(store, day, manifest_key, dict(dataset, rows=per_day[day]),
                                   native_rows, tracking, value['published_at'])
    return revisions


def bind_publication(db, value, previous, revisions):
    """Bind updated days under the same transaction as the existing publication CAS."""
    if not _exists(db):
        if revisions:
            raise ValueError('shared_es_stage_unavailable')
        return
    active = db.execute('SELECT value FROM meta WHERE key=?', (META,)).fetchone()
    prior = active[0] if active else previous
    ident = value['publication_id']
    cutoff = stamp(value['cutoff']).date().isoformat()
    existing = db.execute(
        'SELECT data_revision,captured_at,cutoff FROM shared_es_publications WHERE publication_id=?',
        (ident,)).fetchone()
    if existing:
        recorded = dict(db.execute('SELECT day,revision FROM shared_es_publication_days WHERE publication_id=?',
                                   (ident,)))
        if ((existing[0], existing[1]) != (value['data_version'], value['published_at']) or existing[2] < cutoff
                or any(day >= cutoff or recorded.get(day) != revision for day, revision in revisions.items())):
            raise ValueError('shared_es_publication_replay_conflict')
        return
    carry = (db.execute('SELECT cutoff FROM shared_es_publications WHERE publication_id=?', (prior,)).fetchone()
             if prior else None)
    shared_cutoff = max(cutoff, carry[0]) if carry else cutoff
    db.execute('INSERT INTO shared_es_publications VALUES(?,?,?,?)',
               (ident, value['data_version'], value['published_at'], shared_cutoff))
    if prior:
        db.execute('''INSERT INTO shared_es_publication_days
                      SELECT ?,day,revision FROM shared_es_publication_days
                      WHERE publication_id=? AND day<?''', (ident, prior, shared_cutoff))
    for day, revision in revisions.items():
        if (day >= cutoff or not db.execute(
                'SELECT 1 FROM shared_es_slices WHERE day=? AND revision=?', (day, revision)).fetchone()):
            raise ValueError('shared_es_publication_stage_mismatch')
        db.execute('INSERT OR REPLACE INTO shared_es_publication_days VALUES(?,?,?)', (ident, day, revision))
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (META, ident))


def seed(store, start, end, *, apply=False, now=None, archive_root=None, reader=None, archive=None):
    """Explicit finite import from existing complete archives, using the producer's native map."""
    from user_customer_types import ARCHIVE, manifest_inventory
    from user_weekly import stored_publication

    root = ARCHIVE if archive_root is None else Path(archive_root)
    now = stamp(now) if now is not None else datetime.now(stamp(start).tzinfo)
    days = list(_days(start, end))
    if not days or len(days) > 7 or date.fromisoformat(end) >= now.date():
        raise ValueError('shared_es_seed_period')
    published = stored_publication(store)
    if published is None:
        raise ValueError('shared_es_seed_publication_unavailable')
    available = defaultdict(list)
    for pin in manifest_inventory(root):
        raw = (root / pin['name']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ValueError('shared_es_seed_manifest_changed')
        manifest = json.loads(raw)
        query, file_set = manifest['query'], manifest.get('file_set') or {}
        hashes = manifest.get('file_sha256') or []
        if (not hashes or file_set.get('failed_files') != 0 or file_set.get('declared_files') != len(hashes)
                or stamp(manifest['captured_at']) > now):
            continue
        for day in days:
            if query['start'] <= day <= query['end']:
                available[day].append(pin)
    active = latest_publication(db=store.path)
    covered = {}
    if active:
        with closing(_read_db(store.path)) as connection:
            covered = dict(connection.execute(
                '''SELECT day,revision FROM shared_es_publication_days
                   WHERE publication_id=? AND day BETWEEN ? AND ? ORDER BY day''',
                (active['publication_id'], start, end)))
    missing = [day for day in days if day not in covered and day not in available]
    needed = [day for day in days if day in available and day not in covered]
    ready = {}
    for day in needed:
        key = digest(available[day])
        if revision := staged(store, day, key):
            ready[day] = revision
    result = dict(status='preview', selected_days=days, already_indexed=sorted(covered),
                  missing_es_days=missing, reusable_staged_days=sorted(ready),
                  needs_native_identity_days=[day for day in needed if day not in ready],
                  base_publication_id=active['publication_id'] if active else published['publication_id'])
    if not apply or not needed:
        return result
    if archive is None:
        from es_order_structure import archived_dataset
        archive = lambda args, **options: archived_dataset(args, root=root, **options)
    for day in needed:
        if day in ready:
            continue
        candidate = dict(published, flag_manifests=available[day], published_at=now.isoformat(),
                         cutoff=stamp((date.fromisoformat(day) + DAY).isoformat()).isoformat())
        candidate.pop('publication_id')
        candidate['publication_id'] = 'uw_' + digest(candidate)[:32]
        ready.update(prepare_publication(store, candidate, day, day, reader=reader, archive=archive))
    cutoff = stamp((date.fromisoformat(max(days)) + DAY).isoformat())
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT value FROM meta WHERE key=?', (META,)).fetchone()
        base = prior[0] if prior else published['publication_id']
        if base != result['base_publication_id']:
            raise ValueError('shared_es_seed_publication_changed')
        previous = db.execute('SELECT cutoff FROM shared_es_publications WHERE publication_id=?', (base,)).fetchone()
        cutoff = max(cutoff, stamp(previous[0] if previous else published['cutoff']))
        value = dict(data_version=published['data_version'], published_at=now.isoformat(), cutoff=cutoff.isoformat())
        value['publication_id'] = 'se_' + digest(dict(value, base=base, revisions=ready))[:32]
        bind_publication(db, value, base, ready)
    return dict(result, status='partial' if missing else 'available', publication_id=value['publication_id'],
                indexed_days=sorted(ready))


def _unavailable(days, publication_id=None):
    return dict(status='unavailable', rows=[], dataset=None, identity_catalog=None,
                coverage=dict(complete=False, missing_days=days, day_revisions={}, source_revision=None,
                              publication_id=publication_id, data_revision=None, captured_at=None, cutoff=None,
                              order_facts_status='unavailable',
                              admin_complete=False, admin_date_basis='paytime', admin_snapshot=True,
                              admin_source_rows=0, admin_payment_membership='pay_status_1_or_2'))


def _scoped_rows(db, days, site, gid, publication_id):
    rows, lines, identities, order_hashes = [], [], {}, set()
    args = [value for value in (site, gid) if value != 'all']
    conditions = ''.join(' AND n.' + field + '=?' for field, value in (('site', site), ('gid', gid)) if value != 'all')
    for day, revision in days.items():
        key = (day, revision)
        rows.extend(json.loads(r[0]) for r in db.execute(
            'SELECT n.body FROM shared_es_native n WHERE n.day=? AND n.revision=?' + conditions, (*key, *args)))
        line_sql = 'SELECT l.order_hash,l.body FROM shared_es_lines l WHERE l.day=? AND l.revision=?'
        if conditions:
            line_sql += (''' AND EXISTS(SELECT 1 FROM shared_es_native n WHERE n.day=l.day
                         AND n.revision=l.revision AND n.order_hash=l.order_hash''' + conditions + ')')
        for order_hash, body in db.execute(line_sql, (*key, *args)):
            row = json.loads(body)
            fact = row['marketing_attribution']
            fact['source_revision'] = publication_id
            lines.append(row)
            if order_hash:
                order_hashes.add(order_hash)
    # The old all-site bridge checks collisions across the requested period,
    # including the same order number on two websites on different days.
    keys = sorted(order_hashes)
    for day, revision in days.items():
        for offset in range(0, len(keys), 400):
            group = keys[offset:offset + 400]
            params = ','.join('?' for _ in group)
            for native, in db.execute(
                    'SELECT body FROM shared_es_native WHERE day=? AND revision=? AND order_hash IN (' + params + ')',
                    (day, revision, *group)):
                match = json.loads(native)
                match_key = (str(match['site_id']), match['order_no'])
                identities[match_key] = {field: match[field] for field in ('site_id', 'order_no', 'site')}
    return rows, lines, list(identities.values())


def _read_db(path):
    path = Path(path)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('shared_es_database_link')
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)


def latest_publication(*, db=DB):
    """Return metadata for the active shared snapshot, without reading orders."""
    if not Path(db).is_file():
        return None
    with closing(_read_db(db)) as connection:
        if not _exists(connection):
            return None
        row = connection.execute(
            '''SELECT p.publication_id,p.data_revision,p.captured_at,p.cutoff
               FROM shared_es_publications p JOIN meta m ON m.value=p.publication_id WHERE m.key=?''',
            (META,)).fetchone()
    return dict(zip(('publication_id', 'data_revision', 'captured_at', 'cutoff'), row)) if row else None


def read(scope, *, db=DB, publication_id=None):
    """Read one private shared snapshot. The caller owns existing scope permissions."""
    start, end, site, gid = (scope[k] for k in ('start', 'end', 'site_id', 'gid'))
    if any(not isinstance(v, str) or v != 'all' and not v.isdecimal() for v in (site, gid)):
        raise ValueError('shared_es_scope')
    days = list(_days(start, end))
    if not Path(db).is_file():
        return _unavailable(days, publication_id)
    with closing(_read_db(db)) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        if not _exists(connection):
            return _unavailable(days, publication_id)
        if publication_id is None:
            current = connection.execute('SELECT value FROM meta WHERE key=?', (META,)).fetchone()
            if current is None:
                raw = connection.execute("SELECT value FROM meta WHERE key='weekly_publication'").fetchone()
                if raw is None:
                    return _unavailable(days)
                publication_id = json.loads(raw[0])['publication_id']
            else:
                publication_id = current[0]
        published = connection.execute(
            'SELECT data_revision,captured_at,cutoff FROM shared_es_publications WHERE publication_id=?',
            (publication_id,)).fetchone()
        if published is None:
            return _unavailable(days, publication_id)
        version, captured_at, cutoff = published
        slices = connection.execute(
            '''SELECT p.day,p.revision,s.body FROM shared_es_publication_days p
               JOIN shared_es_slices s ON s.day=p.day AND s.revision=p.revision
               WHERE p.publication_id=? AND p.day BETWEEN ? AND ? ORDER BY p.day''',
            (publication_id, start, end)).fetchall()
        day_revisions = {day: revision for day, revision, _ in slices if day < cutoff}
        missing = [day for day in days if day not in day_revisions]
        if not day_revisions:
            return _unavailable(missing, publication_id)
        rows, lines, identities = _scoped_rows(connection, day_revisions, site, gid, publication_id)
    metadata = [json.loads(body) for day, _, body in slices if day in day_revisions]
    for row in lines:
        row['marketing_attribution']['available_at'] = captured_at
    hashes = sorted({value for item in metadata for value in item['hashes']})
    line_orders = {row.get('订单号') for row in lines}
    conflicts = sorted({value for item in metadata for value in item['revision_conflicts'] if value in line_orders})
    complete = not missing
    revision = digest(day_revisions)
    coverage = dict(complete=complete, missing_days=missing, day_revisions=day_revisions, source_revision=revision,
                    publication_id=publication_id, data_revision=version, captured_at=captured_at, cutoff=cutoff,
                    admin_complete=complete, admin_date_basis='paytime', admin_snapshot=True,
                    admin_source_rows=sum(item['native_rows'] for item in metadata),
                    order_facts_status='available' if complete and not conflicts else 'partial',
                    admin_payment_membership='pay_status_1_or_2', attribution_availability='published_pins')
    dataset = dict(_private_dataset=True, status='available' if complete and not conflicts else 'partial',
                   origin='shared_es_facts', rows=lines, hashes=hashes, source_revision=publication_id,
                   publication_id=publication_id, data_revision=version, available_at=captured_at,
                   revision_selection='published_pins', revision_conflicts=conflicts,
                   effective_scope=dict(start=start, end=end))
    identity_catalog = dict(complete=complete, revision=revision, rows=identities,
                            scope=dict(start=start, end=end, site='all', game='all', pay_status='1'))
    return dict(status=dataset['status'], rows=rows, dataset=dataset, identity_catalog=identity_catalog,
                coverage=coverage)

