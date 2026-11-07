from __future__ import annotations

import hashlib
import io
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from player_web.main import App
from player_web.media_client import ImageUploadNotStarted, upload_png, edit_model_icon
from player_web.model_image_service import (create_batch, stage_png, prepare_image_plan,
                                            verify_image_plan, execute_image_plan, validate_png)
from player_web.model_service import refresh_models
from player_web.repository import Repository, StateError
from tests_cloud.test_feature_parity import Backend, configuration
from 球员维护工具.admin_client import AdminContractError


def png():
    buffer = io.BytesIO()
    Image.new('RGBA', (24, 32), (30, 60, 90, 200)).save(buffer, format='PNG')
    return buffer.getvalue()


class ModelImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = replace(configuration(self.root), manual_model_images_enabled=True)
        self.repo = Repository(self.root / 'db/control.sqlite3')
        self.repo.initialize()
        self.backend = Backend(3)
        for row in self.backend.rows.values():
            row['icon'] = 0
        self.backend.rows[300001]['icon'] = 99
        self.content = png()
        self.snapshot = refresh_models(self.settings, self.repo, self.backend, 'operator')['snapshot_id']

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name='400000.png'):
        return {'name': name, 'size': len(self.content), 'sha256': hashlib.sha256(self.content).hexdigest()}

    def batch(self, names=('400000.png',), overwrite=False):
        return create_batch(self.settings, self.repo, self.backend, 'operator', self.snapshot,
                            [self.file(name) for name in names], overwrite)

    def plan(self, names=('400000.png',), overwrite=False):
        batch = self.batch(names, overwrite)
        for item in batch['items']:
            if item['status'] == 'matched':
                stage_png(self.settings, 'operator', batch['batch_id'], item['name'], self.content)
        return prepare_image_plan(self.settings, self.repo, self.backend, 'operator', batch['batch_id'])

    def execution(self, plan):
        return self.repo.confirm(plan['plan_id'], 'operator', plan['plan_digest'], write_enabled=True)[0]

    def bind(self, client, model_id, attachment_id):
        self.backend.writes.append({'id': model_id, 'icon': attachment_id})
        self.backend.rows[model_id]['icon'] = attachment_id

    def test_match_skip_existing_and_unmatched_not_in_execution(self):
        batch = self.batch(('400000.png', '400001.png', '999999.png', '../400002.png', 'Player.png'))
        self.assertEqual([x['status'] for x in batch['items']],
                         ['matched', 'existing_image_skipped', 'unmatched', 'invalid_filename', 'invalid_filename'])
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.plan()['scope_ids'], ['400000'])

    def test_explicit_overwrite_freezes_old_icon(self):
        plan = self.plan(('400001.png',), overwrite=True)
        self.assertEqual(plan['items'][0]['before'], {'icon': 99})
        self.assertTrue(plan['overwrite'])

    def test_duplicate_basename_and_case_duplicate_rejected(self):
        for names in [('400000.png', '400000.png'), ('400000.png', '400000.PNG')]:
            with self.assertRaisesRegex(StateError, 'IMAGE_DUPLICATE_FILENAME'):
                self.batch(names)

    def test_duplicate_futbin_models_never_bound(self):
        self.backend.rows[300002]['futbin_id'] = '400000'
        self.snapshot = refresh_models(self.settings, self.repo, self.backend, 'operator')['snapshot_id']
        self.assertEqual(self.batch()['items'][0]['status'], 'ambiguous_model')

    def test_foreign_owner_and_expired_batch_cannot_stage(self):
        batch = self.batch()
        with self.assertRaisesRegex(StateError, 'IMAGE_BATCH_EXPIRED'):
            stage_png(self.settings, 'someone', batch['batch_id'], '400000.png', self.content)
        path = self.root / 'image_batches' / batch['batch_id'] / 'manifest.json'
        batch['expires_at'] = '2000-01-01T00:00:00+00:00'
        path.write_text(json.dumps(batch))
        with self.assertRaisesRegex(StateError, 'IMAGE_BATCH_EXPIRED'):
            stage_png(self.settings, 'operator', batch['batch_id'], '400000.png', self.content)

    def test_content_hash_png_format_and_staging_idempotency(self):
        batch = self.batch()
        args = (self.settings, 'operator', batch['batch_id'], '400000.png')
        with self.assertRaisesRegex(StateError, 'IMAGE_FILE_CHANGED'):
            stage_png(*args, self.content + b'x')
        self.assertEqual(stage_png(*args, self.content), stage_png(*args, self.content))
        for content in (b'not png', self.content[:30], self.content + b'x' * 2097152):
            with self.assertRaisesRegex(StateError, 'INVALID_PNG'):
                validate_png(content)

    def test_artifact_tamper_and_live_model_change_block_before_upload(self):
        plan = self.plan()
        self.backend.rows[300000]['icon'] = 111
        with self.assertRaisesRegex(StateError, 'IMAGE_MODEL_CHANGED'):
            verify_image_plan(self.settings, self.backend, plan)
        self.backend.rows[300000]['icon'] = 0
        self.backend.rows[300000]['cid'] = 5
        with self.assertRaisesRegex(StateError, 'IMAGE_MODEL_IDENTITY_CHANGED'):
            verify_image_plan(self.settings, self.backend, plan)
        self.backend.rows[300000]['cid'] = 9627
        Path(plan['items'][0]['artifact_path']).write_bytes(png() + b'x')
        with self.assertRaisesRegex(StateError, 'IMAGE_FILE_CHANGED'):
            verify_image_plan(self.settings, self.backend, plan)

    def test_success_changes_only_icons_and_reads_each_model_back(self):
        plan = self.plan(('400000.png', '400002.png'))
        job = self.execution(plan)
        old = {key: dict(row) for key, row in self.backend.rows.items()}
        with patch('player_web.model_image_service.upload_png', return_value={'attachment_id': 777, 'url': ''}) as upload, \
             patch('player_web.model_image_service.edit_model_icon', side_effect=self.bind):
            execute_image_plan(self.settings, self.repo, self.backend, job, plan)
        self.assertEqual(upload.call_count, 2)
        result = self.repo.get_execution(job, 'operator')
        self.assertEqual(result['status'], 'completed_readback')
        self.assertEqual([item['status'] for item in result['items']], ['verified', 'verified'])
        for key, row in self.backend.rows.items():
            self.assertEqual({k:v for k,v in row.items() if k != 'icon'}, {k:v for k,v in old[key].items() if k != 'icon'})
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM active_scope').fetchone()[0], 0)

    def test_lost_upload_response_stops_batch_and_keeps_scope_no_retry(self):
        plan = self.plan(('400000.png', '400002.png'))
        job = self.execution(plan)
        with patch('player_web.model_image_service.upload_png', side_effect=AdminContractError('IMAGE_UPLOAD_UNKNOWN')) as upload, \
             patch('player_web.model_image_service.edit_model_icon') as edit:
            with self.assertRaises(AdminContractError):
                execute_image_plan(self.settings, self.repo, self.backend, job, plan)
            upload.assert_called_once()
            edit.assert_not_called()
        result = self.repo.get_execution(job, 'operator')
        self.assertEqual(result['status'], 'needs_reconcile')
        self.assertEqual([item['status'] for item in result['items']], ['unknown', 'planned'])
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM active_scope').fetchone()[0], 2)

    def test_pre_dispatch_failure_releases_scope_without_claiming_upload(self):
        plan = self.plan(('400000.png', '400002.png'))
        job = self.execution(plan)
        with patch('player_web.model_image_service.upload_png', side_effect=ImageUploadNotStarted('IMAGE_UPLOAD_PRECHECK_FAILED')), \
             patch('player_web.model_image_service.edit_model_icon') as edit:
            with self.assertRaises(ImageUploadNotStarted):
                execute_image_plan(self.settings, self.repo, self.backend, job, plan)
            edit.assert_not_called()
        result = self.repo.get_execution(job, 'operator')
        self.assertEqual((result['status'], result['step']), ('failed', 'image_not_started'))
        self.assertEqual([item['status'] for item in result['items']], ['not_started', 'planned'])
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM active_scope').fetchone()[0], 0)

    def test_readback_failure_preserves_attachment_id_and_does_not_repeat(self):
        plan = self.plan()
        job = self.execution(plan)
        with patch('player_web.model_image_service.upload_png', return_value={'attachment_id': 777, 'url': ''}) as upload, \
             patch('player_web.model_image_service.edit_model_icon') as edit:
            with self.assertRaisesRegex(StateError, 'IMAGE_READBACK_INCOMPLETE'):
                execute_image_plan(self.settings, self.repo, self.backend, job, plan)
            upload.assert_called_once()
            edit.assert_called_once()
        result = self.repo.get_execution(job, 'operator')
        self.assertEqual(result['items'][0]['after']['attachment_id'], 777)
        self.assertEqual(result['status'], 'needs_reconcile')

    def test_write_switch_and_stop_before_upload(self):
        plan = self.plan()
        job = self.execution(plan)
        with patch('player_web.model_image_service.upload_png') as upload:
            with self.assertRaisesRegex(StateError, 'WRITE_DISABLED'):
                execute_image_plan(replace(self.settings, manual_model_images_enabled=False), self.repo, self.backend, job, plan)
            execute_image_plan(self.settings, self.repo, self.backend, job, plan, lambda: True)
            upload.assert_not_called()
        self.assertEqual(self.repo.get_execution(job, 'operator')['status'], 'stopped')
        self.assertFalse(self.settings.write_enabled)
        self.assertFalse(self.settings.new_card_write_enabled)
        self.assertTrue(self.settings.model_image_write_enabled)

    def test_http_scope_confirmation_auth_csrf_and_no_duplicate_dispatch(self):
        app = App(self.settings)
        app._pool.shutdown(wait=True)
        def call(path, data=None, headers=None, raw=None):
            body = raw if raw is not None else json.dumps(data or {}).encode()
            env = {'PATH_INFO': path, 'REQUEST_METHOD': 'POST' if data is not None or raw is not None else 'GET',
                   'REMOTE_ADDR':'127.0.0.1', 'wsgi.input':io.BytesIO(body), 'CONTENT_LENGTH':str(len(body)),
                   'CONTENT_TYPE':'image/png' if raw is not None else 'application/json', **(headers or {})}
            response = {}
            def start(status, values):
                response.update(status=status, headers=dict(values))
            response['body'] = json.loads(b''.join(app(env, start)))
            return response
        gate = {'HTTP_X_FC27_USER':'operator', 'HTTP_X_FC27_ROLE':'admin'}
        boot = call('/api/bootstrap', headers=gate)
        headers = {**gate, 'HTTP_COOKIE':boot['headers']['Set-Cookie'].split(';')[0],
                   'HTTP_ORIGIN':self.settings.public_origin, 'HTTP_X_CSRF_TOKEN':boot['body']['csrf']}
        self.assertTrue(boot['body']['model_image_write_enabled'])
        self.assertFalse(boot['body']['write_enabled'])
        self.assertEqual(call('/api/image-batches', {}, headers)['body']['error'], 'AUTH_REQUIRED')
        app._sessions['operator:' + app._browser_sid(headers)] = (self.backend, time.time(), time.time())
        payload = {'snapshot_id':self.snapshot, 'files':[self.file()]}
        self.assertEqual(call('/api/image-batches', payload, {**headers, 'HTTP_X_CSRF_TOKEN':'bad'})['body']['error'], 'CSRF_INVALID')
        self.assertEqual(call('/api/image-batches', payload, {**headers, 'HTTP_X_FC27_ROLE':'readonly'})['body']['error'], 'ROLE_REQUIRED')
        batch = call('/api/image-batches', payload, headers)['body']
        staged = call('/api/image-batches/' + batch['batch_id'] + '/files/400000.png', headers=headers, raw=self.content)
        self.assertTrue(staged['body']['staged'])
        plan = call('/api/plans/model-images', {'batch_id':batch['batch_id']}, headers)['body']
        self.assertNotIn('artifact_path', plan['items'][0])
        with patch.object(app._pool, 'submit') as submit:
            path = '/api/plans/' + plan['plan_id'] + '/confirm'
            self.assertEqual(call(path, {'confirmed':False, 'plan_digest':plan['plan_digest']}, headers)['body']['error'], 'EXPLICIT_CONFIRMATION_REQUIRED')
            accepted = call(path, {'confirmed':True, 'plan_digest':plan['plan_digest']}, headers)
            self.assertTrue(accepted['status'].startswith('202'))
            self.assertEqual(call(path, {'confirmed':True, 'plan_digest':plan['plan_digest']}, headers)['body']['status'], 'existing')
            submit.assert_called_once()
        app._sessions.clear()


