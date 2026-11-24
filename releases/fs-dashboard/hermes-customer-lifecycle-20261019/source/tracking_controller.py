"""Administrator-only FS adapter for a private Admin-session read capability."""
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import threading
import time
from urllib.error import HTTPError

from customer_tracking import AdminService, Store, ID

KEY_FILE=Path(os.environ.get('FS_CUSTOMER_TRACKING_KEY_FILE','/var/lib/fs-hermes-fc/private/customer-tracking.key'))
SHANGHAI=timezone(timedelta(hours=8))


def scan_permission_denied(job):
    return bool(job and job['state']=='failed' and job.get('reason')=='es_export_permission_denied')


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

def private_key(path=KEY_FILE):
    info=Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=65:raise PermissionError('tracking_key_integrity')
    if os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):raise PermissionError('tracking_key_permissions')
    value=Path(path).read_text('ascii').strip()
    if not re.fullmatch('[a-f0-9]{64}',value):raise PermissionError('tracking_key_format')
    return value

class PrivateClient:
    def __init__(self,key_file=KEY_FILE):
        self.key_file=key_file;self.reads=None;self.lock=threading.RLock()
    def read(self,body):
        raw=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        if len(raw)>4096:raise ValueError('private_query_size')
        key=private_key(self.key_file)
        with self.lock:
            if self.reads is None:
                from tracking_private_session import direct_reads
                self.reads=direct_reads(self.key_file)
        if not self.reads.authorized(key):raise PermissionError('tracking_key_integrity')
        value=self.reads.execute(body)
        if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>4*1024*1024:raise ValueError('private_result_size')
        return value

    @contextmanager
    def permission_scan_recovery(self,body):
        key=private_key(self.key_file)
        with self.lock:
            reads=self.reads
            if reads is None:
                yield lambda:None
                return
            with reads.lock:
                if not reads.authorized(key):raise PermissionError('tracking_key_integrity')
                fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                job=reads.jobs.get(fingerprint)
                if job is None:
                    yield lambda:None
                    return
                if not job['future'].done() or not job.get('observed'):raise ValueError('private_scan_recovery_unobserved')
                try:result=job['future'].result()
                except Exception:raise ValueError('private_scan_recovery_not_permission_denied') from None
                if (result.get('reason')!='es_export_permission_denied' or result.get('status') not in ('unavailable','failed')
                        or result.get('stage','not_generated')!='not_generated'):
                    raise ValueError('private_scan_recovery_not_permission_denied')
                yield lambda:reads.jobs.pop(fingerprint)


def recovered_es_receipt(day,expected_sha,root):
    from es_order_structure import checked_query,_receipt_paths,_read_receipt,SERVER_LOCK
    if not isinstance(expected_sha,str) or not re.fullmatch('[a-f0-9]{64}',expected_sha):raise ValueError('scan_recovery_es_sha')
    root=Path(root)
    if any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('es_cache_symlink')
    query=checked_query({'profile':'ALL','start':day,'end':day})
    with SERVER_LOCK:
        index,attempt,legacy=_receipt_paths(query,root)
        record,actual_sha=_read_receipt(index)
        if actual_sha!=expected_sha:raise ValueError('scan_recovery_es_receipt_changed')
        if any(p.exists() or p.is_symlink() for p in (attempt,legacy)):raise ValueError('scan_recovery_es_attempt_unknown')
        value=record.get('value') or {};denial=record.get('permission_denial') or {}
        original=denial.get('result') or {}
        if (record.get('last_attempt') or value.get('status')!='available' or original.get('reason')!='es_export_permission_denied'
                or original.get('stage') not in (None,'not_generated')
                or not re.fullmatch('[a-f0-9]{64}',str(denial.get('receipt_sha256','')))):
            raise ValueError('scan_recovery_es_not_rechecked')
        snapshots=value.get('snapshots')
        if not isinstance(snapshots,list) or len(snapshots)!=1 or checked_query(snapshots[0]['query'])!=query:
            raise ValueError('scan_recovery_es_query')
        projection=snapshots[0]['value'];quality=projection.get('quality') or {}
        if (value.get('kind')!='es_order_structure_bundle' or projection.get('kind')!='es_order_structure'
                or projection.get('status')!='available' or quality.get('file_set_complete') is not True
                or quality.get('parse_failures')!=0 or quality.get('failed_files')!=0
                or type(quality.get('declared_files')) is not int or quality['declared_files']!=quality.get('read_files')
                or not re.fullmatch('[a-f0-9]{64}',str(projection.get('source_version','')))):
            raise ValueError('scan_recovery_es_incomplete')
        return dict(receipt_sha256=actual_sha,query=query,original_denial_sha256=denial['receipt_sha256'],
                    source_version=projection['source_version'],captured_at=projection.get('captured_at'))

