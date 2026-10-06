"""Synthetic 323-file trees and mocked child commands only; no business suite runs."""
from pathlib import Path
import hashlib,importlib.util,json,os,subprocess,sys,tempfile,types,unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('checker_contract_under_test',REPO/'tools/candidate_tree_contract.py')
contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
def sha(b):return hashlib.sha256(b).hexdigest()

class CheckerContract(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='fs-checker-contract-test-');self.addCleanup(self.temp.cleanup)
  self.repo=Path(self.temp.name)/'repo';self.repo.mkdir()
  contents={
   'tools/check_candidate.py':(REPO/'tools/check_candidate.py').read_bytes(),
   'tools/candidate_tree_contract.py':(REPO/'tools/candidate_tree_contract.py').read_bytes(),
   'fc27_ops_cloud/data/fc-analytics.js':b'',
   'fc_calendar_trim_20261004/test_calendar.cjs':b'',
   'tests/integration/test_fc_rev25_matrix.py':b'# synthetic; never executed\n'}
  while len(contents)<321:contents['fixture/file-'+str(len(contents))+'.txt']=b'synthetic\n'
  self.rows=[]
  for rel,b in sorted(contents.items()):
   p=self.repo/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
   self.rows.append({'path':rel,'bytes':len(b),'sha256':sha(b),'gitBlobSha1':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'gitMode':'100644'})
  self.allow={'manifestSelfExclusions':list(contract.MANIFEST_PATHS),'files':self.rows}
  self.write_allow()
 def write_allow(self):
  self.allow.update(contentFiles=len(self.allow['files']),contentBytes=sum(r['bytes'] for r in self.allow['files']),contentSetSha256=sha(json.dumps(self.allow['files'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()))
  for rel in contract.MANIFEST_PATHS:
   p=self.repo/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(self.allow,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 def extra(self,rel):
  p=self.repo/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic unexpected',encoding='utf-8')
 def directory_link(self,link,target):
  try:link.symlink_to(target,target_is_directory=True)
  except OSError as error:
   if os.name=='nt':self.skipTest('Windows directory symlink unavailable: '+str(error))
   raise
  self.addCleanup(lambda:link.unlink() if link.is_symlink() else None)
 def cli(self,mode='tree'):
  if mode=='tree':
   command=[sys.executable,'-B',str(self.repo/'tools/check_candidate.py'),'--tree-only']
  else:
   wrapper=r'''
import pathlib,sys,runpy,tempfile,json,types,subprocess
from unittest.mock import patch
repo=pathlib.Path(sys.argv[1]);mode=sys.argv[2]
output=repo.parent/'checks-result';output.mkdir()
def fake(command,**kwargs):
    if len(command)>2 and command[1:3]==['-B','-c']:
        group=command[-1];failure=group=='engine' and mode in ('test-fail','lying-child','malformed-child')
        stdout='invalid result' if failure and mode=='malformed-child' else json.dumps({'check':group,'passed':not failure or mode=='lying-child','testsRun':1,'output':'synthetic child; no business execution'})
        return types.SimpleNamespace(returncode=9 if failure and mode=='lying-child' else 0,stdout=stdout,stderr='synthetic child')
    failure=mode=='node-fail' and command[0]=='node' and '--check' not in command
    return types.SimpleNamespace(returncode=7 if failure else 0,stdout='',stderr='synthetic child')
sys.path.insert(0,str(repo/'tools'));sys.argv=[str(repo/'tools/check_candidate.py')]
with patch('subprocess.run',side_effect=fake),patch('tempfile.mkdtemp',return_value=str(output)):
    runpy.run_path(sys.argv[0],run_name='__main__')
'''
   command=[sys.executable,'-B','-c',wrapper,str(self.repo),mode]
  env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
  return subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=20,env=env)
 def test_exact_legal_323_tree_and_both_self_exclusions(self):
  self.assertEqual(len(contract.validate_tree(self.repo)),321)
  r=self.cli();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['treeFiles'],323)
 def test_root_git_metadata_only_is_outside_upload_tree(self):
  self.extra('.git/HEAD');self.assertEqual(len(contract.validate_tree(self.repo)),321)
 def test_recorded_windows_path_order_is_not_resorted_as_unicode(self):
  from pathlib import PureWindowsPath
  row=next(r for r in self.rows if r['path']=='fixture/file-5.txt')
  (self.repo/row['path']).rename(self.repo/'Z-source.txt');row['path']='Z-source.txt'
  self.allow['files']=sorted(self.rows,key=lambda r:PureWindowsPath(r['path']))
  self.assertNotEqual(self.allow['files'],sorted(self.rows,key=lambda r:r['path']))
  self.write_allow();self.assertEqual(len(contract.validate_tree(self.repo)),321)
 def test_unexpected_provenance_file_is_not_implicitly_allowed(self):
  self.extra('docs/provenance/unexpected.json')
  with self.assertRaisesRegex(ValueError,'allowlist differs'):contract.validate_tree(self.repo)
  self.assertNotEqual(self.cli().returncode,0)
 def test_other_unexpected_path_rejected(self):
  self.extra('unexpected.txt')
  with self.assertRaisesRegex(ValueError,'allowlist differs'):contract.validate_tree(self.repo)
 def test_previous_broad_ignored_directories_have_no_exemption(self):
  for rel in ['.checks/arbitrary.py','.testdeps/arbitrary.py','.venv/arbitrary.py','nested/__pycache__/arbitrary.py','nested/.git/arbitrary.py']:
   with self.subTest(rel=rel):
    self.extra(rel)
    with self.assertRaises(ValueError):contract.validate_tree(self.repo)
    (self.repo/rel).unlink()
    # Keep the fixture clean: newly created directories are not allowlisted.
    parent=(self.repo/rel).parent
    while parent!=self.repo and not any(parent.iterdir()):
     parent.rmdir();parent=parent.parent
 def test_unlisted_empty_directory_rejected(self):
  (self.repo/'unexpected-empty').mkdir()
  with self.assertRaisesRegex(ValueError,'unlisted candidate directory'):contract.validate_tree(self.repo)
  self.assertEqual(self.cli().returncode,1)
 def test_unlisted_directory_symlinks_populated_empty_and_dangling_rejected(self):
  for kind in ['populated','empty','dangling']:
   with self.subTest(kind=kind):
    target=Path(self.temp.name)/('outside-'+kind)
    if kind!='dangling':target.mkdir()
    if kind=='populated':(target/'not-allowed.txt').write_text('synthetic')
    link=self.repo/('unexpected-link-'+kind);self.directory_link(link,target)
    with self.assertRaisesRegex(ValueError,'linked candidate path'):contract.validate_tree(self.repo)
    self.assertEqual(self.cli().returncode,1)
    link.unlink()
 def test_listed_parent_directory_symlink_rejected(self):
  target=Path(self.temp.name)/'moved-fixture';(self.repo/'fixture').rename(target)
  link=self.repo/'fixture';self.directory_link(link,target)
  with self.assertRaisesRegex(ValueError,'linked candidate path'):contract.validate_tree(self.repo)
  self.assertEqual(self.cli().returncode,1)
 def test_root_git_directory_link_is_not_exempt(self):
  target=Path(self.temp.name)/'fake-git';target.mkdir()
  self.directory_link(self.repo/'.git',target)
  with self.assertRaisesRegex(ValueError,'linked candidate path'):contract.validate_tree(self.repo)
  self.assertEqual(self.cli().returncode,1)
 def test_linked_repository_root_rejected(self):
  link=Path(self.temp.name)/'repo-link';self.directory_link(link,self.repo)
  with self.assertRaisesRegex(ValueError,'linked candidate path'):contract.validate_tree(link)
 @unittest.skipUnless(os.name=='nt','Windows junction native test requires Windows')
 def test_windows_junction_unlisted_and_listed_directory_rejected(self):
  for kind in ['populated','empty','listed-parent']:
   with self.subTest(kind=kind):
    target=Path(self.temp.name)/('junction-target-'+kind)
    link=self.repo/('unexpected-junction-'+kind)
    if kind=='listed-parent':
     (self.repo/'fixture').rename(target);link=self.repo/'fixture'
    else:
     target.mkdir()
     if kind=='populated':(target/'not-allowed.txt').write_text('synthetic')
    result=subprocess.run(['cmd','/d','/c','mklink','/J',str(link),str(target)],capture_output=True,timeout=10)
    self.assertEqual(result.returncode,0,result.stderr)
    try:
     with self.assertRaisesRegex(ValueError,'linked candidate path'):contract.validate_tree(self.repo)
     self.assertEqual(self.cli().returncode,1)
    finally:os.rmdir(link)  # Remove junction itself, never recurse into its target.
    if kind=='listed-parent':target.rename(self.repo/'fixture')
 def test_reparse_point_rejected_even_without_symlink_mode(self):
  import stat
  fake=types.SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_file_attributes=0x400)
  with patch.object(Path,'lstat',return_value=fake):
   with self.assertRaisesRegex(ValueError,'linked candidate path'):contract._unlinked_stat(self.repo/'synthetic-junction')
 def test_unreadable_listed_directory_enumeration_fails_closed(self):
  def broken_walk(repo,followlinks=False,onerror=None):
   yield str(repo),['fixture'],[]
   onerror(PermissionError('synthetic unreadable allowlisted directory'))
  with patch.object(contract.os,'walk',side_effect=broken_walk):
   with self.assertRaisesRegex(PermissionError,'unreadable'):contract.validate_tree(self.repo)
  wrapper=r'''
import pathlib,sys,runpy,os
from unittest.mock import patch
repo=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(repo/'tools'));sys.argv=[str(repo/'tools/check_candidate.py'),'--tree-only']
def broken_walk(repo,followlinks=False,onerror=None):
    yield str(repo),['fixture'],[]
    onerror(PermissionError('synthetic unreadable allowlisted directory'))
with patch('os.walk',side_effect=broken_walk):runpy.run_path(sys.argv[0],run_name='__main__')
'''
  result=subprocess.run([sys.executable,'-B','-c',wrapper,str(self.repo)],capture_output=True,text=True,timeout=20)
  self.assertEqual(result.returncode,1,result.stderr)
  self.assertIn('unreadable',result.stderr)
 @unittest.skipUnless(os.name=='posix','POSIX executable-bit check; NTFS stat cannot prove Git mode')
 def test_promised_git_executable_mode_is_enforced(self):
  p=self.repo/'fixture/file-5.txt';row=next(r for r in self.rows if r['path']=='fixture/file-5.txt')
  p.chmod(0o755)
  with self.assertRaisesRegex(ValueError,'executable mode differs'):contract.validate_tree(self.repo)
  self.assertEqual(self.cli().returncode,1)
  row['gitMode']='100755';self.write_allow();self.assertEqual(len(contract.validate_tree(self.repo)),321)
  p.chmod(0o644)
  with self.assertRaisesRegex(ValueError,'executable mode differs'):contract.validate_tree(self.repo)
 @unittest.skipUnless(os.name=='posix','Unpromised POSIX executable-bit case requires POSIX')
 def test_absent_git_mode_makes_no_executable_promise(self):
  p=self.repo/'fixture/file-5.txt';row=next(r for r in self.rows if r['path']=='fixture/file-5.txt')
  row.pop('gitMode');self.write_allow();p.chmod(0o755)
  self.assertEqual(len(contract.validate_tree(self.repo)),321)
 def test_invalid_promised_git_mode_rejected(self):
  self.rows[0]['gitMode']='120000';self.write_allow()
  with self.assertRaisesRegex(ValueError,'unsupported source mode'):contract.validate_tree(self.repo)
 def test_cli_reports_mode_validation_platform_limits(self):
  result=self.cli();self.assertEqual(result.returncode,0,result.stderr)
  info=json.loads(result.stdout)['gitModeValidation'];self.assertEqual(info['promisedFiles'],321)
  self.assertIn('POSIX executable bits checked' if os.name=='posix' else 'Windows executable bits unverified',info['status'])
 def test_missing_content_file_rejected(self):
  (self.repo/self.rows[-1]['path']).unlink()
  with self.assertRaisesRegex(ValueError,'allowlist differs'):contract.validate_tree(self.repo)
 def test_missing_provenance_manifest_rejected(self):
  (self.repo/contract.MANIFEST_PATHS[1]).unlink()
  with self.assertRaises(ValueError):contract.validate_tree(self.repo)
 def test_hash_drift_same_size_and_nonzero_cli(self):
  p=self.repo/'fixture/file-5.txt';p.write_bytes(b'XXXXXXXXXX')
  self.assertEqual(len(p.read_bytes()),next(r['bytes'] for r in self.rows if r['path']=='fixture/file-5.txt'))
  with self.assertRaisesRegex(ValueError,'candidate changed'):contract.validate_tree(self.repo)
  self.assertNotEqual(self.cli().returncode,0)
 def test_mirror_manifest_disagreement_rejected(self):
  p=self.repo/contract.MANIFEST_PATHS[1];x=json.loads(p.read_text());x['contentFiles']=320;p.write_text(json.dumps(x))
  with self.assertRaisesRegex(ValueError,'disagree'):contract.validate_tree(self.repo)
 def test_extra_or_duplicate_self_exclusion_rejected(self):
  for value in [list(contract.MANIFEST_PATHS)+['unexpected.txt'],[contract.MANIFEST_PATHS[0]]*2]:
   with self.subTest(value=value):
    self.allow['manifestSelfExclusions']=value;self.write_allow()
    with self.assertRaisesRegex(ValueError,'two exact'):contract.validate_tree(self.repo)
 def test_manifest_in_content_rows_rejected(self):
  self.allow['files'].append({'path':contract.MANIFEST_PATHS[0],'bytes':0,'sha256':sha(b'')});self.write_allow()
  with self.assertRaisesRegex(ValueError,'self-excluded'):contract.validate_tree(self.repo)
 def test_noncanonical_or_duplicate_content_paths_rejected(self):
  original=[dict(r) for r in self.rows]
  for bad in ['../outside','/outside','fixture/../outside','fixture\\outside','fixture//outside','C:/outside']:
   with self.subTest(path=bad):
    self.allow['files']=[dict(r) for r in original];self.allow['files'][0]['path']=bad;self.write_allow()
    with self.assertRaises(ValueError):contract.validate_tree(self.repo)
  self.allow['files']=[dict(r) for r in original]+[dict(original[0])];self.write_allow()
  with self.assertRaisesRegex(ValueError,'duplicate'):contract.validate_tree(self.repo)
 def test_count_and_digest_metadata_must_match(self):
  for key,value in [('contentFiles',320),('contentBytes',0),('contentSetSha256','0'*64)]:
   with self.subTest(key=key):
    self.write_allow();self.allow[key]=value
    for rel in contract.MANIFEST_PATHS:(self.repo/rel).write_text(json.dumps(self.allow),encoding='utf-8')
    with self.assertRaises(ValueError):contract.validate_tree(self.repo)
 def test_actual_cli_success_returns_zero_with_mocked_children(self):
  r=self.cli('success');self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)['passed'])
 def test_actual_cli_failed_test_exits_nonzero(self):
  r=self.cli('test-fail');self.assertEqual(r.returncode,1,r.stderr);self.assertFalse(json.loads(r.stdout)['passed'])
 def test_actual_cli_nonzero_child_cannot_claim_passed_true(self):
  r=self.cli('lying-child');self.assertEqual(r.returncode,1,r.stderr);self.assertFalse(json.loads(r.stdout)['passed'])
 def test_actual_cli_malformed_child_result_exits_nonzero(self):
  r=self.cli('malformed-child');self.assertEqual(r.returncode,1,r.stderr);self.assertFalse(json.loads(r.stdout)['passed'])
 def test_actual_cli_node_failure_exits_nonzero(self):
  r=self.cli('node-fail');self.assertEqual(r.returncode,1,r.stderr);self.assertFalse(json.loads(r.stdout)['passed'])
 def test_result_schema_requires_explicit_boolean_pass(self):
  for text,code in [('true',0),('{}',0),('{"passed":"true"}',0),('{"passed":true}',5)]:
   obj=contract.decode_unit_result(types.SimpleNamespace(stdout=text,stderr='synthetic',returncode=code),'synthetic')
   self.assertFalse(obj['passed'])
  self.assertEqual(contract.result_exit_code([]),1)
  self.assertEqual(contract.result_exit_code([{'passed':True,'returncode':2}]),1)

if __name__=='__main__':unittest.main(verbosity=2)
