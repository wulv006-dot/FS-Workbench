"""Private, publication-pinned ES facts inside the existing customer database."""
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from user_contract import canonical, digest, money, stamp

DB = Path('/var/lib/fs-user-analytics/customers.sqlite3')
CONTRACT = 'shared-es-order-facts-v1'
META = 'shared_es_publication'
PENDING = 'shared_es_pending:'
FC27_SITE, FC27_GID = '266', '1327'
FC27_PROJECTION_FIELDS = frozenset(('platform', 'purchase_k', 'bonus_k', 'delivered_k',
    'single_line_unit_purchase', 'region_id', 'regular_usd', 'retained_percent', 'points',
    'source_sha256', 'observed_at'))
FC27_PROJECTION_PIN = 'shared_es_fc27_projection:'
HISTORICAL_CHANNEL_SITE = '266'
HISTORICAL_CHANNEL_ROOT = Path('/var/lib/fs-channel-effects/days')
DISCOUNT_OWNER_PROJECTS = {
    '张玲玲':'KOL', '董文鑫':'广告投放', '陈宝':'广告投放', '刘晓辰':'分销', '尹岚':'分销',
    '张皓':'TikTok', '王修权':'SEO',
}
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
           source_at TEXT NOT NULL,
           PRIMARY KEY(publication_id,day))''',
)
DISCOUNT_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS shared_es_discount_revisions (
           revision TEXT PRIMARY KEY, captured_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS shared_es_discount_codes (
           revision TEXT NOT NULL, code TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(revision,code))''',
    '''CREATE TABLE IF NOT EXISTS shared_es_discount_pins (
           publication_id TEXT PRIMARY KEY, revision TEXT NOT NULL)''',
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


def _has_discount_catalog(db):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_es_discount_pins'").fetchone() is not None


def _discount_catalog(rows):
    selected = defaultdict(set)
    for row in rows:
        code = row.get('code')
        owner = row.get('admins')
        if str(row.get('site_id')) != HISTORICAL_CHANNEL_SITE:
            raise ValueError('shared_es_discount_scope')
        if not isinstance(code,str) or not 0 < len(code.strip()) <= 160:
            raise ValueError('shared_es_discount_code')
        owner_id = str(row.get('admin_id') or '')
        nickname = (owner or {}).get('nickname') if isinstance(owner,dict) else None
        nickname = nickname.strip() if isinstance(nickname,str) else ''
        valid_owner = (owner_id.isdecimal() and int(owner_id) > 0 and nickname
                       and str(owner.get('id')) == owner_id and any(ch.isalpha() for ch in nickname)
                       and nickname.casefold() not in ('无','未知','未设置','none','unknown'))
        project = DISCOUNT_OWNER_PROJECTS.get(nickname,'运营') if valid_owner else None
        def game_ids(field):
            values = {part.strip() for part in str(row.get(field) or '').split(',')} - {'','0'}
            if any(not gid.isdecimal() for gid in values):
                raise ValueError('shared_es_discount_game_scope')
            return sorted(values)
        selected[code.strip().casefold()].add(canonical(dict(project=project,games=game_ids('gid'),
                                                             excluded_games=game_ids('exclude_gids'))))
    return {key:sorted(variants) for key, variants in selected.items()}


def _store_discounts(db, catalog, captured_at):
    for statement in DISCOUNT_SCHEMA:
        db.execute(statement)
    revision = digest(catalog)
    if not db.execute('SELECT 1 FROM shared_es_discount_revisions WHERE revision=?',(revision,)).fetchone():
        db.execute('INSERT INTO shared_es_discount_revisions VALUES(?,?)',(revision,captured_at))
        db.executemany('INSERT INTO shared_es_discount_codes VALUES(?,?,?)',
                       ((revision,key,canonical([json.loads(item) for item in variants])) for key, variants in catalog.items()))
    return revision


def _discount_revision(db, publication_id):
    if not _has_discount_catalog(db):
        return None
    row = db.execute('SELECT revision FROM shared_es_discount_pins WHERE publication_id=?',(publication_id,)).fetchone()
    return row[0] if row else None


