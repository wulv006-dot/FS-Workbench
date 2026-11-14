import unittest
from datetime import datetime, timezone

from matchday_openligadb import MatchdaySourceError, fetch_group_if_changed, fetch_season_window, normalize_match


MATCH = {
    'matchID': 86635, 'matchDateTimeUTC': '2026-11-21T12:30:00Z',
    'matchIsFinished': False, 'group': {'groupOrderID': 11},
    'team1': {'teamId': 2617, 'teamName': 'Manchester City'},
    'team2': {'teamId': 2620, 'teamName': 'Fulham FC'},
    'goals': [
        {'goalID': 1, 'scoreTeam1': 0, 'scoreTeam2': 0, 'matchMinute': None},
        {'goalID': 2, 'scoreTeam1': 1, 'scoreTeam2': 0, 'matchMinute': 15,
         'goalGetterName': 'Player A', 'scoringTeamId': 2617,
         'isPenalty': False, 'isOwnGoal': False},
    ],
    'matchResults': [],
}


class OpenLigaAdapterTests(unittest.TestCase):
    def test_normalize_scoring_event_and_source_credit(self):
        match = normalize_match(MATCH, 'pl')
        self.assertEqual(match['fixture_id'], '86635')
        self.assertEqual(match['score'], [1, 0])
        self.assertEqual(match['kickoff_utc'], '2026-11-21T12:30:00+00:00')
        self.assertEqual(match['goals'][0]['id'], '86635:2')
        self.assertEqual(len(match['goals']), 1)
        self.assertIn('ODbL', match['attribution'])

    def test_unknown_score_is_not_fabricated(self):
        match = normalize_match(dict(MATCH, goals=[]), 'pl')
        self.assertIsNone(match['score'])
        self.assertFalse(match['finished'])

    def test_changed_marker_avoids_duplicate_full_fetch(self):
        calls = []

        def request(path):
            calls.append(path)
            return '2026-11-14T10:00:00' if 'lastchangedate' in path else [MATCH]

        marker, matches = fetch_group_if_changed('pl', 2026, 11, request_json=request)
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(calls), 2)
        calls.clear()
        same, matches = fetch_group_if_changed('pl', 2026, 11, marker, request_json=request)
        self.assertEqual(same, marker)
        self.assertIsNone(matches)
        self.assertEqual(len(calls), 1)

    def test_rejects_unknown_league_before_request(self):
        with self.assertRaises(MatchdaySourceError):
            fetch_group_if_changed('../evil', 2026, 11, request_json=lambda path: None)

    def test_season_window_selects_only_target_dates(self):
        other = dict(MATCH, matchID=1, matchDateTimeUTC='2027-05-30T12:30:00Z')
        rows = fetch_season_window('pl', 2026,
            datetime(2026, 11, 20, tzinfo=timezone.utc),
            datetime(2026, 11, 23, tzinfo=timezone.utc),
            request_json=lambda path: [other, MATCH])
        self.assertEqual([row['fixture_id'] for row in rows], ['86635'])


if __name__ == '__main__':
    unittest.main()
