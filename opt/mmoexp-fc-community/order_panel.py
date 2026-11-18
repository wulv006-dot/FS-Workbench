"""Private order lookup and native Discord reaction rewards."""
import asyncio
import json
import logging

LOG = logging.getLogger(__name__)
from pathlib import Path

import discord
from club_panel import brand_embed
from order_service import InteractionStore, OrderService, PROBLEM_SUPPORT
from quote_bridge import SocketProvider

MENTIONS = discord.AllowedMentions.none()
REWARDS_PAUSED = False
GUILDS = (1565922092518613064, 1041923524601851914)
SUPPORT_CHANNEL_ID = 1326761935487635466
REACTIONS = ('❤️', '👍')
COUPON = ('Thank you! Your code: **FCVIP6** · **8% off** eligible FC27 purchases at MMOEXP. '
          'Valid 2026-10-27 to 2027-11-01; no usage-count limit. '
          'Final eligibility and price are confirmed at checkout.')


async def report_error(interaction, error, phase):
    # No exception text/traceback: upstream or interaction objects may contain private data.
    status, code = getattr(error, 'status', None), getattr(error, 'code', None)
    LOG.error('order interaction phase=%s error=%s status=%s code=%s', phase,
              type(error).__name__, status if type(status) is int else None,
              code if type(code) is int else None)
    text = 'Order service is temporarily unavailable. Please try again shortly.'
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True, allowed_mentions=MENTIONS)
        else:
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=MENTIONS)
    except discord.HTTPException as reply_error:
        LOG.error('order interaction phase=error_reply error=%s', type(reply_error).__name__)


def validate_order_config(config):
    if (not isinstance(config, dict) or set(config) != {'guild_id', 'channel_id', 'socket'}
            or type(config['guild_id']) is not int or config['guild_id'] not in GUILDS
            or type(config['channel_id']) is not int or config['channel_id'] <= 0
            or config['socket'] != '/run/fc-order/order.sock'):
        raise ValueError('Invalid order panel configuration')
    return config


def panel_embed(count, presentation=None):
    embed = discord.Embed(title='FC 27 · Order Support', description=(
        'Check your order privately using its complete order number. '
        'Never post your order number, email or account details in this channel.\n\n'
        'React with ❤️ or 👍 below — counts are public in Discord.\n'
        'Your first reaction unlocks a private MMOEXP FC27 8% discount code sent by DM.\n'
        'DMs closed? Use Get my code after reacting.'))
    return brand_embed(embed, presentation)


def support_view():
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label='Open support ticket', style=discord.ButtonStyle.link,
        url='https://discord.com/channels/{}/{}'.format(GUILDS[1], SUPPORT_CHANNEL_ID)))
    return view


