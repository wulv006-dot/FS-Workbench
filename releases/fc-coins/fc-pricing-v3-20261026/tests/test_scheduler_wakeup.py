import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from fc_pricing_v3 import runtime, scheduler
from fc_pricing_v3.ledger import Ledger


class SchedulerWakeupTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE durable_jobs (id TEXT PRIMARY KEY, kind TEXT, state TEXT, due_at TEXT)')
        self.now = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
        self.sleeps = 0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        self.now += timedelta(seconds=seconds)

    def wait(self, running=None, natural=None):
        return scheduler._wait_for_due(self.db, running or {}, [], natural,
                                       clock_fn=self.clock, sleep_fn=self.sleep)

    def test_idle_falls_back_after_sixty_seconds(self):
        self.assertEqual(self.wait(), 'interval')
        self.assertEqual(self.sleeps, 60)

    def test_due_manual_wakes_without_claiming(self):
        self.db.execute('INSERT INTO durable_jobs VALUES (?,?,?,?)',
                        ('manual:x', 'cycle', 'queued', self.now.isoformat()))
        self.assertEqual(self.wait(), 'manual')
        self.assertEqual(self.sleeps, 1)
        self.assertEqual(self.db.execute('SELECT state FROM durable_jobs').fetchone()[0], 'queued')

    def test_future_manual_wakes_at_due_time(self):
        due = self.now + timedelta(seconds=7)
        self.db.execute('INSERT INTO durable_jobs VALUES (?,?,?,?)',
                        ('manual:x', 'cycle', 'queued', due.isoformat()))
        self.assertEqual(self.wait(), 'manual')
        self.assertEqual(self.sleeps, 7)

    def test_busy_collection_does_not_spin(self):
        self.db.execute('INSERT INTO durable_jobs VALUES (?,?,?,?)',
                        ('manual:x', 'cycle', 'queued', self.now.isoformat()))
        self.assertEqual(self.wait({'collection': Future()}, self.now), 'interval')
        self.assertEqual(self.sleeps, 60)

    def test_completed_collection_wakes_original_tick(self):
        future = Future()
        future.set_result(None)
        self.assertEqual(self.wait({'collection': future}), 'collection_finished')
        self.assertEqual(self.sleeps, 1)

    def test_natural_due_wakes_at_original_target(self):
        self.assertEqual(self.wait(natural=self.now + timedelta(seconds=17)), 'natural')
        self.assertEqual(self.sleeps, 17)

    def test_other_jobs_and_claimed_manual_do_not_wake(self):
        for identity, kind, state in (('manual:x', 'cycle', 'running'),
                                      ('manual:y', 'outcomes', 'queued'),
                                      ('cycle:z', 'cycle', 'queued')):
            self.db.execute('INSERT INTO durable_jobs VALUES (?,?,?,?)',
                            (identity, kind, state, self.now.isoformat()))
        self.assertEqual(self.wait(), 'interval')
        self.assertEqual(self.sleeps, 60)

    def test_unavailable_hint_falls_back_to_normal_tick(self):
        self.db.close()
        self.assertEqual(self.wait(), 'interval')
        self.assertEqual(self.sleeps, 60)

    def test_original_tick_keeps_one_hour_due_and_one_cycle(self):
        start = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
        completed = start + timedelta(minutes=37)
        with tempfile.TemporaryDirectory() as folder:
            db = Ledger(Path(folder) / 'control.sqlite3')
            plan = dict(plan_id='plan', revision=1, generation='g', resources=['base:pc'],
                        starts_at=start.isoformat(), state='ACTIVE', mode='daily', resume_count=1)
            db.put('metadata', 'generation', dict(id='g'))
            db.put('pricing_plans', 'plan', plan)
            db.put('operations', 'original', dict(plan_id='plan', status='COMPLETED',
                                                 completed_at=completed.isoformat()))
            with db.transaction() as conn:
                conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','plan',1,'g')")
            future = Mock()
            future.done.return_value = False
            executors = {lane: Mock() for lane in ('collection', 'control', 'observation', 'outcomes')}
            executors['collection'].submit.return_value = future
            running = {}
            with patch.object(scheduler, 'ledger', return_value=db), \
                    patch.object(scheduler, 'export_shadow_snapshot'), \
                    patch.object(runtime, 'write_json'), \
                    patch('automation_policy.load_policy', return_value=dict(interval_minutes=60)):
                with patch.object(scheduler, 'clock', return_value=completed + timedelta(minutes=59)):
                    natural = scheduler.tick(executors, running)
                self.assertEqual(natural, completed + timedelta(hours=1))
                with db.connect() as conn:
                    self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='cycle'").fetchone()[0], 0)
                with patch.object(scheduler, 'clock', return_value=natural):
                    scheduler.tick(executors, running)
                    scheduler.tick(executors, running)
            with db.connect() as conn:
                rows = conn.execute("SELECT id,state FROM durable_jobs WHERE kind='cycle'").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['state'], 'running')
            self.assertTrue(rows[0]['id'].endswith(':r1'))
            executors['collection'].submit.assert_called_once()


    def test_original_future_retry_wakes_at_due_without_changing_identity(self):
        now = datetime(2026, 11, 20, 0, 43, 10, tzinfo=timezone.utc)
        due = now + timedelta(seconds=29, milliseconds=700)
        for deferred in (False, True):
            with self.subTest(deferred=deferred), tempfile.TemporaryDirectory() as folder:
                db = Ledger(Path(folder) / 'control.sqlite3')
                plan = dict(plan_id='plan', revision=1, generation='g', resources=['base:pc'],
                            starts_at=(now - timedelta(hours=1)).isoformat(),
                            last_cycle_at=(now - timedelta(hours=1)).isoformat(),
                            state='ACTIVE', mode='daily', resume_count=1)
                db.put('metadata', 'generation', dict(id='g'))
                db.put('pricing_plans', 'plan', plan)
                body = dict(plan_id='plan', revision=1)
                if deferred:
                    body['deferred_reason'] = scheduler.WAITING_FOR_ES
                identity = 'cycle:plan:original:r1'
                db.enqueue('cycle', identity, due, body)
                with db.transaction() as conn:
                    conn.execute("INSERT INTO plan_ownership VALUES ('base:pc','plan',1,'g')")
                    conn.execute('UPDATE durable_jobs SET attempt=? WHERE id=?', (2, identity))
                future = Mock()
                future.done.return_value = False
                executors = {lane: Mock() for lane in ('collection', 'control', 'observation', 'outcomes')}
                executors['collection'].submit.return_value = future
                running = {}
                with patch.object(scheduler, 'ledger', return_value=db), \
                        patch.object(scheduler, 'export_shadow_snapshot'), \
                        patch.object(runtime, 'write_json'), \
                        patch('automation_policy.load_policy', return_value=dict(interval_minutes=60)):
                    with patch.object(scheduler, 'clock', return_value=now):
                        self.assertEqual(scheduler.tick(executors, running), due)
                    with db.connect() as conn:
                        before = dict(conn.execute('SELECT * FROM durable_jobs WHERE id=?', (identity,)).fetchone())
                    self.assertEqual((before['state'], before['attempt'], before['due_at']),
                                     ('queued', 2, due.isoformat()))
                    with patch.object(scheduler, 'clock', return_value=due):
                        scheduler.tick(executors, running)
                        scheduler.tick(executors, running)
                with db.connect() as conn:
                    rows = conn.execute("SELECT id,state,attempt,due_at FROM durable_jobs WHERE kind='cycle'").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(tuple(rows[0]), (identity, 'running', 2, due.isoformat()))
                executors['collection'].submit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
