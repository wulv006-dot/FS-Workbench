from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'ui-system/modules/game-monitor/backend'),
 str(ROOT / 'releases/fs-dashboard/news-weekly-schedule-20261016/source'),
 str(ROOT / 'releases/fs-dashboard/fs-revision-20261015/ai/candidate')]
import discovery

AT = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
TEXT = 'Path of Exile 2 update announced for November 7, 2026. The official livestream will explain the new systems and trading changes. This announcement is not a launch date.'
URL = 'https://www.pathofexile.com/forum/view-thread/123'


class Source:
    def __init__(self, url=URL, text=TEXT, fail=False):
        self.url, self.text, self.fail, self.calls = url, text, fail, []
    def search(self, query):
        self.calls.append(('search', query))
        if self.fail:
            raise discovery.SourceError('search_http_402')
        return {'results': [{'url': self.url, 'title': 'Path of Exile 2 official update', 'date': '2026-11-05T00:00:00Z'}]}
    def fetch(self, url):
        self.calls.append(('fetch', url))
        return {'title': 'Announcements - Path of Exile 2 official update', 'content': self.text}


class DiscoveryTests(unittest.TestCase):
    def test_unknown_game_never_calls_paid_api(self):
        source = Source()
        with self.assertRaisesRegex(ValueError, 'unregistered_game'):
            discovery.collect(['invented-game'], source, AT)
        self.assertEqual(source.calls, [])

    def test_private_and_credential_urls_rejected_before_fetch(self):
        for url in ['https://127.0.0.1/x', 'https://localhost/x', 'https://user:pass@www.pathofexile.com/x', 'http://www.pathofexile.com/x']:
            with self.subTest(url=url):
                source = Source(url)
                result = discovery.collect(['poe2'], source, AT)
                self.assertEqual(result['documents'], [])
                self.assertEqual(len(source.calls), 1)

    def test_unregistered_domain_cannot_pose_as_official(self):
        source = Source('https://www.pathofexile.com.attacker.example/patch')
        result = discovery.collect(['poe2'], source, AT)
        self.assertEqual(result['documents'], [])
        self.assertEqual(len(source.calls), 1)

    def test_full_original_content_becomes_hashed_document(self):
        result = discovery.collect(['poe2'], Source(), AT)
        self.assertEqual(len(result['documents']), 1)
        doc = result['documents'][0]
        self.assertEqual(doc['game_keys'], ['poe1','poe2'])
        self.assertIn(TEXT, doc['text'])
        self.assertEqual(doc['source_url'], URL)
        self.assertEqual(result['collected_at'], '2026-11-05T08:00:00+00:00')
        self.assertEqual(len(doc['sha256']), 64)

    def test_sequel_is_not_assigned_to_base_game(self):
        result = discovery.collect(['poe1'], Source(), AT)
        self.assertEqual(result['documents'], [])

    def test_search_snippet_never_substitutes_failed_fetch(self):
        source = Source()
        def fail(url):
            raise discovery.SourceError('fetch_http_404')
        source.fetch = fail
        result = discovery.collect(['poe2'], source, AT)
        self.assertEqual(result['documents'], [])
        self.assertEqual(result['source_status'][0]['status'], 'failed')

    def test_partial_game_failure_does_not_erase_success(self):
        source = Source()
        original = source.search
        source.search = lambda query: original(query) if 'Path of Exile 2' in query else (_ for _ in ()).throw(discovery.SourceError('search_http_402'))
        result = discovery.collect(['poe2', 'runescape'], source, AT)
        self.assertEqual(len(result['documents']), 1)
        self.assertTrue(result['coverage']['partial'])
        self.assertEqual(result['coverage']['missing_games'], ['runescape'])

    def test_empty_search_is_reported_as_no_matches(self):
        source = Source()
        source.search = lambda query: {'results': []}
        result = discovery.collect(['poe2'], source, AT)
        self.assertEqual(result['source_status'][0]['reason'], 'no_search_matches')

    def test_failed_collection_preserves_published_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = b'{"version":"previous","events":[{"title":"preserve"}]}'
            (root / 'intelligence.json').write_bytes(old)
            result = discovery.run_once(root, ['poe2'], Source(fail=True), lambda messages: self.fail('model should not run'), AT)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual((root / 'intelligence.json').read_bytes(), old)
            self.assertEqual(json.loads((root / 'intelligence.status.json').read_text())['reason'], 'no_verified_documents')

    def test_model_error_preserves_published_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'intelligence.json').write_bytes(b'{"events":[]}')
            def fail(messages):
                raise discovery.SourceError('model_http_429')
            result = discovery.run_once(root, ['poe2'], Source(), fail, AT)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual((root / 'intelligence.json').read_bytes(), b'{"events":[]}')

    def test_successful_grounded_events_publish_with_receipt_and_ttl(self):
        def model(messages):
            batch = json.loads(messages[1]['content'])
            doc = batch['documents'][0]
            event = dict(game_key='poe2', game_name='Path of Exile 2', source_id=doc['source_id'],
                document_id=doc['document_id'], title='POE2 更新情报', kind='update', summary='官方预告更新情报。',
                evidence=TEXT, event_date='2026-11-07', date_evidence='November 7, 2026',
                event_time=None, time_evidence=None, timezone=None, timezone_evidence=None)
            return dict(id='test-receipt-123', model='deepseek-flash',
                choices=[dict(finish_reason='stop', message=dict(content=json.dumps({'events':[event]})))],
                usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            result=discovery.run_once(root,['poe2'],Source(),model,AT)
            self.assertEqual(result['status'],'succeeded')
            published=json.loads((root/'intelligence.json').read_bytes())
            self.assertEqual(published['events'][0]['event_date'],'2026-11-07')
            self.assertEqual(published['receipt'],'test-receipt-123')
            self.assertEqual(published['stale_after'],'2026-11-05T12:00:00+00:00')

    def test_no_game_query_exceeds_provider_contract(self):
        source=Source()
        def search(query):
            self.assertLessEqual(len(query),128)
            return {'results':[]}
        source.search=search
        result=discovery.collect(list(discovery.official.GAMES),source,AT)
        self.assertEqual(len(result['source_status']),29)

    def test_official_domain_player_post_is_not_an_announcement(self):
        source=Source()
        source.fetch=lambda url:{'title':'General Discussion - Next league - Forum - Path of Exile','content':TEXT}
        result=discovery.collect(['poe2'],source,AT)
        self.assertEqual(result['documents'],[])
        self.assertEqual(result['source_status'][0]['candidate_checks'][0]['reason'],'community_forum_not_official_announcement')

    def test_bound_steam_announcement_does_not_require_game_name_in_each_body(self):
        source=Source('https://steamcommunity.com/games/2694490/announcements/detail/123',text='The developer announces the next major update and explains its systems. '+('Official update details. '*8))
        result=discovery.collect(['poe2'],source,AT)
        self.assertEqual(len(result['documents']),1)
        self.assertEqual(result['documents'][0]['game_keys'],['poe2'])

    def test_search_gap_uses_existing_reader_and_keeps_search_gap_visible(self):
        source=Source()
        source.search=lambda query:{'results':[]}
        spec=next(s for s in discovery.official.SOURCES if s['kind']=='steam' and s['games']==['poe2'])
        doc=discovery.official.document(spec,spec['url'],'Official announcement',TEXT)
        source.direct=lambda source_spec:[doc]
        result=discovery.collect(['poe2'],source,AT)
        self.assertEqual(len(result['documents']),1)
        self.assertEqual(result['source_status'][0]['method'],'existing_official_reader')
        self.assertEqual(result['source_status'][0]['search_reason'],'no_search_matches')

    def test_raven_player_board_is_not_official_news(self):
        source=Source('https://forum.netmarble.com/raven2_gb/view/19/2714',text='RAVEN2 player discussion. '+('A player predicts a new server launch. '*8))
        result=discovery.collect(['raven-2'],source,AT)
        self.assertEqual(result['documents'],[])
        self.assertEqual(result['source_status'][0]['candidate_checks'][0]['reason'],'community_board_not_official_announcement')


if __name__ == '__main__':
    unittest.main()
