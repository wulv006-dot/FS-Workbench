"""Private Black Friday interactions in the test and configured FC27 channels."""
import asyncio
import json
from functools import partial
from pathlib import Path

import discord

from black_friday_claims import Campaign, ClaimConflict
from black_friday_pilot import CHANNEL, GUILD, STATE, REWARDS, coupon_link, fixture, show_spin
from match_rewards_delivery import CouponBridge, email_fingerprint

OFFICIAL = 1041923524601851914
MANIFEST = Path('/etc/mmoexp-fc-black-friday.json')
D4_BUTTON = 'bf26:verify'
LIVE_BUTTON = 'bf26:claim'
STATUS_BUTTON = 'bf26:receipt'
LIVE_LOCK = asyncio.Semaphore(6)
SCENARIOS = {
    'new': '$1 · No paid orders',
    'return': '$2 · One paid order',
    'four': '$2 · Five paid, four complete',
    'five': '$2 + 20% · Five complete',
}


def settings():
    return json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.is_file() else {}


def prior_entitlement():
    path = Path(__file__).with_name('d4-test-entitlement.json')
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


class TestCouponBridge:
    coupons = {'one': 11, 'two': 22, 'bonus': 33}

    def detail(self, coupon):
        mode, amount = {11: (1, 1), 22: (1, 2), 33: (2, 80)}[coupon]
        return dict(id=coupon, type=1, status=1, site_id=266, game_id=1327,
                    mode_type=mode, fetch_scene=4, time_effect=2, days=7, is_open=0,
                    repeat_qty=1, goods_id=0, product_type=0, attain=0, max_reduce=0,
                    reduce=amount, scope_bindings='')

    def grant(self, coupon, email, batch):
        return dict(state='confirmed', member_coupon_id=str(1000 + coupon))


def run_test(discord_id, scenario):
    from black_friday_orders import MEMBERS, lookup_order_history

    address = f'{scenario}+{discord_id}@example.test'
    member, orders = fixture(address)

    def fetch(path, query):
        rows = ([dict(uid=member, email=address, site_id=266)] if path == MEMBERS else [
            dict(id=row['id'], uid=member, email=address, site_id=row['site'], gid=row['game'],
                 paytime='2026-10-01 00:00:00', pay_status=1,
                 status=101 if row['status'] == 'complete' else 21)
            for row in reversed(orders)])
        return {'code': 1, 'data': {'list': rows, 'total': len(rows)}}

    lookup = partial(lookup_order_history, fetch=fetch)
    return Campaign(STATE, TestCouponBridge.coupons, lookup, TestCouponBridge(),
                    ledger=f'd4-{scenario}.sqlite3').claim(discord_id, address)


def run_live(discord_id, address, coupons, *, duplicate_only=False, resume_only=False):
    from black_friday_orders import lookup_order_history

    if duplicate_only:
        legacy = prior_entitlement()
        if (not legacy or discord_id != legacy['discord_id']
                or email_fingerprint(address.strip().lower()) != legacy['recipient_sha256']):
            raise ClaimConflict('Use the approved MMOEXP email from the first test.')
        # The D4 repeat test only reads the real ledger. It cannot initiate a new grant.
        bridge = None
    else:
        legacy = prior_entitlement()
        bridge = CouponBridge()
    campaign = Campaign(STATE, coupons, lookup_order_history, bridge, legacy=legacy)
    return campaign.claim(discord_id, address, resume_only=resume_only or duplicate_only)


def gate(interaction, clubs, *, resume_only=False):
    cfg = settings()
    if (interaction.guild_id != OFFICIAL or interaction.channel_id != cfg.get('channel_id')
            or clubs.get('guild_id') != OFFICIAL or (not resume_only and cfg.get('enabled') is not True)):
        return None
    if resume_only:
        return cfg
    roles = {role.id for role in getattr(interaction.user, 'roles', ())}
    if clubs.get('community_role_id') not in roles or not roles.intersection(clubs.get('role_ids', {}).values()):
        return False
    return cfg


async def render_receipt(interaction, receipt, *, test=False):
    if not receipt.complete:
        content = ('Contact MMOEXP support so we can check the original claim.' if receipt.rejected
                   else 'Your delivery is awaiting confirmation. Use **Check my reward** to check again.')
        if receipt.receipts:
            content = '**$2 OFF** was added to your MMOEXP account. ' + content
        await interaction.edit_original_response(content=content,
                                                 view=coupon_link() if receipt.receipts and not test else None)
        return
    receipts = ' · '.join(receipt.receipts)
    if receipt.replay:
        delivery = 'Test result · No coupon issued.' if test else 'Already added to your MMOEXP account.'
        card = discord.Embed(title='🧾  Your existing Black Friday reward',
                             description=f'{REWARDS[receipt.tier]} · {delivery}\nReceipt **{receipts}**',
                             colour=0xE4AF45)
        await interaction.edit_original_response(embed=card, view=None if test else coupon_link())
        return
    await show_spin(interaction, interaction.user.id, receipt.tier, True, receipts, test=test)


