"""Management-only JSON subprocess bridge. No customer data or enabled business writes.

Run from the trusted FS server behind its existing auth/role/CSRF boundary.
"""
import json
import contextlib
import io
import sys
import os
from pathlib import Path

# Repository development layout; deployment may instead provide the shared module on PYTHONPATH.
for parent in Path(__file__).resolve().parents:
    if (parent / 'shared_backend_session' / 'shared_admin.py').is_file():
        sys.path.insert(0, str(parent))
        break

from campaign_backend.adapters import AdminRead
from campaign_backend.catalog import (CatalogMapping, field, project_product, positive_id,
                                      discover_product, read_product_metadata)
from campaign_backend.core import ContractError, source_identity


def capabilities():
    return dict(integration_mode='preview', adapter_version='campaign-backend-v1',
        capabilities=dict(catalog_read=False, benefit_catalog_read=False, coupon_management=False,
            coupon_create=False, coupon_edit=False, coupon_toggle=False, coupon_grant=False,
            order_discount_readback=False, authoritative_quote=False, cart_handoff=False),
        configured_read_routes=True, verification_status='not_verified_by_this_backend',
        implemented_management_actions=['benefit_detail', 'benefit_edit', 'benefit_toggle', 'operation_lookup',
            'operation_reconcile', 'analysis_reconcile', 'analysis_summary', 'catalog_mapping_read'],
        mutation_reason='EXACT_WRITE_AND_READBACK_MAPPING_REQUIRED')


def benefit_projection(row, kind, site_id=None):
    # Field existence verified by controller's 2026-10-24 read-only probe; enum meanings unverified.
    allowed = (('title', 'site_id', 'game_id', 'goods_id', 'start_time', 'end_time', 'days')
               if kind == 'coupons' else ('site_id', 'gid', 'aid', 'cid', 'timestart', 'timeend'))
    result = dict(native_id=source_identity(row.get('id')), kind='coupon' if kind == 'coupons' else 'discount',
                  status_semantics='unknown', verified_for_mutation=False)
    status = row.get('status')
    if type(status) not in (str, int):
        raise ContractError('BENEFIT_STATUS_MISSING')
    result['raw_status'] = status
    if site_id is not None:
        result['scope_status'] = 'global' if str(row.get('site_id')) == '0' else 'exact_site'
        result['bindability'] = 'explicit_native_binding_and_rule_verification_required'
    for key in allowed:
        if key in row and type(row[key]) in (str, int, bool):
            result[key] = row[key]
    return result


def handle(request, reader_factory=AdminRead.from_shared_session, services=None):
    action = request.get('action')
    if action == 'capabilities':
        return capabilities()
    if action == 'catalog_mapping_read':
        if positive_id(request.get('site_id')) != '266' or set(request) - {'action', 'site_id', 'reference_key'}:
            raise ContractError('CATALOG_MAPPING_SCOPE_REQUIRED')
        from campaign_backend.catalog import read_reference_mapping
        path = Path(os.environ.get('CAMPAIGN_CATALOG_MAPPING_PATH', str(Path(__file__).parent / 'catalog-mapping.json')))
        return read_reference_mapping(json.loads(path.read_text('utf-8')), request.get('reference_key'))
    if action in ('benefit_detail', 'benefit_edit', 'benefit_toggle', 'operation_lookup', 'operation_reconcile',
                  'analysis_reconcile', 'analysis_summary'):
        from campaign_backend.services import BackendServices
        return (services or BackendServices.from_environment()).handle(request, reader_factory)
    if action not in ('benefits_read', 'catalog_read', 'catalog_discover', 'product_read'):
        raise ContractError('ACTION_NOT_ALLOWED')
    # Require concrete target scope before acquiring a session.
    site_id = source_identity(request.get('site_id'))
    if site_id == '0':
        raise ContractError('CONCRETE_SITE_REQUIRED')
    if action in ('catalog_discover', 'product_read'):
        site_id, game_id = positive_id(site_id), positive_id(request.get('game_id'))
        if action == 'product_read':
            goods_id = positive_id(request.get('goods_id'))
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
        if action == 'catalog_discover':
            products = [discover_product(row, site_id, game_id)
                        for row in reader.discover_goods(site_id, game_id)]
            return dict(site_id=site_id, game_id=game_id, products=products, total=len(products),
                        completeness='complete', management_only=True, authoritative=False,
                        checkout_enabled=False, verification_scope='observed_admin_metadata')
        if action == 'product_read':
            model, goods = reader.scoped_product(site_id, game_id, goods_id)
            return dict(product=read_product_metadata(model, goods, site_id, game_id),
                        management_only=True, authoritative=False, checkout_enabled=False)
        if action == 'benefits_read':
            site_id = positive_id(site_id)
            if site_id != '266':
                raise ContractError('PROJECT_SITE_REQUIRED')
            rows = {}
            for kind in ('coupons', 'discounts'):
                scoped = reader.pages(kind, [('site_id', 'IN', '0,' + site_id)],
                    validate=lambda row: type(row.get('site_id')) in (str, int) and str(row['site_id']) in ('0', site_id))
                rows[kind] = [benefit_projection(row, kind, site_id) for row in scoped]
            return dict(requested_site_id=site_id, scope_status='exact_or_global_scope_verified',
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
