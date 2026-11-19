"""Closed-day channel cache; native shared sources and existing locks only."""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from channel_effects import TZ, EMPTY_COST, delivery_index

ROOT = Path('/var/lib/fs-channel-effects')
CONTRACT = 'channel-day-v1'


def atomic(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, allow_nan=False)
            output.flush(); os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def days(period):
    start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    while start <= end:
        yield start.isoformat()
        start += timedelta(days=1)


def store_days(data, root=ROOT):
    import fcntl
    if any(data['sources'][name]['status'] != 'complete' for name in ('orders', 'coupons')):
        raise ValueError('complete_order_and_coupon_sources_required')
    if len({r['orderNo'] for r in data['orders']}) != len(data['orders']):
        raise ValueError('duplicate_archived_order')
    if any(not data['period']['start'] <= r['day'] <= data['period']['end'] for r in data['orders']):
        raise ValueError('archived_order_out_of_range')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / 'archive.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for day in days(data['period']):
            if day >= datetime.now(TZ).date().isoformat(): continue
            path = root / 'days' / (day + '.json')
            previous = json.loads(path.read_text('utf-8')) if path.is_file() else None
            if previous and previous['generatedAt'] > data['generatedAt']: continue
            rows = [r for r in data['orders'] if r['day'] == day]
            sources = dict(data['sources'])
            sources['orders'] = dict(sources['orders'], rows=len(rows))
            sources['coupons'] = dict(sources['coupons'], rows=sum(len(r['coupons']) for r in rows))
            atomic(path, dict(data, contract=CONTRACT, period=dict(start=day, end=day), sources=sources, orders=rows))


def compose(period, root=ROOT):
    captures = []
    for day in days(period):
        path = root / 'days' / (day + '.json')
        if not path.is_file(): return None
        value = json.loads(path.read_text('utf-8'))
        if value.get('contract') != CONTRACT or value['period'] != dict(start=day, end=day):
            raise ValueError('invalid_day_cache')
        if any(value['sources'][name]['status'] != 'complete' for name in ('orders', 'coupons')):
            raise ValueError('incomplete_day_cache')
        if any(r['day'] != day for r in value['orders']): raise ValueError('day_cache_range_mismatch')
        cost_path = root / 'delivery-days' / (day + '.json')
        if cost_path.is_file():
            cost = json.loads(cost_path.read_text('utf-8'))
            if cost.get('contract') != 'channel-order-deliveries-v1' or cost.get('complete') is not True or cost.get('period') != value['period']:
                raise ValueError('invalid_delivery_day_cache')
            value['sources']['cost'] = dict(value['sources'].get('cost', {}), status='complete', generatedAt=cost['generatedAt'],
                source='Order完整分页日归档', coverage=dict(contract=cost['contract'], period=cost['period'], deliveryRows=len(cost['rows'])))
        captures.append(value)
    if not captures: return None
    if any(v['mapping'] != captures[0]['mapping'] for v in captures): return None
    rows = [r for value in captures for r in value['orders']]
    if len({r['orderNo'] for r in rows}) != len(rows): raise ValueError('duplicate_day_cache_order')
    oldest = min(v['generatedAt'] for v in captures)
    sources = dict(captures[-1]['sources'])
    sources['orders'] = dict(sources['orders'], rows=len(rows))
    sources['coupons'] = dict(sources['coupons'], rows=sum(len(r['coupons']) for r in rows))
    costs = [v['sources'].get('cost', {}) for v in captures]
    complete_costs = [c for c in costs if c.get('status') == 'complete']
    sources['cost'] = dict(sources.get('cost', {}), status='complete' if len(complete_costs) == len(costs) else 'partial' if complete_costs else 'unavailable',
        generatedAt=min((c['generatedAt'] for c in complete_costs), key=lambda s: datetime.fromisoformat(s).timestamp()) if complete_costs else None,
        coverage=dict(days=len(costs), completeDays=len(complete_costs), period=period))
    sources['cache'] = dict(source='已校验的逐日归档', days=len(captures), oldest=oldest,
                            newest=max(v['generatedAt'] for v in captures),
                            deliveryDayComplete=all(v.get('deliveryDayComplete') for v in captures),
                            customerDayComplete=all(v['sources'].get('customer',{}).get('status')=='complete' for v in captures),
                            limitation='按原采集时点保存；完整历史日直接复用，缺口继续补齐，需要重新核验时可手动刷新。')
    return dict(captures[-1], period=period, generatedAt=oldest, orders=rows, sources=sources)