class OrderModal(discord.ui.Modal, title='Private order lookup'):
    number = discord.ui.TextInput(label='Complete order number', min_length=19,
                                  max_length=19, required=True)

    def __init__(self, panel, user_id):
        super().__init__(timeout=180)
        self.panel, self.user_id = panel, user_id

    async def on_submit(self, interaction):
        if interaction.user.id != self.user_id or not self.panel.permitted(interaction):
            await interaction.response.send_message('This form is not available here.',
                ephemeral=True, allowed_mentions=MENTIONS)
            return
        print('order interaction phase=submit', flush=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await asyncio.to_thread(self.panel.service.lookup,
            interaction.guild_id, interaction.user.id, str(self.number.value))
        text = result.get('message') or ('Status: **{}**\n{}'.format(result['status'], result['support']))
        needs_support = bool(result.get('message') or result.get('status') in
                             ('Needs support', 'Refund requested'))
        embed = None
        if not result.get('message'):
            if result['status'] == 'Delivering':
                embed = discord.Embed().set_image(
                    url='https://media.discordapp.net/stickers/1520247440953835531.gif')
            elif result['support'] == PROBLEM_SUPPORT:
                embed = discord.Embed().set_image(
                    url='https://media.discordapp.net/stickers/1520247371223535717.gif')
        if needs_support:
            text += '\n\nNeed more help? Open a private support ticket below.'
        await interaction.followup.send(text, embed=embed,
            view=support_view() if needs_support else None,
            ephemeral=True, allowed_mentions=MENTIONS)
        print('order interaction phase=replied', flush=True)

    async def on_error(self, interaction, error):
        await report_error(interaction, error, 'modal')


class OrderPanelView(discord.ui.View):
    def __init__(self, config, service, presentation=None):
        super().__init__(timeout=None)
        self.reward.disabled = REWARDS_PAUSED
        self.config = validate_order_config(config)
        self.service, self.presentation = service, presentation
        self.like_lock = asyncio.Lock()

    def permitted(self, interaction):
        return (interaction.guild_id == self.config['guild_id']
                and interaction.channel_id == self.config['channel_id']
                and interaction.guild is not None
                and interaction.guild.id == self.config['guild_id']
                and not interaction.user.bot)

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error, 'view')

    async def interaction_check(self, interaction):
        if self.permitted(interaction):
            return True
        await interaction.response.send_message('This menu is not available here.',
            ephemeral=True, allowed_mentions=MENTIONS)
        return False

    @discord.ui.button(label='Check my order', style=discord.ButtonStyle.primary,
                       custom_id='fc:order:lookup:v1')
    async def lookup(self, interaction, button):
        print('order interaction phase=button', flush=True)
        await interaction.response.send_modal(OrderModal(self, interaction.user.id))
        print('order interaction phase=modal_sent', flush=True)

    @discord.ui.button(label='Get my code', style=discord.ButtonStyle.secondary,
                       custom_id='fc:order:reward:v1')
    async def reward(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if REWARDS_PAUSED:
            await interaction.followup.send('Discount rewards are temporarily paused.',
                                            ephemeral=True, allowed_mentions=MENTIONS)
            return
        eligible = await asyncio.to_thread(self.service.store.eligible,
                                           interaction.guild_id, interaction.user.id)
        await interaction.followup.send(COUPON if eligible else
            'React with ❤️ or 👍 on this card first, then try again.',
            ephemeral=True, allowed_mentions=MENTIONS)


def build_panel(config, state_dir, presentation=None):
    validate_order_config(config)
    provider = SocketProvider(config['socket'])
    store = InteractionStore(Path(state_dir) / 'order-interactions.sqlite3')
    service = OrderService(lambda number: provider.call('lookup', [number]), store)
    return OrderPanelView(config, service, presentation)


async def publish_panel(client):
    """Idempotent route-bound card; ambiguous sends require reconciliation."""
    view = client.order_panel
    if view is None:
        return
    async with view.like_lock:
        config = view.config
        channel = client.get_channel(config['channel_id'])
        if channel is None or channel.guild.id != config['guild_id']:
            return
        marker = Path(client.store.path).parent / 'order-panel.json'
        temp = marker.with_suffix('.tmp')
        embed = panel_embed(view.service.store.count(config['guild_id']), view.presentation)
        if marker.exists():
            saved = json.loads(marker.read_text(encoding='utf-8'))
            if (not isinstance(saved, dict) or set(saved) != {'guild_id', 'channel_id', 'message_id'}
                    or saved['guild_id'] != config['guild_id']
                    or saved['channel_id'] != config['channel_id']
                    or type(saved['message_id']) is not int or saved['message_id'] <= 0):
                raise ValueError('Order panel needs reconciliation')
            message = channel.get_partial_message(saved['message_id'])
            await message.edit(embed=embed, view=view, allowed_mentions=MENTIONS)
        else:
            saved = {'guild_id': config['guild_id'], 'channel_id': config['channel_id'], 'message_id': 'pending'}
            temp.write_text(json.dumps(saved), encoding='utf-8')
            temp.replace(marker)
            message = await channel.send(embed=embed, view=view, allowed_mentions=MENTIONS)
            saved['message_id'] = message.id
            temp.write_text(json.dumps(saved), encoding='utf-8')
            temp.replace(marker)
        if not REWARDS_PAUSED:
            for emoji in REACTIONS:
                await message.add_reaction(emoji)


async def handle_reaction(client, payload):
    if REWARDS_PAUSED:
        return
    view = client.order_panel
    if (view is None or payload.guild_id != view.config['guild_id']
            or payload.channel_id != view.config['channel_id']
            or str(payload.emoji) not in REACTIONS
            or payload.member is None or payload.member.bot
            or payload.member.id != payload.user_id):
        return
    marker = Path(client.store.path).parent / 'order-panel.json'
    try:
        saved = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return
    if (not isinstance(saved, dict) or saved.get('guild_id') != payload.guild_id
            or saved.get('channel_id') != payload.channel_id
            or type(saved.get('message_id')) is not int
            or saved['message_id'] != payload.message_id):
        return
    first = await asyncio.to_thread(view.service.store.first_reward,
                                    payload.guild_id, payload.user_id)
    if first:
        try:
            await payload.member.send(COUPON, allowed_mentions=MENTIONS)
        except discord.HTTPException:
            # Durable eligibility enables private recovery without repeated DMs.
            pass
