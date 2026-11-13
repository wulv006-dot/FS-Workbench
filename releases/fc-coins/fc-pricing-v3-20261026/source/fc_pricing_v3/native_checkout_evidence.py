"""Normalize native guest cart quotes and derive fixed-tier candidate amounts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

from .admin_readback import GID_FC27, MID_FC27_COINS, PLATFORM_AID, SITE_MAIN
from .financial import fingerprint, instant, number
from .price_curve import EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, curve_key, quote_native


CONTRACT = 'fc_native_checkout_observation_v1'
GUEST = 'anonymous_no_coupon'
FIXED_CATALOGUE = 'derived_native_fixed_catalogue'
CART_CENTS = 'native_usd_cart_line_cent_as_read_v1'
CATALOGUE_CENTS = 'native_fixed_catalogue_usd_cent_as_published_v1'
MAX_AGE = timedelta(minutes=15)
GOODS = {'PS': ('163329309', '163329311'), 'XBOX': ('163329275', '163329277'),
         'PC': ('163329343', '163329345')}
REF = re.compile(r'[a-f0-9]{64}')
USD = re.compile(r'(?:0|[1-9]\d*)(?:\.\d{1,2})?')
INT = re.compile(r'0|[1-9]\d*')
ORIGIN = 'https://www.mmoexp.com'
LANDING = ORIGIN + '/Fc-27/Coins.html?cy=USD'
CART = '/Cart.html?cy=USD'
CART_SHOW = '/Cart/cartShow.html'
CART_ADD = '/Cart/add.html'
CART_CLEAR = '/Cart/clear'
REQUEST_TIMEOUT = 10
TLS_PYTHON = '/opt/python39/bin/python3'
TLS_MODULE = 'fc_pricing_v3.native_checkout_evidence'
OBSERVATION_ERRORS = (AttributeError, ArithmeticError, KeyError, OSError, TypeError, ValueError)


def _digest(raw):
    return sha256(raw).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _money(value):
    _require(isinstance(value, str) and USD.fullmatch(value), 'native_cart_amount_invalid')
    return number(value, zero=True)


def _whole(value):
    _require(type(value) in (int, str) and INT.fullmatch(str(value)), 'native_cart_quantity_invalid')
    result = int(value)
    _require(result <= 10 ** 8, 'native_cart_quantity_invalid')
    return result


class _Checkout(HTMLParser):
    def __init__(self, raw):
        super().__init__()
        self.site_currency = []
        self.in_currency = False
        self.rows = []
        self.subtotal = []
        self.coupon = []
        self.empty = False
        self.feed(raw.decode('utf-8'))

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        classes = set(attr.get('class', '').split())
        if 'lang-currency' in classes:
            self.in_currency = True
        if tag == 'h1' and 'no-title' in classes:
            self.empty = True
        if 'data-cart-category' in attr:
            match = re.fullmatch(r"'cart_key_'\s*\+\s*'new_gold'\s*\+\s*'(GOLD_\d+_\d+)'", attr.get(':class', ''))
            _require(attr['data-cart-category'] == 'new_gold' and match, 'native_cart_html_line_invalid')
            self.rows.append([match[1], None])
        if tag == 'input' and 'item-num' in classes:
            _require(self.rows and self.rows[-1][1] is None, 'native_cart_html_quantity_invalid')
            self.rows[-1][1] = _whole(attr['value'])
        if 'amount-price' in classes and 'data-compute-price' in attr:
            currency, amount = attr['data-compute-price'].split()
            _require(currency == '$', 'native_cart_html_currency_invalid')
            self.subtotal.append(_money(amount))
        if 'gree-price' in classes:
            self.coupon.append(tuple(_money(attr[name]) for name in ('data-coupon-id', 'data-coupon-price',
                'data-discount-price', 'data-count-coupon-price', 'data-count-discount-price')))

    def handle_endtag(self, tag):
        if tag == 'div':
            self.in_currency = False

    def handle_data(self, data):
        if self.in_currency and data.strip():
            self.site_currency.append(data.strip())


def _main_curve(curve, platform):
    identity = curve['identity']
    _require(identity['site_id'] == SITE_MAIN and identity['id'] == GOODS[platform][1]
             and identity['aid'] == PLATFORM_AID[platform] and identity['mid'] == MID_FC27_COINS
             and identity['gid'] == GID_FC27 and identity['unit'] == 'K'
             and curve.get('compilation_status') != 'EDITOR_CANDIDATE', 'native_checkout_curve_scope')
    return identity


def _cart_lines(raw, response_kind, platform, identity):
    body = json.loads(raw)
    _require(body['code'] == 1, 'native_cart_response_invalid')
    cart = body['data']['cart'][response_kind]
    _require(cart['has_removed'] is False and not cart['removed_items'], 'native_cart_items_removed')
    rows = {}
    for group, group_rows in cart['details'].items():
        if not group_rows:
            continue
        if response_kind == 'cartshow' and group == GID_FC27 and isinstance(group_rows, list):
            items = [(row['cart_key'], row) for row in group_rows]
        elif response_kind == 'detach' and group == 'new_gold' and isinstance(group_rows, dict):
            items = group_rows.items()
        else:
            raise ValueError('native_cart_unexpected_group')
        for key, row in items:
            quantity, multiplier, gift = (_whole(row[field]) for field in ('group', 'num', 'free_num'))
            _require(quantity > 0 and multiplier == 1 and str(row['id']) == GOODS[platform][1]
                     and str(row['aid']) == identity['aid'] and str(row['gid']) == identity['gid']
                     and str(row['goods_cid']) == identity['cid'] and str(row['top_cid']) == '1'
                     and row['unit'] == 'K' and row['coin'] == 'new_gold'
                     and key == f'GOLD_{GOODS[platform][1]}_{quantity}' and key not in rows,
                     'native_cart_row_scope_mismatch')
            regular = _money(row['amount_format'])
            net = _money(row['discount_amount_format'])
            off = _money(row['off_amount_format'])
            _require(regular > 0 and regular == net and not off, 'native_cart_not_guest_regular')
            rows[key] = dict(purchase_k=str(quantity), gift_k=str(gift), multiplier=multiplier,
                             promised_delivered_k=str(quantity + gift), regular_usd=format(regular.normalize(), 'f'),
                             net_goods_usd=format(net.normalize(), 'f'))
    subtotal = _money(cart['amount_format'])
    _require(rows and len(rows) == cart['total'] == cart['item_total']
             and sum(Decimal(row['net_goods_usd']) for row in rows.values()) == subtotal, 'native_cart_subtotal_mismatch')
    return rows, subtotal, body['time']


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, stream, code, message, headers, new_url):
        raise ValueError('native_checkout_redirect')


class _GuestCart:
    def __init__(self):
        self.opener = build_opener(_NoRedirect(), HTTPCookieProcessor(CookieJar()))

    def request(self, path, form=None):
        if path in (CART_ADD, CART_CLEAR, '/ajax/goods'):
            _require(form is not None, 'native_cart_post_form_required')
        else:
            _require(path in (CART, CART_SHOW) and form is None, 'native_cart_request_scope')
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'en-US,en;q=0.8', 'Referer': LANDING}
        if path == CART_SHOW:
            headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
        if path == CART_SHOW or form is not None:
            headers['X-Requested-With'] = 'XMLHttpRequest'
        data = None
        if form is not None:
            headers.update({'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'Origin': ORIGIN})
            data = urlencode(form).encode()
        with self.opener.open(Request(ORIGIN + path, headers=headers, data=data), timeout=REQUEST_TIMEOUT) as response:
            _require(response.url == ORIGIN + path, 'native_cart_unexpected_url')
            body = response.read(2_000_001)
        _require(len(body) <= 2_000_000, 'native_cart_response_too_large')
        return body

    def confirm_empty(self):
        raw = self.request(CART)
        html = _Checkout(raw)
        _require(html.empty and not html.rows and b'Your cart is empty' in raw, 'native_guest_cart_not_empty')


def _probe_quantities(platform, curve, requested):
    wanted = set(requested)
    tiers = [tier for tier in curve['tiers'] if tier['purchase_k'] in wanted
             and INT.fullmatch(tier['purchase_k'])]
    preferred = ('100', '2000', '1000') if platform == 'PC' else ('100', '1000', '2000')
    rank = {quantity: index for index, quantity in enumerate(preferred)}
    ordered = sorted(tiers, key=lambda tier: rank.get(tier['purchase_k'], len(rank)))
    by_rule = {}
    for tier in ordered:
        by_rule.setdefault(_fixed_rule(tier), tier['purchase_k'])
    anchors = dict.fromkeys([*by_rule.values(), *(tier['purchase_k'] for tier in ordered)])
    return tuple(anchors)[:2]


def _partial(run_id, platform, curve, reason, latest=None):
    if latest:
        return dict(latest, status='partial', reason=reason, coverage_gaps=[*latest['coverage_gaps'], reason])
    return dict(contract=CONTRACT, run_id=run_id, platform=platform, site_id=SITE_MAIN, curve_key=curve_key(curve),
                captured_at=datetime.now(timezone.utc).isoformat(), lines=[], status='partial', reason=reason,
                coverage_status='partial', coverage_gaps=[reason])


def _collect_platform(run_id, platform, curve, requested):
    identity = _main_curve(curve, platform)
    quantities = _probe_quantities(platform, curve, requested)
    if not quantities:
        return {}
    client = _GuestCart()
    try:
        goods = client.request('/ajax/goods', {'Game_id': identity['gid'], 'top_cid': 1, 'aid': identity['aid'],
                                              'cid': identity['cid'], 'site_id': identity['site_id']})
        client.confirm_empty()
    except OBSERVATION_ERRORS:
        return _partial(run_id, platform, curve, 'native_guest_cart_preflight_unavailable')

    latest, reason = {}, None
    try:
        for quantity in quantities:
            request = dict(category='new_gold', id=identity['id'], group=quantity, num=1, attr='', aid='')
            try:
                detach = client.request(CART_ADD, request)
            except (OSError, ValueError):
                # Same guest cart only. A missing response is never permission to add again.
                reason = 'native_guest_cart_add_readback_unavailable'
                try:
                    shown = client.request(CART_SHOW)
                    rows, _, _ = _cart_lines(shown, 'cartshow', platform, identity)
                    if quantity in {line['purchase_k'] for line in rows.values()}:
                        reason = 'native_guest_cart_add_observed_without_receipt'
                except OBSERVATION_ERRORS:
                    pass
                break
            try:
                current = build_anonymous_observation(
                    run_id, platform, curve, goods_raw=goods, detach_raw=detach,
                    cart_show_raw=client.request(CART_SHOW), cart_html_raw=client.request(CART),
                    captured_at=datetime.now(timezone.utc))
                _require(quantity in {line['purchase_k'] for line in current['lines']}, 'native_cart_requested_line_missing')
            except OSError:
                reason = 'native_guest_cart_checkout_read_unavailable'
                break
            except OBSERVATION_ERRORS:
                reason = 'native_guest_cart_checkout_evidence_invalid'
                break
            latest = current
    finally:
        # Read the same anonymous cart even when the clear response is lost.
        try:
            client.request(CART_CLEAR, {})
        except (OSError, ValueError):
            pass
        try:
            client.confirm_empty()
        except OBSERVATION_ERRORS:
            reason = 'native_guest_cart_cleanup_unverified'
            latest = {}
    return _partial(run_id, platform, curve, reason, latest) if reason else latest


def _collect_live(run_id, primary_curves, requested_quantities):
    def capture(platform, curve):
        try:
            return _collect_platform(run_id, platform, curve, requested_quantities.get(platform, ()))
        except OBSERVATION_ERRORS:
            return _partial(run_id, platform, curve, 'native_guest_cart_observation_unavailable')

    if not primary_curves:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(primary_curves), 3)) as pool:
        work = {platform: pool.submit(capture, platform, curve) for platform, curve in primary_curves.items()}
        return {platform: value for platform, task in work.items() if (value := task.result())}


def _collect_with_tls_runtime(run_id, primary_curves, requested_quantities):
    """Use the installed HTTPS interpreter when the quote worker has no ssl module."""
    try:
        import ssl
    except ImportError:
        request = dict(run_id=run_id, primary_curves=primary_curves, requested_quantities=requested_quantities)
        try:
            child = subprocess.run([TLS_PYTHON, '-B', '-m', TLS_MODULE], input=json.dumps(request),
                                   cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=120)
            if child.returncode:
                raise ValueError('native_guest_cart_tls_child_failed')
            result = json.loads(child.stdout)
            if not isinstance(result, dict) or set(result) - set(primary_curves):
                raise ValueError('native_guest_cart_tls_child_reply_invalid')
            return result
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {platform: _partial(run_id, platform, curve, 'native_guest_cart_tls_runtime_unavailable')
                    for platform, curve in primary_curves.items()}
    return _collect_live(run_id, primary_curves, requested_quantities)


def build_anonymous_observation(run_id, platform, current_curve, *, captured_at, goods_raw,
                                detach_raw, cart_show_raw, cart_html_raw):
    """One private guest preview, with exact server add/readback and rendered subtotal."""
    identity = _main_curve(current_curve, platform)
    captured = instant(captured_at)
    source = json.loads(goods_raw)['goods']['index']['list']
    _require(len(source) == 1, 'native_goods_not_unique')
    row = source[0]
    _require(all(str(row[name]) == identity[name] for name in ('id', 'site_id', 'aid', 'gid', 'mid', 'cid', 'unit'))
             and number(row['_region_factor']) == 1
             and number(row['unit_price']) == Decimal(current_curve['unit_price_usd_per_k']), 'native_goods_curve_mismatch')
    add, add_subtotal, added_at = _cart_lines(detach_raw, 'detach', platform, identity)
    read, subtotal, read_at = _cart_lines(cart_show_raw, 'cartshow', platform, identity)
    _require(add == read and add_subtotal == subtotal and 0 <= read_at - added_at <= 30
             and 0 <= captured.timestamp() - read_at <= 60, 'native_cart_readback_mismatch')
    html = _Checkout(cart_html_raw)
    _require(' '.join(' '.join(html.site_currency).split()) == 'US | USD' and html.subtotal == [subtotal]
             and html.coupon == [(0, 0, 0, subtotal, subtotal)]
             and len(html.rows) == len(read) and dict(html.rows) == {key: value['multiplier'] for key, value in read.items()},
             'native_cart_checkout_path_unverified')

    sources = {name: _digest(raw) for name, raw in dict(goods=goods_raw, add=detach_raw,
                                                     cart_show=cart_show_raw, cart_html=cart_html_raw).items()}
    revision = fingerprint(dict(contract=CONTRACT, sources=sources, platform=platform))
    key = curve_key(current_curve)
    lines = []
    for native_key, observed in read.items():
        quantity = observed['purchase_k']
        quote = quote_native(current_curve, dict(purchase_k=quantity, multiplier=1, site_id=SITE_MAIN, currency='USD'))
        fixed = row['goods_list'].get(quantity)
        is_fixed = bool(fixed and quote['regular_usd'] is not None
                        and _whole(fixed['num']) == int(quantity)
                        and Decimal(quote['regular_usd']) == Decimal(observed['regular_usd'])
                        and _money(fixed['full_price_format']) == Decimal(observed['regular_usd'])
                        and quote['promised_delivered_k'] == observed['promised_delivered_k'])
        ref = fingerprint(dict(revision=revision, native_key=native_key, curve_key=key, line=observed))
        lines.append(dict(observed, path_id='catalogue:' + quantity, site_id=SITE_MAIN, goods_id=identity['id'],
                          aid=identity['aid'], region_id='0', currency='USD', amount_kind='TOTAL',
                          curve_key=key, offer_path=GUEST, proof_status='verified' if is_fixed else 'observed',
                          quote_basis='observed_native_cart', quote_ref=ref, eligibility_ref=sources['cart_html'],
                          offer_version=revision, fulfilment_ref=sources['cart_show'],
                          fulfilment_contract='native_cart_purchase_and_free_num_only_v1',
                          rounding_contract=CART_CENTS,
                          native_tier_or_rule=quote['native_tier_or_rule'] if is_fixed else 'native_cart_custom_observed',
                          net_receipt_usd=observed['net_goods_usd']))
    fixed_catalogue = _matched_fixed_catalogue(current_curve, row['goods_list'])
    return dict(contract=CONTRACT, run_id=run_id, platform=platform, site_id=SITE_MAIN, curve_key=key,
                captured_at=captured.isoformat(), source_sha256=sources, native_quote_revision=revision,
                lines=lines, fixed_catalogue=fixed_catalogue, coverage_status='partial',
                coverage_gaps=['anonymous_guest_quantities_only', 'member_and_discount_allocation_unverified',
                               'multi_order_fulfilment_unverified'])


def _matched_fixed_catalogue(curve, public):
    """Capture only complete fixed quantities agreeing with the Admin goods row."""
    tiers = curve['tiers']
    if not isinstance(public, dict) or set(public) != {tier['purchase_k'] for tier in tiers}:
        return []
    try:
        for tier in tiers:
            quantity = tier['purchase_k']
            row = public[quantity]
            if (_whole(row['num']) != _whole(quantity)
                    or _money(row['full_price_format']) != Decimal(tier['native_price_usd'])
                    or _whole(row['give']) != _whole(tier['promised_bonus_k'])
                    or number(row['discount'], zero=True) != Decimal(tier['native_discount'])):
                return []
        return [tier['purchase_k'] for tier in tiers]
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
        pass
    return []


def _bound_line(line, curve, key, *, derived=False):
    try:
        qty = line['purchase_k']
        quote = quote_native(curve, dict(purchase_k=qty, multiplier=1, site_id=SITE_MAIN, currency='USD'))
        return (line['curve_key'] == key and line['site_id'] == SITE_MAIN and line['offer_path'] == GUEST
                and line['goods_id'] == curve['identity']['id'] and line['aid'] == curve['identity']['aid']
                and line['region_id'] == '0' and type(line['multiplier']) is int and line['multiplier'] == 1
                and line['currency'] == 'USD' and line['amount_kind'] == 'TOTAL'
                and line['net_receipt_usd'] == line['net_goods_usd']
                and line['fulfilment_contract'] == 'native_cart_purchase_and_free_num_only_v1'
                and line['rounding_contract'] == (CATALOGUE_CENTS if derived else CART_CENTS)
                and line['native_tier_or_rule'] == quote['native_tier_or_rule']
                and line['quote_basis'] == (FIXED_CATALOGUE if derived else 'observed_native_cart')
                and line['proof_status'] == 'verified'
                and all(REF.fullmatch(line[field]) for field in ('quote_ref', 'eligibility_ref', 'offer_version', 'fulfilment_ref'))
                and Decimal(line['regular_usd']) == Decimal(quote['regular_usd']) == Decimal(line['net_goods_usd'])
                and line['promised_delivered_k'] == quote['promised_delivered_k']
                and line['gift_k'] == quote['promised_bonus_k'])
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False


def _fixed_rule(tier):
    return (Decimal(tier['promised_bonus_k']) / Decimal(tier['purchase_k']),
            Decimal(tier['native_discount']))


def _fixed_catalogue_lines(curve, observation, anchors, requested):
    catalogue = observation.get('fixed_catalogue')
    tiers = {tier['purchase_k']: tier for tier in curve['tiers']}
    if catalogue != list(tiers) or len(anchors) < 2:
        return []
    measured_rules = {_fixed_rule(tiers[line['purchase_k']]) for line in anchors}
    if measured_rules != {_fixed_rule(tier) for tier in tiers.values()}:
        return []
    goods = observation['source_sha256']['goods']
    if not REF.fullmatch(goods):
        return []
    version = observation['native_quote_revision']
    key = observation['curve_key']
    identity = curve['identity']
    measured = {line['purchase_k'] for line in anchors}
    ref = fingerprint(dict(goods=goods, curve=key, anchors=sorted(line['quote_ref'] for line in anchors)))
    lines = []
    for quantity in catalogue:
        if quantity not in requested or quantity in measured:
            continue
        quote = quote_native(curve, dict(purchase_k=quantity, multiplier=1, site_id=SITE_MAIN, currency='USD'))
        amount = format(Decimal(quote['regular_usd']), '.2f')
        lines.append(dict(purchase_k=quantity, gift_k=quote['promised_bonus_k'], multiplier=1,
                          promised_delivered_k=quote['promised_delivered_k'], regular_usd=amount,
                          net_goods_usd=amount, net_receipt_usd=amount, path_id='catalogue:' + quantity,
                          site_id=SITE_MAIN, goods_id=identity['id'], aid=identity['aid'], region_id='0',
                          currency='USD', amount_kind='TOTAL', curve_key=key, offer_path=GUEST,
                          native_tier_or_rule=quote['native_tier_or_rule'], offer_version=version,
                          rounding_contract=CATALOGUE_CENTS, proof_status='verified',
                          fulfilment_contract='native_cart_purchase_and_free_num_only_v1',
                          quote_basis=FIXED_CATALOGUE, fulfilment_ref=ref, eligibility_ref=ref,
                          quote_ref=fingerprint(dict(catalogue=ref, quantity=quantity, amount=amount))))
    return lines


def collect_anonymous_observations(evidence, primary_curves, requested_quantities, *, as_of, live=False):
    """Reuse the frozen run attachment or collect bounded isolated guest-cart evidence."""
    attachment = evidence.get('native_checkout_observations')
    run_id = evidence['run_id']
    if attachment is None:
        if not live:
            return {}
        platforms = _collect_with_tls_runtime(run_id, primary_curves, requested_quantities)
        attachment = dict(run_id=run_id, platforms=platforms)
        as_of = datetime.now(timezone.utc)
    if not isinstance(attachment, dict) or attachment.get('run_id') != run_id:
        return {}
    cutoff = instant(evidence['checked_at'])
    platforms = attachment.get('platforms')
    if not isinstance(platforms, dict):
        return {}
    result = {}
    for platform, curve in primary_curves.items():
        observation = platforms.get(platform)
        if not observation:
            continue
        try:
            _main_curve(curve, platform)
            key = curve_key(curve)
            stamp = instant(observation['captured_at'])
            if (observation['contract'] != CONTRACT or observation['run_id'] != run_id
                    or observation['platform'] != platform or observation['site_id'] != SITE_MAIN
                    or observation['curve_key'] != key or not cutoff - MAX_AGE <= stamp <= as_of
                    or as_of - stamp > MAX_AGE):
                continue
            requested = set(requested_quantities[platform])
            anchors = [line for line in observation['lines'] if _bound_line(line, curve, key)]
            lines = [line for line in anchors if line['purchase_k'] in requested]
            lines.extend(_fixed_catalogue_lines(curve, observation, anchors, requested))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if len({line['purchase_k'] for line in lines}) != len(lines):
            continue
        if lines or observation.get('status') == 'partial':
            coverage = list(observation['coverage_gaps'])
            if {line['purchase_k'] for line in lines} == {tier['purchase_k'] for tier in curve['tiers']}:
                coverage = [gap for gap in coverage if gap != 'anonymous_guest_quantities_only']
                if 'custom_quantities_unverified' not in coverage:
                    coverage.append('custom_quantities_unverified')
            result[platform] = dict(observation, lines=lines, coverage_gaps=coverage)
    return result


def project_anonymous_fixed_tiers(current_curve, target_curve, observation):
    """Apply a saved native-cent rule to observed fixed guest tiers of an editor candidate."""
    if not observation:
        return {}
    identity = current_curve['identity']
    target_identity = target_curve['identity']
    if (observation.get('curve_key') != curve_key(current_curve)
            or observation.get('platform') not in GOODS
            or observation.get('site_id') != SITE_MAIN or identity['site_id'] != SITE_MAIN
            or target_identity['site_id'] not in (SITE_MAIN, '0')
            or any(identity[name] != target_identity[name] for name in ('aid','mid','gid','cid','unit'))
            or target_identity['site_id'] == SITE_MAIN and target_identity['id'] != identity['id']):
        return {}
    key = curve_key(target_curve)
    if key == observation['curve_key']:
        return observation
    is_all = target_identity['site_id'] == '0'
    if is_all:
        platform = observation['platform']
        if target_identity['id'] != GOODS[platform][0]:
            return {}
    elif target_curve.get('compilation_status') != 'EDITOR_CANDIDATE':
        return {}
    contract = target_curve['native_contract']
    if (contract.get('editor_asset_sha256'), contract.get('editor_handler_sha256')) != (
            EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256):
        return {}
    lines = []
    for observed in observation['lines']:
        derived = observed.get('quote_basis') == FIXED_CATALOGUE
        if not _bound_line(observed, current_curve, observation['curve_key'], derived=derived):
            continue
        quote = quote_native(target_curve, dict(purchase_k=observed['purchase_k'], multiplier=1,
                                               site_id=target_identity['site_id'], currency='USD'))
        amount = quote['regular_usd']
        if (amount is None or not USD.fullmatch(amount) or Decimal(amount) <= 0
                or not is_all and quote['catalogue_status'] != 'editor_candidate_tier'
                or quote['promised_delivered_k'] != observed['promised_delivered_k']):
            continue
        rounding = ('admin_editor_tofixed2_and_native_fixed_catalogue_cent_v1' if derived
                    else 'admin_editor_tofixed2_and_observed_native_usd_cart_cent_v1')
        ref = fingerprint(dict(observed_quote=observed['quote_ref'], curve_key=key, amount=amount, rounding=rounding))
        lines.append(dict(observed, curve_key=key, regular_usd=amount, net_goods_usd=amount,
                          net_receipt_usd=amount, quote_basis='derived_candidate_fixed_catalogue' if derived
                          else 'derived_candidate_fixed_tier', quote_ref=ref,
                          native_tier_or_rule=quote['native_tier_or_rule'], rounding_contract=rounding))
    return dict(observation, curve_key=key, lines=lines) if lines or observation.get('status') == 'partial' else {}


if __name__ == '__main__':
    payload = json.load(sys.stdin)
    print(json.dumps(_collect_live(payload['run_id'], payload['primary_curves'], payload['requested_quantities'])))
