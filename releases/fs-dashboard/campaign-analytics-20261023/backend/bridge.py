"""Management-only JSON subprocess bridge. No customer data or enabled business writes.

Run from the trusted FS server behind its existing auth/role/CSRF boundary.
"""
import json
import contextlib
import io
import sys
from pathlib import Path

# Repository development layout; deployment may instead provide the shared module on PYTHONPATH.
for parent in Path(__file__).resolve().parents:
    if (parent / 'shared_backend_session' / 'shared_admin.py').is_file():
        sys.path.insert(0, str(parent))
        break

from campaign_backend.adapters import AdminRead
from campaign_backend.catalog import CatalogMapping, field, project_product
from campaign_backend.core import ContractError, source_identity


def capabilities():
    return dict(integration_mode='preview', adapter_version='campaign-backend-v1',
        capabilities=dict(catalog_read=False, benefit_catalog_read=False, coupon_management=False,
            coupon_create=False, coupon_edit=False, coupon_toggle=False, coupon_grant=False,
            order_discount_readback=False, authoritative_quote=False, cart_handoff=False),
        configured_read_routes=True, verification_status='not_verified_by_this_backend',
        mutation_reason='EXACT_WRITE_AND_READBACK_MAPPING_REQUIRED')


def benefit_projection(row, kind):
    # Field existence verified by controller's 2026-10-24 read-only probe; enum meanings unverified.
    allowed = (('title', 'site_id', 'game_id', 'goods_id', 'start_time', 'end_time', 'days')
               if kind == 'coupons' else ('site_id', 'gid', 'aid', 'cid', 'timestart', 'timeend'))
    result = dict(native_id=source_identity(row.get('id')), kind='coupon' if kind == 'coupons' else 'discount',
                  status_semantics='unknown', verified_for_mutation=False)
    status = row.get('status')
    if type(status) not in (str, int):
        raise ContractError('BENEFIT_STATUS_MISSING')
    result['raw_status'] = status
    for key in allowed:
        if key in row and type(row[key]) in (str, int, bool):
            result[key] = row[key]
    return result


def handle(request, reader_factory=AdminRead.from_shared_session):
    action = request.get('action')
    if action == 'capabilities':
        return capabilities()
    if action not in ('benefits_read', 'catalog_read'):
        raise ContractError('ACTION_NOT_ALLOWED')
    # Require concrete target scope before acquiring a session.
    site_id = source_identity(request.get('site_id'))
    if site_id == '0':
        raise ContractError('CONCRETE_SITE_REQUIRED')
    if action == 'catalog_read':
        game_id = source_identity(request.get('game_id'))
        try:
            mapping = CatalogMapping(**request['mapping'])
            purchases = request['purchases']
            if not isinstance(purchases, dict) or not mapping.verification_ref:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ContractError('CATALOG_MAPPING_REQUIRED') from None
    reader = reader_factory()
    try:
        if action == 'benefits_read':
            # Scope expressions in these sources vary (scalar/list/ALL); preserve scope and let
            # management inspect it. Never claim filtered eligibility from title or status.
            rows = {}
            for kind in ('coupons', 'discounts'):
                rows[kind] = [benefit_projection(row, kind) for row in reader.pages(kind)]
            return dict(requested_site_id=site_id, scope_status='raw_scope_requires_verification',
                        management_only=True, **rows)
        goods = reader.pages('goods', [('site_id', '=', site_id), ('gid', '=', game_id)],
            validate=lambda r: source_identity(field(r, mapping.goods_fields['site_id'])) == site_id
            and source_identity(field(r, mapping.goods_fields['game_id'])) == game_id)
        products, unresolved, models = [], [], {}
        for row in goods:
            goods_id = source_identity(field(row, mapping.goods_fields['goods_id']))
            if goods_id not in purchases:
                unresolved.append(dict(goods_id=goods_id, reason='PURCHASE_MAPPING_REQUIRED'))
                continue
            model_id = source_identity(field(row, mapping.goods_fields['model_id']))
            if model_id not in models:
                models[model_id] = reader.detail('model', model_id)
            products.append(project_product(models[model_id], row, mapping, purchases[goods_id]))
        return dict(products=products, unresolved=unresolved, authoritative=False,
                    verification_status='mapping_supplied_by_integrator')
    finally:
        reader.close()


def main():
    try:
        raw = sys.stdin.buffer.read(300001)
        if len(raw) > 300000:
            raise ContractError('REQUEST_TOO_LARGE')
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ContractError('INVALID_REQUEST')
        # Legacy Session logs to stdout. Do not expose its messages or break the JSON protocol.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            data = handle(request)
        result = dict(status='ok', data=data)
    except ContractError as error:
        result = dict(status='error', error=str(error))
    except Exception:
        result = dict(status='error', error='BACKEND_UNAVAILABLE')
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
