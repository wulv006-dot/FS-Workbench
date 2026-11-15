import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from matchday_focus import (FocusStore, is_empty_daily_card, parse_choice,
                            parse_daily_card, validate_config)


GUILD = 1565922092518613064
CHANNEL = 1568260661010497627
SOURCE = 1571528702620340237
NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone.utc)
ROUTE = {'provider': 'unify_football', 'source_channel_id': CHANNEL,
         'discussion_channel_id': CHANNEL, 'players_channel_id': CHANNEL,
         'coins_channel_id': CHANNEL}
ENGAGEMENT = {'enabled': True, 'routes': {str(GUILD): ROUTE}}


def card(now=NOW, author=1332364544869142538):
    embed = SimpleNamespace(
        title="Today's matches in Nations League - League C",
        description='November 15, 2026 (Europe/London)',
        fields=[SimpleNamespace(name='Nations League - League C',
                                value='Belarus   vs   Albania       17:00\n'
                                      'Finland   vs   San Marino       17:00'),
                SimpleNamespace(name='Nations League - League A',
                                value='France   vs   Turkey       19:45\n'
                                      'Spain   vs   England       19:45')])
    return SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=GUILD),
                           channel=SimpleNamespace(id=CHANNEL),
                           author=SimpleNamespace(id=author, bot=True),
                           webhook_id=None, embeds=[embed], content='',
                           created_at=now,
                           jump_url='https://discord.com/channels/{}/{}/{}'.format(
                               GUILD, CHANNEL, SOURCE))


def v2_card():
    message = card()
    message.embeds = []
    payload = {'type': 17, 'components': [
        {'type': 9, 'components': [{'type': 10, 'content':
            "## 📅 Today's matches in `Nations League - League C`\n"
            '-# **_November 15, 2026 (Europe/London)_**'}]},
        {'type': 10, 'content':
            '### 🏆 `Nations League - League C`\n'
            '- **__Belarus__** vs **__Albania__** _🕒 `17:00`_\n'
            '- **__Finland__** vs **__San Marino__** _🕒 `17:00`_\n'
            '### 🏆 `Nations League - League A`\n'
            '- **__France__** vs **__Turkey__** _🕒 `19:45`_\n'
            '- **__Spain__** vs **__England__** _🕒 `19:45`_'}]}
    message.components = [SimpleNamespace(to_dict=lambda: payload)]
    return message


