"""Controller loaded by the existing FS process. No provider key enters Hermes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler

from pilot import TaskStore, SHANGHAI, digest, encoded, complete_week
from transport import Grants, Proxy, start_loopback, SAFE_MODEL_ERRORS
from fs_inprocess import gateway, approved_background, spending_hold
from fs_evidence import build_book,attach_owner_history
from report_validation import FORMAT, validate_output
from runs_contract import submission,validate_admission,run_path
from proxy_gateway import MAX_PROVIDER_WIRE_BYTES


def clean_hermes_question(value):
    # Hermes has an explicit user-authorized text policy; the legacy advisor stays independent.
    if not isinstance(value,str) or not 2 <= len(value.strip()) <= 600:
        raise ValueError('question_length')
    value=value.strip()
    if re.search(r'Bearer\s|password\s*[:=]|密码\s*[:：=]|Cookie\s*[:=]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|\b\d{10,}\b',value,re.I):
        raise ValueError('sensitive_question')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


@contextmanager
def admission_guard(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('linked_admission_lock')
    fd=os.open(str(path),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    locked=False
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or (os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077)):
            raise ValueError('admission_lock_boundary')
        try:
            if os.name=='posix':
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            else:
                import msvcrt
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            locked=True
        except OSError:pass
        yield locked
    finally:
        if locked:
            if os.name=='posix':
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_UN)
            else:
                import msvcrt
                os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
        os.close(fd)


def atomic(path,value,mode=0o640):
    path=Path(path)
    if path.is_symlink():raise ValueError('linked_result')
    temporary=path.with_name('.'+path.name+'.'+secrets.token_hex(4))
    try:
        with temporary.open('x',encoding='utf-8') as out:
            json.dump(value,out,ensure_ascii=False,sort_keys=True);out.flush()
            import os
            os.fsync(out.fileno())
        temporary.chmod(mode);temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()


class HermesService:
    def __init__(self,detail,daily,read_range,diagnostics,root,run_root,source_root,authorizer,clock=None):
        self.detail,self.daily,self.read_range,self.diagnostics=detail,daily,read_range,diagnostics
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.run_root=Path(run_root);self.source_root=Path(source_root);self.authorizer=authorizer
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.tasks=TaskStore(self.root/'tasks.sqlite3')
        self.grants=Grants();self.gateways={};self.tokens={};self.books={};self.lock=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='fs-hermes-controller')
        self.proxy=Proxy(self.grants,self.lookup,approved_background(self.source_root))
        self.server=None;self.thread=None
        with self.tasks.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,body TEXT,state TEXT,task_id TEXT,error TEXT,result TEXT,UNIQUE(owner,request_id));'
                             'CREATE TABLE IF NOT EXISTS evidence(task_id TEXT,evidence_id TEXT,content TEXT,PRIMARY KEY(task_id,evidence_id));')
            # A process restart cannot assume the old runtime/provider attempt stopped.
            db.execute("UPDATE requests SET state='NEEDS_RECONCILE',error='fs_process_restarted' WHERE state IN ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED')")

    def lookup(self,grant):
        with self.lock:
            item=self.gateways.get(grant.task_id)
        if item is None:raise PermissionError('task_not_attached')
        return item

    def start(self):
        if self.server is not None:raise ValueError('proxy_already_started')
        self.server,self.thread=start_loopback(self.proxy)

    def remote(self,method,path,body=None,idempotency=None):
        if not (path=='/v1/runs' or re.fullmatch(r'/v1/runs/run_[a-f0-9]{32}(?:/stop)?',path)):raise ValueError('runtime_route')
        key=(self.run_root/'api-key').read_text('ascii').strip()
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
        if idempotency:headers['Idempotency-Key']=idempotency
        request=Request('http://127.0.0.1:8941'+path,data=encoded(body).encode() if body is not None else None,headers=headers,method=method)
        with build_opener(NoRedirect).open(request,timeout=30) as response:
            raw=response.read(MAX_PROVIDER_WIRE_BYTES+1);status=response.status
        if len(raw)>MAX_PROVIDER_WIRE_BYTES:raise ValueError('runtime_response_size')
        return status,json.loads(raw)

    def get_job(self,owner,key):
        with self.tasks.db() as db:row=db.execute('SELECT * FROM requests WHERE id=? AND owner=?',(key,owner)).fetchone()
        if row is None:return None
        if row['state']=='ALIASED':
            with self.tasks.db() as db:canonical=db.execute("SELECT id FROM requests WHERE task_id=? AND state!='ALIASED' ORDER BY rowid LIMIT 1",(row['task_id'],)).fetchone()
            if not canonical:raise ValueError('canonical_request_missing')
            return self.get_job(owner,canonical[0])
        item=dict(row);item['body']=json.loads(item['body']);item['result']=json.loads(item['result']) if item['result'] else None
        if item['task_id']:
            task=self.tasks.get(item['task_id'],owner)
            item['run_id']=task['run_id'];item['task_state']=task['state']
            item['model_usage']=self.usage(item['task_id'],owner)
        return item

    def usage(self,task_id,owner):
        with self.daily.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_reservations'").fetchone():
                return {'status':'ledger_initializing','calls':None,'total_tokens':None,'estimated_microcny':None}
            rows=db.execute('SELECT m.state,m.content,r.policy FROM hermes_reservations r JOIN model_calls m ON m.fingerprint=r.fingerprint WHERE r.task=? AND r.owner=?',(task_id,owner)).fetchall()
        out={'calls':len(rows),'total_tokens':0,'reasoning_tokens':0,'estimated_microcny':0,'unknown_calls':0,'invalid_response_calls':0,'cost_basis':'public_peak_rate_estimate_not_invoice'}
        if any(json.loads(row['policy']).get('id')=='no-pilot-quotas-deepseek-direct-tokens-only-v1' for row in rows):out['estimated_microcny']=None
        for row in rows:
            if row['state'] not in ('succeeded','invalid_response'):out['unknown_calls']+=1;continue
            if row['state']=='invalid_response':out['invalid_response_calls']+=1
            receipt=json.loads(row['content']);out['total_tokens']+=receipt['usage']['total_tokens'];out['reasoning_tokens']+=receipt.get('reasoning_tokens',0);out['estimated_microcny'] = (out['estimated_microcny']+receipt['cost_microcny']) if out['estimated_microcny'] is not None and receipt['cost_microcny'] is not None else None
        if out['estimated_microcny'] is None:out['cost_basis']='amount_unknown_no_cny_invoice_or_fx'
        return out

    def update(self,key,**values):
        if set(values)-{'state','task_id','error','result'}:raise ValueError('request_update')
        if 'result' in values:values['result']=encoded(values['result'])
        with self.tasks.db() as db:
            db.execute('UPDATE requests SET '+','.join(k+'=?' for k in values)+' WHERE id=?',tuple(values.values())+(key,))

    def post(self,body,user,headers):
        if not user:return 401,{'error':'login_required'}
        if not self.authorizer(user):return 403,{'error':'admin_required'}
        with admission_guard(self.root/'admission.lock') as acquired:
            if not acquired:return 503,{'error':'release_in_progress'}
            result=self._post(body,user,headers,defer_submit=True)
        if len(result)==3:
            key,owner,value=result[2]
            # PREPARING is durable before releasing admission. A publisher which
            # wins here observes it and refuses, before the worker is scheduled.
            self.pool.submit(self.execute,key,owner,value)
            return result[0],self.get_job(owner,key)
        return result

    def _post(self,body,user,headers,defer_submit=False):
        if not user:return 401,{'error':'login_required'}
        if not self.authorizer(user):return 403,{'error':'admin_required'}
        if headers.get('X-FS-Advisor-Action')!='submit' or headers.get('Sec-Fetch-Site')!='same-origin':return 403,{'error':'same_origin_required'}
        if not isinstance(body,dict):return 422,{'error':'invalid_request'}
        if body.get('kind')=='hermes_cancel':
            if set(body)!={'kind','id'}:return 422,{'error':'cancel_fields'}
            task=None
            with self.lock:
                job=self.get_job(user,body['id'])
                if not job:return 404,{'error':'not_found'}
                if job['state'] in {'COMPLETED','FAILED','CANCELLED','NEEDS_RECONCILE'}:return 200,job
                self.update(job['id'],state='CANCEL_REQUESTED')
                if job['task_id']:
                    task=self.tasks.cancel(job['task_id'],user)
                    token=self.tokens.get(task['id'])
                    if token:self.grants.revoke(token)
            if task and task['run_id']:
                try:self.remote('POST',run_path(task['run_id'],'stop')['path'],{})
                except Exception:self.update(job['id'],error='stop_ack_unknown')
            return 202,self.get_job(user,job['id'])
        if set(body)!={'kind','request_id','start','end','question','mode'} or body['kind']!='hermes_report' or body['mode'] not in {'daily','investigation','kpi','pricing'}:
            return 422,{'error':'report_fields'}
        try:
            question=clean_hermes_question(body['question']);lo,hi=date.fromisoformat(body['start']),date.fromisoformat(body['end'])
            today=self.clock().astimezone(SHANGHAI).date()
            if lo.isoformat()!=body['start'] or hi.isoformat()!=body['end'] or hi>=today or lo>hi or (hi-lo).days>92:raise ValueError('complete_period')
            if not isinstance(body['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',body['request_id']):raise ValueError('request_id')
        except (ValueError,TypeError,KeyError):return 422,{'error':'invalid_period_or_question'}
        body=dict(body,question=question);key=digest({'owner':user,'request_id':body['request_id']})[:32]
        with self.tasks.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT body FROM requests WHERE owner=? AND request_id=?',(user,body['request_id'])).fetchone()
            if old:
                if old[0]!=encoded(body):return 409,{'error':'idempotency_conflict'}
                return 200,self.get_job(user,key)
            hold = spending_hold(self.daily, self.tasks, user)
            if hold:
                return 503, {'error': hold}
            db.execute("INSERT INTO requests VALUES(?,?,?,?,'PREPARING',NULL,NULL,NULL)",(key,user,body['request_id'],encoded(body)))
        if defer_submit:return 202,self.get_job(user,key),(key,user,body)
        self.pool.submit(self.execute,key,user,body)
        return 202,self.get_job(user,key)

    def get(self,params,user):
        if not user:return 401,{'error':'login_required'}
        if set(params)-{'mode','id','evidence'} or params.get('mode')!=['hermes'] or any(len(v)!=1 for v in params.values()):return 422,{'error':'invalid_parameters'}
        if 'id' in params:
            job=self.get_job(user,params['id'][0])
            if not job:return 404,{'error':'not_found'}
            if 'evidence' in params:
                ref=params['evidence'][0]
                if not re.fullmatch(r'ev_[a-f0-9]{24}',ref):return 422,{'error':'invalid_evidence'}
                with self.tasks.db() as db:row=db.execute('SELECT content FROM evidence WHERE task_id=? AND evidence_id=?',(job['task_id'],ref)).fetchone()
                return (200,json.loads(row[0])) if row else (404,{'error':'not_found'})
            return 200,job
        if 'evidence' in params:return 422,{'error':'evidence_task_required'}
        with self.tasks.db() as db:rows=db.execute("SELECT id,state,error,body FROM requests WHERE owner=? AND state!='ALIASED' ORDER BY rowid DESC LIMIT 20",(user,)).fetchall()
        hold = spending_hold(self.daily, self.tasks, user)
        return 200,{'contract':'hermes-fc-investigation-v2','can_generate':self.authorizer(user) and hold is None,
                    'admission': {'status': 'blocked' if hold else 'ready', 'reason': hold},
                    'items':[dict(r,body=json.loads(r['body'])) for r in rows],
                    'business_acceptance':'user_review_required','default_entry_replaced':False,'reasoning_policy':'analysis high; investigation/pricing max; no none fallback'}

    def execute(self,key,owner,body):
        task=None;token=None;session_id=None
        try:
            book=build_book(self.detail,self.daily,self.read_range,self.diagnostics,body['start'],body['end'],self.source_root,owner)
            book.background=self.proxy.background
            spec={'period':{'start':body['start'],'end_exclusive':(date.fromisoformat(body['end'])+timedelta(days=1)).isoformat(),'timezone':'Asia/Shanghai'},
                  'snapshot_id':book.capture_id,'template_version':'v3-1m-'+digest({k:v for k,v in body.items() if k!='request_id'})[:20],
                  'knowledge_version':book.skills['version'],'budget_policy_id':'existing-ledger-public-estimate'}
            with self.lock:
                if self.get_job(owner,key)['state']=='CANCEL_REQUESTED':self.update(key,state='CANCELLED');return
                task=self.tasks.create(owner,spec);lease=secrets.token_hex(16)
                if task['state']!='QUEUED':
                    self.update(key,state='ALIASED',task_id=task['id']);task=None;return
                self.tasks.reserve_dispatch(task['id'],owner,lease)
                self.update(key,state='DISPATCH_UNKNOWN',task_id=task['id'])
            attach_owner_history(book,self.tasks,owner)
            def save_evidence(value):
                with self.tasks.db() as db:db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?)',(task['id'],value['evidence_id'],encoded(value)))
            book.persist=save_evidence
            item_gateway=gateway(self.daily,self.tasks,book)
            effort='max' if body['mode'] in {'investigation','pricing'} else 'high'
            token=self.grants.mint(owner,task['id'],lease,reasoning_effort=effort)
            with self.lock:self.tokens[task['id']]=token;self.books[task['id']]=book;self.gateways[task['id']]=item_gateway
            request=submission(self.tasks.get(task['id'],owner));session_id=request['body']['session_id']
            admission={'session_id':session_id,'token':token,'model':item_gateway.budget.policy['model'],'reasoning_effort':effort,'ready':False,
                       'prompt':body['question']+'\n目标区间：'+body['start']+' 至 '+body['end']+'；快照：'+book.capture_id+'\n'+FORMAT}
            path=self.run_root/'admissions'/(session_id+'.json');atomic(path,admission)
            with self.lock:
                if self.get_job(owner,key)['state']=='CANCEL_REQUESTED':
                    self.tasks.change(self.tasks.get(task['id'],owner),'CANCELLED')
                    self.update(key,state='CANCELLED');return
            code,remote=self.remote('POST','/v1/runs',request['body'],request['headers']['Idempotency-Key'])
            run_id=validate_admission(code,remote)
            with self.lock:
                self.tasks.bind_run(task['id'],owner,lease,run_id)
                cancel=self.get_job(owner,key)['state']=='CANCEL_REQUESTED'
                if cancel:self.tasks.cancel(task['id'],owner)
                else:self.update(key,state='RUNNING')
            if cancel:
                self.grants.revoke(token)
                self.remote('POST',run_path(run_id,'stop')['path'],{})
            admission['ready']=True;atomic(path,admission)
            while True:
                job=self.get_job(owner,key);cancel=job['state']=='CANCEL_REQUESTED'
                if not cancel:self.grants.renew(token,owner,task['id'],lease)
                _,remote=self.remote('GET',run_path(run_id)['path'])
                state=remote.get('status')
                if state not in {'queued','running','stopping','waiting_approval'} and not self.proxy.active(task['id']):break
                time.sleep(2)
            with self.lock:
                if self.get_job(owner,key)['state']=='CANCEL_REQUESTED':
                    self.tasks.observe(task['id'],owner,lease,'cancelled',worker_stopped=True);self.update(key,state='CANCELLED');return
                if state!='completed':
                    self.tasks.observe(task['id'],owner,lease,state,worker_stopped=True)
                    safe_error = next((code for code in sorted(SAFE_MODEL_ERRORS) if
                        re.search(r'FC model request blocked: '+code+r'\b', str(remote.get('error', '')))), None)
                    self.update(key,state='NEEDS_RECONCILE' if state=='interrupted' else 'FAILED',error=safe_error or 'runtime_'+str(state));return
            result=validate_output(remote.get('output'),book)
            with self.lock:
                if self.get_job(owner,key)['state']=='CANCEL_REQUESTED':
                    self.tasks.observe(task['id'],owner,lease,'cancelled',worker_stopped=True);self.update(key,state='CANCELLED');return
                self.tasks.observe(task['id'],owner,lease,state,worker_stopped=True)
                task=self.tasks.get(task['id'],owner)
                self.tasks.change(task,'PARTIAL' if result['limitations'] else 'SUCCEEDED')
                result.update(reasoning_effort=effort,skills_version=book.skills['version'],skill_sha256=book.skills['sha256'],trace=book.trace,
                              model_usage=self.usage(task['id'],owner),run_id=run_id)
                self.update(key,state='COMPLETED',result=result)
        except Exception as error:
            code=str(error) if isinstance(error,(ValueError,PermissionError)) and re.fullmatch(r'[a-z_]{3,80}',str(error)) else 'controller_'+type(error).__name__
            state='NEEDS_RECONCILE' if task and self.tasks.get(task['id'],owner)['state'] in {'DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE'} else 'FAILED'
            self.update(key,state=state,error=code)
        finally:
            if token:self.grants.revoke(token)
            if session_id and self.get_job(owner,key)['state']!='NEEDS_RECONCILE':
                path=self.run_root/'admissions'/(session_id+'.json')
                if path.exists():path.unlink()
            if task:
                with self.lock:
                    self.tokens.pop(task['id'],None);self.gateways.pop(task['id'],None);self.books.pop(task['id'],None)
