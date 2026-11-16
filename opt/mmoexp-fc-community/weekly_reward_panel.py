"""Private FC27 weekly reward claim; the public card never handles email."""

import asyncio

import discord

from match_rewards import RewardError


def reward_embed():
    return discord.Embed(
        title='🏆 FC27 Weekly Prediction Rewards',
        description=('Finished in this server’s verified weekly prediction top 20? '
                     'Tap below to check privately. Eligible players can enter their '
                     'MMOEXP account email for one 8% FC27 coupon, valid for 7 days '
                     'after claiming.'),
        colour=0x2275E8,
    )


class WeeklyEmailModal(discord.ui.Modal, title='Claim your FC27 reward'):
    email = discord.ui.TextInput(label='Your MMOEXP account email',
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
                'confirmed': '✅ Your 8% FC27 coupon has reached your MMOEXP account.',
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


class WeeklyClaimView(discord.ui.View):
    def __init__(self, guild_id, channel_id, store, delivery):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.store = store
        self.delivery = delivery

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
