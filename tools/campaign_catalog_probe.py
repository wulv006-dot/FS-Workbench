"""GET-only in-memory product mapping probe. Only projected identities/specifications leave it.

Controller may exec this source in memory, then call run_probe(seed) and JSON-encode its result.
No write, login, environment dump, raw response dump or POST endpoint exists here.
"""
import contextlib
import hashlib
from html.parser import HTMLParser
import io
import json
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

ADMIN = {'goods': '/admin/goods.Goods/edit', 'model': '/admin/goods.GoodsMould/edit'}
PUBLIC_PATHS = {'/Fc-27/Players.html', '/Fc-27/Sbc.html', '/Fc-27/Packs.html',
                '/Fc-27/Coins.html', '/Nba-2k27/Vc.html', '/Nfl-27/Coins.html',
                '/Diablo-4/Gold.html', '/Poe-2/Currency.html', '/Aion-2/Kinah.html'}
BLOCKED = re.compile(r'price|cost|profit|amount|money|token|password|secret|cookie|authorization|email|order|customer|member', re.I)
SPEC_KEYS = {'id', 'name', 'title', 'label', 'key', 'value', 'values', 'children', 'options',
             'sku_id', 'skuid', 'skuId', 'prop_id', 'property_id', 'attribute_id', 'value_id',
             'pid', 'vid', 'ids', 'propids', 'attr', 'saleprop', 'skuTableSet', 'skuData',
             'spec', 'props', 'propvalues', 'status', 'stock', 'min_qty', 'max_qty', 'step',
             'num', 'group', 'quantity', 'unit', 'required', 'selected', 'disabled', 'checked'}
SPEC_KEYS.update({'gold', 'items', 'sku', 'skus', 'specs', 'attributes', 'attrs', 'sale_props',
                  'baseprop', 'extend', 'min', 'max', 'qty', 'quantity_group', 'type'})
PURCHASE_FIELDS = {'id', 'goods_id', 'gid', 'Game_id', 'site_id', 'aid', 'sid', 'cid',
                   'category', 'category_id', 'sku', 'sku_id', 'attr', 'saleprop', 'propvalues',
                   'quantity', 'min_qty', 'max_qty', 'step', 'num', 'group', 'unit', 'has_sku'}


def safe_id(value, zero=False):
    if type(value) not in (str, int) or not re.fullmatch(r'[0-9]{1,19}', str(value)):
        raise ValueError('IDENTITY_INVALID')
    if not zero and int(value) < 1:
        raise ValueError('IDENTITY_INVALID')
    return str(int(value))


def scalar(value):
    if type(value) in (bool, int, float) or value is None:
        return value
    if isinstance(value, str) and len(value) <= 160 and not re.search(r'[\x00-\x1f$€£¥]|https?://|@|phx_', value) and not BLOCKED.search(value):
        return value
    return None


def specs(value, depth=0):
    if depth > 7:
        return {'schema_status': 'depth_limit'}
    if isinstance(value, list):
        if len(value) > 200:
            return {'schema_status': 'entry_limit', 'entry_count': len(value)}
        return [specs(v, depth + 1) for v in value]
    if isinstance(value, dict):
        output, unknown = {}, []
        for key, item in value.items():
            key = str(key)
            if BLOCKED.search(key):
                continue
            if key in SPEC_KEYS or re.fullmatch(r'[0-9]+', key):
                output[key] = specs(item, depth + 1)
            elif re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,48}', key):
                unknown.append(key)
        if unknown:
            output['_unmapped_fields'] = sorted(unknown)
        return output
    return scalar(value)


