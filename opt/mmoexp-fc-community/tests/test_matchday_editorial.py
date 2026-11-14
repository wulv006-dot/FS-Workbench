import datetime as dt
import json
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
                               title='Manchester City vs Arsenal',
                               description='Premier League · <t:{}:F>'.format(
                                   int(kickoff.timestamp())), fields=[])])


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
            no_time.embeds[0].description = 'Premier League fixture'
            self.assertFalse(verify_smart_score_source(no_time, fixtures[0]))
            self.assertEqual(due_cards(fixtures, now), [(fixtures[0], 'day_before')])
            self.assertEqual(due_cards(fixtures, kickoff - dt.timedelta(minutes=30)),
                             [(fixtures[0], 'kickoff_soon')])
            self.assertEqual(due_cards(fixtures, kickoff + dt.timedelta(minutes=11)), [])
            self.assertIn('<t:{}:F>'.format(int(kickoff.timestamp())),
                          card_text(fixtures[0], 'day_before'))

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

    def test_config_requires_absolute_paths_and_existing_matchday_route(self):
        with self.assertRaises(ValueError):
            validate_config({'enabled': True, 'plan_path': 'relative.json',
                             'state_path': 'relative.db'}, {'enabled': True})
        with self.assertRaises(ValueError):
            validate_config({'enabled': True, 'plan_path': '/tmp/plan.json',
                             'state_path': '/tmp/state.db'}, None)


class EditorialChatTests(unittest.IsolatedAsyncioTestCase):
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
                'matchday_editorial': {'enabled': True, 'plan_path': str(path),
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
                'matchday_editorial': {'enabled': True, 'plan_path': str(path),
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
