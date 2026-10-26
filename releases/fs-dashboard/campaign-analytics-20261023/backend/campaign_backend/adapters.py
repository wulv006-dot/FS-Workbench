"""Allowlisted GET access using the existing shared owner session; no new login."""
import sys
import json
import threading
import time
from pathlib import Path
from .core import ContractError, identity, source_identity
from .catalog import positive_id

LIST_ROUTES = {
    'models': '/admin/goods.GoodsMould/index',
    'goods': '/admin/goods.Goods/index',
    'discounts': '/admin/market.Discount/index',
    'coupons': '/admin/market.Coupon/index',
    'coupon_logs': '/admin/user.MemberCouponLog/index',
    'orders': '/admin/order.Order/index',
}
DETAIL_ROUTES = {'model': '/admin/goods.GoodsMould/edit', 'goods': '/admin/goods.Goods/edit',
                 'coupon': '/admin/market.Coupon/edit', 'discount': '/admin/market.Discount/edit'}


def payment_observation(row, site_id):
    """Current orderStatus-9f89c2eb.js proves pay_status==1 paid, not refund settlement."""
    site_id = positive_id(site_id)
    if not isinstance(row, dict) or positive_id(row.get('site_id')) != site_id:
        raise ContractError('ORDER_SCOPE_MISMATCH')
    raw = row.get('pay_status')
    if type(raw) not in (int, str):
        raise ContractError('PAYMENT_STATE_UNKNOWN')
    paid = type(raw) in (int, str) and raw in (1, '1')
    paid_at = row.get('paytime')
    if not isinstance(paid_at, str) or not paid_at.strip():
        raise ContractError('PAYMENT_TIME_MISSING')
    return dict(site_id=site_id, order_no=identity(row.get('order_no')),
        raw_pay_status=raw, payment_state='paid' if paid else 'unknown', raw_paid_at=paid_at,
        timestamp_semantics='source_timezone_mapping_required', refund_state='unknown',
        attribution_ready=False, verification_ref='admin-ui/orderStatus-9f89c2eb.js/pay_status==1')


def search(filters):
    params = {}
    for index, (field, operator, value) in enumerate(filters):
        if operator not in ('=', 'IN', 'LIKE', 'RANGE'):
            raise ContractError('INVALID_FILTER')
        for key, val in (('field', field), ('operator', operator), ('val', value)):
            params[f'search[{index}][{key}]'] = str(val)
        if operator == 'RANGE':
            params[f'search[{index}][render]'] = 'datetime'
    return params