class FocusTests(unittest.TestCase):
    def test_only_fresh_unify_no_match_card_in_source_is_empty(self):
        message = card()
        message.embeds = [SimpleNamespace(
            title='😴 No matches today in `ENGLAND: Premier League`',
            description='The football gods are taking a break today — no matches lined up in '
                        '**`ENGLAND: Premier League`**!')]
        message.components = []
        self.assertTrue(is_empty_daily_card(message, ROUTE, NOW))
        self.assertFalse(is_empty_daily_card(message, ROUTE, NOW + dt.timedelta(days=2)))
        message.channel.id = CHANNEL + 1
        self.assertFalse(is_empty_daily_card(message, ROUTE, NOW))
        message.channel.id = CHANNEL
        message.author.id = 123
        self.assertFalse(is_empty_daily_card(message, ROUTE, NOW))
        message.author.id = 1332364544869142538
        message.embeds[0].title = "Today's matches in Premier League"
        self.assertFalse(is_empty_daily_card(message, ROUTE, NOW))

    def test_parse_real_daily_card_shape_and_reject_wrong_source_or_day(self):
        fixtures = parse_daily_card(card(), ROUTE, NOW)
        self.assertEqual([(f.home, f.away, f.competition) for f in fixtures], [
            ('Belarus', 'Albania', 'Nations League - League C'),
            ('Finland', 'San Marino', 'Nations League - League C'),
            ('France', 'Turkey', 'Nations League - League A'),
            ('Spain', 'England', 'Nations League - League A')])
        self.assertEqual(fixtures[-1].kickoff.isoformat(), '2026-11-15T19:45:00+00:00')
        self.assertEqual(parse_daily_card(card(author=123), ROUTE, NOW), [])
        self.assertEqual(parse_daily_card(card(), ROUTE, NOW + dt.timedelta(days=1)), [])

    def test_parse_live_components_v2_daily_card(self):
        fixtures = parse_daily_card(v2_card(), ROUTE, NOW)
        self.assertEqual([(f.home, f.away, f.competition) for f in fixtures], [
            ('Belarus', 'Albania', 'Nations League - League C'),
            ('Finland', 'San Marino', 'Nations League - League C'),
            ('France', 'Turkey', 'Nations League - League A'),
            ('Spain', 'England', 'Nations League - League A')])
        self.assertEqual(parse_daily_card(v2_card(), ROUTE, NOW + dt.timedelta(days=1)), [])

    def test_daily_card_keeps_each_league_heading(self):
        message = card()
        message.embeds[0].fields = [
            SimpleNamespace(name='Premier League', value='Arsenal vs Chelsea 15:00'),
            SimpleNamespace(name='La Liga EA SPORTS', value='Real Madrid vs Barcelona 20:00'),
            SimpleNamespace(name='Bundesliga', value='Bayern vs Dortmund 17:30'),
            SimpleNamespace(name='Serie A', value='Inter vs Milan 19:45'),
            SimpleNamespace(name='Ligue 1', value='PSG vs Marseille 20:00'),
        ]
        fixtures = parse_daily_card(message, ROUTE, NOW)
        self.assertEqual([f.competition for f in fixtures], [
            'Premier League', 'La Liga EA SPORTS', 'Bundesliga', 'Serie A', 'Ligue 1'])

        message = v2_card()
        message.components[0] = SimpleNamespace(to_dict=lambda: {'type': 17, 'components': [
            {'type': 10, 'content': "## Today's matches\nNovember 15, 2026 (Europe/London)"},
            {'type': 10, 'content': '### 🏆 `La Liga EA SPORTS`\n'
             '- **__Real Madrid__** vs **__Barcelona__** _🕒 `20:00`_\n'
             '### 🏆 `Bundesliga`\n'
             '- **__Bayern__** vs **__Dortmund__** _🕒 `17:30`_'},
        ]})
        fixtures = parse_daily_card(message, ROUTE, NOW)
        self.assertEqual([f.competition for f in fixtures], ['La Liga EA SPORTS', 'Bundesliga'])

    def test_choice_is_one_number_or_none_without_extra_claims(self):
        self.assertEqual(parse_choice('4', 4), 3)
        self.assertEqual(parse_choice('4|Spain or England: who owns midfield tonight?', 4), 3)
        self.assertEqual(parse_choice("N|3|Will Belgium's defence hold up against Italy?", 4), 2)
        self.assertIsNone(parse_choice('NONE', 4))
        with self.assertRaises(ValueError):
            parse_choice('5', 4)
        with self.assertRaises(ValueError):
            parse_choice('4|@everyone who wins?', 4)

    def test_weekly_cap_and_daily_dedupe_survive_restart(self):
        fixtures = parse_daily_card(card(), ROUTE, NOW)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'focus.sqlite3'
            store = FocusStore(path)
            day = NOW.date() - dt.timedelta(days=6)  # Monday of this London week.
            self.assertTrue(store.reserve(GUILD, day, SOURCE, fixtures[-1],
                                          'Who wins this one?', 2))
            self.assertFalse(store.may_select(GUILD, day, 2))
            store.finish(GUILD, day, 1571600000000000000)
            again = FocusStore(path)
            self.assertTrue(again.selected(GUILD, fixtures[-1].key,
                                           fixtures[-1].kickoff.timestamp()))
            self.assertFalse(again.selected(GUILD, fixtures[0].key,
                                            fixtures[-1].kickoff.timestamp()))
            self.assertTrue(again.reserve(GUILD, day + dt.timedelta(days=1), SOURCE + 1,
                                          fixtures[0], 'Who wins this one?', 2))
            self.assertFalse(again.may_select(GUILD, day + dt.timedelta(days=2), 2))

    def test_config_is_explicit_subset_of_matchday_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            good = {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3')}
            validate_config(good, ENGAGEMENT)
            with self.assertRaises(ValueError):
                validate_config(dict(good, guild_ids=['999999999999999999']), ENGAGEMENT)


class FocusIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_clears_existing_empty_card_even_after_focus_decision(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3')},
            }
            client = ChatClient(config)
            client.focus_store.may_select = lambda *_: False
            message = card()
            message.embeds = [SimpleNamespace(
                title='😴 No matches today in `ENGLAND: Premier League`',
                description='No matches lined up in `ENGLAND: Premier League`')]
            message.components = []
            message.delete = AsyncMock()
            async def history(limit):
                yield message
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                                      history=history)
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            with patch('chat_service.discord.utils.utcnow', return_value=NOW), patch.object(
                    client, 'setup_matchday_intro', new_callable=AsyncMock):
                await client.on_ready()
            message.delete.assert_awaited_once()
            await client.close()

    async def test_empty_unify_card_is_deleted_without_hosting_or_touching_other_bot(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3')},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock()
            message = card()
            message.embeds = [SimpleNamespace(
                title='😴 No matches today in `ENGLAND: Premier League`',
                description='The football gods are taking a break today — no matches lined up in '
                            '**`ENGLAND: Premier League`**!')]
            message.components = []
            message.delete = AsyncMock()
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(message)
            message.delete.assert_awaited_once()
            client.brain.select_matchday.assert_not_awaited()

            message.author.id = 123
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(message)
            message.delete.assert_awaited_once()
            await client.close()

    async def test_ai_selector_sends_only_verified_fixture_candidates(self):
        from chat_brain import ChatBrain

        fixtures = parse_daily_card(card(), ROUTE, NOW)
        with patch.dict('os.environ', {'ARK_API_KEY': 'synthetic-test-key'}):
            brain = ChatBrain({})
        brain._ask = AsyncMock(return_value='4')
        answer = await brain.select_matchday(fixtures)
        self.assertEqual(parse_choice(answer, len(fixtures)), 3)
        prompt = brain._ask.await_args.args[1]
        self.assertIn('Spain vs England', prompt[1]['content'])
        self.assertIn('never fill a quota', prompt[0]['content'])

    async def test_restart_recovers_today_card_without_duplicate_post(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3')},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(return_value='4')
            empty = card()
            empty.id = SOURCE - 1
            empty.embeds = [SimpleNamespace(
                title='😴 No matches today in `ENGLAND: Premier League`',
                description='No matches lined up in `ENGLAND: Premier League`')]
            empty.components = []
            empty.delete = AsyncMock()
            async def history(limit):
                yield v2_card()
                yield empty
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                history=history, send=AsyncMock(return_value=SimpleNamespace(
                    id=1571600000000000000)))
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            with patch('chat_service.discord.utils.utcnow', return_value=NOW), patch.object(
                    client, 'setup_matchday_intro', new_callable=AsyncMock):
                await client.on_ready()
                empty.delete.assert_awaited_once()
                await client.on_ready()
            self.assertEqual(channel.send.await_count, 1)
            await client.close()

    async def test_recovery_checks_another_league_after_a_skipped_card(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3')},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(side_effect=['NONE', '4'])
            newer = card()
            newer.id = SOURCE + 1
            async def history(limit):
                yield newer
                yield card()
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                history=history, send=AsyncMock(return_value=SimpleNamespace(
                    id=1571600000000000000)))
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            with patch('chat_service.discord.utils.utcnow', return_value=NOW), patch.object(
                    client, 'setup_matchday_intro', new_callable=AsyncMock):
                await client.on_ready()
            self.assertEqual(client.brain.select_matchday.await_count, 2)
            self.assertEqual(channel.send.await_count, 1)
            self.assertTrue(client.focus_store.reviewed(GUILD, SOURCE + 1))
            await client.close()

    async def test_quiet_day_has_no_public_post_or_repeat_model_call(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3')},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(return_value='NONE')
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                                      send=AsyncMock())
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(card())
                await client.on_message(card())
            self.assertEqual(client.brain.select_matchday.await_count, 1)
            channel.send.assert_not_awaited()
            self.assertIsNone(client.focus_retry_task)
            self.assertTrue(client.focus_store.may_select(GUILD, NOW.date(), 2))
            self.assertTrue(client.focus_store.reviewed(GUILD, SOURCE))
            client.brain.select_matchday.return_value = '4'
            next_card = card()
            next_card.id = SOURCE + 1
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(next_card)
            self.assertEqual(client.brain.select_matchday.await_count, 2)
            self.assertEqual(channel.send.await_count, 1)
            await client.close()

    async def test_selector_failure_retries_once_from_current_daily_card(self):
        from chat_brain import ChatBrainError
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3')},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(
                side_effect=[ChatBrainError('temporary outage'), '4'])
            message = card()
            async def history(limit):
                yield message
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                history=history, send=AsyncMock(return_value=SimpleNamespace(
                    id=1571600000000000000)))
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            with patch('chat_service.discord.utils.utcnow', return_value=NOW), patch(
                    'chat_service.asyncio.sleep', new_callable=AsyncMock):
                await client.on_message(message)
                await client.focus_retry_task
            self.assertEqual(client.brain.select_matchday.await_count, 2)
            channel.send.assert_awaited_once()
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(message)
            self.assertEqual(client.brain.select_matchday.await_count, 2)
            await client.close()

    async def test_daily_card_posts_once_and_only_selected_live_match_is_hosted(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            score_channel = CHANNEL + 999
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    routes={str(GUILD): dict(ROUTE, score_channel_id=score_channel)},
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3'),
                    'weekly_limit': 2},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(return_value='4')
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                send=AsyncMock(return_value=SimpleNamespace(id=1571600000000000000)))
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(card())
                await client.on_message(card())
            self.assertEqual(channel.send.await_count, 1)
            self.assertEqual(client.brain.select_matchday.await_count, 1)
            self.assertIn('Spain vs England', channel.send.await_args.kwargs['embed'].description)
            self.assertIn('Who are you backing: Spain or England?',
                          channel.send.await_args.kwargs['embed'].description)
            self.assertEqual(channel.send.await_args.kwargs['nonce'], SOURCE)
            event_at = (NOW + dt.timedelta(hours=8)).timestamp()
            def goal(mid, home, away, channel_id=score_channel):
                return SimpleNamespace(id=mid, guild=SimpleNamespace(id=GUILD),
                    channel=SimpleNamespace(id=channel_id),
                    author=SimpleNamespace(id=1332364544869142538, bot=True),
                    type=SimpleNamespace(value=0), webhook_id=None,
                    interaction_metadata=None, content='', embeds=[SimpleNamespace(
                        title="[67'] ⚽️ GOAAAAAAAAAAL!",
                        description='{}  1 - 0  {}'.format(home, away), fields=[])],
                    created_at=dt.datetime.fromtimestamp(event_at, dt.timezone.utc),
                    jump_url='https://discord.com/channels/{}/{}/{}'.format(
                        GUILD, channel_id, mid))
            with patch('chat_service.time.time', return_value=event_at):
                await client.on_message(goal(SOURCE + 3, 'Spain', 'England', CHANNEL))
                self.assertEqual(channel.send.await_count, 1)
                await client.on_message(goal(SOURCE + 1, 'France', 'Turkey'))
                self.assertEqual(channel.send.await_count, 1)
                await client.on_message(goal(SOURCE + 2, 'Spain', 'England'))
                self.assertEqual(channel.send.await_count, 2)
            self.assertIn('Spain vs England', channel.send.await_args.kwargs['embed'].description)
            button = channel.send.await_args.kwargs['view'].children[0]
            self.assertEqual(button.label, 'UnifyFootball fixture')
            self.assertEqual(button.url, card().jump_url)
            await client.close()


if __name__ == '__main__':
    unittest.main()
