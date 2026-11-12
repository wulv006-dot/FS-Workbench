"""One same-run Lootbar fallback, only after a proven pre-egress CDP failure."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from .contracts import decimal, fingerprint, instant, fresh

VERSION = 'lootbar-public-browser-v1'
REQUEST_BUDGET = 128  # One conservatively reserved group; the browser enforces this ceiling.
ROUTING = Path('/var/lib/fc27-cloud/collection-access/lootbar-routing.json')
BLOCKERS = {'http_401', 'http_403', 'http_429', 'challenge', 'captcha'}


def source_policy(generation):
    """Explicit reviewable source recipe; this function never changes live state."""
    if type(generation) is not int or generation < 1:
        raise ValueError('lootbar_generation_invalid')
    return dict(origin='https://www.lootbar.com', nodes=['183'], mode='consume', generation=generation,
        adapter_version=VERSION, policy_version='lootbar-pre-egress-fallback-v1', lease_seconds=100,
        request_timeout_seconds=90, clock_margin_seconds=2, stable_seconds=5, window_seconds=60,
        max_requests=REQUEST_BUDGET, concurrency=1, retry_after_seconds=60)


def eligible_trigger(events):
    # The existing reader emits this exact two-event trace before it has a page.
    return (isinstance(events, list) and len(events) == 2
            and all(isinstance(e, dict) for e in events)
            and events[0].get('stage') == 'cdp_connecting'
            and events[1].get('stage') == 'failed'
            and events[1].get('reason') == 'browser_connection_timeout'
            and not any(e.get('offers') or e.get('platform') for e in events))


def cents(value, *, zero=False):
    amount = decimal(value, zero)
    if amount * 100 != (amount * 100).to_integral_value():
        raise ValueError('lootbar_cent_precision_required')
    return int(amount * 100)


def reconstruct_price(raw):
    coupon = raw.get('couponState')
    if coupon == 'none':
        if raw.get('observedCouponPrice') is not None or raw.get('excludedCouponDiscount') is not None:
            raise ValueError('lootbar_coupon_conflict')
        gross = cents(raw.get('usdPrice'))
        return Decimal(gross)/100, dict(method='direct_no_coupon', exact=True, precision='USD_cent')
    if coupon == 'excluded':
        gross, paid, discount = (cents(raw.get(k)) for k in ('usdPrice','observedCouponPrice','excludedCouponDiscount'))
        if gross-paid != discount:
            raise ValueError('lootbar_coupon_arithmetic_invalid')
        observed = raw.get('reconstruction')
        if observed is not None:
            if (not isinstance(observed, dict) or set(observed) != {'method','exact','precision','paid_usd','discount_usd'}
                    or observed['method'] not in ('direct_strike','derived_actual_discount')
                    or observed['exact'] is not True or observed['precision'] != 'USD_cent'
                    or cents(observed['paid_usd']) != paid or cents(observed['discount_usd']) != discount):
                raise ValueError('lootbar_reconstruction_conflict')
            return Decimal(gross)/100, dict(observed)
        return Decimal(gross)/100, dict(method='direct_strike', exact=True, precision='USD_cent',
            paid_usd=str(Decimal(paid)/100), discount_usd=str(Decimal(discount)/100))
    if coupon not in ('original_missing','discount_missing'):
        raise ValueError('lootbar_coupon_conflict')
    terms = raw.get('couponEvidence')
    if not isinstance(terms, dict):
        raise ValueError('lootbar_coupon_unverified')
    paid = cents(terms.get('paid_usd'))
    if terms.get('original_usd') is not None:
        gross = cents(terms['original_usd'])
        if gross <= paid:
            raise ValueError('lootbar_original_price_invalid')
        return Decimal(gross)/100, dict(method='direct_strike', exact=True, precision='USD_cent',
            paid_usd=terms['paid_usd'], discount_usd=str(Decimal(gross-paid)/100))
    if terms.get('actual_discount_usd') is not None:
        if set(terms) != {'paid_usd','actual_discount_usd','actual_discount_verified'} or terms['actual_discount_verified'] is not True:
            raise ValueError('lootbar_actual_discount_unverified')
        discount = cents(terms['actual_discount_usd'])
        return Decimal(paid+discount)/100, dict(method='derived_actual_discount', exact=True, precision='USD_cent',
            paid_usd=terms['paid_usd'], discount_usd=terms['actual_discount_usd'])
    required = {'paid_usd','percent_off','cap_usd','cap_verified','minimum_spend_usd','eligibility_verified','rounding'}
    if (set(terms) != required or terms['cap_verified'] is not True or terms['eligibility_verified'] is not True
            or terms['rounding'] not in ('half_up_cent','floor_cent','ceiling_cent')):
        raise ValueError('lootbar_coupon_conditions_unverified')
    rate = decimal(terms['percent_off'])/100
    if not 0 < rate < 1:
        raise ValueError('lootbar_coupon_percent_invalid')
    cap = None if terms['cap_usd'] is None else cents(terms['cap_usd'])
    minimum = cents(terms['minimum_spend_usd'], zero=True)
    rounding = {'half_up_cent':ROUND_HALF_UP,'floor_cent':ROUND_FLOOR,'ceiling_cent':ROUND_CEILING}[terms['rounding']]
    # Enumerate the small cent interval around the exact inverse, plus the cap branch.
    low = max(paid, int((Decimal(paid)-1)/(1-rate))-2)
    high = int((Decimal(paid)+1)/(1-rate))+3
    if high-low > 20000:
        raise ValueError('lootbar_coupon_inverse_too_ambiguous')
    candidates = set(range(low, high+1))
    if cap is not None:
        candidates.add(paid+cap)
    valid = []
    for gross in sorted(candidates):
        discount = int((Decimal(gross)*rate).to_integral_value(rounding=rounding))
        if cap is not None:
            discount = min(discount, cap)
        if gross >= minimum and gross-discount == paid:
            valid.append(gross)
    if not valid:
        raise ValueError('lootbar_coupon_inverse_no_solution')
    money = lambda value: format(Decimal(value)/100, '.2f')
    return Decimal(valid[0])/100, dict(method='derived_percent', exact=len(valid)==1,
        precision='USD_cent', gross_interval_usd=[money(valid[0]),money(valid[-1])],
        anchor_basis='conservative_interval_lower_bound', raw_terms=dict(terms),
        cap_applied=cap is not None and valid[0]-paid == cap)


def snapshot_offer(raw, platform, now):
    label = {'PS':'PS4/5', 'XBOX':'Xbox', 'PC':'PC'}[platform]
    if (not isinstance(raw, dict) or raw.get('selected') != [label]
            or type(raw.get('loggedIn')) is not bool or raw.get('currencyState') != 'ready'
            or raw.get('tierState') != 'ready' or str(raw.get('baseK')) != '100'
            or raw.get('priceState') != 'ready' or raw.get('giftState') != 'ready'
            or type(raw.get('stable_reads')) is not int or raw['stable_reads'] < 3):
        raise ValueError('lootbar_selection_unverified')
    price, reconstruction = reconstruct_price(raw)
    observed = instant(raw.get('observed_at'))
    fresh(observed, now)
    bonus = decimal(raw.get('bonusK'), True)
    if price * 100 != (price * 100).to_integral_value():
        raise ValueError('lootbar_price_invalid')
    coupon = raw.get('couponState')
    meta = dict(coupon_state=coupon, raw_coupon_excluded=coupon == 'excluded',
        logged_in=raw['loggedIn'], observed_coupon_price=raw.get('observedCouponPrice'),
        excluded_coupon_discount=raw.get('excludedCouponDiscount'), stable_reads=raw['stable_reads'],
        raw_usd_price=raw.get('usdPrice'), coupon_evidence=raw.get('couponEvidence'),
        parser_reconstruction=raw.get('reconstruction'), reconstruction=reconstruction)
    return dict(platform=platform, region_id=0, currency='USD', settlement_currency='USD',
        conversion_source='not_required', purchase_quantity='100', bonus_quantity=str(bonus),
        delivered_quantity=str(Decimal(100)+bonus), quantity_unit='K', amount=format(price,'.2f'),
        price_basis='reconstructed_no_coupon_lower_bound' if reconstruction['method']=='derived_percent' else 'visible_public_sale_price', delivery_method='standard',
        discount_source='visible_no_coupon' if coupon == 'none' else 'visible_coupon_excluded',
        coupon_excluded=True, auth_state='logged_in' if raw['loggedIn'] else 'public',
        conditional=False, comparable=True, observed_at=observed.isoformat(),
        selection_verified=True, sanitized_evidence_ref='sha256:'+fingerprint(raw), source_metadata=meta)


def lootbar_adapter(task, transport):
    from .adapters import SourceUnavailable
    if task['region_scope'] != [0] or task['total_request_budget'] != REQUEST_BUDGET:
        raise ValueError('lootbar_task_scope_invalid')
    payload = json.loads(transport.get('lootbar_capture', count=REQUEST_BUDGET))
    if not isinstance(payload, dict) or set(payload)-{'browser_requests_allowed'} != {'snapshots', 'platform_errors'}:
        raise ValueError('lootbar_renderer_reply_invalid')
    snapshots, errors = payload['snapshots'], payload['platform_errors']
    if (not isinstance(snapshots, dict) or not isinstance(errors, dict)
            or set(snapshots) & set(errors) or set(snapshots) | set(errors) != set(task['requested_platforms'])):
        raise ValueError('lootbar_platform_coverage_invalid')
    rows = []
    for platform in task['requested_platforms']:
        if platform not in snapshots:
            continue
        try:
            rows.append(snapshot_offer(snapshots[platform], platform, transport.clock()))
        except ValueError:
            errors[platform] = 'lootbar_quote_unverified'
    reason = next((v for v in errors.values() if v in BLOCKERS), next(iter(errors.values()), None))
    return dict(status='partial' if rows and errors else 'ok' if rows else 'blocked' if reason in BLOCKERS else 'failed',
        reason_code=reason, offers=rows, evidence_hash=fingerprint(payload),
        request_accounting=dict(basis='reserved_browser_group', charged=transport.used,
            browser_requests_allowed=payload.get('browser_requests_allowed')),
        **(dict(platform_errors=errors) if errors else {}))


def render_fetch(task, template, timeout):
    from .adapters import SourceUnavailable
    if template != 'lootbar_capture' or task['source_id'] != 'Lootbar':
        raise ValueError('lootbar_template_invalid')
    body = dict(platforms=task['requested_platforms'], request_limit=REQUEST_BUDGET,
                timeout_seconds=min(75, max(1, int(timeout)-3)))
    req = Request('http://127.0.0.1:9223/fc27_lootbar', data=json.dumps(body).encode(),
                  headers={'Content-Type':'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read(65537)
    except OSError:
        raise SourceUnavailable('renderer_unavailable') from None
    if len(raw) > 65536:
        raise SourceUnavailable('renderer_reply_too_large')
    value = json.loads(raw)
    if value.get('ok') is not True or not isinstance(value.get('result'), dict):
        raise SourceUnavailable(value.get('reason') if value.get('reason') in ('renderer_busy', 'browser_start_failed') else 'renderer_unavailable')
    return json.dumps(value['result']).encode()


def collect_remote(parent, routing, trigger_sha256):
    from .client import collect_remote as collect
    return collect(parent, routing, source_id='Lootbar', trigger_sha256=trigger_sha256)


def primary_ready():
    from .client import legacy_ready
    return legacy_ready('Lootbar')


def after_primary_failure(run_id, events, created_at):
    if not eligible_trigger(events) or not ROUTING.exists():
        return None
    from .client import read_routing_file
    routing = read_routing_file(ROUTING)
    if routing['remote_result_mode'] != 'consume':
        return None
    now = datetime.now(timezone.utc)
    started = instant(events[0].get('at', created_at))
    fresh(started, now)
    parent = dict(run_id=run_id, created_at=started.isoformat(),
                  deadline_at=min(now+timedelta(seconds=110), started+timedelta(seconds=900)).isoformat())
    return collect_remote(parent, routing, fingerprint(events))


def main():
    import argparse
    import fcntl
    import os
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--trace', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', args.run_id):
        raise ValueError('lootbar_run_invalid')
    lock = Path('/var/lib/fc27-cloud/state/lootbar.lock')
    # fd9 is inherited from the original shell; never reopen or unlock that source lock.
    info, held = lock.stat(), os.fstat(9)
    if (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino):
        raise ValueError('lootbar_source_lock_required')
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
    trace = Path(args.trace)
    if trace.is_symlink() or trace.parent != Path('/var/lib/fc27-cloud/evidence') or not trace.name.startswith('lootbar-') or trace.stat().st_size > 1048576:
        raise ValueError('lootbar_trace_invalid')
    raw = trace.read_bytes()
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    # The original trace timestamp is stable across CLI recovery; never age it forward.
    created_at = instant(events[0]['at'])
    result = after_primary_failure(args.run_id, events, created_at)
    if not result or not result.get('offers'):
        raise ValueError('lootbar_fallback_unavailable')
    if result.get('run_id') != args.run_id:
        raise ValueError('lootbar_original_run_mismatch')
    print(json.dumps(dict(stage='remote_complete', read_only=True, node_id='183',
        trigger_sha256=fingerprint(events), source_receipt_verified=True, **result), ensure_ascii=True))
