import datetime
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from content_bot import TEST_GUILD, build_client, validate_config
from community import CommunityStore
from verified_prize_claim import VerifiedPrizeClaims
from weekly_reward_consent import WeeklyRewardConsent, current_week
from weekly_reward_panel import WeeklyClaimView, reward_embed


COUPON = dict(id=2001, title='FC27 weekly reward', type=1, fetch_scene=4,
              status=1, mode_type=2, attain='0', reduce='92', max_reduce='0',
              limit_qty=30, repeat_qty=1, time_effect=2, days=7,
              site_id=266, game_id=1327, is_open=0)
CHANNEL = 1568260661010497627
PLAYER = 333333333333333333


def interaction(guild=TEST_GUILD, channel=CHANNEL, player=PLAYER):
    return SimpleNamespace(
        guild_id=guild, channel_id=channel,
        user=SimpleNamespace(id=player, bot=False),
        response=SimpleNamespace(send_message=AsyncMock(), send_modal=AsyncMock(),
                                 defer=AsyncMock(), edit_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


class WeeklyRewardPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VerifiedPrizeClaims(Path(self.tmp.name) / 'weekly.sqlite3')
        self.delivery = SimpleNamespace(deliver=lambda *_: {'status': 'confirmed'})
        self.view = WeeklyClaimView(TEST_GUILD, CHANNEL, self.store, self.delivery)

    async def test_private_email_form_only_for_verified_player(self):
        now = int(time.time())
        week = datetime.date.today().isocalendar()
        week_key = '{}-W{:02d}'.format(week[0], week[1])
        self.store.issue(week_key, 'proof:oneweek', str(PLAYER), COUPON,
                         expires_at=now + 3600, now=now)
        wrong = interaction(player=444444444444444444)
        await self.view.children[0].callback(wrong)
        wrong.response.send_modal.assert_not_awaited()
        self.assertTrue(wrong.response.send_message.call_args.kwargs['ephemeral'])

        correct = interaction()
        await self.view.children[0].callback(correct)
        modal = correct.response.send_modal.call_args.args[0]
        self.assertEqual(modal.week_key, week_key)
        correct.response.send_message.assert_not_awaited()
        modal.email._value = 'PLAYER@example.com'
        await modal.on_submit(correct)
        self.assertTrue(correct.followup.send.call_args.kwargs['ephemeral'])
        self.assertIn('coupon has reached', correct.followup.send.call_args.args[0])
        self.assertEqual(self.store.open_week_for_player(str(PLAYER)), week_key)

    async def test_forwarded_card_cannot_be_used_outside_its_channel(self):
        wrong = interaction(channel=555555555555555555)
        await self.view.children[0].callback(wrong)
        wrong.response.send_modal.assert_not_awaited()
        self.assertTrue(wrong.response.send_message.call_args.kwargs['ephemeral'])

    async def test_private_opt_in_can_be_withdrawn_and_cannot_be_stolen(self):
        consent = WeeklyRewardConsent(Path(self.tmp.name) / 'weekly.sqlite3', 't' * 32)
        view = WeeklyClaimView(TEST_GUILD, CHANNEL, self.store, self.delivery,
                               consent=consent)
        player = interaction()
        await view.children[1].callback(player)
        self.assertTrue(player.response.send_message.call_args.kwargs['ephemeral'])
        choice = player.response.send_message.call_args.kwargs['view']
        other = interaction(player=444444444444444444)
        await choice.children[0].callback(other)
        self.assertFalse(consent.has_consent(TEST_GUILD, str(PLAYER), current_week()))
        await choice.children[0].callback(player)
        self.assertTrue(consent.has_consent(TEST_GUILD, str(PLAYER), current_week()))
        await choice.children[1].callback(player)
        self.assertFalse(consent.has_consent(TEST_GUILD, str(PLAYER), current_week()))
        with patch('weekly_reward_panel.current_week', return_value='2099-W01'):
            await choice.children[0].callback(player)
        self.assertFalse(consent.has_consent(TEST_GUILD, str(PLAYER), current_week()))

    async def test_test_guild_card_says_no_coupon_is_issued(self):
        self.assertIn('Pilot only', reward_embed(pilot=True).description)
        self.assertNotIn('Pilot only', reward_embed().description)

    async def test_config_is_off_by_default_and_staff_command_is_scoped(self):
        base = {'guild_id': TEST_GUILD, 'staff_user_ids': [str(PLAYER)]}
        store = CommunityStore(Path(self.tmp.name) / 'content.sqlite3', base['staff_user_ids'])
        client = build_client(base, store)
        self.addAsyncCleanup(client.close)
        import discord
        self.assertIsNone(client.tree.get_command('weekly-reward-card',
                                                    guild=discord.Object(TEST_GUILD)))
        base['weekly_rewards'] = {'guild_id': TEST_GUILD, 'channel_id': CHANNEL}
        validate_config(base)
        enabled = build_client(base, store)
        self.addAsyncCleanup(enabled.close)
        self.assertIsNotNone(enabled.tree.get_command('weekly-reward-card',
                                                       guild=discord.Object(TEST_GUILD)))
        with patch.dict('os.environ', {'FC27_WEEKLY_CONSENT_KEY': 's' * 32}):
            with patch.object(enabled.tree, 'sync', new=AsyncMock()):
                await enabled.setup_hook()
        self.assertIsInstance(enabled.weekly_reward_view, WeeklyClaimView)
        self.assertEqual(len(enabled.weekly_reward_view.children), 2)
        for bad in ({'guild_id': TEST_GUILD, 'channel_id': 'not-an-id'},
                    {'guild_id': TEST_GUILD, 'channel_id': 555555555555555555},
                    {'guild_id': 1, 'channel_id': CHANNEL}):
            base['weekly_rewards'] = bad
            with self.assertRaises(ValueError):
                validate_config(base)


if __name__ == '__main__':
    unittest.main()
