"""Read existing FC27 collector observations; no collection, price or model calls."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import re

ROOT = Path('/var/lib/fc27-cloud')
PLATFORMS = ('PS', 'XBOX', 'PC')
SOURCES = ('Lootbar', 'IGGM', 'U4GM', 'U7Buy')
# Existing capture contract, not a new pricing or collection policy.
MAX_CAPTURE_SECONDS = 3600
MISSING = ('delivery_method', 'coupon_code', 'coupon_eligibility', 'mandatory_fees_usd', 'offer_expires_at')


def checked_query(args):
    if args != {'profile': 'FC27'}:
        raise ValueError('market_query_fields')


def desktop_token():
    value = Path('/var/lib/fs-hermes-fc/profile/.desktop-management/token').read_text('ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,80}', value):
        raise PermissionError('desktop_identity_unavailable')
    return value


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2000000:
        raise ValueError('market_source_file_invalid')
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('market_source_shape')
    return value, hashlib.sha256(raw).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('source_time_missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('source_time_timezone_missing')
    return parsed


def freshness(value, now):
    try:
        age = (now - timestamp(value)).total_seconds()
        return 'future' if age < -300 else 'stale' if age > MAX_CAPTURE_SECONDS else 'fresh'
    except (TypeError, ValueError):
        return 'unknown'


def number(value, zero=False):
    if isinstance(value, bool):
        raise ValueError('market_number')
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('market_number') from None
    if not out.is_finite() or out < 0 or (not zero and out == 0):
        raise ValueError('market_number')
    return out


def offer(row, now, own=False):
    out = {'platform': row.get('platform'), 'status': 'unusable',
           'complete_comparable_offer': False, 'missing_fields': list(MISSING),
           **{k: None for k in MISSING}}
    try:
        base = number(row.get('base_k') if own else row.get('purchase_k'))
        bonus = number(row.get('bonus_k'), True)
        price = number(row.get('package_usd') if own else row.get('gross_usd'))
        stamp = row.get('checked_at') if own else row.get('captured_at')
        timestamp(stamp)
        urls = {'https://www.lootbar.com/game-coins/fc27', 'https://www.iggm.com/ea-sports-fc/fc-27-coins',
                'https://www.u4gm.com/fc-27/coins', 'https://www.u4gm.com/fc-27/coins?server_code=xbox_one_series',
                'https://www.u4gm.com/fc-27/coins?server_code=pc', 'https://www.u7buy.com/fc27/coins',
                'https://www.mmoexp.com/Fc-27/Coins.html'}
        if base != 100 or row.get('platform') not in PLATFORMS or row.get('currency') != 'USD' or row.get('url') not in urls:
            return out
        out.update(currency='USD', url=row['url'], base_k=str(base), bonus_k=str(bonus),
                   gross_usd=str(price), effective_usd_per_k=str(price/(base+bonus)),
                   captured_at=stamp, freshness=freshness(stamp, now),
                   auth_state='public' if own else row.get('auth_state') if row.get('auth_state') in ('public','logged_in') else 'unknown',
                   coupon_excluded=row.get('coupon_excluded') if type(row.get('coupon_excluded')) is bool else None,
                   conditional=row.get('conditional') if type(row.get('conditional')) is bool else None)
        if row.get('status') in ('valid', 'ok') and out['freshness'] == 'fresh':
            out['status'] = 'available'
    except (ValueError, TypeError):
        pass
    return out


class MarketReader:
    def __init__(self, root=ROOT, clock=None):
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def __call__(self, args):
        checked_query(args)
        now = self.clock()
        base = {'http_status': 200, 'contract': 'fc27-existing-market-readonly-v1', 'profile': 'FC27',
                'game': 'FC27', 'product': 'Game Coins', 'platforms': list(PLATFORMS), 'purchase_k': '100',
                'scope': 'current collector observations, not historical paid-order cohort',
                'captured_at': now.isoformat(), 'business_writes': False, 'collection_triggered': False,
                'can_recommend_price': False, 'offer_completeness': 'partial',
                'fee_scenario': {'rate': '0.05', 'source': 'user instruction 2026-10-15',
                                 'scope': 'analysis only; production policy unchanged', 'fixed_fee_usd': None},
                'limitations': ['Incomplete delivery/coupon/fees/expiry; missing is not zero',
                    'Lootbar may use pre-existing logged-in collection, not an anonymous quote',
                    'Current platform transaction cost is not historical COGS or reference-margin inversion',
                    'BOC CNY/USD only; publication time may be missing',
                    'No G2G/ItemD2R, FC26, 1M, official events or new collection claimed']}
        try:
            paths = list((self.root / 'runs').glob('*.json'))
            if not paths or len(paths) > 10000:
                raise ValueError('market_run_unavailable')
            runs = []
            for path in paths:
                if not re.fullmatch(r'[a-f0-9-]{36}\.json', path.name):
                    continue
                data, sha = read_json(path)
                if data.get('run_id') != path.stem:
                    raise ValueError('market_run_identity')
                runs.append((timestamp(data.get('created_at')), path.name, data, sha))
            _, name, run, sha = max(runs, key=lambda r: (r[0], r[1]))
        except (OSError, ValueError, TypeError):
            return dict(base, status='not_available', reason='market_source_unavailable')
        base.update(collection_run_id=run['run_id'], source_snapshot_id='market_' + sha[:24],
                    run_created_at=run['created_at'], run_sha256=sha, collector_status=run.get('status'),
                    run_freshness=freshness(run['created_at'], now))
        if (not isinstance(run.get('competitors'),list) or not isinstance(run.get('costs'),list) or not isinstance(run.get('fx'),dict) or any(not isinstance(r,dict) for r in run['competitors']+run['costs'])):
            return dict(base,status='not_available',reason='market_source_shape')
        competitors = []
        for source in SOURCES:
            for platform in PLATFORMS:
                rows = [r for r in run.get('competitors', []) if r.get('source') == source and r.get('platform') == platform]
                if len(rows) != 1:
                    competitors.append({'source': source, 'platform': platform, 'status': 'missing', 'reason': 'missing_or_duplicate'})
                    continue
                row = rows[0]
                value = offer(row, now)
                if row.get('run_id') != run['run_id']:
                    value['status'] = 'unusable'
                competitors.append(dict(value, source=source))
        costs = []
        for platform in PLATFORMS:
            rows = [r for r in run.get('costs', []) if r.get('platform') == platform]
            if len(rows) != 1:
                costs.append({'platform': platform, 'status': 'missing', 'reason': 'missing_or_duplicate'})
                continue
            row = rows[0]
            cost = {k: row[k] for k in ('platform', 'game', 'product', 'unit', 'cny_per_1k', 'trade_at', 'checked_at', 'delivery_type') if k in row}
            cost.update(source='Order platform transaction', freshness=freshness(row.get('checked_at'), now), status='unusable')
            try:
                number(row.get('cny_per_1k'))
                trade = row.get('trade_at')
                parsed = datetime.strptime(trade, '%y-%m-%d %H:%M:%S') if re.fullmatch(r'\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', str(trade)) else datetime.fromisoformat(trade)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
                age = (now - parsed).total_seconds()
                if (row.get('status') == 'valid' and row.get('game') == 'FC27' and row.get('product') == 'Game Coins'
                    and row.get('genre') == '1' and row.get('delivery_type') == '订单发货' and row.get('unit') == 'CNY/K'
                    and row.get('run_id') == run['run_id'] and cost['freshness'] == 'fresh' and -300 <= age <= 8*86400):
                    cost['status'] = 'available'
            except (ValueError, TypeError):
                pass
            costs.append(cost)
        raw_fx = run.get('fx') or {}
        fx = {k: raw_fx[k] for k in ('cny_per_usd', 'published_at', 'checked_at', 'url') if k in raw_fx}
        fx.update(source='Bank of China', field='BOC conversion rate / 100', direction='CNY per USD',
                  publication_time_status='not_provided', freshness=freshness(raw_fx.get('checked_at'), now), status='unusable')
        try:
            number(fx.get('cny_per_usd'))
            if raw_fx.get('status') == 'valid' and fx['freshness'] == 'fresh':
                fx['status'] = 'available'
        except ValueError:
            pass
        storefront = {'status': 'missing', 'reason': 'same_run_storefront_unavailable', 'rows': []}
        try:
            raw, own_sha = read_json(self.root / 'monitor/storefront.json')
            if raw.get('collection_run_id') == run['run_id'] and raw.get('currency') == 'USD' and raw.get('package_k') == 100:
                own = raw.get('rows') or {}
                rows = [offer(dict(own[p], currency='USD', url='https://www.mmoexp.com/Fc-27/Coins.html'), now, True) for p in PLATFORMS if p in own]
                storefront = {'status': 'available' if len(rows) == 3 and all(r['status'] == 'available' for r in rows) else 'partial',
                              'source': 'MMOEXP main public product', 'collection_run_id': run['run_id'], 'sha256': own_sha, 'rows': rows}
        except (OSError, ValueError, TypeError):
            pass
        base.update(competitors=competitors, costs=costs, fx=fx, storefront=storefront)
        ready = (base['run_freshness'] == 'fresh' and all(r['status'] == 'available' for r in competitors + costs)
                 and fx['status'] == 'available' and storefront['status'] == 'available')
        base.update(status='available' if ready else 'partial',
                    snapshot_policy='latest run by source creation time; no older-success fallback; freeze within task')
        return base
