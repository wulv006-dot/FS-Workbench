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
from pathlib import Path

import discord
from discord import app_commands

import chat_brain
import chat_panel
import chat_schedule
import matchday_engagement
import matchday_editorial
import matchday_scout_bridge

MAX_HISTORY = 10

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
    if config.get('matchday_editorial') is not None:
        matchday_editorial.validate_config(config['matchday_editorial'],
                                           config.get('matchday_engagement'))
    token_env = config.get('token_env', 'DISCORD_CHAT_BOT_TOKEN')
    if not os.environ.get(token_env):
        raise ValueError('missing bot token in environment variable ' + token_env)
    return validated


def guild_ids(chat_config):
    return [int(guild) for guild in chat_config['routes']]


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
        self.followup_task = None
        self.editorial_config = config.get('matchday_editorial')
        self.editorial_store = None
        self.editorial_task = None
        self.scout_seen_mtime_ns = None
        self.scout_lock = asyncio.Lock()
        self.editorial_last_error = None
        self.editorial_last_error_at = 0
        if self.matchday_config and self.matchday_config['enabled']:
            self.matchday_store = matchday_engagement.MatchPulseStore(
                self.matchday_config.get('state_path') or
                Path(__file__).parent / 'var' / 'match-pulse.sqlite3')
        if self.editorial_config and self.editorial_config['enabled']:
            self.editorial_store = matchday_editorial.EditorialPostStore(
                self.editorial_config['state_path'])

    # -- lifecycle ---------------------------------------------------------
    async def setup_hook(self):
        await self.add_commands()
        for guild_id in guild_ids(self.chat_config):
            await self.tree.sync(guild=discord.Object(guild_id))
        targets = chat_panel.topic_targets(self.chat_config)
        if self.post_topic_now:
            self.topic_task = asyncio.create_task(self.post_topics_once())
        elif targets and self.topic_pool:
            self.topic_task = asyncio.create_task(self.run_topics())
        if self.editorial_store is not None and not self.post_topic_now:
            self.editorial_task = asyncio.create_task(self.run_editorial())
        if self.matchday_store is not None and not self.post_topic_now:
            self.followup_task = asyncio.create_task(self.run_followups())

    async def on_ready(self):
        await self.setup_matchday_intro()

    async def setup_matchday_intro(self):
        route = (self.matchday_config or {}).get('routes', {}).get('1041923524601851914')
        if not route or not (self.matchday_config or {}).get('enabled'):
            return
        channel = self.get_channel(route['discussion_channel_id'])
        if channel is None or channel.guild.id != 1041923524601851914:
            print('Matchday intro channel unavailable', flush=True)
            return
        embed = discord.Embed(
            title='🏟️ FC27 Matchday Lounge',
            description=('Follow live football and predictions with **Smart Score** in Matchday. '
                         'Talk fixtures, goals and players here. Choose your club in Welcome; '
                         'MMOEXP FC Assistant handles private FUT price checks.'),
            colour=0x2275E8)
        view = discord.ui.View(timeout=None)
        for label, target in (
                ('Live matches', route['source_channel_id']),
                ('FC27 Players', route['players_channel_id']),
                ('FC27 Coins', route['coins_channel_id']),
                ('Choose a club', 1568663362567413820)):
            view.add_item(discord.ui.Button(label=label,
                url='https://discord.com/channels/1041923524601851914/{}'.format(target)))
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

    async def close(self):
        for task in (self.topic_task, self.editorial_task, self.followup_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        self.topic_task = None
        self.editorial_task = None
        self.followup_task = None
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
                await self.handle_match_pulse(message)
            if self.editorial_store is not None:
                await self.handle_scout_card(message)
            return
        if message.guild is None:
            return
        await self.handle_chat(message)

    async def handle_match_pulse(self, message):
        pulse = matchday_engagement.parse_smart_score(message, self.matchday_config, time.time())
        if pulse is None:
            return
        channel = self.get_channel(pulse.discussion_channel_id)
        if channel is None or channel.guild.id != pulse.guild_id:
            print('Matchday discussion channel unavailable source={}'.format(message.id), flush=True)
            return
        if not self.matchday_store.claim(message.id, pulse, time.time()):
            return
        embed = discord.Embed(title='⚽ Matchday chat',
                              description=matchday_engagement.prompt_text(pulse),
                              colour=0x2275E8)
        embed.set_footer(text='Match updates: Smart Score · FC27 tools: MMOEXP')
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label='Smart Score update', url=pulse.source_url))
        view.add_item(discord.ui.Button(label='FC27 Players',
            url='https://discord.com/channels/{}/{}'.format(pulse.guild_id, pulse.players_channel_id)))
        view.add_item(discord.ui.Button(label='FC27 Coins',
            url='https://discord.com/channels/{}/{}'.format(pulse.guild_id, pulse.coins_channel_id)))
        try:
            sent = await channel.send(embed=embed, view=view,
                                      allowed_mentions=discord.AllowedMentions.none())
            print('Matchday pulse sent source={} discussion={} kind={} delay_ms={}'.format(
                message.id, sent.id, pulse.kind,
                round((time.time() - message.created_at.timestamp()) * 1000)), flush=True)
            if pulse.kind == 'final':
                self.matchday_store.queue_followup(pulse, time.time())
            history = list(self.history.get(pulse.discussion_channel_id, ()))
            history.append(('assistant', 'Smart Score public update: ' +
                            matchday_engagement.prompt_text(pulse)))
            self.history[pulse.discussion_channel_id] = history[-MAX_HISTORY:]
        except discord.DiscordException as exc:
            print('Matchday prompt failed source={} kind={}: {}'.format(
                message.id, pulse.kind, type(exc).__name__), flush=True)

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
            embed.set_footer(text='Match result: Smart Score · FC27 tools: MMOEXP')
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='Smart Score final', url=pulse.source_url))
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
                await self.send_followups_due()
            except Exception as exc:
                print('Match to Squad worker failed: ' + type(exc).__name__, flush=True)
            await asyncio.sleep(60)

    # -- selected fixture editorial ---------------------------------------
    async def handle_scout_card(self, message):
        if (message.author.id != matchday_engagement.SMART_SCORE_ID or
                message.guild is None or
                str(message.guild.id) not in self.editorial_config['allowed_guild_ids'] or
                not any(embed.title == 'Upcoming Matches' for embed in message.embeds)):
            return
        await self.refresh_scout_plan([message])

    async def refresh_scout_plan(self, source_messages=None):
        scout_path = (self.editorial_config or {}).get('scout_path')
        if not scout_path:
            return
        async with self.scout_lock:
            try:
                scout_file = Path(scout_path)
                mtime = scout_file.stat().st_mtime_ns
                if source_messages is None and mtime == self.scout_seen_mtime_ns:
                    return
                now = discord.utils.utcnow()
                matches = matchday_scout_bridge.load_scout(scout_file, now)
                if not matches:
                    self.scout_seen_mtime_ns = mtime
                    return
                path = Path(self.editorial_config['plan_path'])
                before = path.stat()
                plan = json.loads(path.read_text(encoding='utf-8'))
                routes = {guild: self.matchday_config['routes'][guild]
                          for guild in self.editorial_config['allowed_guild_ids']}
                weekly = self.editorial_config.get('max_matches_per_london_week', 2)
                matchday_editorial.load_plan(path, routes, now=now, weekly_limit=weekly)
                changed = False
                for guild_id, route in routes.items():
                    channel = self.get_channel(route['source_channel_id'])
                    if channel is None or channel.guild.id != int(guild_id):
                        continue
                    if source_messages is None:
                        messages = [message async for message in channel.history(limit=100)]
                    else:
                        messages = source_messages
                    proposed, receipt = matchday_scout_bridge.merge_plan(
                        matches, messages, plan, int(guild_id),
                        route['source_channel_id'], now, weekly)
                    if receipt['added']:
                        plan = proposed
                        changed = True
                    print('Scout bridge: ' + json.dumps(receipt, ensure_ascii=False), flush=True)
                if changed and not matchday_scout_bridge.replace_plan(
                        path, (before.st_mtime_ns, before.st_size), plan):
                    self.editorial_error('Scout bridge kept a newer operator plan')
                    return
                self.scout_seen_mtime_ns = mtime
            except (OSError, ValueError, KeyError, TypeError, discord.DiscordException) as exc:
                self.editorial_error('Scout bridge unavailable: ' + type(exc).__name__)

    def editorial_error(self, message):
        now = time.time()
        if (message != self.editorial_last_error or
                now - self.editorial_last_error_at >= 600):
            print(message, flush=True)
            self.editorial_last_error = message
            self.editorial_last_error_at = now

    @staticmethod
    def editorial_card(fixture, phase):
        if fixture.status == 'hold':
            embed = discord.Embed(
                title='⚠️ Matchday schedule under review',
                description=('Kickoff details may have changed. Check Smart Score '
                             'for the latest information. New prompts are paused.'),
                colour=0xF0B232)
        else:
            embed = discord.Embed(
                title='⚽ Matchday · {} vs {}'.format(fixture.home, fixture.away),
                description=matchday_editorial.card_text(fixture, phase),
                colour=0x2275E8)
        embed.set_footer(text='Source: Smart Score · Matchday Host is AI-assisted')
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label='Smart Score fixture',
                                        url=fixture.source_url))
        return embed, view

    async def send_editorial_due(self):
        try:
            routes = {guild: self.matchday_config['routes'][guild]
                      for guild in self.editorial_config['allowed_guild_ids']}
            fixtures = matchday_editorial.load_plan(
                self.editorial_config['plan_path'], routes,
                weekly_limit=self.editorial_config.get('max_matches_per_london_week', 2))
        except (KeyError, OSError, ValueError, TypeError) as exc:
            self.editorial_error('Matchday editorial plan unavailable: ' +
                                 type(exc).__name__)
            return
        for fixture in fixtures:
            channel = self.get_channel(fixture.discussion_channel_id)
            if channel is None or channel.guild.id != fixture.guild_id:
                self.editorial_error('Editorial discussion channel unavailable')
                continue
            rows = self.editorial_store.records(fixture)
            if any(row[1] in ('sending', 'unknown') for row in rows):
                self.editorial_error('Editorial prior post needs reconciliation')
                continue
            updates = [row for row in rows if row[1] == 'sent' and
                       ((fixture.status == 'hold' and row[5] != 'hold') or
                        (fixture.status == 'scheduled' and
                         (row[5] != 'normal' or row[3] != fixture.source_url or
                          row[4] != int(fixture.kickoff_at.timestamp()))))]
            due = [(selected, phase) for selected, phase in
                   matchday_editorial.due_cards([fixture])
                   if self.editorial_store.status(selected, phase) is None]
            if not updates and not due:
                continue
            if fixture.status == 'scheduled':
                source_channel = self.get_channel(fixture.source_channel_id)
                if source_channel is None or source_channel.guild.id != fixture.guild_id:
                    self.editorial_error('Editorial Smart Score channel unavailable')
                    continue
                try:
                    source_message = await source_channel.fetch_message(fixture.source_message_id)
                except discord.DiscordException as exc:
                    self.editorial_error('Editorial source unavailable: ' + type(exc).__name__)
                    continue
                if not matchday_editorial.verify_smart_score_source(source_message, fixture):
                    self.editorial_error('Editorial source card does not match selected fixture')
                    continue
            edit_failed = False
            for phase, _, message_id, _, _, _ in updates:
                try:
                    previous = await channel.fetch_message(int(message_id))
                    if (self.user is None or previous.author.id != self.user.id or
                            not previous.embeds or not str(previous.embeds[0].title or '').startswith(
                                ('⚽ Matchday ·', '⚠️ Matchday schedule under review'))):
                        raise ValueError('Editorial original card identity mismatch')
                    embed, view = self.editorial_card(fixture, phase)
                    await previous.edit(embed=embed, view=view)
                    self.editorial_store.mark_display(fixture, phase, message_id)
                except (discord.DiscordException, OSError, TypeError, ValueError, RuntimeError) as exc:
                    self.editorial_error('Editorial correction failed: ' + type(exc).__name__)
                    edit_failed = True
                    break
            if edit_failed:
                continue
            for _, phase in due:
                if not self.editorial_store.reserve(fixture, phase, time.time()):
                    continue
                embed, view = self.editorial_card(fixture, phase)
                try:
                    sent = await channel.send(embed=embed, view=view,
                                              allowed_mentions=discord.AllowedMentions.none())
                    self.editorial_store.finish(fixture, phase, sent.id)
                    self.editorial_last_error = None
                except Exception as exc:
                    self.editorial_store.unknown(fixture, phase)
                    print('Editorial post result unknown: ' + type(exc).__name__, flush=True)

    async def run_editorial(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self.refresh_scout_plan()
                await self.send_editorial_due()
            except Exception as exc:
                self.editorial_error('Matchday editorial worker failed: ' +
                                     type(exc).__name__)
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
