"""Private, dated source replies; callers retain their existing authorization."""
from calendar import monthrange
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from copy import deepcopy
from decimal import Decimal

ROOT = Path('/var/lib/fs-data-archive')
TZ = timezone(timedelta(hours=8))
FAMILIES = {'summary', 'native', 'marketing', 'paid-detail', 'native-statistics'}
LIMIT = 64 * 1024 * 1024


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def cutoff(today=None, months=3):
    today = today or datetime.now(TZ).date()
    year, month = divmod(today.year * 12 + today.month - months - 1, 12)
    month += 1
    return date(year, month, min(today.day, monthrange(year, month)[1]))


def retention_cutoff(today=None):
    return cutoff(today, months=12)


def closed(query, today=None):
    today = today or datetime.now(TZ).date()
    try:
        lo, hi = (date.fromisoformat(query[k]) for k in ('start', 'end'))
        return lo <= hi < today and (hi-lo).days <= 365 and query.get('grain', 'day') == 'day'
    except (ValueError, KeyError, TypeError):
        return False


def full_period(query, period):
    # Only whole-day queries can be published to the daily archive.
    if query.get('grain', 'day') != 'day': return False
    return period == {'start': query['start'] + ' 00:00',
                      'end': (date.fromisoformat(query['end']) + timedelta(days=1)).isoformat() + ' 00:00'}


