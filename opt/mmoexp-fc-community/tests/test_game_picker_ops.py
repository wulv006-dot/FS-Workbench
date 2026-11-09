import importlib
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


class FakeDiscord:
    def __init__(self, fail_after_post=False):
        self.messages = {}
        self.posts = 0
        self.fail_after_post = fail_after_post

    def request(self, method, route, payload=None):
        if route == 'users/@me':
            return {'id': '1568239618111832094', 'bot': True}
        if route == 'channels/1568260661010497627':
            return {'id': '1568260661010497627', 'guild_id': '1565922092518613064', 'type': 0}
        if route == 'channels/1569198390107971795':
            return {'id': '1569198390107971795', 'guild_id': '1041923524601851914', 'type': 0}
        if method == 'POST':
            self.posts += 1
            self.messages['900000000000000001'] = dict(payload, id='900000000000000001',
                author={'id': '1568239618111832094'})
            if self.fail_after_post:
                raise OSError('ambiguous send')
            return self.messages['900000000000000001']
        return self.messages[route.rsplit('/', 1)[-1]]


class PublishGamePickerTests(unittest.TestCase):
    def setUp(self):
        try:
            self.ops = importlib.import_module('ops.publish_game_picker')
        except ModuleNotFoundError as exc:
            if exc.name == 'ops.publish_game_picker':
                self.fail('game picker publisher is not implemented')
            raise
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.marker = Path(self.tmp.name) / 'game-picker-panel.json'
        self.api = FakeDiscord()

    def payload(self, disabled):
        buttons = [{'type': 2, 'style': 1, 'custom_id': 'mmoexp:game:g' + str(n),
                    'label': 'Game ' + str(n), 'disabled': disabled} for n in range(24)]
        return {'embeds': [{'title': 'Choose your game'}], 'allowed_mentions': {'parse': []},
                'components': [{'type': 1, 'components': buttons[n:n+5]} for n in range(0, 24, 5)]}

    def test_preview_is_disabled_and_reuse_does_not_duplicate(self):
        payload = self.payload(True)
        first = self.ops.publish_panel('preview', payload, self.marker, self.api.request)
        second = self.ops.publish_panel('preview', payload, self.marker, self.api.request)
        self.assertEqual(first, second)
        self.assertEqual(self.api.posts, 1)
        self.assertTrue(all(button['disabled'] for row in self.api.messages[first]['components']
                            for button in row['components']))

    def test_ambiguous_send_is_recorded_and_not_retried(self):
        self.api.fail_after_post = True
        with self.assertRaises(OSError):
            self.ops.publish_panel('official', self.payload(False), self.marker, self.api.request)
        self.api.fail_after_post = False
        with self.assertRaisesRegex(RuntimeError, 'reconcil'):
            self.ops.publish_panel('official', self.payload(False), self.marker, self.api.request)
        self.assertEqual(self.api.posts, 1)

    def test_preview_cannot_publish_live_buttons(self):
        with self.assertRaises(ValueError):
            self.ops.publish_panel('preview', self.payload(False), self.marker, self.api.request)
        self.assertEqual(self.api.posts, 0)

    def test_concurrent_publisher_refuses_existing_lock(self):
        self.marker.with_suffix('.lock').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'lock'):
            self.ops.publish_panel('official', self.payload(False), self.marker, self.api.request)
        self.assertEqual(self.api.posts, 0)

    def test_role_preflight_rejects_management_permissions_on_channel_overwrite(self):
        def request(method, route):
            if route.endswith('/roles'):
                return [{'id': '1041923524601851914', 'permissions': '0', 'position': 0},
                        {'id': '700000000000000001', 'permissions': str(1 << 28), 'position': 5},
                        {'id': '700000000000000002', 'permissions': '0', 'position': 1, 'managed': False}]
            if '/members/' in route:
                return {'roles': ['700000000000000001']}
            return [{'id': '800000000000000001', 'permission_overwrites': [
                {'id': '700000000000000002', 'type': 0, 'allow': str(1 << 28), 'deny': '0'}]}]
        config = {'guild_id': 1041923524601851914, 'games': [
            {'role_ids': [700000000000000002], 'channel_ids': [800000000000000001]}]}
        with self.assertRaisesRegex(RuntimeError, 'unsafe'):
            self.ops.preflight_roles(config, request)

    def test_deploy_preflight_refuses_source_drift_or_existing_picker(self):
        deploy = importlib.import_module('ops.deploy_game_picker')
        base = Path(self.tmp.name)
        (base / 'content_bot.py').write_bytes(b'live')
        (base / 'content.config.json').write_text(json.dumps({'guild_id': 1}))
        digest = hashlib.sha256(b'live').hexdigest()
        deploy.verify_live(base, digest)
        (base / 'content_bot.py').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'drift'):
            deploy.verify_live(base, digest)
        (base / 'content_bot.py').write_bytes(b'live')
        (base / 'game_picker.py').write_text('existing')
        with self.assertRaisesRegex(RuntimeError, 'exists'):
            deploy.verify_live(base, digest)
