import copy
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'candidate'))
import workspace_official_model as official
import game_intelligence as intelligence
import management_daily as management


class OfficialWorkspaceTests(unittest.TestCase):
    def test_catalog_restart_recovers_without_model_retry(self):
        now = [0]
        replies = iter([{'http_status': 503}, {'http_status': 200, 'body': {'ok': True}}])
        result = management.read_catalog(lambda path: next(replies), 420,
                    monotonic=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n))
        self.assertEqual(result['http_status'], 200)
        self.assertEqual(now[0], 5)

    def test_catalog_timeout_is_bounded_and_access_denial_not_retried(self):
        now = [0]
        calls = []
        def unavailable(path):
            calls.append(1)
            raise ConnectionError('service restarting')
        with self.assertRaisesRegex(ValueError, 'catalog_unavailable'):
            management.read_catalog(unavailable, 420, monotonic=lambda: now[0],
                 sleep=lambda n: now.__setitem__(0, now[0] + n))
        self.assertEqual(len(calls), 6)
        self.assertEqual(management.read_catalog(lambda path: {'http_status': 403}, 420)['http_status'], 403)

    def test_existing_provider_high_and_no_tools_or_private_reasoning(self):
        seen = []
        def send(request, tools, deadline=None):
            seen.append((request, tools, deadline))
            return {'model': official.MODEL, 'choices': [{'message': {'content': '{}', 'reasoning_content': 'private'}}], 'usage': {'total_tokens': 9}}
        provider = types.SimpleNamespace(OUTPUT_TOKENS=393216, request_model=send)
        with patch.object(official, 'runtime', return_value=(provider, [{'type': 'function'}])):
            out = official.request_model([], {}, lambda raw, facts: raw)
        self.assertEqual(seen[0][0]['tools'], [])
        self.assertEqual(seen[0][0]['reasoning_effort'], 'high')
        self.assertEqual(seen[0][0]['model'], 'deepseek-flash')
        self.assertIsNotNone(seen[0][2])
        self.assertNotIn('reasoning_content', out['choices'][0]['message'])
        self.assertEqual(out['usage']['total_tokens'], 9)

    def test_unknown_is_not_retried(self):
        calls = []
        def send(*args, **kwargs):
            calls.append(1)
            return {'status': 'unknown_transport'}
        provider = types.SimpleNamespace(OUTPUT_TOKENS=393216, request_model=send)
        with patch.object(official, 'runtime', return_value=(provider, ['registered'])):
            self.assertEqual(official.request_model([], {}, None)['status'], 'unknown_transport')
        self.assertEqual(len(calls), 1)

    def test_bad_deadline_does_not_load_provider(self):
        with patch.object(official, 'runtime', side_effect=AssertionError('loaded')):
            for value in (0, -1, True, 1801, '120'):
                self.assertEqual(official.request_model([], {}, None, timeout=value)['status'], 'configuration_invalid')

    def test_japan_and_korea_event_offsets(self):
        for abbreviation in ('JST', 'KST'):
            quote = 'Diablo IV Season begins October 20, 2026 at 07:00 '+abbreviation+'. Official season announcement.'
            spec = intelligence.source('official', 'https://news.blizzard.com/example', 'html', ['diablo4'])
            doc = intelligence.document(spec, spec['url'], 'Diablo IV', quote, '2026-10-12T01:00:00Z')
            batch = {'collected_at': '2026-10-15T01:00:00Z', 'documents': [doc]}
            event = dict(game_key='diablo4', game_name='Diablo IV', source_id=doc['source_id'], document_id=doc['document_id'], title='新赛季', kind='season', summary='官方赛季时间。', evidence=quote, event_date='2026-10-20', date_evidence='October 20, 2026', event_time='07:00', time_evidence='07:00', timezone='UTC+09:00', timezone_evidence=abbreviation)
            self.assertEqual(intelligence.validate_event(event, batch, {doc['document_id']: doc})['timezone'], 'UTC+09:00')
            event['timezone'] = 'UTC+00:05'
            with self.assertRaisesRegex(ValueError, 'unsupported_timezone'):
                intelligence.validate_event(event, batch, {doc['document_id']: doc})


if __name__ == '__main__':
    unittest.main()
