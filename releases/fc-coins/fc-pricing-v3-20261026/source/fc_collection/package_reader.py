"""Read ordinary, platform-bound FC27 packages through public Scrapling HTTP."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
import sys
import uuid

IGGM = 'https://www.iggm.com/ea-sports-fc/fc-27-coins'
U4GM = 'https://www.u4gm.com/fc-27/coins'
LABELS = {'PS': ('PS', 'PS 4/5', ''), 'XBOX': ('XBOX', 'Xbox One/Series', '?server_code=xbox_one_series'),
          'PC': ('PC', 'PC', '?server_code=pc')}
QUANTITIES = ('100', '1000')
CENT = Decimal('.01')


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


def iggm_rows(doc, url, wanted, stamp):
    for card in doc.css('li.item.shippingCoins'):
        title = card.css('.item-title')
        chosen = card.css('[data-num].active')
        price = card.css('.item-price .price[lkr]')
        if len(title) != 1 or len(chosen) != 1 or len(price) != 1:
            continue
        name = re.fullmatch(r'FC\s*27 Coins (PS(?:4/5)?|Xbox|PC) Comfort Trade', content(title[0]), re.I)
        quantity = chosen[0].attrib['data-num']
        tier = re.fullmatch(r'(\d+)\s*K(?:\s*\+\s*(\d+)\s*K)?', content(chosen[0]), re.I)
        value = re.fullmatch(r'\$\s*(\d+(?:\.\d{1,2})?)', content(price[0]))
        if not (name and tier and tier[1] == quantity and value):
            continue
        platform = name[1].upper()
        platform = 'PS' if platform.startswith('PS') else platform
        if (platform, quantity) not in wanted:
            continue
        visible = amount(value[1])
        if visible > 0 and amount(price[0].attrib['lkr']).quantize(CENT, rounding=ROUND_HALF_UP) == visible:
            yield row('IGGM', platform, quantity, visible, tier[2] or '0', url, stamp, 'selected_native_price')


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
    parse = {'IGGM': iggm_rows, 'U4GM': u4gm_rows}[source]
    return list(parse(doc, url, {tuple(slot) for slot in wanted}, stamp))


def collect(source, wanted, get):
    if source == 'IGGM':
        urls = [IGGM]
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
            rows.extend(parse_packages(source, response, url, wanted, datetime.now(timezone.utc).isoformat()))
        except (ValueError, TypeError, KeyError, InvalidOperation, OSError) as exc:
            errors.append(type(exc).__name__)
    return rows, errors, max(0, retry_after)


def run_request(request):
    from scrapling.fetchers import Fetcher
    run_id = request['run_id']
    wanted = [tuple(pair) for pair in request['wanted']]
    if (str(uuid.UUID(run_id)) != run_id or not wanted or len(wanted)>6 or len(set(wanted))!=len(wanted)
            or any(p not in LABELS or q not in QUANTITIES for p,q in wanted)):
        raise ValueError('invalid_package_request')
    if request.get('receipt_only'):
        return dict(run_id=run_id, source=request['source'], offers=[], errors=['source_access_restricted'])
    def get(url):
        return Fetcher.get(url, timeout=7, retries=0, follow_redirects=False, stealthy_headers=False,
                           impersonate=None, headers={'User-Agent':'FS-FC27-PublicPrices/1.0','Accept':'text/html'})
    rows, errors, retry_after = collect(request['source'], wanted, get)
    return dict(run_id=run_id, source=request['source'], offers=[dict(r,run_id=run_id) for r in rows], errors=errors, retry_after_seconds=retry_after)


if __name__ == '__main__':
    print(json.dumps(run_request(json.load(sys.stdin))))
