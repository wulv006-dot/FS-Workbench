"""Current RS backlog aggregates, separate from paid-date history; shared Admin session/pool."""
from datetime import datetime, timezone
from threading import RLock
import copy, json, sys, time
from rs_admin import selection, SITES, SERVERS, CATEGORIES

CONTRACT='rs-current-backlog-v1'
TTL=300

def collect(q):
    sys.path[:0]=['/opt/sales-dashboard/collector','/opt/fs-transaction-snapshot']
    import p2pah_auth as auth
    session=auth.Session();token,error=auth.admin_token_from_service()
    if error:raise OSError(error)
    session.bind_admin_token(token);del token
    deadline=time.monotonic()+85
    def read(params):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('rs_backlog_deadline')
        r=session.admin.request('GET',auth.ADMIN_API+'/admin/order.Order/index',params=params,
            headers={'batoken':session.token},timeout=min(30,remaining),allow_redirects=False)
        if r.status_code in (301,302,401,403):raise PermissionError('rs_backlog_denied')
        if r.status_code!=200 or len(r.content)>8*1024*1024:raise OSError('rs_backlog_unavailable')
        value=r.json()
        if value.get('code')!=1:raise ValueError('rs_backlog_contract')
        return value['data']
    try:return project(read,q)
    finally:session.close()

def project(read,q):
    filters=[('gid',506,'=')]
    # The current-list API ignores site_id with progress; filter verified websites after enumeration.
    for key,field,table in [('rs_server','aid',SERVERS),('rs_category','cid',CATEGORIES)]:
        if q[key]!='all':filters.append((field,table[q[key]][0],'='))
    metrics={}
    for name,rules in [('issues',[('pay_status',1,'='),('progress',9,'=')]),('unpaid',[('pay_status',0,'=')])]:
        seen={};expected=None;received=0
        try:
            for page in range(1,301):
                params={'page':page,'limit':100,'order':'id,desc'}
                for i,(field,value,op) in enumerate(filters+rules):
                    params.update({f'search[{i}][field]':field,f'search[{i}][val]':value,f'search[{i}][operator]':op})
                value=read(params);rows=value.get('list');total=value.get('total')
                if type(total) is not int or total<0 or not isinstance(rows,list) or len(rows)>100 or expected is not None and expected!=total:raise ValueError('rs_backlog_pagination_changed')
                expected=total
                for row in rows:
                    identity=row.get('id')
                    if type(identity) is not int or identity<=0 or str(row.get('gid'))!='506':raise ValueError('rs_backlog_scope')
                    if type(row.get('site_id')) is not int or row['site_id']<=0:raise ValueError('rs_backlog_site')
                    valid=(str(row.get('pay_status'))=='1' and row.get('status')==91) if name=='issues' else (str(row.get('pay_status'))=='0' and any(t in str(row.get('status_format','')) for t in ('未支付','待支付','未付款','待付款')))
                    if not valid:raise ValueError('rs_backlog_status_mismatch')
                    signature=json.dumps(row,sort_keys=True)
                    if identity in seen and seen[identity][0]!=signature:raise ValueError('rs_backlog_conflicting_order')
                    seen[identity]=(signature,row['site_id'])
                received+=len(rows)
                if received==total:break
                if not rows or received>total:raise ValueError('rs_backlog_incomplete')
            else:raise ValueError('rs_backlog_page_budget')
            count=sum(q['rs_site']=='all' or site==SITES[q['rs_site']][0] for _,site in seen.values())
            metrics[name]={'value':count,'status':'available','sourceTotal':expected,'duplicates':received-len(seen)}
        except PermissionError:raise
        except (ValueError,OSError,TimeoutError):
            # Do not publish ES candidate totals when the returned current states disagree.
            metrics[name]={'value':None,'status':'unavailable','error':'current_status_not_verified'}
    return {'contractId':CONTRACT,'selection':q,'asOf':datetime.now(timezone.utc).isoformat(),
            'basis':'current_no_payment_date_filter','metrics':metrics,'refreshSeconds':TTL}

class RSBacklog:
    def __init__(self,pool,reader=collect,clock=time.monotonic):
        self.pool,self.reader,self.clock=pool,reader,clock
        self.lock,self.entries=RLock(),{}
    def capture(self,key,q,entry):
        try:
            value=self.reader(q)
            if value.get('contractId')!=CONTRACT or value.get('selection')!=q:raise ValueError('rs_backlog_contract')
            with self.lock:entry.update(data=value,at=self.clock(),state='available')
        except PermissionError:
            with self.lock:entry.update(data=None,state='denied',at=self.clock())
        except Exception:
            with self.lock:entry.update(state='failed',at=self.clock())
    def get(self,params):
        if set(params)-{'mode','profile','rs_site','rs_server','rs_category','refresh'} or any(len(v)!=1 for v in params.values()) or params.get('mode')!=['rs-backlog'] or params.get('profile')!=['RS'] or params.get('refresh',['true'])!=['true']:raise ValueError('invalid_rs_backlog_parameters')
        q=selection({k:v[0] for k,v in params.items()});key=json.dumps(q,sort_keys=True)
        with self.lock:
            now=self.clock();entry=self.entries.get(key)
            if entry is None:
                if len(self.entries)>=80:
                    victim=next((k for k,v in self.entries.items() if v['state']!='pending'),None)
                    if victim is None:return 429,{'status':'pending','retryAfter':3}
                    self.entries.pop(victim)
                entry=self.entries[key]={'state':'new','at':-float('inf'),'data':None}
            fresh=entry['state']=='available' and 0<=now-entry['at']<TTL
            if entry['state']=='denied' and now-entry['at']<30:return 403,{'status':'denied'}
            due=not fresh or params.get('refresh')==['true']
            if due and entry['state']!='pending' and (entry['state']=='new' or now-entry['at']>=30):
                if sum(v['state']=='pending' for v in self.entries.values())>=2:return 429,{'status':'pending','retryAfter':3}
                entry['state']='pending';self.pool.submit(self.capture,key,q,entry)
            data=copy.deepcopy(entry['data'])
            if data is None:return (503 if entry['state']=='failed' else 202),{'status':entry['state'],'retryAfter':3}
            data.update(status='available',refreshing=entry['state']=='pending',refreshError=entry['state']=='failed',stale=not fresh)
            return 200,data
