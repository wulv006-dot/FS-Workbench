import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from matchday_editorial import (EditorialPostStore, card_text, due_cards, load_plan,
                                validate_config, verify_smart_score_source)

GUILD = 1565922092518613064
SOURCE = 1568260661010497627
DISCUSSION = 1568260661010497627
MESSAGE = 1571184986541789367
ROUTES = {str(GUILD): {'source_channel_id': SOURCE,
                       'discussion_channel_id': DISCUSSION,
                       'players_channel_id': SOURCE, 'coins_channel_id': SOURCE}}
UTC = dt.timezone.utc


def plan(kickoff, **changes):
    item = {'fixture_id': 'city-arsenal-20261115', 'guild_id': str(GUILD),
            'home': 'Manchester City', 'away': 'Arsenal',
            'competition': 'Premier League',
            'kickoff_utc': kickoff.isoformat().replace('+00:00', 'Z'),
            'smart_score_message_url':
                'https://discord.com/channels/{}/{}/{}'.format(GUILD, SOURCE, MESSAGE)}
    item.update(changes)
    return {'version': 1, 'matches': [item]}


def source_message(kickoff, author_id=1496068397757366273):
    return SimpleNamespace(id=MESSAGE, guild=SimpleNamespace(id=GUILD),
                           channel=SimpleNamespace(id=SOURCE),
                           author=SimpleNamespace(id=author_id, bot=True),
                           content='', embeds=[SimpleNamespace(
                               title='Upcoming Matches',
                               description='Upcoming matches in the selected window.',
                               fields=[SimpleNamespace(
                                   name='🟦 UPCOMING **Manchester City** vs **Arsenal**',
                                   value='> 🏆 **League**: Premier League\n'
                                         '> 📡 **Status**: Not Started\n'
                                         '> 📅 **Kickoff**: <t:{}:F>'.format(
                                             int(kickoff.timestamp())))])])