def delivery_records(signature):
    rows, captures, removed, retired = {}, [], set(), set()
    for name, mtime, size, inode in signature:
        value = json.loads(Path(name).read_text('utf-8'))
        if value.get('contract') != 'channel-order-deliveries-v1' or value.get('complete') is not True:
            raise ValueError('invalid_delivery_day_cache')
        if value.get('scope') == 'exact_orders' and any(r['sn'] not in value['orderNos'] for r in value['rows']):
            raise ValueError('supplement_order_scope_mismatch')
        if len({str(r['delivery_id']) for r in value['rows']}) != len(value['rows']):
            raise ValueError('duplicate_delivery_cache_record')
        captures.append(value)
    captures.sort(key=lambda v: datetime.fromisoformat(v['generatedAt']).timestamp())
    for value in captures:
        period = value.get('period')
        if value.get('scope') == 'exact_orders' or period:
            begin, stop = delivery_bounds(period) if period else (None, None)
            for identity, previous in list(rows.items()):
                covered = previous['sn'] in value['orderNos'] if value.get('scope') == 'exact_orders' else begin <= previous['trade_at'] <= stop
                if covered:
                    removed.add(previous['sn'])
                    retired.add(identity)
                    del rows[identity]
        for row in value['rows']:
            identity = str(row['delivery_id'])
            # Retained rows outside a refreshed window have no new source evidence.
            if period and not begin <= row['trade_at'] <= stop and (identity in retired or identity in rows):
                continue
            rows[identity] = row
    return tuple(rows.values()), captures[-1]['generatedAt'] if captures else None, removed


@lru_cache(maxsize=2)
def cost_index(signature):
    rows, stamp, removed = delivery_records(signature)
    return delivery_index(rows), stamp, removed


def delivery_bounds(period):
    begin = period.get('since', period['start'] + ' 00:00:00')
    stop = period.get('until', period['end'] + ' 23:59:59')
    if len(begin) == 16: begin += ':00'
    if len(stop) == 16: stop += ':59'
    datetime.strptime(begin, '%Y-%m-%d %H:%M:%S')
    datetime.strptime(stop, '%Y-%m-%d %H:%M:%S')
    if not period['start'] + ' 00:00:00' <= begin <= stop <= period['end'] + ' 23:59:59':
        raise ValueError('invalid_delivery_window')
    return begin, stop


def apply_delivery_cache(data, root=ROOT):
    paths = sorted((root / 'delivery-days').glob('*.json'))
    if (root / 'order-deliveries.json').is_file(): paths.append(root / 'order-deliveries.json')
    if (root / 'order-supplements.json').is_file(): paths.append(root / 'order-supplements.json')
    if not paths: return data
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_ino) for p in paths)
    index, stamp, removed = cost_index(signature)
    for row in data['orders']:
        if row['orderNo'] in index: row.update(index[row['orderNo']])
        elif row['orderNo'] in removed: row.update(EMPTY_COST)
    data['sources']['cost'] = dict(data['sources']['cost'], generatedAt=stamp,
        source='Order完整分页日归档 / 原全局缓存 / 逐单补核',
        limitation='按发货记录关联，已完成未匹配保持未知；NBA2K、ARC部分订单由SCM履约，当前Order源不含其成本。')
    return data


def collect_period(period, root=ROOT, force=False):
    """Reuse fixed historical facts and collect missing contiguous days only."""
    from channel_source import collect
    from copy import deepcopy
    requested = list(days(period))
    known = {day: compose(dict(start=day, end=day), root) for day in requested}
    from channel_effects import final_order_statuses
    known = {day: value if value is not None and all('adminSaleCny' in r for r in value['orders']) and final_order_statuses(value) else None
             for day, value in known.items()}
    missing = [day for day in requested if known[day] is None]
    if force or len(missing) == len(requested): return collect(period)
    if not missing:
        value=compose(period,root)
        return value if value['sources']['cache']['customerDayComplete'] and final_order_statuses(value) else collect(period)
    chunks = []
    for day in missing:
        if chunks and (date.fromisoformat(day)-date.fromisoformat(chunks[-1]['end'])).days == 1:
            chunks[-1]['end'] = day
        else: chunks.append(dict(start=day, end=day))
    parts = [value for value in known.values() if value is not None]
    for chunk in chunks:
        value = collect(chunk)
        store_days(value, root)
        parts.append(value)
    if any(value['mapping'] != parts[-1]['mapping'] for value in parts): return collect(period)
    result = deepcopy(parts[-1])
    result['period'] = period
    result['orders'] = [row for value in parts for row in value['orders']]
    if len({r['orderNo'] for r in result['orders']}) != len(result['orders']): raise ValueError('duplicate_composed_order')
    result['generatedAt'] = min(value['generatedAt'] for value in parts)
    result['sources']['orders']['rows'] = len(result['orders'])
    result['sources']['coupons']['rows'] = sum(len(row['coupons']) for row in result['orders'])
    result['sources']['cache'] = dict(source='完整日归档与缺日完整读取', days=len(requested)-len(missing),
        oldest=result['generatedAt'], newest=max(value['generatedAt'] for value in parts),
        limitation='只补缺少的连续日期；各源原时间保留，缺日全部校验后才返回完整区间。')
    return result


