import asyncio
import tempfile
import time
import unittest
import sqlite3
from contextlib import closing
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from matchday_engagement import (MatchPulse, MatchPulseStore, followup_due_at, parse_match_event,

                                 prompt_text, validate_matchday_config)

TEST_GUILD = 1565922092518613064
SOURCE = 1568260661010497627
CONFIG = {'enabled': True, 'routes': {str(TEST_GUILD): {
    'source_channel_id': SOURCE, 'discussion_channel_id': SOURCE,
    'players_channel_id': SOURCE, 'coins_channel_id': SOURCE,
    'provider': 'unify_football'}}}


def message(mid, body, author=1332364544869142538, channel=SOURCE, now=None):
    now = time.time() if now is None else now
    embed = SimpleNamespace(title='UEFA Nations League · 2H', description=body, fields=[])
    return SimpleNamespace(id=mid, guild=SimpleNamespace(id=TEST_GUILD),
                           channel=SimpleNamespace(id=channel),
                           author=SimpleNamespace(id=author, bot=True),
                           type=SimpleNamespace(value=0), webhook_id=None,
                           interaction_metadata=None, content='', embeds=[embed],
                           created_at=datetime.fromtimestamp(now, timezone.utc),
                           jump_url='https://discord.com/channels/{}/{}/{}'.format(TEST_GUILD, SOURCE, mid))


def unify_message(mid, title, score, now=None):
    event = message(mid, score, author=1332364544869142538, now=now)
    event.embeds[0].title = title
    return event


UNIFY_CONFIG = {'enabled': True, 'routes': {str(TEST_GUILD): dict(
    CONFIG['routes'][str(TEST_GUILD)], provider='unify_football')}}


