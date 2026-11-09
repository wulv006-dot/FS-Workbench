import sys,json,tempfile,unittest,hashlib,ast,re,time,threading,types
from concurrent.futures import Future
from copy import deepcopy
from unittest.mock import patch,Mock
from pathlib import Path
from datetime import date,datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
# The active tracking model reads the shared Admin game registry.
sys.path.append(str(Path(__file__).resolve().parents[2]/'hermes-generic-data-20261018/source'))
sys.path.append(str(Path(__file__).resolve().parents[2]/'fs-business-baseline-20261021/source'))
from customer_tracking import Store,lifecycle_clock,AdminService
from pool_reports import PoolReports,pool_evidence

NOW=datetime(2026,10,19,4,tzinfo=timezone.utc)
class FakeConversation:
 def __init__(self):self.calls=0;self.prompt='';self.fail=False
 def create(self,user):return {'conversation_id':'c'*32}
 def submit(self,user,cid,text,rid):
  self.calls+=1;self.prompt=text
  if self.fail:raise TimeoutError('test')
  return {'turn_id':'d'*32,'state':'queued'}
 def detail(self,user,cid):return {'turns':[{'turn_id':'d'*32,'state':'completed','artifacts':[{'artifact_id':'e'*32,'mime':'text/html'}]}]}

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(self.tmp.name);self.id='a'*32
  self.row={'order_no':'SYNTH-1','email':'synthetic@example.invalid','site_id':266,'gid':1327,'pay_status':1,'paid_at':'2026-10-13 23:00:00','order_usd':'600','identity_status':'verified','uid':0}
  with self.s.db() as db:
   db.execute('INSERT INTO candidates VALUES(?,?,?,?,?)',('b'*32,'SYNTH-1',json.dumps(self.row),json.dumps(self.row),NOW.isoformat()))
   db.execute('INSERT INTO scan_items VALUES(?,?,?,?,?)',('2026-10-13',1,'b'*32,json.dumps(self.row))) if False else None
   db.execute('INSERT INTO scan_items VALUES(?,?,?,?)',('2026-10-13',1,'b'*32,json.dumps(self.row)))
 def tearDown(self):self.tmp.cleanup()
 def track(self):
  r=self.s.track('b'*32,'1'*32,now=NOW,owner='tester');self.id=r['tracking_id'];return r
 def observe(self,complete=True):return self.s.observe(self.id,[self.row],observed_at=NOW.isoformat(),coverage={'complete':complete})
 def test_buyer_evidence_and_authorized_identifiers_survive_refresh(self):
  self.row['es_identity']={'buyer_id':'private-buyer-1','uid':None,'status':'verified'}
  with self.s.db() as db:db.execute('UPDATE candidates SET latest_body=?,first_body=?',(json.dumps(self.row),json.dumps(self.row)))
  self.track();self.observe()
  detail=self.s.detail(self.id)
  self.assertEqual(detail['orders'][0]['es_identity']['buyer_id'],'private-buyer-1')
  self.assertEqual(detail['buyer_identity_evidence']['covered_orders'],1)
  import importlib.util
  spec=importlib.util.spec_from_file_location('actual_lifecycle_tool',Path(__file__).resolve().parents[1]/'source/tracking_tool.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  public=module.anonymous_snapshot(detail)
  self.assertIn('buyer_identity_evidence',public)
  self.assertFalse(public['buyer_identity_evidence']['canonical_identity_updated'])
  self.assertNotIn('private-buyer-1',json.dumps(public))
  business=module.customer_snapshot(detail)
  self.assertEqual(business['email'],self.row['email'])
  self.assertEqual(business['uid'],0)
  self.assertEqual(business['orders'][0]['order_no'],self.row['order_no'])
  self.assertEqual(business['orders'][0]['es_identity']['buyer_id'],'private-buyer-1')
  self.assertTrue(business['history_coverage']['complete'])
  detail['orders'][0]['token']='fixture-credential'
  detail['orders'][0]['payment']={'amount':'12','currency':'USD','password':'fixture-credential'}
  detail['orders'][0]['es_identity']['secret']='fixture-credential'
  self.assertNotIn('fixture-credential',json.dumps(module.customer_snapshot(detail)))
  pool=pool_evidence(self.s,NOW)
  self.assertIn('buyer_identity_evidence',pool['customers'][0])
  self.assertNotIn('private-buyer-1',json.dumps(pool))

 def test_buyer_candidates_require_exact_admin_order_and_conflicts_are_not_merged(self):
  from customer_tracking import candidate_rows,DEFAULT_CONFIG
  es={'游戏':'FC 27','产品类型':'货币(Gold)','订单号':'SYNTH-1','订单金额（美元）':'600','实付金额':'600','实付币种':'USD','折扣金额':'0','是否新客户':'是','付款时间':'2026-10-13 23:00:00','buyer_id':'opaque-buyer','uid':'0'}
  admin=dict(self.row,amount='600')
  rows,_=candidate_rows([es],{'SYNTH-1':admin},DEFAULT_CONFIG)
  self.assertEqual(rows[0]['es_identity']['buyer_id'],'opaque-buyer')
  self.assertEqual(rows[0]['es_identity']['source'],'ES exact order matched to Admin')
  merged,_=candidate_rows([dict(es,buyer_id='N/A'),es],{'SYNTH-1':admin},DEFAULT_CONFIG)
  self.assertEqual(len(merged),1)
  self.assertEqual(merged[0]['es_identity']['buyer_id'],'opaque-buyer')
  rows,coverage=candidate_rows([es,dict(es,buyer_id='different-buyer')],{'SYNTH-1':admin},DEFAULT_CONFIG)
  self.assertEqual(rows,[])
  self.assertEqual(coverage['conflicts'],1)

 def test_first_paid_day_one_and_seven(self):
  c=lifecycle_clock([self.row],{'complete':True},NOW);self.assertEqual(c['lifecycle_day'],7);self.assertTrue(c['stage_markers'][0]['reached']);self.assertEqual(c['stage_markers'][0]['date'],'2026-10-19')
 def test_unknown_partial_invalid_unpaid(self):
  self.assertIsNone(lifecycle_clock([self.row],{'complete':False},NOW)['first_paid_at'])
  self.assertIsNone(lifecycle_clock([dict(self.row,paid_at=None)],{'complete':True},NOW)['first_paid_at'])
  self.assertIsNone(lifecycle_clock([dict(self.row,pay_status=0)],{'complete':True},NOW)['first_paid_at'])
 def test_first_payment_crossgame_not_enrollment(self):
  older=dict(self.row,order_no='SYNTH-2',gid=99,paid_at='2026-10-01 01:00:00');c=lifecycle_clock([self.row,older],{'complete':True},NOW);self.assertEqual(c['lifecycle_day'],19)
 def test_track_no_reports_and_stop_idempotency(self):
  r=self.track();self.assertEqual(r['milestones'],[]);self.assertEqual(self.s.due_reports(),[])
  result=self.s.stop(self.id,'2'*32,'tester');self.assertEqual(result['state'],'stopped');self.assertTrue(self.s.stop(self.id,'2'*32,'tester')['reused']);self.assertEqual(self.s.due_histories(now=NOW),[])
  self.assertEqual(self.s.track('b'*32,'3'*32,now=NOW,owner='tester')['status'],'paused')
 def test_retire_only_scheduled_preserve_history(self):
  self.track()
  with self.s.db() as db:
   for n,st in [(0,'completed'),(7,'scheduled'),(14,'dispatch_unknown')]:db.execute('INSERT INTO milestones(track_id,days,due_at,state,request_id) VALUES(?,?,?,?,?)',(self.id,n,NOW.isoformat(),st,str(n).zfill(32)))
  Store(self.tmp.name)
  with self.s.db() as db:states=dict(db.execute('SELECT days,state FROM milestones').fetchall())
  self.assertEqual(states,{0:'completed',7:'cancelled',14:'dispatch_unknown'})
 def test_existing_report_binding_accepts_authorized_identity_and_keeps_type_size_cas(self):
  self.track()
  with self.s.db() as db:
   db.execute('INSERT INTO milestones(track_id,days,due_at,state,request_id) VALUES(?,?,?,?,?)',(self.id,7,NOW.isoformat(),'completed','7'*32))
  prompt=self.row['email']+' UID 0 '+self.row['order_no']
  self.s.bind_report(self.id,7,'completed',prompt=prompt)
  self.assertEqual(self.s.detail(self.id)['milestones'][0]['state'],'completed')
  with self.s.db() as db:self.assertEqual(db.execute('SELECT prompt FROM milestones WHERE track_id=?',(self.id,)).fetchone()['prompt'],prompt)
  for bad in (None,'x'*16001):
   with self.assertRaisesRegex(ValueError,'report_prompt'):self.s.bind_report(self.id,7,'completed',prompt=bad)
  with self.assertRaisesRegex(ValueError,'report_state_changed'):self.s.bind_report(self.id,7,'queued',prompt=prompt)
 def test_daily_calendar_not_24h(self):
  self.track();self.observe();self.assertEqual(self.s.due_histories(now=NOW+timedelta(hours=1)),[])
  self.assertEqual(self.s.due_histories(now=NOW+timedelta(hours=13)),[self.id])
 def test_manual_only_authorized_identifiers_once(self):
  self.track();self.observe();f=FakeConversation();p=PoolReports(f,self.s);self.assertEqual(f.calls,0)
  r=p.generate('tester','4'*32);self.assertEqual(r['customer_count'],1);self.assertEqual(f.calls,1)
  self.assertTrue(p.generate('tester','4'*32)['reused']);self.assertEqual(f.calls,1)
  self.assertIn(self.row['email'],f.prompt);self.assertIn(self.id,f.prompt)
  evidence=pool_evidence(self.s,NOW)['customers'][0]
  self.assertEqual(evidence['uid'],0);self.assertEqual(evidence['customer_ref'],self.id)
  with self.assertRaisesRegex(ValueError,'already_running'):p.generate('tester','5'*32)
  self.assertEqual(p.listed('tester')['items'][0]['state'],'completed')
  self.s.stop(self.id,'6'*32,'tester')
  self.assertEqual(pool_evidence(self.s)['totals']['customers'],0)
  with self.assertRaisesRegex(ValueError,'empty'):p.generate('tester','7'*32)
 def test_pool_report_long_realistic_order_ids_keep_complete_aggregate_and_detail_reference(self):
  self.track();self.observe();detail=self.s.detail(self.id)
  detail['orders']=[dict(self.row,order_no='ORDER-20261109-'+str(i).zfill(9)) for i in range(1000)]
  with patch.object(self.s,'detail',return_value=detail):
   evidence=pool_evidence(self.s,NOW)
   f=FakeConversation();result=PoolReports(f,self.s).generate('tester','a'*32)
  customer=evidence['customers'][0]
  self.assertEqual(sum(row['paid_orders'] for row in customer['groups']),1000)
  self.assertEqual(customer['email'],self.row['email']);self.assertEqual(customer['uid'],0)
  self.assertEqual(customer['customer_ref'],self.id)
  self.assertEqual(result['customer_count'],1);self.assertEqual(f.calls,1)
  self.assertLess(len(f.prompt),12000)
 def test_unknown_dispatch_never_replayed(self):
  self.track();self.observe();f=FakeConversation();f.fail=True;p=PoolReports(f,self.s)
  self.assertEqual(p.generate('tester','8'*32)['state'],'dispatch_unknown');p.generate('tester','8'*32);self.assertEqual(f.calls,1)
 def test_owner_receipts_and_authorization(self):
  self.track();self.observe();p=PoolReports(FakeConversation(),self.s);p.generate('tester','9'*32)
  with self.assertRaisesRegex(ValueError,'idempotency_conflict'):p.generate('another','9'*32)
  self.assertEqual(p.listed('another')['items'],[])
  with self.assertRaises(PermissionError):AdminService(self.s,lambda _:False).post('bad',{'kind':'hermes_customer_tracking','action':'stop','tracking_id':self.id,'request_id':'0'*32})
 def test_stopped_observation_cannot_update(self):
  self.track();self.observe();self.s.stop(self.id,'a'*32,'tester')
  result=self.s.observe(self.id,[dict(self.row,order_usd='9999')],coverage={'complete':True})
  self.assertEqual(result['status'],'stopped');self.assertEqual(self.s.detail(self.id)['orders'][0]['order_usd'],'600')
 def test_controller_retired_queue_and_night_gate(self):
  import ast
  s=(Path(__file__).resolve().parents[1]/'source/tracking_controller.py').read_text();tree=ast.parse(s)
  klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TrackingController')
  queue=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='_queue_reports')
  self.assertFalse(any(isinstance(n,ast.Call) for n in ast.walk(queue)))
  self.assertIn('datetime.now(SHANGHAI).hour>=7',s)
  self.assertIn("body.get('action')=='generate_pool'",s)
 def test_controller_manual_report_and_stop_routes(self):
  from tracking_controller import TrackingController
  self.track();self.observe();f=FakeConversation()
  class Client:
   def read(self,body):raise AssertionError('unexpected upstream read')
  c=TrackingController(self.tmp.name,lambda u:u=='tester',client=Client(),auto_start=False,conversation=f)
  code,r=c.post('tester',{'kind':'hermes_customer_tracking','action':'generate_pool','request_id':'c'*32})
  self.assertEqual(code,200);self.assertEqual(f.calls,1)
  code,r=c.get('tester',{'mode':['hermes'],'structure':['customer_tracking'],'view':['pool_reports']});self.assertEqual(r['items'][0]['state'],'completed')
  c.post('tester',{'kind':'hermes_customer_tracking','action':'stop','tracking_id':self.id,'request_id':'d'*32})
  self.assertEqual(c._poll_history(self.id),'stopped');c._queue_reports();self.assertEqual(f.calls,1)
