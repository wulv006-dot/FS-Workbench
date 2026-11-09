import importlib.util,pathlib,tempfile,sqlite3,json,unittest
P=pathlib.Path(__file__).with_name('reconcile-curl-local-failure.py');spec=importlib.util.spec_from_file_location('recovery',P);r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class Recovery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=pathlib.Path(self.tmp.name);self.tasks=base/'tasks.sqlite3';self.budget=base/'daily.sqlite3';self.audit=base/'audit'
  before={'task':dict(id=r.TASK,owner=r.OWNER,fingerprint='task-fp',spec='{}',state='NEEDS_RECONCILE',version=2,run_id=r.RUN,lease=None,tokens=123,rounds=0),'recommendation':dict(owner=r.OWNER,operation_id=r.OP,request_hash='original-body-hash',input='{}',state='unknown',task_id=r.TASK,run_id=r.RUN,lease='original-lease',result='{"status":"unknown","diagnostic":{"code":"curl_exit"}}',network_started=1),'weekly':dict(operation_id=r.OP,owner=r.OWNER,state='unknown',stage='model',prepared='{}',model_input='{}',result='{"status":"unknown","evidence_coverage":{"vertical":1}}'),'call':dict(fingerprint=r.FP,day='2026-11-09',state='unknown',content='{"status":"unknown","local_trace_id":"original-trace"}'),'reservation':dict(fingerprint=r.FP,owner=r.OWNER,task=r.TASK,turn=0,request_digest='original-request-digest',policy='{"model":"gpt-6.1-sol"}',tokens=10000,microcny=-1)}
  self.before=before;self.expected={k:r.digest(v) for k,v in before.items()}
  for file,names in ((self.tasks,('task','recommendation','weekly')),(self.budget,('call','reservation'))):
   with r.db(file,True) as db:
    for name in names:
     table,key,_=r.TABLES[name];row=before[name];db.execute('CREATE TABLE '+table+'('+','.join('"'+k+'" '+('INTEGER' if isinstance(v,int) else 'TEXT') for k,v in row.items())+')');db.execute('INSERT INTO '+table+' VALUES('+','.join('?' for k in row)+')',tuple(row.values()))
    db.execute('CREATE TABLE unrelated(value TEXT)');db.execute("INSERT INTO unrelated VALUES('keep')")
 def run_recovery(self,**kwargs):return r.recover(self.tasks,self.budget,self.audit,expected=self.expected,proof_provider=lambda:{'fixture':'zero_network_proof'},**kwargs)
 def test_inspect_is_readonly_and_apply_is_exact_idempotent_and_keeps_audit(self):
  self.assertEqual(self.run_recovery()['status'],'inspect_ready');self.assertFalse(self.audit.exists());self.assertEqual(r.rows(self.tasks,self.budget),self.before)
  self.assertEqual(self.run_recovery(apply=True)['status'],'reconciled_not_dispatched');after=r.rows(self.tasks,self.budget);self.assertEqual(after,r.after_rows(self.before));self.assertEqual(after['reservation'],self.before['reservation']);self.assertEqual(after['recommendation']['network_started'],1);self.assertEqual(after['task']['tokens'],123)
  journal=json.loads((self.audit/'recovery.json').read_text());self.assertEqual(journal['before'],self.before);self.assertEqual(journal['phase'],'completed');self.assertEqual(self.run_recovery(apply=True)['status'],'already_reconciled')
  for file in (self.tasks,self.budget):
   with r.db(file,True) as db:self.assertEqual(db.execute('SELECT value FROM unrelated').fetchone()[0],'keep')
 def test_frozen_row_drift_refused_before_any_audit_or_write(self):
  with r.db(self.tasks,True) as db:db.execute('UPDATE tasks SET version=3')
  with self.assertRaisesRegex(ValueError,'frozen_row_hash_changed'):self.run_recovery(apply=True)
  self.assertFalse(self.audit.exists());self.assertEqual(r.rows(self.tasks,self.budget)['call']['state'],'unknown')
 def test_crash_after_budget_commit_resumes_original_audit_without_replaying(self):
  def crash(phase):
   if phase=='budget_committed':raise RuntimeError('simulated crash')
  with self.assertRaises(RuntimeError):self.run_recovery(apply=True,checkpoint=crash)
  partial=r.rows(self.tasks,self.budget);self.assertEqual(partial['call']['state'],'not_dispatched');self.assertEqual(partial['task']['state'],'NEEDS_RECONCILE');self.assertEqual(self.run_recovery()['status'],'inspect_ready')
  self.assertEqual(self.run_recovery(apply=True)['status'],'reconciled_not_dispatched')
 def test_task_version_drift_after_budget_commit_is_not_overwritten(self):
  def conflict(phase):
   if phase=='budget_committed':
    with r.db(self.tasks,True) as db:db.execute('UPDATE tasks SET version=3')
  with self.assertRaisesRegex(ValueError,'row_cas_changed_task'):self.run_recovery(apply=True,checkpoint=conflict)
  after=r.rows(self.tasks,self.budget);self.assertEqual(after['task']['state'],'NEEDS_RECONCILE');self.assertEqual(after['recommendation']['state'],'unknown');self.assertEqual(after['weekly']['state'],'unknown')
 def test_unproven_transport_cannot_change_any_rows(self):
  def reject():raise ValueError('local_argument_rejection_not_reproduced')
  with self.assertRaises(ValueError):r.recover(self.tasks,self.budget,self.audit,expected=self.expected,proof_provider=reject,apply=True)
  self.assertEqual(r.rows(self.tasks,self.budget),self.before)
if __name__=='__main__':unittest.main()