def _scoped_discount_projects(db, rows, revision):
    if not revision:
        return
    codes = sorted({r['discount_code'].strip().casefold() for r in rows
                    if r['site_id'] in (266,'266') and isinstance(r.get('discount_code'),str) and r['discount_code'].strip()})
    entries = {}
    for offset in range(0,len(codes),400):
        group = codes[offset:offset+400]
        placeholders = ','.join('?' for _ in group)
        entries.update((code,json.loads(body)) for code,body in db.execute(
            'SELECT code,body FROM shared_es_discount_codes WHERE revision=? AND code IN ('+placeholders+')',
            (revision,*group)))
    for row in rows:
        code = row.get('discount_code')
        if str(row['site_id']) != HISTORICAL_CHANNEL_SITE or not isinstance(code,str):
            continue
        gid = str(row['gid'])
        projects = {item['project'] for item in entries.get(code.strip().casefold(),())
                    if (not item['games'] or gid in item['games']) and gid not in item['excluded_games']}
        if len(projects)==1 and None not in projects:
            row.setdefault('tracking',{})['discountOperatorProject'] = next(iter(projects))


def _order_hash(order_no):
    return hashlib.sha256(order_no.encode()).hexdigest()


def _checked_fc27_projection(value):
    if (not isinstance(value,dict) or value.keys()!=FC27_PROJECTION_FIELDS
            or value['platform'] not in ('PS','XBOX','PC') or type(value['single_line_unit_purchase']) is not bool
            or value['region_id'] is not None and (type(value['region_id']) is not int or value['region_id'] < 0)
            or not isinstance(value['source_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['source_sha256'])):
        raise ValueError('shared_es_fc27_projection')
    amounts = {key:money(value[key]) for key in ('purchase_k','bonus_k','delivered_k','regular_usd','retained_percent','points')}
    purchase, bonus, delivered = (amounts[key] for key in ('purchase_k','bonus_k','delivered_k'))
    if (None in (purchase,bonus,delivered) or Decimal(purchase)<=0 or Decimal(bonus)<0
            or Decimal(purchase)+Decimal(bonus)!=Decimal(delivered)):
        raise ValueError('shared_es_fc27_quantity')
    return {**value, **amounts, 'observed_at':stamp(value['observed_at']).isoformat()}


def _fc27_projection_pin(db, publication_id):
    row = db.execute('SELECT value FROM meta WHERE key=?',(FC27_PROJECTION_PIN+publication_id,)).fetchone()
    return row[0] if row else None


def _supplement_fc27(db, rows, days, pin):
    revision = _fc27_projection_pin(db,pin)
    if not revision:
        return
    by_key = {(raw['paytime'][:10],_order_hash(raw['order_no'])):raw for raw in rows if 'fc27_coins' not in raw}
    for day, day_revision in days.items():
        for order_hash, body in db.execute('''SELECT order_hash,body FROM shared_es_fc27_projection
                WHERE revision=? AND day=? AND day_revision=?''',(revision,day,day_revision)):
            raw = by_key.get((day,order_hash))
            if raw is not None:
                raw['fc27_coins'] = json.loads(body)


def store_fc27_projection(store, *, publication_id, source_revision, scope, rows):
    """Bind one exact Admin-ID supplement to a new shared pin without copying native rows."""
    if (scope['site_id'],scope['gid'])!=(FC27_SITE,FC27_GID):
        raise ValueError('shared_es_fc27_scope')
    wanted = set(_days(scope['start'],scope['end']))
    submitted = {}
    for row in rows:
        paid = row['paid_at']
        order_no, ident = row['order_no'], str(row['id'])
        day = stamp(paid).date().isoformat()
        if day not in wanted or not ident.isdecimal() or not isinstance(order_no,str) or not order_no:
            raise ValueError('shared_es_fc27_scope')
        key = (day,_order_hash(order_no))
        if key in submitted:
            raise ValueError('shared_es_fc27_duplicate_identity')
        projection = _checked_fc27_projection(row['fc27_coins'])
        if stamp(projection['observed_at']) < stamp(paid):
            raise ValueError('shared_es_fc27_observation_time')
        submitted[key] = (ident,order_no,paid,projection)
    revision = digest([publication_id,source_revision,sorted(wanted),sorted(submitted.items())])
    next_pin = 'se_'+digest([publication_id,revision])[:32]
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT p.publication_id,p.data_revision,p.captured_at,p.cutoff
            FROM shared_es_publications p JOIN meta m ON m.value=p.publication_id WHERE m.key=?''',(META,)).fetchone()
        if row is not None and row[0]==next_pin and _fc27_projection_pin(db,next_pin)==revision:
            return dict(status='reused',publication_id=next_pin,supplement_revision=revision)
        if row is None or row[0]!=publication_id:
            raise ValueError('shared_es_fc27_publication_changed')
        _,version,captured_at,cutoff = row
        slices = db.execute('''SELECT p.day,p.revision,s.body FROM shared_es_publication_days p
            JOIN shared_es_slices s ON s.day=p.day AND s.revision=p.revision
            WHERE p.publication_id=? AND p.day BETWEEN ? AND ?''',(publication_id,scope['start'],scope['end']))
        days = {day:day_revision for day,day_revision,body in slices
                if day < cutoff and 'archive_site' not in json.loads(body)}
        if set(days)!=wanted or digest(days)!=source_revision:
            raise ValueError('shared_es_fc27_source_changed')
        values = {}
        for (day,order_hash),(ident,order_no,paid,projection) in submitted.items():
            native = db.execute('''SELECT body FROM shared_es_native
                WHERE day=? AND revision=? AND site=? AND gid=? AND order_hash=?''',
                (day,days[day],FC27_SITE,FC27_GID,order_hash)).fetchone()
            raw = json.loads(native[0]) if native else {}
            if (str(raw.get('id')),raw.get('order_no'),raw.get('paytime'))!=(ident,order_no,paid):
                raise ValueError('shared_es_fc27_identity_mismatch')
            if 'fc27_coins' not in raw:
                values[(day,days[day],order_hash)] = canonical(projection)
        if not values:
            return dict(status='unchanged',publication_id=publication_id,supplement_revision=None,rows=0)
        db.execute('''CREATE TABLE IF NOT EXISTS shared_es_fc27_projection (
            revision TEXT NOT NULL, day TEXT NOT NULL, day_revision TEXT NOT NULL, order_hash TEXT NOT NULL, body TEXT NOT NULL,
            PRIMARY KEY(revision,day,day_revision,order_hash))''')
        prior_revision = _fc27_projection_pin(db,publication_id)
        if prior_revision:
            db.execute('''INSERT INTO shared_es_fc27_projection
                SELECT ?,s.day,s.day_revision,s.order_hash,s.body FROM shared_es_fc27_projection s
                JOIN shared_es_publication_days p ON p.day=s.day AND p.revision=s.day_revision
                WHERE s.revision=? AND p.publication_id=?''',(revision,prior_revision,publication_id))
        db.executemany('INSERT OR REPLACE INTO shared_es_fc27_projection VALUES(?,?,?,?,?)',
                       ((revision,*key,body) for key,body in values.items()))
        available_at = max(stamp(captured_at),*(stamp(projection['observed_at'])
                                               for _,_,_,projection in submitted.values()))
        value = dict(publication_id=next_pin,data_version=version,published_at=available_at.isoformat(),cutoff=cutoff)
        bind_publication(db,value,publication_id,{})
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(FC27_PROJECTION_PIN+next_pin,revision))
    return dict(status='available',publication_id=next_pin,supplement_revision=revision,rows=len(values))


def coupon_tracking(rows, logs, clean, gaps=()):
    out = {}
    for row in rows:
        key = (str(row['site_id']), row['order_no'])
        coupons = None if key in gaps else [dict(id=str(log['id']), templateId=str(log.get('coupon_id') or 'unknown'),
                        title=clean(log.get('title')) or '未命名优惠券',
                        batch=clean((log.get('memberCoupon') or {}).get('grant_batch_no')) or '批次未提供',
                        usedAt=clean(log.get('use_time')), status=clean(log.get('status')))
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
        if (site,gid)==(FC27_SITE,FC27_GID) and 'fc27_coins' in raw:
            body['fc27_coins'] = _checked_fc27_projection(raw['fc27_coins'])
        if type(raw.get('device')) is int and raw['device'] in (0,1):
            body['device'] = raw['device']
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
    return _stage(store, day, manifest_key, native, lines, meta)


def _stage(store, day, manifest_key, native, lines, meta):
    evidence = dict(day=day, native=native, lines=lines, hashes=meta['hashes'])
    if 'archive_site' in meta:
        evidence['archive_site'] = meta['archive_site']
    revision = digest(evidence)
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


def retain_pending(db, value, start, cutoff, review_start):
    """Keep the original date and archive pins in the customer publication transaction."""
    pin = {key: value[key] for key in ('publication_id', 'data_version', 'cutoff', 'published_at', 'flag_manifests')}
    pending = dict(pin=pin, start=start, cutoff=cutoff, review_start=review_start)
    db.execute('INSERT INTO meta VALUES(?,?)', (PENDING + pin['publication_id'], canonical(pending)))


def pending_publications(store):
    with store.db() as db:
        rows = db.execute('SELECT value FROM meta WHERE key GLOB ?', (PENDING + '*',))
        return sorted((json.loads(row[0]) for row in rows), key=lambda item: item['pin']['published_at'], reverse=True)


def record_pending_error(store, pending, evidence):
    with store.db() as db:
        db.execute('UPDATE meta SET value=? WHERE key=?',
                   (canonical(dict(pending, **evidence)), PENDING + pending['pin']['publication_id']))


def complete_pending(store, pending, checkpoint):
    """Fill absent days or refresh older slices using the pinned archive, keeping newer readbacks intact."""
    pin = pending['pin']
    start, stop, review = pending['start'], pending['cutoff'], pending['review_start']
    with store.db() as db:
        covered = {}
        if _exists(db):
            stored = db.execute('''SELECT d.day,d.source_at,s.body
                FROM meta m JOIN shared_es_publication_days d ON d.publication_id=m.value
                JOIN shared_es_slices s ON s.day=d.day AND s.revision=d.revision
                WHERE m.key=? AND d.day>=? AND d.day<?''', (META, start, stop))
            covered = {day:source_at for day,source_at,body in stored if 'archive_site' not in json.loads(body)}
    days = [day for day in _days(start, (date.fromisoformat(stop) - DAY).isoformat())
            if day not in covered or review and day >= review and stamp(covered[day]) < stamp(pin['published_at'])]
    # The archive reader verifies the digest of its inputs. Keep the original
    # publication ID on the work record and bind it after sourcing the exact pins.
    archive_value = {key: pin[key] for key in ('data_version', 'cutoff', 'published_at', 'flag_manifests')}
    archive_value['contract'] = 'fs-users-weekly-publication-v1'
    archive_value['publication_id'] = 'uw_' + digest(archive_value)[:32]
    revisions = {}
    while days:
        if checkpoint():
            return None
        count = 1
        while count < min(len(days), 31) and date.fromisoformat(days[count]) == date.fromisoformat(days[count-1]) + DAY:
            count += 1
        batch = prepare_publication(store, archive_value, days[0], days[count-1], checkpoint=checkpoint)
        if batch is None:
            return None
        revisions.update(batch)
        days = days[count:]
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if revisions:
            active = db.execute('''SELECT p.publication_id,p.data_revision,p.captured_at,p.cutoff
                FROM meta m JOIN shared_es_publications p ON p.publication_id=m.value WHERE m.key=?''', (META,)).fetchone()
            value = pin
            if active and (stamp(active[2]) > stamp(pin['published_at']) or stamp(active[3]) > stamp(pin['cutoff'])):
                value = dict(data_version=active[1], published_at=max(stamp(active[2]), stamp(pin['published_at'])).isoformat(),
                             cutoff=max(stamp(active[3]), stamp(pin['cutoff'])).isoformat())
                value['publication_id'] = 'se_' + digest(dict(value, source=pin['publication_id'],
                                                             base=active[0], revisions=revisions))[:32]
            bind_publication(db, value, None, revisions, source_at=pin['published_at'])
        db.execute('DELETE FROM meta WHERE key=?', (PENDING + pin['publication_id'],))
    return sorted(revisions)


def bind_publication(db, value, previous, revisions, *, source_at=None, discount_revision=None):
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
                      SELECT ?,day,revision,source_at FROM shared_es_publication_days
                      WHERE publication_id=? AND day<?''', (ident, prior, shared_cutoff))
    discount_revision = discount_revision or (_discount_revision(db,prior) if prior else None)
    if discount_revision:
        db.execute('INSERT INTO shared_es_discount_pins VALUES(?,?)',(ident,discount_revision))
    if prior and (projection_revision := _fc27_projection_pin(db,prior)):
        db.execute('INSERT INTO meta VALUES(?,?)',(FC27_PROJECTION_PIN+ident,projection_revision))
    for day, revision in revisions.items():
        if (day >= cutoff or not db.execute(
                'SELECT 1 FROM shared_es_slices WHERE day=? AND revision=?', (day, revision)).fetchone()):
            raise ValueError('shared_es_publication_stage_mismatch')
        db.execute('INSERT OR REPLACE INTO shared_es_publication_days VALUES(?,?,?,?)',
                   (ident, day, revision, source_at or value['published_at']))
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (META, ident))


def refresh_discount_catalog(store, *, reader=None, now=None):
    """Publish one central inventory revision without reacquiring order or coupon membership."""
    if reader is None:
        from user_source import shared_discount_catalog as reader
    base = latest_publication(db=store.path)
    if base is None:
        raise ValueError('shared_es_discount_publication_unavailable')
    catalog = _discount_catalog(reader())
    captured_at = stamp(now).isoformat() if now is not None else datetime.now(stamp(base['captured_at']).tzinfo).isoformat()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT value FROM meta WHERE key=?',(META,)).fetchone()
        if current is None or current[0] != base['publication_id']:
            raise ValueError('shared_es_discount_publication_changed')
        revision = _store_discounts(db,catalog,captured_at)
        if revision == _discount_revision(db,current[0]):
            publication_id = current[0]
        else:
            publication_id = 'se_' + digest(dict(base=current[0],discount_revision=revision))[:32]
            value = dict(publication_id=publication_id,data_version=base['data_revision'],
                         published_at=max(stamp(captured_at),stamp(base['captured_at'])).isoformat(),cutoff=base['cutoff'])
            bind_publication(db,value,current[0],{},discount_revision=revision)
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('shared_es_discount_checked_day',stamp(captured_at).date().isoformat()))
    return dict(status='available',publication_id=publication_id,discount_revision=revision,
                code_count=len(catalog),captured_at=captured_at)


