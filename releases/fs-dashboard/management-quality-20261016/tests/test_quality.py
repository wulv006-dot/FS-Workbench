import sys,unittest
from pathlib import Path
base=Path(__file__).resolve().parents[2]/'management-v2-20261015/baseline'
if not base.exists():base=Path(__file__).resolve().parents[2]/'fs-management-rebuild-20261015/baseline'
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'source'),str(base)]
import management_context as m
class Quality(unittest.TestCase):
 def test_middle_prose_quotes_and_structured_values_preserved(self):
  raw='{"report_contract":"fs-report-v2","summary":"结论","research_text":"这是"原话"，不作因果。\\n第二行","findings":[],"numeric_checks":{"target_revenue":2}}'
  v=m.decode_management_output(raw);self.assertEqual(v['research_text'],'这是"原话"，不作因果。\n第二行');self.assertEqual(v['numeric_checks']['target_revenue'],2)
  with self.assertRaises(ValueError):m.decode_management_output(raw.replace('"target_revenue":2','"target_revenue":bad'))
 def test_three_day_scenario_is_not_single_day(self):
  f={'period':{'end':'2026-10-14','month_days':31,'observed':14}};p={'profile':'TEST','month':{'values':{'rev':1000}},'daily':[{'d':'2026-10-12','rev':300},{'d':'2026-10-13','rev':200},{'d':'2026-10-14','rev':100}]}
  v=m.recent_three_day(f,[p]);self.assertEqual(v['dailyMeanRevenue'],200);self.assertEqual(v['monthEndScenarioRevenue'],4400)
  p['daily'].pop();v=m.recent_three_day(f,[p]);self.assertFalse(v['complete']);self.assertIsNone(v['dailyMeanRevenue']);self.assertIsNone(v['monthEndScenarioRevenue']);self.assertEqual(v['knownRevenueLowerBound'],500)
if __name__=='__main__':unittest.main()
