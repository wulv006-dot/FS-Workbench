"""Player configuration and the read-only adapter shared by the bot and FS."""
import json
from pathlib import Path

from player_catalog import PlayerCatalog

from player_config import validate_player_config


class ProductProvider:
    def __init__(self, catalog, client, config_path, tag_client=None):
        self.base_catalog, self.client = catalog, client
        self.config_path, self.tag_client = Path(config_path), tag_client

    def players(self):
        cfg = validate_player_config(json.loads(self.config_path.read_text(encoding='utf-8'))['player_panel'])
        if not cfg['enabled']:
            raise ValueError('Players are disabled')
        return PlayerCatalog(self.client, cfg['verified_prices'], self.tag_client,
                             cfg['allowed_tag_ids']), cfg

    def catalog(self, kind):
        if kind != 'players':
            return self.base_catalog.catalog(kind)
        return self.player_featured(1)['items']

    def options(self, product_id):
        return (self.players()[0] if product_id.startswith('players:') else self.base_catalog).options(product_id)

    def quote(self, product_id, option_id):
        return (self.players()[0] if product_id.startswith('players:') else self.base_catalog).quote(product_id, option_id)

    def player_search(self, query, page):
        return self.players()[0].search(query, page=page)

    def player_tags(self):
        return self.players()[0].tags()

    def player_tag(self, tag_id, page):
        return self.players()[0].browse_tag(tag_id, page=page)

    def player_featured(self, page):
        if type(page) is not int or not 1 <= page <= 200:
            raise ValueError('Invalid player page')
        player, config = self.players()
        if config['featured_model_ids']:
            if page != 1:
                raise ValueError('Featured list has one page')
            return {'items': player.featured(config['featured_model_ids']), 'page': 1, 'has_more': False}
        return player.recommended(page=page)

    def player_preview(self, model_id):
        if not isinstance(model_id, str) or not model_id.isascii() or not model_id.isdigit() or not 1 <= int(model_id) < 10**12:
            raise ValueError('Invalid player ID')
        player, config = self.players()
        mid = int(model_id)
        card = player.featured([mid])[0]
        if (config['featured_model_ids'] and mid not in config['featured_model_ids']
                or not config['featured_model_ids'] and not card['recommended']):
            raise ValueError('Player is not featured')
        if not player.options(card['id']):
            raise ValueError('Player has no verified available price')
        return card
