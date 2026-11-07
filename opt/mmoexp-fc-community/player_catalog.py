"""Bounded, read-only Players lookup; price verification is opt-in per model/platform."""
import time
from decimal import Decimal, ROUND_HALF_UP

from quote_catalog import AREAS, GID, SITE, QuoteCatalog, _decimal, _equals, _integer


CID = 9627
URL = 'https://www.mmoexp.com/Fc-27/Players.html'


def _product(value):
    if not isinstance(value, str) or not value.startswith('players:'):
        raise ValueError('invalid player')
    return _integer(value[8:])


def _card(row):
    try:
        mid = _integer(row['id'])
        if (_integer(row['gid']) != GID or _integer(row['cid']) != CID
                or not _equals(row['status'], 1) or not _equals(row.get('is_put', 1), 1)):
            raise ValueError('player unavailable')
        title = row['title']
        if not isinstance(title, str) or len(title) > 200 or any(ord(c) < 32 for c in title):
            raise ValueError('invalid title')
        parts = [part.strip() for part in title.split('/')]
        if len(parts) not in (4, 5) or any(not p for p in parts):
            raise ValueError('invalid card identity')
        rating = _integer(parts[1])
        if rating > 99:
            raise ValueError('invalid rating')
        more = row.get('more') or {}
        extensions = more.get('extend') or []
        ids = [v.get('value') for v in extensions if isinstance(v, dict) and v.get('key') == 'player_id']
        if len(ids) > 1:
            raise ValueError('ambiguous player id')
        futbin = str(_integer(ids[0])) if ids else None
        return {'id': 'players:' + str(mid), 'title': title, 'name': parts[0], 'rating': rating,
                'position': parts[2], 'card_version': parts[3],
                'card_type': parts[4] if len(parts) == 5 else '', 'futbin_player_id': futbin,
                'recommended': _equals(row.get('is_rec'), 1)}
    except (KeyError, TypeError, AttributeError):
        raise ValueError('invalid player') from None


