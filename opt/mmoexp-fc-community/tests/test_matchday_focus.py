import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from matchday_focus import (DailyFixture, FocusStore, club_fixtures, is_empty_daily_card, parse_choice,
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

    def test_my_club_uses_today_only_and_exact_team_aliases(self):
        evening = NOW + dt.timedelta(hours=8)
        self.assertEqual(parse_daily_card(card(), ROUTE, evening), [])
        self.assertEqual(len(parse_daily_card(card(), ROUTE, evening,
                                              include_started=True)), 4)
        self.assertEqual(parse_daily_card(card(), ROUTE, evening + dt.timedelta(days=1),
                                          include_started=True), [])
        fixtures = [
            DailyFixture('Manchester City', 'Chelsea', 'Premier League', NOW, 'https://example.com/1'),
            DailyFixture('Inter Milan', 'Juventus', 'Serie A', NOW, 'https://example.com/2'),
            DailyFixture('Paris Saint-Germain', 'Lyon', 'Ligue 1', NOW, 'https://example.com/3'),
        ]
        self.assertEqual(club_fixtures('man_city', fixtures), fixtures[:1])
        self.assertEqual(club_fixtures('milan', fixtures), [])
        self.assertEqual(club_fixtures('inter', fixtures), fixtures[1:2])
        self.assertEqual(club_fixtures('psg', fixtures), fixtures[2:])

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

    def test_daily_source_heartbeat_survives_restart_and_alerts_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'focus.sqlite3'
            store = FocusStore(path)
            store.record_daily_source(GUILD, NOW.date())
            self.assertFalse(FocusStore(path).claim_missing_source(GUILD, NOW.date()))
            tomorrow = NOW.date() + dt.timedelta(days=1)
            self.assertTrue(store.claim_missing_source(GUILD, tomorrow))
            self.assertFalse(FocusStore(path).claim_missing_source(GUILD, tomorrow))
            store.finish_missing_source(GUILD, tomorrow, 12345)
            store.record_daily_source(GUILD, tomorrow)
            self.assertFalse(FocusStore(path).claim_missing_source(GUILD, tomorrow))

    def test_config_is_explicit_subset_of_matchday_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            good = {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3'), 'settle_seconds': 0}
            validate_config(good, ENGAGEMENT)
            with self.assertRaises(ValueError):
                validate_config(dict(good, guild_ids=['999999999999999999']), ENGAGEMENT)
            with self.assertRaises(ValueError):
                validate_config(dict(good, ops_channel_id='not-a-channel'), ENGAGEMENT)
            validate_config(dict(good, game_chat_channels={str(GUILD): str(CHANNEL)}),
                            ENGAGEMENT)
            with self.assertRaises(ValueError):
                validate_config(dict(good, game_chat_channels={'999': str(CHANNEL)}),
                                ENGAGEMENT)

    def test_game_chat_invite_is_due_only_before_kickoff_and_once(self):
        fixture = DailyFixture('Spain', 'England', 'Nations League',
                               NOW + dt.timedelta(minutes=90), 'https://example.com')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'focus.sqlite3'
            store = FocusStore(path)
            self.assertEqual(store.due_game_chat_invites(GUILD, NOW.timestamp()), [])
            self.assertTrue(store.reserve(GUILD, NOW.date(), SOURCE, fixture,
                                          'Who wins?', 2))
            store.finish(GUILD, NOW.date(), SOURCE + 1)
            self.assertEqual(store.due_game_chat_invites(GUILD, NOW.timestamp()), [])
            due = NOW.timestamp() + 1800
            row, = store.due_game_chat_invites(GUILD, due)
            self.assertTrue(store.reserve_game_chat_invite(row, due))
            self.assertFalse(FocusStore(path).reserve_game_chat_invite(row, due))
            store.finish_game_chat_invite(row, SOURCE + 2)
            self.assertEqual(FocusStore(path).due_game_chat_invites(GUILD, due), [])
            self.assertEqual(store.due_game_chat_invites(GUILD,
                             fixture.kickoff.timestamp() + 1), [])


class FocusIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_match_invites_fc_chat_once_with_both_links(self):
        from chat_service import ChatClient

        fixture = DailyFixture('Spain', 'England', 'Nations League',
                               NOW + dt.timedelta(minutes=90),
                               'https://discord.com/channels/{}/{}/{}'.format(
                                   GUILD, CHANNEL, SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3'),
                    'game_chat_channels': {str(GUILD): str(CHANNEL)}},
            }
            client = ChatClient(config)
            client.focus_store.reserve(GUILD, NOW.date(), SOURCE, fixture, 'Who wins?', 2)
            client.focus_store.finish(GUILD, NOW.date(), SOURCE + 1)
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                send=AsyncMock(return_value=SimpleNamespace(id=SOURCE + 2)))
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            await client.send_game_chat_invites_due(NOW.timestamp())
            channel.send.assert_not_awaited()
            await client.send_game_chat_invites_due(NOW.timestamp() + 1800)
            await client.send_game_chat_invites_due(NOW.timestamp() + 1801)
            channel.send.assert_awaited_once()
            view = channel.send.await_args.kwargs['view']
            self.assertEqual([button.label for button in view.children],
                             ['Predict with Unify', 'Join match chat'])
            self.assertTrue(view.children[0].url.endswith('/' + str(SOURCE)))
            self.assertTrue(view.children[1].url.endswith('/' + str(SOURCE + 1)))
            await client.close()

    async def test_uncertain_invite_result_is_not_reposted(self):
        from chat_service import ChatClient

        fixture = DailyFixture('Spain', 'England', 'Nations League',
                               NOW + dt.timedelta(minutes=90),
                               'https://discord.com/channels/{}/{}/{}'.format(
                                   GUILD, CHANNEL, SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3'),
                    'game_chat_channels': {str(GUILD): str(CHANNEL)}},
            }
            client = ChatClient(config)
            client.focus_store.reserve(GUILD, NOW.date(), SOURCE, fixture, 'Who wins?', 2)
            client.focus_store.finish(GUILD, NOW.date(), SOURCE + 1)
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                                      send=AsyncMock(side_effect=TimeoutError()))
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            due = NOW.timestamp() + 1800
            await client.send_game_chat_invites_due(due)
            await client.send_game_chat_invites_due(due + 60)
            channel.send.assert_awaited_once()
            self.assertEqual(client.focus_store.due_game_chat_invites(GUILD, due), [])
            await client.close()

    async def test_my_club_button_reads_current_role_and_replies_privately(self):
        from chat_service import ChatClient, OFFICIAL_GUILD

        official_route = dict(ROUTE, source_channel_id=1571043454136484082,
                              discussion_channel_id=1571043570268242014)
        config = {
            'chat_bot': {'enabled': True, 'allow_message_content': True,
                         'routes': {str(OFFICIAL_GUILD): {'channels': {
                             str(official_route['discussion_channel_id']): {}}, 'keywords': []}}},
            'matchday_engagement': {'enabled': True,
                'routes': {str(OFFICIAL_GUILD): official_route}},
        }
        with tempfile.TemporaryDirectory() as directory:
            config['matchday_engagement']['state_path'] = str(Path(directory) / 'pulse.sqlite3')
            client = ChatClient(config)
            view = client.build_matchday_intro_view(official_route)
            self.assertTrue(view.is_persistent())
            client.add_view(view)
            button = next(item for item in view.children if item.custom_id == 'fc:matchday:my-club')
            self.assertEqual(len(view.children), 5)

            role_id = 1571600000000000011
            member = SimpleNamespace(id=7, bot=False, roles=[SimpleNamespace(id=role_id)])
            guild = SimpleNamespace(id=OFFICIAL_GUILD,
                                    fetch_member=AsyncMock(return_value=member))
            interaction = SimpleNamespace(guild_id=OFFICIAL_GUILD,
                channel_id=official_route['discussion_channel_id'], guild=guild,
                user=SimpleNamespace(id=7),
                response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            match = DailyFixture('Manchester City', 'Chelsea', 'Premier League', NOW,
                                 'https://discord.com/channels/1041923524601851914/1571043454136484082/123')

            async def history(limit):
                self.assertEqual(limit, 50)
                yield card()

            channel = SimpleNamespace(id=official_route['source_channel_id'],
                                      guild=guild, history=history)
            client.get_channel = lambda channel_id: channel
            club_config = json.dumps({'club_panels': {'guild_id': OFFICIAL_GUILD,
                                      'role_ids': {'man_city': role_id}}})
            with patch('chat_service.Path.read_text', return_value=club_config), \
                    patch('chat_service.discord.utils.utcnow', return_value=NOW), \
                    patch('chat_service.matchday_focus.parse_daily_card', return_value=[match]):
                await button.callback(interaction)
            response = interaction.followup.send.await_args
            self.assertTrue(response.kwargs['ephemeral'])
            self.assertIn('Manchester City vs Chelsea', response.args[0])
            self.assertEqual(response.kwargs['view'].children[0].url, match.source_url)

            member.roles = []
            with patch('chat_service.Path.read_text', return_value=club_config):
                await button.callback(interaction)
            response = interaction.followup.send.await_args
            self.assertIn('Choose one club', response.args[0])
            await client.close()

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
                    'state_path': str(Path(directory) / 'focus.sqlite3'), 'settle_seconds': 0},
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
            self.assertFalse(client.focus_store.claim_missing_source(GUILD, NOW.date()))
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
                    'state_path': str(Path(directory) / 'focus.sqlite3'), 'settle_seconds': 0},
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

    async def test_yesterday_empty_card_does_not_mask_missing_today(self):
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
            message = card(now=NOW - dt.timedelta(hours=13))
            message.embeds = [SimpleNamespace(
                title='😴 No matches today in `ENGLAND: Premier League`',
                description='No matches lined up in `ENGLAND: Premier League`')]
            message.components = []
            message.delete = AsyncMock()
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(message)
            message.delete.assert_awaited_once()
            self.assertTrue(client.focus_store.claim_missing_source(GUILD, NOW.date()))
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
        self.assertIn('Sun 19:45 London / Sun 14:45 New York', prompt[1]['content'])
        self.assertIn('never fill a quota', prompt[0]['content'])

    def test_choice_accepts_a_match_beyond_the_first_card(self):
        self.assertEqual(parse_choice('27', 35), 26)
        with self.assertRaises(ValueError):
            parse_choice('36', 35)

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
                    'state_path': str(Path(directory) / 'focus.sqlite3'), 'settle_seconds': 0},
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
            self.assertFalse(client.focus_store.claim_missing_source(GUILD, NOW.date()))
            await client.close()

    async def test_missing_daily_card_alerts_private_ops_once_after_ten_london(self):
        from chat_service import ChatClient, OFFICIAL_GUILD

        ops_id = 1568699207022285040
        route = dict(ROUTE)
        config = {
            'chat_bot': {'enabled': True, 'allow_message_content': True,
                         'routes': {str(OFFICIAL_GUILD): {'channels': {str(CHANNEL): {}},
                                                          'keywords': []}}},
            'matchday_engagement': {'enabled': True, 'routes': {str(OFFICIAL_GUILD): route}},
            'matchday_focus': {'enabled': True, 'guild_ids': [str(OFFICIAL_GUILD)],
                'state_path': '', 'ops_channel_id': str(ops_id)},
        }
        with tempfile.TemporaryDirectory() as directory:
            config['matchday_focus']['state_path'] = str(Path(directory) / 'focus.sqlite3')
            config['matchday_engagement']['state_path'] = str(Path(directory) / 'pulse.sqlite3')
            client = ChatClient(config)
            ops = SimpleNamespace(id=ops_id, guild=SimpleNamespace(id=OFFICIAL_GUILD),
                                  send=AsyncMock(return_value=SimpleNamespace(id=12345)))
            client.get_channel = lambda channel_id: ops if channel_id == ops_id else None
            await client.alert_missing_daily_card(NOW.replace(hour=9))
            ops.send.assert_not_awaited()
            await client.alert_missing_daily_card(NOW)
            await client.alert_missing_daily_card(NOW + dt.timedelta(minutes=1))
            ops.send.assert_awaited_once()
            self.assertIn('No UnifyFootball daily fixture card', ops.send.await_args.args[0])
            self.assertFalse(client.focus_store.claim_missing_source(OFFICIAL_GUILD, NOW.date()))
            await client.close()

    async def test_pulse_worker_error_does_not_skip_daily_source_check(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
            }
            client = ChatClient(config)
            client.focus_recovered.set()
            client.wait_until_ready = AsyncMock()
            is_closed = client.is_closed
            client.is_closed = iter([False, True]).__next__
            client.send_pending_pulses_due = AsyncMock(side_effect=RuntimeError('pulse failed'))
            client.alert_missing_daily_card = AsyncMock()
            client.alert_overdue_followups = AsyncMock()
            with patch('chat_service.asyncio.sleep', new_callable=AsyncMock):
                await client.run_followups()
            client.alert_missing_daily_card.assert_awaited_once()
            client.alert_overdue_followups.assert_awaited_once()
            client.is_closed = is_closed
            await client.close()

    async def test_recovery_selects_from_all_league_cards_in_one_model_call(self):
        from chat_service import ChatClient

        with tempfile.TemporaryDirectory() as directory:
            config = {
                'chat_bot': {'enabled': True, 'allow_message_content': True,
                             'routes': {str(GUILD): {'channels': {str(CHANNEL): {}},
                                                    'keywords': []}}},
                'matchday_engagement': dict(ENGAGEMENT,
                    state_path=str(Path(directory) / 'pulse.sqlite3')),
                'matchday_focus': {'enabled': True, 'guild_ids': [str(GUILD)],
                    'state_path': str(Path(directory) / 'focus.sqlite3'), 'settle_seconds': 0},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(return_value='5')
            newer = card()
            newer.id = SOURCE + 1
            newer.embeds[0].title = "Today's matches in Premier League"
            newer.embeds[0].fields = [SimpleNamespace(
                name='Premier League', value='Small Town vs Valley FC 17:00')]
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
            self.assertEqual(client.brain.select_matchday.await_count, 1)
            self.assertEqual(len(client.brain.select_matchday.await_args.args[0]), 5)
            self.assertEqual(channel.send.await_count, 1)
            self.assertIn('Spain vs England', channel.send.await_args.kwargs['embed'].description)
            self.assertEqual(client.focus_store.selected_source_id(
                GUILD, 'spain|england', NOW.timestamp()), str(SOURCE))
            await client.close()

    async def test_new_card_waits_before_selecting_daily_focus(self):
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
            async def history(limit):
                yield card()
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                history=history, send=AsyncMock())
            client.get_channel = lambda cid: channel if cid == CHANNEL else None
            with patch('chat_service.discord.utils.utcnow', return_value=NOW):
                await client.on_message(card())
            client.brain.select_matchday.assert_not_awaited()
            channel.send.assert_not_awaited()
            self.assertIsNotNone(client.focus_retry_task)
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
                    'state_path': str(Path(directory) / 'focus.sqlite3'), 'settle_seconds': 0},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(return_value='NONE')
            async def history(limit):
                yield card()
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                                      history=history, send=AsyncMock())
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
                    'state_path': str(Path(directory) / 'focus.sqlite3'), 'settle_seconds': 0},
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
                    'weekly_limit': 2, 'settle_seconds': 0},
            }
            client = ChatClient(config)
            client.brain.select_matchday = AsyncMock(return_value='4')
            async def history(limit):
                yield card()
            channel = SimpleNamespace(id=CHANNEL, guild=SimpleNamespace(id=GUILD),
                history=history, send=AsyncMock(return_value=SimpleNamespace(
                    id=1571600000000000000)))
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
