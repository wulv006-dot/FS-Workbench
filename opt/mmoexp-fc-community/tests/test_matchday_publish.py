import tempfile
import unittest

from matchday_publish import publish


class MatchdayPublishTests(unittest.TestCase):
    def test_creates_then_edits_same_card_only_after_change(self):
        snapshot = {'schema_version': 1, 'checked_at_utc': '2026-11-14T14:00:00+00:00',
                    'sources': {'openligadb': {}, 'espn': {}}}
        calls = []

        def sender(method, path, card, token):
            calls.append((method, path))
            return {'id': '1234567890123456789'}

        with tempfile.TemporaryDirectory() as folder:
            first = publish('test', snapshot, 'unused', sender, folder)
            second = publish('test', snapshot, 'unused', sender, folder)
            changed = dict(snapshot, checked_at_utc='2026-11-14T15:00:00+00:00')
            third = publish('test', changed, 'unused', sender, folder)
        self.assertEqual([first['result'], second['result'], third['result']],
                         ['created', 'unchanged', 'edited'])
        self.assertEqual([method for method, _ in calls], ['POST', 'PATCH'])


if __name__ == '__main__':
    unittest.main()
