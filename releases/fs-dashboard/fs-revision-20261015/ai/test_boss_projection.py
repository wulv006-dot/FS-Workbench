import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('boss_projection',ROOT/'candidate/boss_projection.py')
projection=importlib.util.module_from_spec(spec);spec.loader.exec_module(projection)


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.evidence=json.loads((ROOT/'fixtures/evidence-public.json').read_text('utf-8'))
        self.result={'period':{'start':'2026-10-05','end':'2026-10-11'},'snapshot_id':'fc-detail-ce9093f37832f24b5bc0','summary':'合成摘要，仅验证投影','actions':[]}

    def project(self):return projection.project(self.result,self.evidence,{},'a'*64)

    def test_real_frozen_week_reconciles_without_sample_ids(self):
        content=self.project()
        self.assertEqual(content['metrics'][0]['value'],'$227,259.77')
        self.assertEqual(content['metrics'][1]['value'],'3,426')
        self.assertEqual(len(content['charts'][0]['rows']),7)
        self.assertEqual(content['actions'],[])

    def test_other_period_does_not_copy_previous_report_numbers(self):
        self.result['period']={'start':'2026-10-14','end':'2026-10-14'}
        content=self.project()
        self.assertEqual(content['metrics'][0]['status'],'missing')
        self.assertTrue(all(not c['rows'] for c in content['charts']))

    def test_partial_filtered_different_snapshot_are_not_totals(self):
        for row in self.evidence.values():
            row['snapshot_id']='other'
        self.assertEqual(self.project()['metrics'][0]['status'],'missing')

    def test_conflicting_frozen_totals_are_not_arbitrarily_selected(self):
        key='ev_fd8914720a8382f5766ebf0e'
        duplicate=copy.deepcopy(self.evidence[key]);duplicate['data']['total']['revenue_usd']='999'
        self.evidence['ev_'+'f'*24]=duplicate
        self.assertEqual(self.project()['metrics'][0]['status'],'missing')

    def test_bad_daily_series_not_plotted(self):
        row=self.evidence['ev_6129f30ebfe61433a3df819c']
        row['data']['groups'][0]['orders']=99999
        self.assertFalse(self.project()['charts'][0]['rows'])

    def test_period_boundaries(self):
        self.assertEqual(projection.periods({'start':'2026-03-01','end':'2026-03-31'})[2].isoformat(),'2026-02-28')
        self.assertEqual(projection.periods({'start':'2026-03-02','end':'2026-03-05'})[0],'investigation')

    def breakdown(self,dimension,start='2026-10-05'):
        return next((key,row) for key,row in self.evidence.items() if row.get('query',{}).get('group_by')==[dimension] and row['query'].get('start')==start and row['query'].get('filters')=={})

    def test_real_groups_queue_and_payment_reconcile(self):
        content=self.project();charts={c['id']:c for c in content['charts']}
        self.assertEqual(len(charts['platform']['rows']),3)
        self.assertEqual(len(charts['category']['rows']),3)
        self.assertEqual(sum(projection.number(r['current']) for r in charts['category']['rows']),projection.number('227259.77'))
        self.assertEqual(sum(projection.number(r['value']) for r in charts['bridge']['rows'] if r['role']=='delta'),projection.number('-13187.46'))
        self.assertEqual(sum(r['value'] for r in charts['queue']['rows']),1143)
        self.assertEqual(charts['queue']['period_basis'],'current_snapshot')
        self.assertNotIn(' vs ',charts['queue']['period'])
        self.assertGreater(len(content['payment']),4)
        self.assertEqual(sum(projection.number(r['current']) for r in content['payment']),projection.number('227259.77'))

    def test_breakdown_mismatch_filtered_capture_and_unpriced_not_used(self):
        original=copy.deepcopy(self.evidence)
        for mutate in [lambda r:r['data']['groups'][0].update(revenue_usd='999999'),lambda r:r['data']['groups'][0].update(unpriced_orders=1),lambda r:r['query'].update(filters={'platform':'PS'}),lambda r:r.update(captured_at='2026-10-01T00:00:00+00:00')]:
            self.evidence=copy.deepcopy(original);_,r=self.breakdown('product');mutate(r)
            self.assertFalse(self.project()['charts'][3]['rows'])

    def test_payment_last_page_without_first_is_not_complete(self):
        _,row=self.breakdown('payment');row['query']['page']=2;row['data']['pagination'].update(page=2,page_size=50,total_groups=71)
        self.assertEqual(self.project()['payment'],[])

    def test_payment_complete_pages_are_combined(self):
        key,row=self.breakdown('payment');groups=copy.deepcopy(row['data']['groups']);count=len(groups)
        row['data']['groups']=groups[:11];row['data']['pagination'].update(page=1,page_size=11,total_groups=count,complete=False)
        second=copy.deepcopy(row);second['query']['page']=2;second['data']['pagination'].update(page=2,complete=True);second['data']['groups']=groups[11:]
        self.evidence['ev_'+'e'*24]=second
        self.assertTrue(self.project()['payment'])
        self.assertIn('ev_'+'e'*24,self.project()['payment_evidence_ids'])

    def test_conflicting_or_duplicate_group_does_not_plot(self):
        key,row=self.breakdown('platform');duplicate=copy.deepcopy(row);duplicate['data']['groups'][0]['orders']+=1
        self.evidence['ev_'+'d'*24]=duplicate
        self.assertFalse(self.project()['charts'][2]['rows'])
        self.evidence.pop('ev_'+'d'*24);row['data']['groups'][1]['group']=dict(row['data']['groups'][0]['group'])
        self.assertFalse(self.project()['charts'][2]['rows'])

    def test_amount_band_uses_dynamic_complete_evidence(self):
        for i,start in enumerate(['2026-09-28','2026-10-05']):
            _,source=self.breakdown('product',start);item=copy.deepcopy(source);item['query']['group_by']=['amount_band']
            for n,g in enumerate(item['data']['groups']):g['group']={'amount_band':['0–10','10–50','50+'][n]}
            self.evidence['ev_'+str(i)*24]=item
        chart=self.project()['charts'][5]
        self.assertEqual(chart['dimension_label'],'金额档')
        self.assertEqual(chart['kind'],'bars_compare')
        self.assertEqual(sum(projection.number(r['current']) for r in chart['rows']),projection.number('227259.77'))

    def test_renamed_evidence_ids_do_not_change_values(self):
        import hashlib
        self.evidence={'ev_'+hashlib.sha256(key.encode()).hexdigest()[:24]:row for key,row in self.evidence.items()}
        content=self.project()
        self.assertEqual(content['metrics'][0]['value'],'$227,259.77')
        self.assertTrue(content['payment'])
        self.assertTrue(all(key in self.evidence for key in content['payment_evidence_ids']))

    def test_no_comparison_does_not_fill_structure(self):
        self.evidence={key:r for key,r in self.evidence.items() if r.get('query',{}).get('end')!='2026-10-04'}
        content=self.project()
        self.assertIsNone(content['report']['period']['comparison_start'])
        self.assertFalse(content['charts'][2]['rows'])
        self.assertFalse(content['payment'])

    def test_real_completed_research_projects_and_renders_in_full(self):
        reports=ROOT.parent/'reports'
        result=json.loads((reports/'fixtures/real-result.json').read_text('utf-8'))
        renderer_spec=importlib.util.spec_from_file_location('boss_renderer',ROOT/'candidate/boss_renderer.py')
        renderer=importlib.util.module_from_spec(renderer_spec);renderer_spec.loader.exec_module(renderer)
        helper_spec=importlib.util.spec_from_file_location('report_html',reports/'fixtures/report_html.py')
        helper=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
        content=projection.project(result,self.evidence,{'artifact_written_at':'2026-10-14T09:00:00+00:00'},'a'*64)
        self.assertEqual(content['research_text'],result['raw_model_text'])
        self.assertGreater(len(content['research_text']),10000)
        with mock.patch.dict('sys.modules',{'report_html':helper}),mock.patch.object(helper,'markdown',wraps=helper.markdown) as markdown:
            rendered=renderer.render(content,self.evidence)
            markdown.assert_called_once_with(result['raw_model_text'],self.evidence)
        self.assertIn('完整研究正文',rendered)
        self.assertIn(helper.markdown(result['raw_model_text'],self.evidence),rendered)
        self.assertIn('227,259.77',rendered)
        self.assertIn('3,426',rendered)
        self.assertNotIn('@@BODY@@',rendered)

    def test_timestamp_is_stable_without_totals_and_requires_timezone(self):
        evidence=copy.deepcopy(self.evidence)
        for row in evidence.values():row['snapshot_id']='other'
        first=projection.project(self.result,evidence,{},'a'*64)
        second=projection.project(self.result,evidence,{},'a'*64)
        self.assertEqual(first['report']['generated_at'],second['report']['generated_at'])
        self.assertEqual(first['metrics'][0]['status'],'missing')
        with self.assertRaisesRegex(ValueError,'missing_stable_report_timestamp'):
            projection.project(self.result,{}, {},'a'*64)
        with self.assertRaisesRegex(ValueError,'timestamp_requires_timezone'):
            projection.project(self.result,evidence,{'artifact_written_at':'2026-10-14T09:00:00'},'a'*64)


if __name__=='__main__':unittest.main()
