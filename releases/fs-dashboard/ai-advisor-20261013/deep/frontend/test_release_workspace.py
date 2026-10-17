"""Focused fault/CAS tests in a temporary root, no production runtime or requests."""
import base64, contextlib, copy, hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import release_workspace as r

HERE=Path(__file__).resolve().parent

class WorkspaceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.m=json.loads((HERE/'release-manifest.json').read_text(encoding='utf-8'));self.m['releaseReady']=True
        live=json.loads((HERE/'baseline-fixture.json').read_text(encoding='utf-8'))
        for name in r.MUTABLE:
            p=r.at(self.root,name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(base64.b64decode(live['files'][name]['bytesB64']))
        self.raw=json.dumps(self.m).encode();self.sha=r.hashed(self.raw);self.commands=[]
        self.guard_failure=False
        def guards(*args):
            if self.guard_failure:raise ValueError('simulated profit peer drift')
        self.patches=[patch.object(r,'guards',guards),patch.object(r,'runtime',self.runtime)]
        # Ownership checks require actual POSIX/root in Linux QA; Windows syntax run is not Linux proof.
        if __import__('os').name=='nt':
            import release_navigation
            self.patches.extend([patch.object(r,'trusted',lambda *a:None),patch.object(r,'locks',lambda *a:contextlib.nullcontext()),patch.object(r,'directory_sync',lambda *a:None),patch.object(release_navigation,'directory_sync',lambda *a:None)])
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def runtime(self,argv):self.commands.append(argv);return {'returncode':0}
    def apply(self):return r.apply(self.m,HERE,self.raw,self.sha,self.root)
    def backup(self):return r.at(self.root,r.BACKUPS+'/'+self.m['releaseId'])
    def assert_restored(self):
        for row in self.m['targets']:self.assertEqual(r.digest(r.at(self.root,row['target'])),row['beforeSha256'])
        self.assertFalse(r.at(self.root,'/var/www/dashboard/index.html').exists())
    def test_success_and_exact_inverse_retains_static_history(self):
        result=self.apply();self.assertIn('awaiting-real',result['status']);r.rollback(self.backup(),self.sha,self.root);self.assert_restored()
        self.assertEqual(self.commands,[['nginx','-t'],['systemctl','reload','nginx'],['nginx','-t'],['systemctl','reload','nginx']])
        for row in self.m['immutableAssets']:self.assertEqual(r.digest(r.at(self.root,row['target'])),row['sha256'])
    def test_false_ready_refuses_all_writes(self):
        m=copy.deepcopy(self.m);m['releaseReady']=False
        with self.assertRaises(ValueError):r.apply(m,HERE,self.raw,self.sha,self.root)
        self.assertFalse(r.at(self.root,r.BACKUPS).exists());self.assert_restored()
    def test_wrong_manifest_approval_refused(self):
        with self.assertRaises(ValueError):r.apply(self.m,HERE,self.raw,'0'*64,self.root)
        self.assertFalse(r.at(self.root,r.BACKUPS).exists())
    def test_target_drift_refused_before_backup(self):
        r.at(self.root,r.FRAGMENT).write_bytes(b'peer')
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(r.at(self.root,r.FRAGMENT).read_bytes(),b'peer');self.assertFalse(r.at(self.root,r.BACKUPS).exists())
    def test_native_pending_is_not_cleared(self):
        p=r.pending(self.root);p.parent.mkdir(parents=True);p.write_text('{}')
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(p.read_text(),'{}');self.assert_restored()
    def test_rename_then_fsync_failure_recovers_by_intent(self):
        actual=r.atomic;fired=False
        def faulty(path,data,mode=0o644):
            nonlocal fired
            actual(path,data,mode)
            if str(path)==str(r.at(self.root,r.FRAGMENT)) and not fired:fired=True;raise OSError('post rename failure')
        with patch.object(r,'atomic',faulty):
            with self.assertRaises(OSError):self.apply()
        self.assert_restored();self.assertFalse(r.pending(self.root).exists())
    def test_activation_reload_failure_restores_both_entries(self):
        count=0
        def faulty(argv):
            nonlocal count
            self.commands.append(argv)
            if argv==['systemctl','reload','nginx']:
                count+=1
                if count==1:raise RuntimeError('reload failed')
        with patch.object(r,'runtime',faulty):
            with self.assertRaises(RuntimeError):self.apply()
        self.assert_restored();self.assertEqual(count,2)
    def test_rollback_peer_drift_refuses_before_any_restore(self):
        self.apply();r.at(self.root,r.FRAGMENT).write_bytes(b'peer')
        fragment=r.at(self.root,r.FRAGMENT).read_bytes()
        with self.assertRaises(ValueError):r.rollback(self.backup(),self.sha,self.root)
        self.assertEqual(r.at(self.root,r.FRAGMENT).read_bytes(),fragment);self.assertEqual(r.at(self.root,r.FRAGMENT).read_bytes(),b'peer')
    def test_profit_guard_drift_stops_and_keeps_pending(self):
        actual=r.atomic
        def drift(path,data,mode=0o644):
            actual(path,data,mode)
            if str(path)==str(r.at(self.root,r.FRAGMENT)):self.guard_failure=True
        with patch.object(r,'atomic',drift):
            with self.assertRaises(ValueError):self.apply()
        self.assertTrue(r.pending(self.root).exists());self.assertEqual(r.digest(r.at(self.root,r.FRAGMENT)),self.m['targets'][0]['sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
