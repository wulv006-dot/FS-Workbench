"""Restricted read-only FC product quotes, using the existing AdminClient."""
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


GID, SITE = 1327, 266
AREAS = {21587: 'PlayStation 5', 21585: 'Xbox Series X|S', 21589: 'PC'}
# These categories have been matched against public USD prices.
CATEGORIES = {
    'packs': ((9629, '', 'https://www.mmoexp.com/Fc-27/Packs/In-game-packs.html'),),
    'sbc': ((9625, '', 'https://www.mmoexp.com/Fc-27/Sbc.html'),),
    'evolutions': ((9825, '', 'https://www.mmoexp.com/Fc-27/Evolutions.html'),),
    'gallery': ((10211, 'Your Coins', 'https://www.mmoexp.com/Fc-27/Boosting/Gallery-your-coins.html'),
                (10063, 'Coins Provided', 'https://www.mmoexp.com/Fc-27/Boosting/Gallery-grade-2.html')),
}
COIN_TIERS = (100, 500, 1000, 2000, 5000)
COIN_MID, COIN_CID = 41217957, 9623
COIN_URL = 'https://www.mmoexp.com/Fc-27/Coins.html'
BOOSTING = {
    9711: ('Champions Finals', 'https://www.mmoexp.com/Fc-27/Boosting/Champions-finals.html'),
    9963: ('Unlock Champions Finals', 'https://www.mmoexp.com/Fc-27/Boosting/Unlock-champions-finals.html'),
    10445: ('Season 2', 'https://www.mmoexp.com/Fc-27/Boosting.html'),
    10265: ('Ultimate Gauntlet', 'https://www.mmoexp.com/Fc-27/Boosting.html'),
    9999: ('Unlock Transfer Market', 'https://www.mmoexp.com/Fc-27/Boosting.html'),
}


def _integer(value):
    if isinstance(value, bool):
        raise ValueError('invalid identifier')
    text = str(value)
    if not text.isascii() or not text.isdecimal() or len(text) > 12 or int(text) <= 0:
        raise ValueError('invalid identifier')
    return int(text)


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('invalid price') from None
    if not result.is_finite() or result <= 0:
        raise ValueError('invalid price')
    return result


def _equals(value, expected):
    if isinstance(value, bool):
        return False
    try:
        return Decimal(str(value)) == expected
    except InvalidOperation:
        return False


def _product(value):
    if not isinstance(value, str) or value.count(':') != 1:
        raise ValueError('invalid product')
    kind, mid = value.split(':')
    if kind not in CATEGORIES and kind not in ('coins', 'boosting'):
        raise ValueError('unsupported category')
    return kind, _integer(mid)


