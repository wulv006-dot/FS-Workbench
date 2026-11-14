import json
import unittest
from unittest.mock import Mock

from matchday_espn import MatchdaySourceError, fetch_scoreboard, normalize_event


EVENT = {
    'id': '401878757', 'date': '2026-11-07T17:30Z',
    'status': {'displayClock': "73'", 'type': {'state': 'in', 'completed': False}},
    'competitions': [{'competitors': [
        {'homeAway': 'home', 'score': '3', 'team': {'id': '393', 'displayName': 'Nottingham Forest'}},
        {'homeAway': 'away', 'score': '1', 'team': {'id': '382', 'displayName': 'Manchester City'}},
    ], 'details': [
        {'scoringPlay': True, 'redCard': False, 'clock': {'value': 4377, 'displayValue': "73'"},
         'team': {'id': '393'}, 'athletesInvolved': [{'id': '307114', 'displayName': 'Liam Delap'}]},
    ]}],
    'links': [{'rel': ['summary'], 'href': 'https://www.espn.com/soccer/match/_/gameId/401878757/example'}],
}


class ESPNAdapterTests(unittest.TestCase):
    def test_normalizes_verified_scoreboard_shape(self):
        event = normalize_event(EVENT, 'pl')
        self.assertEqual(event['score'], [3, 1])
        self.assertEqual(event['state'], 'in')
        self.assertEqual(event['important_events'][0]['type'], 'goal')
        self.assertEqual(event['important_events'][0]['player'], 'Liam Delap')
        self.assertEqual(event['important_events'][0]['id'], normalize_event(EVENT, 'pl')['important_events'][0]['id'])

    def test_scheduled_match_has_no_score(self):
        item = dict(EVENT, status={'type': {'state': 'pre', 'completed': False}})
        self.assertIsNone(normalize_event(item, 'pl')['score'])

    def test_only_fixed_leagues_and_dates_can_be_requested(self):
        with self.assertRaises(MatchdaySourceError):
            fetch_scoreboard('../evil', '20261107', opener=lambda *_args, **_kw: None)
        with self.assertRaises(MatchdaySourceError):
            fetch_scoreboard('pl', '2026-11-07', opener=lambda *_args, **_kw: None)

    def test_fetches_one_day_and_rejects_bad_shape(self):
        response = Mock()
        response.read.return_value = json.dumps({'events': [EVENT]}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        opener = Mock(return_value=response)
        self.assertEqual(fetch_scoreboard('pl', '20261107', opener)[0]['fixture_id'], '401878757')
        self.assertIn('/eng.1/scoreboard?dates=20261107', opener.call_args[0][0].full_url)
        self.assertNotIn('User-agent', opener.call_args[0][0].headers)


if __name__ == '__main__':
    unittest.main()