def cache_day(day, root=ROOT, *, shared=False, recheck=False):
    import fcntl
    from order_delivery_index import sync, sync_after_publish

    if date.fromisoformat(day).isoformat()!=day or day>=datetime.now(TZ).date().isoformat():
        raise ValueError('closed_day_required')
    period = dict(start=day, end=day)
    if not shared:
        from channel_source import collect
        with (root / 'collector.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = compose(period, root)
            if data is None or data['sources']['customer']['status'] != 'complete' or any('adminSaleCny' not in r for r in data['orders']):
                data = collect(period)
                store_days(data, root)
    path = root / 'delivery-days' / (day + '.json')
    if recheck or not path.exists():
        from channel_cost_source import collect as collect_cost
        sys.path.insert(0, '/opt/sales-dashboard/collector'); import p2pah_auth as auth
        with (root / 'order-deliveries.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if recheck or not path.exists():
                if recheck and path.is_file():
                    sync(root)
                session = auth.Session()
                try:
                    rows = collect_cost(session, day, day)
                finally: session.close()
                atomic(path, dict(contract='channel-order-deliveries-v1', complete=True,
                    generatedAt=datetime.now(TZ).isoformat(), period=period, rows=rows))
    index_revision = sync_after_publish(root)
    if shared:
        cost = json.loads(path.read_text('utf-8'))
        if cost.get('contract')!='channel-order-deliveries-v1' or cost.get('complete') is not True or cost.get('period')!=period:
            raise ValueError('invalid_delivery_day_cache')
        from shared_es_facts import read
        try:
            value = read(dict(period,site_id='266',gid='all'))
            orders = len(value['rows']) if value['coverage']['admin_complete'] else None
            missing = value['coverage']['missing_days']
        except (OSError,sqlite3.Error):
            orders, missing = None, [day]
        return dict(day=day,orders=orders,status='complete' if orders is not None else 'partial',
                    missingDays=missing,deliveryDayComplete=True,
                    deliveryIndexRevision=index_revision,deliveryIndexStatus='complete' if index_revision else 'pending')
    # Complete pagination means source coverage, not that every order has a cost.
    result = compose(period, root)
    result['deliveryDayComplete'] = True
    atomic(root / 'days' / (day + '.json'), result)
    return dict(day=day, orders=len(data['orders']), customer=data['sources']['customer']['status'],
                status='complete' if data['sources']['customer']['status'] == 'complete' else 'partial')


def rotation_day(days_to_check, root, now):
    """Recheck at most one prior closed day during the existing nightly backfill."""
    older = []
    for day in days_to_check:
        path = root/'delivery-days'/f'{day}.json'
        if not path.is_file():
            return None
        modified = datetime.fromtimestamp(path.stat().st_mtime,TZ)
        # File replacement schedules the next revisit. Its mtime is not source coverage evidence.
        if modified.date() >= now.date():
            return None
        older.append((modified,day))
    return min(older)[1] if older else None


def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument('--backfill', action='store_true')
    parser.add_argument('--day')
    parser.add_argument('--recheck', action='store_true')
    args = parser.parse_args()
    if args.recheck and (args.backfill or not args.day):
        parser.error('--recheck requires one explicit --day')
    now = datetime.now(TZ)
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    target = args.day or yesterday
    if not args.backfill and (date.fromisoformat(target).isoformat()!=target or target>yesterday):
        raise ValueError('closed_day_required')
    if args.backfill and not 1 <= now.hour < 7: return
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = 'backfill' if args.backfill else 'daily'
    with (ROOT / 'schedule.lock').open('a+b') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: print('{"status":"deferred","reason":"scheduled_job_running"}'); return
        from daily_archive import cutoff
        period = dict(start=max('2026-09-01',cutoff(now.date()).isoformat()), end=yesterday)
        queue = list(reversed(list(days(period)))) if args.backfill else list(dict.fromkeys((yesterday,target)))
        historical = rotation_day(queue[1:],ROOT,now) if args.backfill else None
        for day in queue:
            recheck = day==historical or args.recheck and day==target
            if not date.fromisoformat(day) < now.date(): raise ValueError('closed_day_required')
            if args.backfill:
                if datetime.now(TZ).hour >= 7: break
                if day != yesterday and not recheck and (ROOT/'delivery-days'/(day+'.json')).is_file():continue
            try: result = cache_day(day,shared=True,recheck=recheck)
            except BlockingIOError:
                result = dict(day=day, status='deferred', reason='foreground_source_read_active')
                atomic(ROOT / (mode + '-status.json'), dict(result, at=datetime.now(TZ).isoformat()))
                print(json.dumps(result), flush=True)
                if not args.backfill: raise SystemExit(75)
                return
            except Exception as error:
                result = dict(day=day, status='failed', error=type(error).__name__)
                atomic(ROOT / (mode + '-status.json'), dict(result, at=datetime.now(TZ).isoformat()))
                print(json.dumps(result), flush=True); raise
            if recheck:
                result['recheck'] = True
            atomic(ROOT / (mode + '-status.json'), dict(result, at=datetime.now(TZ).isoformat()))
            print(json.dumps(result), flush=True)
            if not result.get('deliveryIndexRevision'):
                if not args.backfill: raise SystemExit(75)
                return
            if not args.backfill and day==target: return
            time.sleep(2)


if __name__ == '__main__': main()
