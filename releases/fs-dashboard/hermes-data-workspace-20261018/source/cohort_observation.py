"""Private paid-order observation groups; isNew is not proof of first purchase."""
from datetime import date, datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

CONTRACT = 'fc-es-customer-observation-v2'


def update(path, group, start, end, rows, *, complete_through, source_complete, source_version):
    """Call with normalized FC paid rows and a complete acquisition-to-cutoff scan.

    Group identity must include the fixed game/site/filter scope. Store only
    pseudonyms; caller owns file permissions and source authorization.
    """
    lo, hi, cutoff = map(date.fromisoformat, (start, end, complete_through))
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('observation_linked_path')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    os.close(fd)
    if os.name=='posix' and path.stat().st_mode&0o077:raise ValueError('observation_private_permissions')
    if lo > hi or cutoff < hi or not group or not source_version:
        raise ValueError('observation_period_or_source')
    prepared = []
    missing_identity = missing_time = 0
    for row in rows:
        key, paid, ident = row.get('customer_key'), row.get('paid_at'), row.get('id')
        if not key:
            missing_identity += 1
        if not paid:
            missing_time += 1
        if not key or not paid:
            continue
        if not ident:
            raise ValueError('observation_order_identity')
        when = datetime.fromisoformat(paid)
        if when.tzinfo is None:
            raise ValueError('observation_timezone')
        when=when.astimezone(timezone(timedelta(hours=8)))
        day = when.date()
        if not lo <= day <= cutoff:
            continue
        # Customer pseudonym already includes site:uid, preventing cross-site order collisions.
        prepared.append((hashlib.sha256((key+':'+str(ident)).encode()).hexdigest(), key, when.isoformat(), row.get('customer') == 'new'))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS groups (name TEXT PRIMARY KEY, start TEXT, end TEXT, cutoff TEXT, version TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS members (group_name TEXT, customer TEXT, anchor TEXT, PRIMARY KEY(group_name,customer))')
        db.execute('CREATE TABLE IF NOT EXISTS payments (group_name TEXT, order_key TEXT, customer TEXT, paid TEXT, PRIMARY KEY(group_name,order_key))')
        db.execute('CREATE TABLE IF NOT EXISTS snapshots (group_name TEXT PRIMARY KEY, payload TEXT)')
        existing = db.execute('SELECT start,end,cutoff FROM groups WHERE name=?', (group,)).fetchone()
        if existing and existing[:2] != (start, end):
            raise ValueError('observation_group_frozen_period')
        if existing and cutoff.isoformat() < existing[2]:
            raise ValueError('observation_cutoff_regression')
        if not source_complete:
            return {'kind': 'cohort_observation', 'contract': CONTRACT, 'status': 'unavailable', 'reason': 'source_incomplete_preserved_previous', 'persisted': False}
        if not existing and (missing_identity or missing_time):
            return {'kind':'cohort_observation','contract':CONTRACT,'status':'partial','reason':'initial_customer_linkage_incomplete_not_frozen','period':{'start':start,'end':end},'members':None,'windows':[],
                    'coverage':{'complete_through':complete_through,'source_version':source_version,'source_complete':True,'orders_without_customer_key':missing_identity,'orders_without_paid_at':missing_time},
                    'campaign_eligibility':'unknown','raw_identifiers_exposed':False,'persisted':False}
        if not existing:
            anchors = {}
            for _, key, paid, new in prepared:
                if new and lo <= datetime.fromisoformat(paid).date() <= hi:
                    anchors[key] = min(anchors.get(key, paid), paid)
            db.executemany('INSERT INTO members VALUES (?,?,?)', [(group, key, paid) for key, paid in anchors.items()])
        for order, key, paid, _ in prepared:
            previous = db.execute('SELECT customer,paid FROM payments WHERE group_name=? AND order_key=?', (group, order)).fetchone()
            if previous and previous != (key, paid):
                raise ValueError('observation_order_conflict')
            db.execute('INSERT OR IGNORE INTO payments VALUES (?,?,?,?)', (group, order, key, paid))
        db.execute('INSERT OR REPLACE INTO groups VALUES (?,?,?,?,?)', (group,start,end,complete_through,source_version))
        members = db.execute('SELECT customer,anchor FROM members WHERE group_name=?', (group,)).fetchall()
        payments = db.execute('SELECT customer,paid FROM payments WHERE group_name=?', (group,)).fetchall()
        windows = []
        for days in (7,14,30):
            mature = repeat = 0
            for key, anchor_text in members:
                anchor = datetime.fromisoformat(anchor_text)
                boundary = anchor + timedelta(days=days)
                # Source cutoff is a completed local day, so next midnight is exclusive.
                if boundary.date() > cutoff:
                    continue
                mature += 1
                repeat += any(customer == key and anchor < datetime.fromisoformat(paid) <= boundary for customer, paid in payments)
            windows.append({'days':days,'mature_customers':mature,'immature_customers':len(members)-mature,'repeat_customers':repeat,'repeat_rate':repeat/mature if mature else None})
        result = {'kind':'cohort_observation','contract':CONTRACT,'status':'partial' if missing_identity or missing_time else 'available','period':{'start':start,'end':end},
                'definition':'Stable linked ES-new-flag paid customer observation group; not verified first-purchase cohort',
                'members':len(members),'windows':windows,'coverage':{'complete_through':complete_through,'source_version':source_version,'source_complete':True,'orders_without_customer_key':missing_identity,'orders_without_paid_at':missing_time},
                'campaign_eligibility':'unknown','identity_scope':'site-local anonymous customer key; not cross-site identity',
                'limitations':['No verified historical first qualified purchase','Repeat paid orders do not prove promotion incrementality or net settled retention','Membership frozen at first complete acquisition scan; late changes require a separately versioned group'],
                'raw_identifiers_exposed':False}
        db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?)', (group,json.dumps(result)))
        return result


def read(path, group):
    """Read last complete aggregate only; callers must enforce group scope access."""
    from pathlib import Path
    if not Path(path).exists():
        return {'kind':'cohort_observation','contract':CONTRACT,'status':'unavailable','reason':'observation_not_started'}
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT payload FROM snapshots WHERE group_name=?',(group,)).fetchone()
    return json.loads(row[0]) if row else {'kind':'cohort_observation','contract':CONTRACT,'status':'unavailable','reason':'observation_not_started'}
