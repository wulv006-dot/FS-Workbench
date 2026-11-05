"""Persist verified order regions; exact Order lookup only for unresolved orders.

Uses the existing shared session and history database. No login, inferred server
mapping, business order writes, or refresh-time full historical traversal.
"""
import re
import time
import json
from pathlib import Path
from collections import defaultdict
from html.parser import HTMLParser

REGIONS = ('NA East', 'NA West', 'EU', 'Asia', 'SA', 'Korea', 'TW')
_map_path = Path(__file__).with_name('sales_region_areas.json')
_map = json.loads(_map_path.read_text()) if _map_path.exists() else {}
AREA_MAPPING_VERSION = _map.get('version', 'unmapped')
AREA_REGIONS = {}
for _region, _ids in _map.get('groups', {}).items():
    if _region not in REGIONS:
        raise ValueError('invalid configured region')
    for _aid in _ids:
        _key = (str(_map.get('order_gid')), str(_aid))
        if _key in AREA_REGIONS:
            raise ValueError('duplicate configured area')
        AREA_REGIONS[_key] = _region
CN = {'美东': 'NA East', '美西': 'NA West', '欧服': 'EU', '亚服': 'Asia', '南美': 'SA'}
SCHEMA = '''CREATE TABLE IF NOT EXISTS order_regions (
 order_no TEXT PRIMARY KEY, region TEXT NOT NULL, source TEXT NOT NULL,
 area_key TEXT NOT NULL, checked_at REAL NOT NULL, retry_at REAL NOT NULL,
 attempts INTEGER NOT NULL, evidence TEXT NOT NULL)'''


def region_in(text):
    matches = set(re.findall(r'\b(NA East|NA West|Asia|EU|SA|Korea|TW)\b', text or ''))
    for m in re.findall(r'▶\s*([^-（(]+)', text or ''):
        if m.strip() in CN:
            matches.add(CN[m.strip()])
    return next(iter(matches)) if len(matches) == 1 else ''


class OrderTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth=0;self.present=False;self.login=False
        self.rows=[];self.cells=None;self.cell=None;self.gid='';self.aid=''
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='input' and attrs.get('name')=='password':self.login=True
        if tag=='table':
            if self.depth:self.depth+=1
            elif 'table-list' in attrs.get('class','').split():self.depth=1;self.present=True
        if self.depth and tag=='tr':
            self.cells=[];self.gid=attrs.get('data-gid','');self.aid=attrs.get('data-aid','')
        if self.cells is not None and tag=='td':self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag=='td' and self.cell is not None:
            self.cells.append(' '.join(' '.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.cells is not None:
            self.rows.append((self.gid,self.aid,self.cells));self.cells=None;self.cell=None
        if tag=='table' and self.depth:self.depth-=1


def parse_order_region(text, order_no):
    """Require exact merchant order number, MMOEXP site and Aion2 game ID."""
    doc=OrderTable();doc.feed(text)
    if doc.login:
        raise RuntimeError('order_session_unavailable')
    if not doc.present:
        raise RuntimeError('order_table_unavailable')
    matches = set()
    for gid,aid,cells in doc.rows:
        if gid!='826' or len(cells) < 4:
            continue
        source = cells[2]
        # Do not accept a substring, another site, or another order in the page.
        tokens = re.findall(r'[A-Za-z0-9._-]+', source)
        if order_no not in tokens or 'www.mmoexp.com' not in tokens:
            continue
        game = cells[3]
        region = region_in(game) or AREA_REGIONS.get((gid,aid), '')
        if region:
            matches.add(region)
    if len(matches) > 1:
        raise RuntimeError('order_region_conflict')
    return next(iter(matches)) if matches else ''


def load_verified(conn):
    conn.execute(SCHEMA)
    return {r['order_no']: dict(r) for r in conn.execute('SELECT * FROM order_regions')}


def resolve_regions(session, conn, orders, deliveries, parse_content, max_lookups=200, budget=180):
    cached = load_verified(conn)
    by_order = defaultdict(list)
    for d in deliveries:
        by_order[d.get('order_no') or d.get('sn')].append(d)
    started = time.monotonic()
    stats = dict(lookups=0, resolved=0, cached=0, pending=0, errors=0)
    writes = []
    for o in orders:
        no = str(o.get('order_no') or '').strip()
        if not no:
            continue
        area, _ = parse_content(o.get('content'))
        delivery_regions = {region_in(d.get('game')) for d in by_order[no]} - {''}
        region = region_in(area)
        source = 'admin-content' if region else ''
        if not region and len(delivery_regions) == 1:
            region, source = next(iter(delivery_regions)), 'order-delivery'
        old = cached.get(no, {})
        now = time.time()
        attempts = old.get('attempts', 0)
        retry = 0
        if not region and old.get('area_key') == area and old.get('region') in REGIONS:
            stats['cached'] += 1
            continue
        if not region:
            if old.get('area_key') == area and old.get('retry_at', 0) > now and old.get('evidence','').endswith(AREA_MAPPING_VERSION):
                stats['pending'] += 1
                continue
            if stats['lookups'] >= max_lookups or time.monotonic()-started > budget or stats['errors'] >= 3:
                stats['pending'] += 1
                continue
            stats['lookups'] += 1
            attempts += 1
            try:
                status, text = session.get_order('/order/admin_order/index.html', sn=no, status='all')
                if status != 200:
                    raise RuntimeError('order_lookup_http_%s' % status)
                region = parse_order_region(text, no)
                source = 'order-order-list' if region else 'pending'
                retry = now + min(86400, 21600 * attempts) if not region else 0
            except Exception:
                # Never store response bodies or credentials in errors or logs.
                stats['errors'] += 1
                source, retry = 'lookup-error', now + 1800
        if region:
            stats['resolved'] += 1
        else:
            stats['pending'] += 1
        # Previously verified Order evidence survives a transient empty response.
        evidence = ('exact-order/site/game/area' if source == 'order-order-list' else source) + ':' + AREA_MAPPING_VERSION
        if region and old.get('region') == region and old.get('source') == source and old.get('area_key') == area:
            continue
        writes.append((no, region, source, area, now, retry, attempts, evidence))
    conn.executemany('INSERT OR REPLACE INTO order_regions VALUES (?,?,?,?,?,?,?,?)', writes)
    conn.commit()
    return stats
