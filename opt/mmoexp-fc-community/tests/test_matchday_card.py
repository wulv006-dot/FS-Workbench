import datetime
import unittest

from matchday_card import render_card


class MatchdayCardTests(unittest.TestCase):
    def test_uses_discord_local_time_and_one_source_aware_card(self):
        now = datetime.datetime(2026, 11, 14, tzinfo=datetime.timezone.utc)
        snapshot = {'schema_version': 1, 'checked_at_utc': now.isoformat(),
                    'sources': {'openligadb': {'pl': [{
                        'fixture_id': '86635', 'league': 'pl',
                        'kickoff_utc': '2026-11-21T12:30:00+00:00', 'finished': False,
                        'home_team': {'name': 'Manchester City'},
                        'away_team': {'name': 'Fulham FC'},
                    }]}, 'espn': {'pl': [{
                        'league': 'pl', 'kickoff_utc': '2026-11-21T12:30:00+00:00',
                        'home_team': {'name': 'Manchester City FC'},
                        'away_team': {'name': 'Fulham'},
                    }], 'fr1': []}}}
        card = render_card(snapshot, guild_id=1, discuss_channel_id=2,
                           players_channel_id=3, now=now)
        self.assertEqual(len(card['embeds']), 1)
        self.assertIn('<t:', card['embeds'][0]['description'])
        self.assertIn('Manchester City', card['embeds'][0]['description'])
        self.assertEqual(card['allowed_mentions'], {'parse': []})

    def test_conflicting_live_scores_are_not_presented_as_verified(self):
        now = datetime.datetime(2026, 11, 21, 13, tzinfo=datetime.timezone.utc)
        snapshot = {'schema_version': 1, 'checked_at_utc': now.isoformat(),
                    'sources': {'openligadb': {'pl': [{
                        'fixture_id': '86635', 'league': 'pl',
                        'kickoff_utc': '2026-11-21T12:30:00+00:00', 'finished': False,
                        'home_team': {'name': 'Manchester City'},
                        'away_team': {'name': 'Fulham FC'},
                    }]}, 'espn': {'pl': [{
                        'league': 'pl', 'kickoff_utc': '2026-11-21T12:30:00+00:00',
                        'home_team': {'name': 'Manchester City'},
                        'away_team': {'name': 'Fulham'},
                    }]}},
                    'live': {'fixtures': [{'openliga_id': '86635',
                        'openligadb': {'score': [1, 0]}, 'espn': {'score': [2, 0]}}]}}
        text = render_card(snapshot, guild_id=1, discuss_channel_id=2,
                           players_channel_id=3, now=now)['embeds'][0]['description']
        self.assertIn('(OpenLigaDB, checking)', text)
        self.assertNotIn('**2–0**', text)

    def test_unconfirmed_openliga_fixture_is_not_published(self):
        now = datetime.datetime(2026, 11, 14, tzinfo=datetime.timezone.utc)
        snapshot = {'schema_version': 1, 'checked_at_utc': now.isoformat(),
                    'sources': {'openligadb': {'la1': [{
                        'fixture_id': '1', 'league': 'la1',
                        'kickoff_utc': '2026-11-21T12:30:00+00:00', 'finished': False,
                        'home_team': {'name': 'AFC Ajax'},
                        'away_team': {'name': 'Espanyol Barcelona'},
                    }]}, 'espn': {'la1': [{
                        'league': 'la1', 'kickoff_utc': '2026-11-21T12:30:00+00:00',
                        'home_team': {'name': 'Real Madrid'},
                        'away_team': {'name': 'Barcelona'},
                    }]}}}
        text = render_card(snapshot, guild_id=1, discuss_channel_id=2,
                           players_channel_id=3, now=now)['embeds'][0]['description']
        self.assertNotIn('Ajax', text)
        self.assertIn('No selected league fixtures', text)


if __name__ == '__main__':
    unittest.main()
