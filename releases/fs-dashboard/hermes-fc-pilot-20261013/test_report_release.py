import copy,hashlib,json,unittest
from unittest.mock import patch
import test_release


class ReportReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_release.ReleaseTests('test_wire_scope_is_exact_eight_and_legacy_scopes_still_validate');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.pub=self.fixture.publisher;self.stage=self.fixture.stage
        self.manifest=self.fixture.wire_manifest();self.manifest['scope']=self.pub.HERMES_REPORT_SCOPE
        self.manifest['files']=[]
        for rel,target in self.pub.HERMES_REPORT_TARGETS.items():
            path=self.stage/'candidate'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'reviewed report fixture')
            self.manifest['files'].append({'candidate':rel,'target':target,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'beforeSha256':None if rel.endswith('/report_html.py') else 'b'*64})
        protected={r['path']:r['sha256'] for r in self.manifest['unchangedRequired']}
        protected.update({p:'c'*64 for p in self.pub.HERMES_TARGETS.values()})
        protected.update({p:'d'*64 for p in set(self.pub.HERMES_DIRECT_TARGETS.values())|set(self.pub.HERMES_CAPABILITY_TARGETS.values())|self.pub.CAP_PROTECTED_SESSION})
        self.manifest['unchangedRequired']=[{'path':p,'sha256':h} for p,h in protected.items() if p not in self.pub.HERMES_REPORT_TARGETS.values()]
    def test_exact_six_scope_protects_existing_consumers_and_existing_source_baselines(self):
        self.assertEqual(len(self.pub.validate(self.manifest,self.stage)),6)
        for row in self.manifest['unchangedRequired']:
            bad=copy.deepcopy(self.manifest);bad['unchangedRequired'].remove(row)
            with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)
        for row in self.manifest['files']:
            if row['candidate'].endswith('/report_html.py'):continue
            bad=copy.deepcopy(self.manifest);next(r for r in bad['files'] if r['candidate']==row['candidate'])['beforeSha256']=None
            with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)
        bad=copy.deepcopy(self.manifest);bad['files'].append(copy.deepcopy(bad['files'][0]))
        with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)
    def test_report_release_uses_fence_and_only_restarts_original_fs(self):
        events=[]
        class Fence:
            def stop_then_unlock_database(self):events.append('old_fs_stopped')
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"ok":true,"status":"ready"}'
        def run(command,**kwargs):events.append(command)
        with patch.object(self.pub.subprocess,'run',side_effect=run),patch.object(self.pub.urllib.request,'urlopen',return_value=Response()):
            self.pub.restart_for(self.manifest,Fence())
        self.assertEqual(events[0],'old_fs_stopped')
        self.assertIn(['systemctl','restart','fs-business-range.service'],events)
        self.assertNotIn(['systemctl','restart','fs-hermes-fc.service'],events)
        self.assertNotIn(['systemctl','restart','fc27-p2pah-session.service'],events)
        with self.assertRaises(ValueError):self.pub.restart_for(self.manifest,None)


if __name__=='__main__':unittest.main()
