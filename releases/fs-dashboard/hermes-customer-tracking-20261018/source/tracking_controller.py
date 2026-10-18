"""Administrator-only FS adapter for a private Admin-session read capability."""
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from customer_tracking import AdminService, Store, ID

SESSION_URL='http://127.0.0.1:8767/business/customer-tracking-private'
KEY_FILE=Path(os.environ.get('FS_CUSTOMER_TRACKING_KEY_FILE','/var/lib/fs-hermes-fc/private/customer-tracking.key'))
SHANGHAI=timezone(timedelta(hours=8))


def safe_client_failure(error):
    """Never persist a URL, key, email, order, or untrusted exception text."""
    if isinstance(error,HTTPError):
        return 'private_client_http_'+str(error.code) if error.code in (400,403,404,503) else 'private_client_http_unavailable'
    if isinstance(error,PermissionError) and str(error) in {
            'tracking_key_integrity','tracking_key_permissions','tracking_key_format'}:
        return 'private_client_key_unavailable'
    if isinstance(error,json.JSONDecodeError):return 'private_client_json_invalid'
    if isinstance(error,ValueError) and str(error)=='private_result_size':return 'private_client_result_size'
    if isinstance(error,TimeoutError):return 'private_client_timeout'
    if isinstance(error,OSError):return 'private_client_transport_unavailable'
    return 'private_client_unavailable'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def private_key(path=KEY_FILE):
    info=Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=65:raise PermissionError('tracking_key_integrity')
    if os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):raise PermissionError('tracking_key_permissions')
    value=Path(path).read_text('ascii').strip()
    if not re.fullmatch('[a-f0-9]{64}',value):raise PermissionError('tracking_key_format')
    return value

class PrivateClient:
    def __init__(self,url=SESSION_URL,key_file=KEY_FILE):
        if url!=SESSION_URL:raise ValueError('private_session_url')
        self.url=url;self.key_file=key_file
    def read(self,body):
        raw=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        if len(raw)>4096:raise ValueError('private_query_size')
        request=Request(self.url,data=raw,method='POST',headers={
            'Content-Type':'application/json','X-FS-Customer-Tracking-Key':private_key(self.key_file)})
        with build_opener(NoRedirect()).open(request,timeout=12) as response:
            data=response.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError('private_result_size')
            return json.loads(data)