class MatchdayEngagementTests(unittest.TestCase):
    def test_unify_real_card_shapes_and_source_isolation(self):
        validate_matchday_config(UNIFY_CONFIG)
        private_route = dict(UNIFY_CONFIG['routes'][str(TEST_GUILD)],
                             score_channel_id=SOURCE + 1)
        private_config = {'enabled': True, 'routes': {str(TEST_GUILD): private_route}}
        validate_matchday_config(private_config)
        now = time.time()
        goal = unify_message(1571546825184256152, "[67'] ⚽️ GOAAAAAAAAAAL!",
                             '## 👤 N. Krstovic (_Montenegro_)\n\n'
                             '### **Cyprus**  ` 1 - 3 `  **Montenegro**', now)
        pulse = parse_match_event(goal, UNIFY_CONFIG, now)
        self.assertIsNone(parse_match_event(goal, private_config, now))
        goal.channel.id = SOURCE + 1
        self.assertIsNotNone(parse_match_event(goal, private_config, now))
        goal.channel.id = SOURCE
        self.assertEqual((pulse.home, pulse.away, pulse.score, pulse.kind, pulse.source_name),
                         ('Cyprus', 'Montenegro', '1–3', 'goal', 'UnifyFootball'))
        half = unify_message(1571537266675818698, '',
                             '## ⏸️ HALFTIME\n\n# **Latvia** `0 - 0` **Armenia**', now)
        self.assertEqual(parse_match_event(half, UNIFY_CONFIG, now).kind, 'half_time')
        final = unify_message(1571553535739437117, '',
                              '## 🔴 FULL-TIME!\n\n## **Cyprus**  ` 1 - 4 `  **Montenegro**', now)
        self.assertEqual(parse_match_event(final, UNIFY_CONFIG, now).kind, 'final')
        kickoff = unify_message(1571613094285934593, 'KICK OFF!',
                                'Spain vs England\nReferee\nClement Turpin, France', now)
        kickoff_pulse = parse_match_event(kickoff, UNIFY_CONFIG, now)
        self.assertEqual((kickoff_pulse.home, kickoff_pulse.away,
                          kickoff_pulse.score, kickoff_pulse.kind),
                         ('Spain', 'England', '0–0', 'kickoff'))
        self.assertIsNone(parse_match_event(unify_message(kickoff.id, 'KICK OFF!',
                            'Referee\nClement Turpin, France', now), UNIFY_CONFIG, now))
        self.assertIsNone(parse_match_event(message(goal.id, 'Cyprus 1 - 3 Montenegro', now=now),
                                            UNIFY_CONFIG, now))
        self.assertIsNone(parse_match_event(unify_message(goal.id, goal.embeds[0].title,
                            'Cyprus 1 - 3 Montenegro', now - 400), UNIFY_CONFIG, now))
        goal.interaction_metadata = object()
        self.assertIsNone(parse_match_event(goal, UNIFY_CONFIG, now))
        with self.assertRaises(ValueError):
            validate_matchday_config({'enabled': True, 'routes': {str(TEST_GUILD): dict(
                UNIFY_CONFIG['routes'][str(TEST_GUILD)], provider='unknown')}})
        with self.assertRaises(ValueError):
            validate_matchday_config({'enabled': True, 'routes': {str(TEST_GUILD): dict(
                private_route, score_channel_id='bad')}})

    def test_discord_py_enforces_supplied_nonce(self):
        from discord.http import handle_message_parameters

        with handle_message_parameters(content='test', nonce=1571184986541789367) as params:
            self.assertEqual(params.payload['nonce'], '1571184986541789367')
            self.assertIs(params.payload['enforce_nonce'], True)

    def test_followup_is_next_day_even_for_early_final(self):
        final = datetime(2026, 11, 15, 9, 50, tzinfo=timezone.utc).timestamp()
        due = datetime.fromtimestamp(followup_due_at(final), timezone.utc)
        self.assertEqual(due, datetime(2026, 11, 16, 10, tzinfo=timezone.utc))

    def test_strict_source_and_goal_parser(self):
        validate_matchday_config(CONFIG)
        now = time.time()
        body = '**Kosovo** `0 — 1` **Israel**\nGOAL!\n 72\' Israel Player Normal Goal'
        pulse = parse_match_event(message(1571184986541789367, body, now=now), CONFIG, now)
        self.assertEqual((pulse.home, pulse.away, pulse.score, pulse.kind),
                         ('Kosovo', 'Israel', '0–1', 'goal'))
        self.assertIn('Kosovo vs Israel', prompt_text(pulse))
        self.assertIn('0–1', prompt_text(pulse))
        self.assertIsNone(parse_match_event(message(1, body, author=2, now=now), CONFIG, now))
        self.assertIsNone(parse_match_event(message(1, body, channel=3, now=now), CONFIG, now))
        self.assertIsNone(parse_match_event(message(1, body, now=now-400), CONFIG, now))

    def test_var_disallowed_goal_corrects_a_posted_score_once(self):
        now = time.time()
        goal = unify_message(1571630123386409092, "[53'] ⚽️ GOAAAAAAAAAAL!",
                             'A. Guler (Turkey)\nFrance 1 - 1 Turkey', now)
        correction = unify_message(1571634149775769661, "[53'] VAR REVIEW",
                                   'Goal Disallowed\nArda Güler (Turkey)\n'
                                   'Overturned · on-field call: Goal confirmed\n'
                                   'France 1 - 0 Turkey', now)
        pulse = parse_match_event(correction, UNIFY_CONFIG, now)
        self.assertEqual((pulse.kind, pulse.score), ('correction', '1–0'))
        self.assertIn('goal disallowed', prompt_text(pulse))
        with tempfile.TemporaryDirectory() as directory:
            store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            self.assertTrue(store.claim(goal.id, parse_match_event(goal, UNIFY_CONFIG, now), now))
            self.assertTrue(store.claim(correction.id, pulse, now + 1))
            repeat = unify_message(correction.id + 1, "[53'] VAR REVIEW",
                                   'Goal Disallowed\nFrance 1 - 0 Turkey', now)
            self.assertFalse(store.claim(repeat.id, parse_match_event(repeat, UNIFY_CONFIG, now), now + 2))
            later = unify_message(correction.id + 2, "[76'] ⚽️ GOAAAAAAAAAAL!",
                                  'France 2 - 0 Turkey', now)
            self.assertTrue(store.claim(later.id, parse_match_event(later, UNIFY_CONFIG, now), now + 3))

    def test_cooldown_and_single_final(self):
        now = time.time()
        kickoff = parse_match_event(message(1571184986541789366, 'Kosovo 0 — 0 Israel\nMatch Started', now=now), CONFIG, now)
        goal = parse_match_event(message(1571184986541789367, 'Kosovo 1 — 0 Israel\nGoal!', now=now), CONFIG, now)
        next_goal = parse_match_event(message(1571184986541789369, 'Kosovo 2 — 0 Israel\nGoal!', now=now), CONFIG, now)
        half_time = parse_match_event(message(1571184986541789370, 'Kosovo 2 — 0 Israel\nHalf Time', now=now), CONFIG, now)
        final = parse_match_event(message(1571184986541789372, 'Kosovo 2 — 0 Israel\nFULL-TIME!', now=now), CONFIG, now)
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

    def test_pending_delivery_survives_restart_and_new_event_supersedes_it(self):
        now = time.time()
        first_id, second_id = 1571184986541789367, 1571184986541789369
        first = parse_match_event(message(first_id, 'Kosovo 1 — 0 Israel\nGoal!', now=now), CONFIG, now)
        second = parse_match_event(message(second_id, 'Kosovo 2 — 0 Israel\nGoal!', now=now), CONFIG, now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pulse.sqlite3'
            store = MatchPulseStore(path)
            self.assertTrue(store.claim(first_id, first, now))
            restarted = MatchPulseStore(path)
            self.assertEqual([mid for mid, _, _ in restarted.due_deliveries(now + 16)[0]], [first_id])
            self.assertTrue(restarted.claim(second_id, second, now + 20))
            self.assertEqual([mid for mid, _, _ in restarted.due_deliveries(now + 40)[0]], [second_id])
            restarted.delivery_sent(second_id, 1571184986541789380)
            self.assertEqual(restarted.due_deliveries(now + 50)[0], [])

    def test_unconfirmed_delivery_stops_retrying_after_nonce_window(self):
        now = time.time()
        source_id = 1571184986541789367
        pulse = parse_match_event(message(source_id, 'Kosovo 1 — 0 Israel\nGoal!', now=now), CONFIG, now)
        with tempfile.TemporaryDirectory() as directory:
            store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            self.assertTrue(store.claim(source_id, pulse, now))
            pending, expired = store.due_deliveries(now + 121)
            self.assertEqual((pending, expired), ([], [source_id]))
            self.assertEqual(store.due_deliveries(now + 150), ([], []))
            with closing(sqlite3.connect(store.path)) as db:
                status = db.execute('SELECT status FROM match_pulse_delivery WHERE source_message_id=?',
                                    (str(source_id),)).fetchone()[0]
            self.assertEqual(status, 'unknown')

    def test_followup_waits_for_latest_confirmed_final_score(self):
        now = time.time()
        final = MatchPulse(TEST_GUILD, 'kosovo|israel', 'Kosovo', 'Israel', '2–0',
            'final', 'https://discord.com/channels/1/2/3', SOURCE, SOURCE, SOURCE)
        corrected = MatchPulse(TEST_GUILD, final.match_key, final.home, final.away,
            '1–0', 'correction', final.source_url, SOURCE, SOURCE, SOURCE)
        other = MatchPulse(TEST_GUILD, 'england|france', 'England', 'France', '1–1',
            'final', final.source_url, SOURCE, SOURCE, SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            due = followup_due_at(now) + 1
            store.queue_followup(final, now)
            self.assertEqual(store.due_followups(due), [])
            self.assertTrue(store.claim(1571184986541789372, final, now))
            key, ready_final = store.due_followups(due)[0]
            self.assertEqual(ready_final.score, '2–0')
            self.assertTrue(store.claim(1571184986541789373, corrected, now + 1))
            self.assertEqual(store.due_followups(due), [])
            self.assertFalse(store.reserve_followup(key))
            self.assertTrue(store.claim(1571184986541789374, other, now + 2))
            store.queue_followup(other, now + 2)
            self.assertEqual([pulse.match_key for _, pulse in store.due_followups(due)],
                             [other.match_key])
            updated_final = MatchPulse(TEST_GUILD, final.match_key, final.home, final.away,
                corrected.score, 'final', final.source_url, SOURCE, SOURCE, SOURCE)
            self.assertTrue(store.claim(1571184986541789375, updated_final, now + 3))
            store.queue_followup(updated_final, now + 3)
            self.assertEqual({pulse.match_key: pulse.score for _, pulse in
                              store.due_followups(due)},
                             {final.match_key: '1–0', other.match_key: '1–1'})

    def test_ignores_status_and_configuration_messages(self):
        now = time.time()
        self.assertIsNone(parse_match_event(message(1, 'Live Subscription Active\nMatch\n**Kosovo** vs **Israel**\nPush Notifications\nGoals · Half Time', now=now), CONFIG, now))
        self.assertIsNone(parse_match_event(message(2, 'Match status changed → Second Half\nKosovo 0 — 0 Israel', now=now), CONFIG, now))
        finished = parse_match_event(message(3, '🏁 FULL-TIME!\nManchester City  `3 — 0`  Arsenal\nResult\nManchester City wins', now=now), CONFIG, now)
        self.assertEqual((finished.kind, finished.score), ('final', '3–0'))
        with self.assertRaises(ValueError):
            validate_matchday_config({'enabled': True, 'routes': {'999999999999999999': CONFIG['routes'][str(TEST_GUILD)]}})


class ChatIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_overdue_followup_alerts_ops_once_without_public_repost(self):
        from chat_service import ChatClient, OFFICIAL_GUILD

        ops_id = 1568699207022285040
        with tempfile.TemporaryDirectory() as directory:
            config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(OFFICIAL_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': {'enabled': True, 'routes': {str(OFFICIAL_GUILD):
                    dict(CONFIG['routes'][str(TEST_GUILD)])},
                    'state_path': str(Path(directory) / 'pulse.sqlite3')}}
            client = ChatClient(config)
            client.focus_config = {'ops_channel_id': str(ops_id)}
            pulse = MatchPulse(OFFICIAL_GUILD, 'spain-england', 'Spain', 'England', '2–3',
                'final', 'https://discord.com/channels/1/2/3', SOURCE, SOURCE, SOURCE)
            now = time.time()
            for index in range(4):
                client.matchday_store.queue_followup(MatchPulse(
                    TEST_GUILD, 'old-test-{}'.format(index), 'A', 'B', '1–0', 'final',
                    pulse.source_url, SOURCE, SOURCE, SOURCE), now - 86400)
            client.matchday_store.queue_followup(pulse, now)
            with closing(sqlite3.connect(client.matchday_store.path)) as db:
                due = db.execute('SELECT due_at FROM match_followup WHERE event_key LIKE ?',
                                 ('{}:%'.format(OFFICIAL_GUILD),)).fetchone()[0]
            ops = SimpleNamespace(guild=SimpleNamespace(id=OFFICIAL_GUILD),
                                  send=AsyncMock(return_value=SimpleNamespace(id=456)))
            client.get_channel = lambda channel_id: ops if channel_id == ops_id else None
            await client.alert_overdue_followups(due + 599)
            ops.send.assert_not_awaited()
            await client.alert_overdue_followups(due + 600)
            client.matchday_store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            await client.alert_overdue_followups(due + 1200)
            ops.send.assert_awaited_once()
            self.assertIn('overdue or unconfirmed', ops.send.await_args.args[0])
            self.assertEqual(client.matchday_store.overdue_followups(due + 1200, OFFICIAL_GUILD), [])
            sent_pulse = MatchPulse(OFFICIAL_GUILD, 'other-match', 'A', 'B', '1–0',
                'final', pulse.source_url, SOURCE, SOURCE, SOURCE)
            client.matchday_store.queue_followup(sent_pulse, now)
            self.assertTrue(client.matchday_store.claim(1571184986541789388,
                sent_pulse, now))
            with closing(sqlite3.connect(client.matchday_store.path)) as db:
                sent_key = db.execute("SELECT event_key FROM match_followup WHERE status='pending' "
                                      "AND event_key LIKE '%other-match%'").fetchone()[0]
            self.assertTrue(client.matchday_store.reserve_followup(sent_key))
            client.matchday_store.finish_followup(sent_key, 789)
            await client.alert_overdue_followups(due + 1200)
            ops.send.assert_awaited_once()
            await client.close()

    async def test_match_locks_use_the_client_running_loop(self):
        from chat_service import ChatClient

        config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
            'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}}}
        client = ChatClient(config)
        old_loop = asyncio.new_event_loop()
        try:
            # Reproduce the lock state after a previous loop has seen contention.
            client.pulse_lock._loop = old_loop
            client.focus_lock._loop = old_loop
            with patch.object(client, 'add_commands', new_callable=AsyncMock), \
                    patch.object(client.tree, 'sync', new_callable=AsyncMock):
                await client.setup_hook()
            for lock in (client.pulse_lock, client.focus_lock):
                await lock.acquire()
                waiter = asyncio.create_task(lock.acquire())
                try:
                    await asyncio.sleep(0)
                    lock.release()
                    await waiter
                finally:
                    if lock.locked():
                        lock.release()
                    if not waiter.done():
                        waiter.cancel()
        finally:
            await client.close()
            old_loop.close()

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

    async def test_unify_event_posts_one_discussion_card(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            chat_config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': dict(CONFIG, state_path=str(Path(directory) / 'pulse.sqlite3'))}
            client = ChatClient(chat_config)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=TEST_GUILD), send=AsyncMock())
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            now = time.time()
            event = message(1571184986541789367, 'Kosovo 1 — 0 Israel\nGOAL!', now=now)
            client.matchday_store = MatchPulseStore(Path(directory) / 'pulse.sqlite3')
            await client.on_message(event)
            await client.on_message(event)
            self.assertEqual(channel.send.await_count, 1)
            self.assertIn('Kosovo vs Israel', channel.send.await_args.kwargs['embed'].description)
            self.assertEqual(len(channel.send.await_args.kwargs['view'].children), 3)
            self.assertEqual(channel.send.await_args.kwargs['nonce'], event.id)
            self.assertIn('UnifyFootball public update:', client.history[SOURCE][-1][1])
            await client.close()

    async def test_unify_event_posts_one_discussion_card_with_source_link(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            chat_config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': dict(UNIFY_CONFIG, state_path=str(Path(directory) / 'pulse.sqlite3'))}
            client = ChatClient(chat_config)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=TEST_GUILD), send=AsyncMock())
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            event = unify_message(1571546825184256152, "[67'] ⚽️ GOAAAAAAAAAAL!",
                                  'Cyprus  1 - 3  Montenegro')
            await client.on_message(event)
            await client.on_message(event)
            self.assertEqual(channel.send.await_count, 1)
            sent = channel.send.await_args.kwargs
            self.assertIn('Cyprus vs Montenegro', sent['embed'].description)
            self.assertIn('UnifyFootball', sent['embed'].footer.text)
            self.assertEqual(sent['view'].children[0].label, 'UnifyFootball update')
            self.assertEqual(sent['view'].children[0].url, event.jump_url)
            self.assertIn('UnifyFootball public update:', client.history[SOURCE][-1][1])
            await client.close()

    async def test_retry_uses_same_discord_nonce(self):
        import discord
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            chat_config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': dict(CONFIG, state_path=str(Path(directory) / 'pulse.sqlite3'))}
            client = ChatClient(chat_config)
            event = message(1571184986541789367, 'Kosovo 1 — 0 Israel\nGoal!')
            failed = discord.HTTPException(SimpleNamespace(status=503, reason='Unavailable'), 'temporary')
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=TEST_GUILD),
                send=AsyncMock(side_effect=[failed, SimpleNamespace(id=1571184986541789380)]))
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            with patch('chat_service.asyncio.sleep', new_callable=AsyncMock):
                await client.on_message(event)
            await client.on_message(event)
            self.assertEqual(channel.send.await_count, 2)
            self.assertEqual([call.kwargs['nonce'] for call in channel.send.await_args_list],
                             [event.id, event.id])
            await client.close()

    async def test_failed_send_is_retried_from_durable_delivery(self):
        import discord
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pulse.sqlite3'
            chat_config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(TEST_GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': dict(CONFIG, state_path=str(path))}
            client = ChatClient(chat_config)
            event = message(1571184986541789367, 'Kosovo 1 — 0 Israel\nGoal!')
            failed = discord.HTTPException(SimpleNamespace(status=503, reason='Unavailable'), 'temporary')
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=TEST_GUILD),
                send=AsyncMock(side_effect=[failed, failed, failed,
                                            SimpleNamespace(id=1571184986541789380)]))
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            with patch('chat_service.asyncio.sleep', new_callable=AsyncMock):
                await client.on_message(event)
            self.assertEqual(channel.send.await_count, 3)
            client.matchday_store = MatchPulseStore(path)
            await client.send_pending_pulses_due(time.time() + 31)
            self.assertEqual(channel.send.await_count, 4)
            self.assertTrue(all(call.kwargs['nonce'] == event.id
                                for call in channel.send.await_args_list))
            self.assertEqual(client.matchday_store.due_deliveries(time.time() + 40)[0], [])
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
            event = message(1571184986541789372, 'Kosovo 2 — 0 Israel\nFULL-TIME!', now=now)
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
