"""D4 VIP fixtures plus an explicitly provisioned single-recipient test."""
import asyncio
import hashlib
import os
from pathlib import Path
import re
from datetime import datetime, timezone

import discord
from black_friday import ClaimStore, reward_tier

GUILD = 1565922092518613064
CHANNEL = 1568260661010497627
APP = 1568239618111832094
STATE = Path(os.environ.get('BF_PILOT_STATE', '/var/lib/fc27-black-friday-pilot'))
CLUBS = ('Manchester City', 'Real Madrid', 'Barcelona', 'Bayern Munich', 'Paris Saint-Germain')
REWARDS = {'one':'**$1 OFF**', 'two':'**$2 OFF**', 'bonus':'**$2 OFF**  +  🏆 **20% OFF**'}
TERMS = 'FC27 only · 7 days from claim · One coupon per order · No minimum spend.'
COUPONS_URL = 'https://www.mmoexp.com/Ucenter/coupon.html'
FOOT = 'D4 VIP playtest · Demo accounts and coupons'
PROFILES = {'new':(0, 0), 'return':(1, 0), 'four':(5, 4), 'five':(5, 5)}


def fixture(address):
    match = re.fullmatch(r'(new|return|four|five)\+([a-z0-9]{1,24})@example\.test',
                         address.strip().lower())
    if not match:
        raise ValueError('Use the provided test email. Never enter your real email here.')
    key = match.group(0)
    member = int.from_bytes(hashlib.sha256(key.encode()).digest()[:7], 'big') + 1
    total, completed = PROFILES[match.group(1)]
    rows = [dict(id=i+1, site=266, game=99 if i % 2 == 0 else 1327,
                 paid=True, paid_at='2026-10-01T00:00:00+08:00',
                 status='complete' if i<completed else 'open') for i in range(total)]
    return member, rows


def embed(title, body):
    card = discord.Embed(title=title, description=body, colour=0xE4AF45)
    return card.set_footer(text=FOOT)


def coupon_link():
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label='View my coupons', emoji='🎟️', url=COUPONS_URL))
    return view


async def allowed(interaction, owner=None):
    ok = (interaction.guild_id == GUILD and interaction.channel_id == CHANNEL and
          (owner is None or owner == interaction.user.id))
    if not ok:
        await interaction.response.send_message('Open the test card in D4 VIP.', ephemeral=True)
    return ok


async def show_spin(interaction, owner, tier, first, receipt=None, *, test=False):
    left, middle, right = {
        'one': ('⚽', '⭐', '🪙'),
        'two': ('⚽', '⚽', '⭐'),
        'bonus': ('🏆', '🏆', '🏆'),
    }[tier]
    frames = (
        ('🔄  │  🔄  │  🔄', 'Kick-off!', 1.6),
        (f'{left}  │  🔄  │  🔄', 'First reel locked', 1.7),
        (f'{left}  │  {middle}  │  🔄', 'One more to go…', 1.9),
    )
    for reels, caption, delay in frames:
        frame = embed('🎰  Black Friday spin', f'## {reels}\n{caption}')
        if receipt:
            frame.set_footer(text='D4 VIP · Test run' if test else 'MMOEXP account reward')
        await interaction.edit_original_response(embed=frame, view=None)
        await asyncio.sleep(delay)
    if receipt:
        title = '🎁  Your FC27 Black Friday coupon' if first else '🧾  Your existing Black Friday reward'
        delivery = 'Test result · No coupon issued.' if test else 'Added to your MMOEXP account.'
        card = discord.Embed(title=title,
            description=f'## {left}  │  {middle}  │  {right}\n{REWARDS[tier]} · {delivery}\n'
                        f'{TERMS}\nReceipt **{receipt}**', colour=0xE4AF45)
        await interaction.edit_original_response(embed=card, view=None if test else coupon_link())
        return
    title = '🎁  Your Black Friday drop' if first else '🧾  Your original drop'
    await interaction.edit_original_response(embed=embed(title,
        f'## {left}  │  {middle}  │  {right}\n{REWARDS[tier]}\n\n{TERMS} The 20% coupon has no discount cap.\n\n'
        '**Demo receipt** · Replay shows this same reward.'), view=Replay(owner, tier))


