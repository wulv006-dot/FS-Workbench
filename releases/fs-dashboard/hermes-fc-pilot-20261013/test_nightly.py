from datetime import datetime, timedelta, timezone
from pathlib import Path
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from nightly import NightlyScheduler, due, closed_period, preparation_status, SHANGHAI
from pilot import TaskStore
import direct_provider


class Service:
    def __init__(self, root):
        self.root = Path(root)
        self.tasks = TaskStore(self.root/'tasks.sqlite3')
        self.at = datetime(2026, 10, 19, 2, tzinfo=SHANGHAI)
        self.calls = []
        self.jobs = {}
        self.stops = []
        with self.tasks.db() as db:
            db.execute('CREATE TABLE requests(id TEXT, state TEXT)')
        self.authorizer = lambda owner: owner == 'wulv'

    def clock(self):
        return self.at

    def get_job(self, owner, key):
        return self.jobs.get(key)

    def submit_scheduled(self, body):
        self.calls.append(body)
        return 202, {'state': 'PREPARING'}

    def cancel_job(self, owner, key, reason):
        self.stops.append((key, reason))
        return 202, {'state': 'CANCEL_REQUESTED'}

    def update(self,key,**values):
        self.jobs.setdefault(key,{}).update(values)


class NightlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = Service(self.tmp.name)
        self.scheduler = NightlyScheduler(self.service, readiness=lambda now: (True, []))
        self.config = self.service.root/'nightly-schedule.json'
        self.config.write_text(json.dumps({'contract': 'fs-hermes-nightly-v1', 'enabled': True,
                                          'owner': 'wulv', 'timezone': 'Asia/Shanghai'}))
        self.config.chmod(0o600)

    def rows(self):
        with self.service.tasks.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM nightly_requests')]

    def test_day_week_month_closed_boundaries_and_utc_conversion(self):
        now = datetime(2027, 3, 1, 3, 30, tzinfo=SHANGHAI)
        self.assertEqual([x['kind'] for x in due(now)], ['daily', 'weekly', 'monthly'])
        self.assertEqual(due(now), due(now.astimezone(timezone.utc)))
        self.assertEqual(closed_period(now.date(), 'monthly'), ('2027-02-01', '2027-02-28'))
        self.assertEqual(closed_period(datetime(2028, 3, 1).date(), 'monthly'), ('2028-02-01', '2028-02-29'))

    def test_no_daytime_admission_or_disabled_timer(self):
        self.service.at = self.service.at.replace(hour=7)
        self.scheduler.tick()
        self.assertEqual(self.service.calls, [])
        self.config.unlink()
        self.service.at = self.service.at.replace(hour=2)
        self.scheduler.tick()
        self.assertEqual(self.service.calls, [])

    def test_durable_daily_then_weekly_without_same_day_replay(self):
        self.scheduler.tick()
        self.scheduler.tick()
        self.scheduler.tick()
        self.assertEqual([x['mode'] for x in self.service.calls], ['daily', 'investigation'])
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.service.calls[0]['start'], '2026-10-18')
        self.assertEqual(self.service.calls[1]['start'], '2026-10-12')

    def test_existing_manual_chain_keeps_scheduled_ai_waiting(self):
        with self.service.tasks.db() as db:
            db.execute("INSERT INTO requests VALUES('manual','RUNNING')")
        self.scheduler.tick()
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.rows(), [])

    def test_missing_preparation_is_visible_then_expires_without_next_night_replay(self):
        self.scheduler.readiness = lambda now: (False, ['management_preparation_missing'])
        self.scheduler.tick()
        row = self.rows()[0]
        self.assertEqual(row['state'], 'WAITING')
        self.assertEqual(row['error'], 'management_preparation_missing')
        self.service.at += timedelta(days=1)
        self.scheduler.tick()
        expired = next(x for x in self.rows() if x['id'] == row['id'])
        self.assertEqual(expired['state'], 'EXPIRED')
        self.assertEqual(self.service.calls, [])

    def test_inflight_deadline_is_enforced_with_config_removed(self):
        self.scheduler.tick()
        row = self.rows()[0]
        self.service.jobs[row['id']] = {'state': 'RUNNING'}
        self.config.unlink()
        self.service.at = self.service.at.replace(hour=6,minute=59)
        self.scheduler.tick()
        self.assertEqual(self.service.stops, [(row['id'], 'nightly_deadline_exceeded')])

    def test_result_delivery_pending_never_reopens_model(self):
        self.scheduler.tick()
        row = self.rows()[0]
        self.service.jobs[row['id']] = {'state': 'REPORT_PENDING'}
        self.service.at = self.service.at.replace(hour=7)
        self.scheduler.tick()
        self.assertEqual(self.rows()[0]['state'], 'REPORT_PENDING')
        self.assertEqual(self.service.stops, [])
        self.assertEqual(len(self.service.calls), 1)

    def test_wrong_owner_configuration_rejected(self):
        value = json.loads(self.config.read_text())
        value['owner'] = 'other'
        self.config.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.scheduler.tick()
        self.assertEqual(self.service.calls, [])

    def test_preparation_failures_are_disclosed_instead_of_success(self):
        root = Path(self.tmp.name)/'boss'
        (root/'public').mkdir(parents=True)
        for kind in ('game-monitor', 'management'):
            (root/'public'/(kind+'.status.json')).write_text(json.dumps({'day': '2026-10-19', 'phase': 'completed', 'status': 'failed'}))
        record = Path(self.tmp.name)/'marketing.json'
        record.write_text(json.dumps({'completed_at_utc': self.service.at.astimezone(timezone.utc).isoformat(),
                                     'steps': {'synthetic': 2}, 'publication_performed': False}))
        ready, warnings = preparation_status(self.service.at, boss_root=root, marketing_record=record)
        self.assertTrue(ready)
        self.assertEqual(len(warnings), 3)


class DeadlineTransportTests(unittest.TestCase):
    def test_expired_deadline_rejected_before_key_or_network(self):
        with patch.object(direct_provider, '_load_key') as key:
            result = direct_provider._open('/chat/completions', b'{}', deadline=datetime.now(timezone.utc)-timedelta(seconds=1))
        self.assertEqual(result, {'status': 'scheduled_deadline', 'network_started': False})
        key.assert_not_called()

    def test_real_loopback_stream_stops_at_absolute_deadline(self):
        finish = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(b': synthetic keepalive\n\n')
                self.wfile.flush()
                finish.wait(3)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            with patch.object(direct_provider, 'BASE_URL', 'http://127.0.0.1:'+str(server.server_port)), patch.object(direct_provider, '_load_key', return_value='sk-synthetic-nonsecret'):
                result = direct_provider._open('/chat/completions', b'{"stream":true}', deadline=datetime.now(timezone.utc)+timedelta(seconds=0.25))
            self.assertEqual(result['status'], 'scheduled_deadline')
            self.assertLess(time.monotonic()-started, 1.5)
            self.assertTrue(result['response_headers_received'])
        finally:
            finish.set()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
