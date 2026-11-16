import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from chat_service import ChatClient, quote_link_view


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
