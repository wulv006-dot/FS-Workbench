"""Private FC27 weekly reward claim; the public card never handles email."""

import asyncio

import discord

from match_rewards import RewardError
from weekly_reward_consent import current_week


def reward_embed(pilot=False):
    if pilot:
        description = ('Pilot only: test the private join, withdraw and reward-check buttons. '
                       'One owner-only coupon delivery test succeeded; public weekly rewards '
                       'are not open. No player ID has been shared with Unify.')
    else:
        description = ('Finished in this server’s verified weekly prediction top 20? '
                       'Tap below to check privately. Eligible players can enter the '
                       'MMOEXP email where the 8% FC27 coupon should be delivered. '
                       'The coupon is valid for 7 days after claiming.')
    return discord.Embed(
        title='🏆 FC27 Weekly Prediction Rewards',
        description=description,
        colour=0x2275E8,
    )


class WeeklyEmailModal(discord.ui.Modal, title='Claim your FC27 reward'):
    email = discord.ui.TextInput(label='MMOEXP email to receive the coupon',
                                 placeholder='name@example.com', max_length=254)

    def __init__(self, week_key, player_id, store, delivery):
        super().__init__()
        self.week_key = week_key
        self.player_id = player_id
        self.store = store
        self.delivery = delivery

    async def on_submit(self, interaction):
        if str(interaction.user.id) != self.player_id:
            await interaction.response.send_message('This reward form belongs to another player.',
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            address = str(self.email.value)
            claim = await asyncio.to_thread(self.store.redeem_email_for_player,
                                            self.week_key, self.player_id, address)
            if claim['status'] == 'pending':
                result = await asyncio.to_thread(self.delivery.reconcile, claim['claim_id'], address)
            elif claim['status'] == 'reserved':
                result = await asyncio.to_thread(self.delivery.deliver, claim['claim_id'], address)
            else:
                result = claim
            status = result['status']
            message = {
                'confirmed': '✅ Your 8% FC27 coupon has reached the MMOEXP account for that email.',
                'pending': '⏳ Your coupon is processing. Check again here with the same email.',
                'sending': '⏳ Your coupon is processing. Please wait before checking again.',
                'unknown': 'We could not confirm delivery. Staff will review the original request.',
            }.get(status, 'This reward needs staff review. Please do not submit another email.')
        except RewardError as exc:
            message = str(exc)
        except Exception:
            message = 'The reward service is temporarily unavailable. Please contact staff.'
        await interaction.followup.send(message, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())


class WeeklyConsentChoiceView(discord.ui.View):
    def __init__(self, guild_id, player_id, week_key, consent):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.player_id = player_id
        self.week_key = week_key
        self.consent = consent

    async def _change(self, interaction, agree):
        if (interaction.guild_id != self.guild_id or
                str(interaction.user.id) != self.player_id):
            await interaction.response.send_message('This choice belongs to another player.',
                                                    ephemeral=True)
            return
        if current_week() != self.week_key:
            await interaction.response.edit_message(
                content='The prediction week changed. Open the rewards card again.', view=None)
            return
        try:
            action = self.consent.agree if agree else self.consent.withdraw
            week = await asyncio.to_thread(action, self.guild_id, self.player_id)
        except Exception:
            await interaction.response.edit_message(
                content='Weekly rewards are temporarily unavailable.', view=None)
            return
        message = ('✅ Joined weekly rewards for {}. Check back after the final results.'
                   if agree else '🔕 Your weekly rewards opt-in for {} was removed.')
        await interaction.response.edit_message(content=message.format(week), view=None)

    @discord.ui.button(label='I agree', style=discord.ButtonStyle.success)
    async def agree(self, interaction, _button):
        await self._change(interaction, True)

    @discord.ui.button(label='Withdraw', style=discord.ButtonStyle.secondary)
    async def withdraw(self, interaction, _button):
        await self._change(interaction, False)


class WeeklyClaimView(discord.ui.View):
    def __init__(self, guild_id, channel_id, store, delivery, consent=None, pilot=False):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.store = store
        self.delivery = delivery
        self.consent = consent
        self.pilot = pilot
        if consent is not None:
            button = discord.ui.Button(label='Join weekly rewards', emoji='🏆',
                                       style=discord.ButtonStyle.secondary,
                                       custom_id='fc27:weekly-opt-in')
            button.callback = self.manage_consent
            self.add_item(button)

    async def manage_consent(self, interaction):
        if (interaction.guild_id != self.guild_id or
                interaction.channel_id != self.channel_id or interaction.user.bot):
            await interaction.response.send_message('Open this card in the FC27 rewards channel.',
                                                    ephemeral=True)
            return
        try:
            week_key = current_week()
            joined = await asyncio.to_thread(self.consent.has_consent,
                                             self.guild_id, str(interaction.user.id),
                                             week_key)
        except Exception:
            await interaction.response.send_message('Weekly rewards are temporarily unavailable.',
                                                    ephemeral=True)
            return
        state = 'You have joined this week.' if joined else 'You have not joined this week.'
        notice = 'Pilot only: public rewards are closed; no ID goes to Unify. ' if self.pilot else ''
        await interaction.response.send_message(
            (notice + '{} If you finish in this server’s weekly prediction top 20, Unify may '
             'share your Discord user ID and final rank with MMOEXP to check your '
             '8% FC27 coupon eligibility. Your MMOEXP email stays private to MMOEXP. '
             'You can withdraw before weekly results are sent.').format(state),
            view=WeeklyConsentChoiceView(self.guild_id, str(interaction.user.id),
                                         week_key, self.consent),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label='Check my reward', emoji='🎁', style=discord.ButtonStyle.primary,
                       custom_id='fc27:weekly-claim')
    async def check(self, interaction, _button):
        if (interaction.guild_id != self.guild_id or
                interaction.channel_id != self.channel_id or interaction.user.bot):
            await interaction.response.send_message('Open this card in the FC27 rewards channel.',
                                                    ephemeral=True)
            return
        try:
            week = await asyncio.to_thread(self.store.open_week_for_player,
                                           str(interaction.user.id))
        except Exception:
            await interaction.response.send_message('Reward check is temporarily unavailable.',
                                                    ephemeral=True)
            return
        if not week:
            await interaction.response.send_message('No verified weekly reward is available for you yet.',
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(WeeklyEmailModal(
            week, str(interaction.user.id), self.store, self.delivery))
