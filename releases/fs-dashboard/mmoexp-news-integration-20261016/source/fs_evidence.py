"""FS-owned adapters reuse source services and return only explicit projections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import threading
import secrets
from copy import deepcopy
from pilot import digest

from research import ResearchBook, label
from skill_bundle import load_bundle


class SourcePins:
    """Freeze the first usable reply per query, retaining its actual source times."""
    def __init__(self):self.values={};self.lock=threading.RLock()
    def wrap(self,reader,family):
        def read(args):
            key=digest({'family':family,'query':args})
            with self.lock:
                if key in self.values:return deepcopy(self.values[key])
                value=deepcopy(reader(args))
                value['source_snapshot_id']='src_'+digest({'family':family,'query':args,'reply':value})[:24]
                value['snapshot_policy']='first_usable_source_reply_per_query; source timestamps remain distinct from Admin capture'
                if value.get('http_status')==200 and value.get('status') not in {None,'pending','reading','running','queued','failed','error','not_available','unavailable','not_sent'}:
                    self.values[key]=deepcopy(value)
                return value
        return read


def shared_news(args):
    """Read the operator-installed shared snapshot adapter; never fetch a source."""
    from importlib.util import spec_from_file_location, module_from_spec
    try:
        spec=spec_from_file_location('fs_mmoexp_shared_news','/opt/fs-boss-workspaces/backend/mmoexp_news.py')
        module=module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.read_shared(args)
    except (OSError,ValueError,TypeError,AttributeError,ImportError):
        return {'http_status':503,'status':'not_available','reason':'shared_news_unavailable'}


class AsyncRead:
    def __init__(self, reader):
        self.reader=reader;self.future=None;self.lock=threading.Lock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='hermes-evidence-read')

    def get(self):
        with self.lock:
            if self.future is None:self.future=self.pool.submit(self.reader)
            future=self.future
        if not future.done():return {'status':'pending','reason':'source_read_running','retryAfter':3}
        try:return future.result()
        except Exception:return {'status':'unavailable','reason':'source_read_failed'}


def source_capture(detail,start,end,deadline=None):
    from fc_deep_sources import EvidenceReader
    if deadline is not None:
        remaining=(deadline-datetime.now(timezone.utc)).total_seconds()
        if remaining<=0:raise TimeoutError('nightly_deadline_exceeded')
        return EvidenceReader(detail).capture({'read_start':start,'read_end':end},timeout=min(920,remaining))
    return EvidenceReader(detail).capture({'read_start':start,'read_end':end})


def problem_projection(value, scope):
    out={k:value[k] for k in ('contract','status','reason','captured_at','sampled','listed','pages','coverage','categories','platform_counts','errors','note') if k in value}
    out['samples']=[{'case_ref':'case_'+hashlib.sha256((scope+str(r.get('ref'))).encode()).hexdigest()[:24],
                     **{k:r[k] for k in ('platform','amount_usd','category','last_matching_log_at','basis','requires_latest_state_review') if k in r}}
                    for r in value.get('samples',[])]
    out['case_identity']='task_scoped_pseudonym_not_cross_task_cohort'
    return out


def old_report_projection(report):
    out={k:report[k] for k in ('day','date','revision','report_id','generated_at','status','data_status') if k in report}
    out['model_status']=report.get('ai',{}).get('status')
    out['main']=report.get('main')
    deep=report.get('deep') or {}
    out['readings']=[{k:e[k] for k in ('ref','kind','value','source','scope','captured_at','period','snapshot_id','state_basis') if k in e}
                      for e in deep.get('evidence',[]) if e.get('kind')=='period_facts']
    out['previous_judgments']=[{k:label(r[k]) if k=='title' else r[k] for k in ('priority','type','title','observation','hypothesis','action','condition','risk','refs','verify') if k in r}
                               for r in deep.get('decision',{}).get('findings',[])]
    out['rule']='历史模型/规则判断仅供复盘；同业务日多时点不等于同成熟度，未执行建议不得归因效果'
    return out


def bounded_history(value,args):
    """Keep large report bytes available in declared Unicode-safe JSON fragments."""
    sections=('readings','previous_judgments','summary','findings','actions','reviews','limitations')
    collection='hermes_reports' if value.get('hermes_reports') else 'reports'
    entries=value.get(collection,[])
    section=args.get('section')
    if section is not None and section not in ('overview',)+sections:raise ValueError('history_section')
    item=args.get('item',1)
    if type(item) is not int or not 1<=item<=100000:raise ValueError('history_item')
    full=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if entries and (section is not None or len(full)>12000 and 'chunk' not in args):
        report=entries[0]
        index={k:{'items':len(report[k]) if isinstance(report[k],list) else 1,'bytes':len(json.dumps(report[k],ensure_ascii=False,separators=(',',':')).encode())} for k in sections if k in report}
        chosen={k:v for k,v in report.items() if k not in sections}
        if section not in (None,'overview') and section in report:
            source=report[section];chosen[section]=source[item-1:item] if isinstance(source,list) else source if item==1 else None
        value={**value,collection:[chosen],'content_index':index,'selected_section':section or 'overview','selected_item':item,
               'complete_version_sha256':hashlib.sha256(full).hexdigest(),'coverage':'selected metadata/section only; omitted fields remain in the original report'}
    chunk=args.get('chunk',1)
    if type(chunk) is not int or not 1<=chunk<=100000:raise ValueError('history_chunk')
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(raw)<=12000:
        if chunk!=1:return dict(value,status='empty',reports=[],hermes_reports=[],report_chunks={'chunk':chunk,'total_chunks':1,'has_more':False})
        return value
    fragments=[];lo=0
    while lo<len(raw):
        hi=min(lo+4096,len(raw))
        while True:
            try:text=raw[lo:hi].decode('utf-8');break
            except UnicodeDecodeError:hi-=1
        fragments.append(text);lo=hi
    out={k:value[k] for k in ('http_status','captured_at','pagination','scope','owner_context','date_basis','version_boundary','history_index_snapshot_id') if k in value}
    out.update(status='partial' if chunk<=len(fragments) else 'empty',reports=[],hermes_reports=[],
        report_chunks={'format':'canonical-json-fragments','chunk':chunk,'total_chunks':len(fragments),'has_more':chunk<len(fragments),
                       'text':fragments[chunk-1] if chunk<=len(fragments) else '',
                       'sha256':hashlib.sha256(raw).hexdigest(),'full_payload_bytes':len(raw),
                       'rule':'Partial canonical JSON fragment. Read relevant sections/items or reconstruct every fragment and verify sha256 before treating a version as complete. There is no cumulative history byte quota; native Hermes manages context. Original report is unchanged.'})
    if len(json.dumps(out,ensure_ascii=False,separators=(',',':')).encode())>12000:raise ValueError('history_fragment_budget')
    return out


class ReportHistory:
    """Freeze the version boundary once, then expose complete versions in pages."""
    def __init__(self,daily):
        self.daily=daily
        with daily.db() as db:
            self.maximum=db.execute('SELECT COALESCE(MAX(job_id),0) FROM reports').fetchone()[0]
            rows=db.execute('SELECT day,count(*) FROM reports WHERE job_id<=? GROUP BY day ORDER BY day DESC LIMIT 90',(self.maximum,)).fetchall()
        self.index={'available_days':[{'day':r[0],'versions':r[1]} for r in rows],
                    'date_basis':'stored report business day; generation/analysis periods are distinct and must be inspected',
                    'captured_at':datetime.now(timezone.utc).isoformat(),'coverage':'recent 90 stored business days',
                    'version_boundary':'versions present at analysis creation; later generated reports excluded',
                    'snapshot_id':'hist_'+digest({'maximum':self.maximum,'days':[list(r) for r in rows]})[:24]}
    def read(self,args):
        page=args.get('page',1)
        if type(page) is not int or not 1<=page<=100000:raise ValueError('history_page')
        with self.daily.db() as db:
            query=(args['start'],args['end'],self.maximum)
            total=db.execute('SELECT count(*) FROM reports WHERE day>=? AND day<=? AND job_id<=?',query).fetchone()[0]
            rows=db.execute('SELECT content FROM reports WHERE day>=? AND day<=? AND job_id<=? ORDER BY job_id DESC LIMIT 1 OFFSET ?',(*query,page-1)).fetchall()
        return bounded_history({'http_status':200,'status':'available' if rows else 'empty','reports':[old_report_projection(json.loads(r[0])) for r in rows],
                'pagination':{'page':page,'page_size':1,'total_reports':total,'has_more':page<total},
                'history_index_snapshot_id':self.index['snapshot_id'], 'captured_at':self.index['captured_at'],
                'scope':'FC stored complete report versions; inspect actual Admin/Order periods before comparison',
                'date_basis':self.index['date_basis'],'version_boundary':self.index['version_boundary']},args)


class OwnerRunHistory:
    """Freeze completed canonical owner requests, never append all reports to a page."""
    def __init__(self,tasks,owner):
        self.tasks,self.owner=tasks,owner
        with tasks.db() as db:
            rows=db.execute("SELECT id,body FROM requests WHERE owner=? AND state='COMPLETED' ORDER BY rowid DESC",(owner,)).fetchall()
        self.entries=[{'id':r[0],'period':{k:json.loads(r[1])[k] for k in ('start','end')}} for r in rows]
        self.index={'available_periods':[r['period'] for r in self.entries[:90]],'total_versions':len(self.entries),
                    'coverage':'latest 90 period descriptors; all captured versions remain paged',
                    'captured_at':datetime.now(timezone.utc).isoformat(),'date_basis':'completed own investigation period overlaps query',
                    'version_boundary':'only completed canonical requests present at analysis creation',
                    'snapshot_id':'ownhist_'+digest({'owner':owner,'entries':self.entries})[:24]}
    def read(self,args):
        page=args.get('page',1)
        if type(page) is not int or not 1<=page<=100000:raise ValueError('history_page')
        matches=[r for r in self.entries if r['period']['start']<=args['end'] and r['period']['end']>=args['start']]
        selected=matches[page-1:page];previous=[]
        if selected:
            with self.tasks.db() as db:row=db.execute("SELECT result FROM requests WHERE id=? AND owner=? AND state='COMPLETED'",(selected[0]['id'],self.owner)).fetchone()
            if row is None or not row[0]:return {'http_status':503,'status':'not_available','reason':'history_version_missing'}
            saved=json.loads(row[0]);previous=[{'report_id':selected[0]['id'],'period':selected[0]['period'],
                **{k:saved[k] for k in ('summary','findings','actions','reviews','limitations')},
                'rule':'原证据ID属于原任务；复盘须重查当前证据，未执行建议不能归因效果'}]
        return bounded_history({'http_status':200,'status':'available' if previous else 'empty','reports':[],'hermes_reports':previous,
                'pagination':{'page':page,'page_size':1,'total_reports':len(matches),'has_more':page<len(matches)},
                'captured_at':self.index['captured_at'],'history_index_snapshot_id':self.index['snapshot_id'],
                'owner_context':'current_owner_only','date_basis':self.index['date_basis'],'version_boundary':self.index['version_boundary']},args)


def attach_owner_history(book,tasks,owner):
    daily=book.history;owned=OwnerRunHistory(tasks,owner);pins=SourcePins()
    read_owned=pins.wrap(owned.read,'FC-owner-investigation-history')
    def history(args):
        if args.get('source','daily')=='hermes':return read_owned(args)
        return daily(args) if daily else {'status':'not_available','reason':'daily_history_missing'}
    book.history=history
    book.history_index=dict(book.history_index or {},hermes=owned.index)


def build_book(detail,daily,read_range,diagnostics,start,end,source_root,owner,*,persist=None,deadline=None):
    lo,hi=date.fromisoformat(start),date.fromisoformat(end)
    read_start=(lo-timedelta(days=max(7,(hi-lo).days+1))).isoformat()
    dataset,config=source_capture(detail,read_start,end,deadline=deadline) if deadline is not None else source_capture(detail,read_start,end)
    skills=load_bundle(source_root)
    scope=secrets.token_hex(32)
    clue_read=AsyncRead(lambda:problem_projection(diagnostics(),scope))
    history=ReportHistory(daily)
    def reference(args):
        params={k:[v] for k,v in dict(mode='profit-history',grain='day',**args).items()}
        status,raw=read_range(params)
        return {'status':raw.get('status'),'http_status':status,'query':args,'source_scope':'Order/all-websites',
                'reference_only':True,'not_verified_pricing_cost':True,'captured_at':datetime.now(timezone.utc).isoformat(),
                'source_metadata':{k:raw[k] for k in ('snapshot_id','snapshotId','version','generatedAt','capturedAt','sourceDataAsOf','stale') if k in raw},
                'missingDays':raw.get('missingDays'), 'rows':raw.get('history',{}).get('daily',[]),'error':raw.get('error') or raw.get('lastError')}
    def native(args):
        params={k:[v] for k,v in dict(mode='summary',grain='day',**args).items()}
        status,raw=read_range(params)
        if raw.get('scopeContractId') not in (None,'admin-main-order-labelled-supplement-v1'):raise ValueError('native_source_contract')
        profile=raw.get('profile') or {}
        return {'http_status':status,'status':raw.get('status'),'query':args,'source_contract':raw.get('scopeContractId'),
                'captured_at':datetime.now(timezone.utc).isoformat(),'capture_time_basis':'supplement_retrieved_at; each sourceDataAsOf retained below',
                'source_records':{k:{field:profile[k][field] for field in ('system','status','period','currency','orders','revenueUsd','metrics','dimensions','capturedAt','sourceDataAsOf','stale') if field in profile[k]} for k in ('primary','supplement') if isinstance(profile.get(k),dict)},
                'source_status':raw.get('sources'),'consistentPeriod':raw.get('consistentPeriod'),
                'rule':'须读取各记录system/source/scope；Admin权威主源，Order仅参考，不按primary字段名猜实际源'}
    from admin_order_capabilities_20261014.provider import CapabilityProvider
    from admin_order_capabilities_20261014.fs_reader import admin_read,order_read
    capability=CapabilityProvider(config,detail.pool,admin_read,lambda q:order_read(q,detail.config,'/var/www/dashboard/fs-home/transactions'))
    pins=SourcePins()
    from market_snapshot import MarketReader
    from marketing_snapshot import MarketingReader
    from official_intelligence import OfficialReader, checked_query as checked_official_query
    pinned_market=pins.wrap(MarketReader(),'FC27-existing-market')
    pinned_marketing=pins.wrap(MarketingReader(),'MMOEXP-existing-marketing')
    pinned_news=pins.wrap(shared_news,'MMOEXP-SEO-shared-news')
    def news_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_news(args)
    def marketing_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_marketing(args)
    official_jobs={};official_lock=threading.Lock();official_reader=OfficialReader()
    def read_official(args):
        checked_official_query(args)
        with official_lock:
            key=digest(args)
            if key not in official_jobs:
                official_jobs[key]=AsyncRead(lambda:official_reader(args))
            job=official_jobs[key]
        return job.get()
    pinned_official=pins.wrap(read_official,'EA-FC27-official')
    def official_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_official(args)
    def market_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_market(args)
    pinned_capability=pins.wrap(capability.get,'Admin-Order-capability')
    def capability_read(args):
        # User OFF is a live barrier checked before any task snapshot/cache reply.
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_capability(args)
    return ResearchBook(dataset,config,{'start':start,'end':end},history=pins.wrap(history.read,'FC-report-history'),history_index=history.index,reference=pins.wrap(reference,'Order-reference'),
                        clues=clue_read.get,skills=skills,persist=persist,native=pins.wrap(native,'Admin-native-labelled-Order'),capability=capability_read,market=market_read,official=official_read,marketing=marketing_read,news=news_read)
