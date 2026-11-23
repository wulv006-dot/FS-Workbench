"""Official independent ArabUT Console and PC public quotes; no account or writer."""
from decimal import Decimal
from html.parser import HTMLParser
import json
import re

from .contracts import (fingerprint, instant, fresh, ARAB_WARM_PATHS,
                        ARAB_PRICE_TABLE, ARAB_TABLE_SCOPE, ARAB_CONSOLE_DELIVERIES)

from .lootbar import VERSION as LOOTBAR_VERSION
VERSIONS = {'ArabUT': 'arab-public-quote-collection-v3', 'Lootbar': LOOTBAR_VERSION}
ARAB_QUERY = dict(platform='playstation', delivery='normal', quantity='100000')
ARAB_PC_QUERY = dict(platform='pc', quantity='100000')
REGISTRY = {'ArabUT': {name:dict(host='www.arab-ut.com', path=path,
    query=dict(ARAB_QUERY, currency='USD'), max_bytes=2097153) for name,path in ARAB_WARM_PATHS.items()}}
REGISTRY['ArabUT']['quote'] = dict(host='www.arab-ut.com', path='/en/coins/quote', query=ARAB_QUERY, max_bytes=1048576)
REGISTRY['ArabUT']['quote_fast'] = dict(REGISTRY['ArabUT']['quote'], query=dict(ARAB_QUERY, delivery='fast'))
REGISTRY['ArabUT']['quote_pc'] = dict(host='www.arab-ut.com', path='/en/coins/quote', query=ARAB_PC_QUERY, max_bytes=1048576)
REGISTRY['ArabUT']['prices_table'] = ARAB_PRICE_TABLE


# Both observers use fixed public GETs and the existing per-origin permit for each request.
from .package_reader import IGGM, U4GM, LABELS, parse_packages
VERSIONS.update(U4GM='u4gm-native-packages-v1', IGGM='iggm-native-packages-v1')
REGISTRY['IGGM'] = {'cards':dict(host='www.iggm.com',path='/ea-sports-fc/fc-27-coins',max_bytes=2097152)}
REGISTRY['U4GM'] = {platform:dict(host='www.u4gm.com',path='/fc-27/coins',max_bytes=2097152)
                    for platform in LABELS}
for platform, code in (('XBOX','xbox_one_series'),('PC','pc')):
    REGISTRY['U4GM'][platform]['query']={'server_code':code}


def package_adapter(task, transport):
    from .adapters import SourceUnavailable
    try:
        from scrapling import Selector
    except ImportError:
        raise ValueError('scrapling_runtime_unavailable') from None
    source = task['source_id']
    wanted = task['quantity_scope']['slots']
    pages = [('cards',IGGM)] if source=='IGGM' else [
        (p,U4GM+LABELS[p][2]) for p in task['requested_platforms']]
    offers = []
    for template, url in pages:
        try:
            html = transport.get(template)
            observed = instant(transport.clock()).isoformat()
            rows = parse_packages(source, Selector(html), url, wanted, observed)
        except (SourceUnavailable, OSError, ValueError, ArithmeticError) as exc:
            if not offers:
                raise
            reason = str(exc) if isinstance(exc, SourceUnavailable) else (
                'transport_unavailable' if isinstance(exc, OSError) else 'adapter_contract_invalid')
            result = dict(status='partial', reason_code=reason, offers=offers, evidence_hash=fingerprint(offers))
            if getattr(exc, 'retry_after_seconds', 0):
                result['retry_after_seconds'] = exc.retry_after_seconds
            return result
        for row in rows:
            size, gift = row['purchase_k'], row['bonus_k']
            offers.append(dict(platform=row['platform'],region_id=0,currency='USD',settlement_currency='USD',
                conversion_source='not_required',purchase_quantity=size,bonus_quantity=gift,quantity_unit='K',
                delivered_quantity=str(Decimal(size)+Decimal(gift)),amount=row['regular_price'],
                price_basis='ordinary_native_package',delivery_method='comfort_trade',discount_source='public_no_coupon',
                coupon_excluded=True,auth_state='public',conditional=False,comparable=True,observed_at=observed,
                selection_verified=True,sanitized_evidence_ref='sha256:'+fingerprint(row)))
    return dict(status='ok' if len(offers)==len(wanted) else 'partial' if offers else 'failed',
                reason_code=None if offers else 'ordinary_package_missing',offers=offers,evidence_hash=fingerprint(offers))