class TrackingController:
    def __init__(self,root,authorizer,client=None,auto_start=True,conversation=None):
        self.store=Store(root);self.admin=AdminService(self.store,authorizer)
        self.client=client or PrivateClient()
        if conversation is not None:
            from customer_reports import CustomerReports
            self.reports=CustomerReports(conversation,self.store)
            self.report_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='customer-reports')
            self.report_future=None
        else:self.reports=None
        if auto_start:
            threading.Thread(target=self._daily_loop,name='fs-customer-daily',daemon=True).start()

    def _queue_reports(self):
        if self.reports is not None and (self.report_future is None or self.report_future.done()):
            self.report_future=self.report_pool.submit(self.reports.tick)

    def active_reports(self):
        return int(self.reports is not None and self.report_future is not None and not self.report_future.done())

    def tool_read(self,user,tracking_id):
        self.admin._admin(user)
        if not isinstance(tracking_id,str) or not ID.fullmatch(tracking_id):raise ValueError('tracking_id')
        detail=self.store.detail(tracking_id)
        if detail['owner']!=user:raise PermissionError('tracking_owner_required')
        refresh_status=self._poll_history(tracking_id)
        detail=self.store.detail(tracking_id)
        if detail['history_coverage'] is None:
            return {'status':'pending' if refresh_status=='pending' else 'unavailable',
                'tracking_id':tracking_id,'refresh_status':refresh_status,'retryAfter':5 if refresh_status=='pending' else None}
        from tracking_tool import anonymous_snapshot
        value=anonymous_snapshot(detail)
        value['refresh_status']=refresh_status
        value['stale']=refresh_status in ('pending','unavailable')
        return value

    def _poll_scan(self,day):
        job=self.store.scan_job(day)
        if job is None or job['state']!='pending':return
        config=self.store.config()
        if config['version']!=job['config_version']:return
        query={'action':'scan','day':day,'config':{key:value for key,value in config.items()
            if key not in ('version','last_request_id','enabled_profiles')}}
        try:result=self.client.read(query)
        except (OSError,ValueError,PermissionError) as error:
            result={'status':'unavailable','reason':safe_client_failure(error)}
        self.store.finish_scan(day,job['config_version'],result)

    def _poll_history(self,tracking_id,max_age_seconds=900):
        detail=self.store.detail(tracking_id)
        last=detail['history_observed_at']
        if last and (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()<max_age_seconds:
            return detail['history_coverage'].get('complete') and 'available' or 'partial'
        query={'action':'history','email':detail['email'],'profile':'FC27','start':None,'end':None}
        try:result=self.client.read(query)
        except (OSError,ValueError,PermissionError):
            self.store.note_history_attempt(tracking_id,'unavailable')
            return 'unavailable'
        state=result.get('status')
        if state in ('available','partial') and isinstance(result.get('orders'),list):
            self.store.observe(tracking_id,result['orders'],coverage=result.get('coverage'))
            self._queue_reports()
        state=state if state in ('available','partial','pending') else 'unavailable'
        self.store.note_history_attempt(tracking_id,state)
        return state

    def _daily_loop(self):
        while True:
            try:
                day=(datetime.now(SHANGHAI).date()-timedelta(days=1)).isoformat()
                config=self.store.config()
                if config['enabled']:
                    job=self.store.scan_job(day)
                    if job is None:
                        request_id=hashlib.sha256(f'auto:{day}:{config["version"]}'.encode()).hexdigest()[:32]
                        self.store.begin_scan(day,request_id)
                    elif job['state']=='failed':
                        due=datetime.fromisoformat(job['updated_at'])+timedelta(minutes=15)
                        if datetime.now(timezone.utc)>=due:
                            request_id=hashlib.sha256(f'auto:{day}:{config["version"]}:{int(time.time()//900)}'.encode()).hexdigest()[:32]
                            self.store.begin_scan(day,request_id)
                    self._poll_scan(day)
                for pending_day in self.store.pending_scans():
                    if pending_day!=day:self._poll_scan(pending_day)
                for tracking_id in self.store.due_histories():
                    self._poll_history(tracking_id,max_age_seconds=86400)
                self._queue_reports()
            except Exception:pass
            time.sleep(60)

    def get(self,user,params):
        self.admin._admin(user)
        if not isinstance(params,dict) or params.get('mode')!=['hermes'] or params.get('structure')!=['customer_tracking'] or any(len(value)!=1 for value in params.values()):
            raise ValueError('tracking_query')
        view=params.get('view',[''])[0]
        allowed={'mode','structure','view'}
        if view=='candidates':
            allowed.add('day')
            if set(params)!=allowed:raise ValueError('tracking_query')
            day=params['day'][0]
            self.admin._admin(user)
            self._poll_scan(day)
            value=self.store.candidates(day)
            value['day']=value.pop('date')
            return 200,value
        if view in ('detail','request'):
            field='id' if view=='detail' else 'request_id'
            allowed.add(field)
            if set(params)!=allowed or not ID.fullmatch(params[field][0]):raise ValueError('tracking_query')
            value=self.admin.get(user,view,id=params[field][0])
            if view=='detail':
                value['history_status']=self._poll_history(params[field][0])
                value=self.admin.get(user,view,id=params[field][0])|{'history_status':value['history_status']}
                value['orders']=[dict(row,status=row.pop('current_status',None)) for row in value['orders']]
                for node in value['milestones']:
                    if node['state'] in ('claimed','creating','dispatch_unknown','queued'):
                        node['state']='pending'
            return 200,value
        if set(params)!=allowed:raise ValueError('tracking_query')
        return 200,self.admin.get(user,view)

    def post(self,user,body):
        self.admin._admin(user)
        if not isinstance(body,dict) or body.get('kind')!='hermes_customer_tracking':raise ValueError('tracking_kind')
        if body.get('action')=='scan' and set(body)=={'kind','action','day','request_id'}:
            day=body['day'];request_id=body['request_id']
            if date.fromisoformat(day)>datetime.now(SHANGHAI).date():raise ValueError('future_scan')
            receipt=self.store.begin_scan(day,request_id)
            self._poll_scan(day)
            return 200,dict(receipt,**{'status':self.store.candidates(day)['status']})
        value=self.admin.post(user,body)
        if body.get('action')=='track':
            value=dict(value,state='tracked',request_id=body['request_id'],
                history_status=self._poll_history(value['tracking_id']))
            self._queue_reports()
        return 200,value
