"""One original operation, evidence-bound recovery. Default inspect; never sends model traffic."""
import argparse,contextlib,hashlib,json,os,pathlib,shutil,sqlite3,subprocess,tempfile
OP='8dd85cc4-32c3-4cb7-9af1-ae46dea6aa7a'; TASK='bfb3d4bc39111250646ade712860e3ae'; RUN='campaign_b731b300aa3dfb1c9aa0c88f29add897'; OWNER='wulv'; FP='bac27e35436f0d466b89098112808a14028305213b909372c26576e9221b768f'
CURL_SHA='8f406d8115fa235eb3d3e979e5f4d22a2319c8dac4ec1899f82b29f7abf4ca2d'; PROVIDER_SHA='681afc43b0a7ce6f3664b92b31cba2092ad029ec3cdbb14ea112557f757fe19a'
EXPECTED={'task':'501111824fc57aacea503dc04a9d429f8d20fe543a5f1aa95b9ec32eecacee72','recommendation':'54bb071fd49fb2b6c9d4d9c96fc39a06e79a75b25f50a161e353c1cf75622749','weekly':'631ab7cfa0454d71603dde7ad4f3f5b44f6ad3b21472d86ec0c5c8e6c6aafc89','call':'5fbff1e17d4a649d90054cf092f3e743a5af388615f729d2d87a74bdad80d8d5','reservation':'0bc699e44338225c4eaee1a90bb70901a243443a081cfbfdc77c7887a3af4ab9'}
TABLES={'task':('tasks','id',TASK),'recommendation':('campaign_recommendations','operation_id',OP),'weekly':('campaign_weekly_runs','operation_id',OP),'call':('model_calls','fingerprint',FP),'reservation':('hermes_reservations','fingerprint',FP)}
def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
@contextlib.contextmanager
def db(path,write=False):
 connection=sqlite3.connect(str(path) if write else 'file:'+str(path)+'?mode=ro',uri=not write,timeout=5);connection.row_factory=sqlite3.Row
 try:
  if not write:connection.execute('PRAGMA query_only=ON')
  with connection:yield connection
 finally:connection.close()
def rows(tasks,budget):
 result={}
 for file,kinds in ((tasks,('task','recommendation','weekly')),(budget,('call','reservation'))):
  with db(file) as conn:
   for name in kinds:
    table,key,value=TABLES[name];items=conn.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(value,)).fetchall()
    if len(items)!=1:raise ValueError('original_row_cardinality_'+name)
    result[name]=dict(items[0])
 return result

