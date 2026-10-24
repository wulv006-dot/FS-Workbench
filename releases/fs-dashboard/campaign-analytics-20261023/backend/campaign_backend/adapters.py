"""Allowlisted GET access using the existing shared owner session; no new login."""
import sys
from pathlib import Path
from .core import ContractError, identity

LIST_ROUTES = {
    'models': '/admin/goods.GoodsMould/index',
    'goods': '/admin/goods.Goods/index',
    'discounts': '/admin/market.Discount/index',
    'coupons': '/admin/market.Coupon/index',
    'coupon_logs': '/admin/user.MemberCouponLog/index',
    'orders': '/admin/order.Order/index',
}
DETAIL_ROUTES = {'model': '/admin/goods.GoodsMould/edit', 'goods': '/admin/goods.Goods/edit'}


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
    def __init__(self, session):
        self.session = session

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
