import sys,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
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
 def test_daily_calendar_not_24h(self):
  self.track();self.observe();self.assertEqual(self.s.due_histories(now=NOW+timedelta(hours=1)),[])
  self.assertEqual(self.s.due_histories(now=NOW+timedelta(hours=13)),[self.id])
 def test_manual_only_anonymous_once(self):
  self.track();self.observe();f=FakeConversation();p=PoolReports(f,self.s);self.assertEqual(f.calls,0)
  r=p.generate('tester','4'*32);self.assertEqual(r['customer_count'],1);self.assertEqual(f.calls,1)
  self.assertTrue(p.generate('tester','4'*32)['reused']);self.assertEqual(f.calls,1)
  self.assertNotIn(self.row['email'],f.prompt);self.assertNotIn(self.row['order_no'],f.prompt)
  with self.assertRaisesRegex(ValueError,'already_running'):p.generate('tester','5'*32)
  self.assertEqual(p.listed('tester')['items'][0]['state'],'completed')
  self.s.stop(self.id,'6'*32,'tester')
  self.assertEqual(pool_evidence(self.s)['totals']['customers'],0)
  with self.assertRaisesRegex(ValueError,'empty'):p.generate('tester','7'*32)
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
if __name__=='__main__':unittest.main()
