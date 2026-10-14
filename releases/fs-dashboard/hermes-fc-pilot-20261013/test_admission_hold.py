from unittest.mock import patch
import unittest
import test_controller as fixture
from fs_inprocess import spending_hold
from pilot import digest, encoded


class AdmissionHoldTests(unittest.TestCase):
    setUp = fixture.ControllerTests.setUp
    def seed_hold(self, state='unknown', owner='owner', amount=344416):
        self.fp = 'e' * 64
        with self.daily.db() as db:
            db.execute('CREATE TABLE hermes_reservations(fingerprint TEXT PRIMARY KEY,owner TEXT,task TEXT,turn INTEGER,request_digest TEXT,policy TEXT,tokens INTEGER,microcny INTEGER)')
            db.execute('INSERT INTO hermes_reservations VALUES(?,?,?,?,?,?,?,?)',
                       (self.fp, owner, 'old_failed_task', 3, 'digest', '{}', 1, amount))
            db.execute('INSERT INTO model_calls VALUES(?,?,?,NULL)', (self.fp, '2026-10-14', state))

    def test_hold_rejects_before_capture_task_runtime_or_spending(self):
        self.seed_hold()
        with patch('controller.build_book') as capture, patch.object(self.service, 'remote') as remote, patch.dict('sys.modules', {'ai_advisor_model': type('Module', (), {'clean_question': staticmethod(lambda q: q)})()}):
            status, body = self.service.post(self.body, 'owner', self.headers)
        self.assertEqual((status, body), (503, {'error': 'pilot_usage_hold'}))
        capture.assert_not_called(); remote.assert_not_called()
        with self.service.tasks.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)
        with self.daily.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT state,content FROM model_calls').fetchone()[:], ('unknown', None))

    def test_history_exposes_safe_hold_without_private_reservation(self):
        self.seed_hold()
        status, body = self.service.get({'mode': ['hermes']}, 'owner')
        self.assertEqual(status, 200); self.assertFalse(body['can_generate'])
        self.assertEqual(body['admission'], {'status': 'blocked', 'reason': 'pilot_usage_hold'})
        self.assertNotIn(self.fp, str(body)); self.assertNotIn('344416', str(body))

    def test_exact_approval_allows_new_task_by_same_owner(self):
        self.seed_hold()
        with patch('fs_inprocess.approved_unknowns', return_value={self.fp: 344416}):
            self.assertIsNone(spending_hold(self.daily, self.service.tasks, 'owner'))
            self.assertEqual(spending_hold(self.daily, self.service.tasks, 'different_owner'), 'pilot_usage_hold')
        with self.daily.db() as db:
            self.assertEqual(db.execute('SELECT state,content FROM model_calls').fetchone()[:], ('unknown', None))

    def test_started_cannot_be_approved(self):
        self.seed_hold('started')
        with patch('fs_inprocess.approved_unknowns', return_value={self.fp: 344416}):
            self.assertEqual(spending_hold(self.daily, self.service.tasks, 'owner'), 'pilot_usage_hold')

    def test_wrong_amount_remains_blocked(self):
        self.seed_hold()
        with patch('fs_inprocess.approved_unknowns', return_value={self.fp: 344415}):
            self.assertEqual(spending_hold(self.daily, self.service.tasks, 'owner'), 'pilot_usage_hold')

    def test_initial_ledger_ready_without_mutation(self):
        status, body = self.service.get({'mode': ['hermes']}, 'owner')
        self.assertEqual(status, 200); self.assertTrue(body['can_generate'])
        self.assertEqual(body['admission'], {'status': 'ready', 'reason': None})
        with self.daily.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_reservations'").fetchone())

    def test_runtime_failure_projects_only_explicit_safe_code(self):
        self.build_gateway = fixture.ControllerTests.build_gateway.__get__(self)
        for index, error in enumerate(('HTTP 400: FC model request blocked: context_window_exceeded', 'private error detail')):
            body = dict(self.body, request_id='safe_error_fixture_'+str(index), question=self.body['question']+str(index))
            def remote(method, *args, **kwargs):
                return (202, {'run_id': 'run_'+str(index+1)*32, 'status': 'queued'}) if method == 'POST' else (200, {'status': 'failed', 'error': error})
            with patch('controller.build_book', return_value=self.book), patch('controller.gateway', side_effect=self.build_gateway), patch.object(self.service, 'remote', side_effect=remote), patch.dict('sys.modules', {'ai_advisor_model': type('Module', (), {'clean_question': staticmethod(lambda q: q)})()}):
                status, result = self.service.post(body, 'owner', self.headers)
            self.assertEqual(status, 202); self.assertEqual(result['state'], 'FAILED')
            self.assertEqual(result['error'], 'context_window_exceeded' if index == 0 else 'runtime_failed')
            with self.daily.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 0)

    def test_new_release_accepts_new_request_without_replaying_old_failed_task(self):
        old_spec = {'period': {'start': '2026-10-05', 'end_exclusive': '2026-10-12', 'timezone': 'Asia/Shanghai'},
                    'snapshot_id': self.book.capture_id, 'template_version': 'v2-'+digest({k:v for k,v in self.body.items() if k!='request_id'})[:20],
                    'knowledge_version': self.book.skills['version'], 'budget_policy_id': 'existing-ledger-public-estimate'}
        old = self.service.tasks.create('owner', old_spec)
        self.service.tasks.reserve_dispatch(old['id'], 'owner', 'old_lease')
        self.service.tasks.bind_run(old['id'], 'owner', 'old_lease', 'run_'+'c'*32)
        self.service.tasks.observe(old['id'], 'owner', 'old_lease', 'failed', worker_stopped=True)
        old_body = dict(self.body, request_id='old_failed_request')
        old_key = digest({'owner': 'owner', 'request_id': old_body['request_id']})[:32]
        with self.service.tasks.db() as db:
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?)', (old_key, 'owner', old_body['request_id'], encoded(old_body), 'FAILED', old['id'], 'runtime_failed', None))
        def remote(method, *args, **kwargs):
            return (202, {'run_id': 'run_'+'d'*32, 'status': 'queued'}) if method == 'POST' else (200, {'status': 'failed', 'error': 'synthetic terminal'})
        build_gateway = fixture.ControllerTests.build_gateway.__get__(self)
        with patch('controller.build_book', return_value=self.book), patch('controller.gateway', side_effect=build_gateway), patch.object(self.service, 'remote', side_effect=remote) as runtime, patch.dict('sys.modules', {'ai_advisor_model': type('Module', (), {'clean_question': staticmethod(lambda q: q)})()}):
            status, result = self.service.post(self.body, 'owner', self.headers)
            before = runtime.call_count
            replay_status, replay = self.service.post(old_body, 'owner', self.headers)
        self.assertEqual(status, 202); self.assertNotEqual(result['task_id'], old['id'])
        self.assertEqual((replay_status, replay['task_id']), (200, old['id']))
        self.assertEqual(runtime.call_count, before)
        self.assertEqual(self.service.tasks.get(old['id'], 'owner')['state'], 'FAILED')
        self.assertTrue(self.service.tasks.get(result['task_id'], 'owner')['spec']['template_version'].startswith('v3-1m-'))


if __name__ == '__main__':
    unittest.main()
