"""Private MMOEXP price panels restricted to configured guild and channel routes."""
import asyncio
import re
import threading
import time
from collections import deque
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import discord

from club_panel import brand_embed

TEST_GUILD = 1565922092518613064
OFFICIAL_GUILD = 1041923524601851914
FC_ROLE_IDS = frozenset((1263726836160925696, 1568664882650288159))
FC_WELCOME_CHANNEL = 1568663362567413820
MENTIONS = discord.AllowedMentions.none()
CATEGORIES = {
    'sbc': ('SBC', '🧩', 0xF28C28, 'Find the SBC service that fits your squad.'),
    'packs': ('Packs', '🎁', 0x8B5CF6, 'Explore in-game packs and their current prices.'),
    'gallery': ('Gallery', '🖼️', 0x20B8A6, 'Explore Gallery services and their current prices.'),
    'evolutions': ('Evolutions', '🧬', 0x23A85D, 'Explore Evolution services and their current prices.'),
    'boosting': ('Boosting', '🏆', 0xDAA520, 'Explore Boosting services and their starting prices.'),
    'coins': ('Coins', '🪙', 0xD29A21, 'Choose a Coins amount and check its current price.'),
    'players': ('Players', '⚽', 0x2688E8, 'Find your next player. Compare versions and live prices.'),
}
HUB_KINDS = ('evolutions', 'boosting', 'gallery', 'packs')
PLATFORMS = ('PC', 'Xbox Series X|S', 'PlayStation 5')
PLATFORM_EMOJI = {'PC': '🖥️', 'Xbox Series X|S': '🟢', 'PlayStation 5': '🎮'}
PROVIDER_LIMIT = threading.BoundedSemaphore(3)
QUERY_TIMES = {}
QUERY_ORDER = deque()
QUERY_INTERVAL = 3
MAX_QUERY_USERS = 10000
ICON_KEYS = frozenset(CATEGORIES) | {'clock', 'search', 'external', 'platform'}
CUSTOM_ICON = re.compile(r'<a?:[A-Za-z0-9_]{2,32}:[1-9][0-9]{16,19}>')


def presentation_icon(key, fallback, presentation=None):
    """Use application emoji where Discord renders them; retain safe defaults."""
    value = (presentation or {}).get('icons', {}).get(key)
    return value if isinstance(value, str) and CUSTOM_ICON.fullmatch(value) else fallback


class ProviderBusy(Exception):
    pass


def begin_query(user):
    now = time.monotonic()
    while QUERY_ORDER and (now - QUERY_ORDER[0][0] >= QUERY_INTERVAL or len(QUERY_ORDER) >= MAX_QUERY_USERS):
        stamp, old_user = QUERY_ORDER.popleft()
        if QUERY_TIMES.get(old_user) == stamp:
            del QUERY_TIMES[old_user]
    if user in QUERY_TIMES:
        return None
    QUERY_TIMES[user] = now
    QUERY_ORDER.append((now, user))
    return now


async def call_provider(action, *args):
    if not PROVIDER_LIMIT.acquire(blocking=False):
        raise ProviderBusy()
    def run():
        try:
            return action(*args)
        finally:
            PROVIDER_LIMIT.release()
    try:
        future = asyncio.get_running_loop().run_in_executor(None, run)
    except Exception:
        PROVIDER_LIMIT.release()
        raise
    return await asyncio.shield(future)


def category_embed(kind, presentation=None):
    label, emoji, color, description = CATEGORIES[kind]
    choice = 'service' if kind == 'boosting' else 'amount' if kind == 'coins' else 'product'
    instruction = 'Choose {} & platform · Private live quote'.format(choice)
    icon = presentation_icon(kind, emoji, presentation)
    result = discord.Embed(title=label,
        description='{}  {}\n\n{}'.format(icon, description, instruction),
        color=color)
    result.set_footer(text='MMOEXP · Final price at checkout')
    return brand_embed(result, {key: value for key, value in (presentation or {}).items()
                               if key != 'banner_url'})


