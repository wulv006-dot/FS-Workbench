import importlib.util
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.client import HTTPConnection
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEMP = tempfile.TemporaryDirectory()
os.environ['BOTCONSOLE_DATA'] = str(Path(TEMP.name) / 'data')
spec = importlib.util.spec_from_file_location('console_candidate', ROOT / 'server.py')
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


class FCConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = console.ThreadingHTTPServer(('127.0.0.1', 0), console.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        TEMP.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'config.json'
        self.config = {'guild_id': 1565922092518613064, 'staff_user_ids': ['123456789012345678'],
                       'database': 'var/community.sqlite3', 'quote_socket': '/run/example.sock',
                       'quote_relay': {'guild_id': 1041923524601851914,
                                       'channels': {'1301379787696377926': 'sbc'}}}
        self.path.write_text(json.dumps(self.config), encoding='utf-8')
        console.FC_CONFIG = self.path
        console.FC_STATIC_MARKER = Path(self.tmp.name) / 'quote-static-panel.json'
        repository_source = ROOT.parent / 'mmoexp-fc-community' / 'news_feed.py'
        console.FC_NEWS_CODE = (repository_source if repository_source.is_file() else
                                ROOT.parent.parent / 'mmoexp-fc-pilot' / 'news_feed.py')
        console.FC_NEWS_DB = Path(self.tmp.name) / 'news.sqlite3'
        self.original_run = console._run
        console._run = lambda *args, **kwargs: (0, 'ActiveState=active\nSubState=running\nMainPID=42\n', '')
        self.addCleanup(setattr, console, '_run', self.original_run)

    def request(self, method, path, data=None, user='operator', role='admin', csrf=True):
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'X-Auth-User': user, 'X-Auth-Role': role}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
            if csrf:
                headers['X-Requested-With'] = 'XMLHttpRequest'
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = json.loads(response.read())
        status = response.status
        conn.close()
        return status, result

    def test_routes_save_and_disable_without_overwriting_unrelated_config(self):
        status, before = self.request('GET', '/api/fc/config')
        self.assertEqual(status, 200)
        self.assertEqual(before['routes']['sbc'], '1301379787696377926')
        routes = dict(before['routes'], sbc='', packs='1568610700463710278',
                      coins='1501757710381748254')
        status, saved = self.request('POST', '/api/fc/config', {'routes': routes, 'revision': before['revision']})
        self.assertEqual(status, 200)
        current = json.loads(self.path.read_text())
        self.assertEqual(current['quote_relay']['channels'], {'1568610700463710278': 'packs'})
        self.assertEqual(current['quote_static']['channels'], {'1501757710381748254': 'coins'})
        for key in ('guild_id', 'staff_user_ids', 'database', 'quote_socket'):
            self.assertEqual(current[key], self.config[key])
        self.assertTrue((console.CFG['data_dir'] / 'backups' / saved['backup']).is_file())

    def test_rejects_unauthorized_invalid_and_stale_updates(self):
        _, before = self.request('GET', '/api/fc/config')
        body = {'routes': before['routes'], 'revision': before['revision']}
        self.assertEqual(self.request('POST', '/api/fc/config', body, role='readonly')[0], 403)
        self.assertEqual(self.request('POST', '/api/fc/config', body, csrf=False)[0], 403)
        self.assertEqual(self.request('GET', '/api/fc/config', user='')[0], 401)
        bad = dict(body, routes=dict(before['routes'], packs='not-a-channel'))
        self.assertEqual(self.request('POST', '/api/fc/config', bad)[0], 400)
        bad = dict(body, routes=dict(before['routes'], packs=before['routes']['sbc']))
        self.assertEqual(self.request('POST', '/api/fc/config', bad)[0], 400)
        self.path.write_text(json.dumps(dict(self.config, unrelated='changed')))
        self.assertEqual(self.request('POST', '/api/fc/config', body)[0], 409)
        self.assertEqual(json.loads(self.path.read_text())['unrelated'], 'changed')

    def test_disabled_all_removes_both_route_blocks(self):
        _, before = self.request('GET', '/api/fc/config')
        routes = {kind: '' for kind in before['routes']}
        self.assertEqual(self.request('POST', '/api/fc/config',
                                      {'routes': routes, 'revision': before['revision']})[0], 200)
        current = json.loads(self.path.read_text())
        self.assertNotIn('quote_relay', current)
        self.assertNotIn('quote_static', current)

    def test_logs_are_admin_only_and_never_return_unrecognized_text(self):
        console._run = lambda *args, **kwargs: (0, '\n'.join([
            'Quote relay sent: 1568610700463710278', 'Quote relay send failed: OSError',
            'News collection failed: HTTPError', 'News publication failed: TimeoutError',
            'Club panels need manual reconciliation.', 'Club panel setup failed: Forbidden',
            'News collection failed: HTTPError https://private.example/token',
            'Authorization: Bot synthetic-secret', 'mail: private@example.com']), '')
        self.assertEqual(self.request('GET', '/api/fc/logs', role='readonly')[0], 403)
        status, data = self.request('GET', '/api/fc/logs')
        self.assertEqual(status, 200)
        self.assertIn('Quote relay sent:', data['text'])
        self.assertIn('Quote relay send failed: OSError', data['text'])
        self.assertIn('News collection failed: HTTPError', data['text'])
        self.assertIn('News publication failed: TimeoutError', data['text'])
        self.assertIn('Club panels need manual reconciliation.', data['text'])
        self.assertNotIn('private.example', data['text'])
        self.assertNotIn('synthetic-secret', data['text'])
        self.assertNotIn('private@example.com', data['text'])

    def test_restart_failure_is_reported_after_config_is_saved(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[:2] == ['systemctl', 'restart']:
                return 1, '', 'failure'
            return 0, 'ActiveState=failed\n', ''
        console._run = run
        _, before = self.request('GET', '/api/fc/config')
        routes = dict(before['routes'], packs='1568610700463710278')
        status, data = self.request('POST', '/api/fc/config',
                                    {'routes': routes, 'revision': before['revision'], 'restart': True})
        self.assertEqual(status, 200)
        self.assertIs(data['restarted'], False)
        self.assertIn(['systemctl', 'restart', 'mmoexp-fc-community'], calls)
        self.assertEqual(json.loads(self.path.read_text())['quote_relay']['channels']
                         ['1568610700463710278'], 'packs')

    def test_audit_failure_prevents_config_write(self):
        _, before = self.request('GET', '/api/fc/config')
        original = console.AUDIT_LOG
        console.AUDIT_LOG = Path(self.tmp.name) / 'missing' / 'audit.log'
        self.addCleanup(setattr, console, 'AUDIT_LOG', original)
        routes = dict(before['routes'], packs='1568610700463710278')
        status, _ = self.request('POST', '/api/fc/config', {'routes': routes, 'revision': before['revision']})
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(self.path.read_text()), self.config)

    def test_independent_page_is_served(self):
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request('GET', '/fc27.html')
        response = conn.getresponse()
        html = response.read().decode('utf-8')
        self.assertEqual(response.status, 200)
        self.assertIn('FC27 控制台', html)
        self.assertIn('精选 Player', html)
        conn.close()

    def test_static_channel_change_requires_existing_panel_reconciliation(self):
        console.FC_STATIC_MARKER.write_text(json.dumps({'guild_id': 1041923524601851914,
            'channel_id': 1501757710381748254, 'message_id': 1568645119320522927}))
        _, before = self.request('GET', '/api/fc/config')
        routes = dict(before['routes'], coins='1568610224502345758')
        status, _ = self.request('POST', '/api/fc/config', {'routes': routes, 'revision': before['revision']})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(self.path.read_text()), self.config)

    def test_robot_management_has_separate_fc_link_and_keeps_existing_card(self):
        html = (ROOT / 'dashboard/modules/bots/index.html').read_text(encoding='utf-8')
        self.assertEqual(html.count('data-tool="bot-console"'), 1)
        self.assertEqual(html.count('data-tool="fc27-console"'), 1)
        self.assertIn('href="/bots/fc27.html" data-tool="fc27-console"', html)
        self.assertIn('href="/bots/" data-tool="bot-console"', html)

    def test_news_config_preserves_other_fields_and_enforces_revision_admin_csrf(self):
        _, before = self.request('GET', '/api/fc/news/config')
        self.assertIsNone(before['news_publish'])
        news = {'guild_id': console.FC_GUILD, 'channel_id': '123456789012345678',
                'enabled': True, 'poll_seconds': 900}
        body = {'news_publish': news, 'revision': before['revision'], 'restart': False}
        self.assertEqual(self.request('POST', '/api/fc/news/config', body, role='readonly')[0], 403)
        self.assertEqual(self.request('POST', '/api/fc/news/config', body, csrf=False)[0], 403)
        self.assertEqual(self.request('POST', '/api/fc/news/config', dict(body, news_publish=dict(news, poll_seconds=1)))[0], 400)
        status, result = self.request('POST', '/api/fc/news/config', body)
        self.assertEqual(status, 200)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved.pop('news_publish'), news)
        self.assertEqual(saved, self.config)
        self.assertTrue((console.CFG['data_dir'] / 'backups' / result['backup']).is_file())
        self.assertEqual(self.request('POST', '/api/fc/news/config', body)[0], 409)

    def test_news_x_submissions_are_independent_and_reads_do_not_recover_sends(self):
        module = console.fc_news_module()
        store = module.NewsStore(console.FC_NEWS_DB)
        self.config['news_publish'] = {'guild_id': console.FC_GUILD, 'channel_id': '123456789012345678',
                                     'enabled': True, 'poll_seconds': 900}
        self.path.write_text(json.dumps(self.config), encoding='utf-8')
        _, cfg = self.request('GET', '/api/fc/news/config')
        body = {'url': 'https://twitter.com/FutSheriff/status/123?s=20', 'summary': '@everyone selected', 'revision': cfg['revision']}
        self.assertEqual(self.request('POST', '/api/fc/news/x', body, role='readonly')[0], 403)
        self.assertEqual(self.request('POST', '/api/fc/news/x', body, csrf=False)[0], 403)
        self.assertEqual(self.request('POST', '/api/fc/news/x', dict(body, url='https://127.0.0.1/private'))[0], 400)
        status, item = self.request('POST', '/api/fc/news/x', body)
        self.assertEqual(status, 200)
        self.assertEqual(item['url'], 'https://x.com/FutSheriff/status/123')
        repeated = self.request('POST', '/api/fc/news/x', body)[1]
        self.assertNotEqual(repeated['id'], item['id'])
        store.claim('123456789012345678')
        _, items = self.request('GET', '/api/fc/news/items', role='readonly')
        self.assertEqual(len(items['manual']), 2)
        first = next(row for row in items['manual'] if row['id'] == item['id'])
        self.assertEqual(first['status'], 'sending')
        self.assertNotIn('actor', first)
        third = self.request('POST', '/api/fc/news/x', body)[1]
        self.assertNotIn(third['id'], (item['id'], repeated['id']))
        self.assertEqual(third['status'], 'pending')

    def test_news_enqueue_requires_enabled_config_and_bot_initialized_database(self):
        _, cfg = self.request('GET', '/api/fc/news/config')
        body = {'url': 'https://x.com/test/status/123', 'summary': '', 'revision': cfg['revision']}
        self.assertEqual(self.request('POST', '/api/fc/news/x', body)[0], 400)
        self.config['news_publish'] = {'guild_id': console.FC_GUILD, 'channel_id': '123456789012345678',
                                     'enabled': True, 'poll_seconds': 900}
        self.path.write_text(json.dumps(self.config), encoding='utf-8')
        _, cfg = self.request('GET', '/api/fc/news/config')
        self.assertEqual(self.request('POST', '/api/fc/news/x', dict(body, revision=cfg['revision']))[0], 409)
        self.assertFalse(console.FC_NEWS_DB.exists())

    def test_news_collector_config_roundtrip_preserves_six_hours_and_unrelated_fields(self):
        _, before = self.request('GET', '/api/fc/news/config')
        for collector in ('187', '183', 'auto'):
            news = {'guild_id': console.FC_GUILD, 'channel_id': '123456789012345678',
                    'enabled': True, 'poll_seconds': 21600, 'collector': collector}
            body = {'news_publish': news, 'revision': before['revision'], 'restart': False}
            status, _ = self.request('POST', '/api/fc/news/config', body)
            self.assertEqual(status, 200)
            _, before = self.request('GET', '/api/fc/news/config')
            self.assertEqual(before['news_publish'], news)
        current = json.loads(self.path.read_text())
        self.assertEqual(current['quote_relay'], self.config['quote_relay'])
        self.assertEqual(current['staff_user_ids'], self.config['staff_user_ids'])
        bad = dict(body, revision=before['revision'], news_publish=dict(news, collector='other-host'))
        self.assertEqual(self.request('POST', '/api/fc/news/config', bad)[0], 400)
        current['news_publish'].pop('collector')
        self.path.write_text(json.dumps(current))
        self.assertEqual(self.request('GET', '/api/fc/news/config')[1]['news_publish']['collector'], '187')

    def test_article_manual_repeats_when_automatic_disabled_and_keeps_actor(self):
        module = console.fc_news_module()
        store = module.NewsStore(console.FC_NEWS_DB)
        self.config['news_publish'] = {'guild_id': console.FC_GUILD, 'channel_id': '123456789012345678',
                                     'enabled': False, 'poll_seconds': 21600, 'collector': '187'}
        self.path.write_text(json.dumps(self.config))
        _, cfg = self.request('GET', '/api/fc/news/config')
        body = {'url': 'https://www.mmoexp.com/News/fc-27-test-article.html', 'title': 'Test news',
                'summary': 'A short manual summary', 'revision': cfg['revision']}
        self.assertEqual(self.request('POST', '/api/fc/news/article', body, role='readonly')[0], 403)
        self.assertEqual(self.request('POST', '/api/fc/news/article', body, csrf=False)[0], 403)
        self.assertEqual(self.request('POST', '/api/fc/news/article', dict(body, revision='0'*64))[0], 409)
        self.assertEqual(self.request('POST', '/api/fc/news/article', dict(body, url='https://127.0.0.1/private'))[0], 400)
        with patch('urllib.request.urlopen', side_effect=AssertionError('Manual entry must not fetch arbitrary URLs')):
            first_status, first = self.request('POST', '/api/fc/news/article', body)
            second_status, second = self.request('POST', '/api/fc/news/article', body)
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(len(store.items()), 2)
        self.assertTrue(all(item['actor'] == 'operator' for item in store.items()))
        x = {'url': 'https://x.com/test/status/123', 'summary': '', 'revision': cfg['revision']}
        self.assertEqual(self.request('POST', '/api/fc/news/x', x)[0], 200)

    def test_news_record_groups_are_bounded_hide_baseline_and_report_source_failure(self):
        module = console.fc_news_module()
        store = module.NewsStore(console.FC_NEWS_DB)
        with store.db() as db, db:
            for index in range(12):
                status = 'baseline' if index == 11 else 'published' if index < 8 else 'pending'
                db.execute('INSERT INTO news_items(external_id,kind,title,summary,url,cover_url,source,published_date,published_at,created_at,actor,status,delivery_mode,last_seen_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('auto:%s'%index, 'ea' if index%2 else 'mmoexp', 'Auto %s'%index, 'Summary',
                     'https://www.mmoexp.com/News/fc-27-test-%s.html'%index, '', 'Official source',
                     'Nov 8, 2026', 100+index, 200+index, 'official-source', status, 'auto', 300+index, 400+index))
            for index in range(9):
                cur = db.execute('INSERT INTO news_items(external_id,kind,title,summary,url,cover_url,source,published_date,created_at,actor,status,delivery_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('manual:%s'%index, 'x', 'Manual %s'%index, '', 'https://x.com/test/status/123', '', 'X', '',
                     500+index, 'operator', 'pending', 'manual'))
                if index < 7:
                    db.execute("UPDATE news_items SET status='published',completed_at=? WHERE id=?", (1000+index, cur.lastrowid))
                elif index == 8:
                    db.execute("UPDATE news_items SET status='uncertain',completed_at=?,error_code='TimeoutError' WHERE id=?", (1000+index, cur.lastrowid))
            meta = {'last_attempt_at': '2000', 'last_poll_at': '1900', 'last_poll_error': 'all_sources_failed',
                    'collector_status': json.dumps({'ea': {'ok': False, 'error': 'source_unavailable', 'checked_at': 2000,
                        'attempts': [{'collector': '183', 'ok': False, 'error': 'remote_unavailable', 'elapsed_ms': 10}],
                        'raw_token': 'synthetic-private-secret'}})}
            for key, value in meta.items():
                db.execute('INSERT OR REPLACE INTO news_meta(key,value) VALUES(?,?)', (key, value))
        status, data = self.request('GET', '/api/fc/news/items', role='readonly')
        self.assertEqual(status, 200)
        self.assertEqual(len(data['collected']), 6)
        self.assertTrue(all(row['kind'] in ('ea', 'mmoexp') for row in data['collected']))
        self.assertEqual([row['title'] for row in data['collected']], ['Auto %s'%index for index in (10,9,8,7,6,5)])
        self.assertEqual(len(data['published']), 6)
        self.assertEqual([row['completed_at'] for row in data['published']], list(range(1006,1000,-1)))
        self.assertEqual(len(data['manual']), 6)
        self.assertEqual(data['pending'][0]['title'], 'Manual 7')
        self.assertEqual([row['title'] for row in data['pending'][1:]], ['Auto 9', 'Auto 10', 'Auto 8'])
        self.assertEqual(data['collected'][0]['last_seen_at'], 310)
        self.assertEqual(data['failed'][0]['status'], 'uncertain')
        self.assertFalse(any(row['status'] == 'baseline' for key in ('collected','pending','published','failed','manual') for row in data[key]))
        self.assertEqual(data['collection']['last_attempt_at'], 2000)
        self.assertEqual(data['collection']['last_success_at'], 1900)
        self.assertEqual(data['collection']['last_error_code'], 'all_sources_failed')
        self.assertEqual(data['collection']['sources']['ea']['attempts'][0]['collector'], '183')
        self.assertNotIn('synthetic-private-secret', json.dumps(data))
        self.assertNotIn('actor', data['collected'][0])

    def test_news_center_has_separate_tabs_hour_controls_and_manual_repeat_copy(self):
        html = (ROOT / 'static/fc27.html').read_text(encoding='utf-8')
        for text in ('新闻中心', '采集设置', '新闻记录', '手动发布', '最近采集 6 条', '最近发布 6 条', '每轮最多发布 6 条',
                     '同一链接可重复', 'id="news-hours"', 'value="183"', 'value="auto"', 'id="player-panel"'):
            self.assertIn(text, html)
        self.assertNotIn('检查间隔（秒', html)
        self.assertNotIn('历史基线', html)
        self.assertNotIn('北京时间', html)
        self.assertNotIn("timeZone:'Asia/Shanghai'", html)
