import datetime as dt
import importlib.util
import json
import unittest
from pathlib import Path


path = Path(__file__).parents[1] / 'ops' / 'matchday_scout.py'
spec = importlib.util.spec_from_file_location('matchday_scout', path)
scout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scout)


class MatchdayScoutTests(unittest.TestCase):
    def test_out_of_range_fixture_is_dropped_and_empty_is_valid(self):
        now = dt.datetime(2026, 11, 14, 18, tzinfo=dt.timezone.utc)
        searches = []

        def search(query):
            searches.append(query)
            return {'results': [{'title': 'Football fixtures', 'snippet': 'Spain vs England 15 November 2026'}]}

        def model(system, evidence, limit):
            self.assertIn('2026-11-15', system)
            self.assertIn('2026-11-16', system)
            self.assertEqual(limit, 220)
            return json.dumps({'matches': [
                {'home': 'England', 'away': 'Croatia', 'competition': 'Nations League', 'date': '2026-11-12'},
                {'home': 'Spain', 'away': 'England', 'competition': 'Nations League', 'date': '2026-11-15'},
            ]})

        self.assertEqual(scout.shortlist(now, search, model), [
            {'home': 'Spain', 'away': 'England', 'competition': 'Nations League', 'date': '2026-11-15'}])
        self.assertEqual(len(searches), 2)
        self.assertEqual(scout.shortlist(now, lambda _: {'results': []},
                                        lambda *_: self.fail('No call expected')), [])


if __name__ == '__main__':
    unittest.main()
