from pathlib import Path
import sys,importlib.util,json,types,unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
STRATEGY=next(p for p in (HERE.parent/'hermes-v2-strategy-20261021',HERE.parent/'hermes_v2_strategy_20261021') if p.exists())
spec=importlib.util.spec_from_file_location('strategy_support',STRATEGY/'test_strategy.py');support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
sys.path.append(str(support.support.ROOT/'releases/fs-dashboard/hermes-report-repair-20261019/source'))
spec=importlib.util.spec_from_file_location('evidence_service',HERE/'source/learning_service.py');service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
REPAIR=next(p for p in (HERE.parent/'hermes-v2-review-repair-20261021',HERE.parent/'hermes_v2_review_repair_20261021') if p.exists())
spec=importlib.util.spec_from_file_location('repair_support',REPAIR/'test_review_repair.py');repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)
repair.service=service
ReviewRepair=repair.ReviewRepair


def record():
    return dict(evidence_id='ev_real',source='Admin原生统计',query={'start':'2026-10-19','end':'2026-10-19','profile':'FC27'},data={'authoritative_fields':{'revenueUsd':{'value':'123.45','unit':'USD','system':'admin.p2pah.cn','period':{'start':'2026-10-19','end':'2026-10-20'}},'orders':{'value':3,'unit':'count'}},'raw_orders':[{'email':'private@example.invalid','customer_id':123456,'api_key':'MUST_NOT_COPY'}]})


class VisibleAggregates(unittest.TestCase):
    def test_aggregate_value_and_provenance_are_present_without_raw_identities(self):
        value=record();result=service.review_evidence([value]);text=json.dumps(result)
        self.assertEqual(result['items'][0]['values']['authoritative_fields']['revenueUsd']['value'],'123.45')
        self.assertEqual(result['items'][0]['full_record_sha256'],service.digest(value));self.assertTrue(result['coverage']['complete'])
        for secret in ('private@example','123456','MUST_NOT_COPY','raw_orders'):self.assertNotIn(secret,text)
        value['data']['authoritative_fields']['revenueUsd']['value']='124.00'
        self.assertNotEqual(service.review_evidence([value])['sha256'],result['sha256'])

    def test_unsafe_values_and_unknown_fields_do_not_become_visible_evidence(self):
        value=record();value['data']['authoritative_fields']['revenueUsd']['definition']='email private@example.invalid';value['data']['authoritative_fields']['orders']['value']=float('nan')
        value['data']['authoritative_fields']['customer_id']={'value':'123456'}
        result=service.review_evidence([value]);text=json.dumps(result)
        self.assertNotIn('private@example',text);self.assertNotIn('123456',text);self.assertNotIn('NaN',text)
        result=service.review_evidence([dict(evidence_id='ev_raw',query={},data={'orders':[{'email':'private@example.invalid'}]})])
        self.assertEqual(result['items'],[]);self.assertFalse(result['coverage']['complete'])

    def test_coverage_bounds_are_explicit_and_never_silently_truncate(self):
        values=[record(),dict(record(),evidence_id='ev_second')]
        result=service.review_evidence(values,max_bytes=1)
        self.assertEqual(result['items'],[]);self.assertEqual(len(result['coverage']['not_projected']),2);self.assertFalse(result['coverage']['complete'])

    def test_full_platform_aggregates_keep_their_own_total_and_coverage(self):
        r=dict(evidence_id='ev_platform',source='Admin FC支付明细',query={'start':'2026-10-19','end':'2026-10-19','group_by':['platform'],'filters':{}},data={'total':{'revenue_usd':'60'},'groups':[{'group':{'platform':p},'revenue_usd':str(i*10),'orders':i,'email':'hidden@example.invalid'} for i,p in enumerate(('PS','XBOX','PC'),1)],'coverage':{'paid_complete':True},'pagination':{'complete':True}})
        result=service.review_evidence([r])['items'][0]['values'];self.assertEqual(len(result['groups']),3);self.assertEqual(result['total']['revenue_usd'],'60');self.assertTrue(result['coverage']['paid_complete']);self.assertNotIn('hidden@example',json.dumps(result))
        r['query']['group_by']=['customer'];r['data']['groups'][0]['group']={'customer':'hidden@example.invalid'}
        self.assertEqual(service.review_evidence([r])['items'],[])

    def test_real_source_snapshot_contains_facts_that_disagree_with_report(self):
        fixture=support.TaskBoundary('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups);source=fixture.completed_source()
        value=record()
        with fixture.tasks.db() as db:db.execute('UPDATE evidence SET content=? WHERE evidence_id=?',(json.dumps(value),'ev_real'))
        import report_artifacts
        def job(user,key):
            return dict(owner='wulv',state='COMPLETED',task_id=fixture.task['id'],body={'question':'核实原报告'},result={}) if user=='wulv' and key==source else None
        with patch.object(report_artifacts,'read_file',return_value={'content':json.dumps({'summary':'报告声称999.99','research_text':'报告声称999.99'})}):
            result=service.source_snapshot(types.SimpleNamespace(tasks=fixture.tasks,root=fixture.root,get_job=job),'wulv',source,'请自己核查错误。')
        self.assertIn('999.99',result['visible_result']['text']);self.assertEqual(result['visible_evidence']['items'][0]['values']['authoritative_fields']['revenueUsd']['value'],'123.45')
        self.assertEqual(result['visible_evidence']['sha256'],service.digest(result['visible_evidence']['items']))
        self.assertNotIn('private@example',json.dumps(result))
        with self.assertRaises(PermissionError):service.source_snapshot(types.SimpleNamespace(tasks=fixture.tasks,root=fixture.root,get_job=job),'other',source)


if __name__=='__main__':unittest.main()
