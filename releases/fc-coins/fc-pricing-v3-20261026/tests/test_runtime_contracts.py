import json
import hashlib
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3 import api, runtime
from fc_pricing_v3.scheduler import backlog_cleared
from fc_pricing_v3.ledger import Ledger
import pricing_operations
import pricing_simulation


class RuntimeContracts(unittest.TestCase):
    def test_state_summary_excludes_private_orders_and_regional_replay_rows(self):
        private=[dict(order_key='private-order')]
        snapshot=dict(snapshot_id='one',created_at='now',result=dict(rows=[]),evidence=dict(
            historical_orders=private,monthly_target=dict(amount=None),
            region_rules=[dict(region_id=39,history=dict(replay_paths=private,source_sha256='a'))],
            regional_controls=[dict(region_id=21,history=dict(replay_paths=private,coverage=1))]))
        summary=runtime.public_snapshot_summary(snapshot)
        self.assertNotIn('historical_orders',summary['evidence'])
        self.assertNotIn('replay_paths',summary['evidence']['region_rules'][0]['history'])
        self.assertNotIn('replay_paths',summary['evidence']['regional_controls'][0]['history'])
        self.assertEqual(snapshot['evidence']['historical_orders'],private)

    def test_state_uses_thin_summary_for_large_historical_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db')
            orders=[dict(order_key=str(i),paid_usd='12',private_note='x'*520) for i in range(2352)]
            snapshot=dict(snapshot_id='large',created_at='2026-10-26T12:00:00+00:00',
                evidence=dict(historical_orders=orders,monthly_target=dict(mtd='412'),
                    region_rules=[dict(region_id=39,history=dict(replay_paths=orders,source_sha256='a'))],
                    regional_controls=[dict(region_id=21,resource='region:21:PS',history=dict(replay_paths=orders))]),
                result=dict(rows=[dict(platform='PS',package_usd='10')]))
            db.put('pricing_snapshots','large',snapshot)
            db.put('metadata','latest_snapshot_summary',runtime.public_snapshot_summary(snapshot))
            self.assertGreater(len(json.dumps(snapshot).encode()),1024*1024)
            with patch.object(api,'ledger',return_value=db),patch.object(db,'all',wraps=db.all) as all_rows:
                state=api.read('state')
                market=api.read('market')
            self.assertFalse(any(call.args==('pricing_snapshots',) for call in all_rows.call_args_list))
            self.assertEqual(state['snapshot_id'],'large')
            self.assertEqual(state['target']['mtd'],'412')
            self.assertNotIn('private_note',json.dumps(state))
            self.assertNotIn('replay_paths',json.dumps(state))
            self.assertLess(len(json.dumps(state).encode()),1024*1024)
            self.assertEqual(market['snapshot_id'],'large')

    def test_latest_fallback_uses_rowid_and_skips_postwrite_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db')
            db.put('pricing_snapshots','old',dict(snapshot_id='old',created_at='2099-01-01',
                evidence=dict(monthly_target=dict(mtd='1')),result=dict(rows=[])))
            db.put('pricing_snapshots','new',dict(snapshot_id='new',created_at='2026-10-26',
                evidence=dict(monthly_target=dict(mtd='2')),result=dict(rows=[])))
            db.put('pricing_snapshots','postwrite',dict(snapshot_id='postwrite',created_at='2026-10-27',
                authorization_purpose='original_unsent_ALL_steps_only',evidence={},result=dict(rows=[])))
            with patch.object(api,'ledger',return_value=db):
                state=api.read('state')
            self.assertEqual(state['snapshot_id'],'new')
            self.assertEqual(state['target']['mtd'],'2')

    def test_backlog_exit_requires_fresh_complete_zero_normal_queue(self):
        now=datetime.now(timezone.utc)
        queue=dict(status='normal_delivery_gross_quantity_upper_estimate', checked_at=now.isoformat(),
                   gross_ordered_delivery_k='0', counts=dict(active_Coins_orders=0), source_sha256='a'*64,
                   order_status_intersection=dict(status='native_Order_status_1_2_verified'))
        evidence=dict(fulfillment_estimates=dict(current_backlog_source=queue))
        self.assertTrue(backlog_cleared(evidence,now))
        self.assertFalse(backlog_cleared({},now))
        self.assertFalse(backlog_cleared(dict(fulfillment_estimates=dict(current_backlog_source=dict(queue,gross_ordered_delivery_k=None))),now))
        self.assertFalse(backlog_cleared(dict(fulfillment_estimates=dict(current_backlog_source=dict(queue,checked_at=(now-timedelta(minutes=16)).isoformat()))),now))
        self.assertFalse(backlog_cleared(dict(fulfillment_estimates=dict(current_backlog_source=dict(queue,order_status_intersection=dict(status='unavailable')))),now))

    def test_strategy_decisions_route_keeps_requested_run_when_newer_snapshot_exists(self):
        first='00000000-0000-4000-8000-000000000050'
        later='00000000-0000-4000-8000-000000000051'
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db')
            for ident in (first,later):
                db.put('pricing_snapshots',ident,dict(snapshot_id=ident,origin='live_collector',
                    created_at=ident,evidence=dict(run_id=ident),policy_version='fc-pricing-v3-20261026'))
                db.put('strategy_decisions',ident,dict(daily=dict(candidates=[dict(action=ident)])))
            with patch.object(api,'ledger',return_value=db):
                result=api.read('strategy-decisions/'+first)
        self.assertEqual(result['snapshot_id'],first)
        self.assertEqual(result['results']['daily']['candidates'][0]['action'],first)

    def test_hermes_simulate_proposal_and_multi_plan_execution_use_v3_contract(self):
        run='00000000-0000-4000-8000-000000000030'
        plan='00000000-0000-4000-8000-000000000031'
        state=dict(snapshot_id=run,active_plans=[dict(plan_id='other',state='ACTIVE'),dict(plan_id=plan,state='ACTIVE')])
        calls=[]
        def request(path,owner,body=None):
            calls.append((path,body))
            if path.endswith('/state'):return state
            if path.endswith('/evaluate'):return dict(snapshot_id=run,results={'daily':dict(status='READY',selected={'action':{}},failures=[])},execution_authorized=False)
            return dict(status='queued')
        scope=Mock()
        scope.clock.return_value=datetime.now(timezone.utc)
        auth=dict(mode='operator_workflow',runs=[run],conversation='a'*32)
        with tempfile.TemporaryDirectory() as folder:
            db_path=Path(folder)/'tasks.db'
            @contextmanager
            def connection():
                with closing(sqlite3.connect(db_path)) as db, db:
                    yield db
            scope.tasks.db.side_effect=connection
            with patch.object(pricing_operations,'authorization',return_value=auth):
                proposed=pricing_operations.call(scope,'wulv','task','lease',dict(action='plan_propose',request_key='proposal-1',mode='daily'),request)
                pricing_operations.call(scope,'wulv','task','lease',dict(action='simulate',request_key='history-1',kind='fixed_orders_reprice'),request)
                pricing_operations.call(scope,'wulv','task','lease',dict(action='simulation_read',simulation_id=run),request)
                execute=dict(action='plan_execute_authorized',request_key='execute-1',plan_id=plan)
                pricing_operations.call(scope,'wulv','task','lease',execute,request)
                state['snapshot_id']='a-newer-run'
                pricing_operations.call(scope,'wulv','task','lease',execute,request)
        self.assertFalse(proposed['plan_created'])
        self.assertFalse(any(path.endswith('/plans') for path,_ in calls))
        self.assertTrue(any(path.endswith('/simulations') and body['kind']=='fixed_orders_reprice' and body['request_key'] for path,body in calls if body))
        self.assertTrue(any(path.endswith('/simulations/'+run) and body is None for path,body in calls))
        self.assertTrue(any(path.endswith('/execute') and body['plan_id']==plan and body['request_key'] for path,body in calls if body))
        self.assertEqual(len({body['request_key'] for path,body in calls if path.endswith('/execute')}),1)

    def test_hermes_recommendation_uses_exact_run_candidates_not_latest_state(self):
        run='00000000-0000-4000-8000-000000000040'
        action=dict(base_prices=dict(console='10.50',pc='11.00'),region_coefficients={})
        assigned=dict(base_prices=dict(console='10.00',pc='10.00'),region_coefficients={})
        action_hash=hashlib.sha256(json.dumps(action,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        bundle=dict(schema_version='fc-pricing-v3-20261026',snapshot_id=run,snapshot_sha256='c'*64,
                    mode='daily',action=assigned)
        bundle['sha256']=hashlib.sha256(json.dumps(bundle,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        quote=dict(run_id=run,result=dict(decision_receipt=bundle))
        quote['original_quote_sha256']=hashlib.sha256(json.dumps(quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        decisions=dict(snapshot_id=run,snapshot_sha256='c'*64,strategy_version=bundle['schema_version'],
                       results={'daily':dict(candidates=[dict(action=action)])})
        calls=[]
        def request(path,owner,body=None):
            calls.append(path)
            if path.endswith('/state'):return dict(snapshot_id='different-later-run',strategies={'daily':dict(candidates=[])})
            if path.endswith('/quotes/'+run):return quote
            if path.endswith('/strategy-decisions/'+run):return decisions
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as folder:
            db_path=Path(folder)/'tasks.db'
            scope=Mock()
            @contextmanager
            def connection():
                with closing(sqlite3.connect(db_path)) as db, db:
                    yield db
            scope.tasks.db.side_effect=connection
            scope.clock.return_value=datetime.now(timezone.utc)
            args=dict(action='recommend',request_key='recommend-one',run_id=run,bundle_sha256=bundle['sha256'],
                      action_sha256=action_hash,reason='same run alternative',evidence_refs=['pricing:'+bundle['sha256']])
            auth=dict(mode='automatic_review',runs=[run],conversation='a'*32)
            with patch.object(pricing_operations,'authorization',return_value=auth):
                result=pricing_operations.call(scope,'wulv','task','lease',args,request)
                same=pricing_operations.call(scope,'wulv','task','lease',args,request)
                original_request_count=calls.count('/quotes/'+run)
                original_sha=quote.pop('original_quote_sha256')
                with self.assertRaisesRegex(ValueError,'pricing_original_quote_sha256_missing'):
                    pricing_operations.call(scope,'wulv','task','lease',dict(args,request_key='recommend-two'),request)
        self.assertEqual(result,same)
        self.assertEqual(original_request_count,1)
        self.assertEqual(calls.count('/quotes/'+run),2)
        self.assertEqual(result['action_vector'],action)
        self.assertEqual(result['quote_sha256'],original_sha)
        self.assertNotEqual(result['action_vector'],assigned)

    def test_simulation_bridge_pins_local_and_runtime_pure_versions(self):
        source=SOURCE/'fc_pricing_v3'
        hashes={key:hashlib.sha256((source/name).read_bytes()).hexdigest() for key,name in [('engine_sha256','engine.py'),('financial_sha256','financial.py')]}
        remote=dict(version='fc-pricing-v3-20261026',**hashes,legacy_sources=pricing_simulation.LEGACY_SHA)
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'config'
            config.mkdir()
            (config/'automation.json').write_text(json.dumps(dict(revision=7,pricing_rules=dict(bands=dict(at_least_40=dict(min_discount_pct='0',max_discount_pct='10'))))),encoding='utf-8')
            old_run='00000000-0000-4000-8000-000000000041'
            def request(path,owner):
                if path.endswith('/versions'):return remote
                if path.endswith('/simulations/'+old_run):return dict(simulation_id=old_run,execution_authorized=False,records=[])
                if path.endswith('/quotes/'+old_run):return dict(run_id=old_run,evidence=dict(checked_at='historical'))
                return dict(snapshot_id='current')
            bridge=pricing_simulation.SimulationBridge(root=folder,code=source,request=request)
            self.assertEqual(bridge.versions()['engine_sha256'],hashes['engine_sha256'])
            capabilities=bridge.capabilities()
            self.assertEqual(capabilities['baseline_policy']['revision'],7)
            self.assertEqual(capabilities['snapshot_id'],'current')
            self.assertFalse(capabilities['execution_authorized'])
            self.assertIsNone(capabilities['pricing_rules'])
            self.assertFalse(capabilities['rule_ideas_supported'])
            with self.assertRaisesRegex(ValueError,'legacy_bands_retired'):
                bridge.rules(None,dict(pricing_rules=dict(bands={})),[])
            self.assertEqual(bridge.historical_result(old_run)['simulation_id'],old_run)
            with patch('fc_pricing_v3.legacy_simulation.replay',return_value=dict(status='available')):
                self.assertEqual(bridge.legacy_replay(old_run,'legacy_80_15_5')['status'],'available')
            unmounted=pricing_simulation.SimulationBridge(root=Path(folder)/'not-mounted',code=source,request=request)
            self.assertEqual(unmounted.capabilities()['baseline_policy']['status'],'legacy_policy_not_mounted')
            with self.assertRaisesRegex(ValueError,'runtime_version_changed'):
                pricing_simulation.SimulationBridge(code=source,request=lambda path,owner:dict(remote,engine_sha256='0'*64)).versions()

    def test_v3_ui_controls_have_real_elements(self):
        html=(SOURCE / 'fc27-coins.html').read_text(encoding='utf-8')
        script=(SOURCE / 'fc-pricing-v3.js').read_text(encoding='utf-8')
        ids=set(re.findall(r'id="([^"]+)"',html))
        used=set(re.findall(r"\$\('([^']+)'\)",script))
        self.assertFalse(used-ids,used-ids)
        self.assertRegex(html,r'id="hermes-review"[^>]*\bhidden\b')
        self.assertIn('提交 Hermes 决策审核并执行',html)
        self.assertIn("'hermes-review'",script)
        self.assertIn("request('execute',{request_key:'cycle-'",script)
        self.assertIn('最低已观察 100K',html)
        self.assertIn("table('v3-eld-platforms'",script)

    def test_state_reads_only_latest_five_independent_market_observations(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder) / 'control.db')
            for index in range(7):
                db.put('market_observations',str(index),dict(run_id=str(index),status='observed',
                    eldorado=dict(status='partial',platforms=[])))
            with patch.object(api,'ledger',return_value=db):
                state=api.read('state')
            self.assertEqual([item['run_id'] for item in state['latest_market_observations']],
                             ['6','5','4','3','2'])

    def test_restore_preview_only_reads_confirmed_original_before_prices(self):
        ident='00000000-0000-4000-8000-000000000020'
        rows=[dict(platform=p,b2c=value) for p,value in [('PS','.105'),('XBOX','.105'),('PC','.12')]]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'executions').mkdir()
            path=root/'executions'/(ident+'.json')
            with patch.object(runtime,'ROOT',root):
                path.write_text(json.dumps(dict(execution_id=ident,status='UNKNOWN',sync_confirmed=False,before=dict(rows=rows))),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'original_unconfirmed'):
                    api.original_restore_prices(ident)
                path.write_text(json.dumps(dict(execution_id=ident,status='CONFIRMED',sync_confirmed=True,before=dict(rows=rows))),encoding='utf-8')
                self.assertEqual(api.original_restore_prices(ident),dict(console='10.500',pc='12.00'))

    def test_plan_request_reuses_id_and_original_anchor_after_snapshot_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder) / 'control.db')
            db.activate_generation('v3',[])
            def snapshot(ident,price):
                return dict(snapshot_id=ident,created_at=ident,evidence=dict(storefront=dict(rows={p:dict(package_usd=price) for p in ('PS','XBOX','PC')}),
                    region_rules=[dict(id=1,region_id=39,platforms=['PS','XBOX','PC'],factor='.91')],regional_controls=[]))
            db.put('pricing_snapshots','1',snapshot('1','10'))
            data=dict(request_key='same-plan',mode='daily',resources=['base:console'],daily_budget='20',parameters=dict(offsets_pct=['-8','0','8']))
            with patch.object(api,'ledger',return_value=db):
                first=api.post('plans',data,'wulv')
                db.put('pricing_snapshots','2',snapshot('2','11'))
                second=api.post('plans',data,'wulv')
                pc=api.post('plans',dict(data,request_key='pc-plan',resources=['base:pc']),'wulv')
                with self.assertRaisesRegex(ValueError,'pricing_plan_payload_conflict'):
                    api.post('plans',dict(data,daily_budget='30'),'wulv')
                with db.transaction() as conn:
                    conn.execute('DELETE FROM pricing_snapshots')
                self.assertEqual(api.post('plans',data,'wulv')['plan_id'],first['plan_id'])
            self.assertEqual(first['plan_id'],second['plan_id'])
            self.assertEqual(first['price_anchor']['base_prices']['console'],'10')
            self.assertEqual(first['resources'],['base:console'])
            self.assertEqual(pc['resources'],['base:pc'])
            db.activate_plan(first['plan_id'])
            db.activate_plan(pc['plan_id'])
            self.assertEqual(len(db.active_plans()),2)

    def test_manual_preview_intent_and_execute_retry_keep_one_original_id(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder) / 'control.db')
            db.activate_generation('v3',[])
            db.put('pricing_snapshots','s',dict(snapshot_id='s',created_at='1',evidence=dict(storefront=dict(rows={p:dict(package_usd='10') for p in ('PS','XBOX','PC')}),region_rules=[],regional_controls=[])))
            plan=db.create_plan('daily',['base:console'],dict(base_prices=dict(console='10',pc='10'),region_coefficients={}),plan_id='00000000-0000-4000-8000-000000000010')
            db.activate_plan(plan['plan_id'])
            preview=dict(request_key='preview-one',plan_id=plan['plan_id'],reason='manual trial',explicit_prices=dict(console='10.50'))
            proof=dict(selected=dict(action=dict(base_prices=dict(console='10.50',pc='10'))),current={},valid_until=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),plan_id=plan['plan_id'],revision=1)
            with patch.object(api,'ledger',return_value=db),patch.object(runtime,'override_quote',return_value=proof) as override:
                first=api.post('manual-previews',preview,'wulv')
                second=api.post('manual-previews',preview,'wulv')
                self.assertEqual(override.call_count,1)
                with db.transaction() as conn:
                    conn.execute('DELETE FROM pricing_snapshots')
                self.assertEqual(api.post('manual-previews',preview,'wulv')['manual_preview_id'],first['manual_preview_id'])
                intent=dict(request_key='execute-one',plan_id=plan['plan_id'],manual_preview_id=first['manual_preview_id'])
                accepted=api.post('execute',intent,'wulv')
                retried=api.post('execute',intent,'wulv')
            self.assertEqual(first['manual_preview_id'],second['manual_preview_id'])
            self.assertEqual(accepted['job_key'],retried['job_key'])
            with db.connect() as conn:
                jobs=conn.execute("SELECT id,body FROM durable_jobs WHERE id=?",(accepted['job_key'],)).fetchall()
            self.assertEqual(len(jobs),1)
            self.assertEqual(json.loads(jobs[0]['body'])['manual_preview_id'],first['manual_preview_id'])
            self.assertTrue(json.loads(jobs[0]['body'])['manual_requested'])
            self.assertEqual(json.loads(jobs[0]['body'])['request_id'],accepted['job_key'])

    def test_monthly_target_never_overwrites_actual_mtd(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder) / 'control.db')
            db.put('pricing_snapshots','s',dict(snapshot_id='s',created_at='1',evidence=dict(monthly_target=dict(mtd='412',data_cutoff='2026-10-26T08:00:00+00:00'))))
            with patch.object(api,'ledger',return_value=db):
                saved=api.post('monthly-target',dict(request_key='target-one',amount='1000'),'wulv')
                state=api.read('state')
                with self.assertRaisesRegex(ValueError,'pricing_target_payload_conflict'):
                    api.post('monthly-target',dict(request_key='target-one',amount='1200'),'wulv')
            self.assertEqual(saved['target_scope'],'site266_FC27_Coins')
            self.assertEqual(state['target']['amount'],'1000')
            self.assertEqual(state['target']['mtd'],'412')

    def test_history_reader_exposes_aggregate_without_order_rows(self):
        raw=dict(simulation_id='id',simulation_kind='actual_reconstruction',rule_mode='historical_asof',
                 created_at='now',execution_authorized=False,training_eligible=False,
                 reconciled_actual=dict(as_of='now',revised_order_count=1,actual=dict(net_revenue_usd='7')),
                 records=[dict(snapshot_id='s',status='available',actual=dict(net_revenue_usd='7'),
                               orders=[dict(order_key='private-order-id',paid_usd='7')],gaps=[dict(order_key='private-order-id',reason='unavailable')])])
        view=api.history_view(raw)
        self.assertEqual(view['records'][0]['actual']['net_revenue_usd'],'7')
        self.assertEqual(view['reconciled_actual']['revised_order_count'],1)
        self.assertNotIn('private-order-id',json.dumps(view))

    def test_unconfirmed_original_sync_cannot_finish_postwrite(self):
        operation_id = '00000000-0000-4000-8000-000000000001'
        operation = dict(operation_id=operation_id, status='UNKNOWN',
                         steps=[dict(kind='base', step_id='base',state='DISPATCHED',
                                     dispatched_at='2026-10-26T00:00:00+00:00')])
        db = Mock()
        db.get.return_value = operation
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'executions').mkdir()
            (root / 'executions' / (operation_id + '.json')).write_text(
                json.dumps(dict(status='CONFIRMED', sync_confirmed=False)), encoding='utf-8')
            with patch.object(runtime, 'ROOT', root), patch.object(runtime, 'ledger', return_value=db), \
                    patch('fc_pricing_v3.adapters.reconcile_base', return_value={'status':'UNKNOWN'}) as base, \
                    patch('fc_pricing_v3.adapters.reconcile_postwrite') as postwrite:
                runtime.reconcile(operation_id)
        base.assert_called_once()
        db.step_result.assert_not_called()
        postwrite.assert_not_called()
        db.finish.assert_not_called()

    def test_restore_container_includes_v3_adapter_dependency(self):
        script = SOURCE / 'restore_price.sh'
        self.assertTrue(script.exists(), 'restore_price.sh must be a V3 reviewed release target')
        body = script.read_text(encoding='utf-8')
        self.assertIn('src=/opt/fc27-cloud-browser/fc_pricing_v3,dst=/opt/fc_pricing_v3', body)


if __name__ == '__main__':
    unittest.main()
