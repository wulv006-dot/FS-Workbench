"""Candidate facade using an injected FS queue and authorized source callbacks."""
from copy import deepcopy
import json
import threading
import time
import secrets
from datetime import datetime
from urllib.error import HTTPError

from .capabilities import CONTRACT, SHANGHAI, checked_query, fulfillment_projection, result


def tool_schema():
    string = {'type':'string', 'pattern':r'^\d{4}-\d{2}-\d{2}$'}
    return {'type':'function', 'function':{
        'name':'mcp__fcro__fc_query_capability',
        'description':'Read FC27 main-site native loss/product samples or current Order fulfillment samples. Native/product require inclusive start/end dates (up to 31 days). Product supports page/pages/page_size/area_id/category_id/sort; fulfillment accepts only platform/pages/samples with no dates. Read coverage and unknown definitions before calculation. Closed inputs; no URLs, roles or raw identities.',
        'parameters':{'type':'object', 'additionalProperties':False, 'required':['kind','profile'],
            'properties':{'kind':{'type':'string','enum':['native_loss','product_sales','fulfillment_samples']},
                'profile':{'type':'string','enum':['FC27']}, 'start':string, 'end':string,
                'page':{'type':'integer','minimum':1,'maximum':1000}, 'pages':{'type':'integer','minimum':1,'maximum':3},
                'page_size':{'type':'integer','enum':[10,20,50,100]},
                'area_id':{'type':'integer','minimum':0,'maximum':999999999},
                'category_id':{'type':'integer','minimum':0,'maximum':999999999},
                'sort':{'type':'string','enum':['order_count,descending']},
                'platform':{'type':'string','enum':['all','PS','PC','XBOX','unknown']},
                'samples':{'type':'integer','minimum':1,'maximum':6}},
            'oneOf':[
                {'properties':{'kind':{'enum':['native_loss']}, **{k:False for k in
                    ('page','pages','page_size','area_id','category_id','sort','platform','samples')}},
                 'required':['start','end']},
                {'properties':{'kind':{'enum':['product_sales']},'platform':False,'samples':False},
                 'required':['start','end']},
                {'properties':{'kind':{'enum':['fulfillment_samples']}, **{k:False for k in
                    ('start','end','page','page_size','area_id','category_id','sort')}}}]}}}


def response_budget(value):
    """Keep the entire authorized projection; never discard rows to save context/cost."""
    from proxy_gateway import MAX_PROVIDER_WIRE_BYTES
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(raw)>MAX_PROVIDER_WIRE_BYTES:raise ValueError('capability_response_size')
    return deepcopy(value)


class CapabilityProvider:
    """No new executor/timer. The FS owner injects its existing shared queue.

    Keep last usable source evidence after a failed refresh; failed/queued is
    never converted to zero. Existing SourcePins can freeze each task query.
    """
    def __init__(self, config, pool, admin_read, order_read, task_key=None, clock=time.monotonic, date_clock=None):
        self.config, self.pool = config, pool
        if task_key is None:task_key = secrets.token_bytes(32)
        if not isinstance(task_key,bytes) or len(task_key)<32:raise ValueError('private_task_key')
        self.admin_read, self.order_read, self.task_key = admin_read, order_read, task_key
        self.date_clock = date_clock or (lambda:datetime.now(SHANGHAI))
        self.clock, self.lock, self.jobs, self.good, self.failures = clock, threading.RLock(), {}, {}, {}
        self.denied = {}

    def _read(self, args, q):
        if q['kind'] == 'fulfillment_samples':
            if self.order_read is None:return result(q,'not_available',reason='order_adapter_not_wired')
            value = fulfillment_projection(self.order_read(q), q, self.task_key)
        else:
            if self.admin_read is None:return result(q,'not_available',reason='admin_adapter_not_wired')
            # The callback returns this candidate's already-projected session-service
            # response. Never introduce a raw Admin proxy across the container boundary.
            value = self.admin_read(args)
            if (not isinstance(value,dict) or value.get('contract')!=CONTRACT or value.get('kind')!=q['kind'] or
                value.get('source_system')!='Admin' or value.get('readonly') is not True or
                value.get('scope')!={'project':'FC27','site':'www.mmoexp.com','admin_game_id':1327,'admin_site_id':266}):
                raise ValueError('admin_projected_contract')
            common = {'contract','kind','status','readonly','source_system','scope','query','timezone','captured_at','source_data_as_of','immutable_watermark','reason'}
            fields = {'endpoint','method','response_time','currency','source_orders','source_amount_usd','categories','loss_groups','peak','coverage','period_basis','rule'} if q['kind']=='native_loss' else {'endpoint','method','currency','rows','coverage','errors','period_basis','rule'}
            if set(value)-common-fields:raise ValueError('admin_projected_fields')
        http_status = 200 if value['status'] in ('available','partial') else 403 if value['status']=='denied' else 503
        return response_budget(dict(value,http_status=http_status))

    def _finish(self,args,q):
        try:value = self._read(args,q)
        except PermissionError:value = result(q,'denied',reason='source_denied',http_status=403)
        except HTTPError as error:
            value = result(q,'denied' if error.code in (401,403) else 'not_available',
                           reason='source_denied' if error.code in (401,403) else 'source_read_failed',http_status=error.code)
        except Exception:value = result(q,'not_available',reason='source_read_failed')
        return self.clock(),value

    def get(self, args):
        q = checked_query(args, self.config, self.date_clock())
        if not self.config.get('enabled'):return result(q,'not_available',reason='fc_detail_disabled')
        key = json.dumps(args, sort_keys=True, separators=(',',':'))
        with self.lock:
            now = self.clock(); cached = self.good.get(key); job = self.jobs.get(key)
            if job is not None and job.done():
                try:finished,value = job.result()
                except Exception:finished,value = now,result(q,'not_available',reason='source_read_failed')
                self.jobs.pop(key)
                if value['status'] in ('available','partial'):
                    self.good[key] = (finished,deepcopy(value));self.failures.pop(key,None);self.denied.pop(key,None)
                else:
                    self.failures[key] = (finished,deepcopy(value))
                    if value['status']=='denied':self.denied[key]=deepcopy(value)
                cached = self.good.get(key);job = None
            usable = cached and not (q['kind']!='fulfillment_samples' and q['ttl_seconds']==7200 and
                                    cached[1].get('query',{}).get('period')!=q['period'])
            if usable and key not in self.denied and 0 <= now-cached[0] < q['ttl_seconds']:
                return deepcopy(cached[1])
            failed = self.failures.get(key)
            if failed and 0 <= now-failed[0] < 60:
                if key in self.denied:return deepcopy(self.denied[key])
                if not usable:return deepcopy(failed[1])
                value = deepcopy(cached[1]);value['stale'] = True
                value['refresh_status'] = failed[1]['status'];value['refresh_reason'] = failed[1].get('reason')
                return value
            if job is None:self.jobs[key] = self.pool.submit(self._finish,deepcopy(args),q)
            if key in self.denied:return deepcopy(self.denied[key])
            if usable:
                value = deepcopy(cached[1]);value['stale'] = True;value['refresh_status'] = 'pending'
                return value
            return result(q,'pending',reason='source_read_running',retryAfter=3)