class Archive:
    def __init__(self, root=None, today=None):
        self.root, self.today = Path(ROOT if root is None else root), today or (lambda: datetime.now(TZ).date())

    def safe(self, create=False):
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise ValueError('archive_symlink')
        if create: self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.root.exists() and os.name == 'posix':
            info = self.root.stat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('archive_permissions')

    def identity(self, family, query):
        if family not in FAMILIES or not isinstance(query, dict): raise ValueError('archive_family')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', query.get('profile', '')): raise ValueError('archive_profile')
        raw = encoded({'family': family, 'query': query, 'contract': 1})
        if len(raw) > 65536: raise ValueError('archive_query_size')
        return hashlib.sha256(raw).hexdigest()

    def retention_basis(self):
        self.safe()
        return 'business_date'

    def database(self, create=False):
        self.safe(create)
        path = self.root / 'catalog.sqlite3'
        if path.is_symlink(): raise ValueError('archive_catalog_symlink')
        if not create and not path.exists(): return None
        db = sqlite3.connect(str(path) if create else path.resolve().as_uri() + '?mode=ro', uri=not create, timeout=3)
        db.row_factory = sqlite3.Row
        if create:
            os.chmod(path, 0o600)
            db.executescript('''CREATE TABLE IF NOT EXISTS versions(
                version TEXT PRIMARY KEY, key TEXT NOT NULL, family TEXT NOT NULL, profile TEXT NOT NULL,
                start TEXT NOT NULL, end TEXT NOT NULL, saved TEXT NOT NULL, path TEXT NOT NULL UNIQUE, bytes INTEGER NOT NULL, source_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS dated ON versions(family,profile,start,end);
                CREATE TABLE IF NOT EXISTS latest(key TEXT PRIMARY KEY, version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS references_index(family TEXT,profile TEXT,start TEXT,end TEXT,path TEXT PRIMARY KEY,
                    sha256 TEXT,bytes INTEGER,complete INTEGER);''')
        return db

    def put(self, family, query, value, source_at=None):
        key = self.identity(family, query)
        if not closed(query, self.today()): return None
        if self.retention_basis()=='business_date' and date.fromisoformat(query['start'])<retention_cutoff(self.today()):return None
        saved = datetime.now(timezone.utc).isoformat()
        source_at = source_at or value.get('generatedAt') or value.get('captured_at') or saved
        source_at = datetime.fromisoformat(source_at.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
        value = {k:v for k,v in value.items() if k not in ('archive','archiveWriteStatus')}
        raw = encoded({'family': family, 'query': query, 'sourceAt': source_at, 'value': value})
        if len(raw) > LIMIT: raise ValueError('archive_body_size')
        version = hashlib.sha256(raw).hexdigest()
        relative = Path(family) / query['profile'] / (query['start'] + '_' + query['end']) / (version + '.json.gz')
        self.safe(True)
        path = self.root / relative
        if any(p.is_symlink() for p in (path, *path.parents)): raise ValueError('archive_object_symlink')
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        packed = gzip.compress(raw, compresslevel=6, mtime=0)
        fd, temp = tempfile.mkstemp(prefix='.archive-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(packed); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        with closing(self.database(True)) as db, db:
            db.execute('INSERT OR IGNORE INTO versions VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (version, key, family, query['profile'], query['start'], query['end'], saved, str(relative), len(packed), source_at))
            previous = db.execute('SELECT source_at FROM versions WHERE version=(SELECT version FROM latest WHERE key=?)', (key,)).fetchone()
            if previous is None or previous['source_at'] <= source_at:
                db.execute('INSERT OR REPLACE INTO latest VALUES(?,?)', (key, version))
        return version

    def get(self, family, query):
        key = self.identity(family, query)
        if not closed(query, self.today()): return None
        basis=self.retention_basis()
        if basis=='business_date' and date.fromisoformat(query['start'])<retention_cutoff(self.today()):return None
        db = self.database()
        if db is None: return None
        with closing(db):
            row = db.execute('SELECT v.* FROM latest l JOIN versions v ON l.version=v.version WHERE l.key=?', (key,)).fetchone()
        if row is None: return None
        path = self.root / row['path']
        if not path.resolve().is_relative_to(self.root.resolve()) or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('archive_object_boundary')
        try:
            if path.stat().st_size > LIMIT: return None
            with gzip.open(path, 'rb') as stream: raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT or hashlib.sha256(raw).hexdigest() != row['version']: return None
            result = json.loads(raw)
        except (OSError, ValueError, EOFError): return None
        if result['query'] != query or result['family'] != family: raise ValueError('archive_identity')
        value = result['value']
        value['archive'] = {'version': row['version'], 'savedAt': row['saved'], 'start': row['start'], 'end': row['end'],
                            'sourceCapturedAt': row['source_at'], 'read': 'exact_complete_archive', 'sourceTimesUnchanged': True, 'retentionMonths': 12}
        return value

    def catalog(self):
        db = self.database()
        if db is None: return []
        with closing(db):
            return [dict(r) for r in db.execute('''SELECT family,profile,complete,min(start) firstDay,max(end) lastDay,count(*) ranges,sum(bytes) bytes
                FROM (SELECT family,profile,start,end,bytes,1 complete FROM versions WHERE version IN(SELECT version FROM latest)
                UNION ALL SELECT family,profile,start,end,bytes,complete FROM references_index)
                GROUP BY family,profile,complete''')]

    def reference(self, family, profile, start, end, path, complete):
        roots = (Path('/var/lib/fs-channel-effects'),Path('/var/lib/fc27-es-exports'))
        path = Path(path)
        if not any(path.resolve().is_relative_to(root) for root in roots) or any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('archive_reference_boundary')
        date.fromisoformat(start); date.fromisoformat(end)
        with closing(self.database(True)) as db, db:
            db.execute('INSERT OR REPLACE INTO references_index VALUES(?,?,?,?,?,?,?,?)',
                (family,profile,start,end,str(path),hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_size,int(complete)))

    def prune(self, dry_run=True):
        basis=self.retention_basis()
        db = self.database()
        if db is None: return {'objects': 0, 'bytes': 0, 'dryRun': dry_run}
        threshold=retention_cutoff(self.today()).isoformat()
        with closing(db): rows = db.execute('SELECT * FROM versions WHERE start<?', (threshold,)).fetchall()
        total = sum(row['bytes'] for row in rows)
        if not dry_run:
            with closing(self.database(True)) as db, db:
                for row in rows:
                    path = self.root / row['path']
                    if not path.resolve().is_relative_to(self.root.resolve()) or any(p.is_symlink() for p in (path, *path.parents)):
                        raise ValueError('archive_cleanup_boundary')
                    if path.name != row['version'] + '.json.gz': raise ValueError('archive_cleanup_identity')
                    db.execute('DELETE FROM latest WHERE version=?', (row['version'],))
                    db.execute('DELETE FROM versions WHERE version=?', (row['version'],))
                    path.unlink(missing_ok=True)
        result={'objects': len(rows), 'bytes': total, 'dryRun': dry_run, 'cutoff': retention_cutoff(self.today()).isoformat(),'basis':basis}
        if not dry_run:
            receipts=self.root/'cleanup-receipts';receipts.mkdir(mode=0o700,exist_ok=True)
            path=receipts/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:
                out.write(encoded(dict(result,versions=[r['version'] for r in rows])));out.flush();os.fsync(out.fileno())
        return result


def summary_key(query):
    return {k: query[k] for k in ('profile', 'start', 'end', 'grain', 'contractId', 'rs_site', 'rs_server', 'rs_category', 'rs_profit_source', 'profit_site', 'profit_category', 'profit_source','profit_basis','admin_site','country_code','admin_only','authorization_scope','channel','customer_type','payment','device','platform','product','unsupported_filters') if k in query}


def native_key(query, definition=None):
    result = {k: query[k] for k in ('profile', 'start', 'end', 'grain', 'analysis') if k in query}
    result['contract'] = 'native-closed-v2'
    if definition is not None and len(definition)>4 and definition[4]=='rpg' and not query.get('analysis'):
        if 'period' in query and query.get('adminCohort')!='paid-all-status-v2':raise ValueError('native_paid_cohort_unverified')
        result['adminCohort']='paid-all-status-v2'
    if definition is not None: result['profileDefinition'] = hashlib.sha256(encoded(definition)).hexdigest()
    return result


def complete_summary(value):
    if value.get('query',{}).get('admin_only'):
        return (value.get('status')=='available' and value.get('stale') is False
                and value.get('profile',{}).get('supplement',{}).get('status')=='available'
                and value.get('sources',{}).get('Admin',{}).get('status')=='available'
                and full_period(value['query'],value['profile']['period']))
    if value.get('query',{}).get('profit_basis')=='actual':
        q=value['query'];required={'Admin'} if q['profile']=='RS' else {'Admin','Order'}
        sources=value.get('sources',{})
        return (value.get('status')=='available' and value.get('stale') is False
                and value.get('profile',{}).get('supplement',{}).get('status')=='available'
                and required <= set(sources)
                and all(sources[n].get('status')=='available' and sources[n].get('stale') is False for n in required)
                and all(s.get('status')=='not_requested' for n,s in sources.items() if n not in required)
                and full_period(q,value['profile']['period']))
    return (value.get('status') == 'available' and value.get('stale') is False
            and all(value.get('profile', {}).get(k, {}).get('status') == 'available' for k in ('primary', 'supplement'))
            and bool(value.get('sources')) and all(s.get('status') == 'available' and s.get('stale') is False for s in value['sources'].values())
            and full_period(value['query'], value['profile']['period']))


def complete_native(value):
    if value.get('status') != 'available' or not full_period(value['query'], value['query']['period']): return False
    if value['query'].get('analysis'):
        extension = value.get('fc27ProductRankings') or value.get('fc27Analytics') or {}
        return extension.get('status') in ('available', 'empty') and extension.get('coverage', {}).get('complete') is True
    if value.get('scopeContractId') != 'all-websites-order-primary-admin-supplement-v1': return False
    # Retain old completed-only evidence without seeding it under a current paid-cohort key.
    if str(value.get('profile',{}).get('supplement',{}).get('filters',{}).get('order_status',''))=='101':return False
    if value['query'].get('adminCohort')=='paid-all-status-v2':
        filters=value.get('profile',{}).get('supplement',{}).get('filters',{})
        if filters.get('order_status')!='' or str(filters.get('pay_status'))!='1':return False
    return all(value.get('profile', {}).get(k, {}).get('status') == 'available' for k in ('primary', 'supplement'))


def derive_summary(query):
    """Only same-contract additive facts; unique customers and native rates stay unknown."""
    if query.get('admin_only'):return None # No additive fallback with unmatched Order scope.
    if not closed(query): return None
    lo, hi = (date.fromisoformat(query[k]) for k in ('start','end'))
    values = []
    for i in range((hi-lo).days+1):
        day = (lo+timedelta(days=i)).isoformat()
        value = read('summary', dict(query, start=day, end=day))
        if value is None or not complete_summary(value): return None
        values.append(value)
    if len(values) < 2: return None
    result = deepcopy(values[-1])
    result['profile'].pop('shipping',None)
    if 'Shipping' in result.get('sources',{}):result['sources']['Shipping'].update(status='not_derived',stale=True)
    result['query'] = dict(query,period={'start':query['start']+' 00:00','end':(hi+timedelta(days=1)).isoformat()+' 00:00'})
    result['profile']['period'] = result['query']['period']
    sums = {'orders','revenueUsd','pureSalesUsd','deductedAmountUsd','refundAmountUsd','refundOrders','newCustomerRevenueUsd','receiptsCny','goodsPaymentCny'}
    total = lambda numbers: float(sum((Decimal(str(n)) for n in numbers),Decimal(0))) if all(isinstance(n,(float,int)) and not isinstance(n,bool) for n in numbers) else None
    scalar = lambda source,key: source.get(key,source.get('metrics',{}).get(key,{}).get('value'))
    for name in ('primary','supplement'):
        if name=='primary' and query.get('profit_basis')=='actual' and query['profile']=='RS':
            result['profile']['primary']['period']=result['query']['period'];continue
        sources = [v['profile'][name] for v in values]
        first = sources[0]
        if any(any(s.get(k)!=first.get(k) for k in ('system','currency','normalisedScope','endpoint')) for s in sources):return None
        source = result['profile'][name]
        source.update(period=result['query']['period'],capturedAt=min(s['capturedAt'] for s in sources),sourceDataAsOf=None)
        for key in ('orders','revenueUsd'):source[key]=total([scalar(s,key) for s in sources])
        source['newCustomers']=None
        # Do not carry a single day's new D1 native/local percentage into a period sum.
        for field in ('admin_repeat_rate_raw','native_repeat_rate','local_repeat_rate','requested_scope','effective_scope','coverage','actual_cutoff'):
            source.pop(field,None)
        source['reconciliation_status']='not_aligned'
        source['dimensions']={'period':source['period'],'source':'daily-archive-derived'}
        source['charts'],source['rows'],source['nativeSeries']=[],[],[]
        for key,metric in source.get('metrics',{}).items():
            numbers=[s.get('metrics',{}).get(key,{}).get('value') for s in sources]
            derived=total(numbers) if key in sums else None
            if key in ('minOrderAmountUsd','maxOrderAmountUsd'):
                numbers=[n for n,s in zip(numbers,sources) if scalar(s,'orders') and isinstance(n,(int,float))]
                if numbers:derived=(min if key.startswith('min') else max)(numbers)
            metric.update(value=derived,status='available' if derived is not None else 'not_derived',raw=None,
                          definition='同口径完整日归档合计/边界；不可加和人数与原生百分比待整段读取',derived=True)
        result['sources'][('Order' if name=='primary' else 'Admin')].update(capturedAt=source['capturedAt'],stale=True)
    result['profile']['metrics']=deepcopy(result['profile']['primary'].get('metrics',{}))
    for key in ('orders','revenueUsd'):
        result['profile']['metrics'][key]={'value':result['profile']['primary'][key],'source':'primary','derived':True}
    result.update(status='stale',stale=True,origin='daily-archive-derived',generatedAt=min(v['generatedAt'] for v in values))
    result['archive']={'read':'derived_daily_financials','start':query['start'],'end':query['end'],
                       'versions':[v['archive']['version'] for v in values], 'days':len(values),
                       'requiresNative':['unique_customers','native_percentages','whole_range_dimensions'],'sourceTimesUnchanged':True}
    return result


def rebind_native(value, query):
    value['archive']['sourceRangeId'] = value.get('rangeId')
    value['archive']['sourceBaseSnapshotId'] = value.get('baseSnapshotId')
    value['archive']['sourceResultSha256'] = value.pop('resultSha256', None)
    value['query'], value['baseSnapshotId'] = query, query['baseSnapshotId']
    value['rangeId'] = hashlib.sha256(encoded(query)).hexdigest()
    value['resultSha256'] = hashlib.sha256(encoded(value)).hexdigest()
    return value


def read(family, query):
    try: return Archive().get(family, query)
    except (OSError, sqlite3.Error): return None


def save(family, query, value, source_at=None):
    try: return Archive().put(family, query, value, source_at)
    except (OSError, sqlite3.Error):
        value['archiveWriteStatus'] = 'failed_source_result_retained'
        return None
