"""Private player search and quotations using the existing bounded price service."""
import discord

from quote_panel import (GuardedView, QuoteView, MENTIONS, call_provider, entries,
                         panel_embed, begin_query)


class PlayerHomeView(GuardedView):
    def __init__(self, provider, allowed_routes, presentation=None):
        super().__init__(provider, kind='players', allowed_routes=allowed_routes, presentation=presentation)

    @discord.ui.button(label='Search player', emoji='🔎', style=discord.ButtonStyle.primary,
                       custom_id='fc:players:search')
    async def search(self, interaction, button):
        await interaction.response.send_modal(PlayerSearch(self))

    @discord.ui.button(label='Featured players', emoji='⭐', custom_id='fc:players:featured')
    async def featured(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await load_players(interaction, self, 'featured', '', 1)

    @discord.ui.button(label='Browse tags', emoji='🏷️', custom_id='fc:players:tags')
    async def tags(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            tags = await call_provider(self.provider.player_tags)
            view = GuardedView(self.provider, interaction.user.id, 'players', self.allowed_routes, self.presentation)
            view.add_item(PlayerTagSelect(tags))
            await interaction.edit_original_response(content='Choose a player tag.' if tags else 'No tags are available yet.',
                                                     view=view, allowed_mentions=MENTIONS)
        except Exception:
            await interaction.edit_original_response(content='Player tags are unavailable. Try Search player.',
                                                     allowed_mentions=MENTIONS)


class PlayerSearch(discord.ui.Modal, title='Find a player'):
    name = discord.ui.TextInput(label='Player name', placeholder='Haaland, Mbappé…', min_length=2, max_length=80)

    def __init__(self, source):
        super().__init__(timeout=180)
        self.source = source

    async def on_submit(self, interaction):
        if not await self.source.interaction_check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await load_players(interaction, self.source, 'search', self.name.value, 1)


class PlayerTagSelect(discord.ui.Select):
    def __init__(self, tags):
        self.tags = {str(t['id']): t['name'] for t in tags[:25]}
        super().__init__(placeholder='Choose a tag', disabled=not tags,
                         options=[discord.SelectOption(label=name[:100], value=tid) for tid, name in self.tags.items()]
                         or [discord.SelectOption(label='No tags available', value='none')])

    async def callback(self, interaction):
        if self.values[0] not in self.tags:
            return
        await interaction.response.defer()
        await load_players(interaction, self.view, 'tag', self.values[0], 1)


async def load_players(interaction, source, mode, query, page):
    if begin_query(interaction.user.id) is None:
        await interaction.edit_original_response(content='Please wait a few seconds, then try again.',
                                                 allowed_mentions=MENTIONS)
        return
    if isinstance(source, QuoteView):
        source.retire()
    try:
        if mode == 'search':
            result = await call_provider(source.provider.player_search, query, page)
        elif mode == 'tag':
            result = await call_provider(source.provider.player_tag, query, page)
        else:
            result = await call_provider(source.provider.player_featured, page)
        rows = entries(result['items'])
        has_more = result['has_more'] is True
        message = None if rows else ('No matches on this page. Try Next page.' if has_more else 'No players found. Try another name.')
    except Exception:
        rows, has_more, message = {}, False, 'Players are unavailable. Please try again.'
    panel = PlayerQuoteView(source.provider, interaction.user.id, 'players', rows,
                           allowed_routes=source.allowed_routes, presentation=source.presentation,
                           search_mode=mode, search_query=query, search_page=page, has_more=has_more)
    panel.interaction = interaction
    await interaction.edit_original_response(content=None, embed=panel_embed(panel, message), view=panel,
                                             allowed_mentions=MENTIONS)


class PlayerQuoteView(QuoteView):
    def __init__(self, *args, search_mode='featured', search_query='', search_page=1, has_more=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_mode, self.search_query = search_mode, search_query
        self.search_page, self.has_more = search_page, has_more
        self.add_item(SearchAgain())
        if search_page > 1:
            self.add_item(PlayerPage('Previous page', -1))
        if has_more:
            self.add_item(PlayerPage('Next page', 1))

    def copy(self, **changes):
        self.retire()
        values = dict(provider=self.provider, owner=self.owner, kind=self.kind, rows=self.rows,
                      page=self.page, product=self.product, platform=self.platform, quote=self.quote,
                      allowed_routes=self.allowed_routes, presentation=self.presentation,
                      search_mode=self.search_mode, search_query=self.search_query,
                      search_page=self.search_page, has_more=self.has_more)
        values.update(changes)
        return PlayerQuoteView(**values)


class SearchAgain(discord.ui.Button):
    def __init__(self):
        super().__init__(label='Search player', emoji='🔎', row=4)

    async def callback(self, interaction):
        await interaction.response.send_modal(PlayerSearch(self.view))


class PlayerPage(discord.ui.Button):
    def __init__(self, label, offset):
        super().__init__(label=label, row=4)
        self.offset = offset

    async def callback(self, interaction):
        await interaction.response.defer()
        await load_players(interaction, self.view, self.view.search_mode,
                           self.view.search_query, self.view.search_page + self.offset)


def player_card_embed(card, presentation=None):
    from quote_panel import category_embed
    embed = category_embed('players', presentation)
    embed.title = card['title']
    embed.description = '⚽ Choose your platform for a private live quote.'
    return embed


class PlayerCardView(GuardedView):
    def __init__(self, provider, model_id, allowed_routes, presentation=None):
        super().__init__(provider, kind='players', allowed_routes=allowed_routes, presentation=presentation)
        self.model_id = str(model_id)
        if not self.model_id.isascii() or not self.model_id.isdigit() or not 1 <= int(self.model_id) < 10**12:
            raise ValueError('Invalid player ID')
        button = discord.ui.Button(label='Get player price', emoji='💰', style=discord.ButtonStyle.primary,
                                   custom_id='fc:player:' + self.model_id)
        button.callback = self.open_player
        self.add_item(button)
        self.add_item(discord.ui.Button(label='Open MMOEXP', url='https://www.mmoexp.com/Fc-27/Players.html'))

    async def open_player(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if begin_query(interaction.user.id) is None:
            await interaction.edit_original_response(content='Please wait a few seconds.', allowed_mentions=MENTIONS)
            return
        try:
            card = await call_provider(self.provider.player_preview, self.model_id)
            panel = PlayerQuoteView(self.provider, interaction.user.id, 'players', entries([card]),
                                   product=card['id'], allowed_routes=self.allowed_routes, presentation=self.presentation)
            panel.interaction = interaction
            await interaction.edit_original_response(embed=panel_embed(panel), view=panel, allowed_mentions=MENTIONS)
        except Exception:
            await interaction.edit_original_response(content='This player is unavailable. Use Search player for alternatives.',
                                                     allowed_mentions=MENTIONS)
