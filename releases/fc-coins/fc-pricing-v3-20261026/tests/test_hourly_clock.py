import json
import sqlite3
import tempfile
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3 import runtime, scheduler
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL

TZ = timezone(timedelta(hours=8))


class HourlyClockTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE durable_jobs(id TEXT PRIMARY KEY, kind TEXT, state TEXT, due_at TEXT, body TEXT)')
        self.plan = dict(plan_id='plan', revision=1, state='ACTIVE', mode='smart',
            starts_at='2026-11-05T08:43:09+08:00', smart_started_at='2026-11-11T00:36:56+08:00',
            smart_strategy_version='market-anchor-v1', write_protocol=CURVE_WRITE_PROTOCOL,
            last_cycle_at='2026-11-20T00:49:42+08:00')
        self.policy = dict(interval_minutes=60)

    def next_at(self, when):
        with patch.object(scheduler, 'clock', return_value=when):
            return scheduler.next_cycle_at(self.db, self.plan, self.policy).astimezone(TZ)

    def insert_job(self, identity, scheduled, state='done', completed=None, result='confirmed', **extra):
        body = dict(plan_id='plan', revision=1, scheduled_at=scheduled.isoformat(),
                    result=dict(status=result), **extra)
        if completed:
            body['completed_at'] = completed.isoformat()
        self.db.execute('INSERT INTO durable_jobs VALUES (?,?,?,?,?)',
            (identity, 'cycle', state, scheduled.isoformat(), json.dumps(body)))

    def test_current_hour_fixed_at_15_and_late_catches_up(self):
        self.assertEqual(self.next_at(datetime(2026,11,20,1,10,tzinfo=TZ)), datetime(2026,11,20,1,15,tzinfo=TZ))
        self.assertEqual(self.next_at(datetime(2026,11,20,1,25,tzinfo=TZ)), datetime(2026,11,20,1,15,tzinfo=TZ))

    def test_manual_does_not_consume_natural_hour(self):
        now = datetime(2026,11,20,1,25,tzinfo=TZ)
        self.plan['last_cycle_at'] = now.isoformat()
        self.insert_job('manual:x', now, manual_requested=True)
        self.assertEqual(self.next_at(now), datetime(2026,11,20,1,15,tzinfo=TZ))

    def test_existing_natural_hour_goes_to_next_hour(self):
        now = datetime(2026,11,20,1,45,tzinfo=TZ)
        self.insert_job('cycle:plan:original:r0', datetime(2026,11,20,1,36,tzinfo=TZ))
        self.assertEqual(self.next_at(now), datetime(2026,11,20,2,15,tzinfo=TZ))

    def test_natural_retry_finished_this_hour_also_blocks_duplicate(self):
        now = datetime(2026,11,20,1,25,tzinfo=TZ)
        self.insert_job('cycle:plan:original:r0', datetime(2026,11,20,0,36,tzinfo=TZ),
                        completed=datetime(2026,11,20,1,5,tzinfo=TZ))
        self.assertEqual(self.next_at(now), datetime(2026,11,20,2,15,tzinfo=TZ))

    def test_midnight_and_resume_after_slot(self):
        now = datetime(2026,11,20,0,5,tzinfo=TZ)
        self.assertEqual(self.next_at(now), datetime(2026,11,20,0,15,tzinfo=TZ))
        resumed = datetime(2026,11,20,1,22,tzinfo=TZ)
        self.plan['resumed_at'] = resumed.isoformat()
        self.assertEqual(self.next_at(resumed), datetime(2026,11,20,1,15,tzinfo=TZ))

    def test_non_sixty_minutes_keeps_old_clock(self):
        self.policy['interval_minutes'] = 120
        now = datetime(2026,11,20,1,25,tzinfo=TZ)
        result = self.next_at(now)
        self.assertNotEqual(result.minute, 15)


    def test_initial_natural_cycle_in_same_hour_is_not_duplicated(self):
        now = datetime(2026,11,20,1,25,tzinfo=TZ)
        self.insert_job('initial:plan', datetime(2026,11,20,1,5,tzinfo=TZ), completed=now)
        self.assertEqual(self.next_at(now), datetime(2026,11,20,2,15,tzinfo=TZ))

    def test_tick_uses_slot_in_scheduled_at_and_original_id_without_repeat(self):
        now = datetime(2026,11,20,1,25,tzinfo=TZ)
        slot = datetime(2026,11,20,1,15,tzinfo=TZ)
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'control.sqlite3')
            plan = dict(self.plan, generation='g', resources=['base:PC'], resume_count=1)
            db.put('metadata', 'generation', dict(id='g'))
            db.put('pricing_plans', 'plan', plan)
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:PC','plan',1,'g')")
            future = Mock()
            future.done.return_value = False
            executors = {lane: Mock() for lane in ('collection','control','observation','outcomes')}
            executors['collection'].submit.return_value = future
            running = {}
            with patch.object(scheduler,'ledger',return_value=db), \
                    patch.object(scheduler,'clock',return_value=now), \
                    patch.object(scheduler,'export_shadow_snapshot'), \
                    patch.object(runtime,'write_json'), \
                    patch('automation_policy.load_policy',return_value=self.policy):
                scheduler.tick(executors,running)
                scheduler.tick(executors,running)
            with db.connect() as conn:
                rows = conn.execute("SELECT id,state,body FROM durable_jobs WHERE kind='cycle'").fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['id'], 'cycle:plan:' + str(int(slot.timestamp())) + ':r1')
            self.assertEqual(rows[0]['state'],'running')
            self.assertEqual(datetime.fromisoformat(json.loads(rows[0]['body'])['scheduled_at']),slot)
            executors['collection'].submit.assert_called_once()


    def test_not_started_plan_uses_first_future_slot_after_activation(self):
        now = datetime(2026,11,20,1,0,tzinfo=TZ)
        self.plan['starts_at'] = datetime(2026,11,20,2,20,tzinfo=TZ).isoformat()
        self.plan['smart_started_at'] = self.plan['starts_at']
        self.assertEqual(self.next_at(now), datetime(2026,11,20,3,15,tzinfo=TZ))

    def test_es_ready_before_slot_resumes_same_id_without_future_timestamp(self):
        now = datetime(2026,11,20,2,3,tzinfo=TZ)
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'control.sqlite3')
            plan = dict(plan_id='plan',revision=1,generation='g',resources=['base:PS'],
                        starts_at=(now-timedelta(days=1)).isoformat(),state='ACTIVE',mode='daily',
                        write_protocol=CURVE_WRITE_PROTOCOL)
            db.put('metadata','generation',dict(id='g'))
            db.put('pricing_plans','plan',plan)
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:PS','plan',1,'g')")
            identity = 'cycle:plan:original:r0'
            db.enqueue('cycle',identity,now,dict(plan_id='plan',revision=1,
                scheduled_at=(now-timedelta(hours=1)).isoformat(),deferred_reason=scheduler.WAITING_FOR_ES))
            root = Path(folder)
            (root/'quotes').mkdir()
            (root/'quotes'/'run.json').write_text(json.dumps({'result':{'status':'KEEP','rows':[]}}))
            worker = SimpleNamespace(collect_quote=Mock(return_value={'run_id':'run'}),save_job=Mock())
            policy = dict(revision=1,system_enabled=True,mode='auto',interval_minutes=60)
            with db.connect() as conn:
                job = dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?',(identity,)).fetchone())
            with patch.object(scheduler,'ledger',return_value=db),patch.object(scheduler,'ROOT',root), \
                    patch.object(scheduler,'clock',return_value=now), \
                    patch.object(scheduler,'yesterday_es_ready',return_value=True), \
                    patch('automation_policy.load_policy',return_value=policy), \
                    patch.dict(sys.modules,{'fc27_cloud_worker':worker}), \
                    patch.object(scheduler,'recover_curve_cost_alerts'), \
                    patch.object(scheduler,'execute_run') as writer:
                scheduler.run_job(job)
            with db.connect() as conn:
                saved = dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?',(identity,)).fetchone())
                body = json.loads(saved['body'])
                self.assertEqual(saved['state'],'done')
                self.assertEqual(datetime.fromisoformat(body['scheduled_at']),now)
                with patch.object(scheduler,'clock',return_value=now):
                    self.assertEqual(scheduler.next_cycle_at(conn,plan,policy).astimezone(TZ),
                                     datetime(2026,11,20,3,15,tzinfo=TZ))
            worker.collect_quote.assert_called_once()
            writer.assert_not_called()


    def test_revision_and_resume_due_store_utc_and_compare_at_real_deadline(self):
        now = datetime(2026,11,20,1,10,tzinfo=TZ).astimezone(timezone.utc)
        deadline = datetime(2026,11,20,1,15,tzinfo=TZ).astimezone(timezone.utc)
        for resumed in (False, True):
            with self.subTest(resumed=resumed), tempfile.TemporaryDirectory() as folder:
                db = Ledger(Path(folder) / 'control.sqlite3')
                plan = dict(self.plan, revision=2)
                if resumed:
                    plan['resumed_at'] = now.isoformat()
                with patch.object(scheduler,'clock',return_value=now):
                    due = scheduler.next_cycle_at(db,plan,self.policy)
                self.assertEqual(due,deadline)
                self.assertEqual(due.utcoffset(),timedelta(0))
                db.enqueue('cycle','cycle:plan:test:r0',due,dict(plan_id='plan',revision=2))
                with db.connect() as conn:
                    saved = conn.execute("SELECT due_at FROM durable_jobs WHERE id='cycle:plan:test:r0'").fetchone()[0]
                    self.assertEqual(saved,deadline.isoformat())
                    query = "SELECT count(*) FROM durable_jobs WHERE state='queued' AND due_at<=?"
                    self.assertEqual(conn.execute(query,((deadline-timedelta(seconds=1)).isoformat(),)).fetchone()[0],0)
                    self.assertEqual(conn.execute(query,(deadline.isoformat(),)).fetchone()[0],1)

if __name__ == '__main__':
    unittest.main()
