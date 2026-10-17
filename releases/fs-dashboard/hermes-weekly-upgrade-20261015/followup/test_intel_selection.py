"""Synthetic intel selection checks; no live reports, sibling imports or model calls."""
import ast,copy,importlib.util,unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
SOURCE=HERE/'source/report_semantics.py'
spec=importlib.util.spec_from_file_location('selected_intel_semantics',SOURCE)
semantics=importlib.util.module_from_spec(spec);spec.loader.exec_module(semantics)
EID='ev_'+'a'*24
STAMP='2026-01-15T00:00:00Z'

def fixture():
    documents=[{'source_url':'https://www.ea.com/games/ea-sports-fc/fc-27/news/synthetic-'+str(i),
                'observed_at':STAMP,'published_at':'2026-01-08T00:00:00Z',
                'title':'Synthetic source article '+str(i),'text':'Synthetic official source content used only for this test.'} for i in range(6)]
    result={'period':{'start':'2026-01-05','end':'2026-01-11'},'intel':[
        {'title':'中文消息'+str(i),'fact':'中文来源摘要'+str(i),'hypothesis':'中文业务联系待核','action':'中文行动建议未执行',
         'source':'EA 官方','published_at':'2026-01-08','event_at':'未单独核验','applies':'报告期背景',
         'url':documents[i]['source_url'],'retrieved_at':STAMP,'evidence_ids':[EID]} for i in range(3)]}
    return result,{EID:{'captured_at':STAMP,'data':{'documents':documents}}}

class IntelSelectionTests(unittest.TestCase):
    def test_three_selected_cards_are_not_expanded_to_six(self):
        result,evidence=fixture();before=copy.deepcopy((result,evidence))
        accepted,pending,note=semantics.intelligence(result,evidence)
        self.assertEqual(len(accepted),3);self.assertEqual(pending,[])
        self.assertTrue(all(row['fact'].startswith('中文来源摘要') for row in accepted))
        self.assertTrue(all('extraction' not in row for row in accepted))
        self.assertIn('已整理 3 条',note);self.assertEqual((result,evidence),before)

    def test_failed_structured_cards_stay_pending_without_fallback(self):
        result,evidence=fixture()
        for row in result['intel']:row['retrieved_at']='2026-01-14T00:00:00Z'
        before=copy.deepcopy((result,evidence))
        accepted,pending,note=semantics.intelligence(result,evidence)
        self.assertEqual(accepted,[]);self.assertEqual(len(pending),3)
        self.assertTrue(all(row['title'].startswith('中文消息') for row in pending))
        self.assertIn('3 条原报告情报待补证',note)
        self.assertEqual((result,evidence),before)

    def test_old_markdown_without_cards_keeps_official_document_fallback(self):
        for empty in (None,[]):
            with self.subTest(intel=empty):
                result,evidence=fixture();result['research_text']='# 旧版 Markdown\n\n完整研究仍保留。'
                if empty is None:result.pop('intel')
                else:result['intel']=empty
                accepted,pending,note=semantics.intelligence(result,evidence)
                self.assertEqual(len(accepted),6);self.assertEqual(pending,[])
                self.assertTrue(all(row.get('extraction') for row in accepted))
                self.assertIn('已整理 6 条',note)
        ast.parse(SOURCE.read_text('utf-8'),feature_version=(3,9))

if __name__=='__main__':unittest.main()
