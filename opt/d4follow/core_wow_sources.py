# -*- coding: utf-8 -*-
"""WoW Forever public SELL offers and stock-backed 15%-40% pricing.

No demand/buy-order endpoint is used. Public published offers are availability
evidence, not an executed purchase. Only this round's source observations count.
"""
import concurrent.futures
import datetime as dt
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json
import math
import time
import urllib.request

BASE = 'https://www.bijiaqi.com'
REGIONS = {10109: '美服', 10110: '欧服', 10111: '亚服', 10116: '韩服'}
VERSION = 'wow-dual-stock-v3-20261108'


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0',
                 'Accept': 'application/json', 'Referer': BASE + '/categories/gold/1'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def server_key(region, name):
    low = name.lower().replace('-', ' ')
    typ = ('RP_PVP' if 'roleplay pvp' in low else 'RP' if 'roleplay' in low
           else 'NORMAL' if 'normal' in low else 'PVP' if 'pvp' in low else None)
    faction = 'A' if '联盟' in name else 'H' if '部落' in name else None
    return (region, typ, faction) if typ and faction else None


def parse_offers(rows, game_id, region, expected_key):
    result, seen = [], set()
    for row in sorted(rows, key=lambda x: number(x.get('price')) or float('inf')):
        if not isinstance(row, dict):
            raise ValueError('malformed sell row')
        if server_key(region, row.get('attrNameIndexes') or '') != expected_key:
            raise ValueError('sell realm/faction mismatch')
        if ('无限' not in (row.get('gameName') or '') or
                region not in (row.get('gameName') or '')):
            raise ValueError('sell game/region mismatch')
        if row.get('unit') != 'G':
            raise ValueError('unexpected sell unit')
        merchant = row.get('merchant') or {}
        # Never coerce "false" or missing online state to True.
        if merchant.get('online') is not True:
            continue
        price, stock, minimum = (number(row.get(x)) for x in
                                  ('price', 'effectiveQuantity', 'warnQuantity'))
        if price is None or stock is None or minimum is None:
            raise ValueError('missing sell price/stock/minimum')
        if price <= 0 or stock <= 0 or minimum <= 0 or stock < minimum:
            continue
        seller = str(merchant.get('userId') or '')
        if not seller:
            raise ValueError('missing seller identity')
        # Repeated listings from one seller may represent shared inventory.
        # Keep one cheapest quote rather than adding their stock together.
        if seller in seen:
            continue
        seen.add(seller)
        result.append({'unit_rmb': price, 'stock': stock, 'min_qty': minimum,
                       'seller_id': seller, 'offer_id': str(row.get('id') or ''),
                       'online': True, 'title': row.get('title') or ''})
    return sorted(result, key=lambda x: x['unit_rmb'])


