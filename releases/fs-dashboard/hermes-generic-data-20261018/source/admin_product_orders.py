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

VERSION = 'admin-model-product-orders-20261018-v2'
AREAS = {'PC': (21589, 'PC Platform'), 'XBOX': (21585, 'Xbox Series X|S'), 'PS': (21587, 'PlayStation 4|5')}
# Admin gids from the active transaction collector's PROFILES (2026-10-18).
# A PID read is deliberately limited to the already approved main site.
GAME_IDS = {'FC27':1327,'D4':456,'AION2':891,'POE2':552,'NBA2K27':1329,
    'NFL27':1309,'MLB26':927,'CFB27':1307,'RS':506,'ARC_RAIDERS':925,
    'MAPLESTORY_CLASSIC':1333,'DARK_AND_DARKER':589,'WOW_FOREVER':1367,
    'ARENA_BREAKOUT_INFINITE':897,'COD_BO7':859}
SHANGHAI = timezone(timedelta(hours=8))
MAX_MODEL_PIDS = 512


def checked_query(args):
    required = {'profile', 'start', 'end'}
    if not isinstance(args, dict) or not required <= set(args) or set(args) - required - {'model_id', 'product_id', 'platform', 'max_pages'}:
        raise ValueError('product_query_fields')
    direct = 'product_id' in args
    if direct == ('model_id' in args) or args['profile'] not in GAME_IDS:
        raise ValueError('product_query_model')
    if direct:
        if 'platform' in args or type(args['product_id']) is not int or not 1 <= args['product_id'] <= 999999999:
            raise ValueError('product_query_product')
    elif type(args['model_id']) is not int or not 1 <= args['model_id'] <= 999999999 or 'platform' in args and args['profile']!='FC27':
        raise ValueError('product_query_model')
    lo, hi = (date.fromisoformat(args[k]) for k in ('start', 'end'))
    if lo.isoformat() != args['start'] or hi.isoformat() != args['end'] or not 0 <= (hi-lo).days <= 30 or hi > datetime.now(SHANGHAI).date():
        raise ValueError('product_query_period')
    platform, pages = args.get('platform', 'ALL'), args.get('max_pages', 20)
    if (not direct and 'platform' in args and platform not in ('ALL', *AREAS)) or type(pages) is not int or not 1 <= pages <= 50:
        raise ValueError('product_query_budget')
    return dict(args,max_pages=pages)


def tool_schema():
    return {'type':'function','function':{'name':'mcp__fcro__fc_query_product_orders',
        'description':'Read all verified Admin PIDs for one exact game/model ID on main site 266; product_id reads one exact PID. FC27 model_id/platform remains a legacy explicit alternative. Mapping and every PID order page must be complete before the model total is complete. Whole-order USD is deduplicated across PIDs, not SKU revenue; line amounts are only included when uniquely verified. Dates use Admin paytime RANGE, timezone unverified. Aggregate only, no PII. Pending: poll identical query.',
        'parameters':{'type':'object','properties':{'profile':{'type':'string','enum':list(GAME_IDS)},'product_id':{'type':'integer','minimum':1,'maximum':999999999},'model_id':{'type':'integer','minimum':1,'maximum':999999999},'start':{'type':'string'},'end':{'type':'string'},'platform':{'type':'string','enum':['ALL',*AREAS]},'max_pages':{'type':'integer','minimum':1,'maximum':50}},'required':['profile','start','end'],'additionalProperties':False}}}


def endpoint(path, filters, page=1, limit=10, order=None):
    params = {'limit':limit, 'page':page}
    if order: params['order'] = order
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
        if tag == 'br' and self.active == 'item':
            self._append_item()
            return
        if (tag, attrs.get('class')) in (('span','item'), ('em','area'), ('em','game')):
            self.active, self.text = attrs['class'], ''
    def handle_data(self, value):
        if self.active: self.text += value
    def handle_endtag(self, tag):
        if self.active and tag in ('em','span'):
            text = self.text.strip()
            if self.active == 'item':
                self._append_item()
            elif self.active == 'area':
                self.areas.append(text);self.area=text
            else:
                self.game=text;self.area=None
            self.active = None
    def _append_item(self):
        text = self.text.strip()
        if text:
            self.items.append(text);self.contexts.append((self.game,self.area))
        self.text = ''


