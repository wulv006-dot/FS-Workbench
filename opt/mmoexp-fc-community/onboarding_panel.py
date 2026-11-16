"""Compact welcome navigation and opt-in, permissionless FC27 membership."""
import discord

from club_panel import CLUBS, ClubButton, ClubPanelView, MENTIONS, ROLE_CHANGE_LOCK, club_embed, safe_community_role

OFFICIAL_GUILD = 1041923524601851914
PLAYER_CHANNEL = 1568878333087719454
SBC_CHANNEL = 1301379787696377926
HUB_CHANNEL = 1571045541922611200
MATCHDAY_CHANNEL = 1571043454136484082
MATCH_CHAT_CHANNEL = 1571043570268242014
CHANNELS = {
    'news': (('📰 Latest news', 1501757710381748254),),
    'daily': (('⚽ Players', PLAYER_CHANNEL), ('🧩 SBCs', SBC_CHANNEL),
              ('🎒 Objectives & packs', HUB_CHANNEL), ('📅 Matchday', MATCHDAY_CHANNEL),
              ('💬 Match Chat', MATCH_CHAT_CHANNEL)),
    'prices': (('⚽ Players', PLAYER_CHANNEL), ('💰 Coins', 1568663210901504041),
               ('🧩 SBCs', SBC_CHANNEL), ('🎒 Objectives & packs', HUB_CHANNEL)),
}


class OnboardingView(discord.ui.View):
    def __init__(self, clubs):
        super().__init__(timeout=None)
        # Reuse the role/route validation used by the underlying team controls.
        validated = ClubPanelView(clubs['guild_id'], clubs['channel_id'], 'england',
                                  clubs['role_ids'], clubs.get('emoji_map'), clubs.get('community_role_id'))
        self.clubs = dict(clubs)
        self.guild_id, self.channel_id = validated.guild_id, validated.channel_id
        self.community_role_id = validated.community_role_id

    async def interaction_check(self, interaction):
        if (interaction.guild_id != self.guild_id or interaction.channel_id != self.channel_id
                or interaction.guild is None or interaction.guild.id != self.guild_id or interaction.user.bot):
            await interaction.response.send_message('Open this menu in the FC27 welcome channel.',
                                                    ephemeral=True, allowed_mentions=MENTIONS)
            return False
        return True


class WelcomeView(OnboardingView):
    def __init__(self, clubs):
        super().__init__(clubs)
        for action, label, emoji in [('news', 'Latest news', '📰'), ('daily', 'Daily content', '🧩'),
                                     ('prices', 'Check prices', '💰'),
                                     ('join', 'Join FC27', '👋')]:
            self.add_item(WelcomeButton(action, label, emoji))
        self.children[-1].disabled = self.community_role_id is None
        if self.guild_id == OFFICIAL_GUILD:
            self.add_item(discord.ui.Button(label='Match Chat', emoji='💬',
                url=f'https://discord.com/channels/{OFFICIAL_GUILD}/{MATCH_CHAT_CHANNEL}'))


class PopularClubView(OnboardingView):
    def __init__(self, clubs):
        super().__init__(clubs)
        self.role_ids = dict(clubs['role_ids'])
        for section, slug, label in [('england', 'man_city', 'Man City'),
                                      ('europe', 'real_madrid', 'Real Madrid'),
                                      ('europe', 'barcelona', 'Barcelona'),
                                      ('europe', 'bayern', 'Bayern'), ('europe', 'psg', 'PSG')]:
            self.add_item(ClubButton(section, slug, label, 0, slug not in self.role_ids,
                                     clubs.get('emoji_map', {}).get(slug)))
        more = WelcomeButton('clubs', 'More clubs', '⚽')
        more.row = 1
        self.add_item(more)


class ClubSectionView(OnboardingView):
    def __init__(self, clubs, section=None):
        super().__init__(clubs)
        if section is not None and section not in CLUBS:
            raise ValueError('Unsupported club section')
        self.section = section
        for key in ([section] if section else CLUBS):
            label = 'English football clubs' if key == 'england' else 'Other European clubs'
            self.add_item(WelcomeButton('section:' + key, label, '⚽'))


class WelcomeButton(discord.ui.Button):
    def __init__(self, action, label, emoji):
        super().__init__(label=label, emoji=emoji, custom_id='fc:onboard:' + action,
                         style=discord.ButtonStyle.primary if action == 'join' else discord.ButtonStyle.secondary)
        self.action = action

    async def callback(self, interaction):
        view = self.view
        if not await view.interaction_check(interaction):
            return
        if self.action == 'join':
            await self.join(interaction)
            return
        if self.action == 'clubs':
            await interaction.response.send_message('⚽ Choose a club. Your FC27 role is included.',
                view=ClubSectionView(view.clubs), ephemeral=True, allowed_mentions=MENTIONS)
            return
        if self.action.startswith('section:'):
            section = self.action.split(':', 1)[1]
            clubs = view.clubs
            grid = ClubPanelView(view.guild_id, view.channel_id, section, clubs['role_ids'],
                                 clubs.get('emoji_map'), view.community_role_id)
            await interaction.response.send_message(embed=club_embed(section), view=grid,
                                                    ephemeral=True, allowed_mentions=MENTIONS)
            return
        destinations = CHANNELS[self.action] if view.guild_id == OFFICIAL_GUILD else [('FC27 welcome', view.channel_id)]
        links = discord.ui.View(timeout=None)
        for label, channel in destinations:
            links.add_item(discord.ui.Button(label=label,
                url='https://discord.com/channels/{}/{}'.format(view.guild_id, channel)))
        text = 'Open a channel below.' if self.action != 'prices' else 'Open a price card for a private quote.'
        await interaction.response.send_message(text, view=links, ephemeral=True, allowed_mentions=MENTIONS)

    async def join(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        message = 'Could not add FC27. Please ask a moderator.'
        async with ROLE_CHANGE_LOCK:
            guild, view = interaction.guild, self.view
            bot = guild.me
            target = guild.get_role(view.community_role_id) if view.community_role_id else None
            if bot and bot.guild_permissions.manage_roles and safe_community_role(target, bot, guild):
                try:
                    member = await guild.fetch_member(interaction.user.id)
                    if member.id == interaction.user.id and not member.bot:
                        if target.id not in {role.id for role in member.roles}:
                            await member.add_roles(target, reason='MMOEXP FC27 opt-in', atomic=True)
                        message = '⚽ You’re in! Explore FC27 or choose your club.'
                except discord.HTTPException:
                    pass
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=MENTIONS)
