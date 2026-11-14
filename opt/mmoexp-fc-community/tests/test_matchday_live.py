import datetime
import json
import os
import tempfile
import unittest

from matchday_live import collect_live


class MatchdayLiveTests(unittest.TestCase):
    def _state(self, root):
        folder = os.path.join(root, 'snapshots')
        os.mkdir(folder)
        fixture = {'fixture_id': '86635', 'group_order': 11,
                   'kickoff_utc': '2026-11-21T12:30:00+00:00', 'score': None}
        payload = {'season': 2026, 'sources': {'openligadb': {'pl': [fixture]}}}
        with open(os.path.join(folder, 'base.json'), 'w', encoding='utf-8') as out:
            json.dump(payload, out)
        with open(os.path.join(root, 'focus.json'), 'w', encoding='utf-8') as out:
            json.dump({'fixtures': [{'league': 'pl', 'openliga_id': '86635',
                                     'espn_id': '401879233'}]}, out)

    def test_idle_skips_network_and_live_poll_uses_exact_ids(self):
        with tempfile.TemporaryDirectory() as root:
            self._state(root)
            calls = []

            def primary(league, season, group, marker):
                calls.append(('primary', league, group))
                return 'changed', [{'fixture_id': '86635', 'score': [1, 0]}]

            def backup(league, day):
                calls.append(('backup', league, day))
                return [{'fixture_id': '401879233', 'score': [1, 0]}]

            idle = collect_live(root, datetime.datetime(2026, 11, 14, tzinfo=datetime.timezone.utc),
                                primary, backup)
            self.assertEqual(idle['fixtures'], [])
            self.assertEqual(calls, [])
            live = collect_live(root, datetime.datetime(2026, 11, 21, 13, tzinfo=datetime.timezone.utc),
                                primary, backup)
            self.assertEqual(live['fixtures'][0]['openligadb']['score'], [1, 0])
            self.assertEqual(live['fixtures'][0]['espn']['fixture_id'], '401879233')
            self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