def collect_product_id(request, q, mapped_item=None, shared_deadline=None, private_orders=False):
    """Exact Admin PID read; keep unverified item allocations out of the result."""
    from es_order_structure import amount, safe_label, GAME_LABELS
    gid, pid = GAME_IDS[q['profile']], q['product_id']
    out = {'kind':'admin_product_orders','contract':VERSION,'readonly':True,'http_status':200,
        'query':q,'status':'unavailable','captured_at':datetime.now(timezone.utc).isoformat(),
        'scope':{'site_id':266,'site':'www.mmoexp.com','game_id':gid,'profile':q['profile']},
        'period':{'start':q['start']+' 00:00:00','end':q['end']+' 23:59:59',
            'timezone':'unverified','source_field':'paytime','ui_label':'付款时间'},
        'products':[],'totals':None}
    evidence=[];deadline=shared_deadline if shared_deadline is not None else time.monotonic()+22
    def read(path,max_bytes=2000000):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('product_read_deadline')
        code,raw=request(path,min(10,remaining))
        if code in (401,403):raise PermissionError('existing_auth_unavailable')
        if code!=200 or len(raw)>max_bytes:raise ValueError('product_source_contract')
        value=json.loads(raw)
        if value.get('code')!=1 or not isinstance(value.get('data'),dict):raise ValueError('product_source_contract')
        value=value['data']
        if type(value.get('total')) is not int or value['total']<0 or not isinstance(value.get('list'),list):
            raise ValueError('product_pagination_contract')
        evidence.append(hashlib.sha256(raw if isinstance(raw,bytes) else raw.encode()).hexdigest())
        return value
    try:
        # The live Admin product page uses this exact ID search field/operator.
        # Verify site and game on the returned row rather than assume compound filtering.
        if mapped_item is None:
            goods=read(endpoint('/admin/goods.Goods/index',[('id',pid,'=')],limit=10))
            if goods['total']!=1 or len(goods['list'])!=1:raise ValueError('product_mapping_missing_or_ambiguous')
            item=goods['list'][0]
        else:item=mapped_item
        if item.get('site_id')!=266 or item.get('gid')!=gid or item.get('id')!=pid:
            raise ValueError('product_mapping_scope')
        title=safe_label(item.get('title'))
        if title in ('unknown','未知'):raise ValueError('product_mapping_title')
        area=(item.get('gameArea') or {}).get('title')
        product={'product_id':pid,'model_id':item.get('mid') if type(item.get('mid')) is int and item['mid']>0 else None,
            'title':title,'platform':safe_label(area),
            'area_id':item.get('aid') if type(item.get('aid')) is int else None,
            'area_title':safe_label(area)}
        seen={};order_row_ids={};source_row_ids=set();repeated=0;totals=[];pages=[]
        previous_id=None;previous_page=None;previous_ident=None;previous_projection=None
        ordering_stable=True;row_id_types={'int':0,'numeric_string':0,'other':0}
        duplicate_order_same_row_id=0;duplicate_order_distinct_row_id=0;duplicate_order_conflicts=0
        line=re.compile(r'^[\s☑]*(?:(?:.*? - )|(?:[\d,.]+\s+\S+\s+))?'+re.escape(title)+
            r' x (\d+(?:\.\d+)?) = ([^\d-]*)(-?\d+(?:\.\d+)?),?\s*$')
        for page in range(1,q['max_pages']+1):
            data=read(endpoint('/admin/order.Order/index',
                [('site_id',266,'='),('gid',gid,'='),('pid',pid,'='),
                 ('paytime',out['period']['start']+','+out['period']['end'],'RANGE')],page,
                 limit=100,order='id,desc'),8*1024*1024)
            if len(data['list'])>100:raise ValueError('product_page_size')
            totals.append(data['total']);pages.append({'page':page,'rows':len(data['list']),'source_total':data['total']})
            for row in data['list']:
                raw_id=row.get('id')
                row_id=int(raw_id) if type(raw_id) in (int,str) and str(raw_id).isdigit() else None
                row_id_types['int' if type(raw_id) is int else 'numeric_string' if type(raw_id) is str and row_id is not None else 'other']+=1
                if row_id is not None and row_id>0:
                    source_row_ids.add(row_id)
                if row.get('site_id')!=266 or row.get('gid')!=gid or 'pid' in row and row['pid']!=pid:
                    raise ValueError('product_order_scope')
                ident=row.get('order_no')
                if not isinstance(ident,str) or not ident or len(ident)>160:raise ValueError('product_order_identity')
                ident=hashlib.sha256(ident.encode()).hexdigest()
                when=datetime.strptime(row.get('paytime',''),'%Y-%m-%d %H:%M:%S')
                if not q['start']<=when.date().isoformat()<=q['end']:raise ValueError('product_order_period')
                markup=ProductMarkup(row.get('content',''))
                matched=[line.fullmatch(t.strip()) for t,(game,area) in zip(markup.items,markup.contexts)
                    if (game or '').strip(' >')==GAME_LABELS[q['profile']] and
                    (not product['platform'] or area=='['+product['platform']+']')]
                matched=[m for m in matched if m]
                currency=row.get('currency_code')
                if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):currency='unknown'
                exact_line=matched[0] if len(matched)==1 else None
                projection=(amount(row.get('amount')),safe_label(row.get('status_format')),
                    safe_label(row.get('pay_status_format')),
                    Decimal(exact_line[1]) if exact_line else None,
                    Decimal(exact_line[3]) if exact_line else None,
                    currency,bool(exact_line and len(markup.items)>1))
                # An exact duplicate source row may appear beside itself within one page.
                # An equal ID across pages can hide a missing page-boundary row.
                same_source_row=(row_id==previous_id and page==previous_page and
                    ident==previous_ident and projection==previous_projection)
                if row_id is None or row_id<=0 or previous_id is not None and (
                    row_id>previous_id or row_id==previous_id and not same_source_row):
                    ordering_stable=False
                if row_id is not None and row_id>0:
                    previous_id=row_id;previous_page=page
                    previous_ident=ident;previous_projection=projection
                if ident in seen:
                    if seen[ident]!=projection:duplicate_order_conflicts+=1
                    if row_id==order_row_ids[ident]:duplicate_order_same_row_id+=1
                    else:duplicate_order_distinct_row_id+=1
                    repeated+=1;continue
                seen[ident]=projection
                order_row_ids[ident]=row_id
            if page*100>=data['total'] or not data['list']:break
        received_source_rows=sum(p['rows'] for p in pages)
        source_rows_complete=len(set(totals))==1 and received_source_rows==totals[-1]
        complete=(source_rows_complete and ordering_stable and not duplicate_order_distinct_row_id
            and not duplicate_order_conflicts and len(source_row_ids)==len(seen))
        groups={}
        for usd,status,payment,qty,line_amount,currency,mixed in seen.values():
            bucket=groups.setdefault((status,payment),{'order_status':status,'payment_status':payment,
                'orders':0,'known_amount_orders':0,'order_amount_usd':Decimal(0),
                'quantity':Decimal(0),'item_line_by_currency':{},'mixed_orders':0,
                'known_line_orders':0})
            bucket['orders']+=1
            if usd is not None:bucket['known_amount_orders']+=1;bucket['order_amount_usd']+=usd
            if qty is not None:
                bucket['known_line_orders']+=1;bucket['quantity']+=qty
                bucket['item_line_by_currency'][currency]=bucket['item_line_by_currency'].get(currency,Decimal(0))+line_amount
            bucket['mixed_orders']+=mixed
        for bucket in groups.values():
            bucket['order_amount_usd']=str(bucket['order_amount_usd']) if bucket['known_amount_orders'] else None
            bucket['quantity']=str(bucket['quantity']) if bucket['known_line_orders']==bucket['orders'] else None
            bucket['item_line_by_currency']={k:str(v) for k,v in bucket['item_line_by_currency'].items()}
        product.update(groups=list(groups.values()),coverage={'pages':pages,'source_total':totals[-1],
            'received_unique_orders':len(seen),'duplicate_orders':repeated,
            'received_source_rows':received_source_rows,'source_rows_complete':source_rows_complete,
            'unique_numeric_row_ids':len(source_row_ids),'row_id_types':row_id_types,
            'duplicate_order_same_row_id':duplicate_order_same_row_id,
            'duplicate_order_distinct_row_id':duplicate_order_distinct_row_id,
            'duplicate_order_conflicts':duplicate_order_conflicts,
            'total_stable':len(set(totals))==1,'order_id_desc_verified':ordering_stable,
            'complete':complete})
        out['products']=[product]
        known=[v[0] for v in seen.values() if v[0] is not None]
        out.update(status='available' if complete and len(known)==len(seen) else 'partial',
            totals={'distinct_orders':len(seen),'order_amount_usd':str(sum(known,Decimal(0)))
                if known or not seen and complete else None,'known_amount_orders':len(known)},
            quality={'complete':complete,'amount_definition':'whole-order USD, not SKU revenue',
                'item_quantity':'purchased line x-count, not product specification; one uniquely matched game/area/title line per order; null when any line is unverified',
                'item_line_amount':'original currency from matched lines only; check known_line_orders',
                'time_basis':'Admin paytime RANGE; timezone unverified',
                'mapping_basis':'exact Admin site/game/product ID goods row',
                'refund_history':'current statuses only; net settlement unknown',
                'source_version':hashlib.sha256(json.dumps(evidence).encode()).hexdigest(),
                'raw_order_ids_exposed':False,'game_label':GAME_LABELS[q['profile']]})
        if private_orders:out['_private_orders']={key:value[:3] for key,value in seen.items()}
    except (ValueError,TypeError,KeyError,PermissionError,TimeoutError,OSError,json.JSONDecodeError):
        out.update(status='partial' if out['products'] else 'unavailable',
            reason='product_source_unavailable_or_contract_unclosed')
    return out


