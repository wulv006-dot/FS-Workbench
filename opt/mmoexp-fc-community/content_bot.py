"""FC27 content pilot. --check is offline; live start requires explicit opt-in."""
import argparse
import asyncio
import json
import io
import os
import re
import time
from collections import OrderedDict
from pathlib import Path

import discord
from discord import app_commands
from community import CommunityStore, CommunityError

TEST_GUILD = 1565922092518613064
OFFICIAL_GUILD = 1041923524601851914
QUOTE_KINDS = ('sbc', 'packs', 'gallery', 'evolutions', 'boosting', 'coins')


def validate_config(config):
    if config.get('alert_preferences'):
        from alert_panel import validate_alert_config
        alerts = validate_alert_config(config['alert_preferences'])
        if alerts['guild_id'] not in (TEST_GUILD, OFFICIAL_GUILD):
            raise ValueError('Invalid alerts guild')
    if config.get('guild_id') != TEST_GUILD:
        raise ValueError('Only the designated test guild is allowed.')
    staff = config.get('staff_user_ids')
    if not isinstance(staff, list) or any(not isinstance(v, str) or not re.fullmatch(r'[1-9][0-9]{16,19}', v) for v in staff):
        raise ValueError('staff_user_ids must contain Discord user ID strings.')
    presentation = config.get('quote_presentation')
    if presentation is not None:
        from club_panel import brand_embed
        if (not isinstance(presentation, dict) or set(presentation) - {'avatar_url', 'banner_url', 'emoji', 'icons'}
                or any(not isinstance(presentation[key], str) for key in ('avatar_url', 'banner_url')
                       if key in presentation)
                or not isinstance(presentation.get('emoji', {}), dict)
                or set(presentation.get('emoji', {})) - {'PC', 'Xbox Series X|S', 'PlayStation 5'}
                or any(not isinstance(value, str) or not value.strip() or len(value) > 128
                       for value in presentation.get('emoji', {}).values())
                or not isinstance(presentation.get('icons', {}), dict)
                or set(presentation.get('icons', {})) - {'sbc', 'packs', 'gallery', 'evolutions', 'boosting',
                                                        'coins', 'clock', 'search', 'external', 'platform'}
                or any(not isinstance(value, str) or not re.fullmatch(r'<a?:[A-Za-z0-9_]{2,32}:[1-9][0-9]{16,19}>', value)
                       for value in presentation.get('icons', {}).values())):
            raise ValueError('Invalid quote presentation.')
        brand_embed(discord.Embed(), presentation)
    clubs = config.get('club_panels')
    if clubs is not None:
        from club_panel import CLUBS
        known = {slug for rows in CLUBS.values() for slug, _ in rows}
        if (not isinstance(clubs, dict)
                or not {'guild_id', 'channel_id', 'role_ids', 'emoji_map'} <= set(clubs)
                or set(clubs) - {'guild_id', 'channel_id', 'role_ids', 'emoji_map', 'community_role_id'}
                or type(clubs['guild_id']) is not int or clubs['guild_id'] not in (TEST_GUILD, OFFICIAL_GUILD)
                or type(clubs['channel_id']) is not int or not 10**16 <= clubs['channel_id'] < 10**20
                or not isinstance(clubs['role_ids'], dict) or set(clubs['role_ids']) - known
                or any(type(value) is not int or not 10**16 <= value < 10**20
                       for value in clubs['role_ids'].values())
                or len(set(clubs['role_ids'].values())) != len(clubs['role_ids'])
                or ('community_role_id' in clubs and (type(clubs['community_role_id']) is not int
                    or not 10**16 <= clubs['community_role_id'] < 10**20
                    or clubs['community_role_id'] in clubs['role_ids'].values()))
                or not isinstance(clubs['emoji_map'], dict) or set(clubs['emoji_map']) - known
                or any(not isinstance(value, str) or not value.strip() or len(value) > 128
                       for value in clubs['emoji_map'].values())):
            raise ValueError('Invalid club panels configuration.')
    news = config.get('news_publish')
    if news is not None:
        from news_feed import validate_config as validate_news_config
        if not isinstance(news, dict) or news.get('guild_id') not in (TEST_GUILD, OFFICIAL_GUILD):
            raise ValueError('Invalid news publishing guild.')
        validate_news_config(news, guild_id=news['guild_id'])
    panels = config.get('information_panels')
    if panels is not None:
        if not isinstance(panels, dict):
            raise ValueError('Invalid information panels configuration.')
        guild = panels.get('guild_id')
        channels = panels.get('channels')
        database = panels.get('database')
        if (type(guild) is not int or guild == TEST_GUILD or not 10**16 <= guild < 10**20
                or not isinstance(channels, dict) or len(channels) != 6
                or any(not isinstance(channel, str) or not re.fullmatch(r'[1-9][0-9]{16,19}', channel)
                       or not isinstance(kind, str)
                       or kind not in {'news', 'sbc', 'evolutions', 'objectives', 'collection', 'store'}
                       for channel, kind in channels.items())
                or len(set(channels.values())) != 6
                or not isinstance(database, str) or not database.strip()
                or Path(database).resolve() == Path(config.get('database', 'var/community.sqlite3')).resolve()):
            raise ValueError('Information panels require a separate guild, six channels and a separate database.')
    relay = config.get('quote_relay')
    if relay is not None:
        if (not isinstance(relay, dict) or relay.get('guild_id') not in (TEST_GUILD, OFFICIAL_GUILD)
                or not config.get('quote_socket') or not isinstance(relay.get('channels'), dict)
                or not 1 <= len(relay['channels']) <= 5
                or any(not isinstance(c, str) or not re.fullmatch(r'[1-9][0-9]{16,19}', c)
                       or not isinstance(k, str) or k not in QUOTE_KINDS[:-1]
                       for c, k in relay['channels'].items())
                or len(set(relay['channels'].values())) != len(relay['channels'])):
            raise ValueError('Invalid quote relay routes.')
    static = config.get('quote_static')
    if static is not None:
        if (not isinstance(static, dict) or set(static) != {'guild_id', 'channels'}
                or static['guild_id'] not in (TEST_GUILD, OFFICIAL_GUILD) or not config.get('quote_socket')
                or not isinstance(static['channels'], dict) or len(static['channels']) != 1
                or any(not isinstance(c, str) or not re.fullmatch(r'[1-9][0-9]{16,19}', c) or k != 'coins'
                       for c, k in static['channels'].items())
                or (relay is not None and set(static['channels']) & set(relay['channels']))
                or (static['guild_id'] == TEST_GUILD
                    and str(config.get('quote_channel_id', '')) in static['channels'])):
            raise ValueError('Invalid static quote route.')
    return config