class TrackingController:
    def __init__(self,root,authorizer,client=None,auto_start=True,conversation=None):
        self.store=Store(root);self.admin=AdminService(self.store,authorizer)
        self.client=client or PrivateClient()
        if conversation is not None:
            from pool_reports import PoolReports
            self.reports=PoolReports(conversation,self.store)
            self.report_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='customer-reports')
            self.report_future=None
        else:self.reports=None
        from vip_maintenance import VipMaintenance
        self.vip = VipMaintenance(self.store)
        self.maintenance = None
        self.phase_lock = threading.Lock()
        if auto_start:
            threading.Thread(target=self._vip_loop,name='fs-vip-maintenance',daemon=True).start()
            threading.Thread(target=self._daily_loop,name='fs-customer-daily',daemon=True).start()
            operations = [('update', 60), ('reconcile', 30), ('update_effects', 3600)]
            if os.environ.get('FS_CUSTOMER_MAINTENANCE_DISPATCH') == '1':
                operations.append(('dispatch', 15))
            for name, interval in operations:
                threading.Thread(target=self._phase_loop, args=(name, interval),
                                 name='fs-customer-stage-' + name, daemon=True).start()

    def _queue_reports(self):
        # Reports are submitted only by an explicit generate_pool POST.
        return

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
        from tracking_tool import customer_snapshot
        value=customer_snapshot(detail)
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

    def resume_permission_scan(self,user,day,config_version,request_id,*,expected_job_sha256,es_receipt_sha256,
                               es_root=Path('/var/lib/fs-hermes-fc/fs/es-structures')):
        """Operator-only after the original ES receipt was successfully rechecked."""
        self.admin._admin(user)
        _,reused=self.store.permission_scan(day,config_version,request_id,expected_job_sha256,es_receipt_sha256)
        proof=recovered_es_receipt(day,es_receipt_sha256,es_root)
        if not reused:
            config=self.store.config()
            body={'action':'scan','day':day,'config':{k:v for k,v in config.items() if k not in ('version','last_request_id','enabled_profiles')}}
            with self.client.permission_scan_recovery(body) as discard_original_failure:
                self.store.resume_permission_scan(day,config_version,request_id,expected_job_sha256,proof,user)
                discard_original_failure()
        self._poll_scan(day)
        return self.store.scan_job(day)

    def _poll_history(self,tracking_id,max_age_seconds=900):
        detail=self.store.detail(tracking_id)
        if detail['status']!='active':return 'stopped'
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

    def _vip_loop(self):
        while True:
            try:
                self.vip.refresh()
            except Exception as error:
                logging.getLogger(__name__).error('VIP refresh failed: %s', type(error).__name__)
            time.sleep(60)

    def _daily_loop(self):
        while True:
            try:
                if datetime.now(SHANGHAI).hour>=7:
                    time.sleep(60);continue
                day=(datetime.now(SHANGHAI).date()-timedelta(days=1)).isoformat()
                config=self.store.config()
                if config['enabled']:
                    job=self.store.scan_job(day)
                    if job is None:
                        request_id=hashlib.sha256(f'auto:{day}:{config["version"]}'.encode()).hexdigest()[:32]
                        self.store.begin_scan(day,request_id)
                    elif job['state']=='failed' and not scan_permission_denied(job):
                        due=datetime.fromisoformat(job['updated_at'])+timedelta(minutes=15)
                        if datetime.now(timezone.utc)>=due:
                            request_id=hashlib.sha256(f'auto:{day}:{config["version"]}:{int(time.time()//900)}'.encode()).hexdigest()[:32]
                            self.store.begin_scan(day,request_id)
                    self._poll_scan(day)
                for pending_day in self.store.pending_scans():
                    if pending_day!=day:self._poll_scan(pending_day)
                for tracking_id in self.store.due_histories():
                    self._poll_history(tracking_id,max_age_seconds=0)
                self._queue_reports()
            except Exception:pass
            time.sleep(60)

    def get(self,user,params):
        if isinstance(params,dict) and 'stored_only' in params:
            from tracking_readonly import stored_get
            return stored_get(self,user,params)
        self.admin._admin(user)
        if not isinstance(params,dict) or params.get('mode')!=['hermes'] or params.get('structure')!=['customer_tracking'] or any(len(value)!=1 for value in params.values()):
            raise ValueError('tracking_query')
        view=params.get('view',[''])[0]
        allowed={'mode','structure','view'}
        if view.startswith('phase_'):
            return 200, self.phase_get(view, {key: value[0] for key, value in params.items() if key not in allowed})
        if view == 'vip_week' and set(params) <= allowed | {'week','scope'}:
            scope = params.get('scope', ['uk_us'])[0]
            if scope not in ('uk_us', 'global_preferred'):
                raise ValueError('vip_scope')
            return 200, self.vip.queue(week=params.get('week', [None])[0], actor=user, scope=scope)
        if view == 'vip_period':
            from vip_query import query
            from vip_followup import read_period
            return 200, query(read_period,
                              {key: val for key, val in params.items() if key not in allowed},
                              datetime.now(SHANGHAI))
        if view=='pool_reports':
            if set(params)!=allowed:raise ValueError('tracking_query')
            return 200,self.reports.listed(user) if self.reports else {'status':'unavailable','items':[]}
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
            if view == 'request':
                receipt = self.vip.lookup_receipt(user, params[field][0])
                if receipt is not None:
                    return 200, receipt
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
        action = body.get('action')
        if isinstance(action, str) and action.startswith('phase_'):
            return 200, self.phase_post(user, action, {key: value for key, value in body.items() if key not in ('kind','action')})
        if body.get('action') == 'vip_feedback':
            data = {key: val for key, val in body.items() if key not in ('kind', 'action')}
            return 200, self.vip.feedback(user, data)
        if body.get('action') == 'vip_bulk_claim':
            data = {key: val for key, val in body.items() if key not in ('kind', 'action')}
            return 200, self.vip.bulk_claim(user, data)
        if body.get('action')=='scan' and set(body)=={'kind','action','day','request_id'}:
            day=body['day'];request_id=body['request_id']
            if date.fromisoformat(day)>datetime.now(SHANGHAI).date():raise ValueError('future_scan')
            receipt=self.store.begin_scan(day,request_id)
            self._poll_scan(day)
            return 200,dict(receipt,**{'status':self.store.candidates(day)['status']})
        if body.get('action')=='generate_pool' and set(body)=={'kind','action','request_id'}:
            if self.reports is None:raise ValueError('report_service_unavailable')
            return 200,self.reports.generate(user,body['request_id'])
        value=self.admin.post(user,body)
        if body.get('action')=='track':
            value=dict(value,state='tracked',request_id=body['request_id'],
                history_status=self._poll_history(value['tracking_id']))
            self._queue_reports()
        return 200,value

    def phase(self):
        with self.phase_lock:
            if self.maintenance is None:
                from maintenance_service import Maintenance
                self.maintenance = Maintenance(self.store)
            return self.maintenance

    def _phase_loop(self, operation, interval):
        while True:
            try:
                getattr(self.phase(), operation)()
            except Exception as error:
                logging.getLogger(__name__).error('Customer stage %s failed: %s', operation, type(error).__name__)
            time.sleep(interval)

    def phase_get(self, view, fields):
        phase = self.phase()
        if view in ('phase_groups', 'phase_review', 'phase_ready', 'phase_delivery', 'phase_manual'):
            if set(fields) - {'offset'}:
                raise ValueError('maintenance_query')
            offset = fields.get('offset', '0')
            if not offset.isascii() or not offset.isdecimal() or len(offset) > 8:
                raise ValueError('maintenance_offset')
            if view == 'phase_groups':
                return phase.group_view(int(offset))
            return phase.queue_view(view[6:], int(offset))
        if view == 'phase_customer' and set(fields) == {'id'}:
            return phase.customer_view(fields['id'])
        if view == 'phase_effect' and set(fields) <= {'days'} and fields.get('days', '30') in ('7', '30', '60'):
            return phase.effect_view(int(fields.get('days', '30')))
        if fields:
            raise ValueError('maintenance_query')
        if view == 'phase_rules':
            return dict(items=phase.ledger.rules(), dispatch_enabled=os.environ.get('FS_CUSTOMER_MAINTENANCE_DISPATCH') == '1')
        if view == 'phase_config':
            return phase.config_view()
        raise ValueError('maintenance_query')

    def phase_post(self, user, action, data):
        self.admin._admin(user)
        from maintenance_service import keys, strict_id
        phase = self.phase()
        if action == 'phase_rule':
            return phase.save_rule(user, data)
        if action == 'phase_auto':
            keys(data, 'id enabled')
            if type(data['enabled']) is not bool:
                raise ValueError('maintenance_auto_flag')
            return dict(revision=phase.ledger.set_auto(strict_id(data['id']), data['enabled'], user, phase.clock))
        if action == 'phase_config':
            return phase.save_config(data)
        if action == 'phase_decide':
            return phase.decide_entries(user, data)
        if action == 'phase_result':
            return phase.manual_result(user, data)
        if action == 'phase_case':
            return phase.resolve_case(user, data)
        if action in ('phase_owner', 'phase_tier'):
            return phase.modify(user, action[6:], data)
        if action == 'phase_feedback':
            case_id = data.get('case_id')
            customer = data.pop('customer_id', None)
            view = phase.customer_view(customer)
            if not view['case'] or view['case']['case_id'] != case_id:
                raise ValueError('maintenance_case_mismatch')
            return self.vip.feedback(user, data)
        raise ValueError('maintenance_action')
