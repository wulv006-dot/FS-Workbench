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
import json
import os
import random
import sys
import time
from dataclasses import replace
from pathlib import Path

import discord
from discord import app_commands

import chat_brain
import chat_panel
import chat_schedule
import matchday_engagement
import matchday_focus
from club_panel import CLUBS

MAX_HISTORY = 10
OFFICIAL_GUILD = 1041923524601851914
CLUB_LABELS = {slug: label for section in CLUBS.values() for slug, label in section}

HOW_TO_CHAT = ('\u2022 @ me in a normal message\n'
               '\u2022 reply to this card\n'
               '\u2022 or type /chat followed by your question\n'
               '\u2022 keywords work too: SBC, squad, pack, evo')


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
        self.focus_store = None
        self.focus_lock = asyncio.Lock()
        self.focus_retry_task = None
        self.matchday_intro_view = None
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
        await self.add_commands()
        route = (self.matchday_config or {}).get('routes', {}).get(str(OFFICIAL_GUILD))
        if route and self.matchday_config.get('enabled'):
            self.matchday_intro_view = self.build_matchday_intro_view(route)
            self.add_view(self.matchday_intro_view)
        for guild_id in guild_ids(self.chat_config):
            await self.tree.sync(guild=discord.Object(guild_id))
        targets = chat_panel.topic_targets(self.chat_config)
        if self.post_topic_now:
            self.topic_task = asyncio.create_task(self.post_topics_once())
        elif targets and self.topic_pool:
            self.topic_task = asyncio.create_task(self.run_topics())
        if self.matchday_store is not None and not self.post_topic_now:
            self.followup_task = asyncio.create_task(self.run_followups())

    async def on_ready(self):
        print('FC chat ready guilds={}'.format([guild.id for guild in self.guilds]), flush=True)
        await self.setup_matchday_intro()
        if self.focus_store is not None:
            await self.recover_daily_card()

    async def recover_daily_card(self, schedule_retry=True):
        """A same-day Unify card can still be used after a bot restart."""
        for guild_id in self.focus_config['guild_ids']:
            route = self.matchday_config['routes'][guild_id]
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
                    if selection_open and matchday_focus.parse_daily_card(
                            message, route, discord.utils.utcnow()):
                        recognized += 1
                        await self.handle_daily_card(message, schedule_retry=schedule_retry)
                        if not self.focus_store.may_select(
                                int(guild_id), day, self.focus_config.get('weekly_limit', 2)):
                            selection_open = False
                print('Matchday focus recovery guild={} scanned={} unify={} recognized={}'.format(
                    guild_id, scanned, unify_cards, recognized), flush=True)
            except discord.DiscordException as exc:
                print('Matchday focus recovery unavailable: ' + type(exc).__name__, flush=True)

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
            description=('Follow live football and predictions with **{}** in Matchday. '
                         'Talk fixtures, goals and players here. Pick a club in Welcome, then tap '
                         '**My club today**; '
                         'MMOEXP FC Assistant handles private FUT price checks.').format(match_source),
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
        for task in (self.topic_task, self.followup_task, self.focus_retry_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        self.topic_task = None
        self.followup_task = None
        self.focus_retry_task = None
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

    async def retry_daily_card(self):
        await asyncio.sleep(300)
        await self.recover_daily_card(schedule_retry=False)

    async def handle_daily_card(self, message, schedule_retry=True):
        if message.guild is None or str(message.guild.id) not in self.focus_config['guild_ids']:
            return
        route = self.matchday_config['routes'][str(message.guild.id)]
        now = discord.utils.utcnow()
        if matchday_focus.is_empty_daily_card(message, route, now):
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
        async with self.focus_lock:
            limit = self.focus_config.get('weekly_limit', 2)
            if (not self.focus_store.may_select(message.guild.id, day, limit)
                    or self.focus_store.reviewed(message.guild.id, message.id)):
                return
            channel = self.get_channel(route['discussion_channel_id'])
            if channel is None or channel.guild.id != message.guild.id:
                print('Matchday focus discussion channel unavailable', flush=True)
                return
            try:
                answer = await self.brain.select_matchday(fixtures)
                choice = matchday_focus.parse_choice(answer, len(fixtures))
            except (chat_brain.ChatBrainError, ValueError) as exc:
                print('Matchday focus selection skipped: {} response={!r}'.format(
                    type(exc).__name__, locals().get('answer', '')[:240]), flush=True)
                if schedule_retry and (self.focus_retry_task is None or
                                       self.focus_retry_task.done()):
                    self.focus_retry_task = asyncio.create_task(self.retry_daily_card())
                return
            if choice is None:
                self.focus_store.skip_source(message.guild.id, message.id)
                return
            index = choice
            fixture = fixtures[index]
            question = 'Who are you backing: {} or {}?'.format(
                fixture.home, fixture.away)
            if not self.focus_store.reserve(message.guild.id, day, message.id,
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
            try:
                sent = await channel.send(embed=embed, view=view, nonce=message.id,
                                          allowed_mentions=discord.AllowedMentions.none())
                self.focus_store.finish(message.guild.id, day, sent.id)
                print('Matchday focus sent source={} discussion={}'.format(
                    message.id, sent.id), flush=True)
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

    async def run_followups(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.send_pending_pulses_due()
                await self.send_followups_due()
            except Exception as exc:
                print('Match to Squad worker failed: ' + type(exc).__name__, flush=True)
            await asyncio.sleep(60)

    async def handle_chat(self, message):
        guild_id, channel_id = message.guild.id, message.channel.id
        content = message.content or ''
        if not content.strip():
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
        if trigger is None:
            return False
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
        await message.reply(answer[:1900],
                            mention_author=True,
                            allowed_mentions=discord.AllowedMentions(users=[message.author]),
                            **extra)
        return True

    async def do_chat(self, interaction, text):
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
        await interaction.followup.send('<@{}> {}'.format(interaction.user.id, answer), **extra)

    async def do_drop(self, interaction):
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
            embed = discord.Embed(
                title='\U0001F4AC FC27 daily topic',
                description=topic,
                color=0x5865F2)
            embed.add_field(name='How to talk to me', value=HOW_TO_CHAT, inline=False)
            embed.set_footer(text='No prices or order details here \u00b7 use the order panel for that')
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
