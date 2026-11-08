"""Player configuration and the read-only adapter shared by the bot and FS."""
import json
from pathlib import Path

from player_catalog import PlayerCatalog, _card
from quote_catalog import AREAS, GID

from player_config import validate_player_config


class ProductProvider:
    def __init__(self, catalog, client, config_path, tag_client=None):
        self.base_catalog, self.client = catalog, client
        self.config_path, self.tag_client = Path(config_path), tag_client

    def players(self, require_enabled=True):
        cfg = validate_player_config(json.loads(self.config_path.read_text(encoding='utf-8'))['player_panel'])
        if require_enabled and not cfg['enabled']:
            raise ValueError('Players are disabled')
        return PlayerCatalog(self.client, cfg['verified_prices'], self.tag_client,
                             cfg['allowed_tag_ids']), cfg

    def catalog(self, kind):
        if kind != 'players':
            return self.base_catalog.catalog(kind)
        return self.player_featured(1)['items']

    def _player_quote_targets(self, product_id):
        player, config = self.players()
        card = player.featured([int(product_id.removeprefix('players:'))])[0]
        if card['card_type'].casefold() != 'signature':
            return player, [product_id]
        # Resolve the ordinary product from the real Admin directory, never from an EasySBC ID.
        ordinary_title = card['title'].rsplit('/', 1)[0]
        matches, seen, expected = {}, set(), None
        try:
            for page in range(1, 11):
                result = self.client.list_models(gid=GID, cid=9627, title_like=card['name'], page=page, limit=25)
                if type(result.total) is not int or result.total < 0 or len(result.rows) > 25:
                    raise ValueError('Invalid model listing')
                if expected is None:
                    expected = result.total
                if expected != result.total:
                    raise ValueError('Changed model listing')
                for row in result.rows:
                    mid = int(row['id'])
                    if mid in seen:
                        raise ValueError('Repeated model listing')
                    seen.add(mid)
                    if row.get('title') == ordinary_title:
                        standard = _card(row)
                        matches[standard['id']] = standard
                if len(seen) == expected:
                    break
                if not result.rows or len(seen) > expected:
                    raise ValueError('Incomplete model listing')
            if len(seen) != expected or len(matches) != 1:
                return player, [product_id]
            ordinary = next(iter(matches))
            return player, [ordinary, product_id]
        except (ValueError, KeyError, TypeError):
            pass
        return player, [product_id]

    def options(self, product_id):
        if not product_id.startswith('players:'):
            return self.base_catalog.options(product_id)
        player, targets = self._player_quote_targets(product_id)
        result, labels = [], set()
        for target in targets:
            try:
                options = player.options(target)
            except ValueError:
                if target == product_id and not result:
                    raise
                continue
            for option in options:
                if option['label'] not in labels:
                    labels.add(option['label'])
                    result.append(option)
        return result

    def quote(self, product_id, option_id):
        if not product_id.startswith('players:'):
            return self.base_catalog.quote(product_id, option_id)
        player, targets = self._player_quote_targets(product_id)
        if len(targets) == 1:
            return player.quote(product_id, option_id)
        seen_platforms = set()
        for target in targets:
            try:
                options = player.options(target)
            except ValueError:
                if target == product_id:
                    raise
                continue
            for option in options:
                if option['label'] not in seen_platforms and option['id'] == str(option_id):
                    quote = player.quote(target, option_id)
                    quote.update(requested_product_id=product_id, quoted_product_id=target)
                    return quote
                seen_platforms.add(option['label'])
        raise ValueError('Selected player option is no longer available')

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
        if not self.options(card['id']):
            raise ValueError('Player has no valid available price')
        return card

    def _management_card(self, row, config):
        card = _card(row, include_unavailable=True)
        mid = card['id'].split(':')[1]
        card['model_id'] = int(mid)
        card['verified_platforms'] = [AREAS[aid] for aid in config['verified_prices'].get(mid, [])]
        card['goods_availability'] = 'not_checked'
        card['easysbc_mapping'] = 'configured' if any(m['model_id'] == int(mid) for m in config.get('easysbc', {}).get('mappings', [])) else 'missing'
        return card

    def player_manage_search(self, query, page):
        player, config = self.players(require_enabled=False)
        if (not isinstance(query, str) or not 1 <= len(query.strip()) <= 80
                or any(ord(c) < 32 or c in '%_\\' for c in query)
                or type(page) is not int or not 1 <= page <= 10):
            raise ValueError('Invalid player search')
        query = query.strip()
        if query.isascii() and query.isdigit():
            if not 1 <= int(query) < 10**12 or page != 1:
                raise ValueError('Invalid model ID')
            row = self.client.get_model(int(query))['data']['row']
            if int(row['id']) != int(query):
                raise ValueError('Model mismatch')
            return {'items': [self._management_card(row, config)], 'page': 1, 'has_more': False}
        if len(query) < 2:
            raise ValueError('Name must contain at least two characters')
        result = self.client.list_models(gid=GID, cid=9627, title_like=query, page=page, limit=25)
        if type(result.total) is not int or result.total < 0 or len(result.rows) > 25:
            raise ValueError('Invalid player response')
        items, seen = [], set()
        for row in result.rows:
            try:
                card = self._management_card(row, config)
                if query.casefold() in card['title'].casefold() and card['id'] not in seen:
                    items.append(card)
                    seen.add(card['id'])
            except (ValueError, TypeError, KeyError):
                continue
        return {'items': items, 'page': page, 'has_more': page < 10 and page * 25 < result.total}

    def player_manage_selection(self):
        _, config = self.players(require_enabled=False)
        items = []
        for mid in config['featured_model_ids']:
            try:
                row = self.client.get_model(mid)['data']['row']
                if int(row['id']) != mid:
                    raise ValueError('Model mismatch')
                items.append(self._management_card(row, config))
            except Exception:
                items.append({'model_id': mid, 'title': '无法读取模型 #' + str(mid), 'model_available': False,
                              'verified_platforms': [], 'goods_availability': 'unknown', 'easysbc_mapping': 'unknown'})
        return items

    def player_manage_tags(self):
        return self.players(require_enabled=False)[0].tags(include_all=True)

    def player_manage_inspect(self, model_id):
        if not isinstance(model_id, str) or not model_id.isascii() or not model_id.isdigit() or not 1 <= int(model_id) < 10**12:
            raise ValueError('Invalid model ID')
        return self.players(require_enabled=False)[0].inspect_goods('players:' + model_id)

    def player_manage_match(self, model_id):
        from player_matching import resolve
        if not isinstance(model_id, str) or not model_id.isascii() or not model_id.isdigit() or not 1 <= int(model_id) < 10**12:
            raise ValueError('Invalid model ID')
        player, config = self.players(require_enabled=False)
        card = player.featured([int(model_id)])[0]
        card['model_id'] = int(model_id)
        existing = next((item for item in config.get('easysbc', {}).get('mappings', [])
                         if item['model_id'] == int(model_id)), None)
        return resolve(card, existing_mapping=existing)
