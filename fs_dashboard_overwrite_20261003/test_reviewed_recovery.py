from pathlib import Path
import json,hashlib,shutil,unittest
import release_gateway
import test_release_gateway as original
HTML=original.HTML
sha=original.sha
from release_gateway import publish,Lock,Refused

class ReviewedRecoveryTests(original.ReleaseTests):
 def setUp(self):
  super().setUp()
  self.body=HTML+'<meta name="fs-dashboard-release" content="known-v3">'
  self.state=publish(self.root,self.spec(2,'known-v3',self.body))
  self.live.write_text('unmanaged legacy template')
  self.backup=self.root/'var/backups/fs-dashboard-incident-test';self.backup.mkdir(parents=True)
  shutil.copyfile(self.live,self.backup/'index.html')
  (self.backup/'ledger.json').write_text(json.dumps(self.state))
  self.manifest=self.spec(3,'restore-v4',self.body.replace('known-v3','restore-v4'))
  m=json.loads(self.manifest.read_text());m['reviewedUnmanagedRecovery']={'restoreFromReleaseId':'known-v3','expectedLedgerSha256':self.state['sha256'],'incidentBackup':'/var/backups/fs-dashboard-incident-test'}
  m['dependencies']=[]
  for n, path in enumerate(sorted(release_gateway.REQUIRED_DEPENDENCIES)):
   dep=self.root/path.lstrip('/');dep.parent.mkdir(parents=True,exist_ok=True);dep.write_text('valid'+str(n));m['dependencies'].append({'path':path,'sha256':sha(dep.read_bytes())})
  self.manifest.write_text(json.dumps(m))
 def mutate(self,fn):
  m=json.loads(self.manifest.read_text());fn(m);self.manifest.write_text(json.dumps(m))
 def test_reviewed_recovery_success(self):
  result=publish(self.root,self.manifest,recovery=True)
  self.assertEqual(result['releaseId'],'restore-v4');self.assertIn('reviewedUnmanagedRecovery',result)
  self.assertEqual(self.live.read_text(),self.body.replace('known-v3','restore-v4'))
 def test_requires_explicit_flag(self):
  with self.assertRaisesRegex(Refused,'unmanaged'):publish(self.root,self.manifest)
 def test_stale_live_refused(self):
  self.live.write_text('a later writer')
  with self.assertRaisesRegex(Refused,'baseline'):publish(self.root,self.manifest,recovery=True)
 def test_stale_ledger_refused(self):
  self.mutate(lambda m:m['reviewedUnmanagedRecovery'].update(expectedLedgerSha256='wrong'))
  with self.assertRaisesRegex(Refused,'latest recorded'):publish(self.root,self.manifest,recovery=True)
 def test_backup_mismatch_refused(self):
  (self.backup/'index.html').write_text('wrong backup')
  with self.assertRaisesRegex(Refused,'incident backup'):publish(self.root,self.manifest,recovery=True)
 def test_arbitrary_payload_refused(self):
  staged=self.stage/'dashboard.html';staged.write_text(staged.read_text()+'arbitrary feature')
  self.mutate(lambda m:m.update(sha256=sha(staged.read_bytes())))
  with self.assertRaisesRegex(Refused,'exactly match'):publish(self.root,self.manifest,recovery=True)
 def test_pending_refused(self):
  (self.root/'var/lib/fs-dashboard-release/pending.json').write_text('{}')
  with self.assertRaisesRegex(Refused,'pending'):publish(self.root,self.manifest,recovery=True)
 def test_dependency_changed_refused(self):
  (self.root/'var/www/dashboard/fs-home/transactions/snapshot-client.js').write_text('changed')
  with self.assertRaisesRegex(Refused,'dependency changed'):publish(self.root,self.manifest,recovery=True)
 def test_concurrent_refused(self):
  with Lock(self.root/'var/lock/fs-dashboard-release.lock'):
   with self.assertRaisesRegex(Refused,'lock'):publish(self.root,self.manifest,recovery=True)
 def test_normal_publication_cannot_use_recovery_flag(self):
  self.live.write_text(self.body);self.mutate(lambda m:m.update(expectedLiveSha256=self.state['sha256']))
  with self.assertRaisesRegex(Refused,'only for an unmanaged'):publish(self.root,self.manifest,recovery=True)
 # Original gateway tests run independently from this incident-specific setup.
 test_forward_old_concurrent_and_explicit_rollback=None
 test_stale_baseline_and_unmanaged_writes=None
 test_missing_contract_and_digest=None
 test_unknown_rollback_refused=None
 test_external_write_between_check_and_replace=None
 test_dependency_write_between_check_and_replace=None

if __name__=='__main__':unittest.main()
