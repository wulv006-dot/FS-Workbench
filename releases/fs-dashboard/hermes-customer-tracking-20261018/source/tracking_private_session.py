"""Key-gated, bounded customer read jobs inside the existing Admin session.

Only the FS range service receives the key. The public capability endpoint must
never dispatch these operations or echo the key, email, or raw Admin responses.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

from customer_tracking import EMAIL, checked_config, game_scope
from tracking_source import admin_email_history, scan_day

KEY_FILE = Path(os.environ.get('FS_CUSTOMER_TRACKING_KEY_FILE','/run/secrets/fs-customer-tracking.key'))
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


def private_key(path=KEY_FILE):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=65:
        raise PermissionError('tracking_key_integrity')
    if os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):
        raise PermissionError('tracking_key_permissions')
    value=path.read_text('ascii').strip()
    if not re.fullmatch('[a-f0-9]{64}',value):raise PermissionError('tracking_key_format')
    return value


class PrivateReads:
    def __init__(self,manager,key_file=KEY_FILE):
        self.manager=manager;self.key_file=key_file
        self.lock=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='customer-private-read')
        self.jobs={}

    def authorized(self,header):
        try:key=private_key(self.key_file)
        except (OSError,ValueError,PermissionError):return False
        return isinstance(header,str) and hmac.compare_digest(header,key)

    def active(self):
        with self.lock:return sum(not job['future'].done() for job in self.jobs.values())

    def execute(self,body):
        if not isinstance(body,dict):raise ValueError('private_read_body')
        action=body.get('action')
        if action=='scan' and set(body)=={'action','day','config'}:
            if not isinstance(body['day'],str) or not DAY.fullmatch(body['day']):raise ValueError('private_scan_day')
            config=checked_config(body['config'])
            args=(body['day'],config)
        elif action=='history' and set(body)=={'action','email','profile','start','end'}:
            email=body['email']
            if not isinstance(email,str) or len(email)>254 or not EMAIL.fullmatch(email):raise ValueError('private_history_email')
            if body['profile']!='FC27':raise ValueError('phase_one_fc_only')
            game_scope(body['profile'])
            args=(email,body['profile'],body['start'],body['end'])
        else:raise ValueError('private_read_action')
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            now=time.monotonic()
            for key,job in list(self.jobs.items()):
                if job['finished'] is not None and (job['status']=='pending' or now-job['finished']>(900 if job['status']=='available' else 60)):
                    del self.jobs[key]
            job=self.jobs.get(fingerprint)
            if job is None:
                if any(not existing['future'].done() for existing in self.jobs.values()):
                    return {'status':'pending','reason':'private_read_busy','retryAfter':5}
                if len(self.jobs)>=8:
                    oldest=min(self.jobs,key=lambda key:self.jobs[key]['finished'] or float('inf'))
                    del self.jobs[oldest]
                with self.manager.lock:
                    token=self.manager.token
                    if not self.manager.identity_ok(token,timeout=10):
                        return {'status':'unavailable','reason':'existing_auth_unavailable'}
                def run():
                    request=lambda path,timeout:self.manager.request(path,token=token,timeout=min(timeout,10))
                    if action=='scan':
                        from es_order_structure import session_bundle
                        from p2pah_session_service import HEADERS
                        day=args[0]
                        source=session_bundle(self.manager,{'profile':'ALL','start':day,'end':day},HEADERS)
                        if source.get('status')!='available':
                            return {'status':source.get('status','unavailable'),
                                    'reason':source.get('reason','es_daily_export_not_ready'),
                                    'retryAfter':source.get('retryAfter',5)}
                        return scan_day(request,*args)
                    return admin_email_history(request,*args)
                future=self.pool.submit(run)
                job={'future':future,'finished':None,'status':None}
                self.jobs[fingerprint]=job
                def finish(done):
                    with self.lock:
                        job['finished']=time.monotonic()
                        try:job['status']=done.result().get('status')
                        except Exception:job['status']='unavailable'
                future.add_done_callback(finish)
            future=job['future']
        if not future.done():return {'status':'pending','retryAfter':5}
        try:return future.result()
        except Exception:return {'status':'unavailable','reason':'private_source_unavailable'}
