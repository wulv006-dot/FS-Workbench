import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from order_panel import OrderModal, SUPPORT_CHANNEL_ID
from order_service import InteractionStore, OrderService


NUMBER = 'D' + '1' * 18


class OrderLookupTests(unittest.TestCase):
    def test_lookup_returns_only_safe_status_and_support_copy(self):
        payload = {'code': 1, 'data': {'total': 1, 'list': [{
            'order_no': NUMBER, 'site_id': 266, 'gid': 1327,
            'status_format': '问题订单', 'email': 'private@example.invalid',
        }]}}
        with tempfile.TemporaryDirectory() as directory:
            service = OrderService(lambda number: payload,
                InteractionStore(Path(directory) / 'orders.sqlite3'))
            result = service.lookup(1041923524601851914, 1237241595674361962, NUMBER)
        self.assertEqual(result['status'], 'Needs support')
        self.assertNotIn('private@example.invalid', repr(result))


class OrderModalTests(unittest.IsolatedAsyncioTestCase):
    async def submit(self, result):
        panel = SimpleNamespace(permitted=lambda interaction: True,
                                service=SimpleNamespace(lookup=Mock()))
        modal = OrderModal(panel, 1237241595674361962)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=1237241595674361962),
            guild_id=1041923524601851914,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        with patch('order_panel.asyncio.to_thread', new_callable=AsyncMock,
                   return_value=result):
            await modal.on_submit(interaction)
        return interaction.followup.send.call_args

    async def test_unresolved_lookup_links_to_private_support(self):
        call = await self.submit({'message': 'No matching FC27 order was found.'})
        kwargs = call.kwargs
        self.assertTrue(kwargs['ephemeral'])
        buttons = kwargs['view'].children
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].url, 'https://discord.com/channels/'
                         '1041923524601851914/{}'.format(SUPPORT_CHANNEL_ID))

    async def test_problem_order_links_to_support_without_exposing_details(self):
        call = await self.submit({'status': 'Needs support', 'support': 'Contact support.'})
        self.assertIsNotNone(call.kwargs['view'])
        self.assertIn('Open a private support ticket', call.args[0])

    async def test_normal_status_stays_private_without_ticket_prompt(self):
        kwargs = (await self.submit({'status': 'Delivering', 'support': 'On the way.'})).kwargs
        self.assertTrue(kwargs['ephemeral'])
        self.assertIsNone(kwargs['view'])
