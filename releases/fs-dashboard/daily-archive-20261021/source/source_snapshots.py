"""Private, versioned source replies shared by scheduled preparation and FS reports."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import os
import stat
import tempfile
import threading
import time

ROOT=Path('/var/lib/fs-hermes-fc/fs/source-snapshots')
LOCK=threading.RLock()
SHANGHAI=timezone(timedelta(hours=8))


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')


def atomic(path,value):
    fd,name=tempfile.mkstemp(prefix='.snapshot-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class SnapshotStore:
    def __init__(self,root=ROOT,clock=None):
        self.root=Path(root);self.clock=clock or (lambda:datetime.now(timezone.utc))

    def directory(self):
        if any(p.is_symlink() for p in (self.root,*self.root.parents)):raise ValueError('snapshot_symlink')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        info=self.root.stat()
        if os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):raise ValueError('snapshot_permissions')

    def read(self,path):
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>64*1024*1024:raise ValueError('snapshot_file')
        if os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):raise ValueError('snapshot_file_permissions')
        return json.loads(path.read_text('utf8'))

    def get(self,family,query,reader,valid,*,enabled=True):
        if not enabled:raise PermissionError('source_disabled')
        from daily_archive import read,save
        managed=family=='native-statistics' and bool(query.get('profile'))
        if managed:
            value=read(family,query)
            if value is not None and valid(value):return value
        value=self.get_live(family,query,reader,valid,enabled=enabled)
        if managed and valid(value):save(family,query,value,source_at=(value.get('source_cache') or {}).get('saved_at'))
        return value

    def get_live(self,family,query,reader,valid,*,enabled=True):
        if not enabled:raise PermissionError('source_disabled')
        if family not in ('paid-detail','native-statistics','native-loss','official-index','published-source'):raise ValueError('snapshot_family')
        now=self.clock();day=now.astimezone(SHANGHAI).date()
        # Open business days stay on the existing live source contract.
        if family not in ('official-index','published-source') and query['end']>=day.isoformat():return reader()
        max_age=7200 if family=='native-loss' else 21600 if family=='official-index' else 86400
        key=hashlib.sha256(encoded({'family':family,'query':query,'contract':1})).hexdigest()
        with LOCK:
            self.directory();index=self.root/(key+'.json')
            if index.exists() or index.is_symlink():
                pointer=self.read(index);version=pointer.get('version','')
                if len(version)!=64 or any(c not in '0123456789abcdef' for c in version):raise ValueError('snapshot_version')
                saved=self.read(self.root/(version+'.data.json'))
                if hashlib.sha256(encoded(saved)).hexdigest()!=version or saved.get('key')!=key:raise ValueError('snapshot_integrity')
                at=datetime.fromisoformat(saved['saved_at']);age=(now-at).total_seconds()
                if 0<=age<max_age and at.astimezone(SHANGHAI).date()==day and valid(saved['value']):
                    return self.label(saved['value'],version,saved['saved_at'],True,max_age)
            value=reader()
            if not valid(value):return value
            saved={'contract':1,'key':key,'family':family,'query':query,'saved_at':self.clock().isoformat(),'value':value}
            version=hashlib.sha256(encoded(saved)).hexdigest();path=self.root/(version+'.data.json')
            if not path.exists():atomic(path,saved)
            atomic(index,{'version':version})
            return self.label(value,version,saved['saved_at'],False,max_age)

    @staticmethod
    def label(value,version,saved_at,reused,max_age=86400):
        value=json.loads(encoded(value))
        value['source_cache']={'version':version,'saved_at':saved_at,'reused':reused,
            'max_age_seconds':max_age,'policy':'source times unchanged; refresh at age limit or next Shanghai day; current published versions checked before reuse'}
        return value


def archived_publication(family,args,value,store=None):
    """Always inspect the local publisher first; archive never hides a new version or stale flag."""
    identity=value.get('source_sha256') or value.get('source_snapshot_id') or value.get('shared_snapshot_id')
    if not identity or value.get('http_status')!=200:return value
    store=store or SnapshotStore()
    saved=store.get('published-source',dict(args,source_family=family,source_version=identity),lambda:value,lambda v:True)
    return dict(value,source_cache=saved['source_cache'])


def official_snapshot(reader,args,config,store=None):
    """The collector reads one current index; report windows only label article publication dates."""
    store=store or SnapshotStore();day=store.clock().astimezone(SHANGHAI).date().isoformat()
    query={'profile':'FC27','start':day,'end':day}
    value=store.get('official-index',dict(query,config=config),lambda:reader(query),
        lambda v:v.get('http_status')==200 and v.get('coverage',{}).get('index_read') is True and not v.get('failures'),
        enabled=config.get('enabled') is True)
    value=json.loads(encoded(value));value['query']=dict(args)
    for document in value.get('documents',[]):
        published=document.get('published_at')
        document['publication_in_window']=args['start']<=published[:10]<=args['end'] if published else None
    value['source_snapshot_id']='official_'+hashlib.sha256(encoded(value)).hexdigest()
    return value


def prepare_supplements(book,start,end,weekly=False):
    """Preload only repeatedly used sources; large bodies remain tool-readable, not prompt-inlined."""
    queries=report_queries(start,end,weekly)[:2]
    plan=[('fc.query_capability',dict(q,kind='native_loss')) for q in queries]
    plan += [('fc.query_official_intelligence',{'profile':'FC27','start':start,'end':end})]
    marketing_queries=queries
    plan += [('fc.query_marketing_snapshot',q) for q in marketing_queries]
    plan += [('fc.query_game_news',queries[0])]
    plan += [('fc.query_discount_analysis',dict(q,group_by='new_customer')) for q in queries]
    # Same native preparation schedule; reuse archives, never start another collector.
    plan += [('fc.query_pricing_evidence',dict(queries[0],kind=kind)) for kind in ('price_history','order_costs')]
    pending=list(plan);results={};until=time.monotonic()+45
    while pending:
        retry=[]
        for name,args in pending:
            key=json.dumps([name,args],sort_keys=True)
            try:
                row=book.research(name,args);data=row['data']
                results[key]={'tool':name,'query':args,'evidence_id':row['evidence_id'],'status':data.get('status'),
                    'source_cache':data.get('source_cache'),'reason':data.get('reason'),
                    'available_periods':data.get('available_periods')}
                if native_pending(data):retry.append((name,args))
            except (OSError,ValueError,TypeError,KeyError,PermissionError) as error:
                results[key]={'tool':name,'query':args,'status':'not_available','error_type':type(error).__name__}
        if not retry or time.monotonic()>=until:break
        pending=retry;time.sleep(3)
    return list(results.values())


def native_pending(value):
    states={'pending','busy','queued','reading','running'}
    return value.get('status') in states or any(s.get('status') in states for s in (value.get('source_status') or {}).values())


def native_cacheable(value):
    sources=value.get('source_status') or {}
    return (value.get('status')=='available' and bool(sources)
        and all(s.get('status')=='available' and s.get('stale') is False for s in sources.values())
        and all(value.get('authoritative_fields',{}).get(k,{}).get('status')=='available' for k in ('orders','revenueUsd')))


def report_queries(start,end,weekly=False):
    from datetime import date
    lo,hi=date.fromisoformat(start),date.fromisoformat(end)
    shift=timedelta(days=7 if lo==hi else (hi-lo).days+1)
    rows=[{'profile':'FC27','start':start,'end':end},
          {'profile':'FC27','start':(lo-shift).isoformat(),'end':(hi-shift).isoformat()}]
    if lo==hi:rows.append({'profile':'FC27','start':(lo-timedelta(days=1)).isoformat(),'end':(hi-timedelta(days=1)).isoformat()})
    rows.append({'profile':'FC27','start':lo.replace(day=1).isoformat(),'end':end})
    if weekly:
        rows.append({'profile':'FC27','start':(hi-timedelta(days=29)).isoformat(),'end':end})
        try:rows.append({'profile':'FC26','start':lo.replace(year=lo.year-1).isoformat(),'end':hi.replace(year=hi.year-1).isoformat()})
        except ValueError:pass
    return list({json.dumps(r,sort_keys=True):r for r in rows}.values())


def prepared_brief(book,start,end,weekly=False):
    """Register compact facts once before the first paid model turn."""
    from datetime import date
    trend_start=(date.fromisoformat(end)-timedelta(days=29 if weekly else 13)).isoformat()
    trend=book.query({'start':trend_start,'end':end,'group_by':['day'],'filters':{},'page':1})
    queries=report_queries(start,end,weekly);pending=list(queries);until=time.monotonic()+45
    while pending and book.native:
        pending=[q for q in pending if native_pending(book.native(q))]
        if not pending or time.monotonic()>=until:break
        time.sleep(3)
    rows=[]
    for query in queries:
        result=book.research('fc.query_native_statistics',query)
        rows.append({'evidence_id':result['evidence_id'],'query':query,
            'authoritative_fact_table':result.get('authoritative_fact_table',[]),
            'preparation_status':'ready' if native_cacheable(result['data']) else 'partial',
            'data':{k:v for k,v in result['data'].items() if k in ('status','selected_totals','selected_derived','authoritative_fields','native_customer_comparison','source_cache','reason')}})
    supplements=prepare_supplements(book,start,end,weekly)
    return {'contract':'fc-prepared-input-v1','native':rows,'daily_detail_trend':trend,'supplements':supplements,
            'total_basis':'FS原生总盘Admin优先、Order补缺；支付明细只作结构',
            'rule':'这些证据已注册，可直接引用及绑定计算。缺失再补查；同一查询无需重复调用。旧报告只学方法，不能复制旧结论。'}


class Preparation:
    def __init__(self,service):
        self.service=service;self.thread=None;self.day=None

    def tick(self,now):
        local=now.astimezone(SHANGHAI)
        if not (25<=local.hour*60+local.minute<35):return
        if not self.service.nightly.config() or not self.service.detail.config.get('enabled'):return
        day=local.date().isoformat()
        if self.day==day or (self.thread and self.thread.is_alive()):return
        store=SnapshotStore();store.directory();receipt=store.root/('preparation-'+day+'.json')
        if receipt.exists():self.day=day;return
        self.day=day
        self.thread=threading.Thread(target=self.run,args=(local,receipt),name='hermes-source-preparation',daemon=True)
        self.thread.start()

    def run(self,now,receipt):
        from fs_evidence import build_book
        from nightly import closed_period
        results=[]
        for kind in (('daily','weekly') if now.weekday()==0 else ('daily',)):
            if not self.service.nightly.config() or not self.service.detail.config.get('enabled'):break
            start,end=closed_period(now.date(),kind)
            try:
                book=build_book(self.service.detail,self.service.daily,self.service.read_range,self.service.diagnostics,
                    start,end,self.service.source_root,'wulv',recent_days=30 if kind=='weekly' else 14)
                brief=prepared_brief(book,start,end,kind=='weekly')
                results.append({'kind':kind,'snapshot_id':book.capture_id,'native_statuses':[r['preparation_status'] for r in brief['native']],
                    'supplements':brief['supplements']})
            except Exception as error:
                results.append({'kind':kind,'error_type':type(error).__name__})
        atomic(receipt,{'day':now.date().isoformat(),'completed_at':datetime.now(timezone.utc).isoformat(),
            'model_calls':0,'results':results,'status':'ready' if results and all('error_type' not in r and all(s=='ready' for s in r['native_statuses']) and all(s['status'] in ('available','partial','empty') for s in r['supplements']) for r in results) else 'partial'})