class AdminRead:
    def __init__(self, session, catalog_get_once=None, catalog_timeout=20.0):
        self.session = session
        if type(catalog_timeout) not in (int,float) or not 0 < catalog_timeout <= 20:
            raise ContractError('INVALID_CATALOG_DEADLINE')
        self._catalog_transport = catalog_get_once or self._catalog_http_once
        self._catalog_timeout = catalog_timeout
        self._catalog_deadline = None

    def begin_catalog_read(self):
        """One aggregate budget for a model detail + scoped child lookup."""
        self._catalog_deadline = time.monotonic() + self._catalog_timeout

    def _catalog_http_once(self, route, **params):
        """Same authenticated requests session, bypassing shared get_admin retry/refresh loops."""
        url = 'https://admin-api.p2pah.cn' + route
        retries = self.session.admin.get_adapter(url).max_retries
        if type(retries.total) is not int or retries.total != 0:
            raise ContractError('CATALOG_SEARCH_TRANSPORT_NOT_SINGLE_ATTEMPT')
        response = self.session.admin.get(url, params=params, headers={'batoken':self.session.token},
            timeout=(5,15), allow_redirects=False, stream=True)
        try:
            if response.status_code == 504:
                raise TimeoutError()
            if response.status_code != 200:
                raise ContractError('CATALOG_SEARCH_HTTP_REJECTED')
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                raw.extend(chunk)
                if len(raw) > 2000000:
                    raise ContractError('CATALOG_SEARCH_RESPONSE_TOO_LARGE')
            return response.status_code, json.loads(raw)
        finally:
            response.close()

    def _get_catalog_once(self, route, **params):
        # Each management bridge runs in its own process. The daemon deadline never waits for
        # an upstream trickle/blocked socket to finish, and never starts a second HTTP attempt.
        completed, result = threading.Event(), {}
        def run():
            try:
                result['value'] = self._catalog_transport(route, **params)
            except Exception as error:
                name = type(error).__name__
                safe = {'CATALOG_SEARCH_HTTP_REJECTED','CATALOG_SEARCH_TRANSPORT_NOT_SINGLE_ATTEMPT',
                        'CATALOG_SEARCH_RESPONSE_TOO_LARGE'}
                result['error'] = ('CATALOG_SEARCH_TIMEOUT' if isinstance(error,TimeoutError)
                    or name in ('Timeout','ReadTimeout','ConnectTimeout') else str(error)
                    if isinstance(error,ContractError) and str(error) in safe else 'UPSTREAM_UNAVAILABLE')
            finally:
                completed.set()
        remaining = self._catalog_timeout if self._catalog_deadline is None else self._catalog_deadline-time.monotonic()
        if remaining <= 0:
            raise ContractError('CATALOG_SEARCH_TIMEOUT')
        threading.Thread(target=run,daemon=True).start()
        if not completed.wait(remaining):
            raise ContractError('CATALOG_SEARCH_TIMEOUT')
        if 'error' in result:
            raise ContractError(result['error'])
        try:
            status, payload = result['value']
            if status != 200:
                raise ContractError('CATALOG_SEARCH_HTTP_REJECTED')
            if not isinstance(payload,dict) or type(payload.get('code')) is not int or payload.get('code') != 1 or not isinstance(payload.get('data'),dict):
                raise ValueError()
            return payload['data']
        except ContractError:
            raise
        except Exception:
            raise ContractError('UPSTREAM_UNAVAILABLE') from None

    def catalog_goods(self, goods_id):
        goods_id = positive_id(goods_id)
        row = self._get_catalog_once(DETAIL_ROUTES['goods'],id=goods_id).get('row')
        if not isinstance(row,dict) or str(row.get('id')) != goods_id:
            raise ContractError('DETAIL_ID_MISMATCH')
        return row

    def catalog_model(self, model_id):
        model_id = positive_id(model_id)
        row = self._get_catalog_once(DETAIL_ROUTES['model'],id=model_id).get('row')
        if not isinstance(row,dict) or str(row.get('id')) != model_id:
            raise ContractError('DETAIL_ID_MISMATCH')
        return row

    def search_models_page(self, game_id, category_id, keyword, page=1, limit=10):
        game_id, category_id = positive_id(game_id), positive_id(category_id)
        if type(page) is not int or not 1<=page<=500 or type(limit) is not int or not 1<=limit<=20:
            raise ContractError('INVALID_CATALOG_PAGE')
        if keyword is not None and (not isinstance(keyword,str) or not 2<=len(keyword.strip())<=80
                or any(ord(c)<32 for c in keyword)):
            raise ContractError('INVALID_CATALOG_KEYWORD')
        filters = [('gid','=',game_id),('cid','=',category_id)]
        if keyword is not None:filters.append(('title','LIKE',keyword))
        data = self._get_catalog_once(LIST_ROUTES['models'],page=page,limit=limit,order='id,desc',**search(filters))
        rows,total = data.get('list'),data.get('total')
        if isinstance(total,str) and total.isascii() and total.isdecimal():total=int(total)
        if (not isinstance(rows,list) or type(total) is not int or not 0<=total<=100000 or len(rows)>limit
                or (rows and (page-1)*limit+len(rows)>total) or (not rows and (page-1)*limit<total)):
            raise ContractError('INVALID_PAGE')
        seen=set()
        for row in rows:
            if (not isinstance(row,dict) or positive_id(row.get('gid'))!=game_id or positive_id(row.get('cid'))!=category_id
                    or not isinstance(row.get('title'),str)
                    or keyword is not None and keyword.casefold() not in row['title'].casefold()):
                raise ContractError('MODEL_SEARCH_SCOPE_MISMATCH')
            rid=positive_id(row.get('id'))
            if rid in seen:raise ContractError('DUPLICATE_PAGE')
            seen.add(rid)
        return dict(rows=rows,total=total,page=page,page_size=limit,has_more=page*limit<total)

    @classmethod
    def from_shared_session(cls, session_factory=None, token_reader=None):
        # Imports are deferred so local tests do not need production dependencies or sessions.
        if session_factory is None:
            collector = Path('/opt/sales-dashboard/collector')
            if (collector / 'p2pah_auth.py').is_file():
                sys.path.insert(0, str(collector))
                from p2pah_auth import Session
            else:
                from shared_backend_session.sales_auth import Session
            session_factory = Session
        if token_reader is None:
            shared = Path('/opt/fs-shared-session')
            if (shared / 'shared_admin.py').is_file():
                sys.path.insert(0, str(shared))
                from shared_admin import admin_token_from_service
            else:
                from shared_backend_session.shared_admin import admin_token_from_service
            token_reader = admin_token_from_service
        token, _ = token_reader()
        if not token:
            raise ContractError('SHARED_ADMIN_UNAVAILABLE')
        session = session_factory()
        try:
            if not session.bind_admin_token(token):
                raise ContractError('SHARED_ADMIN_UNAVAILABLE')
        except Exception:
            session.close()
            raise ContractError('SHARED_ADMIN_UNAVAILABLE') from None
        finally:
            del token
        return cls(session)

    def close(self):
        self.session.close()

    def _get(self, route, **params):
        try:
            status, payload = self.session.get_admin(route, **params)
            if status != 200 or not isinstance(payload, dict) or payload.get('code') != 1:
                raise ValueError()
            data = payload.get('data')
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except Exception:
            raise ContractError('UPSTREAM_UNAVAILABLE') from None

    def pages(self, resource, filters=(), *, limit=100, validate=None):
        if resource not in LIST_ROUTES or type(limit) is not int or not 1 <= limit <= 200:
            raise ContractError('READ_ROUTE_NOT_ALLOWED')
        result, seen, total = [], set(), None
        for page in range(1, 501):
            data = self._get(LIST_ROUTES[resource], page=page, limit=limit,
                             order='id,desc', **search(filters))
            rows, count = data.get('list'), data.get('total')
            if isinstance(count, str) and count.isascii() and count.isdecimal():
                count = int(count)
            if (not isinstance(rows, list) or type(count) is not int
                    or not 0 <= count <= 100000 or len(rows) > limit):
                raise ContractError('INVALID_PAGE')
            if total is None:
                total = count
            if total != count:
                raise ContractError('PAGINATION_CHANGED')
            for row in rows:
                if not isinstance(row, dict) or row.get('id') is None:
                    raise ContractError('INVALID_ROW')
                rid = identity(str(row['id']))
                if rid in seen:
                    raise ContractError('DUPLICATE_PAGE')
                if validate is not None and not validate(row):
                    raise ContractError('UPSTREAM_SCOPE_MISMATCH')
                seen.add(rid)
                result.append(row)
            if len(result) == total:
                return result
            if not rows or len(result) > total:
                break
        raise ContractError('INCOMPLETE_PAGES')

    def detail(self, resource, object_id):
        if resource not in DETAIL_ROUTES:
            raise ContractError('READ_ROUTE_NOT_ALLOWED')
        row = self._get(DETAIL_ROUTES[resource], id=identity(str(object_id))).get('row')
        if not isinstance(row, dict) or str(row.get('id')) != str(object_id):
            raise ContractError('DETAIL_ID_MISMATCH')
        return row

    def orders(self, site_id, start, end):
        # Raw source time strings and their timezone interpretation are an integration contract.
        return self.pages('orders', [('site_id', '=', site_id), ('paytime', 'RANGE', start + ',' + end)],
                          validate=lambda r: str(r.get('site_id')) == str(site_id)
                          and start <= str(r.get('paytime')) <= end)

    def order_payment_observations(self, site_id, start, end):
        return [payment_observation(row, site_id) for row in self.orders(site_id, start, end)]

    def discover_goods(self, site_id, game_id):
        site_id, game_id = positive_id(site_id), positive_id(game_id)
        return self.pages('goods', [('site_id', '=', site_id), ('gid', '=', game_id)],
            validate=lambda row: positive_id(row.get('site_id')) == site_id
            and positive_id(row.get('gid')) == game_id)

    def search_goods_page(self, site_id, game_id, *, keyword=None, model_id=None,
                          category_id=None, platform_attribute_id=None, page=1, limit=20):
        """One scoped GET only. Field names/order are server-owned, never supplied by the client."""
        site_id, game_id = positive_id(site_id), positive_id(game_id)
        if site_id != '266' or type(page) is not int or not 1 <= page <= 500 or type(limit) is not int or not 1 <= limit <= 50:
            raise ContractError('INVALID_CATALOG_PAGE')
        if (keyword is None) == (model_id is None):
            raise ContractError('CATALOG_QUERY_REQUIRED')
        if keyword is not None and (not isinstance(keyword, str) or not 2 <= len(keyword.strip()) <= 80
                or any(ord(c) < 32 for c in keyword)):
            raise ContractError('INVALID_CATALOG_KEYWORD')
        filters = [('site_id', '=', site_id), ('gid', '=', game_id)]
        expected = {'site_id':site_id, 'gid':game_id}
        for field, value in (('mid',model_id), ('cid',category_id), ('aid',platform_attribute_id)):
            if value is not None:
                expected[field] = positive_id(value)
                filters.append((field, '=', expected[field]))
        params = dict(page=page,limit=limit,order='id,desc',**search(filters))
        if keyword is not None:
            params['quick_search'] = keyword.strip()
        data = self._get_catalog_once(LIST_ROUTES['goods'], **params)
        rows, total = data.get('list'), data.get('total')
        if isinstance(total, str) and total.isascii() and total.isdecimal():
            total = int(total)
        if (not isinstance(rows,list) or type(total) is not int or not 0 <= total <= 100000
                or len(rows) > limit or (rows and (page-1)*limit+len(rows) > total)
                or (not rows and (page-1)*limit < total)):
            raise ContractError('INVALID_PAGE')
        seen = set()
        for row in rows:
            if not isinstance(row,dict):
                raise ContractError('INVALID_ROW')
            rid = positive_id(row.get('id'))
            if rid in seen:
                raise ContractError('DUPLICATE_PAGE')
            if any(positive_id(row.get(field)) != value for field,value in expected.items()):
                raise ContractError('UPSTREAM_SCOPE_MISMATCH')
            seen.add(rid)
        return dict(rows=rows,total=total,page=page,page_size=limit,has_more=page*limit<total)

    def scoped_product(self, site_id, game_id, goods_id):
        site_id, game_id, goods_id = positive_id(site_id), positive_id(game_id), positive_id(goods_id)
        goods = self.detail('goods', goods_id)
        if source_identity(goods.get('site_id')) != site_id or source_identity(goods.get('gid')) != game_id:
            raise ContractError('PRODUCT_SCOPE_MISMATCH')
        model = self.detail('model', positive_id(goods.get('mid')))
        if 'gid' in model and positive_id(model['gid']) != game_id:
            raise ContractError('MODEL_SCOPE_MISMATCH')
        return model, goods

    def coupon_logs(self, site_id, order_numbers):
        selected = {identity(str(n)) for n in order_numbers}
        if any(',' in n for n in selected):
            raise ContractError('INVALID_ORDER_NUMBER')
        result = []
        numbers = sorted(selected)
        for offset in range(0, len(numbers), 100):
            batch = set(numbers[offset:offset + 100])
            result.extend(self.pages('coupon_logs', [('site_id', '=', site_id),
                ('order_no', 'IN', ','.join(sorted(batch)))],
                validate=lambda r: str(r.get('site_id')) == str(site_id)
                and str(r.get('order_no')) in batch))
        return result
