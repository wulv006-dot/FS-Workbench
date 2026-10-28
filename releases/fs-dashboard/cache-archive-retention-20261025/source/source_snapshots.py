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


def archive_status(query,root=Path('/var/lib/fs-data-archive')):
    """Expose observed item gaps without waiting for a whole archive run or collecting."""
    path=Path(root)/'scheduler-state.json'
    result=dict(stateFile=str(path),coverage_complete=None,blocks_publication=False)
    try:
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('archive_state_link')
        state=json.loads(path.read_text('utf-8'))
        if not isinstance(state,dict):raise ValueError('archive_state_shape')
    except (OSError,ValueError):
        return dict(result,status='unavailable',reason='archive_observations_unavailable',missingCount=None,missing=[])
    rows=[]
    for row in state.values():
        if not isinstance(row,dict) or not isinstance(row.get('query'),dict):continue
        q=row['query']
        if query.get('profile') and q.get('profile')!=query['profile']:continue
        if not q.get('start') or not q.get('end'):continue
        if q['end'][:10]<query['start'][:10] or q['start'][:10]>query['end'][:10]:continue
        if any(key in query and q.get(key)!=query[key] for key in ('rs_site','rs_server','rs_category','profit_site','profit_category')):continue
        rows.append(row)
    missing=[{key:row.get(key) for key in ('query','family','cadence','status','reason','retryable','failures','retryAfter','lastObservedAt')} for row in rows if row.get('status')!='complete']
    return dict(result,status='partial' if missing else 'no_recorded_gaps' if rows else 'unobserved',
        observedCount=len(rows),missingCount=len(missing) if rows else None,
        terminalCount=sum(row.get('status')=='failed' and row.get('retryable') is False for row in missing),missing=missing[:16],
        limitation='Observed item states only; absent observations are unknown, not zero or proof of complete period coverage.')


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
        if not path.exists():
            from cache_retention import restore
            restore(path)
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>64*1024*1024:raise ValueError('snapshot_file')
        if os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):raise ValueError('snapshot_file_permissions')
        return json.loads(path.read_text('utf8'))

    def get(self,family,query,reader,valid,*,enabled=True):
        if not enabled:raise PermissionError('source_disabled')
        from daily_archive import read,save
        managed=family=='native-statistics' and bool(query.get('profile'))
        def stale(value):
            cached=value.get('source_cache') or {}
            return bool(value.get('stale') or cached.get('stale') or cached.get('status') in ('busy','pending','stale'))
        def complete(value):
            return value.get('status')=='available' and not stale(value) and valid(value)
        predicate=complete if managed else valid
        if managed:
            query=dict(query,admin_summary_contract='admin-paid-order-labelled-supplement-v2')
            value=read(family,query)
            if value is not None and complete(value) and query.get('refresh') not in (True,1,'1'):return value
        value=self.get_live(family,query,reader,predicate,enabled=enabled)
        if managed and complete(value):save(family,query,value,source_at=(value.get('source_cache') or {}).get('saved_at'))
        elif managed:
            if value.get('status')=='available' and stale(value):value=dict(value,status='stale',stale=True,reason=value.get('reason') or 'source_stale')
            value=dict(value,archive_status=archive_status(query))
        return value

    def get_live(self,family,query,reader,valid,*,enabled=True):
        if not enabled:raise PermissionError('source_disabled')
        if family not in ('paid-detail','native-statistics','native-loss','official-index','published-source'):raise ValueError('snapshot_family')
        now=self.clock();day=now.astimezone(SHANGHAI).date()
        # Open days retain the original live reader and its upstream freshness policy.
        if family not in ('official-index','published-source') and query['end']>=day.isoformat():return reader()
        max_age=7200 if family=='native-loss' else 21600 if family=='official-index' else 86400
        identity=encoded({'family':family,'query':query,'contract':1})
        key=hashlib.sha256(identity).hexdigest();pinned_query=json.loads(encoded(query))
        refresh=query.get('refresh') in (True,1,'1')
        from cache_retention import cache_lock,private
        self.directory();index=self.root/(key+'.json')

        def scope_current():
            if encoded({'family':family,'query':query,'contract':1})!=identity:raise ValueError('snapshot_query_changed')

        def lookup():
            scope_current();self.directory()
            if not (index.exists() or index.is_symlink()):return None
            pointer=self.read(index);version=pointer.get('version','')
            if len(version)!=64 or any(c not in '0123456789abcdef' for c in version):raise ValueError('snapshot_version')
            saved=self.read(self.root/(version+'.data.json'))
            if (hashlib.sha256(encoded(saved)).hexdigest()!=version or saved.get('key')!=key
                    or saved.get('contract')!=1 or saved.get('family')!=family or encoded(saved.get('query'))!=encoded(pinned_query)):
                raise ValueError('snapshot_integrity')
            at=datetime.fromisoformat(saved['saved_at']);current=self.clock();age=(current-at).total_seconds()
            fresh=0<=age<max_age and at.astimezone(SHANGHAI).date()==current.astimezone(SHANGHAI).date() and valid(saved['value'])
            return saved,version,fresh

        def reused(cached):
            scope_current()
            return self.label(cached[0]['value'],cached[1],cached[0]['saved_at'],True,max_age)

        with LOCK,cache_lock(self.root):
            previous=lookup()
            if previous and previous[2] and not refresh:return reused(previous)
        initial_version=previous[1] if previous else None
        # Stable per-query files are deliberately never unlinked: waiters must share one inode.
        lock_path=self.root/('.refresh-'+key+'.lock')
        fd=os.open(str(lock_path),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            info=os.fstat(fd);current=private(lock_path)
            if (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino):raise ValueError('snapshot_refresh_lock_changed')
            try:
                if os.name=='posix':
                    import fcntl
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                else:
                    import msvcrt
                    msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            except OSError as error:
                import errno
                if not isinstance(error,BlockingIOError) and not (os.name=='nt' and error.errno in (errno.EACCES,errno.EAGAIN,errno.EDEADLK)):raise
                scope_current()
                usable=previous is not None and valid(previous[0]['value'])
                value=self.label(previous[0]['value'] if usable else {},previous[1] if usable else None,
                    previous[0]['saved_at'] if usable else None,usable,max_age)
                value.update(status='busy',stale=True,reason='source_refresh_in_progress')
                value['source_cache'].update(status='stale' if usable else 'pending',stale=True)
                return value
            with LOCK,cache_lock(self.root):
                previous=lookup()
                if previous and previous[2] and (not refresh or previous[1]!=initial_version):return reused(previous)
            prior_version=previous[1] if previous else None
            previous=None  # Do not retain an old large reply while the independent reader runs.
            value=reader()
            scope_current()
            if family=='published-source' and pinned_query.get('source_version'):
                actual=value.get('source_sha256') or value.get('source_snapshot_id') or value.get('shared_snapshot_id')
                if actual!=pinned_query['source_version']:raise ValueError('snapshot_source_changed')
            if not valid(value):return value
            with LOCK,cache_lock(self.root):
                scope_current();self.directory();current=private(lock_path)
                if (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino):raise ValueError('snapshot_refresh_lock_changed')
                pointer=self.read(index) if index.exists() or index.is_symlink() else {}
                if pointer.get('version')!=prior_version:
                    newer=lookup()
                    if newer and newer[2]:return reused(newer)
                if not valid(value):return value
                scope_current()
                saved={'contract':1,'key':key,'family':family,'query':pinned_query,'saved_at':self.clock().isoformat(),'value':value}
                version=hashlib.sha256(encoded(saved)).hexdigest();path=self.root/(version+'.data.json')
                if not path.exists():atomic(path,saved)
                atomic(index,{'version':version})
                return self.label(value,version,saved['saved_at'],False,max_age)
        finally:os.close(fd)

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
    plan += [('fc.run_pricing_workflow',dict(queries[0],action='review'))]
    pending=list(plan);results={};until=time.monotonic()+45
    while pending:
        retry=[]
        for name,args in pending:
            key=json.dumps([name,args],sort_keys=True)
            try:
                row=book.research(name,args);data=row['data']
                results[key]={'tool':name,'query':args,'evidence_id':row['evidence_id'],'status':data.get('status'),
                    'source_cache':data.get('source_cache'),'archive':data.get('archive'),'reason':data.get('reason'),
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
            'data':{k:v for k,v in result['data'].items() if k in ('status','selected_totals','selected_derived','authoritative_fields','native_customer_comparison','source_cache','reason','archive_status')}})
    supplements=prepare_supplements(book,start,end,weekly)
    gaps=[{'tool':'fc.query_native_statistics','query':r['query'],'evidence_id':r['evidence_id'],'status':r['preparation_status']} for r in rows if r['preparation_status']!='ready']
    gaps += [r for r in supplements if r['status'] not in ('available','empty')]
    return {'contract':'fc-prepared-input-v1','native':rows,'daily_detail_trend':trend,'supplements':supplements,
            'collection_readiness':{'status':'partial' if gaps else 'ready','gaps':gaps,'blocks_publication':False},
            'total_basis':'FS原生总盘Admin优先、Order补缺；支付明细只作结构',
            'rule':'这些证据已注册，可直接引用及绑定计算。缺失再补查；同一查询无需重复调用。旧报告只学方法，不能复制旧结论。缺失数据不阻塞发布；有可比趋势和已核相关数据才可推算，逐项标注“预估，真实数据暂未提供”，写明证据、方法、假设、适用范围及后续核对条件。无依据则保留未知，不补零。预估不可写入真实归档或作为已验证结论，后续报告取得真实值后核对原估计及误差，追加修订并保留原稿。'}


