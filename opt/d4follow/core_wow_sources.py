# -*- coding: utf-8 -*-
"""WoW Forever public SELL offers and stock-backed pricing.

No demand/buy-order endpoint is used. Public published offers are availability
evidence, not an executed purchase. Only this round's source observations count.

2026-11-12: 150G/50G inventory bands; 25/30/35% margins; compare final sale prices.
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
VERSION = 'wow-dual-stock-v5.4-20261112'


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
        price, stock, minimum = (number(row.get(x)) for x in
                                  ('price', 'effectiveQuantity', 'warnQuantity'))
        if price is None or stock is None or minimum is None:
            raise ValueError('missing sell price/stock/minimum')
        if price <= 0 or stock <= 0 or minimum <= 0 or stock < minimum:
            continue
        seller = str(merchant.get('userId') or '')
        if not seller:
            raise ValueError('missing seller identity')
        # De-duplicate identical offer IDs, retaining distinct supplier listings.
        # Each distinct published offer contributes its displayed inventory.
        if str(row.get('id') or '') in seen:
            continue
        seen.add(str(row.get('id') or ''))
        result.append({'unit_rmb': price, 'stock': stock, 'min_qty': minimum,
                       'seller_id': seller, 'offer_id': str(row.get('id') or ''),
                       'online': merchant.get('online'), 'title': row.get('title') or ''})
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
                    log('[比价器·出货] %s %s/%s 总%d 有效出货%d条' % (*key, total, len(offers)))
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
    """Ascending executable order book, weighted by purchasable gold."""
    target = float(parameters.get('成本采样金', 150))
    if target <= 50:
        raise ValueError('invalid sample target')
    if not page or page.get('error'):
        return None
    captured = page.get('captured_at')
    now = time.time() if now is None else now
    if captured is None or number(captured) is None or now-captured > float(parameters.get('报价最长时效秒',1200)) or captured > now+5:
        return None
    valid, seen = [], set()
    for offer in page.get('items') or []:
        price, stock, minimum = (number(offer.get(k)) for k in ('unit_rmb','stock','min_qty'))
        if price is None or stock is None or minimum is None or min(price, stock, minimum) <= 0 or stock < minimum:
            continue
        ident = offer.get('offer_id')
        if ident and ident in seen:
            continue
        if ident: seen.add(ident)
        valid.append(dict(offer,unit_rmb=price,stock=stock,min_qty=minimum))
    valid.sort(key=lambda o:o['unit_rmb'])
    total = sum(o['stock'] for o in valid)
    result = dict(source=source,avg_rmb=None,gold_used=0.,avail_gold=total,avail_total=total,
                  inventory_complete=page.get('inventory_complete',True),
                  n_items=len(valid),n_used=0,url=page.get('href',''),legs=[],captured_at=captured)
    if not result['inventory_complete'] and total < target:
        return None
    if not valid:
        if page.get('items') or page.get('raw_count',0):
            return None  # Existing but invalid offers are not a confirmed empty market.
        return dict(result,insufficient=True,short_reason='本轮无报价挂单')
    amount, cost = 0., 0.
    for o in valid:
        if total < target:
            take=o['stock']
        else:
            if amount >= target: break
            take=min(o['stock'],max(o['min_qty'],target-amount))
            step=number(o.get('step_qty'))
            if step and step>0:
                take=min(o['stock'],math.ceil(take/step-1e-9)*step)
        amount += take
        cost += take*o['unit_rmb']
        result['legs'].append(dict(price=o['unit_rmb'],gold=take,stock=o['stock'],minimum=o['min_qty'],offer_id=o.get('offer_id'),seller_id=o.get('seller_id')))
    result.update(avg_rmb=cost/amount,gold_used=amount,n_used=len(result['legs']),all_stock_avg_rmb=sum(o['unit_rmb']*o['stock'] for o in valid)/total,
                  offers=valid)
    if not result['inventory_complete']:
        result['observed_stock_avg_rmb']=result.pop('all_stock_avg_rmb')
    return result


def price_pair(dd_page,bjq_page,parameters,fx):
    if not number(fx) or fx<=0: raise ValueError('invalid FX')
    results=[source_cost(dd_page,'DD373',parameters),source_cost(bjq_page,'比价器',parameters)]
    quotes=[q for q in results if q and not q.get('insufficient')]
    target=float(parameters.get('成本采样金',150))
    for q in quotes:
        band = 'full' if q['avail_total']>=target else 'thin' if q['avail_total']>=50 else 'scarce'
        key, default={'full':('常规利润率',.25),'thin':('薄区利润率',.30),'scarce':('稀缺利润率',.35)}[band]
        margin=Decimal(str(parameters.get(key,default)))
        if not 0<=margin<1: raise ValueError('invalid margin')
        cost=Decimal(str(q['avg_rmb']))/Decimal(str(fx))
        q.update(margin=float(margin),margin_band=band,cost_usd=float(cost),
                 b2c=float((cost/(1-margin)).quantize(Decimal('.000001'),rounding=ROUND_CEILING)))
    if quotes:
        chosen=min(quotes,key=lambda q:q['b2c'])
        gap=max(q['b2c'] for q in quotes)/min(q['b2c'] for q in quotes)-1 if len(quotes)==2 else None
        return dict(mode='库存分档·%d%%毛利'%round(chosen['margin']*100),
            margin=chosen['margin'],avg_rmb=chosen['avg_rmb'],cost_usd=chosen['cost_usd'],iggm=None,b2c=chosen['b2c'],
            gold_used=chosen['gold_used'],n_items=chosen['n_items'],n_used=chosen['n_used'],avail_gold=chosen['avail_total'],
            note='库存加权成本；≥150G采样150G(按起购/整件可略超)，50至不足150G全量30%，不足50G全量35%；按双方最终售价择低；未下单锁货',
            margin_band=chosen['margin_band'],selected_source=chosen['source'],source_quotes=[q for q in results if q],
            source_gap=gap,source_gap_alert=gap is not None and gap>.5,
            floor_usd=chosen['b2c'],ceiling_usd=chosen['b2c'],rule=VERSION)
    short=[q for q in results if q and q.get('insufficient')]
    # Preserve the existing zero-stock fallback only; nonzero scarce stocks now price at 35%.
    both_empty = len(short) == 2
    park=2.99 if both_empty else None
    if park is not None and park<=0: raise ValueError('invalid zero-stock fallback')
    return dict(mode='双源无货·.99/G' if both_empty else '货源未确认·冻结',margin=None,avg_rmb=None,cost_usd=None,
        iggm=None,b2c=park,gold_used=0.,n_items=0,n_used=0,avail_gold=0.,
        note='双方均确认无报价挂单，按用户要求.99/G' if both_empty else '缺少双源无货确认，保持现价',
        both_empty=both_empty,margin_band='park' if both_empty else 'frozen',source_quotes=[q for q in results if q],selected_source=None,
        floor_usd=park,ceiling_usd=park,source_gap=None,source_gap_alert=False,rule=VERSION)




def cap_price_result(result, current_price, cap=1.60):
    """The user ceiling applies even to zero-stock/frozen/Hardcore prices."""
    if number(cap) is None or cap <= 0: raise ValueError('invalid price cap')
    result=dict(result)
    proposed=result.get('b2c')
    if proposed is None: proposed=current_price
    result['uncapped_b2c']=proposed
    result['target_margin']=result.get('margin')
    if result.get('both_empty'):
        result.update(b2c=2.99,cap_applied=False,cap_exempt=True,floor_usd=2.99,ceiling_usd=2.99)
        return result
    # A failed collection keeps the previous 2.99 exception until new evidence arrives.
    if result.get('margin_band')=='frozen' and current_price is not None and abs(current_price-2.99)<1e-6:
        result.update(cap_applied=False,cap_exempt=True)
        return result
    result['cap_applied']=proposed is not None and proposed>cap
    if result['cap_applied']:
        result['b2c']=cap
        result['margin']=1-result['cost_usd']/cap if result.get('cost_usd') is not None else None
        result['mode']='售价封顶$%.2f/G'%cap
        result['note']=(result.get('note') or '')+'；用户统一售价上限优先，封顶前$%s/G；利润按封顶价重算'%proposed
        result['floor_usd']=result['ceiling_usd']=cap
    return result


