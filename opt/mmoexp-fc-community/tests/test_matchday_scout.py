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
    def test_afternoon_run_keeps_tonights_matches(self):
        now = dt.datetime(2026, 11, 15, 15, tzinfo=dt.timezone.utc)

        def model(prompt, evidence, limit):
            self.assertIn('2026-11-15 or 2026-11-16', prompt)
            if not evidence:
                return json.dumps({'queries': ['Spain England 15 November 2026 kickoff']})
            return json.dumps({'matches': [{
                'home': 'Spain', 'away': 'England', 'competition': 'Nations League',
                'date': '2026-11-15'}]})

        result = scout.shortlist(now, lambda _: {'results': [{'title': 'Spain vs England'}]}, model)
        self.assertEqual(result[0]['date'], '2026-11-15')

    def test_out_of_range_fixture_is_dropped_and_empty_is_valid(self):
        now = dt.datetime(2026, 11, 15, 8, tzinfo=dt.timezone.utc)
        searches = []

        def search(query):
            searches.append(query)
            return {'results': [{'title': 'Football fixtures', 'snippet': 'Spain vs England 15 November 2026'}]}

        def model(system, evidence, limit):
            self.assertIn('2026-11-15', system)
            self.assertIn('2026-11-16', system)
            if not evidence:
                self.assertEqual(limit, 160)
                return json.dumps({'queries': [
                    '15 16 November 2026 football major league fixtures',
                    '15 16 November 2026 UEFA international fixtures',
                    '15 16 November 2026 cup fixtures',
                ]})
            self.assertEqual(limit, 320)
            return json.dumps({'matches': [
                {'home': 'England', 'away': 'Croatia', 'competition': 'Nations League', 'date': '2026-11-12'},
                {'home': 'Spain', 'away': 'England', 'competition': 'Nations League',
                 'date': '2026-11-15',
                 'question': 'Which side would you build your FC27 midfield around?'},
            ]})

        self.assertEqual(scout.shortlist(now, search, model), [
            {'home': 'Spain', 'away': 'England', 'competition': 'Nations League',
             'date': '2026-11-15',
             'question': 'Which side would you build your FC27 midfield around?'}])
        self.assertEqual(len(searches), 3)
        self.assertIn('UEFA international', searches[1])
        self.assertEqual(scout.shortlist(now, lambda _: {'results': []}, model), [])


if __name__ == '__main__':
    unittest.main()
