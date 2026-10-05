import json,unittest
import test_release_gateway as original
from release_gateway import publish,Refused

class DependencyContractTests(original.ReleaseTests):
 def test_missing_empty_duplicate_wrong_path_and_bad_hash(self):
  for kind in ('missing','empty','duplicate','wrongpath','badhash'):
   with self.subTest(kind=kind):
    p=self.spec(2,'new2');spec=json.loads(p.read_text())
    if kind=='missing':del spec['dependencies']
    elif kind=='empty':spec['dependencies']=[]
    elif kind=='duplicate':spec['dependencies'][1]=spec['dependencies'][0]
    elif kind=='wrongpath':spec['dependencies'][0]['path']='/var/www/dashboard/fs-home/transactions/unknown.js'
    else:spec['dependencies'][0]['sha256']='not-a-sha'
    p.write_text(json.dumps(spec))
    with self.assertRaises(Refused):publish(self.root,p)
    self.assertEqual(self.live.read_bytes(),b'old')
 # Base cases run separately once.
 test_forward_old_concurrent_and_explicit_rollback=None
 test_stale_baseline_and_unmanaged_writes=None
 test_missing_contract_and_digest=None
 test_unknown_rollback_refused=None
 test_external_write_between_check_and_replace=None
 test_dependency_write_between_check_and_replace=None
if __name__=='__main__':unittest.main()