def load_config(path):
    return validate_config(json.loads(Path(path).read_text(encoding='utf-8')))


def render_item(item):
    embed = discord.Embed(title=item['title'], description=item['body'], color=0xF28C28)
    embed.add_field(name='Source', value=item['source'], inline=False)
    embed.set_footer(text=f"FC27 · {item['kind']} · #{item['id']} · {item['status']}")
    if item.get('reviewed'):
        embed.add_field(name='Reviewed', value=f"<t:{item['reviewed']}:f>")
    return embed


class ContentClient(discord.Client):
    def __init__(self, config, store, information_store=None):
        validate_config(config)
        if config.get('information_panels') and (information_store is None or
                Path(information_store.path).resolve() == Path(store.path).resolve()):
            raise ValueError('Information panels require a separate information store.')
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.store = store
        self.rate = OrderedDict()
        self.mention_rate = OrderedDict()
        self.config = config
        self.information_store = information_store
        self.information_lock = asyncio.Lock()
        self.quote_lock = asyncio.Lock()
        self.club_lock = asyncio.Lock()
        self.quote_provider = None
        self.quote_relay = None
        self.relay_task = None
        self.news_store = None
        self.news_tasks = []
        self.news_recovered = False
        if config.get('news_publish'):
            from news_feed import NewsStore
            self.news_store = NewsStore(Path(store.path).parent / 'news.sqlite3')
        if config.get('quote_socket'):
            from quote_bridge import SocketProvider
            self.quote_provider = SocketProvider(config['quote_socket'])
        if config.get('quote_relay'):
            from quote_relay import RelayStore
            relay = config['quote_relay']
            self.quote_relay = RelayStore(Path(store.path).parent / 'quote-relay.sqlite3',
                routes={int(c): k for c, k in relay['channels'].items()}, guild_id=relay['guild_id'])

    def quote_routes(self, kind):
        routes = {}
        relay = self.config.get('quote_relay')
        if relay:
            routes.setdefault(relay['guild_id'], {}).update({int(c): k for c, k in relay['channels'].items()})
        static = self.config.get('quote_static')
        if static:
            routes.setdefault(static['guild_id'], {}).update({int(c): k for c, k in static['channels'].items()})
        routes.setdefault(TEST_GUILD, {})[int(self.config.get('quote_channel_id', 0))] = kind
        return routes

    async def setup_hook(self):
        if self.config.get('alert_preferences'):
            from alert_panel import AlertHomeView
            self.add_view(AlertHomeView(self.config['alert_preferences']))
        from fut_panel import FutHomeView
        self.add_view(FutHomeView(self.store))
        if self.quote_provider:
            from quote_panel import CategoryHomeView
            for kind in QUOTE_KINDS:
                self.add_view(CategoryHomeView(self.quote_provider, kind, allowed_routes=self.quote_routes(kind),
                                              presentation=self.config.get('quote_presentation')))
        if self.config.get('club_panels'):
            from club_panel import ClubPanelView
            from onboarding_panel import WelcomeView, ClubSectionView, PopularClubView
            clubs = self.config['club_panels']
            self.add_view(WelcomeView(clubs))
            self.add_view(ClubSectionView(clubs))
            self.add_view(PopularClubView(clubs))
            for section in ('england', 'europe'):
                self.add_view(ClubPanelView(clubs['guild_id'], clubs['channel_id'], section,
                                           clubs['role_ids'], clubs['emoji_map'],
                                           community_role_id=clubs.get('community_role_id')))
        if self.config.get('information_panels'):
            from fut_panel import InformationPanelView
            panels = self.config['information_panels']
            self.add_view(InformationPanelView(self.information_store, panels['guild_id'], panels['channels']))
        # Guild commands only. Never sync globally or register on the production guild.
        await self.tree.sync(guild=discord.Object(TEST_GUILD))
        if self.quote_relay:
            self.relay_task = asyncio.create_task(self.run_quote_relay())
        if self.news_store:
            if not self.news_recovered:
                self.news_store.recover_sending()
                self.news_recovered = True
            if not self.news_tasks:
                self.news_tasks = [asyncio.create_task(self.run_news_collection()),
                                   asyncio.create_task(self.run_news_publication())]

    async def close(self):
        tasks = list(self.news_tasks) + ([self.relay_task] if self.relay_task else [])
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await super().close()

    async def run_quote_relay(self):
        await self.wait_until_ready()
        while not self.is_closed():
            if self.is_ready():
                try:
                    await self.flush_quote_relay()
                except Exception as exc:
                    print('Quote relay loop failed: ' + type(exc).__name__, flush=True)
            await asyncio.sleep(5)

    async def collect_news_once(self):
        from news_feed import collect_cycle
        return await asyncio.to_thread(collect_cycle, self.news_store, self.config['news_publish'])

    async def run_news_collection(self):
        await self.wait_until_ready()
        while not self.is_closed():
            if self.is_ready() and self.config['news_publish']['enabled']:
                try:
                    await self.collect_news_once()
                except Exception as exc:
                    print('News collection failed: ' + type(exc).__name__, flush=True)
            # Due time is persisted, so restarts/configuration saves cannot replenish the round.
            await asyncio.sleep(30)

    async def run_news_publication(self):
        await self.wait_until_ready()
        while not self.is_closed():
            if self.is_ready():
                try:
                    await self.flush_news()
                except Exception as exc:
                    print('News publication failed: ' + type(exc).__name__, flush=True)
            await asyncio.sleep(5)

    async def send_news(self, item, channel_id):
        from news_feed import DefinitelyNotSent, news_embed, validate_item
        settings = self.config['news_publish']
        channel = self.get_channel(channel_id)
        if (channel_id != int(settings['channel_id'])
                or settings['guild_id'] not in (TEST_GUILD, OFFICIAL_GUILD)
                or not channel or channel.id != channel_id or channel.guild.id != settings['guild_id']):
            raise DefinitelyNotSent('Configured news route unavailable')
        validate_item(item)
        message = await channel.send(embed=news_embed(item), allowed_mentions=discord.AllowedMentions.none())
        return message.id

    async def flush_news(self):
        from news_feed import publish_pending
        settings = self.config['news_publish']
        channel_id = int(settings['channel_id'])
        channel = self.get_channel(channel_id)
        if (not channel or channel.id != channel_id
                or channel.guild.id != settings['guild_id']
                or settings['guild_id'] not in (TEST_GUILD, OFFICIAL_GUILD)):
            return 0
        return await publish_pending(self.news_store, settings['channel_id'], self.send_news,
                                     auto_enabled=settings['enabled'])

    async def flush_quote_relay(self):
        from quote_panel import CategoryHomeView, category_embed
        for item in self.quote_relay.due(time.time()):
            channel = self.get_channel(item['channel_id'])
            if not channel or channel.guild.id != self.config['quote_relay']['guild_id']:
                continue
            claimed = self.quote_relay.claim(item['channel_id'], time.time())
            if not claimed:
                continue
            try:
                await channel.send(embed=category_embed(claimed['kind'], self.config.get('quote_presentation')),
                    view=CategoryHomeView(self.quote_provider, claimed['kind'],
                                          allowed_routes=self.quote_routes(claimed['kind']),
                                          presentation=self.config.get('quote_presentation')),
                    allowed_mentions=discord.AllowedMentions.none())
                self.quote_relay.complete(item['channel_id'], claimed['message_id'], time.time())
                print('Quote relay sent: ' + str(item['channel_id']), flush=True)
            except Exception as exc:
                self.quote_relay.fail(item['channel_id'], claimed['message_id'], time.time())
                print('Quote relay send failed: ' + type(exc).__name__, flush=True)

    async def on_ready(self):
        status = {'connected': True, 'pid': os.getpid(), 'bot_id': self.user.id,
                  'guild_id': TEST_GUILD, 'test_guild_present': self.get_guild(TEST_GUILD) is not None,
                  'ready_at': int(time.time())}
        path = Path(self.store.path).parent / 'ready.json'
        path.write_text(json.dumps(status), encoding='utf-8')
        channel_id = self.config.get('home_channel_id')
        if channel_id:
            from fut_panel import FutHomeView, home_embed
            channel = self.get_channel(int(channel_id))
            if channel and channel.guild.id == TEST_GUILD:
                marker = path.parent / 'home-panel.json'
                try:
                    if marker.exists():
                        message_id = json.loads(marker.read_text())['message_id']
                        await channel.get_partial_message(int(message_id)).edit(embed=home_embed(), view=FutHomeView(self.store))
                    else:
                        message = await channel.send(embed=home_embed(), view=FutHomeView(self.store),
                                                     allowed_mentions=discord.AllowedMentions.none())
                        marker.write_text(json.dumps({'message_id': message.id}), encoding='utf-8')
                except Exception as exc:
                    print('Home panel setup failed: ' + type(exc).__name__, flush=True)

        if self.config.get('information_panels'):
            await self.setup_information_panels()
        if self.quote_provider:
            await self.setup_quote_panel()
            if self.config.get('quote_static'):
                await self.setup_quote_static_panel()
        if self.config.get('club_panels'):
            await self.setup_club_panels()

    async def setup_quote_panel(self):
        from quote_panel import CategoryHomeView, category_embed
        channel = self.get_channel(int(self.config.get('quote_channel_id', 0)))
        if not channel or channel.guild.id != TEST_GUILD or not self.quote_provider:
            return
        directory = Path(self.store.path).parent
        marker = directory / 'quote-panels-v2.json'
        async with self.quote_lock:
            try:
                saved = json.loads(marker.read_text()) if marker.exists() else {}
                kinds = QUOTE_KINDS
                if (not isinstance(saved, dict) or any(kind not in kinds for kind in saved)
                        or any(type(value) is not int or value <= 0 for value in saved.values())):
                    print('Quote panel needs reconciliation.', flush=True)
                    return
                for kind in kinds:
                    presentation = self.config.get('quote_presentation')
                    options = dict(embed=category_embed(kind, presentation),
                                   view=CategoryHomeView(self.quote_provider, kind,
                                                        allowed_routes=self.quote_routes(kind),
                                                        presentation=presentation),
                                   allowed_mentions=discord.AllowedMentions.none())
                    if kind in saved:
                        await channel.get_partial_message(saved[kind]).edit(**options)
                    else:
                        temp = marker.with_suffix('.tmp')
                        saved[kind] = 'pending'
                        temp.write_text(json.dumps(saved))
                        temp.replace(marker)
                        message = await channel.send(**options)
                        saved[kind] = message.id
                        temp.write_text(json.dumps(saved))
                        temp.replace(marker)
                old_marker = directory / 'quote-panel.json'
                if old_marker.exists():
                    old = json.loads(old_marker.read_text())
                    embed = discord.Embed(title='MMOEXP · FC Product Prices',
                        description='Use the SBC, Packs or Gallery panels in this channel.', color=0xF28C28)
                    await channel.get_partial_message(int(old['message_id'])).edit(
                        embed=embed, view=None, allowed_mentions=discord.AllowedMentions.none())
            except Exception as exc:
                print('Quote panel setup failed: ' + type(exc).__name__, flush=True)

    async def setup_quote_static_panel(self):
        from quote_panel import CategoryHomeView, category_embed
        static = self.config['quote_static']
        channel_id = int(next(iter(static['channels'])))
        channel = self.get_channel(channel_id)
        if (not self.quote_provider or not channel or channel.id != channel_id
                or channel.guild.id != static['guild_id']):
            return
        marker = Path(self.store.path).parent / 'quote-static-panel.json'
        async with self.quote_lock:
            try:
                if marker.exists():
                    saved = json.loads(marker.read_text(encoding='utf-8'))
                    if (not isinstance(saved, dict) or set(saved) != {'guild_id', 'channel_id', 'message_id'}
                            or saved['guild_id'] != static['guild_id'] or saved['channel_id'] != channel_id
                            or type(saved['message_id']) is not int or saved['message_id'] <= 0):
                        print('Static quote panel needs reconciliation.', flush=True)
                        return
                    await channel.get_partial_message(saved['message_id']).edit(
                        embed=category_embed('coins', self.config.get('quote_presentation')),
                        view=CategoryHomeView(self.quote_provider, 'coins', allowed_routes=self.quote_routes('coins'),
                                              presentation=self.config.get('quote_presentation')),
                        allowed_mentions=discord.AllowedMentions.none())
                    return
                saved = {'guild_id': static['guild_id'], 'channel_id': channel_id, 'message_id': 'pending'}
                temp = marker.with_suffix('.tmp')
                temp.write_text(json.dumps(saved), encoding='utf-8')
                temp.replace(marker)
                message = await channel.send(embed=category_embed('coins', self.config.get('quote_presentation')),
                    view=CategoryHomeView(self.quote_provider, 'coins', allowed_routes=self.quote_routes('coins'),
                                          presentation=self.config.get('quote_presentation')),
                    allowed_mentions=discord.AllowedMentions.none())
                saved['message_id'] = message.id
                temp.write_text(json.dumps(saved), encoding='utf-8')
                temp.replace(marker)
            except Exception as exc:
                print('Static quote panel setup failed: ' + type(exc).__name__, flush=True)

    async def setup_club_panels(self):
        from club_panel import club_embed, welcome_embed
        from onboarding_panel import WelcomeView, PopularClubView
        clubs = self.config['club_panels']
        channel = self.get_channel(clubs['channel_id'])
        if not channel or channel.id != clubs['channel_id'] or channel.guild.id != clubs['guild_id']:
            return
        marker = Path(self.store.path).parent / 'club-panels.json'
        keys = ('welcome', 'england', 'europe')
        async with self.club_lock:
            try:
                saved = (json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else
                         {'guild_id': clubs['guild_id'], 'channel_id': clubs['channel_id'], 'messages': {}})
                if (not isinstance(saved, dict) or set(saved) != {'guild_id', 'channel_id', 'messages'}
                        or saved['guild_id'] != clubs['guild_id'] or saved['channel_id'] != clubs['channel_id']
                        or not isinstance(saved['messages'], dict) or set(saved['messages']) - set(keys)
                        or any(type(value) is not int or value <= 0 for value in saved['messages'].values())):
                    print('Club panels need manual reconciliation.', flush=True)
                    return
                for key in keys:
                    presentation = self.config.get('quote_presentation')
                    embed = welcome_embed(presentation, clubs['guild_id']) if key == 'welcome' else club_embed(key, presentation)
                    if key == 'welcome':
                        view = WelcomeView(clubs)
                    elif key == 'england':
                        embed.title = '⚽ Choose your club'
                        embed.description = 'Pick your team. Your FC27 badge is included.'
                        view = PopularClubView(clubs)
                    else:
                        embed.title = 'Your club. Your community.'
                        embed.description = '47 clubs in **More clubs** · Switch teams any time.'
                        view = None
                        if self.config.get('alert_preferences'):
                            from alert_panel import AlertHomeView
                            embed.title = '🔔 Your updates'
                            embed.description = 'Choose your alerts. Change or turn them off any time.'
                            view = AlertHomeView(self.config['alert_preferences'])
                    options = dict(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                    if key in saved['messages']:
                        await channel.get_partial_message(saved['messages'][key]).edit(**options)
                    else:
                        temp = marker.with_suffix('.tmp')
                        saved['messages'][key] = 'pending'
                        temp.write_text(json.dumps(saved), encoding='utf-8')
                        temp.replace(marker)
                        message = await channel.send(**options)
                        saved['messages'][key] = message.id
                        temp.write_text(json.dumps(saved), encoding='utf-8')
                        temp.replace(marker)
            except Exception as exc:
                print('Club panel setup failed: ' + type(exc).__name__, flush=True)

    async def setup_information_panels(self):
        from fut_panel import INFORMATION_CATEGORIES, InformationPanelView
        panels = self.config['information_panels']
        marker = Path(self.information_store.path).parent / 'information-panels.json'
        async with self.information_lock:
            try:
                saved = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
                if not isinstance(saved, dict):
                    raise ValueError('Invalid panel marker')
            except (OSError, ValueError):
                print('Information panel marker unavailable; no panels changed.', flush=True)
                return
            for channel_id, kind in panels['channels'].items():
                channel = self.get_channel(int(channel_id))
                if not channel or channel.guild.id != panels['guild_id']:
                    print('Information panel channel unavailable.', flush=True)
                    continue
                embed = discord.Embed(title=INFORMATION_CATEGORIES[kind],
                    description='Click Explore to browse privately.', color=0xF28C28)
                view = InformationPanelView(self.information_store, panels['guild_id'], panels['channels'])
                try:
                    if channel_id in saved:
                        if saved[channel_id] == 'pending':
                            print('Information panel creation needs manual reconciliation.', flush=True)
                            return
                        await channel.get_partial_message(int(saved[channel_id])).edit(embed=embed, view=view,
                            allowed_mentions=discord.AllowedMentions.none())
                    else:
                        # Persist intent before sending so a crash cannot silently create a duplicate.
                        saved[channel_id] = 'pending'
                        temporary = marker.with_suffix('.tmp')
                        temporary.write_text(json.dumps(saved), encoding='utf-8')
                        temporary.replace(marker)
                        message = await channel.send(embed=embed, view=view,
                            allowed_mentions=discord.AllowedMentions.none())
                        saved[channel_id] = message.id
                        temporary.write_text(json.dumps(saved), encoding='utf-8')
                        temporary.replace(marker)
                except Exception as exc:
                    print('Information panel setup failed: ' + type(exc).__name__, flush=True)
                    return

    async def on_message(self, message):
        if self.quote_relay:
            self.quote_relay.accept(message, time.time())
        if (not message.guild or message.guild.id != TEST_GUILD or message.author.bot
                or message.webhook_id or not self.user
                or not any(user.id == self.user.id for user in message.mentions)):
            return
        now = time.monotonic()
        recent = [t for t in self.mention_rate.pop(message.author.id, []) if now-t < 30]
        self.mention_rate[message.author.id] = recent
        if len(recent) >= 3:
            return
        recent.append(now)
        if len(self.mention_rate) > 10000:
            self.mention_rate.popitem(last=False)
        from fut_panel import FutHomeView, home_embed
        await message.channel.send("Hey! What are we exploring in FUT today? Pick a card below.",
                                   embed=home_embed(), view=FutHomeView(self.store),
                                   allowed_mentions=discord.AllowedMentions.none())

    async def run_action(self, interaction, action, *args, formatter=str):
        if interaction.guild_id != TEST_GUILD or interaction.channel_id is None or interaction.user.bot:
            await interaction.response.send_message('This pilot is available in the test server only.', ephemeral=True)
            return
        user = interaction.user.id
        now = time.monotonic()
        recent = [t for t in self.rate.pop(user, []) if now - t < 30]
        self.rate[user] = recent
        if len(recent) >= 8:
            await interaction.response.send_message('Please wait before trying again.', ephemeral=True)
            return
        recent.append(now)
        if len(self.rate) > 10000:
            self.rate.popitem(last=False)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await asyncio.to_thread(action, *args)
            output = formatter(result)
        except CommunityError as exc:
            output = str(exc)
        except Exception:
            # Do not echo exception payloads, SQL data or credentials to Discord/logs.
            output = 'The service is temporarily unavailable. Please contact staff.'
        options = dict(ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        if isinstance(output, discord.Embed):
            await interaction.followup.send(embed=output, **options)
        elif len(str(output)) > 1900:
            result_file = discord.File(io.BytesIO(str(output).encode('utf-8')), filename='fc-result.txt')
            try:
                await interaction.followup.send('The complete result is attached; no rows were truncated.',
                                                file=result_file, **options)
            finally:
                result_file.close()
        else:
            await interaction.followup.send(str(output), **options)


def build_client(config, store, information_store=None):
    client = ContentClient(config, store, information_store)
    group = app_commands.Group(name='fc', description='FC27 guides and community events')
    run = client.run_action

    @group.command(name='home', description='Open your FUT Clubhouse menu')
    async def home(i: discord.Interaction):
        from fut_panel import FutHomeView, home_embed
        if i.guild_id != TEST_GUILD or i.user.bot:
            await i.response.send_message('This pilot is available in the test server only.', ephemeral=True)
            return
        await i.response.send_message(embed=home_embed(), view=FutHomeView(store), ephemeral=True,
                                      allowed_mentions=discord.AllowedMentions.none())

    @group.command(name='latest', description='Browse reviewed FC27 news and guides')
    async def latest(i: discord.Interaction):
        await run(i, store.latest, formatter=lambda rows: '\n'.join(
            f"#{r['id']} · {r['kind']} · {discord.utils.escape_markdown(r['title'])}" for r in rows)
            or 'No reviewed FC27 content yet.')

    @group.command(name='guide', description='Read a reviewed FC27 guide by ID')
    async def guide(i: discord.Interaction, content_id: int):
        await run(i, store.get, content_id, formatter=render_item)

    @group.command(name='draft', description='Staff: draft FC27 content for review')
    @app_commands.choices(kind=[app_commands.Choice(name=k, value=k) for k in ['news', 'leak', 'review', 'topic', 'collection', 'sbc', 'squad', 'guide']])
    async def draft(i: discord.Interaction, title: str, kind: str, body: str, source: str):
        await run(i, store.draft, str(i.user.id), title, kind, body, source, 27, int(time.time()),
                  formatter=lambda item: f'Draft #{item}. You can preview it and publish with /fc approve.')

    @group.command(name='preview', description='Staff: review a draft, source and status')
    async def preview(i: discord.Interaction, content_id: int):
        await run(i, store.preview, str(i.user.id), content_id, formatter=render_item)

    @group.command(name='approve', description='Staff: approve reviewed content for player lookup')
    async def approve(i: discord.Interaction, content_id: int):
        await run(i, store.approve, str(i.user.id), content_id, int(time.time()),
                  formatter=lambda _: 'Approved. Players can now find this content with /fc latest.')

    @group.command(name='withdraw', description='Staff: withdraw outdated or incorrect content')
    async def withdraw(i: discord.Interaction, content_id: int):
        await run(i, store.withdraw, str(i.user.id), content_id, formatter=lambda _: 'Content withdrawn.')

    @group.command(name='event-create', description='Staff: create a community registration event')
    async def event_create(i: discord.Interaction, title: str, capacity: app_commands.Range[int, 1, 5000],
                           hours: app_commands.Range[int, 1, 2160]):
        now = int(time.time())
        await run(i, store.create_event, str(i.user.id), title, capacity, now + hours * 3600, now,
                  formatter=lambda item: f'Event #{item} created. Members can register with /fc join.')

    @group.command(name='events', description='See open community registrations')
    async def events(i: discord.Interaction):
        await run(i, store.events, int(time.time()), formatter=lambda rows: '\n'.join(
            f"#{r['id']} · {discord.utils.escape_markdown(r['title'])} · {r['joined']}/{r['capacity']} · closes <t:{r['closes']}:R>"
            for r in rows) or 'No open events.')

    @group.command(name='join', description='Register; stores your Discord ID and first signup channel')
    async def join(i: discord.Interaction, event_id: int):
        await run(i, store.join, event_id, str(i.user.id), str(i.channel_id), int(time.time()))

    @group.command(name='leave', description='Cancel your registration and release your place')
    async def leave(i: discord.Interaction, event_id: int):
        await run(i, store.leave, event_id, str(i.user.id), formatter=lambda _: 'Registration cancelled if present.')

    @group.command(name='report', description='Staff: active/cancelled registrations by first signup channel')
    async def report(i: discord.Interaction, event_id: int):
        await run(i, store.report, str(i.user.id), event_id, formatter=lambda rows:
                  'First successful registration channel; not sales attribution.\n' +
                  ('\n'.join(f"Channel {r['channel']}: active {r['active']}, cancelled {r['cancelled']}" for r in rows)
                   or 'No registrations.'))

    client.tree.add_command(group, guild=discord.Object(TEST_GUILD))
    return client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='content.config.example.json')
    parser.add_argument('--check', action='store_true', help='Validate config/commands without connecting')
    args = parser.parse_args()
    config = load_config(args.config)
    if args.check:
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = CommunityStore(Path(directory) / 'check.db', config['staff_user_ids'])
            info_store = CommunityStore(Path(directory) / 'information.db', []) if config.get('information_panels') else None
            client = build_client(config, store, info_store)
            group = client.tree.get_command('fc', guild=discord.Object(TEST_GUILD))
            print(json.dumps({'offline': True, 'guild': TEST_GUILD,
                              'commands': [c.name for c in group.commands],
                              'configured_staff': len(set(config['staff_user_ids']))}))
        return
    if os.environ.get('FC_ENABLE_LIVE') != '1' or not os.environ.get('DISCORD_BOT_TOKEN'):
        raise SystemExit('Live mode requires FC_ENABLE_LIVE=1 and DISCORD_BOT_TOKEN in the environment.')
    if not config['staff_user_ids']:
        raise SystemExit('Configure the owner Discord user ID before starting.')
    db_path = Path(config.get('database', 'var/community.sqlite3'))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = CommunityStore(db_path, config['staff_user_ids'])
    panels = config.get('information_panels')
    info_store = None
    if panels:
        info_path = Path(panels['database'])
        info_path.parent.mkdir(parents=True, exist_ok=True)
        info_store = CommunityStore(info_path, config['staff_user_ids'])
    client = build_client(config, store, info_store)
    client.run(os.environ['DISCORD_BOT_TOKEN'], log_handler=None)


if __name__ == '__main__':
    main()
