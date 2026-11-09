"""Opt-in game badges and private navigation, limited to the deployment's 24-game allowlist."""
import asyncio
import re

import discord

from club_panel import MENTIONS, ROLE_CHANGE_LOCK

OFFICIAL_GUILD = 1041923524601851914
TEST_GUILD = 1565922092518613064
GENERAL_CHAT_CHANNEL_ID = 1264777473283981336
API_ERRORS = (discord.HTTPException, OSError, asyncio.TimeoutError)
UPDATE_ERRORS = API_ERRORS + (ValueError,)
# Native game roles may grant ordinary channel access. Anything outside this list fails closed.
ORDINARY_CHANNEL_PERMISSIONS = discord.Permissions(**dict.fromkeys((
    'create_instant_invite', 'view_channel', 'read_message_history', 'send_messages', 'send_tts_messages', 'add_reactions',
    'embed_links', 'attach_files', 'use_external_emojis', 'use_external_stickers', 'connect', 'speak',
    'stream', 'use_voice_activation', 'request_to_speak', 'use_application_commands',
    'create_public_threads', 'create_private_threads', 'send_messages_in_threads',
    'send_voice_messages', 'send_polls', 'use_soundboard', 'use_external_sounds', 'use_external_apps',
), True)).value


def validate_game_config(config):
    if (not isinstance(config, dict) or set(config) != {'guild_id', 'channel_id', 'games'}
            or type(config['guild_id']) is not int or config['guild_id'] not in (OFFICIAL_GUILD, TEST_GUILD)
            or type(config['channel_id']) is not int or config['channel_id'] <= 0
            or not isinstance(config['games'], list) or len(config['games']) != 24):
        raise ValueError('Game picker requires an approved guild, channel and exactly 24 games')
    games, keys, assigned_roles = [], set(), set()
    for game in config['games']:
        if (not isinstance(game, dict) or set(game) != {'key', 'label', 'role_ids', 'channel_ids'}
                or not isinstance(game['key'], str) or not re.fullmatch(r'[a-z0-9_]{1,32}', game['key'])
                or game['key'] in keys or not isinstance(game['label'], str)
                or not game['label'].strip() or len(game['label']) > 80
                or any(ord(character) < 32 for character in game['label'])):
            raise ValueError('Invalid game key or label')
        for field, maximum in [('role_ids', 5), ('channel_ids', 24)]:
            values = game[field]
            if (not isinstance(values, list) or len(values) > maximum
                    or any(type(value) is not int or value <= 0 for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError('Invalid game role or channel allowlist')
        if assigned_roles.intersection(game['role_ids']):
            raise ValueError('A game role must belong to only one game')
        assigned_roles.update(game['role_ids'])
        keys.add(game['key'])
        games.append(dict(key=game['key'], label=game['label'], role_ids=list(game['role_ids']),
                          channel_ids=list(game['channel_ids'])))
    return dict(guild_id=config['guild_id'], channel_id=config['channel_id'], games=games)


def game_picker_embed():
    return discord.Embed(title='Choose your games', color=0x3498DB,
        description=('Select any games you play. You can choose more than one.\n'
                     'Each button adds your game badge and opens a private channel guide.\n\n'
                     'Use **Channels & Roles** to customize your sidebar.'))


def safe_game_role(role, bot, guild, allowlist):
    return (role is not None and role.id in allowlist and not role.is_default() and not role.managed
            and role.permissions.value == 0 and role < bot.top_role
            and not any(channel.overwrites_for(role).pair()[0].value & ~ORDINARY_CHANNEL_PERMISSIONS
                        for channel in guild.channels))


async def valid_route(interaction, config, owner=None):
    if (interaction.guild_id != config['guild_id'] or interaction.channel_id != config['channel_id']
            or interaction.guild is None or interaction.guild.id != config['guild_id']
            or interaction.user.bot or (owner is not None and interaction.user.id != owner)):
        await interaction.response.send_message('Open your own game menu in Choose your game.',
                                                ephemeral=True, allowed_mentions=MENTIONS)
        return False
    return True


async def fetch_actor(guild, actor_id):
    member = await guild.fetch_member(actor_id)
    if member.id != actor_id or member.bot:
        raise ValueError('Game selection actor mismatch')
    return member


async def change_game_roles(guild, actor_id, game, allowlist, join):
    """Mutate only this game's allowlisted IDs; verify and reconcile uncertain API outcomes."""
    async with ROLE_CHANGE_LOCK:
        bot = guild.me
        roles = [guild.get_role(role_id) for role_id in game['role_ids']]
        if (not bot or not bot.guild_permissions.manage_roles
                or not all(safe_game_role(role, bot, guild, allowlist) for role in roles)):
            raise ValueError('Game roles are not safely manageable')
        member = await fetch_actor(guild, actor_id)
        selected_ids = set(game['role_ids'])
        before = {role.id for role in member.roles} & selected_ids
        desired = selected_ids if join else set()
        try:
            for role in roles:
                if role.id in desired - before:
                    await member.add_roles(role, reason='MMOEXP game opt-in', atomic=True)
                elif role.id in before - desired:
                    await member.remove_roles(role, reason='MMOEXP game opt-out', atomic=True)
            verified = await fetch_actor(guild, actor_id)
            if {role.id for role in verified.roles} & selected_ids != desired:
                raise ValueError('Game membership not confirmed')
            return verified
        except UPDATE_ERRORS:
            try:
                current = await fetch_actor(guild, actor_id)
                if all(safe_game_role(role, bot, guild, allowlist) for role in roles):
                    actual = {role.id for role in current.roles} & selected_ids
                    for role in roles:
                        if role.id in before - actual:
                            await current.add_roles(role, reason='MMOEXP game preference rollback', atomic=True)
                        elif role.id in actual - before:
                            await current.remove_roles(role, reason='MMOEXP game preference rollback', atomic=True)
            except UPDATE_ERRORS:
                pass
            raise


class GamePickerView(discord.ui.View):
    def __init__(self, config):
        super().__init__(timeout=None)
        self.config = validate_game_config(config)
        self.role_allowlist = {role_id for game in self.config['games'] for role_id in game['role_ids']}
        styles = (discord.ButtonStyle.primary, discord.ButtonStyle.success, discord.ButtonStyle.secondary)
        for index, game in enumerate(self.config['games']):
            self.add_item(GameButton(game['key'], game['label'], index // 5, styles[index % len(styles)]))


class GameButton(discord.ui.Button):
    def __init__(self, key, label, row, style):
        super().__init__(label=label, custom_id='mmoexp:game:' + key, row=row, style=style)
        self.key = key

    async def callback(self, interaction):
        if not await valid_route(interaction, self.view.config):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        game = next(game for game in self.view.config['games'] if game['key'] == self.key)
        content, panel = await game_result(interaction, self.view.config, game, self.view.role_allowlist, True)
        await interaction.followup.send(content, view=panel, ephemeral=True, allowed_mentions=MENTIONS)


async def game_result(interaction, config, game, allowlist, join):
    member = None
    label = discord.utils.escape_markdown(discord.utils.escape_mentions(game['label']))
    try:
        member = await change_game_roles(interaction.guild, interaction.user.id, game, allowlist, join)
        text = ('✅ **{}** selected. You can select other games too.' if join else
                'Your **{}** game role was removed. Other games were kept.').format(label)
        if not game['role_ids']:
            text = '**{}** channel guide. No game role is configured.'.format(label)
    except UPDATE_ERRORS:
        text = 'I could not update your game roles. Reopen the menu or ask a moderator to check.'
        try:
            member = await fetch_actor(interaction.guild, interaction.user.id)
        except UPDATE_ERRORS:
            pass
    fallback = not game['channel_ids'] or game['channel_ids'] == [GENERAL_CHAT_CHANNEL_ID]
    if fallback:
        text += '\nThis game has no dedicated section yet. Use the shared community lounge below.'
    text += ('\n\nGame roles do not automatically add channels to your sidebar. '
             'Open **Channels & Roles** in the server to customize your channel list.')
    panel = GameSelectionView(config, game, interaction.user.id, member, interaction.guild, allowlist)
    if not any(button.url for button in panel.children):
        text += '\nNo readable channel links are available right now. Please ask a moderator.'
    return text, panel


class GameSelectionView(discord.ui.View):
    def __init__(self, config, game, owner, member, guild, allowlist):
        super().__init__(timeout=180)
        self.config, self.game, self.owner, self.role_allowlist = config, game, owner, allowlist
        selected = member is not None and bool({role.id for role in member.roles} & set(game['role_ids']))
        if selected:
            self.add_item(RemoveGameButton())
        for channel_id in game['channel_ids'] or ([GENERAL_CHAT_CHANNEL_ID] if guild.id == OFFICIAL_GUILD else []):
            channel = guild.get_channel(channel_id)
            if member is None or channel is None or channel.guild.id != config['guild_id']:
                continue
            permissions = channel.permissions_for(member)
            if permissions.view_channel and permissions.read_message_history:
                label = 'Community lounge' if channel_id == GENERAL_CHAT_CHANNEL_ID else channel.name
                self.add_item(discord.ui.Button(label=label[:80],
                    url='https://discord.com/channels/{}/{}'.format(config['guild_id'], channel_id)))


class RemoveGameButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='Remove this game role', style=discord.ButtonStyle.secondary,
                         custom_id='mmoexp:game:remove')

    async def callback(self, interaction):
        view = self.view
        if not await valid_route(interaction, view.config, view.owner):
            return
        await interaction.response.defer()
        content, panel = await game_result(interaction, view.config, view.game, view.role_allowlist, False)
        await interaction.edit_original_response(content=content, view=panel, allowed_mentions=MENTIONS)