def collect_model(request, q, *, max_seconds=22):
    """Map every site/game/model PID, then reuse the verified exact-PID reader."""
    gid=GAME_IDS[q['profile']]
    out={'kind':'admin_product_orders','contract':VERSION,'readonly':True,'http_status':200,
        'query':q,'status':'unavailable','captured_at':datetime.now(timezone.utc).isoformat(),
        'scope':{'site_id':266,'site':'www.mmoexp.com','game_id':gid,'profile':q['profile']},
        'period':{'start':q['start']+' 00:00:00','end':q['end']+' 23:59:59',
            'timezone':'unverified','source_field':'paytime','ui_label':'付款时间'},
        'products':[],'totals':None}
    deadline=time.monotonic()+max_seconds;mapping_pages=[];mapped=[];seen_pids=set();previous_id=None
    source_total=None;mapping_complete=False;global_orders={};conflicts=set();versions=[]
    try:
        # A complete goods mapping is required before any model total is published.
        for page in range(1,21):
            remaining=deadline-time.monotonic()
            if remaining<=0:break
            path=endpoint('/admin/goods.Goods/index',
                [('site_id',266,'='),('gid',gid,'='),('mid',q['model_id'],'=')],
                page,limit=100,order='id,desc')
            code,raw=request(path,min(10,remaining))
            if code in (401,403):raise PermissionError('existing_auth_unavailable')
            if code!=200 or len(raw)>8*1024*1024:raise ValueError('product_mapping_source')
            value=json.loads(raw)
            data=value.get('data') if value.get('code')==1 else None
            if not isinstance(data,dict) or type(data.get('total')) is not int or not isinstance(data.get('list'),list):
                raise ValueError('product_mapping_contract')
            rows=data['list'];total=data['total']
            if total<0 or len(rows)>100 or source_total is not None and source_total!=total:
                raise ValueError('product_mapping_pagination')
            if source_total is None:source_total=total
            mapping_pages.append({'page':page,'rows':len(rows),'source_total':total})
            versions.append(hashlib.sha256(raw if isinstance(raw,bytes) else raw.encode()).hexdigest())
            for row in rows:
                pid=row.get('id');mid=row.get('mid')
                if (type(pid) is not int or pid<=0 or pid in seen_pids or
                    previous_id is not None and pid>=previous_id or
                    row.get('site_id')!=266 or row.get('gid')!=gid or mid!=q['model_id']):
                    raise ValueError('product_mapping_scope_or_order')
                seen_pids.add(pid);previous_id=pid;mapped.append(row)
            if len(mapped)==total:
                mapping_complete=True;break
            if not rows:raise ValueError('product_mapping_empty_page')
        if not mapping_complete:
            raise ValueError('product_mapping_incomplete')
        if len(mapped)>MAX_MODEL_PIDS:
            out.update(reason='product_pid_budget_exceeded',quality={'complete':False,
                'mapping_complete':True,'mapping':{'source_total':source_total,
                    'received':len(mapped),'pages':mapping_pages,'complete':True},
                'mapped_products':len(mapped),'read_products':0,'raw_order_ids_exposed':False})
            return out
        for item in mapped:
            if deadline-time.monotonic()<=0:break
            pid=item['id']
            child_q={'profile':q['profile'],'start':q['start'],'end':q['end'],
                'product_id':pid,'max_pages':q['max_pages']}
            child=collect_product_id(request,child_q,mapped_item=item,
                shared_deadline=deadline,private_orders=True)
            if child['status']=='unavailable' or not child['products']:
                break
            product=child['products'][0]
            out['products'].append(product)
            versions.append(child['quality']['source_version'])
            for ident,projection in child.pop('_private_orders').items():
                if ident in global_orders and global_orders[ident]!=projection:conflicts.add(ident)
                else:global_orders[ident]=projection
        all_products_complete=len(out['products'])==len(mapped) and all(
            p['coverage']['complete'] for p in out['products'])
        valid=[v for k,v in global_orders.items() if k not in conflicts]
        known=[v[0] for v in valid if v[0] is not None]
        complete=all_products_complete and not conflicts and len(known)==len(valid)
        out['totals']=({'distinct_orders':len(valid),'order_amount_usd':str(sum(known,Decimal(0)))
            if known or not valid and complete else None,'known_amount_orders':len(known)}
            if out['products'] or not mapped else None)
        out['status']='available' if complete else 'partial'
        out['quality']={'complete':complete,'mapping_complete':True,
            'mapping':{'source_total':source_total,'received':len(mapped),'pages':mapping_pages,
                'complete':True},'mapped_products':len(mapped),'read_products':len(out['products']),
            'conflicting_orders':len(conflicts),
            'amount_definition':'whole-order USD, deduplicated across all mapped PIDs; not SKU revenue',
            'time_basis':'Admin paytime RANGE; timezone unverified',
            'source_version':hashlib.sha256(json.dumps(versions).encode()).hexdigest(),
            'raw_order_ids_exposed':False}
        if not complete:out['reason']='product_pid_pages_incomplete_or_budget'
    except (ValueError,TypeError,KeyError,PermissionError,TimeoutError,OSError,json.JSONDecodeError):
        out.update(status='unavailable',reason='product_mapping_unavailable_or_incomplete',totals=None,
            products=[],quality={'complete':False,'mapping_complete':False,
                'mapping':{'source_total':source_total,'received':len(mapped),
                    'pages':mapping_pages,'complete':False},'raw_order_ids_exposed':False})
    return out


