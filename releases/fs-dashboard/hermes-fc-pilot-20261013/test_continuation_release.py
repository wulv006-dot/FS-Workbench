import copy,hashlib,unittest
from unittest.mock import patch
import test_report_release


class ContinuationReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_report_release.ReportReleaseTests('test_exact_six_scope_protects_existing_consumers_and_existing_source_baselines')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.pub=self.fixture.pub;self.stage=self.fixture.stage
        self.manifest=copy.deepcopy(self.fixture.manifest);self.manifest['scope']=self.pub.HERMES_CONTINUE_SCOPE
        before={row['path']:row['sha256'] for row in self.manifest['unchangedRequired']}
        before.update({row['target']:row['sha256'] for row in self.manifest['files']})
        self.manifest['files']=[]
        for rel,target in self.pub.HERMES_CONTINUE_TARGETS.items():
            path=self.stage/'candidate'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'continuation fixture')
            self.manifest['files'].append({'candidate':rel,'target':target,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'beforeSha256':None if rel.endswith('/continuation.py') else before[target]})
        self.manifest['unchangedRequired']=[{'path':p,'sha256':h} for p,h in before.items() if p not in self.pub.HERMES_CONTINUE_TARGETS.values()]

    def test_exact_three_targets_and_all_existing_direct_capability_report_sources_protected(self):
        self.assertEqual(len(self.pub.validate(self.manifest,self.stage)),3)
        for row in self.manifest['unchangedRequired']:
            bad=copy.deepcopy(self.manifest);bad['unchangedRequired'].remove(row)
            with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)
        for row in self.manifest['files']:
            if row['candidate'].endswith('/continuation.py'):continue
            bad=copy.deepcopy(self.manifest);next(r for r in bad['files'] if r['candidate']==row['candidate'])['beforeSha256']=None
            with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)

    def test_same_fence_and_only_original_fs_restart(self):
        events=[]
        class Fence:
            def stop_then_unlock_database(self):events.append('old_fs_stopped')
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"ok":true,"status":"ready"}'
        with patch.object(self.pub.subprocess,'run',side_effect=lambda command,**kwargs:events.append(command)),patch.object(self.pub.urllib.request,'urlopen',return_value=Response()):
            self.pub.restart_for(self.manifest,Fence())
        self.assertEqual(events[0],'old_fs_stopped')
        self.assertEqual([e for e in events if isinstance(e,list) and e[:2]==['systemctl','restart']],[['systemctl','restart','fs-business-range.service']])
