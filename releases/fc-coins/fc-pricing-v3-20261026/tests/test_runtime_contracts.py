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
from fc_pricing_v3 import api, runtime, monitoring, scheduler
from fc_pricing_v3.scheduler import next_cycle_at
from fc_pricing_v3.ledger import Ledger
import fc_pricing_v3.ledger as ledger_module
import pricing_operations
import pricing_simulation
import hermes_pricing_bridge


class RuntimeContracts(unittest.TestCase):
    def test_one_hour_cycle_resume_uses_last_completed_operation_once(self):
        start=datetime(2026,10,26,14,tzinfo=timezone.utc)
        completed=start+timedelta(minutes=37)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            db=Ledger(root/'v3/control.sqlite3')
            plan=dict(plan_id='plan',revision=1,generation='g',resources=['base:pc'],
                      starts_at=start.isoformat(),state='SUSPENDED',mode='revenue_sprint',
                      financial_contract_version=runtime.FINANCIAL_CONTRACT_VERSION)
            db.put('metadata','generation',dict(id='g'))
            db.put('pricing_plans','plan',plan)
            db.put('operations','original',dict(plan_id='plan',status='COMPLETED',
                    completed_at=completed.isoformat(),created_at=start.isoformat()))
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','plan',1,'g')")
            self.assertEqual(next_cycle_at(db,plan),completed+timedelta(hours=1))
            self.assertEqual(next_cycle_at(db,plan,dict(interval_minutes=120)),completed+timedelta(hours=2))
            with patch.object(api,'ledger',return_value=db):
                with patch.object(api,'clock',return_value=completed):
                    resumed=api.post('plans/plan/resume',{},'wulv')
                    repeated=api.post('plans/plan/resume',{},'wulv')
            self.assertEqual(resumed['resume_count'],1)
            self.assertEqual(repeated['resume_count'],1)
            self.assertEqual(next_cycle_at(db,resumed),completed+timedelta(hours=1))
            (root/'config').mkdir()
            (root/'config/v3-control.json').write_text('{"enabled":true}')
            (root/'v3/heartbeat.json').write_text(json.dumps(dict(checked_at=(completed+timedelta(minutes=1)).isoformat())))
            view=monitoring.projection(root,completed+timedelta(minutes=1))
            self.assertEqual(view['schedule']['cycle_interval_minutes'],60)
            self.assertEqual(view['schedule']['next_cycle_at'],(completed+timedelta(hours=1)).isoformat())
            self.assertEqual(view['schedule']['active_plan_state'],'ACTIVE')

    def test_one_hour_tick_does_not_enqueue_early_or_duplicate_due_cycle(self):
        start=datetime(2026,10,26,14,tzinfo=timezone.utc)
        completed=start+timedelta(minutes=37)
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3')
            plan=dict(plan_id='plan',revision=1,generation='g',resources=['base:pc'],
                      starts_at=start.isoformat(),state='ACTIVE',mode='daily',resume_count=1)
            db.put('metadata','generation',dict(id='g'))
            db.put('pricing_plans','plan',plan)
            db.put('operations','original',dict(plan_id='plan',status='COMPLETED',completed_at=completed.isoformat()))
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','plan',1,'g')")
            future=Mock();future.done.return_value=False
            executors={lane:Mock() for lane in ('collection','control','observation')}
            executors['collection'].submit.return_value=future
            running={}
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'export_shadow_snapshot'),patch.object(runtime,'write_json'):
                with patch.object(scheduler,'clock',return_value=completed+timedelta(minutes=59)):
                    scheduler.tick(executors,running)
                with db.connect() as conn:
                    self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='cycle'").fetchone()[0],0)
                with patch.object(scheduler,'clock',return_value=completed+timedelta(minutes=60)):
                    scheduler.tick(executors,running)
                    scheduler.tick(executors,running)
            with db.connect() as conn:
                rows=conn.execute("SELECT id,state FROM durable_jobs WHERE kind='cycle'").fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['state'],'running')
            self.assertTrue(rows[0]['id'].endswith(':r1'))

    def test_future_old_revision_cycle_does_not_block_current_natural_cycle(self):
        from types import SimpleNamespace
        now=datetime(2026,10,29,17,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3')
            plan=dict(plan_id='original-plan',revision=5,generation='g',resources=['base:pc'],
                      starts_at=(now-timedelta(hours=2)).isoformat(),last_cycle_at=(now-timedelta(hours=1)).isoformat(),
                      state='ACTIVE',mode='daily',resume_count=7)
            db.put('metadata','generation',dict(id='g'));db.put('pricing_plans',plan['plan_id'],plan)
            db.enqueue('cycle','original-rev4-retry',now+timedelta(hours=1),dict(plan_id=plan['plan_id'],revision=4))
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','original-plan',5,'g')")
                conn.execute("UPDATE durable_jobs SET attempt=4 WHERE id='original-rev4-retry'")
            with db.connect() as conn:old=dict(conn.execute("SELECT * FROM durable_jobs WHERE id='original-rev4-retry'").fetchone())
            future=Mock();future.done.return_value=False
            executors={lane:Mock() for lane in ('collection','control','observation')}
            executors['collection'].submit.return_value=future;running={}
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now),patch.object(scheduler,'export_shadow_snapshot'),patch.object(runtime,'write_json'),patch('automation_policy.load_policy',return_value=dict(interval_minutes=60)):
                scheduler.tick(executors,running);scheduler.tick(executors,running)
            with db.connect() as conn:
                self.assertEqual(dict(conn.execute("SELECT * FROM durable_jobs WHERE id='original-rev4-retry'").fetchone()),old)
                current=[dict(row) for row in conn.execute("SELECT * FROM durable_jobs WHERE kind='cycle'") if json.loads(row['body'])['revision']==5]
            self.assertEqual(len(current),1);self.assertTrue(current[0]['id'].endswith(':r7'))
            self.assertEqual(current[0]['state'],'running');executors['collection'].submit.assert_called_once()
            # The original ID is not rewritten by tick. When its original time is
            # reached, the existing cycle/run_job path naturally closes it.
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now+timedelta(hours=1)),patch.dict(sys.modules,{'fc27_cloud_worker':SimpleNamespace()}):
                scheduler.run_job(old)
            with db.connect() as conn:finished=dict(conn.execute("SELECT * FROM durable_jobs WHERE id='original-rev4-retry'").fetchone())
            self.assertEqual(finished['state'],'done');self.assertEqual(json.loads(finished['body'])['result']['status'],'superseded')
            self.assertEqual((finished['id'],finished['attempt'],finished['due_at']),(old['id'],old['attempt'],old['due_at']))
            self.assertEqual(db.get('pricing_plans',plan['plan_id'])['last_cycle_at'],plan['last_cycle_at'])

    def test_current_revision_pending_cycle_still_blocks_duplicate_cycle(self):
        now=datetime(2026,10,29,17,tzinfo=timezone.utc)
        for state in ('queued','running'):
          with self.subTest(state=state),tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3')
            plan=dict(plan_id='original-plan',revision=5,generation='g',resources=['base:pc'],
                      starts_at=(now-timedelta(hours=2)).isoformat(),state='ACTIVE',mode='daily',resume_count=7)
            db.put('metadata','generation',dict(id='g'));db.put('pricing_plans',plan['plan_id'],plan)
            db.enqueue('cycle','original-current-retry',now+timedelta(hours=1),dict(plan_id=plan['plan_id'],revision=5))
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','original-plan',5,'g')")
                conn.execute('UPDATE durable_jobs SET state=? WHERE id=?',(state,'original-current-retry'))
            with db.connect() as conn:before=dict(conn.execute("SELECT * FROM durable_jobs WHERE id='original-current-retry'").fetchone())
            executors={lane:Mock() for lane in ('collection','control','observation')}
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now),patch.object(scheduler,'export_shadow_snapshot'),patch.object(runtime,'write_json'),patch('automation_policy.load_policy',return_value=dict(interval_minutes=60)):
                scheduler.tick(executors,{});scheduler.tick(executors,{})
            with db.connect() as conn:
                rows=[dict(row) for row in conn.execute("SELECT * FROM durable_jobs WHERE kind='cycle'")]
            self.assertEqual(rows,[before]);executors['collection'].submit.assert_not_called()

    def test_suspended_deadline_waits_for_original_then_ends_without_new_price(self):
        now=datetime(2026,10,26,14,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3')
            plan=dict(plan_id='plan',revision=1,generation='g',resources=['base:pc'],
                      starts_at=now.isoformat(),state='SUSPENDED',mode='revenue_sprint')
            db.put('pricing_plans','plan',plan)
            db.put('operations','original',dict(plan_id='plan',status='UNKNOWN'))
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','plan',1,'g')")
            held=db.deadline('plan',1)
            self.assertEqual(held['status'],'suspended_deadline_original_reconciliation_pending')
            self.assertEqual(db.active_plan()['state'],'SUSPENDED')
            db.put('operations','original',dict(plan_id='plan',status='COMPLETED'))
            ended=db.deadline('plan',1)
            self.assertEqual((ended['state'],ended['exit_reason']),('ENDED','suspended_deadline_no_new_price'))
            self.assertIsNone(db.active_plan())
            with db.connect() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='cycle'").fetchone()[0],0)

    def test_exit_cycle_owns_one_period_with_explicit_or_original_revisionless_body(self):
        from types import SimpleNamespace
        now=datetime(2026,10,29,17,tzinfo=timezone.utc)
        for legacy_body in (False,True):
          with self.subTest(legacy_body=legacy_body),tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'quotes').mkdir();db=Ledger(root/'control.sqlite3')
            old=dict(plan_id='original-parent',revision=1,generation='g',resources=['base:pc'],
                     starts_at=(now-timedelta(hours=2)).isoformat(),state='ENDING',mode='daily',actor='wulv',
                     price_anchor=dict(base_prices=dict(pc='8.59')),last_cycle_at=(now-timedelta(hours=1)).isoformat())
            db.put('metadata','generation',dict(id='g'));db.put('pricing_plans',old['plan_id'],old)
            with db.transaction() as conn:conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','original-parent',1,'g')")
            policy=dict(interval_minutes=60,system_enabled=True,mode='auto',revision=1)
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now),patch.object(ledger_module,'clock',return_value=now),patch('automation_policy.load_policy',return_value=policy):
                child=scheduler.exit_plan(dict(plan_id=old['plan_id'],revision=1))
            ident='exit-cycle:'+child['plan_id']
            with db.transaction() as conn:
                original=dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?',(ident,)).fetchone())
                body=json.loads(original['body']);self.assertEqual(body['revision'],child['revision'])
                if legacy_body:body.pop('revision')  # Exact old producer's persisted body, same original ID/lineage.
                conn.execute('UPDATE durable_jobs SET body=?,due_at=?,attempt=4 WHERE id=?',
                             (json.dumps(body),(now+timedelta(hours=1)).isoformat(),ident))
            with db.connect() as conn:before=dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?',(ident,)).fetchone())
            executors={lane:Mock() for lane in ('collection','control','observation')}
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now),patch.object(scheduler,'export_shadow_snapshot'),patch.object(runtime,'write_json'),patch('automation_policy.load_policy',return_value=policy):
                scheduler.tick(executors,{});scheduler.tick(executors,{})
            with db.connect() as conn:
                self.assertEqual(dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?',(ident,)).fetchone()),before)
                self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='cycle'").fetchone()[0],1)
            executors['collection'].submit.assert_not_called()
            run='00000000-0000-4000-8000-000000000707';operations=[]
            def collect(job):
                operations.append(job['request']['v3_operation_id'])
                (root/'quotes'/(run+'.json')).write_text(json.dumps(dict(result=dict(decision_receipt=dict(plan_id=child['plan_id'])))))
                return dict(run_id=run)
            def execute(run_id):
                result=dict(operation_id=operations[-1],plan_id=child['plan_id'],status='NO_CHANGE',resources=child['resources'],completed_at=(now+timedelta(hours=1)).isoformat())
                db.put('operations',result['operation_id'],result);return result
            worker=SimpleNamespace(save_job=Mock(),collect_quote=Mock(side_effect=collect))
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'ROOT',root),patch.object(scheduler,'clock',return_value=now+timedelta(hours=1)),patch('automation_policy.load_policy',return_value=policy),patch('fc_pricing_v3.business_source.history_ES_blocker',return_value=None),patch.dict(sys.modules,{'fc27_cloud_worker':worker}),patch.object(scheduler,'execute_run',side_effect=execute):
                scheduler.run_job(before)
            worker.collect_quote.assert_called_once();self.assertEqual(len(db.all('operations')),1)
            self.assertEqual(db.get('pricing_plans',old['plan_id'])['state'],'ENDED')
            with db.connect() as conn:self.assertEqual(conn.execute('SELECT state FROM durable_jobs WHERE id=?',(ident,)).fetchone()[0],'done')
            self.assertEqual(db.get('pricing_plans',child['plan_id'])['last_cycle_at'],(now+timedelta(hours=1)).isoformat())
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'export_shadow_snapshot'),patch.object(runtime,'write_json'),patch('automation_policy.load_policy',return_value=policy):
                with patch.object(scheduler,'clock',return_value=now+timedelta(hours=1,minutes=59)):scheduler.tick(executors,{})
                executors['collection'].submit.assert_not_called()
                with patch.object(scheduler,'clock',return_value=now+timedelta(hours=2)):scheduler.tick(executors,{})
            executors['collection'].submit.assert_called_once();self.assertEqual(len(db.all('operations')),1)

    def test_unproven_revisionless_cycle_does_not_block_or_execute_current_plan(self):
        from types import SimpleNamespace
        now=datetime(2026,10,29,17,tzinfo=timezone.utc)
        for ident in ('legacy-ordinary-cycle','exit-cycle:current-plan'):
          with self.subTest(ident=ident),tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3')
            plan=dict(plan_id='current-plan',revision=5,generation='g',resources=['base:pc'],
                      starts_at=(now-timedelta(hours=2)).isoformat(),state='ACTIVE',mode='daily',resume_count=7)
            db.put('metadata','generation',dict(id='g'));db.put('pricing_plans',plan['plan_id'],plan)
            with db.transaction() as conn:conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','current-plan',5,'g')")
            db.enqueue('cycle',ident,now+timedelta(hours=1),dict(plan_id=plan['plan_id']))
            operation_id=str(scheduler.uuid.uuid5(scheduler.uuid.NAMESPACE_URL,'fc-v3-operation:'+ident))
            unknown=dict(operation_id=operation_id,plan_id=plan['plan_id'],resources=plan['resources'],status='UNKNOWN')
            db.put('operations',operation_id,unknown)
            with db.connect() as conn:before=dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?',(ident,)).fetchone())
            executors={lane:Mock() for lane in ('collection','control','observation')}
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now),patch.object(scheduler,'export_shadow_snapshot'),patch.object(runtime,'write_json'),patch('automation_policy.load_policy',return_value=dict(interval_minutes=60)):
                scheduler.tick(executors,{})
            with db.connect() as conn:
                self.assertEqual(dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?',(ident,)).fetchone()),before)
                reconciliations=[json.loads(row[0]) for row in conn.execute("SELECT body FROM durable_jobs WHERE kind='reconcile'")]
            self.assertEqual([body['operation_id'] for body in reconciliations],[operation_id])
            executors['collection'].submit.assert_called_once()
            worker=SimpleNamespace(collect_quote=Mock(),save_job=Mock())
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now+timedelta(hours=1)),patch.dict(sys.modules,{'fc27_cloud_worker':worker}):scheduler.run_job(before)
            worker.collect_quote.assert_not_called();worker.save_job.assert_not_called()
            self.assertNotIn('last_cycle_at',db.get('pricing_plans',plan['plan_id']))
            self.assertEqual(db.get('operations',operation_id),unknown)

    def test_deadline_exit_price_waits_for_one_hour_cycle(self):
        now=datetime(2026,10,26,14,40,tzinfo=timezone.utc)
        last=now-timedelta(minutes=3)
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3')
            db.put('metadata','generation',dict(id='g'))
            old=dict(plan_id='plan',revision=1,generation='g',resources=['base:pc'],
                     starts_at=(now-timedelta(hours=1)).isoformat(),state='ENDING',mode='daily',
                     price_anchor=dict(base_prices=dict(pc='8.59')),actor='wulv',
                     last_cycle_at=last.isoformat())
            db.put('pricing_plans','plan',old)
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','plan',1,'g')")
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'clock',return_value=now),patch.object(ledger_module,'clock',return_value=now):
                successor=scheduler.exit_plan(dict(plan_id='plan',revision=1))
            with db.connect() as conn:
                row=conn.execute("SELECT due_at FROM durable_jobs WHERE id=?",('exit-cycle:'+successor['plan_id'],)).fetchone()
            self.assertEqual(row['due_at'],(last+timedelta(hours=1)).isoformat())
            self.assertEqual(successor['budget_policy'],'none')
            self.assertNotIn('daily_budget',successor)

    def test_per_cycle_hermes_review_is_retired_before_any_submission(self):
        with patch.object(hermes_pricing_bridge,'request') as submit:
            with self.assertRaisesRegex(ValueError,'per_cycle_model_review_retired'):
                hermes_pricing_bridge.review({}, {},mode='automatic_review')
        submit.assert_not_called()

    def test_automatic_hermes_compare_uses_scoped_original_run_without_new_evaluation(self):
        run='00000000-0000-4000-8000-000000000072'
        original=dict(status='READY',candidates=[dict(action_sha256='b'*64)],selected=dict(action_sha256='b'*64))
        paths=[]
        def request(path,owner,body=None):
            paths.append((path,body))
            return dict(snapshot_id=run,results=dict(revenue_sprint=original),execution_authorized=False)
        scope=Mock();scope.clock.return_value=datetime.now(timezone.utc)
        auth=dict(mode='automatic_review',runs=[run],conversation='a'*32)
        with patch.object(pricing_operations,'authorization',return_value=auth):
            result=pricing_operations.call(scope,'wulv','task','lease',
                dict(action='compare_strategies',mode='revenue_sprint'),request)
        self.assertEqual(result['results']['revenue_sprint'],original)
        self.assertEqual(result['snapshot_id'],run)
        self.assertEqual(paths,[('/pricing/v3/strategy-decisions/'+run,None)])

    def test_shadow_monitor_uses_real_outbox_cursor_and_oldest_pending_age(self):
        now=datetime(2026,10,26,14,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            db=Ledger(root/'control.db')
            db.put('pricing_snapshots','one',dict(snapshot_id='one',created_at=(now-timedelta(minutes=4)).isoformat()))
            with closing(db.connect()) as conn, conn:
                conn.execute("INSERT INTO event_outbox(event_key,kind,body) VALUES (?,?,?)",
                             ('one','snapshot_ready',json.dumps(dict(snapshot_id='one'))))
                stalled=monitoring.shadow_progress(conn,root,now)
            self.assertEqual((stalled['status'],stalled['cursor'],stalled['pending']),('scheduled_daily',0,1))
            self.assertEqual(stalled['next_daily_at'],'2026-10-27T02:20:00+08:00')
            with closing(sqlite3.connect(root/'shadow.sqlite3')) as shadow, shadow:
                shadow.execute('CREATE TABLE cursor(id TEXT PRIMARY KEY,value INTEGER NOT NULL)')
                shadow.execute("INSERT INTO cursor VALUES ('production',1)")
            with closing(db.connect()) as conn, conn:
                current=monitoring.shadow_progress(conn,root,now)
            self.assertEqual((current['status'],current['cursor'],current['pending']),('current',1,0))

    def test_strategy_summary_keeps_all_action_hashes_and_selected_proof_under_native_limit(self):
        actions=[]
        candidates=[]
        for index in range(100):
            action=dict(base_prices=dict(console=str(index),pc='8.51'),region_coefficients={})
            actions.append(action)
            candidates.append(dict(action=action,action_sha256=hashlib.sha256(json.dumps(action,
                sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                score=dict(objective=str(index),absolute_forecast_available=True,revenue='100'),
                financial_proof=dict(pass_all=True,minimum_pct='10',prices={'global:PS':dict(
                    catalog=dict(minimum_estimated_average_margin_pct='12',minimum_undiscounted_margin_pct='20'),
                    repeated_proof='x'*12000)})))
        decisions={'daily':dict(status='READY',candidates=candidates,selected=candidates[0],failures=[])}
        summary=api.strategy_summary(decisions)
        self.assertEqual([item['action'] for item in summary['daily']['candidates']],actions)
        self.assertEqual(summary['daily']['selected']['financial_proof'],candidates[0]['financial_proof'])
        self.assertLess(len(json.dumps(summary).encode()),1024*1024)
        self.assertGreater(len(json.dumps(decisions).encode()),1024*1024)

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

    def test_retired_modes_cannot_create_new_plans(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'retired.db')
            for mode in ('acquisition','backlog','flash_sale'):
                with self.assertRaisesRegex(ValueError,'pricing_plan_scope_invalid'):
                    db.create_plan(mode,['base:console'],dict(base_prices=dict(console='10',pc='10'),region_coefficients={}))

    def test_two_modes_allow_open_end_and_keep_explicit_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'optional-end.db');db.activate_generation('g',[])
            anchor=dict(base_prices=dict(console='10',pc='10'),region_coefficients={})
            for mode in ('daily','revenue_sprint'):
                plan=db.create_plan(mode,['base:console'],anchor)
                self.assertIsNone(plan['ends_at'])
                start=datetime.now(timezone.utc);end=start+timedelta(hours=3)
                explicit=db.create_plan(mode,['base:console'],anchor,starts_at=start.isoformat(),ends_at=end.isoformat())
                self.assertEqual(explicit['ends_at'],end.isoformat())
            old=db.create_plan('daily',['base:pc'],anchor);old['mode']='backlog';db.put('pricing_plans',old['plan_id'],old)
            with self.assertRaisesRegex(ValueError,'pricing_strategy_retired'):db.activate_plan(old['plan_id'])

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

    def test_candidate_detail_uses_original_run_and_action_sha(self):
        ident='00000000-0000-4000-8000-000000000052'
        action=dict(base_prices=dict(console='8.51',pc='8.51'),region_coefficients={})
        action_sha=hashlib.sha256(json.dumps(action,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        candidate=dict(action=action,action_sha256=action_sha,financial_proof=dict(pass_all=True,
            original_detail='x'*5000),score=dict(objective='1'))
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db')
            db.put('pricing_snapshots',ident,dict(snapshot_id=ident,origin='live_collector',
                evidence=dict(run_id=ident),policy_version='fc-pricing-v3-20261026'))
            db.put('strategy_decisions',ident,dict(daily=dict(candidates=[candidate],selected=candidate)))
            with patch.object(api,'ledger',return_value=db):
                summary=api.read('strategy-decisions/'+ident)
                detail=api.read('strategy-decisions/'+ident+'/daily/'+action_sha)
                with self.assertRaisesRegex(ValueError,'pricing_strategy_candidate_missing'):
                    api.read('strategy-decisions/'+ident+'/daily/'+'f'*64)
        self.assertNotIn('original_detail',json.dumps(summary['results']['daily']['candidates']))
        self.assertEqual(detail['candidate'],candidate)

    def test_hermes_candidate_detail_reads_exact_original_candidate(self):
        run='00000000-0000-4000-8000-000000000053'
        action_sha='a'*64
        expected=dict(snapshot_id=run,mode='daily',candidate=dict(action_sha256=action_sha,
            financial_proof=dict(pass_all=True)))
        seen=[]
        def request(path,owner,body=None):
            seen.append(path)
            return expected
        scope=Mock()
        with patch.object(pricing_operations,'authorization',return_value=None):
            result=pricing_operations.call(scope,'wulv','task','lease',dict(action='candidate_detail',
                run_id=run,mode='daily',action_sha256=action_sha),request)
        self.assertEqual(result,expected)
        self.assertEqual(seen,['/pricing/v3/strategy-decisions/'+run+'/daily/'+action_sha])

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
                if path.endswith('/legacy-replay/'+old_run+'/legacy_80_15_5'):
                    return dict(snapshot_id=old_run,legacy_policy='legacy_80_15_5',status='available',read_only=True,execution_authorized=False)
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
            self.assertEqual(bridge.legacy_replay(old_run,'legacy_80_15_5')['status'],'available')
            with patch.object(bridge,'request',return_value=dict(snapshot_id=old_run,legacy_policy='legacy_80_15_5',read_only=True,execution_authorized=True)),patch.object(bridge,'versions'):
                with self.assertRaisesRegex(ValueError,'legacy_reply_scope_invalid'):
                    bridge.legacy_replay(old_run,'legacy_80_15_5')
            unmounted=pricing_simulation.SimulationBridge(root=Path(folder)/'not-mounted',code=source,request=request)
            self.assertEqual(unmounted.capabilities()['baseline_policy']['status'],'legacy_policy_not_mounted')
            with self.assertRaisesRegex(ValueError,'runtime_version_changed'):
                pricing_simulation.SimulationBridge(code=source,request=lambda path,owner:dict(remote,engine_sha256='0'*64)).versions()

    def test_legacy_api_replays_saved_snapshot_without_quote_or_writes(self):
        ident='00000000-0000-4000-8000-000000000052'
        evidence=json.loads(Path(__file__).with_name('legacy-replay-fixture.json').read_text(encoding='utf-8'))
        started=datetime.fromisoformat(evidence['checked_at'].replace('Z','+00:00'))
        evidence['fx']['checked_at']=(started+timedelta(seconds=30)).isoformat()
        snapshot=dict(snapshot_id=ident,created_at=(started+timedelta(seconds=60)).isoformat(),evidence=evidence)
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.sqlite3');db.put('pricing_snapshots',ident,snapshot)
            with patch.object(api,'ledger',return_value=db):
                result=api.read('legacy-replay/'+ident+'/legacy_80_15_5')
                self.assertEqual(result['status'],'available')
                self.assertEqual(result['as_of'],snapshot['created_at'])
                self.assertEqual(result['snapshot_id'],ident)
                self.assertNotIn('evidence',result)
                self.assertFalse(result['execution_authorized'])
                for path in ('legacy-replay/bad/legacy_80_15_5','legacy-replay/'+ident+'/unknown','legacy-replay/00000000-0000-4000-8000-000000000053/legacy_80_15_5'):
                    with self.assertRaises(ValueError):api.read(path)
            self.assertEqual(db.get('pricing_snapshots',ident),snapshot)
            self.assertEqual(db.all('operations'),[])

    def test_v3_ui_controls_have_real_elements(self):
        html=(SOURCE / 'fc27-coins.html').read_text(encoding='utf-8')
        script=(SOURCE / 'fc-pricing-v3.js').read_text(encoding='utf-8')
        ids=set(re.findall(r'id="([^"]+)"',html))
        used=set(re.findall(r"\$\('([^']+)'\)",script))
        self.assertFalse(used-ids,used-ids)
        self.assertNotIn('id="hermes-review"',html)
        self.assertIn('立即运行当前策略',html)
        self.assertIn('id="v3-daily-result"',html)
        self.assertIn("request('execute',{request_key:'cycle-'",script)
        self.assertIn('Lootbar',html)
        self.assertNotIn("table('v3-eld-platforms'",script)

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
            data=dict(request_key='same-plan',mode='daily',resources=['base:console'],parameters=dict(offsets_pct=['-8','0','8']))
            with patch.object(api,'ledger',return_value=db):
                with self.assertRaisesRegex(ValueError,'pricing_plan_fields_invalid'):
                    api.post('plans',dict(data,daily_budget='0'),'wulv')
                first=api.post('plans',data,'wulv')
                db.put('pricing_snapshots','2',snapshot('2','11'))
                second=api.post('plans',data,'wulv')
                pc=api.post('plans',dict(data,request_key='pc-plan',resources=['base:pc']),'wulv')
                with self.assertRaisesRegex(ValueError,'pricing_plan_payload_conflict'):
                    api.post('plans',dict(data,parameters=dict(offsets_pct=['-4','0','4'])),'wulv')
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
