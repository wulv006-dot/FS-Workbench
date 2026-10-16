import sys,unittest,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'baseline')]
from boss_projection import project

class PartialProjection(unittest.TestCase):
 def evidence(self,day='2026-10-15',group=None):
  fact={'revenue_usd':'100','orders':2,'unpriced_orders':0}
  return {'source':'Admin FC支付明细','scope':'main','project':'FC27','snapshot_id':'fixture','timezone':'Asia/Shanghai','captured_at':'2026-10-16T00:00:00Z',
    'query':{'start':day,'end':day,'filters':{},'group_by':[group] if group else [],'page':1},
    'data':{'status':'available','coverage':{'paid_complete':True,'missing_days':[]},'pagination':{'complete':True,'page':1,'page_size':100,'total_groups':1 if group else 0},'filters_applied':{},'total':fact,
            'groups':[dict(fact,group={group:day if group=='day' else 'PS'})] if group else []}}
 def result(self):return {'period':{'start':'2026-10-15','end':'2026-10-15'},'snapshot_id':'fixture','summary':'本期有效，缺对照单独说明。','research_text':'## 关键判断\n本期有效。','limitations':[]}
 def test_current_survives_missing_comparison(self):
  evidence={'ev_'+'a'*24:self.evidence(),'ev_'+'b'*24:self.evidence(group='platform'),'ev_'+'c'*24:self.evidence(group='day')}
  content=project(self.result(),evidence,{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(content['metrics'][0]['value'],'$100.00')
  charts={v['id']:v for v in content['charts']}
  self.assertTrue(charts['platform']['rows']);self.assertTrue(charts['daily']['rows'])
  self.assertIsNone(charts['platform']['rows'][0]['previous'])
 def test_comparison_conflict_does_not_erase_current(self):
  result=self.result();result['research_text']='对照：2026-10-08\n对照：2026-10-14\n## 关键判断\n本期有效。'
  c=project(result,{'ev_'+'a'*24:self.evidence()},{'artifact_written_at':'2026-10-16T00:01:00Z'},'a'*64)
  self.assertEqual(c['metrics'][0]['value'],'$100.00');self.assertEqual(c['metrics'][0]['previous'],'未提供')

if __name__=='__main__':unittest.main()