def proof():
 pid=int(subprocess.check_output(['systemctl','show','fs-business-range.service','-p','MainPID']).strip().partition(b'=')[2]);items=(pathlib.Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0');paths=[x[5:].decode() for x in items if x.startswith(b'PATH=')]
 if len(paths)!=1:raise ValueError('service_path_unavailable')
 binary=pathlib.Path(shutil.which('curl',path=paths[0])).resolve(strict=True)
 if str(binary)!='/usr/bin/curl' or hashlib.sha256(binary.read_bytes()).hexdigest()!=CURL_SHA:raise ValueError('curl_evidence_changed')
 provider=pathlib.Path('/opt/fs-hermes-fc/openai_provider.py')
 if hashlib.sha256(provider.read_bytes()).hexdigest()!=PROVIDER_SHA:raise ValueError('original_provider_evidence_changed')
 outcomes=[]
 for timeout in ('1799.999','1799.0','1800'):
  call=subprocess.run([str(binary),'--max-time',timeout,'--version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5);outcomes.append(call.returncode)
 if outcomes!=[2,2,0]:raise ValueError('local_argument_rejection_not_reproduced')
 return dict(curl_binary=str(binary),curl_sha256=CURL_SHA,provider_sha256=PROVIDER_SHA,service_pid=pid,zero_network_option_exit_codes=outcomes,network_operation='none',basis='old provider emits float max-time; curl rejects option before network; exact original row hashes bind the affected attempt')

def after_rows(before):
 out=json.loads(encoded(before));ref='curl-local-argument-recovery-'+OP
 correction=dict(evidence_ref=ref,previous_diagnostic_sha256=digest(before['call']['content']),premature_network_marker_preserved=True,confirmed_outcome='not_dispatched')
 receipt=dict(operation_id=OP,task_id=TASK,run_id=RUN,model='gpt-6.1-sol',reconciliation=correction)
 old=json.loads(before['call']['content'] or '{}');out['call']['state']='not_dispatched';out['call']['content']=encoded(dict(old,status='not_dispatched',provider_outcome='not_dispatched',reconciliation=correction))
 for name in ('recommendation','weekly'):
  old=json.loads(before[name]['result'] or '{}');out[name]['state']='unavailable';out[name]['result']=encoded(dict(old,status='unavailable',operation_id=OP,error='WEEKLY_HERMES_PROVIDER_UNAVAILABLE',provider_outcome='not_dispatched',receipt=receipt,reconciliation=correction))
 out['task']['state']='FAILED';out['task']['version']=before['task']['version']+1
 return out

def durable(file,value):
 raw=(encoded(value)+'\n').encode();fd=os.open(str(file)+'.tmp',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:os.write(fd,raw);os.fsync(fd)
 finally:os.close(fd)
 os.replace(str(file)+'.tmp',file)
 if os.name!='nt':
  fd=os.open(file.parent,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)

def check_scope(before):
 if before['task']['id']!=TASK or before['task']['owner']!=OWNER or before['task']['run_id']!=RUN or before['task']['state']!='NEEDS_RECONCILE' or before['task']['version']!=2 or before['task']['lease'] is not None:raise ValueError('task_scope_changed')
 for name in ('recommendation','weekly'):
  if before[name]['operation_id']!=OP or before[name]['owner']!=OWNER or before[name]['state']!='unknown':raise ValueError('campaign_scope_changed')
 if before['recommendation']['task_id']!=TASK or before['recommendation']['run_id']!=RUN or before['recommendation']['network_started']!=1:raise ValueError('recommendation_scope_changed')
 if before['reservation']['owner']!=OWNER or before['reservation']['task']!=TASK or before['reservation']['turn']!=0 or before['call']['state']!='unknown':raise ValueError('budget_scope_changed')

def cas(conn,name,before,after):
 table,key,value=TABLES[name];current=conn.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(value,)).fetchone()
 if current is None or digest(dict(current))!=digest(before):raise ValueError('row_cas_changed_'+name)
 changed={k:v for k,v in after.items() if v!=before[k]}
 if not changed:return
 # The transaction excludes competing database writers; bind all old fields as well.
 where=' AND '.join('"'+k+'" IS ?' for k in before)
 sql='UPDATE '+table+' SET '+','.join('"'+k+'"=?' for k in changed)+' WHERE '+where
 if conn.execute(sql,tuple(changed.values())+tuple(before.values())).rowcount!=1:raise ValueError('row_cas_failed_'+name)

def recover(tasks,budget,audit,*,apply=False,expected=EXPECTED,proof_provider=proof,checkpoint=lambda phase:None):
 audit=pathlib.Path(audit);journal_file=audit/'recovery.json'
 if any(p.is_symlink() for p in (audit,journal_file,*audit.parents)):raise ValueError('audit_path_linked')
 current=rows(tasks,budget)
 if journal_file.exists():
  journal=json.loads(journal_file.read_text());before,after=journal['before'],journal['after']
  if journal.get('operation_id')!=OP or journal.get('expected')!=expected or {k:digest(v) for k,v in before.items()}!=expected:raise ValueError('audit_binding_changed')
  check_scope(before)
  if after!=after_rows(before):raise ValueError('audit_after_changed')
 else:
  if {k:digest(v) for k,v in current.items()}!=expected:raise ValueError('frozen_row_hash_changed')
  before=current;check_scope(before);after=after_rows(before);journal=dict(operation_id=OP,expected=expected,before=before,after=after,proof=proof_provider(),phase='prepared')
 for name,row in current.items():
  if digest(row) not in {digest(before[name]),digest(after[name])}:raise ValueError('unrelated_drift_'+name)
 task_states={digest(current[k])==digest(after[k]) for k in ('task','recommendation','weekly')}
 if len(task_states)!=1:raise ValueError('task_transaction_incomplete')
 complete=all(current[k]==after[k] for k in current)
 if not apply:return dict(status='already_reconciled' if complete else 'inspect_ready',operation_id=OP,hashes={k:digest(v) for k,v in current.items()},proof=journal['proof'])
 if not journal_file.exists():audit.mkdir(parents=True,mode=0o700);os.chmod(audit,0o700);durable(journal_file,journal)
 if complete:
  if journal['phase']!='completed':journal['phase']='completed';durable(journal_file,journal)
  return dict(status='already_reconciled',operation_id=OP)
 with db(budget,True) as conn:
  conn.execute('BEGIN IMMEDIATE')
  actual=dict(conn.execute('SELECT * FROM model_calls WHERE fingerprint=?',(FP,)).fetchone())
  if actual==before['call']:cas(conn,'call',before['call'],after['call'])
  elif actual!=after['call']:raise ValueError('budget_cas_changed')
  actual=dict(conn.execute('SELECT * FROM hermes_reservations WHERE fingerprint=?',(FP,)).fetchone())
  if actual!=before['reservation']:raise ValueError('reservation_changed')
 checkpoint('budget_committed');journal['phase']='budget_committed';durable(journal_file,journal)
 with db(tasks,True) as conn:
  conn.execute('BEGIN IMMEDIATE')
  for name in ('recommendation','weekly','task'):cas(conn,name,before[name],after[name])
 checkpoint('tasks_committed');journal['phase']='completed';durable(journal_file,journal)
 if rows(tasks,budget)!=after:raise ValueError('readback_mismatch')
 return dict(status='reconciled_not_dispatched',operation_id=OP,task_state='FAILED',task_version=after['task']['version'],model_state='not_dispatched',reservation_preserved=True,network_started_preserved=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args();audit=pathlib.Path('/var/backups/fs-campaign-weekly-reconcile-20261109')/OP
 try:
  if args.apply:
   import fcntl
   lock=pathlib.Path('/var/lib/fs-hermes-fc/fs/admission.lock')
   if lock.is_symlink() or any(p.is_symlink() for p in lock.parents):raise ValueError('admission_path_invalid')
   with lock.open('r+') as held:
    fcntl.flock(held.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    result=recover('/var/lib/fs-hermes-fc/fs/tasks.sqlite3','/var/lib/fs-business-ranges/fc-daily/daily.sqlite3',audit,apply=True)
  else:result=recover('/var/lib/fs-hermes-fc/fs/tasks.sqlite3','/var/lib/fs-business-ranges/fc-daily/daily.sqlite3',audit)
  print(encoded(result))
 except Exception as error:
  print(encoded(dict(status='blocked',operation_id=OP,error=str(error) if isinstance(error,ValueError) else type(error).__name__)));raise SystemExit(1)
