import unittest,tempfile,json,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'source/backend'),str(Path(__file__).resolve().parents[1]/'baseline')]
import hermes_worker as w
class Identity(unittest.TestCase):
 def test_explicit_selection_does_not_scan_embedded_background(self):
  v={'prompt':'背景含周报和竞品等历史词语，不能替代当前任务','skill_question':'经营管理台日更分析'}
  self.assertEqual(w.skill_question(v),'经营管理台日更分析')
  self.assertEqual(w.skill_question({'prompt':'旧周报任务'}),'旧周报任务')
 def test_admission_accepts_bounded_selection_only(self):
  with tempfile.TemporaryDirectory() as folder:
   old=w.ADMISSIONS;w.ADMISSIONS=Path(folder);self.addCleanup(lambda:setattr(w,'ADMISSIONS',old));sid='fc_'+'a'*64
   v={'session_id':sid,'token':'A'*50,'model':'deepseek-flash','prompt':'完整材料中提及周报','ready':True,'reasoning_effort':'high','report_mode':'kpi','skill_question':'管理台日更'}
   path=Path(folder)/(sid+'.json');path.write_text(json.dumps(v));self.assertEqual(w.admission(sid)['skill_question'],'管理台日更')
   for invalid in [None,{},'x','x'*601]:
    v['skill_question']=invalid;path.write_text(json.dumps(v))
    with self.assertRaisesRegex(PermissionError,'skill_question'):w.admission(sid)
if __name__=='__main__':unittest.main()
