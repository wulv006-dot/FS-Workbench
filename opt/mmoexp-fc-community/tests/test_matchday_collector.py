import datetime
import unittest

from matchday_collector import collect


class MatchdayCollectorTests(unittest.TestCase):
    def test_collects_openliga_window_and_bounded_espn_days(self):
        primary_calls, backup_calls = [], []

        def primary(league, season, start, end):
            primary_calls.append((league, season, (end - start).days))
            return [{'fixture_id': league + '-1'}]

        def backup(league, day):
            backup_calls.append((league, day))
            return []

        snapshot = collect(datetime.datetime(2026, 11, 14, tzinfo=datetime.timezone.utc),
                           primary, backup)
        self.assertEqual(len(primary_calls), 4)
        self.assertEqual(primary_calls[0], ('pl', 2026, 9))
        self.assertEqual(len(backup_calls), 45)
        self.assertEqual(len(snapshot['sources']['openligadb']['pl']), 1)
        self.assertEqual(snapshot['sources']['espn']['fr1'], [])
        self.assertTrue(all(row['ok'] for row in snapshot['health']))

    def test_primary_failure_is_reported_without_fabricating_score(self):
        def failed(league, season, start, end):
            raise OSError('offline')

        snapshot = collect(datetime.datetime(2026, 11, 14, tzinfo=datetime.timezone.utc),
                           failed, lambda league, day: [])
        self.assertEqual(snapshot['sources']['openligadb'], {})
        self.assertEqual(sum(not row['ok'] for row in snapshot['health']), 4)


if __name__ == '__main__':
    unittest.main()
