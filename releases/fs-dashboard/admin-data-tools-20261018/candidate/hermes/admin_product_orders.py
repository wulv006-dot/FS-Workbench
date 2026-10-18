"""Observed Admin model/site products -> exact product order filter. Read-only, no PII output."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlencode

VERSION = 'admin-model-product-orders-20261018-v1'
AREAS = {'PC': (21589, 'PC Platform'), 'XBOX': (21585, 'Xbox Series X|S'), 'PS': (21587, 'PlayStation 4|5')}
SHANGHAI = timezone(timedelta(hours=8))


def checked_query(args):
    required = {'profile', 'model_id', 'start', 'end'}
    if not isinstance(args, dict) or not required <= set(args) or set(args) - required - {'platform', 'max_pages'}:
        raise ValueError('product_query_fields')
    if args['profile'] != 'FC27' or type(args['model_id']) is not int or not 1 <= args['model_id'] <= 999999999:
        raise ValueError('product_query_model')
    lo, hi = (date.fromisoformat(args[k]) for k in ('start', 'end'))
    if lo.isoformat() != args['start'] or hi.isoformat() != args['end'] or not 0 <= (hi-lo).days <= 30 or hi > datetime.now(SHANGHAI).date():
        raise ValueError('product_query_period')
    platform, pages = args.get('platform', 'ALL'), args.get('max_pages', 20)
    if platform not in ('ALL', *AREAS) or type(pages) is not int or not 1 <= pages <= 50:
        raise ValueError('product_query_budget')
    return dict(args, platform=platform, max_pages=pages)


def tool_schema():
    return {'type':'function','function':{'name':'mcp__fcro__fc_query_product_orders',
        'description':'Read FC27 main-site266 orders for one model. First query live site/model/platform product IDs, then exact pid order filter; never use FS ALL IDs or infer +2. All original statuses, inclusive date strings submitted as observed paytime RANGE (UI calls it 下单时间; source timezone unverified). Complete pagination or explicit partial. Deduplicate order USD once across platforms; mixed orders are not all SKU revenue. Only aggregate counts, amounts, line quantities and coverage; no PII/order identities. Pending: poll same query.',
        'parameters':{'type':'object','properties':{'profile':{'type':'string','enum':['FC27']},'model_id':{'type':'integer','minimum':1,'maximum':999999999},'start':{'type':'string'},'end':{'type':'string'},'platform':{'type':'string','enum':['ALL',*AREAS]},'max_pages':{'type':'integer','minimum':1,'maximum':50}},'required':['profile','model_id','start','end'],'additionalProperties':False}}}


def endpoint(path, filters, page=1, limit=10):
    params = {'limit':limit, 'page':page}
    for i, (field, value, operator) in enumerate(filters):
        params.update({f'search[{i}][field]':field, f'search[{i}][val]':value, f'search[{i}][operator]':operator})
        if operator == 'RANGE': params[f'search[{i}][render]'] = 'datetime'
    return path + '?' + urlencode(params)


class ProductMarkup(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.items, self.areas, self.contexts, self.active, self.text = [], [], [], None, ''
        self.game, self.area = None, None
        self.feed(value)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if (tag, attrs.get('class')) in (('span','item'), ('em','area'), ('em','game')):
            self.active, self.text = attrs['class'], ''
    def handle_data(self, value):
        if self.active: self.text += value
    def handle_endtag(self, tag):
        if self.active and tag in ('em','span'):
            text = self.text.strip()
            if self.active == 'item':
                self.items.append(text);self.contexts.append((self.game,self.area))
            elif self.active == 'area':
                self.areas.append(text);self.area=text
            else:
                self.game=text;self.area=None
            self.active = None


def collect(request, args, now=None):
    from es_order_structure import amount, safe_label
    q = checked_query(args)
    out = {'kind':'admin_product_orders','contract':VERSION,'readonly':True,'http_status':200,'query':q,
        'status':'unavailable','captured_at':datetime.now(timezone.utc).isoformat(),
        'scope':{'site_id':266,'site':'www.mmoexp.com','game_id':1327,'profile':'FC27'},
        'period':{'start':q['start']+' 00:00:00','end':q['end']+' 23:59:59','timezone':'unverified','source_field':'paytime','ui_label':'下单时间'},
        'products':[], 'totals':None}
    deadline = time.monotonic() + 22
    evidence = []
    def read(path):
        if time.monotonic() >= deadline: raise TimeoutError('product_read_deadline')
        code, raw = request(path, min(10, deadline-time.monotonic()))
        if code in (401,403): raise PermissionError('existing_auth_unavailable')
        if code != 200 or len(raw) > 2000000: raise ValueError('product_source_contract')
        data = json.loads(raw)
        if data.get('code') != 1 or not isinstance(data.get('data'),dict): raise ValueError('product_source_contract')
        data = data['data']
        if type(data.get('total')) is not int or data['total'] < 0 or not isinstance(data.get('list'),list): raise ValueError('product_pagination_contract')
        # A digest is evidence, never a raw response archive.
        evidence.append(hashlib.sha256(raw if isinstance(raw,bytes) else raw.encode()).hexdigest())
        return data
    try:
        mapping = read(endpoint('/admin/goods.Goods/index',[('site_id',266,'='),('mid',q['model_id'],'=')],limit=25))
        if len(mapping['list']) != mapping['total'] or mapping['total'] > 25: raise ValueError('product_mapping_partial')
        mapped = {}
        for row in mapping['list']:
            if row.get('site_id') != 266 or row.get('gid') != 1327 or row.get('mid') != q['model_id'] or row.get('cid') != 10255: raise ValueError('product_mapping_scope')
            candidates = [p for p,(aid,title) in AREAS.items() if row.get('aid') == aid and (row.get('gameArea') or {}).get('title') == title]
            if len(candidates) != 1 or candidates[0] in mapped or type(row.get('id')) is not int: raise ValueError('product_mapping_platform')
            title = safe_label(row.get('title'))
            if title in ('unknown','未知'): raise ValueError('product_mapping_title')
            mapped[candidates[0]] = {'platform':candidates[0],'product_id':row['id'],'model_id':row['mid'],'title':title}
        platforms = list(AREAS) if q['platform'] == 'ALL' else [q['platform']]
        if any(p not in mapped for p in platforms): raise ValueError('product_mapping_missing')
        unique, conflict, observations, groups = {}, set(), [], []
        for platform in platforms:
            product = dict(mapped[platform]); seen = set(); totals = []; pages = []; matched = []; repeated = 0
            for page in range(1,q['max_pages']+1):
                data = read(endpoint('/admin/order.Order/index', [('site_id',266,'='),('cid',0,'='),('gid',1327,'='),('pid',product['product_id'],'='),('paytime',out['period']['start']+','+out['period']['end'],'RANGE')],page))
                rows = data['list']; totals.append(data['total'])
                if len(rows) > 10: raise ValueError('product_page_size')
                pages.append({'page':page,'rows':len(rows),'source_total':data['total']})
                for row in rows:
                    if row.get('site_id') != 266 or row.get('gid') != 1327: raise ValueError('product_order_scope')
                    ident = row.get('order_no')
                    if not isinstance(ident,str) or not ident or len(ident)>160: raise ValueError('product_order_identity')
                    ident = hashlib.sha256(ident.encode()).hexdigest()
                    if ident in seen: repeated += 1; continue
                    seen.add(ident)
                    when = row.get('paytime','')
                    try: parsed = datetime.strptime(when,'%Y-%m-%d %H:%M:%S')
                    except (ValueError,TypeError): raise ValueError('product_order_time')
                    if not q['start'] <= parsed.date().isoformat() <= q['end']: raise ValueError('product_order_period')
                    markup = ProductMarkup(row.get('content',''))
                    if '['+AREAS[platform][1]+']' not in markup.areas: raise ValueError('product_order_platform')
                    line = re.compile(r'^\s*☑?In-Game Packs - '+re.escape(product['title'])+r' x (\d+(?:\.\d+)?) = ([^\d-]*)(-?\d+(?:\.\d+)?),?\s*$')
                    lines = [line.fullmatch(t) for t,(game,area) in zip(markup.items,markup.contexts) if game == 'FC 27 >>>' and area == '['+AREAS[platform][1]+']']; lines = [m for m in lines if m]
                    if not lines: raise ValueError('product_order_line_missing')
                    usd = amount(row.get('amount'))
                    currency = row.get('currency_code')
                    if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency): currency = 'unknown'
                    projection = {'usd':usd,'status':safe_label(row.get('status_format')),'payment':safe_label(row.get('pay_status_format'))}
                    if ident in unique and unique[ident] != projection: conflict.add(ident)
                    unique[ident] = projection
                    matched.append({'key':ident,**projection,'qty':sum((Decimal(m[1]) for m in lines),Decimal(0)),
                        'line_amount':sum((Decimal(m[3]) for m in lines),Decimal(0)),'currency':currency,'mixed':len(markup.items)>len(lines)})
                if page*10 >= data['total'] or not rows: break
            complete = len(set(totals)) == 1 and len(seen)==totals[-1] and not repeated
            product.update(coverage={'pages':pages,'source_total':totals[-1],'received_unique_orders':len(seen),'duplicate_orders':repeated,'total_stable':len(set(totals))==1,'complete':complete})
            observations.append(complete)
            by_state = {}
            for row in matched:
                key = (row['status'],row['payment'])
                b = by_state.setdefault(key,{'order_status':key[0],'payment_status':key[1],'orders':0,'order_amount_usd':Decimal(0),'known_amount_orders':0,'quantity':Decimal(0),'item_line_by_currency':defaultdict(Decimal),'mixed_orders':0})
                b['orders']+=1;b['quantity']+=row['qty'];b['mixed_orders']+=row['mixed']
                if row['usd'] is not None:b['order_amount_usd']+=row['usd'];b['known_amount_orders']+=1
                b['item_line_by_currency'][row['currency']]+=row['line_amount']
            product['groups']=[]
            for b in by_state.values():
                b['quantity']=str(b['quantity']);b['order_amount_usd']=str(b['order_amount_usd']) if b['known_amount_orders'] else None
                b['item_line_by_currency']={k:str(v) for k,v in b['item_line_by_currency'].items()};product['groups'].append(b)
            out['products'].append(product)
        rows = [v for k,v in unique.items() if k not in conflict]
        known = [r['usd'] for r in rows if r['usd'] is not None]
        complete = all(observations) and not conflict
        out.update(status='available' if complete else 'partial',totals={'distinct_orders':len(rows),'order_amount_usd':str(sum(known,Decimal(0))) if known or not rows and complete else None,'known_amount_orders':len(known)},
            quality={'complete':complete,'conflicting_orders':len(conflict),'amount_definition':'whole-order USD, deduplicated across selected products; not SKU line revenue','mixed_order_policy':'do not allocate whole-order USD to target SKU; original line amounts stay in their currency','time_basis':'observed API paytime RANGE, despite UI 下单时间; timezone/end inclusivity unverified','mapping_basis':'fresh site266/model query; no FS ALL IDs or arithmetic conversion','refund_history':'current statuses only, historical/partial refunds and net settlement unknown','source_version':hashlib.sha256(json.dumps(evidence).encode()).hexdigest(),'raw_order_ids_exposed':False})
        if len(known)<len(rows):out['status']='partial'
    except (ValueError,TypeError,KeyError,PermissionError,TimeoutError,OSError,json.JSONDecodeError):
        # Keep any completed products as explicitly partial; never turn a failure into a zero result.
        out.update(status='partial' if out['products'] else 'unavailable',reason='product_source_unavailable_or_contract_unclosed')
    return out


POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='admin-product-orders')
LOCK=threading.RLock()
CACHE={}

def server_read(args):
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    q=checked_query(args)
    with build_opener(NoRedirect).open(Request('http://127.0.0.1:8767/business/fc-capability',data=json.dumps(dict(q,kind='product_orders')).encode(),headers={'Content-Type':'application/json'},method='POST'),timeout=28) as response:
        raw=response.read(1024*1024+1)
    if len(raw)>1024*1024:raise ValueError('product_response_size')
    value=json.loads(raw)
    if value.get('kind')!='admin_product_orders' or value.get('query')!=q:raise ValueError('product_response_contract')
    return value


def read(args):
    q=checked_query(args);key=json.dumps(q,sort_keys=True)
    with LOCK:
        now=time.monotonic()
        for old,(f,started) in list(CACHE.items()):
            if f.done() and now-started>900:CACHE.pop(old)
        if key not in CACHE:
            if len(CACHE)>=16:return {'status':'unavailable','reason':'product_cache_capacity'}
            CACHE[key]=(POOL.submit(server_read,q),now)
        future=CACHE[key][0]
    if not future.done():return {'status':'pending','retryAfter':3}
    try:return future.result()
    except Exception:return {'status':'unavailable','reason':'product_source_unavailable'}
