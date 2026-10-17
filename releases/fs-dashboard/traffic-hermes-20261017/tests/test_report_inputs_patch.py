from copy import deepcopy
import contextlib,hashlib,json,sys,types,unittest,shutil
from pathlib import Path
from unittest.mock import patch
import test_publisher as fixtures
ROOT=fixtures.ROOT;RELEASE=fixtures.RELEASE;sha=fixtures.sha
sys.path.insert(0,str(RELEASE/'publisher'))
import prepare_controller_patch,controller_patch,prepare_report_inputs_patch as prepare,report_inputs_patch as bridge

class ReportInputsPatch(unittest.TestCase):
 def setUp(self):
  h=fixtures.PublisherTests();h.setUp();self.addCleanup(h.doCleanups);self.h=h
  self.repo=h.folder/'historical-repo';source=self.repo/'releases/fs-dashboard/traffic-hermes-20261017/source';source.mkdir(parents=True)
  for item in (RELEASE/'source').iterdir():
   if item.is_file():shutil.copyfile(item,source/item.name)
  for item in (RELEASE/'tests/fixtures/report_inputs_4b').iterdir():shutil.copyfile(item,source/item.name)
  shutil.copytree(RELEASE/'publisher',self.repo/'releases/fs-dashboard/traffic-hermes-20261017/publisher')
  details=self.repo/'mmoexp_google_data/details';details.mkdir(parents=True)
  shutil.copyfile(ROOT/'mmoexp_google_data/details/collect_details.py',details/'collect_details.py')
  previous=deepcopy(h.manifest)
  for row in previous['files']:
   if row['target'] in (controller_patch.CONTROLLER,controller_patch.COLLECTOR,bridge.MARKETING,'/opt/fs-hermes-fc/research.py','/opt/fs-hermes-fc/fs_evidence.py'):
    raw=('old '+row['target']).encode();(h.stage/'candidate'/row['candidate']).write_bytes(raw);row['sha256']=sha(raw)
  previous['unchangedRequired'].append({'path':bridge.SNAPSHOTS,'sha256':'da8ca17d739bbc2a95bf6a21510eefda06b2e2f44eabab33c26278886634a277'})
  (h.stage/'approved-manifest.json').write_text(json.dumps(previous),encoding='utf8');self.follow=h.folder/'follow';last=prepare_controller_patch.prepare(self.repo,h.stage,self.follow,'b'*40)
  self.ui=h.folder/'ui';self.ui.mkdir();assets=[]
  for name in ('business.js','google.js','shell.js','index.html','home.html'):
   dest=self.ui/'assets'/name;dest.parent.mkdir(exist_ok=True);dest.write_bytes(b'current ui');assets.append({'candidate':'assets/'+name,'target':'/var/lib/current-e065/'+name,'sha256':sha(b'current ui')})
  targets=[]
  for name,target in [('formal.conf','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'),('home.html','/var/www/dashboard/fs-home/index.html')]:
   dest=self.ui/'candidate'/name;dest.parent.mkdir(exist_ok=True);dest.write_bytes(b'final e065');targets.append({'candidate':'candidate/'+name,'target':target,'sha256':sha(b'final e065')})
  (self.ui/'release-manifest.json').write_text(json.dumps({'releaseId':'workspace-native-20261006-e0654eaced60','immutableAssets':assets,'targets':targets,'unchangedRequired':[]}),encoding='utf8');self.receipt={'sourceCommit':'b'*40,'ui_backup':'/backup/workspace-native-20261006-e0654eaced60','nginx':'passed','session_ready':True};self.out=h.folder/'report';self.manifest=prepare.prepare(self.repo,h.stage,self.follow,self.ui,self.receipt,self.out,'c'*40);self.base=bridge.load_base()
 def test_exact_four_deltas_latest_controller_and_home(self):
  m=self.manifest;self.assertEqual(len(self.base.validate(m,self.out)),5);self.assertEqual({r['target'] for r in m['files'] if r['sha256']!=r['beforeSha256']},bridge.DELTAS);self.assertEqual(m['reportProtectedBaseline']['/var/www/dashboard/fs-home/index.html'],sha(b'final e065'))
  last=json.loads((self.follow/'approved-manifest.json').read_text());current={r['target']:r['sha256'] for r in last['files']};controller=next(r for r in m['files'] if r['target']==controller_patch.CONTROLLER);self.assertEqual(controller['sha256'],current[controller_patch.CONTROLLER]);self.assertEqual(m['reportProtectedBaseline'][controller_patch.COLLECTOR],current[controller_patch.COLLECTOR]);self.assertFalse(m['releaseReady'])
 def test_extra_target_and_payload_or_protected_drift_rejected(self):
  m=deepcopy(self.manifest);m['files'].append(dict(m['files'][0]));
  with self.assertRaises(ValueError):self.base.validate(m,self.out)
  m=deepcopy(self.manifest);m['unchangedRequired'].pop()
  with self.assertRaises(ValueError):self.base.validate(m,self.out)
  row=self.manifest['files'][0];(self.out/'candidate'/row['candidate']).write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'staged candidate SHA'):self.base.validate(self.manifest,self.out)
 def test_rehashed_unapproved_source_is_still_rejected(self):
  m=deepcopy(self.manifest);row=next(r for r in m['files'] if r['target']==bridge.MARKETING);source=self.out/'candidate'/row['candidate'];source.write_bytes(b'arbitrary rehashed replacement');row['sha256']=sha(source.read_bytes())
  with self.assertRaisesRegex(ValueError,'exact_report_input_source_sha_required'):self.base.validate(m,self.out)
 def test_pending_report_rejected_before_publish_and_restart_scope_preserved(self):
  with patch.object(self.base,'hermes_quiescent',side_effect=ValueError('running_report')) as gate:
   with self.assertRaisesRegex(ValueError,'running_report'):self.base.guards(self.manifest,self.h.root)
  gate.assert_called_once();original=self.base.restart_for;calls=[];fence=types.SimpleNamespace(stop_then_unlock_database=lambda:calls.append('admission'))
  with patch.object(self.base,'restart_for',side_effect=lambda m,*a:calls.append(m['scope'])),patch.object(self.base.subprocess,'run') as run:original(self.manifest,fence)
  self.assertEqual(calls,['admission',self.base.HERMES_WORKER_SCOPE,self.base.DEEP_SCOPE]);run.assert_not_called()
 def test_busy_collector_keeps_outer_release_locks(self):
  lock=self.h.root/bridge.MARKETING_LOCK.lstrip('/');lock.parent.mkdir(parents=True,exist_ok=True);lock.write_bytes(b'');lock.chmod(0o600);events=[]
  fake=types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *a:events.append('lock'))
  kwargs={'st_mode':0o100600,'st_uid':0,'st_gid':0,'st_nlink':1}
  with patch.dict(sys.modules,{'fcntl':fake}),patch.object(self.base,'no_target_link'),patch.object(self.base.os,'getuid',return_value=0,create=True),patch.object(self.base.os,'geteuid',return_value=0,create=True),patch.object(self.base.os,'fstat',return_value=types.SimpleNamespace(**kwargs)):
   with self.base.locks(self.h.root):events.append('inside')
  self.assertEqual(events[-2:],['lock','inside']);fake.flock=lambda *a:(_ for _ in ()).throw(BlockingIOError('busy'))
  with patch.dict(sys.modules,{'fcntl':fake}),patch.object(self.base,'no_target_link'),patch.object(self.base.os,'geteuid',return_value=0,create=True),patch.object(self.base.os,'fstat',return_value=types.SimpleNamespace(**kwargs)):
   with self.assertRaises(BlockingIOError):
    with self.base.locks(self.h.root):self.fail('busy admitted')
 def test_wrong_latest_receipt_or_history_source_drift_rejected(self):
  bad=dict(self.receipt,sourceCommit='d'*40)
  with self.assertRaisesRegex(ValueError,'latest_receipt_required'):prepare.prepare(self.repo,self.h.stage,self.follow,self.ui,bad,self.h.folder/'other','c'*40)
  previous=json.loads((self.follow/'approved-manifest.json').read_text());r=previous['files'][0];(self.follow/'candidate'/r['candidate']).write_bytes(b'drift')
  with self.assertRaisesRegex(ValueError,'successful_stage_source_drift'):prepare.prepare(self.repo,self.h.stage,self.follow,self.ui,self.receipt,self.h.folder/'other','c'*40)
if __name__=='__main__':unittest.main()
