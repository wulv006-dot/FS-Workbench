"""D4 VIP interactive fixture pilot. Never calls Admin or delivers real mail/coupons."""
import asyncio
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
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
FOOT = 'D4 VIP playtest · Simulated member, inbox and coupons'
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


async def allowed(interaction, owner=None):
    ok = (interaction.guild_id == GUILD and interaction.channel_id == CHANNEL and
          (owner is None or owner == interaction.user.id))
    if not ok:
        await interaction.response.send_message('Open the test card in D4 VIP.', ephemeral=True)
    return ok


class Verify(discord.ui.Modal, title='Unlock your test drop'):
    code = discord.ui.TextInput(label='Code from the test inbox', min_length=6, max_length=6)

    def __init__(self, session):
        super().__init__(timeout=180)
        self.session = session

    async def on_submit(self, interaction):
        session = self.session
        if not await allowed(interaction, session.owner):
            return
        if session.is_finished() or not hmac.compare_digest(str(self.code).encode(),session.pin.encode()):
            await interaction.response.send_message('Code incorrect or expired. Reopen the test card.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            member, rows = fixture(session.address)
            tier, first = ClaimStore(STATE / 'claims.sqlite3').claim(
                session.owner, member, reward_tier(rows, datetime.now(timezone.utc)))
        except ValueError:
            await interaction.edit_original_response(content='One drop per Discord account and test member. Reopen with your original test email.')
            return
        session.stop()
        if first:
            await interaction.edit_original_response(embed=embed('🎰  Revealing your drop…', '⚽   ·   🎁   ·   ✨'))
            await asyncio.sleep(1.2)
        title = '🎁  Your Black Friday drop' if first else '🧾  Your original drop'
        await interaction.edit_original_response(embed=embed(title,
            f'{REWARDS[tier]}\n\n{TERMS} The 20% coupon has no discount cap.\n\n**Demo receipt** · No coupon was issued.'))


class Inbox(discord.ui.View):
    def __init__(self, owner, address, club):
        super().__init__(timeout=180)
        self.owner, self.address, self.club = owner, address, club
        self.pin = str(secrets.randbelow(900000)+100000)

    @discord.ui.button(label='Enter code & reveal', emoji='🎰', style=discord.ButtonStyle.primary)
    async def verify(self, interaction, button):
        if await allowed(interaction, self.owner):
            await interaction.response.send_modal(Verify(self))


class Email(discord.ui.Modal, title='Test member email'):
    def __init__(self, owner, club):
        super().__init__(timeout=180)
        self.owner, self.club = owner, club
        self.address = discord.ui.TextInput(label='Test email (new, return, four or five)',
            default=f'five+{owner}@example.test', max_length=64)
        self.add_item(self.address)

    async def on_submit(self, interaction):
        if not await allowed(interaction, self.owner):
            return
        address = str(self.address).strip().lower()
        try:
            fixture(address)
        except ValueError as ex:
            await interaction.response.send_message(str(ex), ephemeral=True)
            return
        inbox = Inbox(self.owner, address, self.club)
        await interaction.response.send_message(embed=embed('✉️  Test inbox',
            f'⚽ {self.club} · Your demo code is **{inbox.pin}**. Enter it within 3 minutes.\nThis inbox simulates email delivery.'), view=inbox, ephemeral=True)


class ChooseClub(discord.ui.View):
    def __init__(self, owner):
        super().__init__(timeout=180)
        self.owner = owner
        select = discord.ui.Select(placeholder='Pick your club', options=[discord.SelectOption(label=x) for x in CLUBS])
        async def pick(interaction):
            if await allowed(interaction,self.owner):
                await interaction.response.send_modal(Email(self.owner, select.values[0]))
        select.callback = pick
        self.add_item(select)


class Home(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Play the test drop', emoji='🎰', style=discord.ButtonStyle.primary, custom_id='bf26:pilot:start')
    async def play(self, interaction, button):
        if await allowed(interaction):
            await interaction.response.send_message(embed=embed('⚽  Choose your club',
                'This selection simulates the FC27 + club role check in D4 VIP. Next, use the prefilled demo email.'),
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
    marker = STATE / 'message.id'
    if getattr(client.user, 'id', None) == APP and marker.is_file():
        message = marker.read_text().strip()
        if message.isascii() and message.isdigit() and len(message) in (17,18,19,20):
            client.add_view(Home(), message_id=int(message))
