"""Player-facing, test-guild-only FUT navigation."""
import asyncio
import time

import discord

from community import CommunityError

TEST_GUILD = 1565922092518613064
CATEGORIES = {
    'news': 'News', 'leak': 'Leaks', 'review': 'Player Reviews',
    'squad': 'Squad Guides', 'topic': 'Hot Topics', 'collection': 'FUT Gallery',
    'sbc': 'SBC Guides', 'bookmarks': 'My Saved', 'events': 'Events',
    'tools': 'FUT Tools',
}
INFORMATION_CATEGORIES = {**CATEGORIES, 'evolutions': 'Evolutions',
                          'objectives': 'Objectives', 'store': 'Store'}
MENTIONS = discord.AllowedMentions.none()


def home_embed():
    return discord.Embed(
        title='FUT Clubhouse',
        description='Your next FUT discovery starts here. Pick a section below to explore.',
        color=0xF28C28,
    )


def item_embed(item):
    embed = discord.Embed(title=item['title'], description=item['body'], color=0xF28C28)
    embed.add_field(name='Source', value=item['source'], inline=False)
    if item.get('published_at'):
        embed.add_field(name='Published', value='<t:{}:f>'.format(item['published_at']), inline=False)
    if item['kind'] == 'leak':
        embed.add_field(name='Heads up', value='Unconfirmed information — treat this as a rumour.', inline=False)
    if item.get('reviewed'):
        embed.add_field(name='Reviewed', value='<t:{}:f>'.format(item['reviewed']), inline=False)
    embed.set_footer(text='FC27 · {}'.format(INFORMATION_CATEGORIES.get(item['kind'], item['kind'])))
    return embed


