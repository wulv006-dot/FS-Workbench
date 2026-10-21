"""Closed-day channel cache; native shared sources and existing locks only."""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from channel_effects import TZ, delivery_index

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
        captures.append(value)
    if not captures: return None
    if any(v['mapping'] != captures[0]['mapping'] for v in captures): return None
    rows = [r for value in captures for r in value['orders']]
    if len({r['orderNo'] for r in rows}) != len(rows): raise ValueError('duplicate_day_cache_order')
    oldest = min(v['generatedAt'] for v in captures)
    sources = dict(captures[-1]['sources'])
    sources['orders'] = dict(sources['orders'], rows=len(rows))
    sources['coupons'] = dict(sources['coupons'], rows=sum(len(r['coupons']) for r in rows))
    sources['cache'] = dict(source='已校验的逐日归档', days=len(captures), oldest=oldest,
                            newest=max(v['generatedAt'] for v in captures),
                            deliveryDayComplete=all(v.get('deliveryDayComplete') for v in captures),
                            limitation='按采集时点保存；十分钟过期后后台自动刷新，需立即核验后续退款、状态和归因变化可手动刷新。')
    return dict(captures[-1], period=period, generatedAt=oldest, orders=rows, sources=sources)


@lru_cache(maxsize=2)
def cost_index(signature):
    rows, stamps = {}, []
    for name, mtime, size, inode in signature:
        value = json.loads(Path(name).read_text('utf-8'))
        if value.get('contract') != 'channel-order-deliveries-v1' or value.get('complete') is not True:
            raise ValueError('invalid_delivery_day_cache')
        if value.get('scope') == 'exact_orders' and any(r['sn'] not in value['orderNos'] for r in value['rows']):
            raise ValueError('supplement_order_scope_mismatch')
        if len({str(r['delivery_id']) for r in value['rows']}) != len(value['rows']):
            raise ValueError('duplicate_delivery_cache_record')
        stamps.append(value['generatedAt'])
        for row in value['rows']:
            previous = rows.get(str(row['delivery_id']))
            if previous is None or value['generatedAt'] > previous[0]:
                rows[str(row['delivery_id'])] = (value['generatedAt'], row)
    return delivery_index([r for stamp, r in rows.values()]), max(stamps, default=None)


def apply_delivery_cache(data, root=ROOT):
    paths = sorted((root / 'delivery-days').glob('*.json'))
    if (root / 'order-deliveries.json').is_file(): paths.append(root / 'order-deliveries.json')
    if (root / 'order-supplements.json').is_file(): paths.append(root / 'order-supplements.json')
    if not paths: return data
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_ino) for p in paths)
    index, stamp = cost_index(signature)
    for row in data['orders']:
        if row['orderNo'] in index: row.update(index[row['orderNo']])
    data['sources']['cost'] = dict(data['sources']['cost'], generatedAt=stamp,
        source='Order完整分页日归档 / 原全局缓存 / 逐单补核',
        limitation='按发货记录关联，已完成未匹配保持未知；NBA2K、ARC部分订单由SCM履约，当前Order源不含其成本。')
    return data


def cache_day(day, root=ROOT):
    import fcntl
    from channel_source import collect
    from channel_cost_source import collect as collect_cost
    sys.path.insert(0, '/opt/sales-dashboard/collector'); import p2pah_auth as auth
    period = dict(start=day, end=day)
    with (root / 'collector.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = collect(period)
        store_days(data, root)
    path = root / 'delivery-days' / (day + '.json')
    if not path.exists():
        with (root / 'order-deliveries.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            session = auth.Session()
            try:
                rows = collect_cost(session, day, day)
            finally: session.close()
            atomic(path, dict(contract='channel-order-deliveries-v1', complete=True,
                generatedAt=datetime.now(TZ).isoformat(), period=period, rows=rows))
    # Complete pagination means source coverage, not that every order has a cost.
    result = compose(period, root)
    result['deliveryDayComplete'] = True
    atomic(root / 'days' / (day + '.json'), result)
    return dict(day=day, orders=len(data['orders']), customer=data['sources']['customer']['status'],
                status='complete' if data['sources']['customer']['status'] == 'complete' else 'partial')


def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument('--backfill', action='store_true')
    parser.add_argument('--day')
    args = parser.parse_args()
    now = datetime.now(TZ)
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    if args.backfill and not 1 <= now.hour < 7: return
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = 'backfill' if args.backfill else 'daily'
    with (ROOT / 'schedule.lock').open('a+b') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: print('{"status":"deferred","reason":"scheduled_job_running"}'); return
        period = dict(start='2026-08-01', end=min(yesterday, '2026-10-31'))
        queue = list(reversed(list(days(period)))) if args.backfill else [args.day or yesterday]
        for day in queue:
            if not date.fromisoformat(day) < now.date(): raise ValueError('closed_day_required')
            if args.backfill:
                if datetime.now(TZ).hour >= 7: break
                cached = compose(dict(start=day, end=day))
                if cached and cached['sources']['cache'].get('deliveryDayComplete') and cached['sources']['customer']['status'] == 'complete': continue
            try: result = cache_day(day)
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
            atomic(ROOT / (mode + '-status.json'), dict(result, at=datetime.now(TZ).isoformat()))
            print(json.dumps(result), flush=True)
            if result['status'] != 'complete': raise SystemExit(75)
            if not args.backfill: return
            time.sleep(2)


if __name__ == '__main__': main()
