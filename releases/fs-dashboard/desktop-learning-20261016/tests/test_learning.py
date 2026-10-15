import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import business_context as b
class Learning(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.fs=self.root/'fs';self.skills=self.root/'skills';self.fs.mkdir();self.skills.mkdir()
 def put(self,name,text):
  p=self.skills/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(0o644);return p
 def test_owner_documents_are_frozen_and_versioned(self):
  (self.fs/'desktop-business-context.md').write_text('当前业务规则')
  self.put(b.FILES[0],'新报告要求：先给判断和证据，再给可落地动作。')
  text,sha,rows=b.learning_bundle(self.fs,self.skills)
  self.assertIn('可落地动作',text);self.assertEqual(len(rows),2)
  self.assertEqual(b.learning_bundle(self.fs,self.skills)[1],sha)
  self.put(b.FILES[0],'新一版要求');self.assertNotEqual(b.learning_bundle(self.fs,self.skills)[1],sha)
 def test_samples_and_scripts_never_loaded(self):
  self.put('ops-report-brief/assets/example-week.json','PRIVATE_SAMPLE')
  self.put('ops-report-brief/scripts/build_weekly_brief.py','EXECUTE_ME')
  self.assertEqual(b.learning_bundle(self.fs,self.skills),('',None,[]))
 def test_symlink_and_oversize_fail_closed(self):
  p=self.put(b.FILES[0],'ok');p.unlink();p.symlink_to(self.fs/'outside')
  with self.assertRaisesRegex(ValueError,'symlink'):b.learning_bundle(self.fs,self.skills)
  p.unlink();p.write_bytes(b'x'*(b.MAX_FILE+1))
  with self.assertRaisesRegex(ValueError,'invalid'):b.learning_bundle(self.fs,self.skills)
 def test_profile_docs_not_modified(self):
  p=self.put(b.FILES[0],'immutable for task only');before=p.read_bytes();b.learning_bundle(self.fs,self.skills);self.assertEqual(p.read_bytes(),before)
if __name__=='__main__':unittest.main()