class CampaignEmail(discord.ui.Modal, title='FC27 Black Friday · Claim your drop'):
    address = discord.ui.TextInput(label='MMOEXP account email', max_length=254)

    def __init__(self, owner, clubs, *, duplicate_only=False, resume_only=False):
        super().__init__(timeout=180)
        self.owner, self.clubs, self.duplicate_only = owner, clubs, duplicate_only
        self.resume_only = resume_only

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message('Open your own claim form.', ephemeral=True)
            return
        if self.duplicate_only:
            if (interaction.guild_id, interaction.channel_id) != (GUILD, CHANNEL):
                await interaction.response.send_message('Open the test card in D4 VIP.', ephemeral=True)
                return
            coupons = TestCouponBridge.coupons
        else:
            cfg = gate(interaction, self.clubs, resume_only=self.resume_only)
            if not cfg:
                await interaction.response.send_message('Open the active FC27 drop after choosing a club.',
                                                        ephemeral=True)
                return
            coupons = cfg['coupons']
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with LIVE_LOCK:
                if not self.duplicate_only and not gate(interaction, self.clubs, resume_only=self.resume_only):
                    await interaction.edit_original_response(content='The Black Friday drop is closed.')
                    return
                receipt = await asyncio.to_thread(partial(run_live, self.owner, str(self.address), coupons,
                        duplicate_only=self.duplicate_only, resume_only=self.resume_only))
        except ClaimConflict as error:
            await interaction.edit_original_response(content=str(error))
        except Exception as error:
            print('Black Friday claim unavailable: ' + type(error).__name__, flush=True)
            await interaction.edit_original_response(content='We could not confirm your claim. Check your MMOEXP email and try again.')
        else:
            await render_receipt(interaction, receipt)


class D4Scenarios(discord.ui.View):
    @discord.ui.select(placeholder='Choose a test case',
                       options=[discord.SelectOption(label=label, value=value) for value, label in SCENARIOS.items()])
    async def case(self, interaction, select):
        if (interaction.guild_id, interaction.channel_id) != (GUILD, CHANNEL):
            await interaction.response.send_message('Open the test card in D4 VIP.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        receipt = await asyncio.to_thread(run_test, interaction.user.id, select.values[0])
        await render_receipt(interaction, receipt, test=True)


class CampaignHome(discord.ui.View):
    def __init__(self, clubs):
        super().__init__(timeout=None)
        self.clubs = clubs

    @discord.ui.button(label='Reveal my reward', emoji='🎰', style=discord.ButtonStyle.primary, custom_id=LIVE_BUTTON)
    async def live(self, interaction, button):
        cfg = gate(interaction, self.clubs)
        if cfg is None:
            await interaction.response.send_message('The Black Friday drop is closed.', ephemeral=True)
        elif cfg is False:
            link = f"https://discord.com/channels/{OFFICIAL}/{self.clubs['channel_id']}"
            await interaction.response.send_message(f'[Choose your club in FC27 Welcome]({link}), then return here.',
                                                    ephemeral=True)
        else:
            await interaction.response.send_modal(CampaignEmail(interaction.user.id, self.clubs))

    @discord.ui.button(label='Check my reward', emoji='🧾', custom_id=STATUS_BUTTON)
    async def check(self, interaction, button):
        if not gate(interaction, self.clubs, resume_only=True):
            await interaction.response.send_message('Open the FC27 Black Friday channel.', ephemeral=True)
            return
        await interaction.response.send_modal(CampaignEmail(interaction.user.id, self.clubs, resume_only=True))

    @discord.ui.button(label='Run acceptance cases', emoji='🧪', custom_id=D4_BUTTON)
    async def verify(self, interaction, button):
        if (interaction.guild_id, interaction.channel_id) == (GUILD, CHANNEL):
            await interaction.response.send_message('Choose an order history. Repeat a case to check the receipt.',
                                                    view=D4Scenarios(), ephemeral=True)
        else:
            await interaction.response.send_message('Open the test card in D4 VIP.', ephemeral=True)

    @discord.ui.button(label='Check prior real receipt', emoji='🧾', custom_id='bf26:verify:prior')
    async def prior(self, interaction, button):
        legacy = prior_entitlement()
        if ((interaction.guild_id, interaction.channel_id) != (GUILD, CHANNEL)
                or not legacy or interaction.user.id != legacy['discord_id']):
            await interaction.response.send_message('Only the original test account can open this receipt.', ephemeral=True)
        else:
            await interaction.response.send_modal(CampaignEmail(interaction.user.id, {}, duplicate_only=True))


def register_campaign(client):
    client.add_view(CampaignHome(client.config.get('club_panels', {})))
