"""Current financial sampling is independent of seven-day observation/learning."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fixtures import fixture,NOW
from fc_pricing_v3 import financial as f, engine, runtime, business_source as business, selective_sources as inputs, scheduler
from fc_pricing_v3.ledger import Ledger
from test_selective_sources import cache_fixture, NOW as CACHE_NOW


class FinancialHistoryWindow(unittest.TestCase):
    def test_eight_days_exclude_yesterday_across_month_and_year(self):
        for at,start,end in [('2026-10-29T00:00:00+08:00','2026-10-20','2026-10-27'),
                             ('2026-03-03T00:00:00+08:00','2026-02-22','2026-03-01'),
                             ('2026-01-04T00:00:00+08:00','2025-12-26','2026-01-02')]:
            period=f.history_period(datetime.fromisoformat(at))
            self.assertEqual(period,dict(start=start,end=end))
            self.assertEqual((datetime.fromisoformat(end)-datetime.fromisoformat(start)).days+1,8)
        self.assertEqual(f.history_period(datetime.fromisoformat('2026-10-28T16:00:00+00:00')),dict(start='2026-10-20',end='2026-10-27'))

    def test_legacy_seven_day_mix_is_readable_but_cannot_authorize_new_price(self):
        legacy=fixture(legacy=True)[0];legacy['run_id']='legacy-snapshot'
        self.assertGreater(f.required_history_ratio(legacy,NOW),0)
        with self.assertRaisesRegex(ValueError,'window_migration_required'):
            f.required_history_ratio(legacy,NOW,require_current=True)
        with tempfile.TemporaryDirectory() as tmp,patch.object(runtime,'ROOT',Path(tmp)),patch.object(runtime,'ledger',return_value=Ledger(Path(tmp)/'db')),patch.object(runtime,'clock',return_value=NOW):
            with self.assertRaisesRegex(ValueError,'window_migration_required'):runtime.calculate(legacy)

    def test_new_tag_does_not_relabel_old_period_or_accept_partial_coverage(self):
        data=fixture()[0];mix=data['historical_discount_mix']
        self.assertEqual(f.required_history_ratio(data,NOW,require_current=True),f.number(mix['net_order_usd'])/f.number(mix['undiscounted_order_usd']))
        for key,value,reason in [('period',fixture(legacy=True)[0]['historical_discount_mix']['period'],'history_period'),('observed_orders',mix['eligible_orders']-1,'history_coverage')]:
            changed=deepcopy(data);changed['historical_discount_mix'][key]=value
            changed['historical_discount_mix']['sha256']=f.fingerprint({k:v for k,v in changed['historical_discount_mix'].items() if k!='sha256'})
            with self.assertRaisesRegex(ValueError,reason):f.required_history_ratio(changed,NOW,require_current=True)

    def test_old_quote_execution_rejected_before_any_writer(self):
        data=fixture(legacy=True)[0]
        receipt=dict(schema_version=engine.VERSION,authorization_purpose=None,financial_contract_version=f.LEGACY_FINANCIAL_CONTRACT_VERSION,
                     financial_proof=dict(execution_eligible=True),snapshot_sha256=f.fingerprint(data))
        receipt['sha256']=f.fingerprint(receipt)
        quote=dict(evidence=data,result=dict(strategy_version=engine.VERSION,decision_receipt=receipt))
        with self.assertRaisesRegex(ValueError,'quote_migration_required'):
            runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW,for_execution=True)

    def test_original_revision_four_migrates_once_without_changing_plan_scope(self):
        with tempfile.TemporaryDirectory() as tmp,patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            db=Ledger(Path(tmp)/'db');db.activate_generation('original',[])
            plan=db.create_plan('revenue_sprint',['base:console','base:pc'],dict(base_prices=dict(console='7.19',pc='7.25'),region_coefficients={}))
            plan.update(revision=4,state='SUSPENDED',financial_contract_version=f.LEGACY_FINANCIAL_CONTRACT_VERSION)
            db.put('pricing_plans',plan['plan_id'],plan)
            before=deepcopy(plan);migrated=db.migrate_financial_contract(plan['plan_id'],4,'wulv')
            self.assertEqual(migrated['revision'],5)
            self.assertEqual(migrated['financial_contract_version'],f.FINANCIAL_CONTRACT_VERSION)
            self.assertEqual(migrated['history_window_contract'],f.HISTORY_WINDOW_CONTRACT)
            for field in ('plan_id','ends_at','state','resources','price_anchor','parameters','generation'):
                self.assertEqual(migrated[field],before[field])
            self.assertEqual(db.migrate_financial_contract(plan['plan_id'],4,'wulv'),migrated)

    def test_rebuild_keeps_original_seven_day_demand_asof_hash_and_denominator(self):
        prior,selected,orders,provenance=cache_fixture()
        model=dict(status='available',period=dict(start='2026-10-19',end='2026-10-25'),history_observed_at='2026-10-25T23:30:00+08:00',
                   source_sha256='c'*64,groups=dict(pc=dict(orders_per_block='3',window_hours=168)))
        prior['daily_rollups']['demand_model']=model;prior['cache_sha256']=f.fingerprint({k:v for k,v in prior.items() if k!='cache_sha256'})
        with patch.object(business,'_period_population',return_value=(selected,provenance)),patch.object(business,'_live_traces',return_value=(orders,{},{})),patch.object(business,'demand_snapshot',side_effect=AssertionError('eight_day_financial_cohort_must_not_redefine_learning')):
            rebuilt,_=business.build_shared_history_cache(None,None,{},[],'new-source',CACHE_NOW,prior_cache=prior)
        self.assertEqual(rebuilt['daily_rollups']['demand_model'],model)
        context=inputs.context_from_cache(rebuilt,inputs.source_plan('revenue_sprint',dict(catalog_only=True)),{},CACHE_NOW)
        self.assertEqual(context['demand_model'],model)
        self.assertEqual(prior['daily_rollups']['demand_model'],model)

    def test_true_cold_financial_cache_uses_relative_prior_without_learning_collection(self):
        _,selected,orders,provenance=cache_fixture()
        with patch.object(business,'_period_population',return_value=(selected,provenance)),patch.object(business,'_live_traces',return_value=(orders,{},{})),patch.object(business,'demand_snapshot',side_effect=AssertionError('no_learning_fetch')):
            rebuilt,_=business.build_shared_history_cache(None,None,{},[],'new-source',CACHE_NOW)
        model=rebuilt['daily_rollups']['demand_model']
        self.assertEqual(model['groups'],{});self.assertIsNone(model['history_observed_at'])
        self.assertEqual(model['forecast_basis'],'relative_100k_price_prior_not_observed_orders')

    def test_money_functions_frozen_with_authorized_100k_catalog_scope(self):
        # Frozen LF function source from d1b17e57e24d61ea65069bbfc5cc5f0d4825527b.
        # Source segments avoid version-dependent ast.dump fields on Python 3.9/3.11+.
        expected={'number': '6e76e6794cfbc2633384c17ac2ad2bea52c0e00de15f4d6c68261a43681d5375', 'hard_floor': '1895d936edcb076cd64a05150cc67ed3b506b4a3221c93a251577516f156956e', 'prove_price': '2e731227d5bd1eb1cacf6453b144e31d463423ae0385d040ff93e654aab63797', 'catalog_floor': '093a7ffcffb583a5d5a482214d1d9c9429cb2f4401d3a0404be62bfb395308b4', 'prove_catalog': '71cd8bca441930475df55db0216e61623abb23798c94a2733134647a9060c46d', 'average_margin': 'c9804b8c250b835bd0d15aafae289fcc26a2d868cce2c464e7d1bd51f99841a9'}
        # Only the authorized 100K floor/proof replace the frozen catalog functions.
        expected.update(catalog_floor='581a016f029ceffb2693155bd05eb068644d9fd21275472ff20360f537c7537a',
                        prove_catalog='73c90316b2aed65864a31575c23e286d6ce764dd5cb623a1a4501240a5835763')
        source=(SOURCE/'fc_pricing_v3/financial.py').read_text(encoding='utf-8').replace('\r\n','\n')
        functions={node.name:hashlib.sha256(ast.get_source_segment(source,node).encode('utf-8')).hexdigest()
                   for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name in expected}
        self.assertEqual(functions,expected)


class ESPrecollectionGate(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.es=self.root/'es';self.receipts=self.root/'receipts';self.es.mkdir();self.receipts.mkdir()
        self.period=f.history_period(datetime.fromisoformat('2026-10-29T00:00:00+08:00'))
        self.module=SimpleNamespace(RULE_VERSION='test-contract',checked_query=lambda q:q)

    def receipt(self,day,reason,stage):
        query=dict(profile='ALL',start=day,end=day)
        key=hashlib.sha256(json.dumps(dict(query=query,rule=self.module.RULE_VERSION),sort_keys=True).encode()).hexdigest()
        path=self.receipts/(key+'.json');path.write_text(json.dumps(dict(value=dict(reason=reason,stage=stage))))
        return path

    def check(self):
        with patch.dict(sys.modules,{'es_order_structure':self.module}):return business.history_ES_blocker(self.period,ES_root=self.es,receipt_root=self.receipts)

    def test_missing_yesterday_permission_does_not_block_completed_eight_days(self):
        (self.es/'original.json').write_text(json.dumps(dict(query=self.period)))
        self.receipt('2026-10-28','es_export_permission_denied','not_generated')
        self.assertIsNone(self.check())

    def test_exact_known_permission_refusal_blocks_until_original_manifest_appears(self):
        path=self.receipt(self.period['end'],'es_export_permission_denied','not_generated')
        self.assertEqual(self.check()['reason'],'selective_history_ES_permission_denied')
        (self.es/'original.json').write_text(json.dumps(dict(query=self.period)))
        self.assertIsNone(self.check());self.assertTrue(path.exists())

    def test_unknown_attempt_is_never_downgraded_to_permission_refusal(self):
        path=self.receipt(self.period['end'],'es_export_permission_denied','not_generated')
        path.with_suffix('.attempt').write_text(json.dumps(dict(query=self.period)))
        self.assertEqual(self.check()['reason'],'es_export_previous_attempt_unknown_requires_reconcile')
        self.assertTrue(path.with_suffix('.attempt').exists())

    def test_unknown_sent_receipt_remains_original_request_reconciliation(self):
        self.receipt(self.period['end'],'es_export_result_unknown_poll_only','export_sent')
        self.assertEqual(self.check()['reason'],'es_export_previous_attempt_unknown_requires_reconcile')

    def test_original_durable_task_uses_existing_backoff_without_becoming_infeasible(self):
        db=Ledger(self.root/'db')
        db.enqueue('cycle','original-request',NOW,dict(plan_id='original-plan',revision=4))
        with db.connect() as conn:job=dict(conn.execute('SELECT * FROM durable_jobs').fetchone())
        with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=NOW),patch.object(scheduler,'cycle',side_effect=ValueError('selective_history_ES_permission_denied')):
            scheduler.run_job(job)
        with db.connect() as conn:after=dict(conn.execute('SELECT * FROM durable_jobs').fetchone())
        self.assertEqual(after['id'],job['id']);self.assertEqual(after['state'],'queued');self.assertEqual(after['attempt'],1)
        self.assertEqual(after['due_at'],(NOW+timedelta(minutes=5)).isoformat())
        body=json.loads(after['body']);self.assertEqual(body['error'],'selective_history_ES_permission_denied')
        self.assertEqual(body['circuit'],'retry');self.assertNotIn('result',body)

    def test_scheduler_gate_precedes_cost_competitor_collection_and_preserves_plan(self):
        with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            db=Ledger(self.root/'db');db.activate_generation('g',[])
            plan=db.create_plan('daily',['base:pc'],dict(base_prices=dict(console='20',pc='20'),region_coefficients={}))
            plan=db.activate_plan(plan['plan_id'])
        worker=SimpleNamespace(save_job=Mock(),collect_quote=Mock())
        blocked=dict(reason='selective_history_ES_permission_denied')
        with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=NOW),patch.dict(sys.modules,{'fc27_cloud_worker':worker}),patch('automation_policy.load_policy',return_value=dict(system_enabled=True,mode='auto')),patch.object(business,'history_ES_blocker',return_value=blocked) as gate:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'selective_history_ES_permission_denied'):
                    scheduler.cycle(dict(plan_id=plan['plan_id'],request_id='same-original-task'))
        gate.assert_called_with(f.history_period(NOW));worker.save_job.assert_not_called();worker.collect_quote.assert_not_called()
        self.assertEqual(db.get('pricing_plans',plan['plan_id'])['state'],'ACTIVE');self.assertEqual(db.all('operations'),[])


if __name__=='__main__':unittest.main()
