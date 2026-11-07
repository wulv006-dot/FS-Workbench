"""Opt-in FC alerts stored only in five configured, permissionless Discord roles."""
import asyncio

import discord

from club_panel import MENTIONS, ROLE_CHANGE_LOCK, safe_club_role

ALERTS = {'sbc': ('🧩', 'SBC'), 'evolutions': ('🧬', 'Evolutions'),
          'objectives': ('💎', 'Objectives & Rush'), 'news': ('📰', 'News'),
          'giveaways': ('🎁', 'Giveaways')}
API_ERRORS = (discord.HTTPException, OSError, asyncio.TimeoutError)
UPDATE_ERRORS = API_ERRORS + (ValueError,)


def validate_alert_config(config):
    if not isinstance(config, dict):
        raise ValueError('Invalid alert configuration')
    guild_id, channels, roles = (config.get(k) for k in ('guild_id', 'channel_ids', 'role_ids'))
    if (type(guild_id) is not int or guild_id <= 0 or not isinstance(channels, (list, tuple))
            or not channels or any(type(c) is not int or c <= 0 for c in channels)
            or len(set(channels)) != len(channels) or not isinstance(roles, dict)
            or set(roles) != set(ALERTS)
            or any(type(r) is not int or r <= 0 for r in roles.values())
            or len(set(roles.values())) != len(ALERTS)):
        raise ValueError('Alerts require a guild, channels and five unique role IDs')
    return {'guild_id': guild_id, 'channel_ids': list(channels), 'role_ids': dict(roles)}


async def valid_route(interaction, config, owner=None):
    valid = (interaction.guild_id == config['guild_id'] and interaction.guild is not None
             and interaction.guild.id == config['guild_id']
             and interaction.channel_id in config['channel_ids'] and not interaction.user.bot
             and (owner is None or interaction.user.id == owner))
    if not valid:
        await interaction.response.send_message('Open your own alert menu in FC27.',
                                                ephemeral=True, allowed_mentions=MENTIONS)
    return valid


class AlertHomeView(discord.ui.View):
    def __init__(self, config):
        super().__init__(timeout=None)
        self.config = validate_alert_config(config)

    @discord.ui.button(label='Set alerts', emoji='🔔', style=discord.ButtonStyle.secondary,
                       custom_id='fc:alerts:open')
    async def open_alerts(self, interaction, button):
        if not await valid_route(interaction, self.config):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
            if member.id != interaction.user.id or member.bot:
                raise ValueError('Member mismatch')
        except UPDATE_ERRORS:
            await interaction.followup.send('Alerts unavailable. Please try again.', ephemeral=True,
                                            allowed_mentions=MENTIONS)
            return
        role_ids = {r.id for r in member.roles}
        selected = [key for key, rid in self.config['role_ids'].items() if rid in role_ids]
        panel = AlertPreferencesView(self.config, member.id, selected)
        panel.origin = interaction
        await interaction.followup.send('🔔 **Your alerts**\nChoose topics, then save.', view=panel,
                                        ephemeral=True, allowed_mentions=MENTIONS)


class AlertSelect(discord.ui.Select):
    def __init__(self, selected):
        super().__init__(placeholder='Choose your alerts', min_values=0, max_values=5,
            options=[discord.SelectOption(label=label, emoji=emoji, value=key, default=key in selected)
                     for key, (emoji, label) in ALERTS.items()])

    async def callback(self, interaction):
        if not await valid_route(interaction, self.view.config, self.view.owner):
            return
        self.view.selected = set(self.values)
        for option in self.options:
            option.default = option.value in self.view.selected
        await interaction.response.edit_message(content='🔔 **Your alerts**\nTap Save alerts to apply.',
                                                 view=self.view, allowed_mentions=MENTIONS)


class AlertPreferencesView(discord.ui.View):
    def __init__(self, config, owner, selected=()):
        super().__init__(timeout=180)
        self.config = validate_alert_config(config)
        if type(owner) is not int or owner <= 0 or set(selected) - set(ALERTS):
            raise ValueError('Invalid alert actor or selection')
        self.owner, self.selected, self.origin = owner, set(selected), None
        self.add_item(AlertSelect(self.selected))

    @discord.ui.button(label='Save alerts', style=discord.ButtonStyle.primary, row=1)
    async def save_button(self, interaction, button):
        await self.save(interaction)

    @discord.ui.button(label='Turn all off', style=discord.ButtonStyle.secondary, row=1)
    async def clear_button(self, interaction, button):
        await self.save(interaction, clear=True)

    async def save(self, interaction, clear=False):
        if not await valid_route(interaction, self.config, self.owner):
            return
        desired_keys = set() if clear else set(self.selected)
        if desired_keys - set(ALERTS):
            await interaction.response.send_message('Please reopen the alert menu.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return
        await interaction.response.defer(thinking=False)
        message = 'Could not save alerts. Reopen to check your settings.'
        # Shared lock also serializes team-role updates; atomic single-role APIs preserve other roles.
        async with ROLE_CHANGE_LOCK:
            guild, role_map = interaction.guild, self.config['role_ids']
            bot = guild.me
            roles = {key: guild.get_role(rid) for key, rid in role_map.items()}
            if bot and bot.guild_permissions.manage_roles and all(
                    safe_club_role(role, bot, guild) for role in roles.values()):
                before = None
                try:
                    member = await guild.fetch_member(self.owner)
                    if member.id != self.owner or member.bot:
                        raise ValueError('Member mismatch')
                    before = {key for key, role in roles.items() if role.id in {r.id for r in member.roles}}
                    await self._apply(member, roles, before, desired_keys)
                    verified = await guild.fetch_member(self.owner)
                    actual = {key for key, role in roles.items() if role.id in {r.id for r in verified.roles}}
                    if verified.id != self.owner or verified.bot or actual != desired_keys:
                        raise ValueError('Alert update not confirmed')
                    self.selected = desired_keys
                    for child in self.children:
                        if isinstance(child, AlertSelect):
                            for option in child.options:
                                option.default = option.value in desired_keys
                    message = '✅ Alerts saved.' if desired_keys else '🔕 All alerts off.'
                except UPDATE_ERRORS:
                    if before is not None:
                        try:
                            current = await guild.fetch_member(self.owner)
                            if current.id == self.owner and not current.bot and all(
                                    safe_club_role(role, bot, guild) for role in roles.values()):
                                now = {k for k, r in roles.items() if r.id in {r.id for r in current.roles}}
                                await self._apply(current, roles, now, before, rollback=True)
                        except API_ERRORS:
                            pass  # No success claim: next open reads the real membership again.
        await interaction.edit_original_response(content=message, view=self,
                                                 allowed_mentions=MENTIONS)

    @staticmethod
    async def _apply(member, roles, current, desired, rollback=False):
        reason = 'MMOEXP alert preferences' + (' rollback' if rollback else '')
        for key in ALERTS:
            if key in desired - current:
                await member.add_roles(roles[key], reason=reason, atomic=True)
        for key in ALERTS:
            if key in current - desired:
                await member.remove_roles(roles[key], reason=reason, atomic=True)

    async def on_timeout(self):
        if self.origin:
            try:
                await self.origin.edit_original_response(content='⏱️ Menu expired. Tap Set alerts.',
                                                         view=AlertHomeView(self.config),
                                                         allowed_mentions=MENTIONS)
            except API_ERRORS:
                pass