def hub_embed(presentation=None):
    """A single public entry for EasySBC updates and private MMOEXP quotes."""
    result = discord.Embed(
        title='FC27 · Objectives & Packs',
        description=('New Evolutions, Objectives, Gallery tiers and Store Packs appear here.\n'
                     'Choose a category below for a **private live price**.'),
        color=0x2688E8)
    result.set_footer(text='MMOEXP · Final price at checkout')
    return brand_embed(result, {key: value for key, value in (presentation or {}).items()
                               if key != 'banner_url'})


def entries(rows):
    result = {}
    for row in rows:
        key, title = str(row['id']), str(row['title']).strip()
        if key and len(key) <= 100 and title and key not in result:
            result[key] = title[:100]
    return result


def validate_quote(quote, kind):
    url = quote['url']
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('Invalid URL')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in ('mmoexp.com', 'www.mmoexp.com')
            or parts.username is not None or parts.password is not None or parts.port not in (None, 443)):
        raise ValueError('Invalid URL')
    amount = quote['amount']
    if not isinstance(amount, str) or len(amount) > 32 or not re.fullmatch(r'\d+(?:\.\d{1,2})?', amount):
        raise ValueError('Invalid amount')
    try:
        if not Decimal(amount).is_finite() or Decimal(amount) <= 0:
            raise ValueError('Invalid amount')
    except InvalidOperation:
        raise ValueError('Invalid amount')
    if (quote['price_basis'] != ('from' if kind == 'boosting' else 'sale')
            or not re.fullmatch(r'[A-Z]{3}', quote['currency'])
            or not isinstance(quote['queried_at'], int) or isinstance(quote['queried_at'], bool)
            or quote['queried_at'] <= 0 or not isinstance(quote['title'], str) or not quote['title'].strip()
            or len(quote['title']) > 512
            or not isinstance(quote['option_label'], str) or not quote['option_label'].strip()):
        raise ValueError('Invalid quote')
    return quote