def structure(value, depth=0):
    """Only field names/types for unknown containers; never arbitrary leaf values."""
    if depth > 7:
        return {'type': type(value).__name__, 'truncated': True}
    if isinstance(value, dict):
        return {'type': 'dict', 'fields': {str(k): structure(v, depth + 1)
            for k, v in list(value.items())[:100] if not BLOCKED.search(str(k))
            and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', str(k))}}
    if isinstance(value, list):
        return {'type': 'list', 'length': len(value), 'sample_shapes': [structure(v, depth + 1) for v in value[:3]]}
    return {'type': type(value).__name__}


def row_projection(row, kind):
    out = {'identity': {}, 'purchase_fields': {}, 'specifications': {},
           'more_structure': structure(row.get('more')), 'nested_purchase_fields': specs(row.get('more'))}
    for key in ('id', 'site_id', 'gid', 'mid', 'aid', 'sid', 'cid'):
        if key in row:
            out['identity'][key] = safe_id(row[key], zero=key in ('aid', 'sid', 'cid'))
    for key in ('min_qty', 'max_qty', 'step', 'num', 'group', 'unit', 'sku_switch',
                'attr_switch', 'status', 'buy_status', 'auto_off', 'has_sku'):
        if key in row:
            out['purchase_fields'][key] = scalar(row[key])
    for container, source in (('row', row), ('more', row.get('more'))):
        if not isinstance(source, dict):
            out['specifications'][container] = {'schema_status': 'not_object'}
            continue
        out['specifications'][container] = {key: {'present': key in source,
            **({'shape': type(source[key]).__name__, 'value': specs(source[key])} if key in source else {})}
            for key in ('saleprop', 'skuTableSet', 'propvalues')}
    return out


class PurchaseHTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts = []; self.controls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'script' and values.get('src'):
            self.scripts.append(values['src'])
        if tag in ('input', 'select', 'option'):
            name = values.get('name', values.get('id', ''))
            if name in PURCHASE_FIELDS:
                self.controls.append({k: scalar(v) for k, v in values.items()
                    if k in ('name', 'id', 'value', 'type', 'min', 'max', 'step')})


def public_projection(raw):
    text = raw.decode('utf-8', errors='replace')
    parser = PurchaseHTML(); parser.feed(text)
    # Emit only fixed vocabulary and hashes, never HTML, JS snippets, prices or arbitrary literals.
    expressions = []
    for match in re.finditer(r'''["']?([A-Za-z_][A-Za-z0-9_]*)["']?\s*[:=]\s*(["'](?:new_items|new_gold)["']|[0-9]+(?:\.[0-9]+)?|[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z0-9_$]+)*)''', text):
        field, expression = match.groups()
        if field in PURCHASE_FIELDS and not BLOCKED.search(expression):
            record = dict(field=field, expression=expression)
            if record not in expressions and len(expressions) < 100:
                expressions.append(record)
    return dict(sha256=hashlib.sha256(raw).hexdigest(), controls=parser.controls,
                purchase_expressions=expressions,
                purchase_tokens=sorted(key for key in PURCHASE_FIELDS if re.search(r'\b' + re.escape(key) + r'\b', text)),
                protocol_markers=sorted(key for key in ('new_items', 'new_gold', '/Cart/add.html',
                    '/ajax/goods', 'saleprop', 'skuTableSet') if key in text)), parser.scripts


def shared_session():
    sys.path.insert(0, '/opt/sales-dashboard/collector')
    sys.path.insert(0, '/opt/fs-shared-session')
    # Reuse current owner session; suppress legacy client informational output.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from p2pah_auth import Session
        from shared_admin import admin_token_from_service
        token, _ = admin_token_from_service()
        if not token:
            raise ValueError('SHARED_SESSION_UNAVAILABLE')
        session = Session()
        try:
            if not session.bind_admin_token(token):
                raise ValueError('SHARED_SESSION_UNAVAILABLE')
        except Exception:
            session.close(); raise
        finally:
            del token
    return session


def run_probe(seed, session=None, public_get=None, interval=0.35, sleep=time.sleep, read_public=True):
    if not isinstance(seed, dict) or seed.get('schema_version') != 1:
        raise ValueError('INVALID_SEED')
    references = seed['references']
    if not isinstance(references, list) or not 1 <= len(references) <= 100:
        raise ValueError('INVALID_SEED')
    for ref in references:
        for value in ref['product_ref'].values():
            safe_id(value)
        if ref['public_path'] not in PUBLIC_PATHS:
            raise ValueError('PUBLIC_ROUTE_NOT_ALLOWED')
    if not 0.2 <= interval <= 5:
        raise ValueError('INVALID_READ_INTERVAL')
    own = session is None
    if own:
        session = shared_session()
    if public_get is None:
        import requests
        public = requests.Session()
        public.trust_env = False
        def public_get(url):
            response = public.get(url, timeout=30, allow_redirects=False)
            if response.status_code != 200 or len(response.content) > 3000000:
                raise ValueError('PUBLIC_READ_UNAVAILABLE')
            return response.content
    else:
        public = None
    goods_cache, model_cache, failures, products, pages, scripts = {}, {}, {}, [], [], {}
    request_counts = dict(goods=0, model=0)
    def detail(kind, object_id):
        cache = goods_cache if kind == 'goods' else model_cache
        if (kind, object_id) in failures:
            raise ValueError(failures[kind, object_id])
        if object_id not in cache:
            request_counts[kind] += 1
            try:
                sleep(interval)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    status, payload = session.get_admin(ADMIN[kind], id=object_id)
                row = payload.get('data', {}).get('row') if isinstance(payload, dict) else None
                if status != 200 or not isinstance(payload, dict) or payload.get('code') != 1 or not isinstance(row, dict) or safe_id(row.get('id')) != object_id:
                    raise ValueError('PRODUCT_DETAIL_UNAVAILABLE')
                cache[object_id] = row
            except Exception:
                failures[kind, object_id] = 'PRODUCT_DETAIL_UNAVAILABLE'
                raise ValueError('PRODUCT_DETAIL_UNAVAILABLE') from None
        return cache[object_id]
    try:
        scopes = sorted({tuple(r['product_ref'][k] for k in ('site_id', 'game_id', 'goods_id')) for r in references})
        for site, game, gid in scopes:
            out = {'product_ref': {'site_id': site, 'game_id': game, 'goods_id': gid}}
            try:
                goods = detail('goods', gid)
                if safe_id(goods.get('site_id')) != site or safe_id(goods.get('gid')) != game:
                    raise ValueError('PRODUCT_SCOPE_MISMATCH')
                model = detail('model', safe_id(goods.get('mid')))
                if 'gid' in model and safe_id(model['gid']) != game:
                    raise ValueError('MODEL_SCOPE_MISMATCH')
                out.update(status='observed', goods=row_projection(goods, 'goods'), model=row_projection(model, 'model'))
            except Exception as error:
                reason = str(error) if str(error) in {'PRODUCT_DETAIL_UNAVAILABLE', 'PRODUCT_SCOPE_MISMATCH', 'MODEL_SCOPE_MISMATCH', 'IDENTITY_INVALID'} else 'READ_UNAVAILABLE'
                out.update(status='unresolved', reason=reason)
            products.append(out)
        for path in (sorted({r['public_path'] for r in references}) if read_public else []):
            try:
                sleep(interval);raw = public_get('https://www.mmoexp.com' + path)
                evidence, sources = public_projection(raw);pages.append(dict(path=path, status='observed', **evidence))
                for src in sources:
                    parsed = urlsplit(urljoin('https://www.mmoexp.com' + path, src))
                    if parsed.scheme != 'https' or parsed.netloc != 'www.mmoexp.com' or (parsed.query and not re.fullmatch(r'(?:v|ver|version|t)=[A-Za-z0-9_.-]{1,40}', parsed.query)) or not re.fullmatch(r'/(?:js|static|assets)/[A-Za-z0-9_./-]+\.js', parsed.path) or '..' in parsed.path.split('/'):
                        continue
                    if parsed.path in scripts or len(scripts) >= 24:
                        continue
                    try:
                        sleep(interval);js = public_get('https://www.mmoexp.com' + parsed.path)
                        evidence, _ = public_projection(js);scripts[parsed.path] = dict(status='observed', **evidence)
                    except Exception:
                        scripts[parsed.path] = dict(status='unresolved', reason='PUBLIC_SCRIPT_READ_UNAVAILABLE')
            except Exception:
                pages.append(dict(path=path, status='unresolved', reason='PUBLIC_PAGE_READ_UNAVAILABLE'))
        return dict(schema_version=1, probe_version='catalog-get-probe-v1', method='GET',
            reference_count=len(references), unique_goods_count=len(scopes),
            observed_goods_count=sum(p['status'] == 'observed' for p in products),
            goods_requests=request_counts['goods'], model_requests=request_counts['model'], products=products,
            public_pages=pages, public_scripts=scripts, authoritative=False, checkout_enabled=False,
            verification_scope='product_structure_observation_not_purchase_or_quote_verification')
    finally:
        if own:
            session.close()
        if public is not None:
            public.close()


if __name__ == '__main__':
    try:
        result = run_probe(json.load(sys.stdin))
    except Exception:
        result = dict(status='unresolved', reason='PROBE_UNAVAILABLE', authoritative=False, checkout_enabled=False)
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
