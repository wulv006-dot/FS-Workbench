import copy,importlib.util,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];REPO=HERE.parents[2]
sys.path[:0]=[str(HERE/'source'),str(REPO/'mmoexp_google_data/details'),str(HERE.parent/'hermes-learning-loop-20261016/source')]
import report_tracks,boss_projection,boss_renderer

class KindTests(unittest.TestCase):
 def test_question_words_do_not_override_actual_period(self):
  for lo,hi,question,expected in [('2026-10-16','2026-10-16','请说明日报与周报和月报的区别','daily'),('2026-10-05','2026-10-11','请写本期周报','weekly'),('2026-10-01','2026-10-31','请写月报','monthly'),('2026-10-01','2026-10-16','请写月报','monthly'),('2026-09-20','2026-10-16','请写月报','investigation'),('2026-10-06','2026-10-12','请写自然周周报','investigation')]:
   with self.subTest(lo=lo,hi=hi):self.assertEqual(report_tracks.request_report_kind(dict(mode='investigation',start=lo,end=hi,question=question)),expected)
  self.assertEqual(report_tracks.request_report_kind(dict(mode='pricing',start='2026-10-16',end='2026-10-16',question='周报')),'pricing')

 def project(self,kind,start,end):
  result=dict(period=dict(start=start,end=end),snapshot_id='synthetic-frozen',summary='合成内容，只测类型边界',actions=[],report_kind=kind)
  frozen=copy.deepcopy(result);content=boss_projection.project(result,{},dict(captured_at='2026-10-17T00:00:00+00:00'),'a'*64)
  self.assertEqual(result,frozen);return content

 def test_legacy_conflict_is_investigation_and_visible_without_mutating_original(self):
  for kind,start,end in [('weekly','2026-10-16','2026-10-16'),('monthly','2026-10-02','2026-10-16')]:
   content=self.project(kind,start,end);self.assertEqual(content['report']['kind'],'investigation');self.assertIn('历史分类不一致',content['report']['status']);self.assertTrue(any('历史分类不一致' in g for g in content['gaps']));boss_renderer.validate(content,{})

 def test_correct_week_month_and_strict_renderer_are_retained(self):
  for kind,start,end in [('weekly','2026-10-05','2026-10-11'),('monthly','2026-09-01','2026-09-30'),('monthly','2026-10-01','2026-10-16')]:
   content=self.project(kind,start,end);self.assertEqual(content['report']['kind'],kind);self.assertNotIn('历史分类不一致',content['report']['status']);boss_renderer.validate(content,{})
  content=self.project('weekly','2026-10-16','2026-10-16');content['report']['kind']='weekly'
  with self.assertRaisesRegex(ValueError,'Weekly requires complete Monday'):boss_renderer.validate(content,{})

if __name__=='__main__':unittest.main()
