import copy,hashlib,unittest
from unittest.mock import patch
import test_release


class AutonomousReleaseTests(unittest.TestCase):
    def setUp(self):
        f=test_release.ReleaseTests('test_wire_scope_is_exact_eight_and_legacy_scopes_still_validate');f.setUp();self.addCleanup(f.doCleanups)
        self.pub,self.stage=f.publisher,f.stage
        self.manifest=f.wire_manifest();self.manifest['scope']=self.pub.HERMES_AUTO_SCOPE
        self.manifest['files']=[]
        for rel,target in self.pub.HERMES_AUTO_TARGETS.items():
            path=self.stage/'candidate'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'autonomous release fixture')
            self.manifest['files'].append({'candidate':rel,'target':target,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'beforeSha256':None if rel.endswith(('/report_artifacts.py','/report_delivery.py')) else 'b'*64})
        protected={r['path']:r['sha256'] for r in self.manifest['unchangedRequired']}
        protected.update({p:'c'*64 for p in self.pub.HERMES_TARGETS.values()})
        protected.update({p:'d'*64 for p in set(self.pub.HERMES_DIRECT_TARGETS.values())|set(self.pub.HERMES_CAPABILITY_TARGETS.values())|self.pub.CAP_PROTECTED_SESSION})
        self.manifest['unchangedRequired']=[{'path':p,'sha256':h} for p,h in protected.items() if p not in self.pub.HERMES_AUTO_TARGETS.values()]

    def test_exact_eleven_targets_existing_baselines_and_all_protected_consumers(self):
        self.assertEqual(len(self.pub.validate(self.manifest,self.stage)),11)
        for row in self.manifest['unchangedRequired']:
            bad=copy.deepcopy(self.manifest);bad['unchangedRequired'].remove(row)
            with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)
        for row in self.manifest['files']:
            if row['beforeSha256'] is None:continue
            bad=copy.deepcopy(self.manifest);next(r for r in bad['files'] if r['candidate']==row['candidate'])['beforeSha256']=None
            with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)
        bad=copy.deepcopy(self.manifest);bad['files'].append(dict(bad['files'][0]))
        with self.assertRaises(ValueError):self.pub.validate(bad,self.stage)

    def test_autonomous_release_keeps_original_fence_and_restarts_only_fs(self):
        events=[]
        class Fence:
            def stop_then_unlock_database(self):events.append('old_fs_stopped')
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"ok":true,"status":"ready"}'
        with patch.object(self.pub.subprocess,'run',side_effect=lambda cmd,**kwargs:events.append(cmd)),patch.object(self.pub.urllib.request,'urlopen',return_value=Response()):self.pub.restart_for(self.manifest,Fence())
        self.assertEqual(events[0],'old_fs_stopped')
        self.assertIn(['systemctl','restart','fs-business-range.service'],events)
        self.assertNotIn(['systemctl','restart','fs-hermes-fc.service'],events)
        self.assertNotIn(['systemctl','restart','fc27-p2pah-session.service'],events)
        with self.assertRaises(ValueError):self.pub.restart_for(self.manifest,None)

    def test_each_autonomous_target_is_guarded_and_unsafe_owner_or_mode_is_rejected(self):
        from types import SimpleNamespace
        for target in self.pub.HERMES_AUTO_TARGETS.values():
            visited=[]
            class FakePath:
                parents=[]
                def __init__(self,value):self.value=value
                def exists(self):return True
                def stat(self):return SimpleNamespace(st_uid=1 if self.value==target else 0,st_gid=0,st_mode=0o644)
            def rooted(root,value):visited.append(value);return FakePath(value)
            with patch.object(self.pub,'hermes_quiescent'),patch.object(self.pub,'no_target_link'),patch.object(self.pub,'rooted',side_effect=rooted):
                with self.assertRaisesRegex(ValueError,'unsafe daily source boundary'):self.pub.guards(self.manifest,self.fixture_root if hasattr(self,'fixture_root') else self.stage)
            self.assertIn(target,visited)


if __name__=='__main__':unittest.main()