class EditorialPlanTests(unittest.TestCase):
    def test_verified_fixture_and_phase_windows(self):
        now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        kickoff = now + dt.timedelta(hours=3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            path.write_text(json.dumps(plan(kickoff)), encoding='utf-8')
            fixtures = load_plan(path, ROUTES, now=now)
            self.assertTrue(verify_smart_score_source(source_message(kickoff), fixtures[0]))
            self.assertFalse(verify_smart_score_source(source_message(kickoff, 123), fixtures[0]))
            no_time = source_message(kickoff)
            no_time.embeds[0].fields[0].value = 'Premier League fixture'
            self.assertFalse(verify_smart_score_source(no_time, fixtures[0]))
            self.assertEqual(due_cards(fixtures, now), [(fixtures[0], 'day_before')])
            self.assertEqual(due_cards(fixtures, kickoff - dt.timedelta(minutes=30)),
                             [(fixtures[0], 'kickoff_soon')])
            self.assertEqual(due_cards(fixtures, kickoff + dt.timedelta(minutes=11)), [])
            self.assertIn('<t:{}:F>'.format(int(kickoff.timestamp())),
                          card_text(fixtures[0], 'day_before'))
            path.write_text(json.dumps(plan(
                kickoff, question='What would you change in your FC27 midfield?')),
                encoding='utf-8')
            self.assertIn('What would you change',
                          card_text(load_plan(path, ROUTES, now=now)[0], 'day_before'))
            self.assertIn('What is your one call',
                          card_text(load_plan(path, ROUTES, now=now)[0], 'kickoff_soon'))
            path.write_text(json.dumps(plan(kickoff, question='first line\nsecond line')),
                            encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'question'):
                load_plan(path, ROUTES, now=now)

    def test_wrong_source_time_and_weekly_capacity_are_rejected(self):
        now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        kickoff = now + dt.timedelta(hours=3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            bad = plan(kickoff, smart_score_message_url=
                       'https://discord.com/channels/{}/{}/{}'.format(GUILD, SOURCE + 1, MESSAGE))
            path.write_text(json.dumps(bad), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_plan(path, ROUTES, now=now)
            bad = plan(kickoff + dt.timedelta(days=3))
            path.write_text(json.dumps(bad), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_plan(path, ROUTES, now=now)
            stale = plan(now - dt.timedelta(hours=3))
            stale['matches'].append(dict(plan(kickoff)['matches'][0],
                                         fixture_id='city-arsenal-current'))
            path.write_text(json.dumps(stale), encoding='utf-8')
            self.assertEqual([row.fixture_id for row in load_plan(path, ROUTES, now=now)],
                             ['city-arsenal-current'])
            repeated = plan(kickoff)
            repeated['matches'].append(dict(repeated['matches'][0], fixture_id='arsenal-city-2'))
            path.write_text(json.dumps(repeated), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_plan(path, ROUTES, now=now, weekly_limit=1)
            malicious = plan(kickoff, home='@everyone')
            path.write_text(json.dumps(malicious), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_plan(path, ROUTES, now=now)

    def test_source_timestamp_disagreement_is_rejected(self):
        now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            kickoff = now + dt.timedelta(hours=3)
            path.write_text(json.dumps(plan(kickoff)), encoding='utf-8')
            fixture = load_plan(path, ROUTES, now=now)[0]
            self.assertFalse(verify_smart_score_source(
                source_message(kickoff + dt.timedelta(hours=1)), fixture))
            wrong_league = source_message(kickoff)
            wrong_league.embeds[0].fields[0].value = (
                wrong_league.embeds[0].fields[0].value.replace(
                    'Premier League', 'Champions League'))
            self.assertFalse(verify_smart_score_source(wrong_league, fixture))
            already_started = source_message(kickoff)
            already_started.embeds[0].fields[0].value = (
                already_started.embeds[0].fields[0].value.replace(
                    'Not Started', 'In Progress'))
            self.assertFalse(verify_smart_score_source(already_started, fixture))

    def test_multi_match_card_must_pair_fixture_and_kickoff_in_one_field(self):
        now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        kickoff = now + dt.timedelta(hours=3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            path.write_text(json.dumps(plan(kickoff)), encoding='utf-8')
            fixture = load_plan(path, ROUTES, now=now)[0]
            card = source_message(kickoff + dt.timedelta(hours=1))
            card.embeds[0].fields.append(SimpleNamespace(
                name='🟦 UPCOMING **Chelsea** vs **Liverpool**',
                value='> 🏆 **League**: Premier League\n'
                      '> 📡 **Status**: Not Started\n'
                      '> 📅 **Kickoff**: <t:{}:F>'.format(int(kickoff.timestamp()))))
            self.assertFalse(verify_smart_score_source(card, fixture))

    def test_persistent_reservation_prevents_duplicate_posts(self):
        now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plan.json'
            path.write_text(json.dumps(plan(now + dt.timedelta(hours=3))), encoding='utf-8')
            fixture = load_plan(path, ROUTES, now=now)[0]
            store = EditorialPostStore(Path(directory) / 'state.sqlite3')
            self.assertTrue(store.reserve(fixture, 'day_before', now.timestamp()))
            self.assertFalse(store.reserve(fixture, 'day_before', now.timestamp()))
            store.finish(fixture, 'day_before', MESSAGE)
            self.assertEqual(store.status(fixture, 'day_before'), ('sent', str(MESSAGE)))
            self.assertFalse(EditorialPostStore(Path(directory) / 'state.sqlite3').reserve(
                fixture, 'day_before', now.timestamp()))

    def test_existing_pilot_ledger_migrates_without_losing_sent_message(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('''CREATE TABLE matchday_editorial_post (
                    guild_id TEXT NOT NULL, fixture_id TEXT NOT NULL, phase TEXT NOT NULL,
                    source_url TEXT NOT NULL, status TEXT NOT NULL,
                    message_id TEXT, reserved_at REAL NOT NULL,
                    PRIMARY KEY (guild_id, fixture_id, phase))''')
                db.execute('''INSERT INTO matchday_editorial_post VALUES (?,?,?,?,?,?,?)''',
                           (str(GUILD), 'city-arsenal-20261115', 'day_before',
                            'https://discord.com/channels/{}/{}/{}'.format(GUILD, SOURCE, MESSAGE),
                            'sent', str(MESSAGE + 1), 1.0))
            db.close()
            store = EditorialPostStore(path)
            fixture = SimpleNamespace(guild_id=GUILD, fixture_id='city-arsenal-20261115')
            self.assertEqual(store.records(fixture)[0][0:3],
                             ('day_before', 'sent', str(MESSAGE + 1)))
            self.assertEqual(store.records(fixture)[0][4:], (None, 'normal'))

    def test_config_requires_absolute_paths_and_existing_matchday_route(self):
        with self.assertRaises(ValueError):
            validate_config({'enabled': True, 'plan_path': 'relative.json',
                             'state_path': 'relative.db'}, {'enabled': True})
        with self.assertRaises(ValueError):
            validate_config({'enabled': True, 'plan_path': '/tmp/plan.json',
                             'state_path': '/tmp/state.db'}, None)
        with tempfile.TemporaryDirectory() as directory:
            config = {'enabled': True, 'plan_path': str(Path(directory) / 'plan.json'),
                      'state_path': str(Path(directory) / 'state.db')}
            matchday = {'enabled': True, 'routes': ROUTES}
            with self.assertRaises(ValueError):
                validate_config(config, matchday)
            with self.assertRaises(ValueError):
                validate_config(dict(config, allowed_guild_ids=[str(GUILD),
                                  '1041923524601851914']), matchday)
            self.assertIs(validate_config(dict(config, allowed_guild_ids=[str(GUILD)]),
                                          matchday)['enabled'], True)


class EditorialChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_hold_edits_original_card_and_resume_requires_verified_source(self):
        from chat_service import ChatClient
        kickoff = dt.datetime.now(UTC) + dt.timedelta(hours=3)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / 'plan.json'
            path.write_text(json.dumps(plan(kickoff)), encoding='utf-8')
            fixture = load_plan(path, ROUTES)[0]
            config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': {'enabled': True, 'routes': ROUTES,
                                        'state_path': str(directory / 'pulse.db')},
                'matchday_editorial': {'enabled': True,
                    'allowed_guild_ids': [str(GUILD)], 'plan_path': str(path),
                    'state_path': str(directory / 'editorial.db')}}
            client = ChatClient(config)
            client._connection.user = SimpleNamespace(id=MESSAGE + 10)
            client.editorial_store.reserve(fixture, 'day_before', 1.0)
            client.editorial_store.finish(fixture, 'day_before', MESSAGE + 1)
            previous = SimpleNamespace(author=SimpleNamespace(id=MESSAGE + 10),
                                       embeds=[SimpleNamespace(title='⚽ Matchday · City vs Arsenal')])
            async def edit(**kwargs):
                previous.embeds = [kwargs['embed']]
            previous.edit = AsyncMock(side_effect=edit)
            async def fetch(message_id):
                return previous if message_id == MESSAGE + 1 else source_message(kickoff)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=GUILD),
                                      fetch_message=AsyncMock(side_effect=fetch),
                                      send=AsyncMock())
            client.get_channel = lambda _: channel
            path.write_text(json.dumps(plan(kickoff, status='hold')), encoding='utf-8')
            await client.send_editorial_due()
            await client.send_editorial_due()
            self.assertEqual(previous.edit.await_count, 1)
            self.assertEqual(channel.send.await_count, 0)
            self.assertEqual(client.editorial_store.records(fixture)[0][5], 'hold')
            path.write_text(json.dumps(plan(kickoff)), encoding='utf-8')
            await client.send_editorial_due()
            self.assertEqual(previous.edit.await_count, 2)
            self.assertEqual(client.editorial_store.records(fixture)[0][5], 'normal')
            self.assertEqual(channel.send.await_count, 0)
            await client.close()

    async def test_reschedule_edits_existing_card_only_with_new_verified_time(self):
        from chat_service import ChatClient
        now = dt.datetime.now(UTC)
        old_kickoff, new_kickoff = now + dt.timedelta(hours=4), now + dt.timedelta(hours=3)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / 'plan.json'
            path.write_text(json.dumps(plan(old_kickoff)), encoding='utf-8')
            old_fixture = load_plan(path, ROUTES)[0]
            config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': {'enabled': True, 'routes': ROUTES,
                                        'state_path': str(directory / 'pulse.db')},
                'matchday_editorial': {'enabled': True,
                    'allowed_guild_ids': [str(GUILD)], 'plan_path': str(path),
                    'state_path': str(directory / 'editorial.db')}}
            client = ChatClient(config)
            client._connection.user = SimpleNamespace(id=MESSAGE + 10)
            client.editorial_store.reserve(old_fixture, 'day_before', 1.0)
            client.editorial_store.finish(old_fixture, 'day_before', MESSAGE + 1)
            previous = SimpleNamespace(author=SimpleNamespace(id=MESSAGE + 10),
                embeds=[SimpleNamespace(title='⚽ Matchday · City vs Arsenal')],
                edit=AsyncMock())
            source = source_message(old_kickoff)
            async def fetch(message_id):
                return previous if message_id == MESSAGE + 1 else source
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=GUILD),
                                      fetch_message=AsyncMock(side_effect=fetch),
                                      send=AsyncMock())
            client.get_channel = lambda _: channel
            path.write_text(json.dumps(plan(new_kickoff)), encoding='utf-8')
            await client.send_editorial_due()
            self.assertEqual(previous.edit.await_count, 0)
            self.assertEqual(client.editorial_store.records(old_fixture)[0][4],
                             int(old_kickoff.timestamp()))
            source = source_message(new_kickoff)
            await client.send_editorial_due()
            self.assertEqual(previous.edit.await_count, 1)
            self.assertEqual(client.editorial_store.records(old_fixture)[0][4],
                             int(new_kickoff.timestamp()))
            self.assertEqual(channel.send.await_count, 0)
            await client.close()

    async def test_test_only_rollout_rejects_official_plan(self):
        from chat_service import ChatClient
        kickoff = dt.datetime.now(UTC) + dt.timedelta(minutes=30)
        official_guild = '1041923524601851914'
        official_channel = 1571043454136484082
        official_plan = plan(kickoff, guild_id=official_guild,
                             smart_score_message_url='https://discord.com/channels/{}/{}/{}'.format(
                                 official_guild, official_channel, MESSAGE))
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / 'plan.json'
            path.write_text(json.dumps(official_plan), encoding='utf-8')
            routes = dict(ROUTES)
            routes[official_guild] = dict(ROUTES[str(GUILD)],
                                          source_channel_id=official_channel,
                                          discussion_channel_id=official_channel)
            config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': {'enabled': True, 'routes': routes,
                                        'state_path': str(directory / 'pulse.db')},
                'matchday_editorial': {'enabled': True,
                    'allowed_guild_ids': [str(GUILD)], 'plan_path': str(path),
                    'state_path': str(directory / 'editorial.db')}}
            client = ChatClient(config)
            client.get_channel = lambda _: self.fail('Official route must not be fetched')
            await client.send_editorial_due()
            await client.close()

    async def test_posts_once_only_after_reading_real_smart_score_card(self):
        from chat_service import ChatClient
        kickoff = dt.datetime.now(UTC) + dt.timedelta(minutes=30)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / 'plan.json'
            path.write_text(json.dumps(plan(kickoff)), encoding='utf-8')
            config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': {'enabled': True, 'routes': ROUTES,
                                        'state_path': str(directory / 'pulse.db')},
                'matchday_editorial': {'enabled': True, 'allowed_guild_ids': [str(GUILD)],
                                       'plan_path': str(path),
                                       'state_path': str(directory / 'editorial.db')}}
            client = ChatClient(config)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=GUILD),
                                      fetch_message=AsyncMock(return_value=source_message(kickoff)),
                                      send=AsyncMock(return_value=SimpleNamespace(id=MESSAGE + 1)))
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            await client.send_editorial_due()
            await client.send_editorial_due()
            self.assertEqual(channel.send.await_count, 1)
            self.assertEqual(channel.fetch_message.await_count, 1)
            self.assertEqual(client.editorial_store.status(
                load_plan(path, ROUTES)[0], 'kickoff_soon'), ('sent', str(MESSAGE + 1)))
            await client.close()

    async def test_unconfirmed_send_is_frozen(self):
        from chat_service import ChatClient
        kickoff = dt.datetime.now(UTC) + dt.timedelta(minutes=30)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / 'plan.json'
            path.write_text(json.dumps(plan(kickoff)), encoding='utf-8')
            config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                'routes': {str(GUILD): {'channels': {str(SOURCE): {}}, 'keywords': []}}},
                'matchday_engagement': {'enabled': True, 'routes': ROUTES,
                                        'state_path': str(directory / 'pulse.db')},
                'matchday_editorial': {'enabled': True, 'allowed_guild_ids': [str(GUILD)],
                                       'plan_path': str(path),
                                       'state_path': str(directory / 'editorial.db')}}
            client = ChatClient(config)
            channel = SimpleNamespace(id=SOURCE, guild=SimpleNamespace(id=GUILD),
                                      fetch_message=AsyncMock(return_value=source_message(kickoff)),
                                      send=AsyncMock(side_effect=RuntimeError('unknown')))
            client.get_channel = lambda channel_id: channel if channel_id == SOURCE else None
            await client.send_editorial_due()
            await client.send_editorial_due()
            self.assertEqual(channel.send.await_count, 1)
            self.assertEqual(client.editorial_store.status(
                load_plan(path, ROUTES)[0], 'kickoff_soon'), ('unknown', None))
            await client.close()


if __name__ == '__main__':
    unittest.main()
