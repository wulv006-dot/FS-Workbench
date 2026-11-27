"""Chat-only Discord service for the FC27 community.

Runs a dedicated bot application that is allowed to request the Message Content
privileged intent, so it can answer ambient conversation in the lounge channel
in addition to mentions and slash commands. It deliberately owns nothing else:
no order panel, no news publishing, no database.

Usage:
    python chat_service.py --config chat.config.json [--check]
"""

import argparse
import asyncio
import datetime as dt
import json
import os
import random
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

import discord
from discord import app_commands

import chat_brain
import carnival_chat
import chat_panel
import chat_schedule
import matchday_engagement
import matchday_focus
from club_panel import CLUBS

MAX_HISTORY = 10
OFFICIAL_GUILD = 1041923524601851914
FC_GAME_CHAT = 1200330251016867880
FC27_WELCOME_URL = ('https://discord.com/channels/1041923524601851914/'
                    '1568663362567413820/1568666884289732751')
PRICE_INTENT = re.compile(r'\b(?:price|prices|cost|costs|quote|quotes|how\s+much)\b|价格|报价|多少钱', re.I)
ORDER_INTENT = re.compile(
    r'\b(?:my\s+order|order\s+(?:status|tracking|help)|track\s+(?:my\s+)?order|'
    r'delivery\s+status|refund|where\s+is\s+my\s+order)\b|订单|退款', re.I)
ORDER_CARD_URL = ('https://discord.com/channels/1041923524601851914/'
                  '1570789310813442080/1570795908205903873')
QUOTE_DESTINATIONS = (
    (re.compile(r'\bcoins?\b|金币', re.I), 'Coins', '1568663210901504041'),
    (re.compile(r'\bplayers?\b|球员', re.I), 'Players', '1568878333087719454'),
    (re.compile(r'\bsbcs?\b', re.I), 'SBC', '1301379787696377926'),
    (re.compile(r'\b(?:packs?|evos?|evolutions?|objectives?|obj|gallery|boosting)\b|进化|代练|收藏馆', re.I),
     'OBJ & Packs', '1571045541922611200'),
)
CLUB_LABELS = {slug: label for section in CLUBS.values() for slug, label in section}

HOW_TO_CHAT = ('\u2022 @ me in a normal message\n'
               '\u2022 reply to this card\n'
               '\u2022 or type /chat followed by your question\n'
               '\u2022 keywords work too: SBC, squad, pack, evo')


def quote_link_view(guild_id, text):
    """Offer a live private quote entry only for explicit price questions."""
    if guild_id != OFFICIAL_GUILD or not PRICE_INTENT.search(text):
        return None
    label, url = 'FC27 prices', FC27_WELCOME_URL
    for pattern, category, channel_id in QUOTE_DESTINATIONS:
        if pattern.search(text):
            label = category + ' prices'
            url = 'https://discord.com/channels/{}/{}'.format(OFFICIAL_GUILD, channel_id)
            break
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label='Check ' + label, url=url))
    return view


def order_link_view(guild_id, text):
    """Take order questions to the existing private lookup before human support."""
    if guild_id != OFFICIAL_GUILD or not ORDER_INTENT.search(text):
        return None
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label='Check my order', url=ORDER_CARD_URL))
    return view


ORDER_HELP = ("Let's check that privately. Tap **Check my order** below. "
              "If it needs a person, the result will offer a support ticket.")


