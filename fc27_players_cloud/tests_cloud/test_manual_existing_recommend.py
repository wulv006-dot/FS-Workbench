"""Scoped manual recommendation; fake backend only, no production connections."""
import io
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from player_web.main import App
from player_web.existing_action_service import execute_existing_action, prepare_existing_action
from player_web.model_service import refresh_models
from player_web.repository import Repository, StateError
from player_web.settings import Settings
from tests_cloud.test_feature_parity import Backend, configuration


class ManualRecommendationTests(unittest.TestCase):
    def test_scoped_confirm_execution_and_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = replace(configuration(root), manual_existing_recommend_enabled=True)
            repo = Repository(root / 'db/control.sqlite3'); repo.initialize()
            backend = Backend(3)
            snapshot = refresh_models(config, repo, backend, 'operator')
            def plan(action='recommend_enable'):
                return prepare_existing_action(config, repo, backend, 'operator', snapshot['snapshot_id'], [300000, 300001], action, [9] if 'tags' in action else [])
            app = App(config); app._pool.shutdown(wait=True)
            def call(path, headers, body=None):
                raw = json.dumps(body or {}).encode()
                env = {'PATH_INFO': path, 'REQUEST_METHOD': 'GET' if body is None else 'POST',
                       'REMOTE_ADDR': '127.0.0.1', 'wsgi.input': io.BytesIO(raw), 'CONTENT_LENGTH': str(len(raw)), **headers}
                result = {}
                def start(status, headers): result.update(status=status, headers=dict(headers))
                result['body'] = json.loads(b''.join(app(env, start)))
                return result
            gate = {'HTTP_X_FC27_USER': 'operator', 'HTTP_X_FC27_ROLE': 'admin'}
            boot = call('/api/bootstrap', gate)
            self.assertFalse(boot['body']['write_enabled'])
            self.assertTrue(boot['body']['existing_recommend_write_enabled'])
            headers = {**gate, 'HTTP_COOKIE': boot['headers']['Set-Cookie'].split(';')[0],
                       'HTTP_ORIGIN': config.public_origin, 'HTTP_X_CSRF_TOKEN': boot['body']['csrf']}
            recommended = plan()
            path = '/api/plans/' + recommended['plan_id'] + '/confirm'
            body = {'confirmed': True, 'plan_digest': recommended['plan_digest']}
            self.assertEqual(call(path, headers, body)['body']['error'], 'AUTH_REQUIRED')
            app._sessions['operator:' + app._browser_sid(headers)] = (backend, time.time(), time.time())
            for changed, error in [({'HTTP_X_FC27_ROLE': 'readonly'}, 'ROLE_REQUIRED'),
                                   ({'HTTP_X_CSRF_TOKEN': 'invalid'}, 'CSRF_INVALID'),
                                   ({'HTTP_ORIGIN': 'https://wrong.invalid'}, 'ORIGIN_MISMATCH')]:
                self.assertEqual(call(path, {**headers, **changed}, body)['body']['error'], error)
            self.assertEqual(call(path, headers, {**body, 'confirmed': False})['body']['error'], 'EXPLICIT_CONFIRMATION_REQUIRED')
            self.assertEqual(call(path, headers, {**body, 'plan_digest': 'wrong'})['body']['error'], 'PLAN_STALE')
            stop = root / 'STOP_WRITES'; stop.touch()
            self.assertEqual(call(path, headers, body)['body']['error'], 'WRITE_DISABLED'); stop.unlink()
            for action in ('add_tags', 'remove_tags', 'recommend_disable'):
                blocked = plan(action)
                self.assertEqual(call('/api/plans/' + blocked['plan_id'] + '/confirm', headers,
                                      {'confirmed': True, 'plan_digest': blocked['plan_digest']})['body']['error'], 'WRITE_DISABLED')
                with self.assertRaisesRegex(StateError, 'WRITE_DISABLED'):
                    execute_existing_action(config, repo, backend, 'unused', blocked)
            blocked = repo.save_plan('operator', {'kind': 'existing_action', 'action': 'recommend_enable',
                                                'scope_ids': ['999'], 'blockers': ['LEGACY_UNRESOLVED']})
            self.assertEqual(call('/api/plans/' + blocked['plan_id'] + '/confirm', headers,
                                  {'confirmed': True, 'plan_digest': blocked['plan_digest']})['body']['error'], 'PLAN_BLOCKED')
            expired = plan()
            with repo.connection() as db: db.execute("UPDATE plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (expired['plan_id'],))
            self.assertEqual(call('/api/plans/' + expired['plan_id'] + '/confirm', headers,
                                  {'confirmed': True, 'plan_digest': expired['plan_digest']})['body']['error'], 'PLAN_STALE')
            with patch.object(app._pool, 'submit') as submit:
                accepted = call(path, headers, body)
                self.assertTrue(accepted['status'].startswith('202'))
                self.assertEqual(call(path, headers, body)['body']['execution_id'], accepted['body']['execution_id'])
                submit.assert_called_once()
            execute_existing_action(config, repo, backend, accepted['body']['execution_id'], recommended)
            self.assertEqual(backend.writes, [{'is_rec': 1, 'id': [300000]}])
            self.assertEqual(repo.get_execution(accepted['body']['execution_id'], 'operator')['status'], 'completed_readback')
            self.assertEqual(backend.rows[300000]['tid'], [7])

    def test_flag_defaults_off_and_only_enables_recommend(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(Settings.from_env().existing_action_write_enabled('recommend_enable'))
        with patch.dict(os.environ, {'MANUAL_EXISTING_RECOMMEND_ENABLED': 'true'}, clear=True):
            config = Settings.from_env()
            self.assertFalse(config.write_enabled)
            self.assertTrue(config.existing_action_write_enabled('recommend_enable'))
            self.assertFalse(config.existing_action_write_enabled('recommend_disable'))


if __name__ == '__main__': unittest.main()