class PlayerCatalog:
    def __init__(self, client, verified_prices=None, tag_client=None, allowed_tag_ids=()):
        self.client = client
        self.catalog = QuoteCatalog(client)
        self.tag_client = tag_client
        if not isinstance(allowed_tag_ids, (list, tuple)) or len(allowed_tag_ids) > 25:
            raise ValueError('invalid allowed tags')
        self.allowed_tag_ids = {_integer(value) for value in allowed_tag_ids}
        self.verified_prices = {}
        for mid, aids in (verified_prices or {}).items():
            mid = _integer(mid)
            self.verified_prices[mid] = {_integer(aid) for aid in aids}
            if not self.verified_prices[mid] <= set(AREAS):
                raise ValueError('invalid verified platform')

    def _model(self, mid):
        self.catalog._require_leaf(CID)
        payload = self.client.get_model(mid)
        try:
            row = payload['data']['row']
            card = _card(row)
        except (KeyError, TypeError):
            raise ValueError('player unavailable') from None
        if _integer(row['id']) != mid:
            raise ValueError('player mismatch')
        return card

    def search(self, query, limit=25, page=1):
        if (not isinstance(query, str) or not 2 <= len(query.strip()) <= 80
                or any(ord(c) < 32 or c in '%_\\' for c in query)):
            raise ValueError('invalid search')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise ValueError('invalid limit')
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 10:
            raise ValueError('invalid page')
        query = query.strip()
        result = self.client.list_models(gid=GID, cid=CID, title_like=query, page=page, limit=limit)
        if len(result.rows) > limit or not isinstance(result.total, int) or result.total < 0:
            raise ValueError('invalid search result')
        items, seen = [], set()
        for row in result.rows:
            try:
                card = _card(row)
                if query.casefold() not in card['title'].casefold():
                    continue
                if card['id'] in seen:
                    raise ValueError('duplicate player')
                seen.add(card['id'])
                items.append(card)
            except (ValueError, TypeError):
                continue
        return {'items': items, 'page': page, 'has_more': page < 10 and page * limit < result.total}

    def featured(self, model_ids):
        if not isinstance(model_ids, (list, tuple)) or len(model_ids) > 25:
            raise ValueError('invalid featured players')
        ids = [_integer(value) for value in model_ids]
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate player')
        return [self._model(mid) for mid in ids]

    def tags(self):
        if self.tag_client is None or not self.allowed_tag_ids:
            return []
        result, seen = [], set()
        for row in self.tag_client.list_tags(gid=GID, cid=CID):
            try:
                tid = _integer(row['id'])
                categories = row['cate_id']
                categories = categories if isinstance(categories, (list, tuple)) else str(categories).split(',')
                name = row['name']
                if (tid not in self.allowed_tag_ids or tid in seen or _integer(row['gid']) != GID
                        or str(CID) not in [str(value).strip() for value in categories]
                        or not _equals(row['status'], 1) or not isinstance(name, str)
                        or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name)):
                    continue
                seen.add(tid)
                result.append({'id': str(tid), 'name': name.strip()})
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def recommended(self, limit=25, page=1):
        return self._filtered_page(limit, page, lambda row: _equals(row.get('is_rec'), 1))

    def browse_tag(self, tag_id, limit=25, page=1):
        tag_id = _integer(tag_id)
        if str(tag_id) not in {tag['id'] for tag in self.tags()}:
            raise ValueError('tag unavailable')
        def matches(row):
            tids = row.get('tid', row.get('tag_ids'))
            if isinstance(tids, str):
                tids = tids.replace('，', ',').split(',')
            return isinstance(tids, (list, tuple)) and tag_id in {_integer(v) for v in tids}
        return self._filtered_page(limit, page, matches)

    def _filtered_page(self, limit, page, matches):
        if type(limit) is not int or not 1 <= limit <= 25:
            raise ValueError('invalid limit')
        if type(page) is not int or not 1 <= page <= 200:
            raise ValueError('invalid page')
        result = self.client.list_models(gid=GID, cid=CID, page=page, limit=limit)
        if len(result.rows) > limit or type(result.total) is not int or result.total < 0:
            raise ValueError('invalid player result')
        items, seen = [], set()
        for row in result.rows:
            try:
                if not matches(row):
                    continue
                card = _card(row)
                if card['id'] in seen:
                    raise ValueError('duplicate player')
                seen.add(card['id'])
                items.append(card)
            except (ValueError, TypeError, AttributeError):
                continue
        return {'items': items, 'page': page, 'has_more': page < 200 and page * limit < result.total}

    def _valid_goods(self, row, mid, card):
        try:
            more = row['more']
            aid = _integer(row['aid'])
            if (aid not in self.verified_prices.get(mid, set()) or _integer(row['mid']) != mid
                    or _integer(row['gid']) != GID or _integer(row['cid']) != CID
                    or _integer(row['site_id']) != SITE or not _equals(row['status'], 1)
                    or not _equals(row.get('is_put', 1), 1) or not _equals(row['sku_switch'], 0)
                    or not _equals(row['attr_switch'], 1) or not _equals(row['num'], 1)
                    or row['title'] != card['title'] or not isinstance(more, dict)
                    or more.get('saleprop') != [] or more.get('skuTableSet') != []):
                return False
            _integer(row['id'])
            # auto_off=0 / total=0 is a live unlimited-stock contract, not sold out.
            auto_off = row['auto_off']
            stock = Decimal(str(row['total']))
            if (not (_equals(auto_off, 0) or _equals(auto_off, 1))
                    or not stock.is_finite() or stock < 0
                    or (_equals(auto_off, 1) and stock < _decimal(row['num']))):
                return False
            price, unit, discount = (_decimal(row['price']), _decimal(row['unit_price']),
                                     _decimal(row['discount']))
            return price < 9999 and discount <= 100 and abs(price - unit * discount / 100) <= Decimal('0.01')
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return False

    def options(self, product_id):
        mid = _product(product_id)
        card = self._model(mid)
        if not self.verified_prices.get(mid):
            return []
        result = self.client.list_goods(gid=GID, mid=mid, site_id=SITE, page=1, limit=25)
        if result.total != len(result.rows) or len(result.rows) > 25:
            raise ValueError('incomplete player goods')
        options, seen = [], set()
        for row in result.rows:
            aid = _integer(row['aid'])
            if aid not in self.verified_prices[mid]:
                continue
            if aid in seen:
                raise ValueError('ambiguous player platform')
            seen.add(aid)
            detail = self.client.get_goods(_integer(row['id']))
            if self._valid_goods(detail, mid, card) and _integer(detail['id']) == _integer(row['id']) and _integer(detail['aid']) == aid:
                options.append({'id': str(detail['id']), 'label': AREAS[aid]})
        return options

    def quote(self, product_id, option_id):
        mid, goods_id = _product(product_id), _integer(option_id)
        card = self._model(mid)
        row = self.client.get_goods(goods_id)
        if not self._valid_goods(row, mid, card) or _integer(row['id']) != goods_id:
            raise ValueError('player quote unavailable')
        amount = _decimal(row['price']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return {'title': card['title'], 'option_label': AREAS[_integer(row['aid'])], 'amount': str(amount),
                'currency': 'USD', 'price_basis': 'sale', 'url': URL, 'queried_at': int(time.time())}
