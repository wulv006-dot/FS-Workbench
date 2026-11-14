import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from matchday_editorial import load_plan
from matchday_selector import parse_upcoming, select


UTC = dt.timezone.utc
GUILD = 1565922092518613064
CHANNEL = 1568260661010497627
SMART_SCORE = 1496068397757366273
ROUTES = {str(GUILD): {'source_channel_id': CHANNEL,
                       'discussion_channel_id': CHANNEL}}


def card(now, fixtures, message_id=1571184986541789367, **changes):
    fields = [SimpleNamespace(
        name='🟦 UPCOMING **{}** vs **{}**'.format(home, away),
        value=('> 🏆 **League**: {}\n> 📡 **Status**: Not Started\n'
               '> 📅 **Kickoff**: <t:{}:F>').format(league, int(kickoff.timestamp())))
        for home, away, league, kickoff in fixtures]
    source = SimpleNamespace(
        id=message_id, author=SimpleNamespace(id=SMART_SCORE, bot=True),
        guild=SimpleNamespace(id=GUILD), channel=SimpleNamespace(id=CHANNEL),
        created_at=now - dt.timedelta(minutes=3), webhook_id=None,
        jump_url='https://discord.com/channels/{}/{}/{}'.format(
            GUILD, CHANNEL, message_id),
        embeds=[SimpleNamespace(title='Upcoming Matches', fields=fields)])
    for key, value in changes.items():
        setattr(source, key, value)
    return source


class MatchdaySelectorTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        self.kickoff = self.now + dt.timedelta(hours=6)

    def test_strict_public_source_and_time_window(self):
        fixture = [('Manchester City', 'Arsenal', 'Premier League', self.kickoff)]
        good = card(self.now, fixture)
        self.assertEqual(len(parse_upcoming(good, GUILD, CHANNEL, self.now)), 1)
        self.assertEqual(parse_upcoming(good, GUILD, CHANNEL + 1, self.now), [])
        self.assertEqual(parse_upcoming(card(self.now, fixture,
            author=SimpleNamespace(id=1, bot=True)), GUILD, CHANNEL, self.now), [])
        self.assertEqual(parse_upcoming(card(self.now, fixture,
            created_at=self.now - dt.timedelta(hours=7)), GUILD, CHANNEL, self.now), [])
        self.assertEqual(parse_upcoming(card(self.now, fixture,
            jump_url='https://example.com/not-a-discord-card'), GUILD, CHANNEL, self.now), [])
        self.assertEqual(parse_upcoming(card(self.now, [('Manchester City', 'Arsenal',
            'Premier League', self.now - dt.timedelta(minutes=1))]),
            GUILD, CHANNEL, self.now), [])
        started = card(self.now, fixture)
        started.embeds[0].fields[0].value = started.embeds[0].fields[0].value.replace(
            'Not Started', 'Live')
        self.assertEqual(parse_upcoming(started, GUILD, CHANNEL, self.now), [])

    def test_ambiguous_league_ranking_and_editorial_plan_contract(self):
        matches = [
            ('Toronto FC', 'Vancouver FC', 'Premier League', self.kickoff),
            ('Paris Saint-Germain', 'Lyon', 'Ligue 1', self.kickoff),
            ('Real Madrid', 'Barcelona', 'La Liga', self.kickoff),
            ('Manchester City', 'Arsenal', 'Premier League', self.kickoff),
        ]
        plan, receipt = select([card(self.now, matches)], GUILD, CHANNEL,
                               self.now, weekly_limit=2)
        self.assertEqual([m['home'] for m in plan['matches']],
                         ['Manchester City', 'Real Madrid'])
        self.assertEqual(len(receipt['selected']), 2)
        self.assertEqual(receipt['selected'][0]['score'] >
                         receipt['selected'][1]['score'], True)
        self.assertIn('ambiguous_competition_or_nonfocus_clubs',
                      [item['reason'] for item in receipt['excluded']])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps(plan), encoding='utf-8')
            loaded = load_plan(path, ROUTES, now=self.now, weekly_limit=2)
            self.assertEqual(len(loaded), 2)

    def test_existing_hold_is_not_selected_and_receipt_keeps_correct_score(self):
        matches = [
            ('Manchester City', 'Arsenal', 'Premier League', self.kickoff),
            ('Real Madrid', 'Barcelona', 'La Liga', self.kickoff),
            ('Paris Saint-Germain', 'Lyon', 'Ligue 1', self.kickoff),
        ]
        existing = [{'guild_id': str(GUILD), 'home': 'Manchester City',
                     'away': 'Arsenal', 'competition': 'Premier League',
                     'fixture_id': 'city-arsenal-held', 'status': 'hold'}]
        plan, receipt = select([card(self.now, matches)], GUILD, CHANNEL,
                               self.now, weekly_limit=2, existing_matches=existing)
        self.assertEqual([m['home'] for m in plan['matches']],
                         ['Real Madrid', 'Paris Saint-Germain'])
        self.assertEqual([r['fixture'].split(' vs ')[0] for r in receipt['selected']],
                         ['Real Madrid', 'Paris Saint-Germain'])
        self.assertEqual([r['score'] for r in receipt['selected']], sorted(
            [r['score'] for r in receipt['selected']], reverse=True))
        self.assertIn('existing_hold_requires_review',
                      [item['reason'] for item in receipt['excluded']])

    def test_newer_card_wins_and_missing_source_is_explicit(self):
        old = card(self.now, [('Manchester City', 'Arsenal', 'Premier League',
                               self.kickoff)], message_id=1571184986541789367,
                   created_at=self.now - dt.timedelta(minutes=4))
        new = card(self.now, [('Manchester City', 'Arsenal', 'Premier League',
                               self.kickoff + dt.timedelta(minutes=15))],
                   message_id=1571184986541789368)
        plan, receipt = select([old, new], GUILD, CHANNEL, self.now)
        self.assertEqual(plan['matches'][0]['smart_score_message_url'], new.jump_url)
        self.assertEqual(receipt['candidates'], 1)
        empty, missing = select([], GUILD, CHANNEL, self.now)
        self.assertEqual(empty['matches'], [])
        self.assertFalse(missing['had_source'])


if __name__ == '__main__':
    unittest.main()
