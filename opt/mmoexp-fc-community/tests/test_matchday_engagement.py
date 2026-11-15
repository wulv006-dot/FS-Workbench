import tempfile
import time
import unittest
import sqlite3
from contextlib import closing
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from matchday_engagement import (MatchPulseStore, followup_due_at, parse_smart_score,
                                 prompt_text, validate_matchday_config)

TEST_GUILD = 1565922092518613064
SOURCE = 1568260661010497627
CONFIG = {'enabled': True, 'routes': {str(TEST_GUILD): {
    'source_channel_id': SOURCE, 'discussion_channel_id': SOURCE,
    'players_channel_id': SOURCE, 'coins_channel_id': SOURCE}}}


def message(mid, body, author=1496068397757366273, channel=SOURCE, now=None):
    now = time.time() if now is None else now
    embed = SimpleNamespace(title='UEFA Nations League · 2H', description=body, fields=[])
    return SimpleNamespace(id=mid, guild=SimpleNamespace(id=TEST_GUILD),
                           channel=SimpleNamespace(id=channel),
                           author=SimpleNamespace(id=author, bot=True),
                           type=SimpleNamespace(value=0), webhook_id=None,
                           interaction_metadata=None, content='', embeds=[embed],
                           created_at=datetime.fromtimestamp(now, timezone.utc),
                           jump_url='https://discord.com/channels/{}/{}/{}'.format(TEST_GUILD, SOURCE, mid))


class MatchdayEngagementTests(unittest.TestCase):
    def test_followup_is_next_day_even_for_early_final(self):
        final = datetime(2026, 11, 15, 9, 50, tzinfo=timezone.utc).timestamp()
        due = datetime.fromtimestamp(followup_due_at(final), timezone.utc)
        self.assertEqual(due, datetime(2026, 11, 16, 10, tzinfo=timezone.utc))

    def test_strict_source_and_goal_parser(self):
        validate_matchday_config(CONFIG)
        now = time.time()
        body = '**Kosovo** `0 — 1` **Israel**\n G O A L !\n 72\' Israel Player Normal Goal'
        pulse = parse_smart_score(message(1571184986541789367, body, now=now), CONFIG, now)
        self.assertEqual((pulse.home, pulse.away, pulse.score, pulse.kind),
                         ('Kosovo', 'Israel', '0–1', 'goal'))
        self.assertIn('Kosovo vs Israel', prompt_text(pulse))
        self.assertIn('0–1', prompt_text(pulse))
        self.assertIsNone(parse_smart_score(message(1, body, author=2, now=now), CONFIG, now))
        self.assertIsNone(parse_smart_score(message(1, body, channel=3, now=now), CONFIG, now))
        self.assertIsNone(parse_smart_score(message(1, body, now=now-400), CONFIG, now))

    def test_cooldown_and_single_final(self):
        now = time.time()
        kickoff = parse_smart_score(message(1571184986541789366, 'Kosovo 0 — 0 Israel\nMatch Started', now=now), CONFIG, now)
        goal = parse_smart_score(message(1571184986541789367, 'Kosovo 1 — 0 Israel\nGoal!', now=now), CONFIG, now)
        next_goal = parse_smart_score(message(1571184986541789369, 'Kosovo 2 — 0 Israel\nGoal!', now=now), CONFIG, now)
        half_time = parse_smart_score(message(1571184986541789370, 'Kosovo 2 — 0 Israel\nHalf Time', now=now), CONFIG, now)
        final = parse_smart_score(message(1571184986541789372, 'Kosovo 2 — 0 Israel\nMatch Finished', now=now), CONFIG, now)
        with tempfile.TemporaryDirectory() as directory:
            store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            self.assertTrue(store.claim(1571184986541789366, kickoff, now))
            self.assertTrue(store.claim(1571184986541789367, goal, now))
            self.assertFalse(store.claim(1571184986541789368, goal, now+1))
            self.assertTrue(store.claim(1571184986541789369, next_goal, now+2))
            self.assertTrue(store.claim(1571184986541789370, half_time, now+3))
            self.assertFalse(store.claim(1571184986541789371, next_goal, now+3))
            self.assertTrue(store.claim(1571184986541789372, final, now+4))
            self.assertFalse(store.claim(1571184986541789373, final, now+1000))
            self.assertFalse(store.claim(1571184986541789368, goal, now+1001))
            with closing(sqlite3.connect(store.path)) as db:
                db.execute("UPDATE match_pulse SET last_kind='final'")
                db.commit()
            self.assertFalse(store.claim(1571184986541789374, final, now+1002))

    def test_ignores_status_and_configuration_messages(self):
        now = time.time()
        self.assertIsNone(parse_smart_score(message(1, 'Live Subscription Active\nMatch\n**Kosovo** vs **Israel**\nPush Notifications\nGoals · Half Time', now=now), CONFIG, now))
        self.assertIsNone(parse_smart_score(message(2, 'Match status changed → Second Half\nKosovo 0 — 0 Israel', now=now), CONFIG, now))
        finished = parse_smart_score(message(3, '🏁 Match Finished\nManchester City  `3 — 0`  Arsenal\nResult\nManchester City wins', now=now), CONFIG, now)
        self.assertEqual((finished.kind, finished.score), ('final', '3–0'))
        with self.assertRaises(ValueError):
            validate_matchday_config({'enabled': True, 'routes': {'999999999999999999': CONFIG['routes'][str(TEST_GUILD)]}})


class ChatIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_discussion_channel_does_not_consume_event(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            chat_config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': dict(CONFIG, state_path=str(Path(directory) / 'pulse.sqlite3'))}
            client = ChatClient(chat_config)
            event = message(1571184986541789367, 'Kosovo 1 — 0 Israel\nGoal!')
            client.get_channel = lambda channel_id: None
            await client.on_message(event)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=TEST_GUILD),
                                      send=AsyncMock(return_value=SimpleNamespace(id=1571184986541789380)))
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            await client.on_message(event)
            self.assertEqual(channel.send.await_count, 1)
            await client.close()

    async def test_smart_score_event_posts_one_discussion_card(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            chat_config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': dict(CONFIG, state_path=str(Path(directory) / 'pulse.sqlite3'))}
            client = ChatClient(chat_config)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=TEST_GUILD), send=AsyncMock())
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            now = time.time()
            event = message(1571184986541789367, 'Kosovo 1 — 0 Israel\n G O A L !', now=now)
            client.matchday_store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            await client.on_message(event)
            await client.on_message(event)
            self.assertEqual(channel.send.await_count, 1)
            self.assertIn('Kosovo vs Israel', channel.send.await_args.kwargs['embed'].description)
            self.assertEqual(len(channel.send.await_args.kwargs['view'].children), 3)
            self.assertIn('Smart Score public update:', client.history[SOURCE][-1][1])
            await client.close()

    async def test_final_creates_one_next_morning_match_to_squad_card(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            chat_config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': dict(CONFIG, state_path=str(Path(directory) / 'pulse.sqlite3'))}
            client = ChatClient(chat_config)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=TEST_GUILD),
                                      send=AsyncMock(return_value=SimpleNamespace(id=1571184986541789380)))
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            now = time.time()
            event = message(1571184986541789372, 'Kosovo 2 — 0 Israel\nMatch Finished', now=now)
            await client.on_message(event)
            await client.on_message(event)
            with closing(sqlite3.connect(client.matchday_store.path)) as db:
                due = db.execute('SELECT due_at FROM match_followup').fetchone()[0]
            client.matchday_store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            await client.send_followups_due(due - 1)
            self.assertEqual(channel.send.await_count, 1)
            await client.send_followups_due(due + 1)
            await client.send_followups_due(due + 2)
            self.assertEqual(channel.send.await_count, 2)
            self.assertIn('2–0', channel.send.await_args.kwargs['embed'].description)
            self.assertEqual(len(channel.send.await_args.kwargs['view'].children), 2)
            await client.close()


if __name__ == '__main__':
    unittest.main()