class ArabPriceTables(HTMLParser):
    sections = {'coins-prices-console': ('PS','XBOX'), 'coins-prices-pc': ('PC',)}

    def __init__(self):
        super().__init__()
        self.tables = {}
        self.table = self.row = self.cell = None
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            attrs = dict(attrs)
            section = attrs.get('aria-labelledby')
            if self.table is not None:
                raise ValueError('arab_price_table_nested')
            if section in self.sections and 'coins-prices__table' in attrs.get('class','').split():
                if section in self.tables:
                    raise ValueError('arab_price_table_duplicate')
                self.table = self.tables[section] = []
        if self.table is None:
            return
        if tag == 'tr':
            self.row = []
        if tag in ('th','td') and self.row is not None:
            self.cell = []
        if tag == 'small':
            self.skip = True

    def handle_endtag(self, tag):
        if tag in ('th','td') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == 'table':
            self.table = None
        if tag == 'small':
            self.skip = False

    def handle_data(self, data):
        if self.cell is not None and not self.skip:
            self.cell.append(data)


def arab_prices(payload, now, requested):
    reader = ArabPriceTables()
    reader.feed(payload.decode('utf-8'))
    reader.close()
    quantities = {'100K':'100','1M':'1000','2M':'2000','5M':'5000'}
    offers, currencies = [], set()
    for section, platforms in reader.sections.items():
        rows = reader.tables.get(section)
        if not rows:
            continue
        console = 'PS' in platforms
        header, *data = rows
        if header != (['Amount','Normal','Fast'] if console else ['Amount','Price']):
            raise ValueError('arab_price_table_columns')
        deliveries = ('normal','fast') if console else ('standard',)
        seen = set()
        for row in data:
            if not row or row[0] not in quantities:
                continue
            purchase = quantities[row[0]]
            if purchase in seen or len(row) != len(header):
                raise ValueError('arab_price_table_quantity_ambiguous')
            seen.add(purchase)
            for delivery, cell in zip(deliveries,row[1:]):
                if cell == '—':
                    continue
                match = re.fullmatch(r'(USD|SAR) ((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,12})\.[0-9]{2})',cell)
                if not match:
                    raise ValueError('arab_price_table_amount_unverified')
                currency, amount = match[1], match[2].replace(',','')
                if Decimal(amount) <= 0:
                    raise ValueError('arab_price_table_amount_unverified')
                currencies.add(currency)
                reference = fingerprint([section,purchase,delivery,currency,amount])
                offers.extend(dict(platform=p, region_id=21, currency=currency, settlement_currency=currency,
                    conversion_source='not_required', purchase_quantity=purchase, bonus_quantity='0',
                    delivered_quantity=purchase, quantity_unit='K', amount=amount,
                    price_basis='official_public_price_table', delivery_method=delivery,
                    discount_source='official_public_no_coupon', coupon_excluded=True, auth_state='public',
                    conditional=False, comparable=False, observed_at=instant(now).isoformat(), selection_verified=True,
                    sanitized_evidence_ref='sha256:'+reference) for p in platforms if p in requested)
    if len(currencies) != 1 or not offers:
        raise ValueError('arab_price_table_coverage_or_currency')
    return offers


def arab_offers(value, now, *, platform='playstation', console_delivery='normal'):
    pc = platform == 'pc'
    if (platform not in ('playstation', 'pc') or console_delivery not in ARAB_CONSOLE_DELIVERIES
            or not isinstance(value, dict)
            or not isinstance(value.get('total'), dict) or not isinstance(value.get('displayTotal'), dict)
            or value.get('platform') != platform or 'delivery' not in value
            or value['delivery'] != (None if pc else console_delivery) or type(value.get('quantity')) is not int
            or value['quantity'] != 100000 or value.get('market') != ('pc' if pc else 'console')
            or value['total'].get('currency') != 'SAR' or value['displayTotal'].get('currency') != 'USD'
            or any(value.get(key, 0) != 0 for key in ('bonus', 'bonusQuantity'))
            or value.get('deliveredQuantity', 100000) != 100000):
        raise ValueError('arab_quote_selection_invalid')
    amount = value['displayTotal'].get('amountMinor')
    settlement = value['total'].get('amountHalalah')
    if type(amount) is not int or amount <= 0 or type(settlement) is not int or settlement <= 0:
        raise ValueError('arab_quote_amount_invalid')
    version = value.get('priceVersion')
    if not (type(version) is int and 0 <= version <= 2**63 - 1
            or isinstance(version, str) and 0 < len(version) <= 120):
        raise ValueError('arab_quote_version_invalid')
    fresh(value.get('pricedAt'), now)
    safe_evidence = {key: value[key] for key in ('platform', 'delivery', 'quantity', 'market',
                     'total', 'displayTotal', 'priceVersion', 'pricedAt')}
    digest = fingerprint(safe_evidence)
    common = dict(region_id=21, currency='USD', settlement_currency='SAR', conversion_source='official_display_quote',
        purchase_quantity='100', bonus_quantity='0', delivered_quantity='100', quantity_unit='K',
        amount=str(Decimal(amount) / 100), price_basis='public_merchandise', delivery_method='standard' if pc else console_delivery,
        discount_source='official_no_coupon', coupon_excluded=True, auth_state='public', conditional=False,
        comparable=True, observed_at=instant(now).isoformat(), selection_verified=True, sanitized_evidence_ref='sha256:' + digest,
        source_metadata=dict(original_currency='SAR', original_amount_minor=settlement,
            price_version=version, priced_at=value['pricedAt'], original_platform=platform,
            original_market=value['market'], original_delivery=value['delivery']))
    return [dict(common, platform=p) for p in (('PC',) if pc else ('PS', 'XBOX'))]


