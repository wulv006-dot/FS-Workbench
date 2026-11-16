import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from chat_service import ChatClient, order_link_view, quote_link_view


class ChatScopeTests(unittest.IsolatedAsyncioTestCase):
    def test_price_questions_get_a_direct_category_entry(self):
        cases = {
            'How much are FC coins?': '1568663210901504041',
            'Player price for Mbappe?': '1568878333087719454',
            'SBC quote please': '1301379787696377926',
            'What do packs cost?': '1571045541922611200',
            'What is the price?': '1568663362567413820/1568666884289732751',
        }
        for question, destination in cases.items():
            with self.subTest(question=question):
                view = quote_link_view(1041923524601851914, question)
                self.assertIn(destination, view.children[0].url)
        self.assertIsNone(quote_link_view(1041923524601851914, 'That pack was great!'))
        self.assertIsNone(quote_link_view(1565922092518613064, 'How much are coins?'))

    def test_order_help_links_to_live_private_card(self):
        view = order_link_view(1041923524601851914, 'Where is my order?')
        self.assertEqual([button.label for button in view.children], ['Check my order'])
        self.assertTrue(view.children[0].url.endswith(
            '/1570789310813442080/1570795908205903873'))
        self.assertIsNone(order_link_view(1041923524601851914, 'Order of play was odd'))
        self.assertIsNone(order_link_view(1565922092518613064, 'Where is my order?'))

    async def test_unmentioned_price_question_gets_one_live_quote_entry(self):
        router = SimpleNamespace(in_scope=Mock(return_value=True),
                                 route=Mock(return_value=None))
        client = SimpleNamespace(
            router=router, surprise=None, topic_threads={}, user=None,
            brain=SimpleNamespace(ready=True, reply=AsyncMock(return_value='Check the live card.')),
            limiter=SimpleNamespace(allow=Mock(return_value=True), record=Mock()),
            history={}, sticker_for=Mock(return_value=None))
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1041923524601851914),
            channel=SimpleNamespace(id=1200330251016867880,
                                    typing=Mock(return_value=AsyncMock())),
            author=SimpleNamespace(id=456, display_name='fan'),
            content='How much are FC coins?', reference=None, reply=AsyncMock())

        self.assertTrue(await ChatClient.handle_chat(client, message))
        message.reply.assert_awaited_once()
        self.assertIn('1568663210901504041',
                      message.reply.await_args.kwargs['view'].children[0].url)
        client.limiter.record.assert_called_once()

        message.content = 'How much is my order?'
        self.assertTrue(await ChatClient.handle_chat(client, message))
        self.assertEqual(message.reply.await_count, 2)
        self.assertIn('1570795908205903873',
                      message.reply.await_args.kwargs['view'].children[0].url)
        client.brain.reply.assert_awaited_once()

        message.channel.id = 1571043570268242014
        message.content = 'How much injury time?'
        self.assertFalse(await ChatClient.handle_chat(client, message))
        self.assertEqual(message.reply.await_count, 2)

    async def test_order_slash_reply_is_private_even_when_ai_is_unavailable(self):
        client = SimpleNamespace(
            router=SimpleNamespace(in_scope=Mock(return_value=True)),
            brain=SimpleNamespace(ready=False, reply=AsyncMock()),
            limiter=SimpleNamespace(allow=Mock(return_value=True), record=Mock()))
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(guild_id=1041923524601851914,
                                      channel_id=1200330251016867880,
                                      user=SimpleNamespace(id=456), response=response)
        await ChatClient.do_chat(client, interaction, 'Where is my order?')
        self.assertTrue(response.send_message.await_args.kwargs['ephemeral'])
        self.assertIn('1570795908205903873',
                      response.send_message.await_args.kwargs['view'].children[0].url)
        client.brain.reply.assert_not_awaited()

    async def test_staff_text_trigger_outside_fc_is_ignored(self):
        surprise = SimpleNamespace(is_staff=Mock())
        client = SimpleNamespace(router=SimpleNamespace(in_scope=Mock(return_value=False)),
                                 surprise=surprise)
        message = SimpleNamespace(guild=SimpleNamespace(id=1041923524601851914),
                                  channel=SimpleNamespace(id=123),
                                  author=SimpleNamespace(id=456), content='!drop')
        self.assertFalse(await ChatClient.handle_chat(client, message))
        surprise.is_staff.assert_not_called()

    async def test_slash_chat_and_drop_outside_fc_only_reply_privately(self):
        client = SimpleNamespace(router=SimpleNamespace(in_scope=Mock(return_value=False)))
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(guild_id=1041923524601851914,
                                      channel_id=123, response=response)
        await ChatClient.do_chat(client, interaction, 'hello')
        await ChatClient.do_drop(client, interaction)
        self.assertEqual(response.send_message.await_count, 2)
        for call in response.send_message.await_args_list:
            self.assertTrue(call.kwargs['ephemeral'])


if __name__ == '__main__':
    unittest.main()
