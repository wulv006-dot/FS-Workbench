import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import black_friday_pilot as pilot


def action(uid, channel=pilot.CHANNEL):
    return SimpleNamespace(user=SimpleNamespace(id=uid), channel_id=channel, guild_id=pilot.GUILD,
        response=SimpleNamespace(send_message=AsyncMock(),send_modal=AsyncMock(),defer=AsyncMock()),
        edit_original_response=AsyncMock())


class PilotFlow(unittest.IsolatedAsyncioTestCase):
    async def test_private_join_verify_reveal_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(pilot,'STATE',Path(tmp)), patch.object(pilot.asyncio,'sleep',AsyncMock()):
            for uid,profile,tier in [(10,'new','one'),(11,'return','two'),(12,'four','two'),(13,'five','bonus')]:
                for attempt in (0,1):
                    it = action(uid)
                    await pilot.Home().children[0].callback(it)
                    args = it.response.send_message.await_args.kwargs
                    self.assertTrue(args['ephemeral'])
                    args['view'].children[0]._values = ['Real Madrid']
                    await args['view'].children[0].callback(it)
                    email = it.response.send_modal.await_args.args[0]
                    email.address._value = f'{profile}+tester@example.test'
                    await email.on_submit(it)
                    inbox = it.response.send_message.await_args.kwargs['view']
                    await inbox.children[0].callback(it)
                    modal = it.response.send_modal.await_args.args[0]
                    modal.code._value = '000000'
                    await modal.on_submit(it)
                    it.response.defer.assert_not_awaited()
                    modal.code._value = inbox.pin
                    await modal.on_submit(it)
                    result = it.edit_original_response.await_args.kwargs['embed']
                    self.assertIn(pilot.REWARDS[tier],result.description)
                    self.assertIn('original' if attempt else 'Black Friday',result.title)
            with self.assertRaises(ValueError):
                pilot.fixture('private@example.com')
            outside=action(10,999)
            await pilot.Home().children[0].callback(outside)
            self.assertNotIn('view',outside.response.send_message.await_args.kwargs)
