"""Persistent MMOEXP club preferences; only configured, permissionless roles are assignable."""
import asyncio
from urllib.parse import urlsplit

import discord

MENTIONS = discord.AllowedMentions.none()


def newcomer_guide(guild_id):
    if guild_id != OFFICIAL_GUILD:
        return ''
    base = f'https://discord.com/channels/{guild_id}/'
    return (
        '\n[Explore the FC event](' + base + '1568663362567413820/1576171859341221909) or '
        '[join FC Chat](' + base + '1200330251016867880). '
        'Which position would you upgrade first? Tell us your platform and coin budget.'
    )

CLUBS = {
    'england': (
        ('arsenal', 'Arsenal'), ('aston_villa', 'Aston Villa'), ('bournemouth', 'Bournemouth'),
        ('brentford', 'Brentford'), ('brighton', 'Brighton'), ('burnley', 'Burnley'),
        ('chelsea', 'Chelsea'), ('coventry', 'Coventry'), ('crystal_palace', 'Crystal Palace'),
        ('everton', 'Everton'), ('fulham', 'Fulham'), ('hull', 'Hull'), ('ipswich', 'Ipswich'),
        ('leeds', 'Leeds'), ('leicester', 'Leicester'), ('liverpool', 'Liverpool'),
        ('man_city', 'Man City'), ('man_united', 'Man United'), ('middlesbrough', 'Middlesbrough'),
        ('newcastle', 'Newcastle'), ('nottingham_forest', 'Forest'), ('southampton', 'Southampton'),
        ('tottenham', 'Spurs'), ('sunderland', 'Sunderland'), ('west_ham', 'West Ham'),
    ),
    'europe': (
        ('ajax', 'Ajax'), ('atletico', 'Atlético'), ('barcelona', 'Barca'), ('bayern', 'Bayern'),
        ('benfica', 'Benfica'), ('celtic', 'Celtic'), ('dortmund', 'Dortmund'),
        ('fenerbahce', 'Fenerbahce'), ('feyenoord', 'Feyenoord'), ('galatasaray', 'Galatasaray'),
        ('inter', 'Inter'), ('juventus', 'Juventus'), ('leverkusen', 'Leverkusen'), ('lyon', 'Lyon'),
        ('real_madrid', 'Madrid'), ('marseille', 'Marseille'), ('milan', 'Milan'), ('napoli', 'Napoli'),
        ('psg', 'PSG'), ('psv', 'PSV'), ('rangers', 'Rangers'), ('roma', 'Roma'),
    ),
}
# ponytail: serialize role changes across both cards; use per-member locks if volume requires it.
ROLE_CHANGE_LOCK = asyncio.Lock()


def brand_embed(embed, presentation=None):
    """Use operator-supplied MMOEXP assets; no third-party assets are fetched or inferred."""
    presentation = presentation or {}
    for key, setter in [('avatar_url', embed.set_thumbnail), ('banner_url', embed.set_image)]:
        value = presentation.get(key)
        if value:
            parts = urlsplit(value)
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
                raise ValueError('Branding assets must use HTTPS')
            setter(url=value)
    embed.set_author(name='MMOEXP · FC 27 Community')
    return embed


def welcome_embed(presentation=None, guild_id=None):
    description = ('📰 FC 27 News · 📅 Matchday · 💬 Match Chat\n'
                   '⚽ Players · 💰 Private quotes\n\n'
                   'Tap **Join FC27** to chat. Pick your club below.')
    embed = discord.Embed(title='Welcome to the MMOEXP FC 27 Club', color=0xF28C28,
                          description=description)
    embed.set_footer(text='Your club. Your squad. Your community.')
    return brand_embed(embed, presentation)


def club_embed(section, presentation=None):
    if section not in CLUBS:
        raise ValueError('Unsupported club section')
    title = 'English football clubs' if section == 'england' else 'Other European clubs'
    embed = discord.Embed(title=title, color=0xF28C28,
        description='Pick one club across both lists. Click another team to switch.')
    return embed


def safe_club_role(role, bot_member, guild):
    return (role is not None and not role.is_default() and not role.managed
            and role.permissions.value == 0 and role < bot_member.top_role
            and not any(channel.overwrites_for(role).pair()[0].value
                        for channel in getattr(guild, 'channels', ())))