def load_config(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def validate_config(config):
    """Offline validation shared by --check and startup."""
    chat_config = config.get('chat_bot')
    if not isinstance(chat_config, dict):
        raise ValueError('config requires a "chat_bot" object')
    if not chat_config.get('enabled'):
        raise ValueError('chat_bot.enabled must be true for the chat service')
    if not chat_config.get('allow_message_content'):
        raise ValueError('chat_bot.allow_message_content must be true: '
                         'this service exists to read message content')
    chat_brain.validate_chat_config(chat_config)
    validated = chat_panel.validate_chat_config(chat_config)
    if not validated['routes']:
        raise ValueError('chat_bot.routes must configure at least one guild')
    chat_panel.validate_surprise_config(chat_config.get('surprise'))
    if config.get('matchday_engagement') is not None:
        matchday_engagement.validate_matchday_config(config['matchday_engagement'])
    if config.get('matchday_focus') is not None:
        matchday_focus.validate_config(config['matchday_focus'],
                                       config.get('matchday_engagement'))
        if 'model_provider' in config['matchday_focus']:
            chat_brain.validate_chat_config(config['matchday_focus']['model_provider'])
        for guild_id, channel_id in config['matchday_focus'].get(
                'game_chat_channels', {}).items():
            route = chat_config['routes'].get(guild_id, {})
            if channel_id not in route.get('channels', {}):
                raise ValueError('Matchday invite target must be an FC chat channel')
    token_env = config.get('token_env', 'DISCORD_CHAT_BOT_TOKEN')
    if not os.environ.get(token_env):
        raise ValueError('missing bot token in environment variable ' + token_env)
    return validated


def guild_ids(chat_config):
    return [int(guild) for guild in chat_config['routes']]


class MyClubButton(discord.ui.Button):
    def __init__(self, client, route):
        super().__init__(label='My club today', emoji='📅',
                         custom_id='fc:matchday:my-club', style=discord.ButtonStyle.secondary)
        self.client, self.route = client, route

    async def callback(self, interaction):
        if (interaction.guild_id != OFFICIAL_GUILD or
                interaction.channel_id != self.route['discussion_channel_id']):
            await interaction.response.send_message('Open this in FC27 Match Chat.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.client.show_my_club(interaction, self.route)


class ChatClient(discord.Client):
    def __init__(self, config, post_topic_now=False, only_channel=None):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none(),
                         activity=discord.Activity(type=discord.ActivityType.watching,
                                                   name='the FC 27 community'))
        self.tree = app_commands.CommandTree(self)
        self.config = config
        self.chat_config = config['chat_bot']
        self.brain = chat_brain.ChatBrain(self.chat_config)
        self.router = chat_panel.ChatRouter(self.chat_config)
        self.limiter = chat_panel.ChatLimiter(
            per_user_seconds=int(self.chat_config.get('per_user_seconds', 60)),
            per_channel_per_minute=int(self.chat_config.get('per_channel_per_minute', 6)),
            daily_budget=int(self.chat_config.get('daily_budget', 400)),
        )
        self.surprise = None
        if (self.chat_config.get('surprise') or {}).get('enabled'):
            self.surprise = chat_panel.SurpriseDrop(
                self.chat_config, config.get('staff_user_ids', ())
            )
        self.history = {}
        self.topic_task = None
        self.carnival_task = None
        self.topic_threads = {}
        self.topic_pool = list(self.chat_config.get('topics') or [])
        self.post_topic_now = bool(post_topic_now)
        self.sticker_chance = float(self.chat_config.get('sticker_chance', 0.35) or 0)
        self.sticker_rng = random.Random()
        self.sticker_cache = {}
        self.only_channel = None if only_channel is None else str(only_channel)
        self.matchday_config = config.get('matchday_engagement')
        self.matchday_store = None
        self.pulse_lock = asyncio.Lock()
        self.followup_task = None
        self.focus_config = config.get('matchday_focus') or {}
        self.focus_brain = None
        if 'model_provider' in self.focus_config:
            self.focus_brain = chat_brain.ChatBrain(self.focus_config['model_provider'])
        self.focus_store = None
        self.focus_lock = asyncio.Lock()
        self.focus_retry_tasks = {}
        self.matchday_intro_view = None
        self.focus_recovered = asyncio.Event()
        if self.matchday_config and self.matchday_config['enabled']:
            self.matchday_store = matchday_engagement.MatchPulseStore(
                self.matchday_config.get('state_path') or
                Path(__file__).parent / 'var' / 'match-pulse.sqlite3')
        if self.focus_config.get('enabled'):
            self.focus_store = matchday_focus.FocusStore(self.focus_config['state_path'])

    # -- lifecycle ---------------------------------------------------------
    async def setup_hook(self):
        self.pulse_lock = asyncio.Lock()
        self.focus_lock = asyncio.Lock()
        # The client is constructed before discord.py starts its event loop.
        # Recreate the gate on the loop that runs the background worker.
        self.focus_recovered = asyncio.Event()
        await self.add_commands()
        route = (self.matchday_config or {}).get('routes', {}).get(str(OFFICIAL_GUILD))
        if route and self.matchday_config.get('enabled'):
            self.matchday_intro_view = self.build_matchday_intro_view(route)
            self.add_view(self.matchday_intro_view)
        for guild_id in guild_ids(self.chat_config):
            await self.tree.sync(guild=discord.Object(guild_id))
        targets = chat_panel.topic_targets(self.chat_config)
        if self.chat_config.get('carnival_2026_first_weekend') and not self.post_topic_now:
            self.carnival_task = asyncio.create_task(carnival_chat.run(self, OFFICIAL_GUILD, FC_GAME_CHAT))
        if self.post_topic_now:
            self.topic_task = asyncio.create_task(self.post_topics_once())
        elif targets and self.topic_pool:
            self.topic_task = asyncio.create_task(self.run_topics())
        if self.matchday_store is not None and not self.post_topic_now:
            self.followup_task = asyncio.create_task(self.run_followups())
            print('Matchday worker scheduled', flush=True)

    async def on_ready(self):
        print('FC chat ready guilds={}'.format([guild.id for guild in self.guilds]), flush=True)
        try:
            await self.setup_matchday_intro()
            if self.focus_store is not None:
                await self.recover_daily_card()
                await self.reconcile_game_chat_invites()
            if self.matchday_store is not None:
                await self.recover_recent_pulses()
        finally:
            self.focus_recovered.set()
            if self.followup_task is None:
                worker_state = 'missing'
            elif self.followup_task.cancelled():
                worker_state = 'cancelled'
            elif self.followup_task.done():
                worker_error = self.followup_task.exception()
                worker_state = 'failed:{}:{}'.format(
                    type(worker_error).__name__, str(worker_error)[:200])
            else:
                worker_state = 'pending'
            print('Matchday recovery released worker task={}'.format(worker_state), flush=True)

    async def recover_daily_card(self, schedule_retry=True):
        """A same-day Unify card can still be used after a bot restart."""
        for guild_id in self.focus_config['guild_ids']:
            route = self.matchday_config['routes'][guild_id]
            ops_id = self.focus_config.get('ops_channel_id')
            if int(guild_id) == OFFICIAL_GUILD and ops_id:
                ops = self.get_channel(int(ops_id))
                if ops is not None and ops.guild.id == OFFICIAL_GUILD:
                    try:
                        async for message in ops.history(limit=200):
                            await self.handle_daily_card(message, schedule_retry=False)
                    except discord.DiscordException as exc:
                        print('Matchday private heartbeat recovery unavailable: ' +
                              type(exc).__name__, flush=True)
            channel = self.get_channel(route['source_channel_id'])
            if channel is None or channel.guild.id != int(guild_id):
                print('Matchday focus source channel unavailable guild={}'.format(guild_id),
                      flush=True)
                continue
            day = discord.utils.utcnow().astimezone(matchday_focus.LONDON).date()
            selection_open = self.focus_store.may_select(
                int(guild_id), day, self.focus_config.get('weekly_limit', 2))
            try:
                scanned = unify_cards = recognized = 0
                async for message in channel.history(limit=200):
                    scanned += 1
                    if getattr(message.author, 'id', None) == matchday_engagement.UNIFY_FOOTBALL_ID:
                        unify_cards += 1
                    if matchday_focus.is_empty_daily_card(
                            message, route, discord.utils.utcnow()):
                        await self.handle_daily_card(message, schedule_retry=schedule_retry)
                        continue
                    if matchday_focus.parse_daily_card(
                            message, route, discord.utils.utcnow()):
                        self.focus_store.record_daily_source(guild_id, day)
                        if selection_open:
                            recognized += 1
                            await self.handle_daily_card(message, schedule_retry=schedule_retry)
                            if not self.focus_store.may_select(
                                    int(guild_id), day, self.focus_config.get('weekly_limit', 2)):
                                selection_open = False
                print('Matchday focus recovery guild={} scanned={} unify={} recognized={}'.format(
                    guild_id, scanned, unify_cards, recognized), flush=True)
            except discord.DiscordException as exc:
                print('Matchday focus recovery unavailable: ' + type(exc).__name__, flush=True)

    async def recover_recent_pulses(self):
        """Catch Unify score events sent during a brief chat-bot restart."""
        cutoff = discord.utils.utcnow() - dt.timedelta(
            seconds=matchday_engagement.MAX_MESSAGE_AGE_SECONDS)
        for guild_id, route in self.matchday_config['routes'].items():
            source_id = route.get('score_channel_id', route['source_channel_id'])
            channel = self.get_channel(source_id)
            if channel is None or channel.guild.id != int(guild_id):
                print('Matchday pulse source channel unavailable guild={}'.format(guild_id),
                      flush=True)
                continue
            try:
                async for message in channel.history(
                        limit=100, after=cutoff, oldest_first=True):
                    await self.handle_match_pulse(message)
            except discord.DiscordException as exc:
                print('Matchday pulse recovery unavailable guild={} reason={}'.format(
                    guild_id, type(exc).__name__), flush=True)

    async def setup_matchday_intro(self):
        route = (self.matchday_config or {}).get('routes', {}).get(str(OFFICIAL_GUILD))
        if not route or not (self.matchday_config or {}).get('enabled'):
            return
        channel = self.get_channel(route['discussion_channel_id'])
        if channel is None or channel.guild.id != OFFICIAL_GUILD:
            print('Matchday intro channel unavailable', flush=True)
            return
        match_source = 'UnifyFootball'
        embed = discord.Embed(
            title='🏟️ FC27 Matchday Lounge',
            description=('Watch fixtures and predict with **{}** in Matchday. '
                         'To chat here, tap **Join FC27** in <#1568663362567413820> '
                         '(or pick a club there). Then try **My club today**. '
                         'MMOEXP FC Assistant keeps FUT price checks private.').format(match_source),
            colour=0x2275E8)
        view = self.matchday_intro_view or self.build_matchday_intro_view(route)
        marker = Path(__file__).parent / 'var' / 'matchday-intro.json'
        try:
            if marker.exists():
                message_id = json.loads(marker.read_text(encoding='utf-8'))['message_id']
                await channel.get_partial_message(int(message_id)).edit(embed=embed, view=view)
            else:
                sent = await channel.send(embed=embed, view=view,
                                          allowed_mentions=discord.AllowedMentions.none())
                temporary = marker.with_suffix('.tmp')
                temporary.write_text(json.dumps({'message_id': sent.id}), encoding='utf-8')
                temporary.replace(marker)
        except (discord.DiscordException, OSError, ValueError, KeyError) as exc:
            print('Matchday intro failed: ' + type(exc).__name__, flush=True)

    def build_matchday_intro_view(self, route):
        view = discord.ui.View(timeout=None)
        for label, target in (
                ('Live matches', route['source_channel_id']),
                ('FC27 Players', route['players_channel_id']),
                ('FC27 Coins', route['coins_channel_id'])):
            view.add_item(discord.ui.Button(label=label,
                url='https://discord.com/channels/{}/{}'.format(OFFICIAL_GUILD, target)))
        view.add_item(MyClubButton(self, route))
        view.add_item(discord.ui.Button(
            label='🏆 Leaderboard',
            url='https://discord.com/channels/1041923524601851914/'
                '1571043454136484082/1571686702513266708'))
        view.add_item(discord.ui.Button(label='👋 Join FC27 to chat', url=FC27_WELCOME_URL))
        return view

    async def show_my_club(self, interaction, route):
        links = discord.ui.View(timeout=None)
        try:
            # Read current role IDs from the owner bot so a club switch needs no second config edit.
            config = json.loads((Path(__file__).parent / 'content.config.json').read_text(encoding='utf-8'))
            clubs = config['club_panels']
            if clubs['guild_id'] != OFFICIAL_GUILD:
                raise ValueError('Club route unavailable')
            member = await interaction.guild.fetch_member(interaction.user.id)
            if member.id != interaction.user.id or member.bot:
                raise ValueError('Member unavailable')
            held = {role.id for role in member.roles}
            selected = [slug for slug, role_id in clubs['role_ids'].items()
                        if slug in CLUB_LABELS and role_id in held]
            if len(selected) != 1:
                text = 'Choose one club in FC27 Welcome first.'
                links.add_item(discord.ui.Button(label='Choose a club', url=
                    'https://discord.com/channels/{}/1568663362567413820'.format(OFFICIAL_GUILD)))
            else:
                slug = selected[0]
                channel = self.get_channel(route['source_channel_id'])
                if channel is None or channel.guild.id != OFFICIAL_GUILD:
                    raise ValueError('Matchday channel unavailable')
                now = discord.utils.utcnow()
                fixtures = []
                async for message in channel.history(limit=50):
                    fixtures.extend(matchday_focus.parse_daily_card(
                        message, route, now, include_started=True))
                matches = sorted(matchday_focus.club_fixtures(slug, fixtures),
                                 key=lambda fixture: fixture.kickoff)
                if matches:
                    match = matches[0]
                    text = '**{} today** · {} vs {} · {} · <t:{}:t>'.format(
                        CLUB_LABELS[slug], match.home, match.away, match.competition,
                        int(match.kickoff.timestamp()))
                    links.add_item(discord.ui.Button(label='Open match card', url=match.source_url))
                elif fixtures:
                    text = 'No {} fixture in today’s Matchday cards.'.format(CLUB_LABELS[slug])
                else:
                    text = 'No fixtures available in today’s Matchday feed.'
                links.add_item(discord.ui.Button(label='All matches', url=
                    'https://discord.com/channels/{}/{}'.format(
                        OFFICIAL_GUILD, route['source_channel_id'])))
        except (discord.DiscordException, OSError, ValueError, KeyError) as exc:
            print('Matchday club lookup unavailable: ' + type(exc).__name__, flush=True)
            text, links = 'Matchday is unavailable right now. Try again shortly.', None
        await interaction.followup.send(text, view=links, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    async def close(self):
        for task in (self.topic_task, self.followup_task, self.carnival_task, *self.focus_retry_tasks.values()):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        self.topic_task = None
        self.followup_task = None
        self.focus_retry_tasks.clear()
        await super().close()

    async def add_commands(self):
        for guild_id in guild_ids(self.chat_config):
            guild = discord.Object(guild_id)
            self.tree.add_command(self.chat_command(), guild=guild)
            self.tree.add_command(self.drop_command(), guild=guild)

    def chat_command(self):
        client = self

        async def callback(interaction, text: str):
            await client.do_chat(interaction, text)

        return app_commands.Command(name='chat',
                                    description='Ask the community bot something',
                                    callback=callback)

    def drop_command(self):
        client = self

        async def callback(interaction):
            await client.do_drop(interaction)

        return app_commands.Command(name='drop',
                                    description='Staff: release a limited discount code',
                                    callback=callback)

    # -- chat --------------------------------------------------------------
    async def on_message(self, message):
        if message.author.bot:
            if self.matchday_store is not None:
                if self.focus_store is not None:
                    await self.handle_daily_card(message)
                await self.handle_match_pulse(message)
            return
        if message.guild is None:
            return
        await self.handle_chat(message)

    async def handle_match_pulse(self, message):
        pulse = matchday_engagement.parse_match_event(message, self.matchday_config, time.time())
        if pulse is None:
            return
        route = self.matchday_config['routes'][str(pulse.guild_id)]
        if self.focus_store is not None and str(pulse.guild_id) in self.focus_config['guild_ids']:
            source_id = self.focus_store.selected_source_id(
                pulse.guild_id, pulse.match_key, time.time())
            if source_id is None:
                return
            if route.get('score_channel_id', route['source_channel_id']) != route['source_channel_id']:
                pulse = replace(pulse, source_url='https://discord.com/channels/{}/{}/{}'.format(
                    pulse.guild_id, route['source_channel_id'], source_id))
        async with self.pulse_lock:
            channel = self.get_channel(pulse.discussion_channel_id)
            if channel is None or channel.guild.id != pulse.guild_id:
                print('Matchday discussion channel unavailable source={}'.format(message.id), flush=True)
                return
            if not self.matchday_store.claim(message.id, pulse, time.time()):
                return
            await self.send_match_pulse(channel, message.id, pulse,
                                        message.created_at.timestamp(), attempts=3)

    def schedule_daily_retry(self, message):
        task = self.focus_retry_tasks.get(message.id)
        if task is None or task.done():
            self.focus_retry_tasks[message.id] = asyncio.create_task(
                self.retry_daily_card(message))

    async def retry_daily_card(self, message):
        try:
            settle = self.focus_config.get('settle_seconds',
                                           matchday_focus.DEFAULT_SETTLE_SECONDS)
            remaining = (message.created_at + dt.timedelta(seconds=settle) -
                         discord.utils.utcnow()).total_seconds()
            await asyncio.sleep(max(0, remaining))
            await self.handle_daily_card(message, schedule_retry=False)
        finally:
            self.focus_retry_tasks.pop(message.id, None)

    async def handle_daily_card(self, message, schedule_retry=True):
        if message.guild is None or str(message.guild.id) not in self.focus_config['guild_ids']:
            return
        route = self.matchday_config['routes'][str(message.guild.id)]
        now = discord.utils.utcnow()
        ops_id = self.focus_config.get('ops_channel_id')
        if (message.guild.id == OFFICIAL_GUILD and ops_id and
                message.channel.id == int(ops_id)):
            private_route = dict(route, source_channel_id=int(ops_id))
            if (message.created_at.astimezone(matchday_focus.LONDON).date() ==
                    now.astimezone(matchday_focus.LONDON).date() and
                    (matchday_focus.is_empty_daily_card(message, private_route, now) or
                     matchday_focus.parse_daily_card(
                         message, private_route, now, include_started=True))):
                self.focus_store.record_daily_source(message.guild.id,
                    now.astimezone(matchday_focus.LONDON).date())
            return
        if matchday_focus.is_empty_daily_card(message, route, now):
            # An old placeholder can still be within the 24-hour source window after midnight.
            if (message.created_at.astimezone(matchday_focus.LONDON).date() ==
                    now.astimezone(matchday_focus.LONDON).date()):
                self.focus_store.record_daily_source(
                    message.guild.id, now.astimezone(matchday_focus.LONDON).date())
            try:
                await message.delete()
                print('Matchday empty card removed guild={} source={}'.format(
                    message.guild.id, message.id), flush=True)
            except discord.DiscordException as exc:
                print('Matchday empty card removal failed guild={} source={} reason={}'.format(
                    message.guild.id, message.id, type(exc).__name__), flush=True)
            return
        fixtures = matchday_focus.parse_daily_card(message, route, now)
        if not fixtures:
            return
        day = now.astimezone(matchday_focus.LONDON).date()
        self.focus_store.record_daily_source(message.guild.id, day)
        limit = self.focus_config.get('weekly_limit', 2)
        if (not self.focus_store.may_select(message.guild.id, day, limit)
                or self.focus_store.reviewed(message.guild.id, message.id)):
            return
        if (now - message.created_at).total_seconds() < self.focus_config.get(
                'settle_seconds', matchday_focus.DEFAULT_SETTLE_SECONDS):
            if schedule_retry:
                self.schedule_daily_retry(message)
            return
        async with self.focus_lock:
            if (not self.focus_store.may_select(message.guild.id, day, limit)
                    or self.focus_store.reviewed(message.guild.id, message.id)):
                return
            channel = self.get_channel(route['discussion_channel_id'])
            if channel is None or channel.guild.id != message.guild.id:
                print('Matchday focus discussion channel unavailable', flush=True)
                return
            source = self.get_channel(route['source_channel_id'])
            if source is None or source.guild.id != message.guild.id:
                print('Matchday focus source channel unavailable', flush=True)
                return
            candidates, source_ids, seen = [], set(), set()
            for fixture in fixtures:
                candidates.append((message.id, fixture))
                seen.add(fixture.key)
            source_ids.add(message.id)
            async for card in source.history(limit=200):
                card_fixtures = matchday_focus.parse_daily_card(card, route, now)
                if card_fixtures:
                    source_ids.add(card.id)
                for fixture in card_fixtures:
                    if fixture.key not in seen:
                        candidates.append((card.id, fixture))
                        seen.add(fixture.key)
            if not candidates:
                return
            try:
                selector = self.focus_brain or self.brain
                answer = await selector.select_matchday([fixture for _, fixture in candidates])
                choice = matchday_focus.parse_choice(answer, len(candidates))
            except (chat_brain.ChatBrainError, ValueError) as exc:
                print('Matchday focus selection skipped: {} response={!r}'.format(
                    type(exc).__name__, locals().get('answer', '')[:240]), flush=True)
                if schedule_retry:
                    self.schedule_daily_retry(message)
                return
            if choice is None:
                for source_id in source_ids:
                    self.focus_store.skip_source(message.guild.id, source_id)
                return
            selected_source_id, fixture = candidates[choice]
            question = 'Who are you backing: {} or {}?'.format(
                fixture.home, fixture.away)
            if not self.focus_store.reserve(message.guild.id, day, selected_source_id,
                                            fixture, question, limit):
                return
            embed = discord.Embed(
                title='🏟️ Matchday pick',
                description=('**{} vs {}** · {}\nKickoff: <t:{}:F>\n\n{}\n'
                             'Open the fixtures, choose this match, then tap **Predict**.').format(
                    fixture.home, fixture.away, fixture.competition,
                    int(fixture.kickoff.timestamp()), question),
                colour=0x2275E8)
            embed.set_footer(text='Fixture: UnifyFootball · FC27 community: MMOEXP')
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='⚽ Open fixtures to predict',
                                            url=fixture.source_url))
            view.add_item(discord.ui.Button(label='Build your FC27 XI', url=
                'https://discord.com/channels/{}/{}'.format(
                    message.guild.id, route['players_channel_id'])))
            if message.guild.id == OFFICIAL_GUILD:
                view.add_item(discord.ui.Button(label='👋 Join FC27 to chat',
                                                url=FC27_WELCOME_URL))
            try:
                sent = await channel.send(embed=embed, view=view, nonce=selected_source_id,
                                          allowed_mentions=discord.AllowedMentions.none())
                self.focus_store.finish(message.guild.id, day, sent.id)
                print('Matchday focus sent source={} discussion={}'.format(
                    selected_source_id, sent.id), flush=True)
            except discord.DiscordException as exc:
                self.focus_store.unknown(message.guild.id, day)
                print('Matchday focus result unknown: ' + type(exc).__name__, flush=True)

    async def send_match_pulse(self, channel, source_id, pulse, source_at, attempts=1):
        embed = discord.Embed(title='⚽ Matchday chat',
                              description=matchday_engagement.prompt_text(pulse),
                              colour=0x2275E8)
        embed.set_footer(text='Match updates: {} · FC27 tools: MMOEXP'.format(pulse.source_name))
        view = discord.ui.View(timeout=None)
        route = self.matchday_config['routes'][str(pulse.guild_id)]
        source_label = ('fixture' if route.get('score_channel_id', route['source_channel_id'])
                        != route['source_channel_id'] else 'update')
        view.add_item(discord.ui.Button(label='{} {}'.format(pulse.source_name, source_label),
                                        url=pulse.source_url))
        view.add_item(discord.ui.Button(label='FC27 Players',
            url='https://discord.com/channels/{}/{}'.format(pulse.guild_id, pulse.players_channel_id)))
        view.add_item(discord.ui.Button(label='FC27 Coins',
            url='https://discord.com/channels/{}/{}'.format(pulse.guild_id, pulse.coins_channel_id)))
        try:
            for attempt in range(attempts):
                try:
                    sent = await channel.send(embed=embed, view=view, nonce=source_id,
                                              allowed_mentions=discord.AllowedMentions.none())
                    break
                except discord.HTTPException:
                    if attempt == attempts - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)
            self.matchday_store.delivery_sent(source_id, sent.id)
            print('Matchday pulse sent source={} discussion={} kind={} delay_ms={}'.format(
                source_id, sent.id, pulse.kind,
                round((time.time() - source_at) * 1000)), flush=True)
            if pulse.kind == 'final':
                self.matchday_store.queue_followup(pulse, time.time())
            history = list(self.history.get(pulse.discussion_channel_id, ()))
            history.append(('assistant', '{} public update: '.format(pulse.source_name) +
                            matchday_engagement.prompt_text(pulse)))
            self.history[pulse.discussion_channel_id] = history[-MAX_HISTORY:]
        except discord.DiscordException as exc:
            self.matchday_store.delivery_failed(source_id, time.time())
            print('Matchday prompt failed source={} kind={}: {}'.format(
                source_id, pulse.kind, type(exc).__name__), flush=True)

    async def send_pending_pulses_due(self, now=None):
        now = time.time() if now is None else now
        async with self.pulse_lock:
            pending, expired = self.matchday_store.due_deliveries(now)
            for source_id in expired:
                print('Matchday delivery unconfirmed source={}'.format(source_id), flush=True)
            for source_id, pulse, first_seen in pending:
                channel = self.get_channel(pulse.discussion_channel_id)
                if channel is None or channel.guild.id != pulse.guild_id:
                    print('Matchday retry channel unavailable source={}'.format(source_id), flush=True)
                    continue
                await self.send_match_pulse(channel, source_id, pulse, first_seen)

    async def send_followups_due(self, now=None):
        now = time.time() if now is None else now
        for key, pulse in self.matchday_store.due_followups(now):
            channel = self.get_channel(pulse.discussion_channel_id)
            if channel is None or channel.guild.id != pulse.guild_id:
                print('Match to Squad channel unavailable', flush=True)
                continue
            if not self.matchday_store.reserve_followup(key):
                continue
            embed = discord.Embed(title='🧩 Match to Squad',
                                  description=matchday_engagement.followup_text(pulse),
                                  colour=0x2275E8)
            embed.set_footer(text='Match result: {} · FC27 tools: MMOEXP'.format(pulse.source_name))
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='{} final'.format(pulse.source_name),
                                            url=pulse.source_url))
            view.add_item(discord.ui.Button(label='Explore FC27 Players',
                url='https://discord.com/channels/{}/{}'.format(
                    pulse.guild_id, pulse.players_channel_id)))
            try:
                sent = await channel.send(embed=embed, view=view,
                                          allowed_mentions=discord.AllowedMentions.none())
                self.matchday_store.finish_followup(key, sent.id)
            except Exception as exc:
                self.matchday_store.unknown_followup(key)
                print('Match to Squad result unknown: ' + type(exc).__name__, flush=True)

    async def send_game_chat_invites_due(self, now=None):
        if self.focus_store is None:
            return
        now = time.time() if now is None else now
        for guild_id, channel_id in self.focus_config.get('game_chat_channels', {}).items():
            channel = self.get_channel(int(channel_id))
            if (channel is None or channel.guild.id != int(guild_id) or
                    not self.router.in_scope(int(guild_id), int(channel_id))):
                print('Matchday game chat channel unavailable', flush=True)
                continue
            for row in self.focus_store.due_game_chat_invites(guild_id, now):
                home, separator, away = row['match_key'].partition('|')
                if not separator or not self.focus_store.reserve_game_chat_invite(row, now):
                    continue
                fixture = '{} vs {}'.format(discord.utils.escape_markdown(home.title()),
                                            discord.utils.escape_markdown(away.title()))
                embed = discord.Embed(
                    title='⚽ Today’s matchday pick',
                    description=('**{}** · Kickoff <t:{}:t>\n'
                                 'Make your prediction, then join the match chat.').format(
                        fixture, int(row['kickoff'])), colour=0x2275E8)
                embed.set_footer(text='Football: UnifyFootball · FC27 community: MMOEXP')
                view = discord.ui.View(timeout=None)
                view.add_item(discord.ui.Button(label='Predict with Unify',
                    url='https://discord.com/channels/{}/{}/{}'.format(
                        guild_id, self.matchday_config['routes'][guild_id]['source_channel_id'],
                        row['source_id'])))
                view.add_item(discord.ui.Button(label='Join match chat',
                    url='https://discord.com/channels/{}/{}/{}'.format(
                        guild_id, self.matchday_config['routes'][guild_id]['discussion_channel_id'],
                        row['posted_id'])))
                try:
                    sent = await channel.send(embed=embed, view=view,
                        allowed_mentions=discord.AllowedMentions.none())
                    self.focus_store.finish_game_chat_invite(row, sent.id)
                    print('Matchday game chat invite sent focus={} message={}'.format(
                        row['posted_id'], sent.id), flush=True)
                except Exception as exc:
                    self.focus_store.unknown_game_chat_invite(row)
                    print('Matchday game chat invite result unknown: ' +
                          type(exc).__name__, flush=True)
                    await self.reconcile_game_chat_invites(now)

    async def reconcile_game_chat_invites(self, now=None):
        """Read back ambiguous sends; never resend a card with an unknown outcome."""
        if self.focus_store is None or self.user is None:
            return
        now = time.time() if now is None else now
        for guild_id, channel_id in self.focus_config.get('game_chat_channels', {}).items():
            channel = self.get_channel(int(channel_id))
            if channel is None or channel.guild.id != int(guild_id):
                continue
            route = self.matchday_config['routes'][guild_id]
            for row in self.focus_store.unresolved_game_chat_invites(guild_id, now):
                focus_url = 'https://discord.com/channels/{}/{}/{}'.format(
                    guild_id, route['discussion_channel_id'], row['posted_id'])
                since = dt.datetime.fromtimestamp(row['kickoff'] - 3660, dt.timezone.utc)
                try:
                    # shortcut: If 500 newer messages hide this card, leave it unknown for manual review.
                    async for message in channel.history(limit=500, after=since):
                        if getattr(getattr(message, 'author', None), 'id', None) != self.user.id:
                            continue
                        if any(getattr(button, 'url', None) == focus_url
                               for action in (getattr(message, 'components', None) or ())
                               for button in getattr(action, 'children', ())):
                            self.focus_store.finish_game_chat_invite(row, message.id)
                            print('Matchday game chat invite recovered focus={} message={}'.format(
                                row['posted_id'], message.id), flush=True)
                            break
                except Exception as exc:
                    print('Matchday game chat invite readback failed focus={} reason={}'.format(
                        row['posted_id'], type(exc).__name__), flush=True)

    async def run_followups(self):
        await self.focus_recovered.wait()
        print('Matchday worker ready', flush=True)
        while not self.is_closed():
            try:
                await self.send_pending_pulses_due()
                await self.send_followups_due()
            except Exception as exc:
                print('Match to Squad worker failed: ' + type(exc).__name__, flush=True)
            try:
                await self.send_game_chat_invites_due()
            except Exception as exc:
                print('Matchday game chat invite worker failed: ' +
                      type(exc).__name__, flush=True)
            try:
                await self.alert_missing_daily_card()
            except Exception as exc:
                print('Matchday daily source check failed: ' + type(exc).__name__, flush=True)
            try:
                await self.alert_overdue_followups()
            except Exception as exc:
                print('Match to Squad overdue check failed: ' + type(exc).__name__, flush=True)
            await asyncio.sleep(60)

    async def alert_overdue_followups(self, now=None):
        ops_id = self.focus_config.get('ops_channel_id')
        if self.matchday_store is None or not ops_id:
            return
        overdue = self.matchday_store.overdue_followups(
            time.time() if now is None else now, OFFICIAL_GUILD)
        if not overdue:
            return
        channel = self.get_channel(int(ops_id))
        if channel is None or channel.guild.id != OFFICIAL_GUILD:
            print('Match to Squad alert channel unavailable', flush=True)
            return
        for key, pulse in overdue:
            if pulse.guild_id != OFFICIAL_GUILD or not self.matchday_store.claim_followup_alert(key):
                continue
            try:
                sent = await channel.send(
                    '⚠️ Match to Squad follow-up is overdue or unconfirmed in <#{}>. '
                    'Check the channel and delivery log before retrying.'.format(
                        pulse.discussion_channel_id),
                    allowed_mentions=discord.AllowedMentions.none())
                self.matchday_store.finish_followup_alert(key, sent.id)
            except discord.DiscordException as exc:
                # shortcut: an uncertain Discord send is not retried, to avoid duplicate ops alerts.
                print('Match to Squad alert result unknown: ' + type(exc).__name__, flush=True)

    async def alert_missing_daily_card(self, now=None):
        ops_id = self.focus_config.get('ops_channel_id')
        if self.focus_store is None or not ops_id:
            return
        local = (now or discord.utils.utcnow()).astimezone(matchday_focus.LONDON)
        if local.hour < 10:
            return
        if not self.focus_store.claim_missing_source(OFFICIAL_GUILD, local.date()):
            return
        channel = self.get_channel(int(ops_id))
        if channel is None or channel.guild.id != OFFICIAL_GUILD:
            self.focus_store.unknown_missing_source(OFFICIAL_GUILD, local.date())
            print('Matchday daily source alert channel unavailable', flush=True)
            return
        try:
            sent = await channel.send(
                '⚠️ No UnifyFootball daily fixture card was seen today. '
                'Check the private daily heartbeat subscription and app status.',
                allowed_mentions=discord.AllowedMentions.none())
            self.focus_store.finish_missing_source(OFFICIAL_GUILD, local.date(), sent.id)
        except discord.DiscordException as exc:
            self.focus_store.unknown_missing_source(OFFICIAL_GUILD, local.date())
            print('Matchday daily source alert unknown: ' + type(exc).__name__, flush=True)

    async def handle_chat(self, message):
        guild_id, channel_id = message.guild.id, message.channel.id
        content = message.content or ''
        if not content.strip():
            return False
        if not self.router.in_scope(guild_id, channel_id):
            return False

        if self.surprise is not None and self.surprise.is_staff(message.author.id):
            if self.surprise.is_trigger(content) and self.surprise.allow():
                self.surprise.record()
                code, text = self.surprise.draw()
                await self.post_surprise(message.channel, code, text)
                return True

        in_topic = self.topic_threads.get(guild_id) == channel_id
        mentioned = self.user is not None and self.user.mentioned_in(message)
        replied = False
        reference = getattr(message, 'reference', None)
        if reference is not None and reference.resolved is not None:
            replied = getattr(reference.resolved, 'author', None) == self.user

        trigger = self.router.route(guild_id, channel_id, message.author.id, False, content,
                                    mentioned_bot=mentioned, replied_to_bot=replied,
                                    in_topic=in_topic)
        order_view = order_link_view(guild_id, content)
        if (trigger is None and guild_id == OFFICIAL_GUILD and
                channel_id == FC_GAME_CHAT and
                (PRICE_INTENT.search(content) or ORDER_INTENT.search(content))):
            trigger = 'help'
        if trigger is None:
            return False
        if order_view is not None:
            if not self.limiter.allow(message.author.id, channel_id):
                return False
            self.limiter.record(message.author.id, channel_id)
            await message.reply(ORDER_HELP, view=order_view, mention_author=True,
                allowed_mentions=discord.AllowedMentions(users=[message.author]))
            return True
        if not self.brain.ready:
            print('chat brain is not configured, ignoring trigger ' + trigger, flush=True)
            return False
        if not self.limiter.allow(message.author.id, channel_id):
            return False
        self.limiter.record(message.author.id, channel_id)

        history = list(self.history.get(channel_id, ()))
        async with message.channel.typing():
            try:
                answer = await self.brain.reply(message.author.display_name, content, history)
            except chat_brain.ChatBrainError as exc:
                print('Chat reply failed: ' + str(exc), flush=True)
                return True
        history.append(('user', content[:400]))
        history.append(('assistant', answer))
        self.history[channel_id] = history[-MAX_HISTORY:]
        sticker = self.sticker_for(getattr(message, 'guild', None), answer)
        extra = {'stickers': [sticker]} if sticker is not None else {}
        help_view = quote_link_view(guild_id, content)
        if help_view is not None:
            extra['view'] = help_view
        await message.reply(answer[:1900],
                            mention_author=True,
                            allowed_mentions=discord.AllowedMentions(users=[message.author]),
                            **extra)
        return True

    async def do_chat(self, interaction, text):
        if not self.router.in_scope(interaction.guild_id, interaction.channel_id):
            await interaction.response.send_message('Use /chat in FC27 Chat or Match Chat.', ephemeral=True)
            return
        order_view = order_link_view(interaction.guild_id, text)
        if order_view is not None:
            if not self.limiter.allow(interaction.user.id, interaction.channel_id):
                await interaction.response.send_message('Slow down a little, try again shortly.',
                                                        ephemeral=True)
                return
            self.limiter.record(interaction.user.id, interaction.channel_id)
            await interaction.response.send_message(ORDER_HELP, view=order_view,
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        if not self.brain.ready:
            await interaction.response.send_message('Chat is not configured yet.', ephemeral=True)
            return
        if not self.limiter.allow(interaction.user.id, interaction.channel_id):
            await interaction.response.send_message('Slow down a little, try again shortly.',
                                                    ephemeral=True)
            return
        self.limiter.record(interaction.user.id, interaction.channel_id)
        await interaction.response.defer(thinking=True)
        history = list(self.history.get(interaction.channel_id, ()))
        try:
            answer = await self.brain.reply(interaction.user.display_name, text, history)
        except chat_brain.ChatBrainError as exc:
            await interaction.followup.send('Chat is unavailable right now.')
            print('Slash chat failed: ' + str(exc), flush=True)
            return
        history.append(('user', text[:400]))
        history.append(('assistant', answer))
        self.history[interaction.channel_id] = history[-MAX_HISTORY:]
        sticker = self.sticker_for(getattr(interaction, 'guild', None), answer)
        extra = {'stickers': [sticker]} if sticker is not None else {}
        help_view = quote_link_view(interaction.guild_id, text)
        if help_view is not None:
            extra['view'] = help_view
        await interaction.followup.send('<@{}> {}'.format(interaction.user.id, answer), **extra)

    async def do_drop(self, interaction):
        if not self.router.in_scope(interaction.guild_id, interaction.channel_id):
            await interaction.response.send_message('Use /drop in FC27 Chat or Match Chat.', ephemeral=True)
            return
        if self.surprise is None:
            await interaction.response.send_message('Drops are not configured.', ephemeral=True)
            return
        if not self.surprise.is_staff(interaction.user.id):
            await interaction.response.send_message('Staff only.', ephemeral=True)
            return
        if not self.surprise.allow():
            await interaction.response.send_message('Drop limit reached for now.',
                                                    ephemeral=True)
            return
        self.surprise.record()
        code, text = self.surprise.draw()
        await interaction.response.send_message('Dropping now.', ephemeral=True)
        await self.post_surprise(interaction.channel, code, text)

    async def post_surprise(self, channel, code, text):
        embed = discord.Embed(title='\U0001F381 FC27 surprise drop',
                              description=text or 'Community discount code',
                              colour=discord.Colour.gold())
        embed.add_field(name='Code', value='`' + code + '`', inline=False)
        embed.set_footer(text='Eligibility and final price confirmed at checkout')
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    # -- stickers ----------------------------------------------------------
    def sticker_for(self, guild, answer):
        """Return a guild sticker that fits the answer, at most one per reply."""
        if guild is None or self.sticker_chance <= 0:
            return None
        if self.sticker_rng.random() >= self.sticker_chance:
            return None
        pool = self.sticker_cache.get(guild.id)
        if pool is None:
            pool = {sticker.name.strip().lower(): sticker for sticker in guild.stickers}
            self.sticker_cache[guild.id] = pool
        name = chat_panel.pick_sticker_name(answer, pool.keys(), self.sticker_rng)
        if name is None:
            return None
        return pool.get(name.strip().lower())

    # -- daily topic -------------------------------------------------------
    async def send_topics(self):
        topic = chat_schedule.pick_topic(self.topic_pool)
        if topic is None:
            return
        for channel_id in chat_panel.topic_targets(self.chat_config):
            if self.only_channel is not None and str(channel_id) != self.only_channel:
                continue
            channel = self.get_channel(int(channel_id))
            if channel is None:
                print('Topic channel missing: ' + str(channel_id), flush=True)
                continue
            if not self.router.in_scope(channel.guild.id, channel.id):
                print('Topic channel outside FC chat routes: ' + str(channel_id), flush=True)
                continue
            embed = discord.Embed(
                title='\U0001F4AC FC27 daily topic',
                description=topic,
                color=0x5865F2)
            embed.add_field(name='How to talk to me', value=HOW_TO_CHAT, inline=False)
            embed.set_footer(text='Prices: FC Assistant cards \u00b7 Orders: FC27 VIP Support > Check my order')
            try:
                await channel.send(embed=embed,
                                   allowed_mentions=discord.AllowedMentions.none())
            except Exception as exc:
                print('Topic post failed: ' + type(exc).__name__, flush=True)
                continue
            print('Topic posted: ' + str(channel_id), flush=True)

    async def post_topics_once(self):
        await self.wait_until_ready()
        await self.send_topics()
        await self.close()

    async def run_topics(self):
        hour = int(self.chat_config.get('topic_hour', 20))
        while not self.is_closed():
            await asyncio.sleep(chat_schedule.seconds_until_next(hour))
            await self.send_topics()


def build_client(config, post_topic_now=False, only_channel=None):
    validate_config(config)
    return ChatClient(config, post_topic_now=post_topic_now, only_channel=only_channel)


def main(argv=None):
    parser = argparse.ArgumentParser(description='FC27 chat-only Discord service')
    parser.add_argument('--config', required=True)
    parser.add_argument('--check', action='store_true',
                        help='validate configuration offline and exit')
    parser.add_argument('--post-topic-now', action='store_true',
                        help='post the daily topic immediately, then exit')
    parser.add_argument('--channel',
                        help='with --post-topic-now, only post to this channel id')
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.check:
        validate_config(config)
        print('chat_service config OK')
        return 0
    client = build_client(config, post_topic_now=args.post_topic_now,
                          only_channel=args.channel)
    token_env = config.get('token_env', 'DISCORD_CHAT_BOT_TOKEN')
    client.run(os.environ[token_env])
    return 0


if __name__ == '__main__':
    sys.exit(main())