def bjq_crawl(log=print):
    pages = {}
    for game_id, region in REGIONS.items():
        expected = {(region, t, f) for t in ('NORMAL', 'PVP', 'RP', 'RP_PVP')
                    for f in ('A', 'H')}
        try:
            tree = post('/api/v1/any/shop/home/servers', {'gameId': game_id})
            if not isinstance(tree, list) or not tree:
                raise ValueError('invalid server directory')
            def leaves(nodes, parent=()):
                for node in nodes:
                    path = parent + (node,)
                    if node.get('children'):
                        yield from leaves(node['children'], path)
                    else:
                        yield path
            found = set()
            for path in leaves(tree):
                leaf = path[-1]
                key = server_key(region, leaf.get('name') or '')
                if key not in expected:
                    continue
                if key in found:
                    raise ValueError('duplicate realm mapping')
                found.add(key)
                index = '-'.join(str(n['id']) for n in path if n.get('type') != 'game')
                url = BASE + '/categories/gold/1?game=%s&category=1&server=%s' % (game_id, index)
                started = time.time()
                try:
                    body = {'page': 1, 'limit': 100, 'categoryId': 1, 'gameId': game_id,
                            'attrIdIndexes': index, 'order': 'price,asc', 'attributeFilters': []}
                    data = post('/api/shop/commodity/listShopCommodity', body)
                    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
                        raise ValueError('invalid sell response')
                    total = data.get('total')
                    if not isinstance(total, int) or total < 0 or total > 1000:
                        raise ValueError('invalid sell total')
                    rows = list(data['list'])
                    for page in range(2, (total + 99) // 100 + 1):
                        body['page'] = page
                        extra = post('/api/shop/commodity/listShopCommodity', body)
                        if extra.get('total') != total or not isinstance(extra.get('list'), list):
                            raise ValueError('changing sell pagination')
                        rows.extend(extra['list'])
                    if len(rows) != total:
                        raise ValueError('incomplete sell list')
                    offers = parse_offers(rows, game_id, region, key)
                    pages[key] = {'label': region + '/' + leaf['name'], 'href': url,
                                  'items': offers, 'error': None, 'source': 'bijiaqi_public_sell',
                                  'captured_at': time.time(), 'started_at': started,
                                  'raw_count': total}
                    log('[比价器·出货] %s %s/%s 总%d 在线可买%d条' % (*key, total, len(offers)))
                except Exception as error:
                    pages[key] = {'items': [], 'error': repr(error), 'href': url,
                                  'source': 'bijiaqi_public_sell', 'captured_at': time.time()}
                    log('[比价器·出货] %s 采集失败 %r' % (key, error))
                time.sleep(.25)
            if found != expected:
                raise ValueError('missing realm mapping %s' % (expected - found))
        except Exception as error:
            for key in expected:
                if key not in pages:
                    pages[key] = {'items': [], 'error': repr(error), 'source': 'bijiaqi_public_sell',
                                  'captured_at': time.time()}
            log('[比价器] %s 目录异常 %r' % (region, error))
    return pages


def collect_pair(dd_crawl, log=print):
    """Start both sources together; one source failure never erases the other."""
    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {'DD373': pool.submit(dd_crawl, log=log),
                '比价器': pool.submit(bjq_crawl, log=log)}
        result = {}
        for source, job in jobs.items():
            try:
                result[source] = job.result()
            except Exception as error:
                result[source] = {}
                log('[双源] %s 整体失败 %r' % (source, error))
    return result['DD373'], result['比价器'], started


def source_cost(page, source, parameters, now=None):
    minimum_stock = float(parameters.get('低价最小库存金', 20))
    target = float(parameters.get('成本采样金', 21))
    if target <= minimum_stock:
        raise ValueError('cost sample must exceed inventory threshold')
    if not page or page.get('error'):
        return None
    captured = page.get('captured_at')
    if captured is not None and (not math.isfinite(captured) or
            (now or time.time()) - captured > float(parameters.get('报价最长时效秒', 1200)) or
            captured > (now or time.time()) + 5):
        return None
    valid = []
    for offer in page.get('items') or []:
        price, stock, lot_min = (number(offer.get(x)) for x in ('unit_rmb', 'stock', 'min_qty'))
        if (price is None or stock is None or lot_min is None or price <= 0 or
                stock <= 0 or lot_min <= 0 or stock < lot_min):
            continue
        valid.append(offer)
    valid.sort(key=lambda x: x['unit_rmb'])
    # A cheap 20G quote cannot borrow the stock of a dearer quote to pass >20G.
    # Pick the lowest PRICE LEVEL whose own independently listed stock qualifies.
    levels = {}
    for offer in valid:
        levels.setdefault(Decimal(str(offer['unit_rmb'])), []).append(offer)
    qualified = [offers for _, offers in sorted(levels.items())
                 if sum(x['stock'] for x in offers) > minimum_stock]
    if not qualified:
        return None
    valid = qualified[0]
    available = sum(x['stock'] for x in valid)
    amount, cost, legs = 0., 0., []
    for offer in valid:
        if amount >= target:
            break
        take = min(offer['stock'], max(offer['min_qty'], target - amount))
        if offer.get('step_qty'):
            take = min(offer['stock'], math.ceil(take / offer['step_qty'] - 1e-9) * offer['step_qty'])
        if take < offer['min_qty']:
            continue
        amount += take
        cost += take * offer['unit_rmb']
        legs.append({'price': offer['unit_rmb'], 'gold': take,
                     'minimum': offer['min_qty'], 'stock': offer['stock'],
                     'offer_id': offer.get('offer_id'), 'seller_id': offer.get('seller_id')})
    if amount <= minimum_stock:
        return None
    return {'source': source, 'avg_rmb': cost / amount, 'gold_used': amount,
            'avail_gold': available, 'n_items': len(valid), 'n_used': len(legs),
            'url': page.get('href') or '', 'legs': legs, 'captured_at': captured}


def price_pair(dd_page, bjq_page, parameters, fx, iggm_usd=None):
    if not number(fx) or fx <= 0:
        raise ValueError('invalid FX')
    quotes = [q for q in (source_cost(dd_page, 'DD373', parameters),
                         source_cost(bjq_page, '比价器', parameters)) if q]
    if not quotes:
        return {'mode': '无已确认>20G货源·冻结', 'margin': None, 'avg_rmb': None,
                'cost_usd': None, 'iggm': iggm_usd, 'b2c': None, 'gold_used': 0.,
                'n_items': 0, 'n_used': 0, 'avail_gold': 0.,
                'note': '不跟IGGM，不把采集失败当无货，不写旧兜底价',
                'source_quotes': [], 'selected_source': None, 'rule': VERSION}
    chosen = min(quotes, key=lambda q: q['avg_rmb'])
    cost = Decimal(str(chosen['avg_rmb'])) / Decimal(str(fx))
    lo = Decimal(str(parameters.get('毛利率下限', .15)))
    hi = Decimal(str(parameters.get('毛利率上限', .40)))
    if not Decimal('0') <= lo <= hi < Decimal('1'):
        raise ValueError('invalid margin bounds')
    quantum = Decimal('.000001')
    floor = (cost / (1 - lo)).quantize(quantum, rounding=ROUND_CEILING)
    ceiling = (cost / (1 - hi)).quantize(quantum, rounding=ROUND_FLOOR)
    if floor > ceiling:
        raise ValueError('no price within margin bounds at write precision')
    if number(iggm_usd) and iggm_usd > 0:
        target = Decimal(str(iggm_usd)) * Decimal(str(parameters.get('IGGM锚定倍数', 1.03)))
        mode = ('15%毛利兜底·不跟IGGM' if target < floor else
                '%d%%毛利封顶·不跟IGGM' % round(float(hi)*100) if target > ceiling else '有货·IGGM×1.03')
    else:
        margin = Decimal(str(parameters.get('常规利润率', .30)))
        margin = max(lo, min(hi, margin))
        target = cost / (1 - margin)
        mode = '有货·成本定价(无有效IGGM)'
    price = min(ceiling, max(floor, target.quantize(quantum)))
    margin = 1 - cost / price
    return {'mode': mode, 'margin': float(margin), 'avg_rmb': chosen['avg_rmb'],
            'cost_usd': float(cost), 'iggm': iggm_usd, 'b2c': float(price),
            'gold_used': chosen['gold_used'], 'n_items': chosen['n_items'],
            'n_used': chosen['n_used'], 'avail_gold': chosen['avail_gold'],
            'note': '以本轮可买报价为成本；来源%s；同一价位库存严格>20G；未下单锁货' % chosen['source'],
            'selected_source': chosen['source'], 'source_quotes': quotes,
            'floor_usd': float(floor), 'ceiling_usd': float(ceiling), 'rule': VERSION}
