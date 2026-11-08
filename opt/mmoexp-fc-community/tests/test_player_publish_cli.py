import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import player_publish_cli as cli
from player_publish import EASYSBC_AUTHOR, TEST_CHANNEL, TEST_GUILD, OFFICIAL_GUILD


class RecordReceiptTests(unittest.TestCase):
    def setUp(self):
        self.started = datetime.now(timezone.utc)
        self.store = Mock()
        self.store.get.return_value = {'created_at': self.started.isoformat()}
        self.mid = '1569000000000000001'
        self.message_url = f'https://discord.com/channels/{TEST_GUILD}/{TEST_CHANNEL}/{self.mid}'
        self.player_url = 'https://www.easysbc.io/players/romelu-lukaku/rttk/50524153?player-role-id=44&utm_content=info'
        self.message = dict(id=self.mid, channel_id=str(TEST_CHANNEL),
            author={'id': str(EASYSBC_AUTHOR)}, timestamp=(self.started + timedelta(seconds=1)).isoformat())
        self.request = Mock(return_value=self.message)

    def record(self):
        return cli.record_receipt(self.store, 'batch', 45490779, self.message_url,
                                  self.player_url, 'Lukaku | 87 RTTK', request=self.request)

    def test_checks_rest_and_extracts_identity(self):
        self.record()
        self.request.assert_called_once_with('GET', f'/channels/{TEST_CHANNEL}/messages/{self.mid}')
        self.store.record.assert_called_once_with('batch', 45490779, self.message_url, dict(
            easysbc_id='50524153', easysbc_role_id='44', easysbc_url=self.player_url,
            autocomplete_label='Lukaku | 87 RTTK'), cli.OPERATOR, EASYSBC_AUTHOR)

    def test_wrong_author_channel_and_id_rejected(self):
        for field, value in [('author', {'id': '1237241595674361962'}),
                             ('channel_id', '111111111111111111'), ('id', '1569000000000000002')]:
            with self.subTest(field=field):
                original = self.message[field]
                self.message[field] = value
                with self.assertRaises(ValueError):
                    self.record()
                self.message[field] = original
        self.store.record.assert_not_called()

    def test_old_message_rejected(self):
        self.message['timestamp'] = (self.started - timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            self.record()
        self.store.record.assert_not_called()

    def test_wrong_destination_url_rejected_before_rest(self):
        self.message_url = self.message_url.replace(str(TEST_GUILD), '1041923524601851914')
        with self.assertRaises(ValueError):
            self.record()
        self.request.assert_not_called()

    def test_duplicate_role_query_rejected(self):
        self.player_url += '&player-role-id=45'
        with self.assertRaises(ValueError):
            self.record()
        self.store.record.assert_not_called()

    def test_official_receipt_uses_frozen_channel(self):
        channel = 1569999999999999999
        self.store.get.return_value.update(target='official', guild_id=OFFICIAL_GUILD, channel_id=channel)
        self.message_url = f'https://discord.com/channels/{OFFICIAL_GUILD}/{channel}/{self.mid}'
        self.message['channel_id'] = str(channel)
        self.record()
        self.request.assert_called_once_with('GET', f'/channels/{channel}/messages/{self.mid}')


class SendHomeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = dict(enabled=True, guild_id=TEST_GUILD, channel_id=TEST_CHANNEL)
        self.calls = []

    def config(self):
        (self.root / 'content.config.json').write_text(json.dumps({'player_panel': self.panel}), encoding='utf-8')

    def request(self, method, route, payload=None):
        self.calls.append((method, route, payload))
        if route == '/users/@me':
            return {'id': '1568239618111832094', 'bot': True}
        if route == f'/channels/{TEST_CHANNEL}':
            return {'guild_id': str(TEST_GUILD)}
        if method == 'POST' and route == f'/channels/{TEST_CHANNEL}/messages':
            return {'id': '1569000000000000002'}
        self.fail('Unexpected REST call')

    async def send(self, request=None):
        self.config()
        with patch.object(cli, 'ROOT', self.root), patch.object(cli, 'discord_request', request or self.request), \
             patch.object(cli, 'SocketProvider', return_value=Mock()):
            return await cli.send_home({'guild_id': TEST_GUILD, 'channel_id': TEST_CHANNEL})

    async def test_real_home_three_buttons_and_no_mentions(self):
        result = await self.send()
        self.assertEqual(result, f'https://discord.com/channels/{TEST_GUILD}/{TEST_CHANNEL}/1569000000000000002')
        posts = [c for c in self.calls if c[0] == 'POST']
        self.assertEqual(len(posts), 1)
        payload = posts[0][2]
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        buttons = [button for row in payload['components'] for button in row['components']]
        self.assertEqual([b['custom_id'] for b in buttons],
                         ['fc:players:search', 'fc:players:featured', 'fc:players:tags'])
        self.assertEqual(len(payload['embeds']), 1)

    async def test_disabled_config_rejected(self):
        for key, value in [('enabled', False)]:
            with self.subTest(key=key):
                original = self.panel[key]
                self.panel[key] = value
                with self.assertRaises(ValueError):
                    await self.send()
                self.panel[key] = original
        self.assertEqual(self.calls, [])

    async def test_test_send_stays_fixed_after_config_moves_official(self):
        self.panel.update(guild_id=OFFICIAL_GUILD, channel_id=1568878333087719454)
        result = await self.send()
        self.assertIn(f'/channels/{TEST_GUILD}/{TEST_CHANNEL}/', result)
        self.assertEqual([c[1] for c in self.calls if c[0] == 'POST'], [f'/channels/{TEST_CHANNEL}/messages'])

    async def test_wrong_bot_rejected_without_post(self):
        request = Mock(return_value={'id': '111111111111111111', 'bot': True})
        with self.assertRaises(ValueError):
            await self.send(request)
        self.assertEqual(request.call_count, 1)

    async def test_wrong_channel_guild_rejected_without_post(self):
        request = Mock(side_effect=[{'id': '1568239618111832094', 'bot': True}, {'guild_id': '1041923524601851914'}])
        with self.assertRaises(ValueError):
            await self.send(request)
        self.assertEqual(request.call_count, 2)

    async def test_official_send_uses_snapshot_and_checks_live_route(self):
        channel = 1569999999999999999
        batch = {'target': 'official', 'guild_id': OFFICIAL_GUILD, 'channel_id': channel}
        self.panel.update(guild_id=OFFICIAL_GUILD, channel_id=channel)
        self.config()
        request = Mock(side_effect=[{'id': '1568239618111832094', 'bot': True},
            {'guild_id': str(OFFICIAL_GUILD)}, {'id': '1569000000000000002'}])
        with patch.object(cli, 'ROOT', self.root), patch.object(cli, 'discord_request', request), \
             patch.object(cli, 'SocketProvider', return_value=Mock()):
            result = await cli.send_home(batch)
        self.assertEqual(result, f'https://discord.com/channels/{OFFICIAL_GUILD}/{channel}/1569000000000000002')
        self.assertEqual(request.call_args.args[:2], ('POST', f'/channels/{channel}/messages'))
        self.panel['channel_id'] = channel - 1
        self.config()
        with patch.object(cli, 'ROOT', self.root), patch.object(cli, 'discord_request', Mock()) as rest:
            with self.assertRaises(ValueError):
                await cli.send_home(batch)
            rest.assert_not_called()


class PlanCliTests(unittest.TestCase):
    def test_test_create_works_after_config_moves_official(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = dict(enabled=True, guild_id=OFFICIAL_GUILD, channel_id=1568878333087719454,
                          featured_model_ids=[42], allowed_tag_ids=[], verified_prices={})
            (root / 'content.config.json').write_text(json.dumps({'player_panel': config}), encoding='utf-8')
            provider = Mock()
            provider.player_manage_selection.return_value = [{'model_id': 42, 'title': 'Player', 'model_available': True}]
            provider.player_manage_match.return_value = {'status': 'unavailable', 'candidates': []}
            import uuid
            output = io.StringIO()
            with patch.object(cli, 'ROOT', root), patch.object(cli, 'SocketProvider', return_value=provider), \
                 patch.object(cli, 'discord_request', return_value={'guild_id': str(TEST_GUILD)}) as request, \
                 patch('sys.argv', ['player_publish_cli.py', 'create', '--request-id', str(uuid.uuid4())]), \
                 contextlib.redirect_stdout(output):
                cli.main()
            result = json.loads(output.getvalue())
            self.assertEqual((result['guild_id'], result['channel_id']), (TEST_GUILD, TEST_CHANNEL))
            request.assert_called_once_with('GET', f'/channels/{TEST_CHANNEL}')

    def test_plan_does_not_create_state_or_send_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = dict(enabled=True, guild_id=OFFICIAL_GUILD, channel_id=1569999999999999999,
                          featured_model_ids=[42], allowed_tag_ids=[], verified_prices={})
            (root / 'content.config.json').write_text(json.dumps({'player_panel': config}), encoding='utf-8')
            provider = Mock()
            provider.player_manage_selection.return_value = [{'model_id': 42, 'title': 'Player / 90 / ST / Gold', 'model_available': True}]
            provider.player_manage_match.return_value = {'status': 'unavailable', 'candidates': []}
            output = io.StringIO()
            with patch.object(cli, 'ROOT', root), patch.object(cli, 'SocketProvider', return_value=provider), \
                 patch.object(cli, 'discord_request') as request, \
                 patch('sys.argv', ['player_publish_cli.py', 'plan', '--target', 'official']), \
                 contextlib.redirect_stdout(output):
                cli.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result['target'], 'official')
            self.assertEqual(result['items'][0]['model_id'], 42)
            self.assertFalse((root / 'var').exists())
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
