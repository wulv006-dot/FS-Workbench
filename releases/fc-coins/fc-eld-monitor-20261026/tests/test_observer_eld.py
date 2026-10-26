import copy,importlib.util,json,sys,tempfile,types,unittest,uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
def module(name,file):
 spec=importlib.util.spec_from_file_location(name,SOURCE/file);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
O=module('eld_observer','observe.py');V=module('eld_view','reference_observer_view.py')
class ObserverELD(unittest.TestCase):
 def test_business_locks_released_before_eld_and_snapshot_preserved(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);fc=root/'fc';state=root/'observer'
   for name in ('jobs','runs','state','queue'):(fc/name).mkdir(parents=True,exist_ok=True)
   for name in ('one','two'):(fc/'state'/name).touch()
   jid=str(uuid.uuid4());at=datetime.now(timezone.utc).isoformat();job=dict(job_id=jid,kind='auto_cycle',actor='system-automation',status='ready',created_at=at,request={'policy_revision':40})
   snap=dict(run_id=jid,status='ready_for_quote',created_at=at,reference_competitors={'status':'captured','run_id':jid,'offers':[dict(platform=p,status='valid',captured_at=at) for p in ('PS','XBOX','PC')]},competitors=[],costs=[],fx={})
   (fc/'jobs'/(jid+'.json')).write_text(json.dumps(job));path=fc/'runs'/(jid+'.json');path.write_text(json.dumps(snap));before=path.read_bytes();held=[]
   @contextmanager
   def mutation():
    held.append(True)
    try:yield
    finally:held.pop()
   tick=types.SimpleNamespace(ROOT=fc,RETRY_LOCKS=('one','two'),queue_mutation=mutation,retry_guard=lambda:'ready')
   fake={'fcntl':types.SimpleNamespace(flock=lambda *a:None,LOCK_EX=2,LOCK_NB=4),
    'automation_tick':tick,'fc27_cloud_api':types.SimpleNamespace(health=lambda:{'incomplete_executions':0}),
    'snapshot_layer':types.SimpleNamespace(atomic_json=lambda p,v:p.write_text(json.dumps(v))),
    'reference_shadow':types.SimpleNamespace(experimental_scenarios=lambda *a,**k:{'status':'partial','weighted_platforms':{}})}
   def read_eld(run):
    self.assertEqual(held,[]);self.assertEqual(run,jid);return dict(status='observed',platforms=[],direct_pricing_weight='0')
   with patch.object(O,'FC',fc),patch.object(O,'STATE',state),patch.object(O,'eldorado_read',side_effect=read_eld) as read,patch.dict(sys.modules,fake):
    result=O.main();self.assertEqual(result['status'],'observed');read.assert_called_once_with(jid)
    self.assertEqual(path.read_bytes(),before);self.assertTrue(json.loads((state/'latest.json').read_text())['original_snapshot_unchanged'])
    O.main();self.assertEqual(read.call_count,1)
    for request in ({'collection_retry_attempt':None},{'collection_retry_of':''},{'collection_retry_root':False}):
     (state/'samples'/(jid+'.json')).unlink();job['request']=request
     (fc/'jobs'/(jid+'.json')).write_text(json.dumps(job));O.main();self.assertEqual(read.call_count,1)
     self.assertEqual(json.loads((state/'latest.json').read_text())['eldorado']['status'],'not_collected')
 def test_no_shared_browser_or_unbounded_runner(self):
  import inspect
  code=inspect.getsource(O.eldorado_read)
  for required in ('--memory=768m','--pids-limit=256','--cpus=0.5','--pull=never','--rm','timeout=80','docker\',\'kill'):
   self.assertIn(required,code)
  self.assertNotIn('connect_over_cdp',code);self.assertNotIn('--volume',code);self.assertNotIn('--network=host',code)
 def test_projection_keeps_eld_separate_from_five_source_weights(self):
  record=dict(status='observed',run_id='original',eldorado={'status':'observed','platforms':[{'platform':'PS','lowest_observed_100k_usd':'5.43'}]})
  result=V.project(record);self.assertEqual(result['eldorado'],record['eldorado']);self.assertEqual(result['market'],[]);self.assertEqual(result['weighted'],[])
 def test_reader_timeout_and_cleanup_timeout_remain_explicit(self):
  import subprocess
  with patch.object(Path,'read_text',return_value='isolated public reader'),patch.object(O.subprocess,'run',side_effect=[subprocess.TimeoutExpired('read',80),subprocess.TimeoutExpired('kill',8)]):
   result=O.eldorado_read(str(uuid.uuid4()))
  self.assertEqual(result['status'],'failed');self.assertEqual(result['cleanup_state'],'cleanup_needs_reconcile');self.assertEqual(result['platforms'],[])
 def test_initial_calibration_does_not_become_natural_sample(self):
  with tempfile.TemporaryDirectory() as td:
   state=Path(td);(state/'samples').mkdir();(state/'eldorado-initial.json').write_text(json.dumps(dict(source='ELD',kind='user_requested_initial_public_observation',status='observed',platforms=[{'platform':'PS'}],direct_pricing_weight='0',stderr='not_public')))
   result=V.build_view(state);self.assertEqual(result['archive_count'],0);self.assertEqual(result['eldorado']['kind'],'user_requested_initial_public_observation');self.assertNotIn('stderr',result['eldorado'])
 def test_failed_natural_read_never_falls_back_to_initial_price(self):
  with tempfile.TemporaryDirectory() as td:
   state=Path(td);(state/'samples').mkdir();(state/'eldorado-initial.json').write_text(json.dumps(dict(status='observed',platforms=[{'platform':'PS','lowest_observed_100k_usd':'1'}])))
   (state/'samples/original.json').write_text(json.dumps(dict(run_id='original',status='observed',started_at=datetime.now(timezone.utc).isoformat(),eldorado={'status':'failed','platforms':[],'reason':'blocked'})))
   result=V.build_view(state);self.assertEqual(result['eldorado']['status'],'failed');self.assertEqual(result['eldorado']['platforms'],[])

if __name__=='__main__':unittest.main()
