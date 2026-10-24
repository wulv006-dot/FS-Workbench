"""One controlled read of a closed delivery period, using Order8768 only.

Run after the shared Order source is repaired. Failed/inconsistent pages preserve
the last complete cache; no login, retry of credentials, timer or business write.
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from channel_effects import TZ


def delivery_timestamp(value):
    parts = value.split('改')
    if len(parts) > 2: raise ValueError('delivery_date_format_changed')
    parsed = []
    for part in parts:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%y-%m-%d %H:%M:%S'):
            try: parsed.append(datetime.strptime(part.strip(), fmt).strftime('%Y-%m-%d %H:%M:%S')); break
            except ValueError: pass
        else: raise ValueError('delivery_date_format_changed')
    return parsed[0]


def collect(session, start, end, progress=lambda page, total: None, until=None, since=None, source='www.mmoexp.com', gid='0'):
    from lxml import html
    if not isinstance(source,str) or source and not __import__('re').fullmatch(r'www\.[a-z0-9.-]+',source) or not str(gid).isdigit():
        raise ValueError('invalid_delivery_scope')
    result, seen, page_count = [], set(), None
    page = 1
    headers = ('', 'delivery_id', 'genre_text', 'source', 'sn', 'trade_at', 'game', 'qty', 'gift', 'cost_unit', 'cost_total', 'sale_total', 'margin_pct', 'supplier', 'payee', 'operator', 'note', 'settle_status', 'action')
    begin, stop = since or start + ' 00:00:00', until or end + ' 23:59:59'
    if len(begin) == 16: begin += ':00'
    if len(stop) == 16: stop += ':59'
    datetime.strptime(begin, '%Y-%m-%d %H:%M:%S'); datetime.strptime(stop, '%Y-%m-%d %H:%M:%S')
    if not start + ' 00:00:00' <= begin <= stop <= end + ' 23:59:59':
        raise ValueError('invalid_delivery_window')
    while True:
        status, text = session.get_order('/order/admin_delivery/index.html', gid=str(gid), aid='0', cid='-1', genre='1', status='-1', op_id='0', show_ccy='-1', is_stock='', keyword='', sn='', start=begin, end=stop, page=str(page), **{'source[]': source})
        if status in (301,302,401,403):raise PermissionError('shared_order_denied')
        doc = html.fromstring(text)
        if status != 200 or doc.xpath('//input[@name="password"]'):
            raise ValueError('shared_order_unavailable')
        pages = [int(v) for v in doc.xpath('//*[contains(@class,"pagination")]//a/@href') for v in __import__('re').findall(r'[?&]page=(\d+)', v)]
        total = max(pages + [page])
        if page_count is None: page_count = total
        if total != page_count: raise ValueError('delivery_page_count_changed')
        table = doc.xpath('//table[contains(@class,"table-list")][.//th[normalize-space()="商户订单号"]]')
        if len(table) != 1: raise ValueError('delivery_table_missing')
        rows = table[0].xpath('.//tbody/tr')
        for tr in rows:
            if tr.xpath('./td[@colspan]'): continue
            cells = [' '.join(td.itertext()).strip() for td in tr.xpath('./td')]
            if len(cells) == 1 and not cells[0].strip(): continue
            if len(cells) != len(headers): raise ValueError('delivery_columns_changed')
            record = dict(zip(headers, cells))
            record['trade_at'] = delivery_timestamp(record['trade_at'])
            did = record['delivery_id']
            if not did.isdigit() or did in seen: raise ValueError('delivery_duplicate_page')
            if not record['source'] or source and record['source'] != source or not begin <= record['trade_at'] <= stop:
                raise ValueError('delivery_filter_not_honored')
            seen.add(did)
            result.append({k: record[k] for k in ('delivery_id', 'source', 'sn', 'trade_at', 'game', 'qty', 'gift', 'cost_unit', 'cost_total', 'sale_total')} | {'genre': 1})
        progress(page, page_count)
        if page == page_count: return result
        if not rows or page >= 2000: raise ValueError('delivery_incomplete_pages')
        page += 1


def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', required=True); parser.add_argument('--end', required=True)
    parser.add_argument('--output', default='/var/lib/fs-channel-effects/order-deliveries.json')
    args = parser.parse_args()
    if not date.fromisoformat(args.start) <= date.fromisoformat(args.end) < datetime.now(TZ).date():
        raise ValueError('closed_period_required')
    output = Path(args.output); output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    sys.path.insert(0, '/opt/sales-dashboard/collector'); import p2pah_auth as auth
    session = auth.Session()
    with output.with_suffix('.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            rows = collect(session, args.start, args.end, lambda p, n: print(json.dumps({'page': p, 'pages': n}), flush=True) if p == 1 or p % 40 == 0 else None)
        finally: session.close()
        data = dict(contract='channel-order-deliveries-v1', complete=True, generatedAt=datetime.now(TZ).isoformat(), period=dict(start=args.start, end=args.end), rows=rows)
        fd, temp = tempfile.mkstemp(dir=output.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f); f.flush(); os.fsync(f.fileno())
            os.replace(temp, output)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        print(json.dumps({'status': 'complete', 'rows': len(rows), 'output': str(output)}))


if __name__ == '__main__': main()