def refresh_discounts_due(store, now, *, reader=None):
    day = stamp(now).date().isoformat()
    with store.db() as db:
        last = db.execute('SELECT value FROM meta WHERE key=?',('shared_es_discount_checked_day',)).fetchone()
    if last and last[0] >= day:
        return dict(status='reused')
    if latest_publication(db=store.path) is None:
        return dict(status='deferred',reason='shared_publication_unavailable')
    try:
        return refresh_discount_catalog(store,reader=reader,now=now)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error) as error:
        # Inventory can be temporarily denied while all closed-day order facts remain available.
        return dict(status='partial',reason=type(error).__name__)


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


def _historical_channel_day(path, day):
    raw = path.read_bytes()
    value = json.loads(raw)
    orders = value['orders']
    sources = value['sources']
    admin, coupons = sources['orders'], sources['coupons']
    if (value.get('contract') != 'channel-day-v1' or value['period'] != dict(start=day,end=day)
            or (admin['status'], admin['site'], admin['dateBasis'], admin['currency'], admin['rows'])
            != ('complete', 'MMOEXP', 'paytime', 'USD', len(orders))
            or coupons['status'] != 'complete'
            or coupons['rows'] != sum(len(row['coupons']) for row in orders)):
        raise ValueError('shared_es_history_source')
    stamp(value['generatedAt'])
    observed_at = (sources.get('orderSource') or {}).get('generatedAt')
    native_rows, tracking = [], {}
    for row in orders:
        order_no = row['orderNo']
        paid = row['paidAt']
        usd = money(row['salesUsd'])
        if row['day'] != day or stamp(paid).date().isoformat() != day or usd is None:
            raise ValueError('shared_es_history_order')
        native_rows.append(dict(order_no=order_no, site_id=HISTORICAL_CHANNEL_SITE, gid=row['gid'],
            game_format=row['game'], paytime=paid, pay_status=row['payStatus'], status_format=row['status'],
            amount_usd_format=usd, amount_rmb_format=money(row['adminSaleCny']), discount_code=row['code'],
            recommend_uid=row['promoterUid'], country_code=row['country'], paytype_display=row['payment'],
            site={'full_title':'www.mmoexp.com'}))
        tracked = {key:row[key] for key in ('code','project','promoterUid','promoter','country','payment',
                   'coupons','conflict','sourceRaw','sourceStatus','customerType') if key in row}
        if observed_at and tracked.get('sourceStatus') == 'available':
            tracked['sourceCapturedAt'] = observed_at
        tracking[(HISTORICAL_CHANNEL_SITE, order_no)] = tracked
    native = _native(native_rows, day, tracking)
    sha = hashlib.sha256(raw).hexdigest()
    return sha, native, value['generatedAt'], coupons['rows']


