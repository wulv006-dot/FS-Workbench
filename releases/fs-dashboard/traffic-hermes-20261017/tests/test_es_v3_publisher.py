from copy import deepcopy
import contextlib,hashlib,json,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
import test_publisher as fixtures
ROOT=fixtures.ROOT;RELEASE=fixtures.RELEASE;sha=fixtures.sha
sys.path.insert(0,str(RELEASE/'publisher'))
import es_v3_patch as bridge,prepare_es_v3_patch as prepare,es_v3_image_lifecycle as leaf

class ESV3Publisher(unittest.TestCase):
 def setUp(self):
  # This publisher is the frozen dfc V3 release, not the later queue patch.
  frozen=Path(__file__).parent/'fixtures/es_v3_dfc/es_order_structure.py'
  self.assertEqual(sha(frozen.read_bytes()),'dfc4521102b2ee14e8778d346f4abf1a092bde52a83d8809c667796627b064d4')
  live=RELEASE/'source/es_order_structure.py';original_sha=prepare.sha;original_copy=prepare.shutil.copyfile
  detail=Path(__file__).parent/'fixtures/es_v3_dfc/detail_model.py'
  self.assertEqual(sha(detail.read_bytes()),'b70662400ea7a298c55148d16771b53699977e076a543fbe6f4c29de05723dbd')
  contract=Path(__file__).parent/'fixtures/es_v3_dfc/traffic_contract.py'
  self.assertEqual(sha(contract.read_bytes()),'8e2ace1134c601c08cf7c8b7ab3d1ca0bde1d0dac3cedc176721281909695d62')
  frozen_sources={live:frozen,ROOT/'mmoexp_google_data/details/detail_model.py':detail,ROOT/'mmoexp_google_data/details/traffic_contract.py':contract}
  mapped=lambda value:frozen_sources.get(Path(value),value)
  sha_patch=patch.object(prepare,'sha',side_effect=lambda value:original_sha(mapped(value)))
  copy_patch=patch.object(prepare.shutil,'copyfile',side_effect=lambda source,dest,*a,**kw:original_copy(mapped(source),dest,*a,**kw))
  sha_patch.start();copy_patch.start();self.addCleanup(sha_patch.stop);self.addCleanup(copy_patch.stop)
  h=fixtures.PublisherTests();h.setUp();self.addCleanup(h.doCleanups);self.h=h
  prior=deepcopy(h.manifest);self.prior=prior
  known={r['path']:r['sha256'] for r in prior['unchangedRequired']};known.update({r['target']:r['sha256'] for r in prior['files']})
  baseline={'observed_at':'fixture','files':[{'path':p,'exists':True,'sha256':v} for p,v in known.items()],'session_image_id':leaf.BASE_IMAGE,'session_tag':leaf.OLD_TAG,'archive_mounts':[{'source':leaf.ARCHIVE,'destination':leaf.ARCHIVE,'rw':True}]}
  marketing=dict(line.split('=',1) for line in h.admission['units']['fs-marketing-range.service'].splitlines())
  self.maintenance={}
  for unit,props in [('fs-marketing-range.service',marketing),('fs-business-range.service',dict(marketing,Id='fs-business-range.service',ControlGroup='/system.slice/fs-business-range.service',FragmentPath='/etc/systemd/system/fs-business-range.service'))]:
   self.maintenance[unit]={'properties':props,'cgroupPath':'/sys/fs/cgroup/systemd'+props['ControlGroup']+'/cgroup.procs','files':[{'path':props['FragmentPath'],'sha256':sha(b'protected')}]}
  self.receipt={'sourceCommit':prior['sourceCommit'],'session_ready':True,'nginx':'passed','container_image':leaf.BASE_IMAGE}
  self.baseline=baseline;self.out=h.folder/'v3';self.manifest=prepare.prepare(ROOT,h.stage,self.receipt,baseline,self.maintenance,self.out,'a'*40);self.base=bridge.load_base()

 def test_closed_thirteen_targets_shared_rules_and_fixed_b023_image(self):
  files=self.base.validate(self.manifest,self.out);self.assertEqual(len(files),13);self.assertFalse(self.manifest['releaseReady'])
  rows={r['candidate']:r for r in files}
  self.assertEqual(len({rows[k]['sha256'] for k in ('contract/details/traffic_contract.py','hermes/traffic_contract.py','session/traffic_contract.py')}),1)
  self.assertEqual(rows['hermes/es_order_structure.py']['sha256'],rows['session/es_order_structure.py']['sha256'])
  before=(RELEASE/'source/fc27-p2pah-session.service').read_bytes();after=(self.out/'candidate/session/fc27-p2pah-session.service').read_bytes();self.assertEqual(after.replace(leaf.NEW_TAG.encode(),leaf.OLD_TAG.encode()),before)
  self.assertEqual(leaf.BASE_IMAGE,'sha256:b0235b2e5fd21d079dcd6c39c1eb5a7083e86f2748c0c030f2ce320468f6178f')
  original=(RELEASE/'publisher/es_image_lifecycle.py').read_text('utf-8');updated=(RELEASE/'publisher/es_v3_image_lifecycle.py').read_text('utf-8')
  self.assertEqual(updated,original.replace('sha256:88963f9429c84615a7ba24623cf0f54a7d4c313644c64092098e0adb52e835d8',leaf.BASE_IMAGE).replace("OLD_TAG='fc27-cloud-session:business-live-20261010'","OLD_TAG='"+leaf.OLD_TAG+"'").replace("NEW_TAG='fc27-cloud-session:traffic-hermes-20261017-es'","NEW_TAG='"+leaf.NEW_TAG+"'"))

 def test_rehashed_unreviewed_source_and_stale_readback_rejected(self):
  m=deepcopy(self.manifest);row=m['files'][0];source=self.out/'candidate'/row['candidate'];source.write_bytes(b'unreviewed');row['sha256']=sha(b'unreviewed')
  with self.assertRaisesRegex(ValueError,'exact_v3_after_sha'):self.base.validate(m,self.out)
  bad=deepcopy(self.baseline);bad['files'][0]['sha256']='f'*64
  with self.assertRaisesRegex(ValueError,'current_runtime_drift'):prepare.prepare(ROOT,self.h.stage,self.receipt,bad,self.maintenance,self.h.folder/'bad','b'*40)

 def test_original_admission_stop_is_before_any_replacement_and_image_build(self):
  m=deepcopy(self.manifest);m['releaseReady']=True;events=[]
  for row in self.prior['files']:
   path=self.h.root/row['target'].lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((self.h.stage/'candidate'/row['candidate']).read_bytes())
  class Fence:
   def __init__(self,root):self.root=root;self.modified=False;self.confirmed=False;events.append('admission')
   def stop_then_unlock_database(self):events.append('reader-stopped')
   def close(self):pass
  original=self.base.atomic
  targets={str(self.h.root/r['target'].lstrip('/')) for r in m['files']}
  def atomic(path,payload,mode=0o644):
   if str(path) in targets:self.assertIn('reader-stopped',events);self.assertIn('marketing-stopped',events);events.append('replace')
   return original(path,payload,mode)
  raw=json.dumps(m).encode()
  with patch.object(self.base,'locks',return_value=contextlib.nullcontext()),patch.object(self.base,'live_lock',return_value=contextlib.nullcontext()),patch.object(self.base,'model_release_lock',return_value=contextlib.nullcontext()),patch.object(self.base,'HermesAdmissionFence',Fence),patch.object(self.base,'inspect'),patch.object(self.base,'guards'),patch.object(self.base,'retirement'),patch.object(self.base,'directory_sync'),patch.object(self.base,'atomic',side_effect=atomic),patch.object(self.base,'traffic_before_write',side_effect=lambda *a:events.append('marketing-stopped')),patch.object(self.base,'traffic_apply',side_effect=lambda *a:events.append('image-built')),patch.object(self.base,'restart_for',side_effect=lambda *a:events.append('restart')):
   result=self.base.apply(m,self.out,sha(raw),raw,'nav-20261017T200000Z',self.h.root)
  self.assertEqual(result['status'],'applied-awaiting-actual-http-role-acceptance');self.assertEqual(events.count('replace'),13);self.assertLess(events.index('image-built'),events.index('restart'))

 def test_failed_image_build_re_stops_reader_before_restore_and_keeps_private_data(self):
  m=deepcopy(self.manifest);m['releaseReady']=True;events=[]
  for row in self.prior['files']:
   path=self.h.root/row['target'].lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((self.h.stage/'candidate'/row['candidate']).read_bytes())
  evidence=self.h.root/'var/lib/fc27-es-exports/keep.xlsx';evidence.parent.mkdir(parents=True);evidence.write_bytes(b'private-evidence')
  class Fence:
   def __init__(self,root):self.root=root;self.modified=False;self.confirmed=False
   def stop_then_unlock_database(self):events.append('reader-stopped')
   def close(self):pass
  def stop(manifest,backup,journal,root,write):journal.update(marketingStopIntent=True,marketingStopped=True);write(backup,journal);events.append('marketing-stopped')
  def ensure(*args):events.append('marketing-rechecked')
  fake=types.SimpleNamespace(stop=stop,ensure_stopped=ensure)
  raw=json.dumps(m).encode()
  with patch.object(self.base,'locks',return_value=contextlib.nullcontext()),patch.object(self.base,'live_lock',return_value=contextlib.nullcontext()),patch.object(self.base,'model_release_lock',return_value=contextlib.nullcontext()),patch.object(self.base,'HermesAdmissionFence',Fence),patch.object(self.base,'inspect'),patch.object(self.base,'guards'),patch.object(self.base,'retirement'),patch.object(self.base,'directory_sync'),patch.object(bridge,'reviewed_marketing',return_value=fake),patch.object(self.base,'traffic_apply',side_effect=RuntimeError('fixture image failure')),patch.object(self.base,'traffic_restore'),patch.object(self.base,'restart_for'):
   with self.assertRaisesRegex(RuntimeError,'fixture image failure'):self.base.apply(m,self.out,sha(raw),raw,'nav-20261017T200001Z',self.h.root)
  self.assertEqual(events.count('reader-stopped'),2);self.assertIn('marketing-rechecked',events)
  for row in m['files']:self.assertEqual(sha((self.h.root/row['target'].lstrip('/')).read_bytes()),row['beforeSha256'])
  self.assertEqual(evidence.read_bytes(),b'private-evidence')

if __name__=='__main__':unittest.main()