OFFICIAL_GUILD = 1041923524601851914
FC27_SEND_CHANNELS = frozenset((1200330251016867880, 1280777367219998786,
                                1571043570268242014))
SEND_MESSAGES = discord.Permissions(send_messages=True).value


def safe_community_role(role, bot_member, guild):
    """FC27 membership may grant Send Messages only in the three FC chat rooms."""
    if (role is None or role.is_default() or role.managed or role.permissions.value != 0
            or not role < bot_member.top_role):
        return False
    for channel in getattr(guild, 'channels', ()):
        allowed, _ = channel.overwrites_for(role).pair()
        if allowed.value and (guild.id != OFFICIAL_GUILD or channel.id not in FC27_SEND_CHANNELS
                              or allowed.value & ~SEND_MESSAGES):
            return False
    return True


class ClubPanelView(discord.ui.View):
    def __init__(self, guild_id, channel_id, section, role_ids, emoji_map=None, community_role_id=None):
        super().__init__(timeout=None)
        if (section not in CLUBS or type(guild_id) is not int or guild_id <= 0
                or type(channel_id) is not int or channel_id <= 0):
            raise ValueError('Invalid club route')
        known = {slug for rows in CLUBS.values() for slug, _ in rows}
        if (set(role_ids) - known or any(type(value) is not int or value <= 0 for value in role_ids.values())
                or len(set(role_ids.values())) != len(role_ids)):
            raise ValueError('Club roles must be unique positive IDs for known clubs')
        if community_role_id is not None and (type(community_role_id) is not int or community_role_id <= 0
                                              or community_role_id in role_ids.values()):
            raise ValueError('Community role must be a separate positive ID')
        self.guild_id, self.channel_id, self.section = guild_id, channel_id, section
        self.role_ids = dict(role_ids)
        self.community_role_id = community_role_id
        for index, (slug, label) in enumerate(CLUBS[section]):
            self.add_item(ClubButton(section, slug, label, index // 5, slug not in role_ids,
                                     (emoji_map or {}).get(slug)))

    async def interaction_check(self, interaction):
        if (interaction.guild_id != self.guild_id or interaction.channel_id != self.channel_id
                or interaction.guild is None or interaction.guild.id != self.guild_id or interaction.user.bot):
            await interaction.response.send_message('This club menu is not available here.',
                                                    ephemeral=True, allowed_mentions=MENTIONS)
            return False
        return True


class ClubButton(discord.ui.Button):
    def __init__(self, section, slug, label, row, disabled, emoji):
        style = discord.ButtonStyle.secondary
        super().__init__(label=label, style=style, row=row, disabled=disabled,
                         emoji=emoji, custom_id='fc:club:{}:{}'.format(section, slug))
        self.slug = slug

    async def callback(self, interaction):
        view = self.view
        if not await view.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        message = 'I could not update your club. Please ask a moderator to check club roles and bot permissions.'
        async with ROLE_CHANGE_LOCK:
            guild = interaction.guild
            bot = guild.me
            target = guild.get_role(view.role_ids.get(self.slug))
            community_role = guild.get_role(view.community_role_id) if view.community_role_id else None
            if (bot and bot.guild_permissions.manage_roles and safe_club_role(target, bot, guild)
                    and (view.community_role_id is None or safe_community_role(community_role, bot, guild))):
                added = []
                try:
                    member = await guild.fetch_member(interaction.user.id)
                    previous = [role for role in member.roles
                                if role.id in view.role_ids.values() and role.id != target.id]
                    if (member.id == interaction.user.id and not member.bot
                            and all(safe_club_role(role, bot, guild) for role in previous)):
                        existing = {role.id for role in member.roles}
                        for role in (community_role, target):
                            if role is not None and role.id not in existing:
                                await member.add_roles(role, reason='MMOEXP club preference', atomic=True)
                                added.append(role)
                        if previous:
                            await member.remove_roles(*previous, reason='MMOEXP club preference', atomic=True)
                        message = 'Your club is now **{}**. You can change it any time.'.format(self.label)
                        if target in added and not previous:
                            message += newcomer_guide(guild.id)
                except discord.HTTPException:
                    for role in reversed(added):
                        try:
                            await member.remove_roles(role, reason='MMOEXP club preference rollback', atomic=True)
                        except discord.HTTPException:
                            pass
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=MENTIONS)
