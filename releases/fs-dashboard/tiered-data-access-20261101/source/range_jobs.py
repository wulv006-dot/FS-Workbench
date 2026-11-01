"""Opt-in bounded query engine for an existing host; no thread, timer or network client.

Jobs/cache/lock are injected host state. The fixtures use dictionaries. Production
must supply the existing durable job/snapshot adapter before enabling this module.
"""
from copy import deepcopy
import hashlib,hmac,json,time,uuid
from threading import RLock

from date_policy import PolicyError


def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


class Engine:
    def __init__(self,*,jobs,subscriptions,cache,authorize,secret,lock,clock=time.monotonic,cache_bytes=2*1024*1024):
        if not isinstance(secret,bytes) or len(secret)<32:raise ValueError('server_secret_required')
        self.jobs,self.subscriptions,self.cache=jobs,subscriptions,cache
        self.authorize,self.secret,self.lock,self.clock=authorize,secret,lock,clock
        self.cache_bytes=cache_bytes

    def grant(self,identity,query):
        value=self.authorize(identity,query)
        if not isinstance(value,dict) or any(not isinstance(value.get(k),str) or not value[k] for k in ('scope_hash','permission_epoch','policy_version')):
            raise PolicyError('permission_denied')
        if value['policy_version']!=query['policy_version']:raise PolicyError('policy_changed')
        return value

    def key(self,query,grant,watermark,source_contract):
        return hmac.new(self.secret,encode(['bounded-query-v1',query['filter_hash'],grant,watermark,source_contract]),'sha256').hexdigest()

    def submit(self,identity,plan,*,watermark,source_contract,ttl=600):
        if not plan.get('network_allowed') or not plan.get('slices') or plan.get('query',{}).get('grain')!='detail' or not isinstance(watermark,str) or not watermark or not source_contract or not 0<ttl<=600:
            raise PolicyError('query_host_contract')
        query=plan['query'];grant=self.grant(identity,query)
        key=self.key(query,grant,watermark,source_contract)
        with self.lock:
            # Authorization happens before cache/singleflight lookup.
            cached=self.cache.get(key)
            if cached and cached['expires']<=self.clock():self.cache.pop(key,None);cached=None
            job=self.jobs.get(key)
            if len(self.subscriptions)>=1000:raise PolicyError('job_capacity')
            if not job and len(self.jobs)>=32:raise PolicyError('job_capacity')
            if not job or job['status'] in ('cancelled','cancel_requested','failed') or job['status']=='complete' and not cached:
                job=dict(query=deepcopy(query),plan=deepcopy(plan),grant=deepcopy(grant),watermark=watermark,status='complete' if cached else 'queued',slice=0,cursor=None,
                         rows=deepcopy(cached['rows']) if cached else [],ids={},seen_cursors=[],requests=0,bytes=0,inflight=False,error=None,ttl=ttl,generation=uuid.uuid4().hex)
                self.jobs[key]=job
            handle=uuid.uuid4().hex
            self.subscriptions[handle]=dict(identity=identity,key=key,active=True)
            return handle

    def access(self,identity,handle):
        subscription=self.subscriptions.get(handle)
        if not subscription or subscription['identity']!=identity:raise PolicyError('permission_denied')
        job=self.jobs[subscription['key']]
        if self.grant(identity,job['query'])!=job['grant']:raise PolicyError('permission_denied')
        return subscription,job

    def status(self,identity,handle):
        with self.lock:
            sub,job=self.access(identity,handle)
            return dict(status=job['status'] if sub['active'] else 'cancelled',complete=sub['active'] and job['status']=='complete',rows_seen=len(job['rows']),requests=job['requests'],error=job['error'],watermark=job['watermark'])

    def cancel(self,identity,handle):
        with self.lock:
            sub,job=self.access(identity,handle);sub['active']=False
            if not any(s['active'] and s['key']==sub['key'] for s in self.subscriptions.values()):
                job['status']='cancel_requested' if job['inflight'] else 'cancelled'
            return dict(status='cancelled')

    def active(self,key,job):
        available=False
        for sub in self.subscriptions.values():
            if sub['key']!=key or not sub['active']:continue
            try:allowed=self.grant(sub['identity'],job['query'])==job['grant']
            except PolicyError:allowed=False
            if not allowed:sub['active']=False
            else:available=True
        return available

    def step(self,key,adapter):
        """One safe page boundary; existing host invokes this with a fixed adapter."""
        with self.lock:
            job=self.jobs[key]
            if job['inflight'] or job['status'] not in ('queued','running'):return
            if not self.active(key,job):job['status']='cancelled';return
            if job['requests']>=job['plan']['budget']['max_requests']:
                job.update(status='partial',error='budget_exhausted');return
            request=dict(job['plan']['slices'][job['slice']],cursor=job['cursor'],watermark=job['watermark'])
            job.update(status='running',inflight=True,requests=job['requests']+1)
        # No engine lock across source I/O; source session/limit locks belong to host.
        try:page=adapter(deepcopy(request))
        except Exception as error:
            with self.lock:
                job['inflight']=False
                if not self.active(key,job) or job['status']=='cancel_requested':job['status']='cancelled'
                else:
                    code=getattr(error,'code','source_error')
                    job.update(status='failed',error=code if code in ('source_auth','source_rate_limited','source_timeout','source_schema_changed','source_unstable') else 'source_error')
            return
        with self.lock:
            job['inflight']=False
            if not self.active(key,job) or job['status']=='cancel_requested':job['status']='cancelled';return
            try:self.accept(key,job,page)
            except (PolicyError,TypeError,ValueError,KeyError):job.update(status='failed',error='source_schema_or_consistency_error')

    def accept(self,key,job,page):
        if not isinstance(page,dict) or page.get('watermark')!=job['watermark'] or type(page.get('complete')) is not bool or not isinstance(page.get('rows'),list):raise PolicyError('source_unstable')
        if page['complete'] and not page['rows'] and page.get('confirmed_empty') is not True:raise PolicyError('source_empty_unconfirmed')
        cursor=page.get('next_cursor')
        if page['complete'] != (cursor is None) or cursor is not None and (not isinstance(cursor,str) or not cursor or cursor in job['seen_cursors']):raise PolicyError('source_unstable')
        new=[];ids=dict(job['ids'])
        for row in page['rows']:
            if not isinstance(row,dict) or set(row)-set(job['query']['fields']) or not isinstance(row.get('order_id'),str) or not row['order_id']:raise PolicyError('source_schema_changed')
            ident=row['order_id'];checksum=hashlib.sha256(encode(row)).hexdigest()
            if ident in ids:
                if ids[ident]!=checksum:raise PolicyError('source_unstable')
            else:ids[ident]=checksum;new.append(row)
        size=len(encode(new));budget=job['plan']['budget']
        if len(job['rows'])+len(new)>budget['max_rows'] or job['bytes']+size>min(budget['max_bytes'],8*1024*1024):
            job.update(status='partial',error='budget_exhausted');return
        job['rows'].extend(deepcopy(new));job['ids']=ids;job['bytes']+=size
        if cursor is not None:job['seen_cursors'].append(cursor);job['cursor']=cursor
        else:job['slice']+=1;job['cursor']=None;job['seen_cursors']=[]
        if job['slice']==len(job['plan']['slices']):
            job['status']='complete'
            size=len(encode(job['rows']))
            if size<=min(self.cache_bytes,8*1024*1024):
                while self.cache and sum(v['bytes'] for v in self.cache.values())+size>self.cache_bytes:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=dict(rows=deepcopy(job['rows']),bytes=size,expires=self.clock()+min(job['ttl'],30) if not job['rows'] else self.clock()+job['ttl'])

    def page(self,identity,handle,*,cursor=None,limit=100):
        if type(limit) is not int or not 1<=limit<=100:raise PolicyError('page_limit')
        with self.lock:
            sub,job=self.access(identity,handle)
            if not sub['active']:raise PolicyError('cancelled')
            if job['status']!='complete':raise PolicyError('result_not_complete')
            offset=0
            if cursor:
                try:
                    body,signature=cursor.rsplit('.',1)
                    if not hmac.compare_digest(signature,hmac.new(self.secret,body.encode(),'sha256').hexdigest()):raise ValueError()
                    value=json.loads(body)
                    if not isinstance(value,list) or len(value)!=4 or value[:3]!=[handle,sub['key'],job['generation']] or type(value[3]) is not int or value[3]<0:raise ValueError()
                    offset=value[3]
                except (ValueError,AttributeError):raise PolicyError('invalid_cursor') from None
            end=min(len(job['rows']),offset+limit)
            body=json.dumps([handle,sub['key'],job['generation'],end],separators=(',',':'))
            next_cursor=None if end==len(job['rows']) else body+'.'+hmac.new(self.secret,body.encode(),'sha256').hexdigest()
            return dict(data=deepcopy(job['rows'][offset:end]),next_cursor=next_cursor,complete=True,watermark=job['watermark'])