def arab_payload(payload, now, platform, *, console_delivery='normal'):
    from .adapters import SourceUnavailable
    try:
        data = json.loads(payload)
    except (ValueError, TypeError, RecursionError):
        raise SourceUnavailable('arab_quote_html_response' if payload.lstrip().startswith(b'<') else 'arab_quote_json_invalid') from None
    if not isinstance(data, dict):
        raise SourceUnavailable('arab_quote_json_invalid')
    try:
        return arab_offers(data.get('data', data), now, platform=platform, console_delivery=console_delivery)
    except ValueError as exc:
        allowed = {'arab_quote_selection_invalid', 'arab_quote_amount_invalid', 'arab_quote_version_invalid',
                   'timestamp_invalid', 'observation_stale'}
        raise SourceUnavailable(str(exc) if str(exc) in allowed else 'arab_quote_contract_invalid') from None


def arab_adapter(task, transport):
    from .adapters import ArabNormalDeliveryUnavailable, SourceUnavailable, WarmLanguageRedirect
    requested = set(task['requested_platforms'])
    if not requested or requested - {'PS', 'XBOX', 'PC'} or task['region_scope'] != [21]:
        raise ValueError('arab_quote_scope_invalid')
    if task.get('quantity_scope') == ARAB_TABLE_SCOPE:
        payload = transport.get('prices_table')
        try:
            offers = arab_prices(payload,transport.clock(),requested)
        except (UnicodeError,ValueError):
            raise SourceUnavailable('arab_price_table_unverified') from None
        return dict(status='ok', reason_code=None, offers=offers,
                    evidence_hash=fingerprint([row['sanitized_evidence_ref'] for row in offers]))
    try:
        transport.get('warm')
    except WarmLanguageRedirect as redirect:
        transport.get(redirect.template_id)
    offers, errors, retry_after = [], {}, 0
    groups = [('quote', 'playstation', requested & {'PS', 'XBOX'}), ('quote_pc', 'pc', requested & {'PC'})]
    blockers = {'http_401', 'http_403', 'http_429', 'challenge', 'captcha'}
    unknown = {'transport_unavailable', 'request_timeout', 'dns_unavailable'}
    for template, platform, platforms in groups:
        if not platforms:
            continue
        try:
            console_delivery = 'normal'
            try:
                payload = transport.get(template)
            except ArabNormalDeliveryUnavailable:
                if template != 'quote':
                    raise
                console_delivery = 'fast'
                payload = transport.get('quote_fast')
            rows = arab_payload(payload, transport.clock(), platform, console_delivery=console_delivery)
            offers.extend(row for row in rows if row['platform'] in platforms)
        except (SourceUnavailable, OSError, TimeoutError) as exc:
            reason = str(exc) if isinstance(exc, SourceUnavailable) else 'transport_unavailable'
            errors.update({p: reason for p in sorted(platforms)})
            retry_after = max(retry_after, getattr(exc, 'retry_after_seconds', 0))
            if reason in blockers or reason in unknown:
                errors.update({p: reason if reason in blockers else 'origin_request_pending' for p in sorted(requested)
                               if p not in errors and not any(row['platform'] == p for row in offers)})
                break
    if not offers and requested <= {'PS', 'XBOX'}:
        raise SourceUnavailable(next(iter(errors.values())), retry_after)
    reason = next((value for value in errors.values() if value in blockers), next(iter(errors.values()), None))
    status = 'ok' if not errors else 'partial' if offers else 'blocked' if reason in blockers else 'failed'
    result = dict(status=status, reason_code=reason, offers=offers,
        evidence_hash=fingerprint([row['sanitized_evidence_ref'] for row in offers]))
    if errors:
        result['platform_errors'] = errors
    if retry_after:
        result['retry_after_seconds'] = retry_after
    return result
