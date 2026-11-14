import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import chat_schedule
from chat_service import ChatClient


class TopicScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_configured_topic_means_no_daily_post(self):
        config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                  'routes': {'1565922092518613064': {'channels': {
                      '1568260661010497627': {}}}},
                  'topic_channel': '1568260661010497627'}}
        client = ChatClient(config)
        channel = SimpleNamespace(send=AsyncMock())
        client.get_channel = lambda _: channel
        await client.send_topics()
        channel.send.assert_not_awaited()
        await client.close()

    async def test_configured_topic_still_posts(self):
        config = {'chat_bot': {'enabled': True, 'allow_message_content': True,
                  'routes': {'1565922092518613064': {'channels': {
                      '1568260661010497627': {}}}},
                  'topic_channel': '1568260661010497627',
                  'topics': [' Which FC squad are you building? ']}}
        client = ChatClient(config)
        channel = SimpleNamespace(send=AsyncMock())
        client.get_channel = lambda _: channel
        await client.send_topics()
        channel.send.assert_awaited_once()
        self.assertEqual(channel.send.await_args.kwargs['embed'].description,
                         'Which FC squad are you building?')
        await client.close()

    def test_london_schedule_accounts_for_daylight_saving(self):
        now = dt.datetime(2026, 3, 28, 21, tzinfo=ZoneInfo('Europe/London'))
        self.assertEqual(chat_schedule.seconds_until_next(20, now), 22 * 3600)


if __name__ == '__main__':
    unittest.main()