class GuardedView(discord.ui.View):
    def __init__(self, provider, owner=None, kind=None, allowed_routes=None, presentation=None):
        super().__init__(timeout=None if owner is None else 180)
        self.provider, self.owner = provider, owner
        self.kind = kind
        self.presentation = dict(presentation or {})
        self.allowed_routes = (None if allowed_routes is None else
                               {guild: dict(channels) for guild, channels in allowed_routes.items()})

    async def interaction_check(self, interaction):
        permitted = (interaction.guild_id == TEST_GUILD if self.allowed_routes is None else
                     self.allowed_routes.get(interaction.guild_id, {}).get(interaction.channel_id) == self.kind)
        if (not permitted or interaction.channel_id is None or interaction.user.bot
                or (self.owner is not None and interaction.user.id != self.owner)):
            await interaction.response.send_message('This menu is not available to you.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return False
        if interaction.guild_id == OFFICIAL_GUILD:
            roles = getattr(interaction.user, 'roles', ())
            permissions = getattr(interaction.user, 'guild_permissions', None)
            if not (permissions and permissions.administrator) and not any(
                    role.id in FC_ROLE_IDS for role in roles):
                await interaction.response.send_message(
                    f'Join FC27 in <#{FC_WELCOME_CHANNEL}> to use this card.', ephemeral=True,
                    allowed_mentions=MENTIONS)
                return False
        return True


class QuoteHomeView(GuardedView):
    """Keep the old persistent entry usable while directing users to category cards."""
    def __init__(self, provider):
        super().__init__(provider)

    @discord.ui.button(label='Browse prices', style=discord.ButtonStyle.primary, custom_id='fc:quote:open')
    async def open(self, interaction, button):
        await interaction.response.send_message('Choose the SBC, Packs, or Gallery card to browse prices.',
                                                ephemeral=True, allowed_mentions=MENTIONS)


class CategoryHomeView(GuardedView):
    def __init__(self, provider, kind, allowed_routes=None, presentation=None):
        if kind not in CATEGORIES:
            raise ValueError('Unsupported category')
        super().__init__(provider, kind=kind, allowed_routes=allowed_routes, presentation=presentation)
        self.add_item(OpenButton(kind, presentation))


class HubHomeView(GuardedView):
    """Public hub buttons, each opening an owner-only category quote panel."""
    def __init__(self, provider, guild_id, channel_id, presentation=None, extra_channels=None):
        routes = {guild_id: {channel_id: 'hub'}}
        for extra_guild, extra_channel in (extra_channels or {}).items():
            routes.setdefault(extra_guild, {})[extra_channel] = 'hub'
        super().__init__(provider, kind='hub',
                         allowed_routes=routes,
                         presentation=presentation)
        for kind in HUB_KINDS:
            self.add_item(HubOpenButton(kind, presentation))


class HubOpenButton(discord.ui.Button):
    def __init__(self, kind, presentation=None):
        labels = {'evolutions': 'Evolutions', 'boosting': 'Objectives / Boosting',
                  'gallery': 'Gallery tiers', 'packs': 'Store packs'}
        super().__init__(label=labels[kind],
                         emoji=presentation_icon(kind, CATEGORIES[kind][1], presentation),
                         style=discord.ButtonStyle.primary,
                         custom_id='fc:hub:' + kind)
        self.kind = kind

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        routes = {interaction.guild_id: {interaction.channel_id: self.kind}}
        await load_catalog(interaction, self.view.provider, self.kind,
                           interaction.user.id, routes, self.view.presentation)


class OpenButton(discord.ui.Button):
    def __init__(self, kind, presentation=None, button_label=None, row=None):
        label, emoji, _, _ = CATEGORIES[kind]
        super().__init__(label=button_label or 'Browse ' + label, emoji=presentation_icon(kind, emoji, presentation),
                         style=discord.ButtonStyle.primary,
                         custom_id='fc:quote:' + kind, row=row)
        self.kind = kind

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await load_catalog(interaction, self.view.provider, self.kind, interaction.user.id,
                           self.view.allowed_routes, self.view.presentation)


async def load_catalog(interaction, provider, kind, owner, allowed_routes, presentation=None):
    if kind == 'players':
        from player_panel import load_players
        source = GuardedView(provider, owner, kind, allowed_routes, presentation)
        await load_players(interaction, source, 'featured', '', 1)
        source.stop()
        return
    try:
        rows = entries(await call_provider(provider.catalog, kind))
        message = None if rows else 'No products are available yet. Try reloading later.'
    except ProviderBusy:
        rows, message = {}, 'Price service is busy. Please try reloading shortly.'
    except Exception:
        rows, message = {}, 'Products are unavailable. Please try reloading.'
    panel = QuoteView(provider, owner, kind, rows, allowed_routes=allowed_routes, presentation=presentation)
    panel.interaction = interaction
    await interaction.edit_original_response(embed=panel_embed(panel, message), view=panel,
                                             allowed_mentions=MENTIONS)


def panel_embed(view, message=None):
    label, emoji, color, _ = CATEGORIES[view.kind]
    product = view.rows.get(view.product, 'Not selected')
    field = 'Amount' if view.kind == 'coins' else 'Service' if view.kind == 'boosting' else 'Product'
    icon = presentation_icon(view.kind, emoji, view.presentation)
    title = label + ' prices'
    fields = []
    if view.quote and not message:
        q = view.quote
        price = '${} USD'.format(q['amount']) if q['currency'] == 'USD' else '{} {}'.format(q['amount'], q['currency'])
        title = '💰 ' + ('From ' if view.kind == 'boosting' else '') + price
        description = '{}  **{}**'.format(icon, discord.utils.escape_markdown(q['title']))
        if view.kind == 'boosting':
            description += '\nChoose service details on the website.'
    else:
        description = '{}  {}'.format(icon, message or 'Choose {} & platform, then Get price.'.format(field.lower()))
        fields.append((field, discord.utils.escape_markdown(product), False))
    fields.append(('{}  Platform'.format(presentation_icon('platform', '🎮', view.presentation)),
                   '{} {}'.format(platform_emoji(view.platform, view.presentation), view.platform)
                   if view.platform else 'Not selected', True))
    if view.quote and not message:
        fields.append(('{}  Last checked'.format(presentation_icon('clock', '🕒', view.presentation)),
                       '<t:{0}:f> · <t:{0}:R>'.format(view.quote['queried_at']), True))
    result = discord.Embed(title=title, description=description, color=color)
    for name, value, inline in fields:
        result.add_field(name=name, value=value, inline=inline)
    result.set_footer(text='Private · Expires after 3 minutes of inactivity · Final price at checkout')
    return brand_embed(result, {key: value for key, value in view.presentation.items() if key != 'banner_url'})


def platform_emoji(platform, presentation=None):
    return (presentation or {}).get('emoji', {}).get(platform, PLATFORM_EMOJI.get(platform, '🎮'))


class QuoteView(GuardedView):
    def __init__(self, provider, owner, kind, rows, page=0, product=None, platform=None, quote=None,
                 allowed_routes=None, presentation=None):
        super().__init__(provider, owner, kind, allowed_routes, presentation)
        self.rows, self.page = rows, page
        self.product, self.platform, self.quote = product, platform, quote
        self.interaction = None
        self.superseded = False
        self.add_item(ProductSelect(self))
        self.add_item(PlatformSelect(self))
        if page:
            self.add_item(PageButton('Previous', -1))
        if (page + 1) * 25 < len(rows):
            self.add_item(PageButton('Next', 1))
        self.add_item(PriceButton(disabled=not product or not platform, presentation=self.presentation))
        if quote:
            self.add_item(discord.ui.Button(label='Open MMOEXP', url=quote['url'], row=2,
                emoji=presentation_icon('external', '🔗', self.presentation)))
        self.add_item(ReloadButton())
        refresh = OpenButton(kind, self.presentation, button_label='Refresh quote', row=3)
        refresh.emoji = '🔄'
        self.add_item(refresh)

    def retire(self):
        self.superseded = True
        self.stop()

    async def on_timeout(self):
        if self.superseded or self.interaction is None:
            return
        self.quote = None  # An expired panel must not look like a current price.
        for item in self.children:
            keep = (isinstance(item, discord.ui.Button) and
                    (item.url or item.custom_id == 'fc:quote:' + self.kind))
            item.disabled = not keep
        embed = panel_embed(self, 'Tap **🔄 Refresh quote** below.')
        embed.title = '⏱️ Quote expired'
        embed.set_footer(text='Private')
        try:
            await self.interaction.edit_original_response(embed=embed, view=self, allowed_mentions=MENTIONS)
        except (discord.HTTPException, discord.ClientException):
            # The original ephemeral token may have expired or the message was dismissed.
            # The fixed Refresh quote button still routes through CategoryHomeView.
            pass

    def copy(self, **changes):
        self.retire()
        values = dict(provider=self.provider, owner=self.owner, kind=self.kind, rows=self.rows,
                      page=self.page, product=self.product, platform=self.platform, quote=self.quote,
                      allowed_routes=self.allowed_routes, presentation=self.presentation)
        values.update(changes)
        return QuoteView(**values)


class ProductSelect(discord.ui.Select):
    def __init__(self, view):
        choices = list(view.rows.items())[view.page * 25:(view.page + 1) * 25]
        options = [discord.SelectOption(label=title, value=key, default=key == view.product)
                   for key, title in choices]
        placeholder = ('Choose an amount' if view.kind == 'coins' else
                       'Choose a service' if view.kind == 'boosting' else 'Choose a product')
        super().__init__(placeholder=placeholder,
            row=0, disabled=not choices,
            options=options or [discord.SelectOption(label='No products available', value='unavailable')])

    async def callback(self, interaction):
        view = self.view
        selected = self.values[0]
        if selected not in dict(list(view.rows.items())[view.page * 25:(view.page + 1) * 25]):
            await interaction.response.send_message('That selection is unavailable.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return
        result = view.copy(product=selected, quote=None)
        result.interaction = interaction
        await interaction.response.edit_message(embed=panel_embed(result), view=result, allowed_mentions=MENTIONS)


class PlatformSelect(discord.ui.Select):
    def __init__(self, view):
        super().__init__(placeholder='Choose a platform', row=1, options=[
            discord.SelectOption(label=label, value=label, default=label == view.platform,
                                 emoji=platform_emoji(label, view.presentation)) for label in PLATFORMS])

    async def callback(self, interaction):
        if self.values[0] not in PLATFORMS:
            await interaction.response.send_message('That selection is unavailable.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return
        result = self.view.copy(platform=self.values[0], quote=None)
        result.interaction = interaction
        await interaction.response.edit_message(embed=panel_embed(result), view=result, allowed_mentions=MENTIONS)


class PageButton(discord.ui.Button):
    def __init__(self, label, offset):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=2)
        self.offset = offset

    async def callback(self, interaction):
        result = self.view.copy(page=self.view.page + self.offset)
        result.interaction = interaction
        await interaction.response.edit_message(embed=panel_embed(result), view=result, allowed_mentions=MENTIONS)


class PriceButton(discord.ui.Button):
    def __init__(self, disabled, presentation=None):
        super().__init__(label='Get price', style=discord.ButtonStyle.primary, row=2, disabled=disabled,
                         emoji=presentation_icon('search', '🔍', presentation))

    async def callback(self, interaction):
        view = self.view
        if view.product not in view.rows or view.platform not in PLATFORMS:
            await interaction.response.send_message('Choose a product and platform first.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return
        stamp = begin_query(interaction.user.id)
        if stamp is None:
            await interaction.response.send_message('Please wait a few seconds before checking another price.',
                                                    ephemeral=True, allowed_mentions=MENTIONS)
            return
        await interaction.response.defer()
        view.retire()
        try:
            quote = await call_provider(fetch_quote, view.provider, view.product, view.platform, view.kind)
            result = view.copy(quote=quote)
            message = None
        except ProviderBusy:
            if QUERY_TIMES.get(interaction.user.id) == stamp:
                del QUERY_TIMES[interaction.user.id]
            result = view.copy(quote=None)
            message = 'Price service is busy. Please try again shortly.'
        except Exception:
            result = view.copy(quote=None)
            message = 'Price is unavailable for this selection. Please try again.'
        result.interaction = interaction
        await interaction.edit_original_response(embed=panel_embed(result, message), view=result,
                                                 allowed_mentions=MENTIONS)


def fetch_quote(provider, product, platform, kind):
    if kind == 'players' and hasattr(provider, 'quote_for_platform'):
        quote = validate_quote(provider.quote_for_platform(product, platform), kind)
        if quote['option_label'] != platform:
            raise ValueError('Mismatched platform')
        return quote
    options = provider.options(product)
    matches = [str(row['id']) for row in options if row['label'] == platform]
    if len(matches) != 1 or not matches[0]:
        raise ValueError('Unavailable or ambiguous option')
    quote = validate_quote(provider.quote(product, matches[0]), kind)
    if quote['option_label'] != platform:
        raise ValueError('Mismatched platform')
    return quote


class ReloadButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='Reload products', style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction):
        view = self.view
        await interaction.response.defer()
        view.retire()
        await load_catalog(interaction, view.provider, view.kind, view.owner, view.allowed_routes, view.presentation)