class QuoteCatalog:
    def __init__(self, client):
        self.client = client

    def _leaves(self, kind):
        def find(nodes, parent):
            for node in nodes:
                children = node.get('children') or node.get('child') or []
                if str(node.get('id')) == str(parent):
                    return collect(children)
                found = find(children, parent)
                if found:
                    return found
            return set()

        def collect(nodes):
            result = set()
            for node in nodes:
                children = node.get('children') or node.get('child') or []
                if children:
                    result.update(collect(children))
                else:
                    result.add(_integer(node.get('id')))
            return result

        tree = self.client.category_tree(gid=GID)
        result = {}
        for parent, label, url in CATEGORIES[kind]:
            leaves = find(tree, parent)
            if not leaves:
                raise ValueError('category unavailable')
            for leaf in leaves:
                if leaf in result:
                    raise ValueError('ambiguous category')
                result[leaf] = (label, url)
        return result

    def _rows(self, **filters):
        rows = []
        seen = set()
        total = None
        for page in range(1, 201):
            result = self.client.list_goods(gid=GID, site_id=SITE, page=page, limit=200, **filters)
            if total is None:
                total = result.total
            if result.total != total:
                raise ValueError('product list changed')
            for row in result.rows:
                item_id = _integer(row['id'])
                if item_id in seen:
                    raise ValueError('duplicate product')
                seen.add(item_id)
            rows.extend(result.rows)
            if len(rows) == total:
                return rows
            if not result.rows or len(rows) > total:
                raise ValueError('incomplete product list')
        raise ValueError('product list too large')

    @staticmethod
    def _valid(row, leaves, kind, mid=None):
        try:
            if (_integer(row['gid']) != GID or _integer(row['site_id']) != SITE
                    or _integer(row['cid']) not in leaves or _integer(row['aid']) not in AREAS
                    or not _equals(row['status'], 1) or not _equals(row.get('is_put', 1), 1)
                    or not _equals(row['sku_switch'], 0) or not _equals(row['attr_switch'], 0)
                    or not _equals(row['num'], 1) or (mid is not None and _integer(row['mid']) != mid)
                    or not str(row['title']).strip()):
                return False
            _integer(row['id'])
            _integer(row['mid'])
            original, sale, discount = (_decimal(row['unit_price']), _decimal(row['price']),
                                        _decimal(row['discount']))
            return (original < 9999 and discount <= 100 and (kind == 'packs' or discount == 100)
                    and abs(sale - original * discount / 100) <= Decimal('0.01'))
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
            return False

    def _model(self, mid, leaves):
        payload = self.client.get_model(mid)
        row = payload.get('data', {}).get('row', {})
        try:
            valid = (_integer(row['id']) == mid and _integer(row['gid']) == GID
                     and _integer(row['cid']) in leaves and _equals(row['status'], 1)
                     and _equals(row.get('is_put', 1), 1))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError('model unavailable')

    def _require_leaf(self, cid):
        def find(nodes):
            for node in nodes:
                children = node.get('children') or node.get('child') or []
                if str(node.get('id')) == str(cid):
                    return not children
                if find(children):
                    return True
            return False
        if not find(self.client.category_tree(gid=GID)):
            raise ValueError('category unavailable')

    def _coins(self, quantity, aid):
        if quantity not in COIN_TIERS or aid not in AREAS:
            raise ValueError('unsupported option')
        self._require_leaf(COIN_CID)
        rows = self._rows(cid=COIN_CID)
        matches = [r for r in rows if str(r.get('aid')) == str(aid)
                   and str(r.get('gid')) == str(GID) and str(r.get('site_id')) == str(SITE)
                   and str(r.get('cid')) == str(COIN_CID) and _equals(r.get('status'), 1)]
        if len(matches) != 1:
            raise ValueError('coin platform unavailable or ambiguous')
        row = matches[0]
        self._model(COIN_MID, {COIN_CID})
        detail = self.client.get_goods(_integer(row['id']))
        if (_integer(detail['id']) != _integer(row['id']) or _integer(detail['mid']) != COIN_MID
                or _integer(detail['gid']) != GID or _integer(detail['cid']) != COIN_CID
                or _integer(detail['site_id']) != SITE or _integer(detail['aid']) != aid
                or not _equals(detail['status'], 1) or not _equals(detail.get('is_put', 1), 1)
                or not _equals(detail['sku_switch'], 1) or not _equals(detail['attr_switch'], 1)
                or not _equals(detail['num'], 1) or detail.get('unit') != 'K'):
            raise ValueError('coin product unavailable')
        more = detail.get('more')
        if not isinstance(more, dict):
            raise ValueError('coin tiers unavailable')
        arrays = [more.get(k) for k in ('gold', 'price', 'give', 'discount')]
        if any(not isinstance(a, list) for a in arrays) or not 1 <= len(arrays[0]) <= 100:
            raise ValueError('invalid coin tiers')
        if any(len(a) != len(arrays[0]) for a in arrays):
            raise ValueError('incomplete coin tiers')
        seen = set()
        result = None
        for gold, price, give, discount in zip(*arrays):
            gold = _integer(gold)
            if gold in seen or not _equals(discount, 100):
                raise ValueError('ambiguous coin tiers')
            seen.add(gold)
            value = _decimal(price)
            if value >= 9999 or isinstance(give, bool):
                raise ValueError('invalid coin tier')
            try:
                bonus = Decimal(str(give))
            except InvalidOperation:
                raise ValueError('invalid bonus') from None
            if not bonus.is_finite() or bonus < 0 or bonus != bonus.to_integral_value():
                raise ValueError('invalid bonus')
            if gold == quantity:
                result = (value, int(bonus))
        if result is None:
            raise ValueError('coin tier unavailable')
        return result

    def _boost(self, cid, aid):
        if cid not in BOOSTING or aid not in AREAS:
            raise ValueError('unsupported option')
        self._require_leaf(cid)
        candidates = []
        for row in self._rows(cid=cid):
            if (str(row.get('gid')) != str(GID) or str(row.get('site_id')) != str(SITE)
                    or str(row.get('cid')) != str(cid) or str(row.get('aid')) != str(aid)
                    or not _equals(row.get('status'), 1) or not _equals(row.get('is_put', 1), 1)):
                continue
            if (not _equals(row.get('sku_switch'), 0) or not _equals(row.get('attr_switch'), 0)
                    or not _equals(row.get('num'), 1)):
                raise ValueError('complex boosting price')
            if not _equals(row.get('discount'), 100):
                raise ValueError('unverified boosting discount')
            if self._valid(row, {cid}, 'boosting'):
                self._model(_integer(row['mid']), {cid})
                candidates.append(row)
        if not candidates:
            raise ValueError('boosting unavailable')
        selected = min(candidates, key=lambda r: _decimal(r['price']))
        detail = self.client.get_goods(_integer(selected['id']))
        if (not self._valid(detail, {cid}, 'boosting', _integer(selected['mid']))
                or _integer(detail['id']) != _integer(selected['id'])
                or _integer(detail['aid']) != aid
                or _decimal(detail['price']) != _decimal(selected['price'])):
            raise ValueError('boosting price changed')
        return _decimal(detail['price'])

    def catalog(self, kind):
        if kind == 'coins':
            return [{'id': 'coins:' + str(q), 'title': str(q) + 'K'} for q in COIN_TIERS]
        if kind == 'boosting':
            return [{'id': 'boosting:' + str(cid), 'title': item[0]} for cid, item in BOOSTING.items()]
        if kind not in CATEGORIES:
            return []
        leaves = self._leaves(kind)
        products = {}
        for parent, _, _ in CATEGORIES[kind]:
            for row in self._rows(cid=parent):
                if self._valid(row, leaves, kind):
                    label = leaves[int(row['cid'])][0]
                    title = str(row['title']).strip()
                    products[str(row['mid'])] = title + (' — ' + label if label else '')
        return [{'id': kind + ':' + mid, 'title': title}
                for mid, title in sorted(products.items(), key=lambda item: item[1].casefold())]

    def options(self, product_id):
        kind, mid = _product(product_id)
        if kind in ('coins', 'boosting'):
            options = []
            for aid, label in AREAS.items():
                try:
                    (self._coins if kind == 'coins' else self._boost)(mid, aid)
                    options.append({'id': str(aid), 'label': label})
                except ValueError:
                    continue
            return options
        leaves = self._leaves(kind)
        self._model(mid, leaves)
        rows = self._rows(mid=mid)
        return [{'id': str(row['id']), 'label': AREAS[int(row['aid'])]}
                for row in rows if self._valid(row, leaves, kind, mid)]

    def quote(self, product_id, option_id):
        kind, mid = _product(product_id)
        goods_id = _integer(option_id)
        if kind in ('coins', 'boosting'):
            if kind == 'coins':
                value, bonus = self._coins(mid, goods_id)
                title = '{}K + {}K bonus = {}K total'.format(mid, bonus, mid + bonus)
                url, basis = COIN_URL, 'sale'
            else:
                value = self._boost(mid, goods_id)
                title, url = BOOSTING[mid]
                basis = 'from'
            return {'title': title, 'option_label': AREAS[goods_id],
                    'amount': str(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                    'currency': 'USD', 'price_basis': basis, 'url': url, 'queried_at': int(time.time())}
        leaves = self._leaves(kind)
        self._model(mid, leaves)
        row = self.client.get_goods(goods_id)
        if not self._valid(row, leaves, kind, mid) or _integer(row['id']) != goods_id:
            raise ValueError('product unavailable')
        amount = _decimal(row['price']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        label, url = leaves[int(row['cid'])]
        title = str(row['title']).strip() + (' — ' + label if label else '')
        return {'title': title, 'option_label': AREAS[int(row['aid'])],
                'amount': str(amount), 'currency': 'USD', 'price_basis': 'sale',
                'url': url, 'queried_at': int(time.time())}

