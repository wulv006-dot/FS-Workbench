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
from campaign_backend.models import request_scope, project_model, resolve_model, historical_image, player_type
from campaign_backend.provider import (scope as provider_scope, model_provider, model_provider_batch,
                                      category_pool, resolve_category_pool)
from campaign_backend.discount_revenue import read_revenue, query_window


def model_image(model):
    """Fixed server artifacts; no client paths, name matching, or fresh Admin image claim."""
    if model.get('image_url'):return model
    try:
        from campaign_backend.catalog import read_reference_mapping
        backend=Path(__file__).parent
        mapping=read_reference_mapping(json.loads((backend/'catalog-mapping.json').read_text('utf-8')))
        catalog=backend.parent/'catalog.json'
        if not catalog.is_file():catalog=backend.parent/'app'/'catalog.json'
        image=historical_image(model['model_id'],mapping,json.loads(catalog.read_text('utf-8')))
        if image:model.update(image_url=image,image_provenance='historical_accepted_model_asset')
    except (OSError,ValueError,TypeError,KeyError):
        pass
    return model


def capabilities():
    return dict(integration_mode='preview', adapter_version='campaign-backend-v1',
        capabilities=dict(catalog_read=False, benefit_catalog_read=False, coupon_management=False,
            coupon_create=False, coupon_edit=False, coupon_toggle=False, coupon_grant=False,
            order_discount_readback=False, authoritative_quote=False, cart_handoff=False),
        configured_read_routes=True, verification_status='not_verified_by_this_backend',
        implemented_management_actions=['benefit_detail', 'benefit_edit', 'benefit_toggle', 'benefit_restore', 'operation_lookup',
            'operation_reconcile', 'analysis_reconcile', 'analysis_summary', 'discount_revenue', 'catalog_mapping_read'],
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
    if action == 'weekly_selection':
        if set(request) != {'action','site_id','game_id'} or str(request.get('site_id')) != '266' or str(request.get('game_id')) != '1327':
            raise ContractError('WEEKLY_PROJECT_SCOPE_REQUIRED')
        from campaign_backend.weekly import weekly_selection
        reader = reader_factory()
        try:
            return weekly_selection(reader)
        finally:
            reader.close()
    if action == 'capabilities':
        return capabilities()
    if action == 'discount_revenue':
        query_window(request)
        reader = reader_factory()
        try:
            return read_revenue(reader, request)
        finally:
            reader.close()
    if action == 'model_provider_batch':
        # Same observed-only semantics as model_provider_read, but the caller may ask for
        # a whole game's models in one process so the catalogue is swept once, not once
        # per model.
        if set(request) - {'action', 'items', 'site_id'}:
            raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
        if positive_id(request.get('site_id')) != '266':
            raise ContractError('PROJECT_SITE_REQUIRED')
        items = request.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            raise ContractError('INVALID_BATCH_ITEMS')
        parsed = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {'key', 'site_id', 'game_id', 'model_id', 'category_id'}:
                raise ContractError('INVALID_BATCH_ITEMS')
            key = item.get('key')
            if not isinstance(key, str) or not 1 <= len(key) <= 200:
                raise ContractError('INVALID_BATCH_ITEMS')
            site_id, game_id, model_id, category_id = (positive_id(item.get(name))
                for name in ('site_id', 'game_id', 'model_id', 'category_id'))
            if site_id != '266':
                raise ContractError('PROJECT_SITE_REQUIRED')
            parsed.append(dict(key=key, site_id=site_id, game_id=game_id, model_id=model_id,
                category_id=category_id))
        reader = reader_factory()
        try:
            return model_provider_batch(reader, parsed)
        finally:
            reader.close()
    if action in ('model_provider_read','model_category_pool'):
        args=provider_scope(request,pool=action=='model_category_pool')
        fixed=set()
        if action=='model_category_pool':
            # Fixed accepted references are server-owned, never supplied by an HTTP client.
            from campaign_backend.catalog import read_reference_mapping
            try:
                artifact=read_reference_mapping(json.loads((Path(__file__).parent/'catalog-mapping.json').read_text('utf-8')))
                fixed={positive_id(row['product_ref']['model_id']) for row in artifact['mappings'].values()
                    if row['product_ref']['site_id']==args['site_id'] and row['product_ref']['game_id']==args['game_id']}
            except (OSError,ValueError,TypeError,KeyError):
                raise ContractError('CATALOG_FIXED_REFERENCES_UNAVAILABLE') from None
        reader=reader_factory()
        try:
            if action=='model_category_pool' and args['resolve_associations']:
                return resolve_category_pool(reader,args,fixed)
            reader.begin_catalog_read()
            return category_pool(reader,args,fixed) if action=='model_category_pool' else model_provider(reader,args)
        finally:reader.close()
    if action in ('model_search','model_resolve'):
        args=request_scope(request,resolve=action=='model_resolve')
        reader=reader_factory()
        try:
            reader.begin_catalog_read()
            if action=='model_resolve':
                row=reader.catalog_model(args['model_id'])
                project_model(row,args['kind'])
                page=reader.search_goods_page('266','1327',model_id=args['model_id'],category_id=args['category_id'],page=1,limit=10)
                return dict(model=model_image(resolve_model(row,args['kind'],page)),resolution_complete=page['total']==len(page['rows']),
                    player_type=player_type(row) if args['kind']=='player' else None,
                    management_only=True,authoritative=False,available=False,checkout_enabled=False)
            if 'model_id' in args:
                row=reader.catalog_model(args['model_id'])
                rows=[row];total=1;has_more=False
            else:
                page=reader.search_models_page('1327',args['category_id'],args['keyword'],args['page'],args['page_size'])
                rows,total,has_more=page['rows'],page['total'],page['has_more']
            return dict(items=[model_image(project_model(row,args['kind'])) for row in rows],total=total,
                page=args['page'],page_size=args['page_size'],has_more=has_more,
                name_query=args.get('name_query'),management_only=True,available=False,authoritative=False,checkout_enabled=False,
                verification_scope='model_candidates_site_association_pending')
        finally:reader.close()
    if action == 'catalog_search':
        allowed = {'action','site_id','game_id','keyword','goods_id','model_id','category_id','platform_attribute_id','page','page_size'}
        if set(request)-allowed:
            raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
        site_id, game_id = positive_id(request.get('site_id')), positive_id(request.get('game_id'))
        if site_id != '266':
            raise ContractError('PROJECT_SITE_REQUIRED')
        queries = [key for key in ('keyword','goods_id','model_id') if key in request]
        if len(queries) != 1:
            raise ContractError('CATALOG_QUERY_REQUIRED')
        query = queries[0]
        page, size = request.get('page',1), request.get('page_size',20)
        if type(page) is not int or not 1<=page<=500 or type(size) is not int or not 1<=size<=50:
            raise ContractError('INVALID_CATALOG_PAGE')
        values = {key:positive_id(request[key]) for key in ('goods_id','model_id','category_id','platform_attribute_id') if key in request}
        if query == 'keyword':
            keyword = request['keyword']
            if not isinstance(keyword,str) or not 2<=len(keyword.strip())<=80 or any(ord(c)<32 for c in keyword):
                raise ContractError('INVALID_CATALOG_KEYWORD')
        if query == 'goods_id' and page != 1:
            raise ContractError('EXACT_GOODS_PAGE_REQUIRED')
        reader = reader_factory()
        try:
            if query == 'goods_id':
                row = reader.catalog_goods(values['goods_id'])
                product = discover_product(row,site_id,game_id,allow_unknown=True)
                matches = all(product[field] == values[key] for key,field in
                    (('category_id','category_id'),('platform_attribute_id','platform_attribute_id')) if key in values)
                rows = [row] if matches else []
                result = dict(rows=rows,total=len(rows),page=1,page_size=size,has_more=False)
            else:
                result = reader.search_goods_page(site_id,game_id,keyword=request['keyword'] if query=='keyword' else None,
                    model_id=values.get('model_id'),category_id=values.get('category_id'),
                    platform_attribute_id=values.get('platform_attribute_id'),page=page,limit=size)
            return dict(items=[discover_product(row,site_id,game_id,allow_unknown=True) for row in result['rows']],
                site_id=site_id,game_id=game_id,total=result['total'],page=result['page'],page_size=result['page_size'],
                has_more=result['has_more'],completeness='single_page',management_only=True,
                authoritative=False,available=False,checkout_enabled=False,
                search_verification=dict(query='exact_goods_detail' if query=='goods_id' else 'source_protocol_not_live_verified',
                    filters='raw_admin_fields_not_business_labels',pagination='single_response_only'))
        finally:
            reader.close()
    if action == 'catalog_mapping_read':
        if positive_id(request.get('site_id')) != '266' or set(request) - {'action', 'site_id', 'reference_key'}:
            raise ContractError('CATALOG_MAPPING_SCOPE_REQUIRED')
        from campaign_backend.catalog import read_reference_mapping
        path = Path(os.environ.get('CAMPAIGN_CATALOG_MAPPING_PATH', str(Path(__file__).parent / 'catalog-mapping.json')))
        return read_reference_mapping(json.loads(path.read_text('utf-8')), request.get('reference_key'))
    if action in ('coupon_candidates', 'benefit_detail', 'benefit_edit', 'benefit_toggle', 'benefit_restore', 'operation_lookup', 'operation_reconcile',
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
            if set(request)-{'action','site_id','game_id','goods_id'}:
                raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
            if site_id != '266':
                raise ContractError('PROJECT_SITE_REQUIRED')
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
            return dict(product=read_product_metadata(model, goods, site_id, game_id,allow_unknown=True),
                        management_only=True, authoritative=False,available=False,checkout_enabled=False)
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