class GuardedView(discord.ui.View):
    def __init__(self, store, guild_id, owner=None, timeout=180):
        super().__init__(timeout=timeout)
        self.store, self.guild_id, self.owner = store, guild_id, owner

    async def interaction_check(self, interaction):
        if (interaction.guild_id != self.guild_id or interaction.channel_id is None
                or interaction.user.bot or (self.owner is not None and interaction.user.id != self.owner)):
            await interaction.response.send_message('This menu is not available to you.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return False
        return True

    async def run(self, interaction, action, *args):
        try:
            return True, await asyncio.to_thread(action, *args)
        except CommunityError as exc:
            message = str(exc)
        except Exception:
            message = 'Something went wrong. Please try again later.'
        await interaction.response.send_message(message, ephemeral=True, allowed_mentions=MENTIONS)
        return False, None


class FutHomeView(GuardedView):
    def __init__(self, store, guild_id=TEST_GUILD, owner=None):
        if guild_id != TEST_GUILD:
            raise ValueError('Only the designated test guild is supported.')
        super().__init__(store, guild_id, owner, timeout=None if owner is None else 180)
        for index, (kind, label) in enumerate(CATEGORIES.items()):
            self.add_item(HomeButton(kind, label, row=index // 5))
        self.add_item(HomeSelect())

    async def show_category(self, interaction, kind):
        if kind not in INFORMATION_CATEGORIES:
            await interaction.response.send_message('That section is unavailable.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return
        if kind == 'tools':
            embed = discord.Embed(
                title='FUT Tools · EasySBC',
                description=('Explore tools on the EasySBC website using the buttons below. '
                             'For player cards, prices and Meta ratings in Discord, use '
                             '`/player` and select EasySBC EA FC Assistant.'),
                color=0xF28C28,
            )
            tools_view = ToolsView(self.store, self.guild_id, interaction.user.id)
            if self.owner is None:
                await interaction.response.send_message(embed=embed, view=tools_view, ephemeral=True,
                                                        allowed_mentions=MENTIONS)
            else:
                await interaction.response.edit_message(embed=embed, view=tools_view, allowed_mentions=MENTIONS)
            return
        if kind == 'events':
            ok, rows = await self.run(interaction, self.store.events, int(time.time()))
        elif kind == 'bookmarks':
            ok, rows = await self.run(interaction, self.store.bookmarks, interaction.user.id)
        else:
            ok, rows = await self.run(interaction, self.store.feed, kind, 10)
        if not ok:
            return
        rows = rows[:10]
        description = 'Choose an item to open it.'
        if kind == 'events':
            description = 'Choose an event to join or leave.'
        elif kind == 'sbc':
            description = 'Explore published guides. Automatic SBC solving is not available yet.'
        elif kind == 'squad':
            description = 'Explore published guides. Automatic squad recommendations are not available yet.'
        if not rows:
            description += ('\nNothing here yet. Check back soon!' if self.guild_id == TEST_GUILD
                            else '\nContent is not available yet. Check back soon!')
        embed = discord.Embed(title=INFORMATION_CATEGORIES[kind], description=description, color=0xF28C28)
        listing = ListingView(self.store, self.guild_id, interaction.user.id, kind, rows)
        if self.owner is None:
            await interaction.response.send_message(embed=embed, view=listing, ephemeral=True,
                                                    allowed_mentions=MENTIONS)
        else:
            await interaction.response.edit_message(embed=embed, view=listing, allowed_mentions=MENTIONS)


class HomeButton(discord.ui.Button):
    def __init__(self, kind, label, row):
        super().__init__(label=label, style=discord.ButtonStyle.primary,
                         custom_id='fut:home:' + kind, row=row)
        self.kind = kind

    async def callback(self, interaction):
        await self.view.show_category(interaction, self.kind)


class HomeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='Explore FUT', custom_id='fut:home:category', row=2,
                         options=[discord.SelectOption(label=label, value=key)
                                  for key, label in CATEGORIES.items()])

    async def callback(self, interaction):
        await self.view.show_category(interaction, self.values[0])


class BackHome(discord.ui.Button):
    def __init__(self):
        super().__init__(label='Home', style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction):
        view = self.view
        if view.guild_id != TEST_GUILD:
            await interaction.response.edit_message(
                embed=discord.Embed(title='FUT information',
                                    description='Use the channel panel to open this section again.'),
                view=None, allowed_mentions=MENTIONS)
            return
        await interaction.response.edit_message(embed=home_embed(),
            view=FutHomeView(view.store, view.guild_id, view.owner), allowed_mentions=MENTIONS)


class InformationPanelView(GuardedView):
    def __init__(self, store, guild_id, channels):
        super().__init__(store, guild_id, timeout=None)
        self.channels = {int(channel): kind for channel, kind in channels.items()}

    async def interaction_check(self, interaction):
        if not await super().interaction_check(interaction):
            return False
        if interaction.channel_id not in self.channels:
            await interaction.response.send_message('This menu is not available here.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return False
        return True

    @discord.ui.button(label='Explore', style=discord.ButtonStyle.primary, custom_id='fut:information:open')
    async def open_section(self, interaction, button):
        await FutHomeView.show_category(self, interaction, self.channels[interaction.channel_id])


class ToolsView(GuardedView):
    def __init__(self, store, guild_id, owner):
        super().__init__(store, guild_id, owner)
        for label, url in (
            ('Players', 'https://www.easysbc.io/players'),
            ('SBCs', 'https://www.easysbc.io/sbc'),
            ('Evolutions', 'https://www.easysbc.io/evolutions'),
            ('Gallery', 'https://www.easysbc.io/fut-gallery'),
        ):
            self.add_item(discord.ui.Button(label=label, url=url))
        self.add_item(BackHome())


class ListingView(GuardedView):
    def __init__(self, store, guild_id, owner, kind, rows):
        super().__init__(store, guild_id, owner)
        self.kind = kind
        self.rows = {str(row['id']): row for row in rows}
        if rows:
            self.add_item(ListingSelect(kind, rows))
        self.add_item(BackHome())


class ListingSelect(discord.ui.Select):
    def __init__(self, kind, rows):
        options = []
        for row in rows:
            description = None
            if kind == 'events':
                description = '{} / {} joined'.format(row['joined'], row['capacity'])
            options.append(discord.SelectOption(label=row['title'][:100], value=str(row['id']),
                                                description=description))
        super().__init__(placeholder='Choose an event' if kind == 'events' else 'Choose an article',
                         options=options)

    async def callback(self, interaction):
        view = self.view
        selected = self.values[0]
        if selected not in view.rows:
            await interaction.response.send_message('That selection is unavailable.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)
            return
        if view.kind == 'events':
            row = view.rows[selected]
            embed = discord.Embed(title=row['title'],
                                  description='{} / {} joined · closes <t:{}:R>'.format(
                                      row['joined'], row['capacity'], row['closes']), color=0xF28C28)
            next_view = EventView(view.store, view.guild_id, view.owner, row['id'])
        else:
            ok, row = await view.run(interaction, view.store.get, int(selected))
            if not ok:
                return
            embed = item_embed(row)
            next_view = ArticleView(view.store, view.guild_id, view.owner, row['id'], row['source'])
        await interaction.response.edit_message(embed=embed, view=next_view, allowed_mentions=MENTIONS)


class ArticleView(GuardedView):
    def __init__(self, store, guild_id, owner, item_id, source):
        super().__init__(store, guild_id, owner)
        self.item_id = item_id
        if guild_id != TEST_GUILD:
            self.remove_item(self.save)
        self.add_item(discord.ui.Button(label='Read source', url=source))
        self.add_item(BackHome())

    @discord.ui.button(label='Save', emoji='🔖', style=discord.ButtonStyle.primary)
    async def save(self, interaction, button):
        ok, _ = await self.run(interaction, self.store.bookmark, interaction.user.id, self.item_id)
        if ok:
            await interaction.response.send_message('Saved! Find it in My Saved.', ephemeral=True,
                                                    allowed_mentions=MENTIONS)


class EventView(GuardedView):
    def __init__(self, store, guild_id, owner, event_id):
        super().__init__(store, guild_id, owner)
        self.event_id = event_id
        self.add_item(BackHome())

    @discord.ui.button(label='Join', style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        ok, result = await self.run(interaction, self.store.join, self.event_id, interaction.user.id,
                                    interaction.channel_id, int(time.time()))
        if ok:
            message = 'You are already registered.' if result == 'Already registered.' else 'You are in!'
            await interaction.response.send_message(message, ephemeral=True, allowed_mentions=MENTIONS)

    @discord.ui.button(label='Leave', style=discord.ButtonStyle.secondary)
    async def leave(self, interaction, button):
        ok, _ = await self.run(interaction, self.store.leave, self.event_id, interaction.user.id)
        if ok:
            await interaction.response.send_message('Your registration is cancelled if you joined.',
                                                    ephemeral=True, allowed_mentions=MENTIONS)