def preparation_complete(results):
    return bool(results) and all('error_type' not in r and all(s=='ready' for s in r['native_statuses'])
        and all(s['status'] in ('available','empty') for s in r['supplements']) for r in results)


class Preparation:
    def __init__(self,service):
        self.service=service;self.thread=None

    def tick(self,now):
        local=now.astimezone(SHANGHAI)
        if not (50<=local.hour*60+local.minute<5*60+20):return
        if not self.service.nightly.config() or not self.service.detail.config.get('enabled'):return
        day=local.date().isoformat()
        if self.thread and self.thread.is_alive():return
        store=SnapshotStore();store.directory();receipt=store.root/('preparation-'+day+'.json')
        prior=store.read(receipt) if receipt.exists() else {}
        if prior.get('status')=='ready' and preparation_complete(prior.get('results',[])):return
        if prior.get('retry_after',0)>local.timestamp():return
        tasks=getattr(self.service,'tasks',None)
        if tasks:
            with tasks.db() as db:
                if db.execute("SELECT 1 FROM requests WHERE state IN ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED') LIMIT 1").fetchone():return
        attempt=prior.get('attempt',0)+1
        # Persist before starting so a restart cannot immediately repeat a failed batch.
        if prior:atomic(receipt.with_name(receipt.stem+'-attempt-'+str(attempt-1)+'.json'),prior)
        atomic(receipt,dict(prior,day=day,status='retrying',attempt=attempt,retry_after=local.timestamp()+min(900,300*2**min(attempt-1,6))))
        self.thread=threading.Thread(target=self.run,args=(local,receipt,attempt),name='hermes-source-preparation',daemon=True)
        self.thread.start()

    def run(self,now,receipt,attempt=1):
        from fs_evidence import build_book
        from nightly import closed_period
        results=[]
        kinds=['daily']+(['weekly'] if now.weekday()==0 else [])+(['monthly'] if now.day==1 else [])
        for kind in kinds:
            if not self.service.nightly.config() or not self.service.detail.config.get('enabled'):break
            start,end=closed_period(now.date(),kind)
            try:
                book=build_book(self.service.detail,self.service.daily,self.service.read_range,self.service.diagnostics,
                    start,end,self.service.source_root,'wulv',deadline=min(datetime.now(SHANGHAI)+timedelta(minutes=20),now.replace(hour=5,minute=25,second=0,microsecond=0)),recent_days=30 if kind=='weekly' else 14)
                brief=prepared_brief(book,start,end,kind=='weekly')
                from nightly_data import save_book
                archive_entry=save_book(now.date().isoformat(),kind,start,end,book,brief)
                results.append({'kind':kind,'archive':archive_entry,'snapshot_id':book.capture_id,'native_statuses':[r['preparation_status'] for r in brief['native']],
                    'supplements':brief['supplements']})
            except Exception as error:
                results.append({'kind':kind,'error_type':type(error).__name__})
        complete=preparation_complete(results)
        value={'day':now.date().isoformat(),'completed_at':datetime.now(timezone.utc).isoformat(),
            'model_calls':0,'results':results,'attempt':attempt,'retry_after':datetime.now(timezone.utc).timestamp()+min(900,300*2**min(attempt-1,6)),
            'status':'ready' if complete else 'partial','blocks_publication':False}
        atomic(receipt.with_name(receipt.stem+'-attempt-'+str(attempt)+'.json'),value)
        atomic(receipt,value)
