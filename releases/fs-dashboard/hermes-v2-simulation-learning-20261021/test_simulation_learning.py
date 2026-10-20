from pathlib import Path
import importlib.util,json,types,unittest
HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def sibling(name):return next(p for p in (HERE.parent/name,HERE.parent/name.replace('-','_')) if p.exists())
prior=load('prior_tests',sibling('hermes-v2-strategy-permissions-20261021')/'test_permissions.py')
bridge=load('latest_bridge',HERE/'source/pricing_simulation.py')
prior.support.ps=bridge;prior.support.st.SimulationBridge=bridge.SimulationBridge
OriginalEngine=prior.OriginalEngine
Records=prior.Records
existing=load('prior_learning_tests',sibling('hermes-v2-learning-evidence-20261021')/'test_learning_evidence.py')
service=load('latest_learning',HERE/'source/learning_service.py');existing.service=service;existing.repair.service=service
VisibleAggregates=existing.VisibleAggregates
ReviewRepair=existing.ReviewRepair


class SimulationTeaching(unittest.TestCase):
    def test_publisher_changes_only_two_existing_research_files(self):
        p=load('publisher',HERE/'deploy/release.py')
        self.assertEqual(p.TARGETS,{'source/pricing_simulation.py':'/opt/fs-hermes-fc/pricing_simulation.py','source/learning_service.py':'/opt/fs-hermes-fc/learning_service.py'})
        self.assertEqual(p.NEW,frozenset());self.assertEqual(p.BASE_SHA,'1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de')

    def fixture(self):
        case=prior.support.Fixture('runTest');case.setUp();self.addCleanup(case.doCleanups);return case

    def test_actual_current_baseline_and_gifts_have_distinct_receipt_fields(self):
        case=self.fixture();result=case.simulate()
        for row in result['comparisons']:
            self.assertEqual(row['current_page_usd'],'100.00');self.assertEqual(row['own_bonus_k'],'5')
            base=next(r for r in result['baseline']['rows'] if r['platform']==row['platform'])
            self.assertEqual(row['baseline_page_usd'],base['target_page_usd'])
        self.assertIn('not actual storefront',result['quantity_contract']['baseline']);self.assertEqual(result['snapshot_created_at'],case.snapshot['created_at'])

    def test_completed_own_task_can_teach_from_simulations_without_raw_rows(self):
        fixture=prior.support.TaskBoundary('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups);source=fixture.completed_source()
        value=fixture.simulate();value['id']='sim_test';value['raw_customers']=[{'email':'hidden@example.invalid'}]
        with fixture.tasks.db() as db:
            prior.support.st.schema(db)
            for key,owner,task in (('own','wulv',fixture.task['id']),('other','other',fixture.task['id']),('different','wulv','other-task')):
                db.execute('INSERT INTO strategy_simulations VALUES(?,?,?,?,?,?,?)',(key,'draft',owner,task,key,json.dumps(value),prior.support.NOW.isoformat()))
        job=lambda u,k:dict(owner='wulv',state='COMPLETED',task_id=fixture.task['id'],body={'question':'检查自己的模拟'},result={}) if u=='wulv' and k==source else None
        result=service.source_snapshot(types.SimpleNamespace(root=fixture.root,tasks=fixture.tasks,get_job=job),'wulv',source,'检验基线和实价的含义。')
        receipts=[i for i in result['visible_evidence']['items'] if 'simulation_receipt' in i['values']]
        self.assertEqual(len(receipts),1);self.assertEqual(result['simulation_evidence_coverage']['source_records'],1)
        projected=receipts[0]['values']['simulation_receipt'];self.assertEqual(projected['current_price_coverage'],'explicit_in_receipt')
        self.assertEqual([r['platform'] for r in projected['candidate']],['PS','XBOX','PC']);self.assertEqual(projected['candidate'][0]['own_bonus_k'],'5')
        self.assertNotIn('hidden@example',json.dumps(result));self.assertFalse(projected['write_performed'])

    def test_older_receipt_missing_current_price_is_never_backfilled(self):
        case=self.fixture();value=case.simulate()
        for row in value['comparisons']:row.pop('current_page_usd')
        result=service.review_evidence([dict(evidence_id='ev_sim',source='Hermes只读策略模拟回执',query={'profile':'FC27'},data={'simulation_receipt':value})])
        projected=result['items'][0]['values']['simulation_receipt'];self.assertEqual(projected['current_price_coverage'],'missing_in_original_receipt_do_not_infer')
        self.assertTrue(all('current_page_usd' not in row for row in projected['comparisons']))


if __name__=='__main__':unittest.main()
