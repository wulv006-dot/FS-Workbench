"""Small revisioned facts in the existing Archive catalog; no new host/timer/raw DB."""
from contextlib import closing
from datetime import timedelta
from decimal import Decimal,InvalidOperation
import hashlib,json
from date_policy import day


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def schema(db):
    # Called explicitly by the fixture/candidate adapter, never service startup.
    db.execute('CREATE TABLE IF NOT EXISTS daily_facts(dataset TEXT,scope_hash TEXT,business_date TEXT,contract TEXT,currency TEXT,revision TEXT,sequence INTEGER,body TEXT,PRIMARY KEY(dataset,scope_hash,business_date,contract,currency,revision))')
    db.execute('CREATE TABLE IF NOT EXISTS daily_current(dataset TEXT,scope_hash TEXT,business_date TEXT,contract TEXT,currency TEXT,revision TEXT,sequence INTEGER,PRIMARY KEY(dataset,scope_hash,business_date,contract,currency))')
    db.execute('CREATE TABLE IF NOT EXISTS dirty_days(dataset TEXT,scope_hash TEXT,business_date TEXT,currency TEXT,reason TEXT,PRIMARY KEY(dataset,scope_hash,business_date,currency))')
    db.execute('CREATE TABLE IF NOT EXISTS daily_dirty_events(dataset TEXT,scope_hash TEXT,event_id TEXT,checksum TEXT,PRIMARY KEY(dataset,scope_hash,event_id))')


class Facts:
    def __init__(self,archive,registry):
        self.archive,self.registry=archive,registry

    def initialize(self):
        with closing(self.archive.database(True)) as db,db:schema(db)

    def publish(self,dataset,scope_hash,business_date,currency,sequence,metrics,*,source_complete,source_watermark,status='published'):
        spec=self.registry[dataset]
        day(business_date)
        if not scope_hash or type(sequence) is not int or sequence<0 or currency not in spec['currencies'] or status not in ('published','sealed'):
            raise ValueError('daily_fact_identity')
        if source_complete is not True:raise ValueError('daily_source_incomplete')
        if not isinstance(source_watermark,str) or not source_watermark:raise ValueError('daily_watermark_required')
        if not isinstance(metrics,dict) or set(metrics)!=set(spec['additive_metrics']):raise ValueError('daily_metric_contract')
        values={}
        for key,value in metrics.items():
            if type(value) not in (str,int):raise ValueError('daily_metric_value')
            try:number=Decimal(value)
            except InvalidOperation:raise ValueError('daily_metric_value') from None
            if not number.is_finite():raise ValueError('daily_metric_value')
            values[key]=str(number)
        body=encoded(dict(metrics=values,timezone=spec['timezone'],date_semantics=spec['date_semantics'],source_watermark=source_watermark,status=status))
        if len(body.encode())>16384:raise ValueError('daily_fact_size')
        revision=hashlib.sha256(body.encode()).hexdigest()
        key=(dataset,scope_hash,business_date,spec['metric_contract'],currency)
        with closing(self.archive.database(True)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT revision,sequence FROM daily_current WHERE dataset=? AND scope_hash=? AND business_date=? AND contract=? AND currency=?',key).fetchone()
            if old and (sequence<old['sequence'] or sequence==old['sequence'] and revision!=old['revision']):raise ValueError('daily_source_revision_conflict')
            dirty=db.execute('SELECT 1 FROM dirty_days WHERE dataset=? AND scope_hash=? AND business_date=? AND currency=?',key[:3]+(currency,)).fetchone()
            if dirty and old and sequence<=old['sequence']:raise ValueError('daily_dirty_requires_new_revision')
            db.execute('INSERT OR IGNORE INTO daily_facts VALUES(?,?,?,?,?,?,?,?)',key+(revision,sequence,body))
            db.execute('INSERT OR REPLACE INTO daily_current VALUES(?,?,?,?,?,?,?)',key+(revision,sequence))
            db.execute('DELETE FROM dirty_days WHERE dataset=? AND scope_hash=? AND business_date=? AND currency=?',key[:3]+(currency,))
        return revision

    def mark_dirty(self,dataset,scope_hash,event_id,old_date,new_date,reason,*,currency):
        if dataset not in self.registry or currency not in self.registry[dataset]['currencies'] or not event_id or not reason:raise ValueError('daily_dirty_event')
        dates=sorted(set(x for x in (old_date,new_date) if x is not None))
        for value in dates:day(value)
        checksum=hashlib.sha256(encoded([dates,reason,currency]).encode()).hexdigest()
        with closing(self.archive.database(True)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT checksum FROM daily_dirty_events WHERE dataset=? AND scope_hash=? AND event_id=?',(dataset,scope_hash,event_id)).fetchone()
            if old:
                if old['checksum']!=checksum:raise ValueError('daily_event_conflict')
                return False
            db.execute('INSERT INTO daily_dirty_events VALUES(?,?,?,?)',(dataset,scope_hash,event_id,checksum))
            for value in dates:db.execute('INSERT OR REPLACE INTO dirty_days VALUES(?,?,?,?,?)',(dataset,scope_hash,value,currency,reason))
        return True

    def read(self,dataset,scope_hash,start,end_exclusive,currency):
        spec=self.registry[dataset];lo,hi=day(start),day(end_exclusive)
        if lo>=hi or currency not in spec['currencies']:raise ValueError('daily_fact_range')
        db=self.archive.database()
        if db is None:return dict(complete=False,currency=currency,rows=[],missing=[start],reason='read_model_missing')
        with closing(db):
            rows=[dict(row) for row in db.execute('SELECT c.business_date,f.body FROM daily_current c JOIN daily_facts f ON c.dataset=f.dataset AND c.scope_hash=f.scope_hash AND c.business_date=f.business_date AND c.contract=f.contract AND c.currency=f.currency AND c.revision=f.revision WHERE c.dataset=? AND c.scope_hash=? AND c.contract=? AND c.currency=? AND c.business_date>=? AND c.business_date<? ORDER BY c.business_date',(dataset,scope_hash,spec['metric_contract'],currency,start,end_exclusive))]
            dirty={row[0] for row in db.execute('SELECT business_date FROM dirty_days WHERE dataset=? AND scope_hash=? AND currency=? AND business_date>=? AND business_date<?',(dataset,scope_hash,currency,start,end_exclusive))}
        existing={row['business_date'] for row in rows};missing=[];cursor=lo
        while cursor<hi:
            if cursor.isoformat() not in existing:missing.append(cursor.isoformat())
            cursor+=timedelta(days=1)
        return dict(complete=not missing and not dirty,currency=currency,rows=[dict(business_date=row['business_date'],**json.loads(row['body'])) for row in rows],missing=missing,dirty=sorted(dirty))


def totals(result):
    if result['complete'] is not True:raise ValueError('daily_coverage_incomplete')
    sums={}
    for row in result['rows']:
        for key,value in row['metrics'].items():sums[key]=sums.get(key,Decimal(0))+Decimal(value)
    return {key:str(value) for key,value in sums.items()}


def ratio(numerator,denominator):
    return None if Decimal(denominator)==0 else str(Decimal(numerator)/Decimal(denominator))
