"""Authenticated aggregate adapter sharing the existing FC paid reader and pool."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import re
import threading
import time
from cohort_observation import update, read, CONTRACT
from cohort_paid_source import GAME_IDS

SHANGHAI=timezone(timedelta(hours=8))


def checked_query(args):
    if not isinstance(args,dict) or not {'profile','start','end'} <= set(args) or set(args)-{'profile','start','end','platform','site_group','window_days','evidence_id','action'}:
        raise ValueError('cohort_fields')
    lo,hi=(date.fromisoformat(args[k]) for k in ('start','end'))
    yesterday=datetime.now(SHANGHAI).date()-timedelta(days=1)
    if args['profile'] not in GAME_IDS or lo.isoformat()!=args['start'] or hi.isoformat()!=args['end'] or not 0 <= (hi-lo).days <= 30 or hi>yesterday:
        raise ValueError('cohort_period')
    platform,site=args.get('platform','all'),args.get('site_group','main')
    if platform not in ('all','PS','PC','XBOX') or site not in ('main','satellite','all'):
        raise ValueError('cohort_scope')
    if args['profile']!='FC27' and (platform!='all' or site!='main'):
        raise ValueError('cohort_generic_scope_unverified')
    if 'evidence_id' in args and (not isinstance(args['evidence_id'],str) or not re.fullmatch(r'cohort_[a-f0-9]{24}',args['evidence_id'])):raise ValueError('cohort_evidence_id')
    if args.get('action','read') not in ('read','create','refresh','pause','resume','cancel'):raise ValueError('cohort_action')
    days=args.get('window_days',30)
    if type(days) is not int or days not in (7,14,30):raise ValueError('cohort_window')
    return dict(args,platform=platform,site_group=site,window_days=days)


def tool_schema():
    result={'type':'function','function':{'name':'mcp__fcro__fc_query_cohort_observation','description':'Read ES-new-flagged paid customer groups by selected exact game, linked to Admin orders by order hash and private site-local UID. Generic games currently main site only, platform all; FC27 retains existing filters. No-uid orders excluded with coverage. Not verified historical first purchases, causal or net settled retention. Default read may start one bounded read on a cache miss but never starts ongoing monitoring; aggregate only.',
        'parameters':{'type':'object','properties':{'profile':{'type':'string','enum':list(GAME_IDS)},'start':{'type':'string'},'end':{'type':'string'},'platform':{'type':'string','enum':['all','PS','PC','XBOX']},'site_group':{'type':'string','enum':['main','satellite','all']},'evidence_id':{'type':'string','description':'Optional exact immutable aggregate returned by FS workspace; reuse that archive instead of a new capture'},'action':{'type':'string','enum':['read','create','refresh','pause','resume','cancel'],'description':'Default read never starts monitoring. Only explicit user requested create starts daily monitoring; refresh reads once; pause/cancel stop next automatic reads.'}},'required':['profile','start','end'],'additionalProperties':False}}}
    result['function']['parameters']['properties']['window_days']={'type':'integer','enum':[7,14,30],'description':'Requested maximum observation days; default 30; monitor stops at this mature cutoff'}
    result['function']['parameters']['properties']['action']={'type':'string','enum':['read'],'description':'Model tools are read-only. A cache miss may start one aggregate read, never a daily monitor. Create/refresh/pause/resume/cancel are explicit authenticated workspace admin actions.'}
    return result


class CohortReader:
    def __init__(self,detail):
        self.detail=detail
        self.root=Path(detail.cache)/'cohort-observations'
        self.lock=threading.RLock();self.jobs={};self.finished={}

    def monitor(self,key):
        path=self.root/(key+'.monitor.json')
        return json.loads(path.read_text('utf-8')) if path.exists() else None

    def run(self,q,key):
        from fc_detail import atomic
        try:
            result=self.capture(q,key)
            status=result['status']
            return result
        except Exception:
            status='failed'
            raise
        finally:
            with self.lock:
                state=self.monitor(key)
                if state:
                    done=datetime.now(SHANGHAI).date()-timedelta(days=1)>=date.fromisoformat(q['end'])+timedelta(days=q['window_days'])
                    if state['state']=='active':
                        state.update(state='active' if status=='pending' else ('completed' if status=='available' else 'needs_review') if done else 'active',next_due=(datetime.now(timezone.utc)+timedelta(seconds=3 if status=='pending' else 86400)).isoformat())
                    state['last_status']=status
                    atomic(self.root/(key+'.monitor.json'),state)

    def capture(self,q,key):
        from fc_detail import atomic
        from cohort_es_source import archive_for,join_paid
        es=archive_for(self.detail,q)
        if es['status'] in ('pending','unavailable'):return es
        cutoff=min(datetime.now(SHANGHAI).date()-timedelta(days=1),date.fromisoformat(q['end'])+timedelta(days=q['window_days']))
        source_q={'start':q['start'],'end':cutoff.isoformat(),'period':{'start':q['start']+' 00:00','end':(cutoff+timedelta(days=1)).isoformat()+' 00:00'}}
        if q['profile']=='FC27':
            data=self.detail.reader(source_q,self.detail.config)
        else:
            from cohort_paid_source import read_service
            data=read_service({'profile':q['profile'],'start':q['start'],'end':cutoff.isoformat()})
        coverage=data.get('coverage',{})
        if coverage.get('period')!=source_q['period'] or coverage.get('paid_complete') is not True or coverage.get('missing_payment_time') or coverage.get('missing_days'):
            raise ValueError('cohort_paid_source_incomplete')
        rows=[r for r in data['orders'] if r['site_group'] in ('main','satellite') and (q['site_group']=='all' or r['site_group']==q['site_group']) and (q['platform']=='all' or r['platform']==q['platform'])]
        rows,linked=join_paid(rows,es,q)
        # Incomplete ES files or contradictory identities/timestamps cannot
        # establish anchors. Isolated unmatched orders and missing customer
        # keys instead narrow the observed subset and must stay visible.
        if (es.get('status')!='available' or linked['conflicting_order_identities'] or
            linked['payment_day_mismatches'] or linked['es_new_marked_paid_orders'] and
            not linked['stable_es_new_marked_paid_orders']):
            return {'kind':'cohort_observation','contract':CONTRACT,'status':'partial','reason':'es_paid_link_incomplete_not_frozen','members':None,'windows':[],'coverage':linked,'persisted':False}
        result=update(self.root/'observations.db',key,q['start'],q['end'],rows,complete_through=cutoff.isoformat(),source_complete=True,source_version=data['snapshot_id'])
        result['coverage'].update(linked)
        result['definition']='ES新客标记付费订单中可稳定关联客户的观察子群；非全部新客、全站新客cohort或已验证首购'
        result['coverage']['member_basis']='获取窗内ES新客标记与Admin付费订单成功匹配，且有稳定站点内客户键；未匹配订单和缺身份订单不作为未复购计入'
        result['coverage'].update(source_paid_complete=True,
            source_complete_basis='Admin付费订单获取窗至完整日的读取覆盖；不表示全部订单匹配ES或具有稳定客户身份',
            source_status=data.get('data_status'),unknown_scope_orders=coverage.get('unknown_scope_orders',0),excluded_distribution_orders=coverage.get('excluded_distribution_orders',0),current_backlog_status=coverage.get('backlog_status','unknown'))
        if not linked['link_complete'] or linked['excluded_identity_orders'] or coverage.get('unknown_scope_orders'):
            result['status']='partial'
        result.update(query=q,scope={'profile':q['profile'],'site_group':q['site_group'],'platform':q['platform'],'customer_identity':'site-local; never merged across sites'},captured_at=data['as_of'])
        result['windows']=[w for w in result['windows'] if w['days']<=q['window_days']]
        result['evidence_id']='cohort_'+hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()[:24]
        result['archive_id']=key
        evidence=self.root/'evidence'/(result['evidence_id']+'.json')
        if not evidence.exists():atomic(evidence,result)
        # Publish only the evidenced aggregate for this fixed subset; private SQLite never reaches model/UI.
        atomic(self.root/(key+'.aggregate.json'),result)
        return result

    def get(self,args,refresh=False,create=False,action=None):
        from fc_detail import atomic
        q=checked_query(args)
        action=action or q.pop('action',None)
        if action=='read':action=None
        if action in ('create','refresh','resume'):create=True
        if self.detail.config.get('enabled') is not True:
            return {'status':'unavailable','reason':'fc_detail_disabled'}
        if any(p.is_symlink() for p in (self.root,*self.root.parents)):raise ValueError('cohort_linked_root')
        if 'evidence_id' in q:
            evidence_id=q.pop('evidence_id')
            file=self.root/'evidence'/(evidence_id+'.json')
            if not file.exists():return {'status':'unavailable','reason':'cohort_evidence_missing'}
            result=json.loads(file.read_text('utf-8'))
            if result.get('query')!=q or result.get('evidence_id')!=evidence_id:raise ValueError('cohort_evidence_scope')
            core={k:v for k,v in result.items() if k not in ('evidence_id','archive_id')}
            if 'cohort_'+hashlib.sha256(json.dumps(core,sort_keys=True).encode()).hexdigest()[:24]!=evidence_id:raise ValueError('cohort_evidence_integrity')
            return result
        identity={'query':q,'config':self.detail.config,'contract':CONTRACT}
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.is_symlink():raise ValueError('cohort_linked_root')
        file=self.root/(key+'.aggregate.json');previous=None
        if file.exists():previous=json.loads(file.read_text('utf-8'))
        with self.lock:
            monitor=self.monitor(key)
            if action:
                if action not in ('create','refresh','pause','resume','cancel'):raise ValueError('cohort_action')
                if action in ('pause','resume','cancel') and monitor is None:raise ValueError('cohort_not_started')
                if monitor is None and action in ('create','resume'):
                    if len(list(self.root.glob('*.monitor.json')))>=32:return {'status':'unavailable','reason':'cohort_registry_capacity'}
                    monitor={'state':'active','frequency_seconds':86400,'window_days':q['window_days'],'next_due':datetime.now(timezone.utc).isoformat(),'query':q}
                if action in ('pause','cancel'):monitor.update(state='paused' if action=='pause' else 'cancelled',next_due=None)
                if action=='resume':monitor.update(state='active',next_due=datetime.now(timezone.utc).isoformat())
                if monitor is not None:atomic(self.root/(key+'.monitor.json'),monitor)
                if action in ('pause','cancel'):return {'status':'available','monitor':monitor,'previous':previous,'inflight_note':'already running read may finish; no next automatic read'}
            if previous:
                previous['monitor']=monitor
                if monitor and monitor.get('last_status') in ('failed','partial'):
                    previous.update(status='partial',retained_previous=True,last_attempt_status=monitor['last_status'])
        # A plain read is a one-shot capture on a cache miss, never a monitor registration.
        # Inspect the job before a prior aggregate: an explicit refresh may be in flight.
        with self.lock:
            job=self.jobs.get(key);now=time.monotonic()
            if job and job[0].done():
                age=now-self.finished.get(key,job[1])
                try:
                    result=job[0].result()
                    if result.get('status')=='pending':
                        if age<result.get('retryAfter',3):return dict(result,monitor=self.monitor(key),previous=previous,archive_id=key)
                    elif result.get('status')=='available':
                        if age<30 or not refresh and age<900:return dict(result,monitor=self.monitor(key),archive_id=key)
                    elif age<60:
                        return dict(result,monitor=self.monitor(key),previous=previous,archive_id=key,retryAfter=max(1,round(60-age)))
                except Exception:
                    if age<60:return {'status':'unavailable','reason':'cohort_source_failed','retryAfter':max(1,round(60-age)),'archive_id':key,'previous':previous}
            elif job:return {'status':'pending','retryAfter':3,'previous':previous,'archive_id':key,'monitor':monitor}
            if not create and previous:return previous
            if not refresh and previous and datetime.now(timezone.utc)-datetime.fromisoformat(previous['captured_at'])<timedelta(minutes=15):return previous
            # Publish the query identity before returning an id while the pool is full.
            atomic(self.root/(key+'.query.json'),q)
            if sum(not f.done() for f,_ in self.jobs.values())>=2:return {'status':'pending','retryAfter':10,'reason':'cohort_queue_capacity','previous':previous,'archive_id':key}
            future=self.detail.pool.submit(self.run,q,key)
            self.jobs[key]=(future,now)
            future.add_done_callback(lambda _done,k=key:self.finished.__setitem__(k,time.monotonic()))
        return {'status':'pending','retryAfter':3,'previous':previous,'monitor':monitor,'archive_id':key}

    def get_id(self,key):
        if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{64}',key):raise ValueError('cohort_archive_id')
        path=self.root/(key+'.query.json')
        if not path.exists():return {'status':'unavailable','reason':'observation_not_started'}
        q=json.loads(path.read_text('utf-8'))
        if checked_query(q)!=q or hashlib.sha256(json.dumps({'query':q,'config':self.detail.config,'contract':CONTRACT},sort_keys=True).encode()).hexdigest()!=key:
            raise ValueError('cohort_archive_scope')
        return self.get(q,create=False)

    def tick(self):
        """One due group per existing service tick; work runs on the existing pool."""
        if self.detail.config.get('enabled') is not True:return
        with self.lock:
            if any(not f.done() for f,_ in self.jobs.values()):return
            for path in sorted(self.root.glob('*.monitor.json')):
                state=json.loads(path.read_text('utf-8'))
                if state.get('state')=='active' and datetime.fromisoformat(state['next_due'])<=datetime.now(timezone.utc):
                    self.get(state['query'],refresh=True,create=True)
                    return


READERS={}
LOCK=threading.Lock()


def reader_for(detail):
    with LOCK:
        if id(detail) not in READERS:READERS[id(detail)]=CohortReader(detail)
        return READERS[id(detail)]


def refresh_registered(detail):
    """Existing scheduler entry: sequential bounded refresh, no model calls."""
    reader=reader_for(detail);results=[]
    for path in sorted(reader.root.glob('*.monitor.json')):
        state=json.loads(path.read_text('utf-8'))
        if state.get('state')!='active':continue
        q=checked_query(state['query'])
        value=reader.get(q,refresh=True,create=True)
        key=path.name.removesuffix('.monitor.json')
        job=reader.jobs.get(key)
        if job:
            try:value=job[0].result(timeout=950)
            except Exception:value={'status':'unavailable','reason':'cohort_source_failed'}
        results.append({'query':q,'status':value.get('status')})
    return results


if __name__=='__main__':
    import argparse
    from concurrent.futures import ThreadPoolExecutor
    from fc_detail import FCDetails
    parser=argparse.ArgumentParser(description='Refresh registered private cohort observations; aggregate stdout only')
    parser.add_argument('--config',required=True);parser.add_argument('--cache',required=True)
    args=parser.parse_args()
    with ThreadPoolExecutor(max_workers=1) as pool:
        detail=FCDetails(pool,args.cache,config=json.loads(Path(args.config).read_text('utf-8')))
        if detail.config.get('enabled') is not True:raise SystemExit('cohort_disabled')
        print(json.dumps(refresh_registered(detail),ensure_ascii=False))
