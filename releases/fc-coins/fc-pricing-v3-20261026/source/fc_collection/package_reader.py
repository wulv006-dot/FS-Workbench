"""Read ordinary, platform-bound FC27 packages through public Scrapling HTTP."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
import sys
import uuid
from urllib.parse import urlencode

U4GM = 'https://www.u4gm.com/fc-27/coins'
LABELS = {'PS': ('PS', 'PS 4/5', ''), 'XBOX': ('XBOX', 'Xbox One/Series', '?server_code=xbox_one_series'),
          'PC': ('PC', 'PC', '?server_code=pc')}
QUANTITIES = ('100', '1000')
CENT = Decimal('.01')
LOOTBAR_SKUS = {'PS': {'100': 2120124, '1000': 2322452},
                'XBOX': {'100': 2120122, '1000': 2322451},
                'PC': {'100': 2099779, '1000': 2322450}}


def lootbar_url(platform):
    return 'https://api.lootbar.com/api/v2/market/sku/price?' + urlencode(dict(
        page_num=1, page_size=40, spu_id=1461, attribute=json.dumps(
            {'platform':platform.lower()}, separators=(',', ':')), dispatch_seller=0, _l='en'))


def lootbar_rows(payload, url, wanted, stamp):
    platform = next((p for p in LABELS if url == lootbar_url(p)), None)
    page = payload.get('data') or {}
    items = page.get('items')
    if (platform is None or payload.get('msg') != 'OK' or not isinstance(items, list)
            or page.get('page_num') != 1 or page.get('total_page') != 1
            or page.get('total_count') != len(items)):
        return []
    rows = {}
    duplicates = set()
    for item in items:
        name = (item.get('info') or {}).get('asset_name')
        qty = {'100K Safe Coins':'100', '1M Safe Coins':'1000', '1000K Safe Coins':'1000'}.get(name)
        if ((platform, qty) not in wanted or item.get('tradable') is not True or item.get('region_error')
                or item.get('id') != LOOTBAR_SKUS[platform][qty]):
            continue
        display = (item.get('sell_order') or {}).get('display_price') or {}
        if display.get('currency') != 'USD':
            continue
        regular, net = amount(display['price']), amount(display['real_price'])
        coupon = (item.get('discount_info') or {}).get('coupon') or {}
        if not 0 < net <= regular:
            continue
        if regular != net and (not re.fullmatch(r'New User \d+(?:\.\d+)?% OFF Coupon', coupon.get('name',''), re.I)
                               or regular-net != amount(display.get('save_price'))):
            continue
        gift = item.get('gift')
        bonus = re.fullmatch(r'(\d+(?:\.\d+)?)K', gift.get('gift_num','') if isinstance(gift,dict) else '0K', re.I)
        if not bonus or gift is not None and not isinstance(gift,dict):
            continue
        if qty in rows:
            duplicates.add(qty)
        rows[qty] = dict(source='Lootbar', platform=platform, purchase_k=qty, bonus_k=bonus[1],
                         regular_price=str(regular), gross_usd=str(regular), currency='USD', region_id=0,
                         effective_usd_per_k=str(regular/(Decimal(qty)+Decimal(bonus[1]))), captured_at=stamp,
                         url=url, auth_state='public', conditional=False, comparable=True, status='valid',
                         selection_verified=True, coupon_excluded=True, price_basis='public_platform_sku',
                         discount_source='public_no_coupon', source_metadata=dict(spu_id=1461, platform=platform,
                         asset_name=name, sku_id=item['id'], selected_currency='USD', coupon_excluded=regular!=net))
    return [r for q,r in rows.items() if q not in duplicates]


def amount(value):
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError('invalid_amount')
    return number


def content(node):
    return ' '.join(node.get_all_text(separator=' ', strip=True).split())


def row(source, platform, quantity, price, gift, url, stamp, basis):
    return dict(source=source, platform=platform, purchase_k=quantity, bonus_k=str(gift),
                regular_price=format(price, '.2f'), currency='USD', region_id='0', source_url=url,
                conditional=False, comparable=True, promotion_eligibility='all_customers', coupon_excluded=True,
                selection_verified=True, delivery_method='comfort_trade', delivery_tier=None,
                captured_at=stamp, status='valid', evidence_ref={'price_basis':basis})


def u4gm_rows(doc, url, wanted, stamp):
    titles, units, levels = doc.css('h1'), doc.css('[data-unit-price]'), doc.css('.js-product-level')
    if len(titles) != 1 or len(units) != 1 or len(levels) != 1:
        return
    title = content(titles[0])
    for platform, (_, label, suffix) in LABELS.items():
        if url != U4GM + suffix or title.casefold() != ('FC 27 Coins '+label+' Comfort Trade').casefold():
            continue
        if not doc.xpath('//*[not(*) and normalize-space(.)="USD"]'):
            return
        unit = amount(units[0].attrib['data-unit-price'])
        rules = json.loads(content(levels[0]))
        if not isinstance(rules, dict) or not unit:
            return
        for quantity in QUANTITIES:
            rule = rules.get(quantity)
            if (platform, quantity) not in wanted or not isinstance(rule, dict):
                continue
            # Unknown or additional incentives have no proven ordinary-customer eligibility.
            if set(rule) - {'type','feature','value'}:
                continue
            value = amount(rule.get('value'))
            price, gift = unit * Decimal(quantity), Decimal(0)
            if (rule.get('type'), rule.get('feature')) == ('bonus', 'fixed'):
                gift = value
            elif (rule.get('type'), rule.get('feature')) == ('discount', 'percent') and value < 100:
                price *= 1 - value / 100
            else:
                continue
            price = price.quantize(CENT, rounding=ROUND_HALF_UP)
            if price > 0:
                yield row('U4GM', platform, quantity, price, gift, url, stamp, 'native_volume_rule')


def parse_packages(source, doc, url, wanted, stamp):
    if source != 'U4GM':
        raise ValueError('unknown_package_source')
    return list(u4gm_rows(doc, url, {tuple(slot) for slot in wanted}, stamp))


def collect(source, wanted, get):
    if source == 'Lootbar':
        urls = [lootbar_url(p) for p in LABELS if any(platform == p for platform, _ in wanted)]
    elif source == 'U4GM':
        urls = [U4GM+details[2] for platform, details in LABELS.items() if any(p==platform for p,q in wanted)]
    else:
        raise ValueError('unknown_package_source')
    rows, errors, retry_after = [], [], 0
    for url in urls:
        try:
            response = get(url)
            if response.status != 200:
                errors.append('http_'+str(response.status))
                if response.status == 429:
                    header = str(response.headers.get('retry-after') or response.headers.get('Retry-After') or '')
                    try:
                        retry_after = int(header) if header.isdecimal() else ceil(
                            (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        retry_after = 0
                if response.status in (401,403,429):
                    break
                continue
            if str(response.url) != url or len(response.body) > 4*1024*1024:
                errors.append('response_scope_invalid')
                continue
            if any(marker in response.body.lower() for marker in (b'cf-chl-', b'challenge-platform', b'g-recaptcha')):
                errors.append('challenge')
                break
            stamp = datetime.now(timezone.utc).isoformat()
            if source == 'Lootbar':
                rows.extend(lootbar_rows(json.loads(response.body), url, set(wanted), stamp))
            else:
                rows.extend(parse_packages(source, response, url, wanted, stamp))
        except (ValueError, TypeError, KeyError, InvalidOperation, OSError) as exc:
            errors.append(type(exc).__name__)
    return rows, errors, max(0, retry_after)


def run_request(request):
    from scrapling.fetchers import Fetcher
    if set(request) != {'source','run_id','wanted'} or request['source'] not in ('Lootbar','U4GM'):
        raise ValueError('invalid_package_request')
    run_id = request['run_id']
    wanted = [tuple(pair) for pair in request['wanted']]
    if (str(uuid.UUID(run_id)) != run_id or not wanted or len(wanted)>6 or len(set(wanted))!=len(wanted)
            or any(p not in LABELS or q not in QUANTITIES for p,q in wanted)):
        raise ValueError('invalid_package_request')
    def get(url):
        return Fetcher.get(url, timeout=7, retries=0, follow_redirects=False, stealthy_headers=False,
                           impersonate=None, headers={'User-Agent':'FS-FC27-PublicPrices/1.0','Accept':'text/html'})
    rows, errors, retry_after = collect(request['source'], wanted, get)
    return dict(run_id=run_id, source=request['source'], offers=[dict(r,run_id=run_id) for r in rows], errors=errors, retry_after_seconds=retry_after)


if __name__ == '__main__':
    print(json.dumps(run_request(json.load(sys.stdin))))
