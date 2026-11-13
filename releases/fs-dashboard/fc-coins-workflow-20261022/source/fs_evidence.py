"""FS-owned adapters reuse source services and return only explicit projections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import threading
import secrets
from copy import deepcopy
from decimal import Decimal,InvalidOperation
from pilot import digest

from research import ResearchBook, label
from skill_bundle import load_bundle


NATIVE_CACHE_CONTRACT='admin-first-paid-order-zero-valid-20261028-v3'

def native_cache_query(args,config):
    from traffic_contract import RULE_VERSION
    return {**args,'config':config,'field_authority_contract':NATIVE_CACHE_CONTRACT,'traffic_rule_version':RULE_VERSION}

def authoritative_native_fields(records,args,source_status=None):
    """Resolve field authority while preserving the original source records."""
    end=(date.fromisoformat(args['end'])+timedelta(days=1)).isoformat()+' 00:00'
    period={'start':args['start']+' 00:00','end':end};selected={}
    for system in ('order.p2pah.cn','admin.p2pah.cn'):
        for role,row in records.items():
            source=(source_status or {}).get('Admin' if system=='admin.p2pah.cn' else 'Order',{})
            stale=row.get('stale') if isinstance(row.get('stale'),bool) else source.get('stale')
            if row.get('system')!=system or row.get('status')!='available' or stale is not False or row.get('period')!=period:continue
            fields=dict(row.get('metrics') or {})
            site=None
            if system=='admin.p2pah.cn':
                from traffic_contract import main_site_values
                site=main_site_values(row)
                for name,value in site['values'].items():
                    if value is not None:fields[name]={'status':'available','value':value,'unit':'USD' if name=='revenueUsd' else 'count'}
            for name,unit in (('orders','count'),('revenueUsd','USD')):
                if name in row:fields.setdefault(name,{'status':'available','value':row[name],'unit':unit})
            for name,metric in fields.items():
                if not isinstance(metric,dict) or metric.get('status')!='available' or isinstance(metric.get('value'),bool):continue
                try:
                    if not Decimal(str(metric.get('value'))).is_finite():continue
                except (InvalidOperation,ValueError,TypeError):continue
                selected[name]={**metric,'system':system,'source_record':role,'period':period,'capturedAt':row.get('capturedAt'),'field_scope':site['scope'] if site and name in ('orders','revenueUsd') and site['values'].get(name) is not None else 'source_native_scope','website_basis':site['basis'] if site and name in ('orders','revenueUsd') and site['values'].get(name) is not None else None}
    return selected


class SourcePins:
    """Freeze the first usable reply per query, retaining its actual source times."""
    def __init__(self):self.values={};self.lock=threading.RLock();self.read_locks={}
    def wrap(self,reader,family,ready=None):
        def read(args):
            key=digest({'family':family,'query':args})
            with self.lock:
                query_lock=self.read_locks.setdefault(key,threading.RLock())
            # Freeze identical reads together; a slow family must not block other tools.
            with query_lock:
                if key in self.values:return deepcopy(self.values[key])
                value=deepcopy(reader(args))
                value['source_snapshot_id']='src_'+digest({'family':family,'query':args,'reply':value})[:24]
                value['snapshot_policy']='first_usable_source_reply_per_query; source timestamps remain distinct from Admin capture'
                if value.get('http_status')==200 and value.get('status') not in {None,'pending','reading','running','queued','failed','error','not_available','unavailable','not_sent'} and (ready is None or ready(value)):
                    self.values[key]=deepcopy(value)
                return value
        return read


def current_pricing_market(args, owner, request, legacy):
    """Read the existing authenticated price console projection for the active protocol."""
    try:
        market = request('/pricing/v3/market', owner)
    except (OSError, ValueError) as error:
        return dict(status='unavailable', reason='pricing_market_read_failed',
                    write_protocol_status='unverified', error_type=type(error).__name__,
                    http_status=getattr(error, 'code', None))
    if isinstance(market, dict) and market.get('write_protocol') == 'fc27_curve_v6':
        fields = ('write_protocol', 'snapshot_id', 'captured_at', 'competitor_policy',
                  'competitor_coverage', 'competitor_offers', 'price_basis', 'catalogue_samples')
        result = {key: market[key] for key in fields if key in market}
        result.update(http_status=200, profile='FC27', basis='active_plan_100k_market',
                      execution_authorized=False, write_performed=False)
        if not market.get('snapshot_id'):
            return dict(result, status='unavailable', reason='active_curve_snapshot_missing')
        complete = (market.get('competitor_coverage') or {}).get('quantity_coverage_complete') is True
        return dict(result, status='available' if complete else 'partial')
    if isinstance(market, dict) and market.get('write_protocol') is None and 'global_offers' in market:
        return legacy(args)
    return dict(status='unavailable', reason='pricing_market_protocol_unverified',
                write_protocol_status='unverified')


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


def lazy_paid_capture(book, reader, config):
    """Attach one asynchronous paid-detail read to only the tools that need it."""
    call=book.call
    paid_tools={'fc.query_business','fc.query_queue','fc.compare_periods','fc.get_breakdown'}
    pending=AsyncRead(reader)
    def on_demand(name,args):
        if name in paid_tools and book.data['coverage'].get('status')=='not_loaded':
            value=pending.get()
            if isinstance(value,dict):return value
            raw,actual=value
            if actual!=config:raise ValueError('source_config_changed')
            with book._lock:
                if book.data['coverage'].get('status')=='not_loaded':
                    book.data=raw
                    book.at=datetime.fromisoformat(raw['as_of'])
        return call(name,args)
    book.call=on_demand
    return book


def source_capture(detail,start,end,deadline=None):
    from fc_deep_sources import EvidenceReader
    from source_snapshots import SnapshotStore
    config=dict(detail.config)
    def capture():
        remaining=920 if deadline is None else (deadline-datetime.now(timezone.utc)).total_seconds()
        if remaining<=0:raise TimeoutError('nightly_deadline_exceeded')
        raw,actual=EvidenceReader(detail).capture({'read_start':start,'read_end':end},timeout=min(920,remaining))
        if actual!=config:raise ValueError('source_config_changed')
        return raw
    raw=SnapshotStore().get('paid-detail',{'start':start,'end':end,'config':config},capture,
        lambda value:value.get('coverage',{}).get('paid_complete') is True and not value.get('coverage',{}).get('missing_days') and 0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(value['as_of'])).total_seconds() < config['today_cache_seconds'],enabled=config.get('enabled') is True)
    if detail.config!=config:raise ValueError('source_config_changed')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(raw['as_of'])).total_seconds()
    if not 0<=age<config['today_cache_seconds']:
        raw['coverage']=dict(raw['coverage'],backlog_status='partial',backlog_reason='saved_current_pool_expired')
    return raw,config


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


def live_native_statistics(read_range,args):
    params={k:[v] for k,v in dict(mode='summary',grain='day',**args).items()}
    status,raw=read_range(params)
    if raw.get('scopeContractId') not in (None,'admin-paid-order-labelled-supplement-v2'):raise ValueError('native_source_contract')
    profile=raw.get('profile') or {}
    records={k:{field:profile[k][field] for field in ('system','status','period','currency','orders','revenueUsd','metrics','dimensions','capturedAt','sourceDataAsOf','stale','dimensions','normalisedScope','filters') if field in profile[k]} for k in ('primary','supplement','shipping') if isinstance(profile.get(k),dict)}
    return {'http_status':status,'status':raw.get('status'),'query':args,'source_contract':raw.get('scopeContractId'),
            'captured_at':datetime.now(timezone.utc).isoformat(),'capture_time_basis':'supplement_retrieved_at; each sourceDataAsOf retained below',
            'source_records':records,'authoritative_fields':authoritative_native_fields(records,args,raw.get('sources')),
            'source_status':raw.get('sources'),'consistentPeriod':raw.get('consistentPeriod'),
            'rule':'authoritative_fields已逐字段执行Admin优先、Order补缺；所有同比/目标也采用该选择，0是有效值。source_records的primary/supplement只是旧容器名，不是优先级；原记录仅供追溯，不能另选Order同字段替代Admin。平台/范围差异不阻断。'}


def build_book(detail,daily,read_range,diagnostics,start,end,source_root,owner,*,persist=None,deadline=None,recent_days=14,lazy_session=None,skills=None,lazy_report=None):
    lo,hi=date.fromisoformat(start),date.fromisoformat(end)
    read_start=min(lo-timedelta(days=max(13,(hi-lo).days+1)),hi-timedelta(days=recent_days-1)).isoformat()
    if lazy_report is not None and lazy_session is not None:raise ValueError('lazy_capture_identity')
    lazy_identity=lazy_session or lazy_report
    if lazy_identity is None:
        dataset,config=source_capture(detail,read_start,end,deadline=deadline) if deadline is not None else source_capture(detail,read_start,end)
    else:
        if not re.fullmatch(r'[a-f0-9]{32}',lazy_identity):raise ValueError('lazy_session_identity')
        config=dict(detail.config)
        dataset={'snapshot_id':('fc-detail-report-' if lazy_report is not None else 'fc-detail-conversation-')+lazy_identity,
                 'as_of':datetime.now(timezone.utc).isoformat(),
                 'coverage':{'period':{'start':read_start,'end':end},'status':'not_loaded'},
                 'orders':[],'backlog':[]}
    if skills is None:skills=load_bundle(source_root)
    scope=secrets.token_hex(32)
    clue_read=AsyncRead(lambda:problem_projection(diagnostics(),scope))
    history=ReportHistory(daily)
    def reference(args):
        params={k:[v] for k,v in dict(mode='profit-history',grain='day',**args).items()}
        status,raw=read_range(params)
        return {'status':raw.get('status'),'http_status':status,'query':args,'source_scope':'Order/all-websites',
                'reference_only':True,'not_verified_pricing_cost':True,'captured_at':datetime.now(timezone.utc).isoformat(),
                'source_metadata':{k:raw[k] for k in ('snapshot_id','snapshotId','version','generatedAt','capturedAt','sourceDataAsOf','stale','dimensions','normalisedScope','filters') if k in raw},
                'missingDays':raw.get('missingDays'), 'rows':raw.get('history',{}).get('daily',[]),'error':raw.get('error') or raw.get('lastError')}
    def live_native(args):
        return live_native_statistics(read_range,args)
    from source_snapshots import SnapshotStore,native_cacheable,official_snapshot,archived_publication
    def native(args):
        return SnapshotStore().get('native-statistics',native_cache_query(args,detail.config),lambda:live_native(args),
            native_cacheable,
            enabled=detail.config.get('enabled') is True)
    from admin_order_capabilities_20261014.provider import CapabilityProvider
    from admin_order_capabilities_20261014.fs_reader import admin_read,order_read
    capability=CapabilityProvider(config,detail.pool,admin_read,lambda q:order_read(q,detail.config,'/var/www/dashboard/fs-home/transactions'))
    pins=SourcePins()
    from market_snapshot import MarketReader
    from pricing_operations import native as pricing_read
    from marketing_snapshot import MarketingReader
    from official_intelligence import OfficialReader, checked_query as checked_official_query
    legacy_market = MarketReader()
    pinned_market = pins.wrap(lambda args: current_pricing_market(args, owner, pricing_read, legacy_market),
                              'FC27-existing-market')
    marketing_reader=MarketingReader(owner=owner)
    from es_order_structure import reader_for
    pinned_es=pins.wrap(lambda q:reader_for(detail).get(q),'Admin-ES-file-set')
    from admin_product_orders import read as product_order_read
    pinned_product_orders=pins.wrap(product_order_read,'Admin-model-product-orders')
    from cohort_reader import reader_for as cohort_reader_for
    pinned_cohort=pins.wrap(lambda q:cohort_reader_for(detail).get(q),'Admin-paid-customer-observation')
    def product_orders_read(args):
        if not detail.config.get('enabled'):return {'status':'unavailable','reason':'fc_detail_disabled'}
        if 'evidence_id' in args:
            from workspace_evidence import read
            return read(detail,'product_orders',{k:v for k,v in args.items() if k!='evidence_id'},args['evidence_id'])
        return pinned_product_orders(args)
    def es_read(args):
        if not detail.config.get('enabled'):return {'status':'unavailable','reason':'fc_detail_disabled'}
        if 'evidence_id' in args:
            from workspace_evidence import read
            return read(detail,'discount_analysis',{k:v for k,v in args.items() if k!='evidence_id'},args['evidence_id'])
        return pinned_es(args)
    pinned_marketing=pins.wrap(lambda q:archived_publication('marketing',q,marketing_reader(q)),'MMOEXP-existing-marketing')
    marketing_jobs={};marketing_lock=threading.Lock()
    pinned_news=pins.wrap(lambda q:archived_publication('news',q,shared_news(q)),'MMOEXP-SEO-shared-news')
    def news_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_news(args)
    def marketing_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        from report_tracks import fc27_marketing_view
        key=digest(args)
        with marketing_lock:
            if key not in marketing_jobs:marketing_jobs[key]=AsyncRead(lambda:pinned_marketing(args))
            value=marketing_jobs[key].get()
            if value.get('status') in ('pending','busy'):
                # A completed native pending reply polls its original query next time.
                if value.get('reason')!='source_read_running':marketing_jobs.pop(key)
                return value
        value['fc27_by_name']=fc27_marketing_view(value)
        value['scope']='2026-10-17明确全局品牌例外优先，FC专属与全局品牌分开；其余未筛选数据为MMOEXP全站背景，非订单级归因。'
        value['rule']=value['fc27_by_name']['rule']+' 未筛选全站数据仍为背景；名称不证明国家定向或订单级因果。'
        for account in value.get('ads_accounts',[]):
            if isinstance(account.get('campaigns'),dict):account['campaigns']['rule']=value['rule']
        return value
    official_jobs={};official_lock=threading.Lock();official_reader=OfficialReader()
    def read_official(args):
        checked_official_query(args)
        with official_lock:
            key=digest(args)
            if key not in official_jobs:
                official_jobs[key]=AsyncRead(lambda:official_snapshot(official_reader,args,detail.config))
            job=official_jobs[key]
        return job.get()
    pinned_official=pins.wrap(read_official,'EA-FC27-official')
    def official_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_official(args)
    def market_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_market(args)
    def durable_capability(args):
        if args.get('kind')!='native_loss':return capability.get(args)
        return SnapshotStore().get('native-loss',dict(args,config=detail.config),lambda:capability.get(args),
            lambda v:v.get('http_status')==200 and v.get('status')=='available' and not v.get('stale'),
            enabled=detail.config.get('enabled') is True)
    pinned_capability=pins.wrap(durable_capability,'Admin-Order-capability')
    pinned_native=pins.wrap(native,'Admin-native-labelled-Order',ready=native_cacheable)
    def native_read(args):
        if not detail.config.get('enabled'):raise PermissionError('source_disabled')
        return pinned_native(args)
    def capability_read(args):
        # User OFF is a live barrier checked before any task snapshot/cache reply.
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_capability(args)
    book=ResearchBook(dataset,config,{'start':start,'end':end},history=pins.wrap(history.read,'FC-report-history'),history_index=history.index,reference=pins.wrap(reference,'Order-reference'),
                        clues=clue_read.get,skills=skills,persist=persist,native=native_read,capability=capability_read,market=market_read,official=official_read,marketing=marketing_read,news=news_read,es_structure=es_read,product_orders=product_orders_read,cohort_observation=pinned_cohort)
    from coins_evidence import CoinsEvidence
    pinned_coins=pins.wrap(CoinsEvidence(dataset=lambda:book.data),'FC-Coins-existing-evidence')
    def coins_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return pinned_coins(args)
    book.coins_evidence=coins_read
    from pricing_workflow import Workflow
    from pricing_simulation import SimulationBridge
    workflow=Workflow(book,SimulationBridge())
    def workflow_read(args):
        if not detail.config.get('enabled'):return {'status':'not_available','reason':'fc_detail_disabled'}
        return workflow(args)
    book.pricing_workflow=workflow_read
    from user_tools import runtime_invoke as user_analytics_read
    book.user_analytics=pins.wrap(lambda args:user_analytics_read(owner,args,detail=detail),'FS-purchase-customer-analytics')
    if lazy_identity is not None:
        lazy_paid_capture(book,lambda:source_capture(detail,read_start,end,deadline=deadline) if deadline is not None else source_capture(detail,read_start,end),config)
    return book