def collect(request, args, now=None, *, model_seconds=22):
    from es_order_structure import amount, safe_label
    q = checked_query(args)
    if 'product_id' in q:
        return collect_product_id(request,q)
    if 'platform' not in q:return collect_model(request,q,max_seconds=model_seconds)
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
    import sys
    sys.path.insert(0,'/opt/sales-dashboard/collector')
    import p2pah_auth as auth
    q=checked_query(args)
    client=auth.Session()
    def request(path,timeout):
        response=client.admin.get(auth.ADMIN_API+path,timeout=timeout)
        return response.status_code,response.content
    try:value=collect(request,q,model_seconds=540)
    finally:client.close()
    if len(json.dumps(value).encode())>1024*1024:raise ValueError('product_response_size')
    if value.get('kind')!='admin_product_orders' or value.get('query')!=q:raise ValueError('product_response_contract')
    return value


def read(args):
    q=checked_query(args);key=json.dumps(q,sort_keys=True)
    with LOCK:
        now=time.monotonic()
        for old,(f,started) in list(CACHE.items()):
            if f.done():
                try:
                    status=f.result().get('status')
                    ttl=(600 if json.loads(old)['end']>=datetime.now(SHANGHAI).date().isoformat() else 900) if status=='available' else 3 if status=='pending' else 60
                except Exception:ttl=60
                if now-started>ttl:CACHE.pop(old)
        if key not in CACHE:
            if len(CACHE)>=16:return {'status':'unavailable','reason':'product_cache_capacity'}
            CACHE[key]=(POOL.submit(server_read,q),now)
        future=CACHE[key][0]
    if not future.done():return {'status':'pending','retryAfter':3}
    try:return future.result()
    except Exception:return {'status':'unavailable','reason':'product_source_unavailable'}