class MediaContractTests(unittest.TestCase):
    def test_get_failure_is_definitely_not_dispatched(self):
        import urllib.error
        opening = unittest.mock.Mock(side_effect=urllib.error.HTTPError('https://example.test/module.js', 404, 'missing', {}, None))
        with patch('player_web.media_client.urllib.request.build_opener', return_value=SimpleNamespace(open=opening)):
            with self.assertRaisesRegex(ImageUploadNotStarted, 'IMAGE_UPLOAD_PRECHECK_FAILED'):
                upload_png(SimpleNamespace(authenticated=True, timeout=3), Path('unused.png'))
        self.assertEqual(opening.call_count, 1)
        self.assertEqual(opening.call_args.args[0].get_method(), 'GET')

    def test_changed_signer_is_not_dispatched(self):
        opening = unittest.mock.Mock(return_value=io.BytesIO(b'changed module'))
        with patch('player_web.media_client.urllib.request.build_opener', return_value=SimpleNamespace(open=opening)):
            with self.assertRaisesRegex(ImageUploadNotStarted, 'IMAGE_UPLOAD_CONTRACT_CHANGED'):
                upload_png(SimpleNamespace(authenticated=True, timeout=3), Path('unused.png'))
        self.assertEqual(opening.call_count, 1)

    def test_post_timeout_remains_unknown_and_is_not_retried(self):
        script = b'const UPLOAD_AUTH_SECRET="synthetic-test-material";'
        opening = unittest.mock.Mock(side_effect=[io.BytesIO(script), TimeoutError()])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'400000.png'
            path.write_bytes(png())
            with patch('player_web.media_client.AUTH_MODULE_SHA', hashlib.sha256(script).hexdigest()), \
                 patch('player_web.media_client.urllib.request.build_opener', return_value=SimpleNamespace(open=opening)):
                with self.assertRaisesRegex(AdminContractError, 'IMAGE_UPLOAD_UNKNOWN') as caught:
                    upload_png(SimpleNamespace(authenticated=True, timeout=3), path)
                self.assertNotIsInstance(caught.exception, ImageUploadNotStarted)
        self.assertEqual([call.args[0].get_method() for call in opening.call_args_list], ['GET', 'POST'])

    def test_upload_one_post_with_official_signature_and_attachment_id(self):
        import urllib.error
        material = 'synthetic-test-material'
        script = ('const UPLOAD_AUTH_SECRET=' + json.dumps(material) + ';').encode()
        current_module = 'https://admin.p2pah.cn/assets/uploadAuth-ac6fbfe3.js'
        retired_module = 'https://admin.p2pah.cn/assets/uploadAuth-4cd714b6.js'
        fixed_time = 1793980000.125
        expected_timestamp = 1793980000125
        response = {'upload':{'picture':{'code':200,'file':{'id':778,'full_url':'https://example.test/778.png'}}}}
        calls = []
        def opening(request, timeout):
            calls.append(request)
            if request.get_method() == 'GET':
                if request.full_url == retired_module:
                    raise urllib.error.HTTPError(retired_module, 404, 'missing', {}, None)
                self.assertEqual(request.full_url, current_module)
                return io.BytesIO(script)
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(request.full_url, 'https://b2c-api.p2pah.cn/upload/file')
            return io.BytesIO(json.dumps(response).encode())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '400000.png'
            image = png()
            path.write_bytes(image)
            with patch('player_web.media_client.AUTH_MODULE_SHA', hashlib.sha256(script).hexdigest()), \
                 patch('player_web.media_client.time.time', return_value=fixed_time), \
                 patch('player_web.media_client.urllib.request.build_opener', return_value=SimpleNamespace(open=opening)):
                result = upload_png(SimpleNamespace(authenticated=True, timeout=3), path)
        self.assertEqual(result['attachment_id'], 778)
        self.assertEqual([request.get_method() for request in calls], ['GET', 'POST'])
        self.assertFalse(any(name.lower() == 'ba-token' for name in calls[-1].headers))
        fields = {'token': hashlib.md5((str(expected_timestamp) + material).encode()).hexdigest(),
                  'timestamp': expected_timestamp, 'id': 0, 'view': 1, 'type': 0, 'watermark': 0}
        # Inspect synthetic signing values only in memory; assertion failures never dump the multipart.
        for name, value in fields.items():
            part = ('name="' + name + '"\r\n\r\n' + str(value) + '\r\n').encode()
            self.assertTrue(part in calls[-1].data, 'multipart field mismatch: ' + name)
        self.assertTrue(b'name="file"; filename="400000.png"' in calls[-1].data,
                        'multipart file identity mismatch')
        self.assertTrue(image in calls[-1].data, 'multipart PNG bytes changed')
        self.assertFalse(material.encode() in calls[-1].data, 'signing material must not be uploaded')

    def test_icon_write_uses_narrow_official_model_field(self):
        calls = []
        client = SimpleNamespace(_edit_fields=lambda *args, **kwargs: calls.append((args,kwargs)))
        edit_model_icon(client, 123, 778)
        self.assertEqual(calls[0][0], ('/admin/goods.GoodsMould/edit', {'id':123, 'icon':778}))
        self.assertEqual(calls[0][1]['allowed_fields'], {'icon'})


if __name__ == '__main__':
    unittest.main()