def import_channel_history(store, expected_publication_id, *, root=HISTORICAL_CHANNEL_ROOT, apply=False,
                           expected_source=None, now=None):
    """Import only missing closed days from the verified existing MMOEXP daily archive."""
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('shared_es_history_archive_link')
    if not root.is_dir():
        raise ValueError('shared_es_history_archive_missing')
    active = latest_publication(db=store.path)
    if not active or active['publication_id'] != expected_publication_id:
        raise ValueError('shared_es_history_publication_changed')
    with closing(_read_db(store.path)) as db:
        covered = dict(db.execute('SELECT day,revision FROM shared_es_publication_days WHERE publication_id=?',
                                  (expected_publication_id,)))
    selected, counts, already = {}, dict(orders=0, coupons=0), []
    for path in sorted(root.glob('????-??-??.json')):
        day = date.fromisoformat(path.stem).isoformat()
        if day >= active['cutoff']:
            continue
        if day in covered:
            already.append(day)
            continue
        if path.is_symlink():
            raise ValueError('shared_es_history_archive_link')
        sha, native, _, coupon_count = _historical_channel_day(path, day)
        counts['orders'] += len(native)
        counts['coupons'] += coupon_count
        selected[day] = sha
    source_revision = digest(selected)
    if apply and source_revision != expected_source:
        raise ValueError('shared_es_history_source_changed')
    result = dict(status='preview', base_publication_id=expected_publication_id, selected_days=sorted(selected),
                  already_indexed=already, source_revision=source_revision, **counts)
    if not apply or not selected:
        return result
    captured_at = stamp(now).isoformat() if now is not None else datetime.now(stamp(active['captured_at']).tzinfo).isoformat()
    if stamp(captured_at) < stamp(active['captured_at']):
        raise ValueError('shared_es_history_publication_time')
    revisions = {}
    for day, expected in selected.items():
        path = root / (day + '.json')
        if path.is_symlink():
            raise ValueError('shared_es_history_archive_link')
        sha, native, source_at, _ = _historical_channel_day(path, day)
        if sha != expected:
            raise ValueError('shared_es_history_source_changed')
        meta = dict(contract=CONTRACT, hashes=[sha], status='partial', revision_conflicts=[],
                    captured_at=source_at, native_rows=len(native), es_lines=0,
                    archive_site=HISTORICAL_CHANNEL_SITE)
        revisions[day] = _stage(store, day, sha, native, [], meta)
    value = dict(data_version=active['data_revision'], published_at=captured_at, cutoff=active['cutoff'])
    value['publication_id'] = 'se_' + digest(dict(base=expected_publication_id, revisions=revisions))[:32]
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT value FROM meta WHERE key=?', (META,)).fetchone()
        if current is None or current[0] != expected_publication_id:
            raise ValueError('shared_es_history_publication_changed')
        bind_publication(db, value, expected_publication_id, revisions)
    return dict(result, status='available', publication_id=value['publication_id'])


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
        slices = [(day, revision, json.loads(body)) for day, revision, body in slices if day < cutoff]
        visible = [(day, revision, info) for day, revision, info in slices if info.get('archive_site') in (None, site)]
        day_revisions = {day: revision for day, revision, _ in visible}
        missing = [day for day in days if day not in day_revisions]
        if not day_revisions:
            return _unavailable(missing, publication_id)
        rows, lines, identities = _scoped_rows(connection, day_revisions, site, gid, publication_id)
        if (site,gid)==(FC27_SITE,FC27_GID):
            _supplement_fc27(connection,rows,day_revisions,publication_id)
        else:
            for raw in rows:
                raw.pop('fc27_coins',None)
        discount_revision = _discount_revision(connection,publication_id)
        _scoped_discount_projects(connection,rows,discount_revision)
    metadata = [info for _, _, info in visible]
    for row in lines:
        row['marketing_attribution']['available_at'] = captured_at
    hashes = sorted({value for item in metadata for value in item['hashes']})
    line_orders = {row.get('订单号') for row in lines}
    conflicts = sorted({value for item in metadata for value in item['revision_conflicts'] if value in line_orders})
    complete = not missing
    historical = [day for day, _, info in visible if 'archive_site' in info]
    full_attribution = complete and not historical and not conflicts
    revision = digest(day_revisions)
    coverage = dict(complete=complete, missing_days=missing, day_revisions=day_revisions, source_revision=revision,
                    publication_id=publication_id, data_revision=version, captured_at=captured_at, cutoff=cutoff,
                    admin_complete=complete, admin_date_basis='paytime', admin_snapshot=True,
                    admin_source_rows=sum(item['native_rows'] for item in metadata),
                    order_facts_status='available' if full_attribution else 'partial',
                    historical_channel_days=historical,
                    discount_mapping_revision=discount_revision,
                    admin_payment_membership='pay_status_1_or_2', attribution_availability='published_pins')
    if (site,gid)==(FC27_SITE,FC27_GID):
        projected = sorted((_order_hash(raw['order_no']),raw['fc27_coins'])
                           for raw in rows if 'fc27_coins' in raw)
        coverage['fc27_projection_revision'] = digest(projected) if projected else None
    dataset = dict(_private_dataset=True, status='available' if full_attribution else 'partial',
                   origin='shared_es_facts', rows=lines, hashes=hashes, source_revision=publication_id,
                   publication_id=publication_id, data_revision=version, available_at=captured_at,
                   revision_selection='published_pins', revision_conflicts=conflicts,
                   effective_scope=dict(start=start, end=end))
    identity_catalog = dict(complete=complete and not historical, revision=revision, rows=identities,
                            verified_days=[day for day, _, info in visible if 'archive_site' not in info],
                            scope=dict(start=start, end=end, site='all', game='all', pay_status='1'))
    return dict(status=dataset['status'], rows=rows, dataset=dataset, identity_catalog=identity_catalog,
                coverage=coverage)


if __name__ == '__main__':
    import argparse
    import fcntl
    from user_runtime import load_store

    parser = argparse.ArgumentParser(description='Import existing closed MMOEXP channel days once.')
    parser.add_argument('--publication-id')
    parser.add_argument('--apply-source', help='Exact source_revision reported by preview.')
    parser.add_argument('--refresh-discounts', action='store_true')
    args = parser.parse_args()
    if args.refresh_discounts == bool(args.publication_id) or args.refresh_discounts and args.apply_source:
        parser.error('select either --publication-id or --refresh-discounts')
    store = load_store()
    if args.apply_source or args.refresh_discounts:
        with (store.root / 'jobs.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.refresh_discounts:
                result = refresh_discount_catalog(store)
            else:
                result = import_channel_history(store, args.publication_id, apply=True, expected_source=args.apply_source)
    else:
        result = import_channel_history(store, args.publication_id)
    print(canonical(result), flush=True)

