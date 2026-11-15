import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from chat_service import ChatClient
from matchday_editorial import card_text, load_plan
from matchday_scout_bridge import load_scout, merge_plan, replace_plan
from test_matchday_selector import CHANNEL, GUILD, card


UTC = dt.timezone.utc
ROUTES = {str(GUILD): {'source_channel_id': CHANNEL,
                       'discussion_channel_id': CHANNEL}}


class ScoutBridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        self.spain_kickoff = dt.datetime(2026, 11, 15, 19, 45, tzinfo=UTC)
        self.germany_kickoff = dt.datetime(2026, 11, 15, 18, 45, tzinfo=UTC)
        self.scout = [
            {'home': 'Spain', 'away': 'England', 'date': '2026-11-15',
             'competition': 'UEFA Nations League',
             'question': 'Which side would you build your FC27 midfield around?'},
            {'home': 'France', 'away': 'Turkey', 'date': '2026-11-15',
             'competition': 'UEFA Nations League'},
        ]
        self.manual = {'fixture_id': 'germany-netherlands', 'guild_id': str(GUILD),
                       'home': 'Germany', 'away': 'Netherlands',
                       'competition': 'UEFA Nations League',
                       'kickoff_utc': self.germany_kickoff.isoformat().replace('+00:00', 'Z'),
                       'smart_score_message_url':
                           'https://discord.com/channels/{}/{}/1571184986541789366'.format(
                               GUILD, CHANNEL)}

    def test_only_confirmed_scout_pick_fills_manual_plan_vacancy(self):
        source = card(self.now, [
            ('Spain', 'England', 'UEFA Nations League', self.spain_kickoff),
            ('France', 'Turkey', 'UEFA Nations League', self.spain_kickoff),
        ], created_at=self.now - dt.timedelta(hours=15))
        plan, receipt = merge_plan(
            self.scout, [source], {'version': 1, 'matches': [self.manual]},
            GUILD, CHANNEL, self.now)
        self.assertEqual(plan['matches'][0], self.manual)
        self.assertEqual([item['home'] for item in plan['matches']],
                         ['Germany', 'Spain'])
        self.assertEqual(receipt['added'], ['Spain vs England'])
        self.assertEqual(receipt['capacity'], ['France vs Turkey'])
        self.assertEqual(plan['matches'][1]['question'], self.scout[0]['question'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps(plan), encoding='utf-8')
            self.assertEqual(len(load_plan(path, ROUTES, self.now)), 2)
            self.assertIn(self.scout[0]['question'],
                          card_text(load_plan(path, ROUTES, self.now)[1], 'day_before'))
        again, receipt = merge_plan(
            self.scout, [source], plan, GUILD, CHANNEL, self.now)
        self.assertEqual(again, plan)
        self.assertEqual(receipt['already_planned'], ['Spain vs England'])

    def test_no_matching_public_card_does_not_invent_fixture(self):
        source = card(self.now, [
            ('England', 'Spain', 'UEFA Nations League', self.spain_kickoff),
        ])
        plan, receipt = merge_plan(
            self.scout, [source], {'version': 1, 'matches': [self.manual]},
            GUILD, CHANNEL, self.now)
        self.assertEqual(plan['matches'], [self.manual])
        self.assertEqual(len(receipt['unmatched']), 2)

    def test_rescheduled_operator_fixture_is_flagged_without_duplicate(self):
        earlier = dict(self.manual, home='Spain', away='England',
                       kickoff_utc='2026-11-16T19:45:00Z', status='hold')
        source = card(self.now, [
            ('Spain', 'England', 'UEFA Nations League', self.spain_kickoff),
        ])
        plan, receipt = merge_plan(
            self.scout[:1], [source], {'version': 1, 'matches': [earlier]},
            GUILD, CHANNEL, self.now)
        self.assertEqual(plan['matches'], [earlier])
        self.assertEqual(receipt['needs_review'], ['Spain vs England'])

    def test_stale_scout_and_concurrent_operator_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            scout_path = Path(folder) / 'scout.json'
            scout_path.write_text(json.dumps({
                'generated_at_utc': (self.now - dt.timedelta(days=2)).isoformat(),
                'matches': self.scout,
            }), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'stale'):
                load_scout(scout_path, self.now)
            scout_path.write_text(json.dumps({
                'generated_at_utc': self.now.isoformat(),
                'matches': [dict(self.scout[0], question='first line\nsecond line')],
            }), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'question'):
                load_scout(scout_path, self.now)
            plan_path = Path(folder) / 'plan.json'
            plan_path.write_text('{"version":1,"matches":[]}', encoding='utf-8')
            old = plan_path.stat()
            plan_path.write_text('{"version":1,"matches":[{"operator":"edit"}]}',
                                 encoding='utf-8')
            self.assertFalse(replace_plan(plan_path, (old.st_mtime_ns, old.st_size),
                                          {'version': 1, 'matches': []}))
            self.assertIn('operator', plan_path.read_text(encoding='utf-8'))


class ScoutBridgeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_scout_reads_public_card_once_and_updates_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            now = dt.datetime.now(UTC)
            kickoff = now + dt.timedelta(hours=6)
            day = kickoff.astimezone(ZoneInfo('Europe/London')).date().isoformat()
            scout_path = root / 'scout.json'
            scout_path.write_text(json.dumps({
                'generated_at_utc': now.isoformat(),
                'matches': [{'home': 'Spain', 'away': 'England', 'date': day,
                             'competition': 'UEFA Nations League'}],
            }), encoding='utf-8')
            plan_path = root / 'plan.json'
            plan_path.write_text('{"version":1,"matches":[]}', encoding='utf-8')
            config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                      'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                              'keywords': []}}},
                      'matchday_engagement': {'enabled': True, 'routes': {
                          str(GUILD): {'source_channel_id': CHANNEL,
                                       'discussion_channel_id': CHANNEL,
                                       'players_channel_id': CHANNEL,
                                       'coins_channel_id': CHANNEL}},
                          'state_path': str(root / 'pulse.sqlite3')},
                      'matchday_editorial': {'enabled': True,
                          'allowed_guild_ids': [str(GUILD)],
                          'plan_path': str(plan_path),
                          'state_path': str(root / 'editorial.sqlite3'),
                          'scout_path': str(scout_path)}}
            client = ChatClient(config)
            source = card(now, [('Spain', 'England', 'UEFA Nations League', kickoff)])
            reads = []

            async def history(limit):
                reads.append(limit)
                if False:
                    yield source

            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                                      history=history)
            client.get_channel = lambda channel_id: channel if channel_id == CHANNEL else None
            await client.refresh_scout_plan()
            self.assertEqual(json.loads(plan_path.read_text(encoding='utf-8'))[
                'matches'], [])
            await client.handle_scout_card(source)
            await client.refresh_scout_plan()
            self.assertEqual(reads, [100])
            self.assertEqual(json.loads(plan_path.read_text(encoding='utf-8'))[
                'matches'][0]['home'], 'Spain')
            await client.close()


if __name__ == '__main__':
    unittest.main()