class LiveTestEmail(discord.ui.Modal, title='Claim your real D4 test coupon'):
    address = discord.ui.TextInput(label='Approved MMOEXP account email', max_length=254)

    def __init__(self, owner):
        super().__init__(timeout=180)
        self.owner = owner

    async def on_submit(self, interaction):
        if not await allowed(interaction, self.owner):
            return
        from black_friday_test_grant import issue
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            status, receipt = await asyncio.get_running_loop().run_in_executor(
                None, issue, STATE, self.owner, str(self.address))
        except ValueError as ex:
            if str(ex).startswith('Use the MMOEXP email'):
                await interaction.edit_original_response(content=str(ex))
                return
            status, receipt = 'unknown', None
        except Exception:
            status, receipt = 'unknown', None
        if status == 'confirmed':
            await show_spin(interaction, self.owner, 'two', True, receipt)
        else:
            await interaction.edit_original_response(content='Delivery has not been confirmed. The host can check the original batch.')


class Replay(discord.ui.View):
    def __init__(self, owner, tier):
        super().__init__(timeout=180)
        self.owner, self.tier = owner, tier

    @discord.ui.button(label='Replay spin', emoji='🔁', style=discord.ButtonStyle.secondary)
    async def replay(self, interaction, button):
        if not await allowed(interaction, self.owner):
            return
        await interaction.response.defer()
        if self.is_finished():
            return
        self.stop()
        await show_spin(interaction, self.owner, self.tier, False)


class Email(discord.ui.Modal, title='Test member email'):
    def __init__(self, owner, club):
        super().__init__(title=f'{club} · Enter email & spin', timeout=180)
        self.owner = owner
        self.address = discord.ui.TextInput(label='Test email (new, return, four or five)',
            default=f'five+{owner}@example.test', max_length=64)
        self.add_item(self.address)

    async def on_submit(self, interaction):
        if not await allowed(interaction, self.owner):
            return
        address = str(self.address).strip().lower()
        try:
            member, rows = fixture(address)
        except ValueError as ex:
            await interaction.response.send_message(str(ex), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            tier, first = ClaimStore(STATE / 'claims.sqlite3').claim(
                self.owner, member, reward_tier(rows, datetime.now(timezone.utc)))
        except ValueError:
            await interaction.edit_original_response(content='One drop per Discord account and test member. Reopen with your original test email.')
            return
        await show_spin(interaction, self.owner, tier, first)



class ChooseClub(discord.ui.View):
    def __init__(self, owner):
        super().__init__(timeout=180)
        self.owner = owner
        select = discord.ui.Select(placeholder='Pick your club', options=[discord.SelectOption(label=x) for x in CLUBS])
        async def pick(interaction):
            if await allowed(interaction,self.owner):
                from black_friday_test_grant import entitlement
                modal = (LiveTestEmail(self.owner) if entitlement(self.owner) else
                         Email(self.owner, select.values[0]))
                await interaction.response.send_modal(modal)
        select.callback = pick
        self.add_item(select)


class Home(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Play the test drop', emoji='🎰', style=discord.ButtonStyle.primary, custom_id='bf26:pilot:start')
    async def play(self, interaction, button):
        if await allowed(interaction):
            from black_friday_test_grant import entitlement
            card = (discord.Embed(title='⚽  D4 private coupon test',
                    description='Pick a club, then submit your approved MMOEXP email to receive your real FC27 test coupon.')
                    if entitlement(interaction.user.id) else embed('⚽  Choose your club',
                    'This selection simulates the FC27 + club role check in D4 VIP. Next, use the prefilled demo email.'))
            await interaction.response.send_message(embed=card,
                view=ChooseClub(interaction.user.id), ephemeral=True)

    @discord.ui.button(label='See all test cases', emoji='📋', style=discord.ButtonStyle.secondary, custom_id='bf26:pilot:examples')
    async def examples(self, interaction, button):
        if await allowed(interaction):
            await interaction.response.send_message(embed=embed('📋  Test cases',
                '**new** · No paid orders → $1\n**return** · One paid order in another game → $2\n'
                '**four** · Five paid, four completed → $2\n**five** · Five completed → $2 + 20%\n\n'
                'Replace the part before + in the demo email to choose a case before your first claim. '
                'Repeat your original email to view your receipt.'), ephemeral=True)


def register_pilot(client):
    if getattr(client.user, 'id', None) == APP:
        from black_friday_discord import register_campaign
        register_campaign(client)
    marker = STATE / 'message.id'
    if getattr(client.user, 'id', None) == APP and marker.is_file():
        message = marker.read_text().strip()
        if message.isascii() and message.isdigit() and len(message) in (17,18,19,20):
            client.add_view(Home(), message_id=int(message))