class PermissionRecovery(unittest.TestCase):
 def setUp(self):
  import tracking_controller as controller
  from customer_tracking import DEFAULT_CONFIG,scan_job_sha256
  self.module=controller;self.config=deepcopy(DEFAULT_CONFIG);self.day='2026-10-28';self.rid='1'*32
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.esroot=self.root/'es';self.esroot.mkdir(mode=0o700)
  source=Path(__file__).resolve().parents[2]/'cache-archive-retention-20261025/source/es_order_structure.py'
  tree=ast.parse(source.read_text('utf-8'));self.es=types.ModuleType('es_order_structure')
  self.es.__dict__.update(Path=Path,hashlib=hashlib,json=json,re=re,time=time,date=date,datetime=datetime,timezone=timezone,timedelta=timedelta,
   GAME_LABELS={'FC27':'FC 27'},GROUPS=('game','source_game','product','country','payment','new_customer','status'),DISCOUNT_GROUPS=(),
   RULE_VERSION='original-contract',SHANGHAI=timezone(timedelta(hours=8)),SERVER_LOCK=threading.RLock())
  names={'checked_query','_receipt_paths','_read_receipt','_permission_denial','_server_bundle','cache_seconds','retained_bundle'}
  exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(source),'exec'),self.es.__dict__)
  self.patches=[patch.dict(sys.modules,es_order_structure=self.es),patch('customer_tracking.game_scope',return_value=(1327,'FC 27'))]
  for p in self.patches:p.start()
  self.client=Mock();self.client.read.return_value={'status':'pending'}
  self.c=controller.TrackingController(self.root/'tracking',lambda user:user=='admin',self.client,auto_start=False)
  self.c.store.begin_scan(self.day,self.rid)
  self.c.store.finish_scan(self.day,1,dict(status='unavailable',reason='es_export_permission_denied',retryable=True,stage='not_generated'))
  with self.c.store.db() as db:
   db.execute("UPDATE scan_jobs SET updated_at='2026-10-28T10:00:00+00:00'")
  self.job_sha=scan_job_sha256(self.c.store.scan_job(self.day))
  q=self.es.checked_query(dict(profile='ALL',start=self.day,end=self.day))
  self.index,self.attempt,self.legacy=self.es._receipt_paths(q,self.esroot)
  self.saved=dict(saved_at=time.time(),permission_denial=dict(receipt_sha256='e'*64,result=dict(reason='es_export_permission_denied')),
    value=dict(kind='es_order_structure_bundle',status='available',snapshots=[dict(query=q,value=dict(kind='es_order_structure',status='available',
     source_version='f'*64,captured_at=datetime.now(timezone.utc).isoformat(),quality=dict(file_set_complete=True,parse_failures=0,failed_files=0,declared_files=1,read_files=1)))]))
  self.save_receipt()
 def tearDown(self):
  if getattr(self,'reads',None):self.reads.pool.shutdown()
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def save_receipt(self):
  self.index.write_text(json.dumps(self.saved));self.index.chmod(0o600);self.es_sha=hashlib.sha256(self.index.read_bytes()).hexdigest()
 def daily_once(self):
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):return datetime(2026,10,29,2,tzinfo=timezone(timedelta(hours=8))).astimezone(tz or timezone.utc)
  with patch('tracking_controller.datetime',Clock),patch('tracking_controller.time.sleep',side_effect=StopIteration):
   with self.assertRaises(StopIteration):self.c._daily_loop()
 def test_definite_denial_new_and_legacy_sixty_stop_only_original_daily(self):
  self.assertIsNone(self.c.store.scan_job(self.day)['retry_after'])
  for retry in (None,60):
   with self.c.store.db() as db:db.execute('UPDATE scan_jobs SET retry_after=?',(retry,))
   before=self.c.store.scan_job(self.day);self.daily_once()
   self.assertEqual(self.c.store.scan_job(self.day),before);self.client.read.assert_not_called()
   value=self.c.store.candidates(self.day);self.assertEqual(value['status'],'failed');self.assertFalse(value['retryable']);self.assertIsNone(value['retry_after'])
  code,value=self.c.post('admin',dict(kind='hermes_customer_tracking',action='scan',day=self.day,request_id=self.rid))
  self.assertEqual(value['status'],'failed');self.client.read.assert_not_called()
 def test_other_failures_new_day_new_config_and_histories_keep_original_behaviour(self):
  self.c.store.finish_scan(self.day,1,dict(status='unavailable',reason='private_source_timeout'))
  with self.c.store.db() as db:db.execute("UPDATE scan_jobs SET updated_at='2026-10-28T10:00:00+00:00'")
  with patch.object(self.c.store,'due_histories',return_value=['a'*32]),patch.object(self.c,'_poll_history') as history:self.daily_once()
  self.assertNotEqual(self.c.store.scan_job(self.day)['request_id'],self.rid);self.client.read.assert_called_once();history.assert_called_once()
  self.c.store.finish_scan(self.day,1,dict(status='unavailable',reason='es_export_permission_denied'))
  with self.c.store.db() as db:db.execute("UPDATE scan_jobs SET day='2026-10-27'")
  self.client.reset_mock();self.daily_once();self.client.read.assert_called_once();self.assertEqual(self.c.store.scan_job(self.day)['state'],'pending')
  self.c.store.save_config(self.config,1,'b'*32);self.client.reset_mock();self.daily_once()
  self.assertEqual(self.c.store.scan_job(self.day)['config_version'],2);self.client.read.assert_called_once()
 def original_private_client(self,result=None,observed=True,pending=False):
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'hermes-customer-tracking-20261018/source'))
  import tracking_private_session as private
  key=self.root/'key';key.write_bytes(b'a'*64+b'\n');key.chmod(0o600)
  self.reads=private.PrivateReads(types.SimpleNamespace(lock=threading.RLock(),token=None,identity_ok=lambda *a,**k:True,request=Mock(side_effect=AssertionError('no HTTP'))),key)
  body=dict(action='scan',day=self.day,config=self.config);fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  old=Future()
  if not pending:old.set_result(result or dict(status='unavailable',reason='es_export_permission_denied'))
  self.reads.jobs[fingerprint]=dict(future=old,finished=time.monotonic(),status=None if pending else 'unavailable',observed=observed)
  client=self.module.PrivateClient(key);client.reads=self.reads;self.c.client=client
  return private,body,fingerprint,old
 def resume(self,**values):
  return self.c.resume_permission_scan(values.pop('user','admin'),self.day,values.pop('version',1),values.pop('rid',self.rid),
   expected_job_sha256=values.pop('job_sha',self.job_sha),es_receipt_sha256=values.pop('es_sha',self.es_sha),es_root=self.esroot,**values)
 def test_same_original_private_future_recovery_runs_real_client_scan_and_finish(self):
  private,body,key,old=self.original_private_client()
  self.es.server_bundle=lambda args:self.es._server_bundle(args,self.esroot,Mock(side_effect=AssertionError('no export')))
  import tracking_source
  archive=dict(status='available',rows=[],source_version='f'*64,captured_at=datetime.now(timezone.utc).isoformat(),coverage=dict(file_set_complete=True))
  with patch.object(tracking_source,'private_es_day',return_value=archive):
   result=self.resume()
   for _ in range(100):
    if self.c.store.scan_job(self.day)['state']!='pending':break
    self.c._poll_scan(self.day);time.sleep(.002)
  final=self.c.store.scan_job(self.day);self.assertEqual((final['state'],final['request_id'],final['config_version']),('available',self.rid,1))
  self.assertIs(self.c.client.reads,self.reads);self.assertIsNot(self.reads.jobs[key]['future'],old)
  receipt=self.c.store.request(self.rid)['result'];self.assertEqual(receipt['permission_recovery']['prior_failure']['reason'],'es_export_permission_denied')
  with self.c.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],1)
  future=self.reads.jobs[key]['future'];self.resume();self.assertIs(self.reads.jobs[key]['future'],future)
  self.assertEqual(self.c.store.request(self.rid)['result'],receipt)
 def test_unknown_active_or_unobserved_future_not_deleted_or_marked_pending(self):
  for result,observed,pending in ((dict(status='unknown',reason='export_sent'),True,False),
    (dict(status='unknown',reason='es_export_permission_denied'),True,False),
    (dict(status='unavailable',reason='es_export_permission_denied',stage='export_sent'),True,False),
    (None,True,True),(None,False,False)):
   if getattr(self,'reads',None):self.reads.pool.shutdown()
   _,body,key,old=self.original_private_client(result,observed,pending);before=self.c.store.scan_job(self.day)
   with self.assertRaises(ValueError):self.resume()
   self.assertEqual(self.c.store.scan_job(self.day),before);self.assertIs(self.reads.jobs[key]['future'],old)
 def test_store_cas_failure_keeps_original_completed_future_and_request(self):
  _,body,key,old=self.original_private_client();before=self.c.store.scan_job(self.day);request=self.c.store.request(self.rid)
  original=self.c.store.resume_permission_scan
  def changed(*args,**kwargs):
   with self.c.store.db() as db:db.execute("UPDATE scan_jobs SET updated_at='2026-10-28T10:01:00+00:00'")
   return original(*args,**kwargs)
  with patch.object(self.c.store,'resume_permission_scan',side_effect=changed):
   with self.assertRaisesRegex(ValueError,'job_changed'):self.resume()
  self.assertEqual(self.c.store.scan_job(self.day)['state'],'failed');self.assertIs(self.reads.jobs[key]['future'],old)
  self.assertEqual(self.c.store.request(self.rid),request)
 def test_recovery_refuses_wrong_actor_id_config_cas_or_es_unknown_without_client_mutation(self):
  before=self.c.store.scan_job(self.day)
  for changes in (dict(user='other'),dict(rid='a'*32),dict(version=2),dict(job_sha='0'*64),dict(es_sha='0'*64)):
   with self.assertRaises((ValueError,PermissionError)):self.resume(**changes)
   self.assertEqual(self.c.store.scan_job(self.day),before)
  for attempt in (self.attempt,self.legacy):
   attempt.write_text('{}');attempt.chmod(0o600)
   with self.assertRaisesRegex(ValueError,'es_attempt_unknown'):self.resume()
   attempt.unlink();self.assertEqual(self.c.store.scan_job(self.day),before)
  self.saved['last_attempt']='es_export_permission_denied';self.save_receipt()
  with self.assertRaisesRegex(ValueError,'es_not_rechecked'):self.resume()
  self.saved.pop('last_attempt');self.saved['value']['snapshots'][0]['value']['quality']['file_set_complete']=False;self.save_receipt()
  with self.assertRaisesRegex(ValueError,'es_incomplete'):self.resume()
  self.client.permission_scan_recovery.assert_not_called()

if __name__=='__main__':unittest.main()
