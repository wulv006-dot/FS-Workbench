"""Bounded, read-only FC weekly selection from current Admin metadata.

Identity observations do not authorize prices, cart attributes or publication.
"""
from datetime import datetime, timezone
from .adapters import search
from .core import ContractError
from .models import KINDS, resolve_model
from .provider import project_source


def _rows(data, limit):
    rows, total = data.get('list'), data.get('total')
    if isinstance(total, str) and total.isdecimal(): total = int(total)
    if not isinstance(rows, list) or type(total) is not int or total < len(rows) or len(rows) > limit:
        raise ContractError('WEEKLY_CATALOG_SHAPE_INVALID')
    return rows, total


def weekly_selection(reader):
    def get(route, **params):
        reader.begin_catalog_read()
        return reader._get_catalog_once(route, **params)

    tree = get('/admin/goods.GoodsCategory/categorySelect', gid=1327).get('list')
    found = {}
    def visit(rows, parent=None):
        if not isinstance(rows, list): raise ContractError('WEEKLY_CATEGORY_UNVERIFIED')
        for row in rows:
            if not isinstance(row, dict): raise ContractError('WEEKLY_CATEGORY_UNVERIFIED')
            title = row.get('title')
            if title == 'Players' or title == 'SBC Players' and parent == 'SBC':
                if title in found: raise ContractError('WEEKLY_CATEGORY_AMBIGUOUS')
                found[title] = str(row.get('id'))
            visit(row.get('children', []), title)
    visit(tree)
    if found != {'Players': KINDS['player'], 'SBC Players': KINDS['sbc']}:
        raise ContractError('WEEKLY_CATEGORY_CHANGED')
    tags, expected = [], None
    for page in range(1, 7):
        rows, total = _rows(get('/admin/goods.GoodsTag/index', page=page, limit=500,
                                quick_search='%', order='sort,desc'), 500)
        if expected is not None and expected != total: raise ContractError('PAGINATION_CHANGED')
        expected = total; tags.extend(rows)
        if len(tags) >= total: break
    if len(tags) != expected or len({str(x.get('id')) for x in tags}) != len(tags):
        raise ContractError('WEEKLY_TAG_COVERAGE_INCOMPLETE')
    matches = [t for t in tags if str(t.get('gid')) == '1327' and t.get('name') == 'Popular'
               and str(t.get('status')) == '1' and '9627' in [str(x) for x in t.get('cate_id', [])]]
    if len(matches) != 1: raise ContractError('WEEKLY_POPULAR_TAG_AMBIGUOUS')
    tag_id = str(matches[0]['id'])

    def models(cid, order, page=1, limit=200):
        rows, total = _rows(get('/admin/goods.GoodsMould/index', page=page, limit=limit,
                               order=order, **search([('gid', '=', '1327'), ('cid', '=', cid)])), limit)
        if any(str(r.get('gid')) != '1327' or str(r.get('cid')) != cid for r in rows):
            raise ContractError('MODEL_SCOPE_MISMATCH')
        return rows, total
    eligible = lambda r: str(r.get('status')) == '1' and str(r.get('auto_off')) == '0' and str(r.get('is_put')) == '1'
    latest, player_total = models('9627', 'id,desc', limit=20)
    if any(int(a['id']) <= int(b['id']) for a, b in zip(latest, latest[1:])):
        raise ContractError('PAGINATION_ORDER_CHANGED')
    players = [r for r in latest if eligible(r)][:16]
    cores, core_total = models('10203', 'id,desc', limit=20)
    if any(int(a['id']) <= int(b['id']) for a, b in zip(cores, cores[1:])):
        raise ContractError('PAGINATION_ORDER_CHANGED')
    cores = [r for r in cores if eligible(r)][:3]
    popular, scanned, seen, anchor, popular_total = [], 0, set(), None, None
    for page in range(1, 7):
        rows, total = models('9627', 'sort,desc', page=page)
        if popular_total is not None and popular_total != total: raise ContractError('PAGINATION_CHANGED')
        popular_total = total
        if page == 1: anchor = rows
        for row in rows:
            key = str(row['id'])
            if key in seen: raise ContractError('PAGINATION_CHANGED')
            seen.add(key)
            if tag_id in [str(x) for x in row.get('tid', [])] and eligible(row): popular.append(row)
        scanned += len(rows)
        if len(popular) >= 3 or scanned >= total: break
    if len(popular) < 3: raise ContractError('WEEKLY_POPULAR_TOP_THREE_UNAVAILABLE')
    if page > 1 and models('9627', 'sort,desc')[0] != anchor: raise ContractError('PAGINATION_CHANGED')
    popular = popular[:3]
    if len(players) < 3 or not cores: raise ContractError('WEEKLY_SOURCE_POOL_EMPTY')
    chosen = {str(r['id']): (r, 'player') for r in players + popular}
    chosen.update({str(r['id']): (r, 'sbc') for r in cores})
    resolved, observations, provider_observations = [], [], []
    for mid, (row, kind) in chosen.items():
        reader.begin_catalog_read()
        goods = reader.search_goods_page('266', '1327', model_id=mid, category_id=KINDS[kind], page=1, limit=20)
        model = resolve_model(row, kind, goods)
        if model['site_association'] != 'observed': raise ContractError('MODEL_SITE_ASSOCIATION_MISSING')
        resolved.append(model)
        args = dict(site_id='266', game_id='1327', category_id=KINDS[kind], model_id=mid)
        details = []
        for item in goods['rows']:
            reader.begin_catalog_read()
            detail = reader.catalog_goods(str(item['id']))
            projected = project_source(detail, args)
            # Missing option structures are unknown, never an empty-cart assertion.
            projected['option_structures_observed'] = isinstance(detail.get('more'), dict) and all(k in detail['more'] for k in ('saleprop', 'skuTableSet'))
            details.append(projected)
        provider_observations.append(dict(source='admin_readonly', observed_at=datetime.now(timezone.utc).isoformat(),
            model=project_source(row,args,True), products=details, coverage=dict(complete=goods['total']==len(goods['rows'])),
            authoritative=False, available=False, checkout_enabled=False))
        source_roles = []
        if any(str(r['id']) == mid for r in popular): source_roles.append(dict(role='scout_popular', order='sort,desc'))
        if any(str(r['id']) == mid for r in players): source_roles.append(dict(role='latest_player', order='id,desc'))
        if any(str(r['id']) == mid for r in cores): source_roles.append(dict(role='latest_sbc', order='id,desc'))
        observations.append(dict(model_id=mid, source_roles=source_roles, shelf_time=row.get('shelf_time'),
            created_at=None, goods_complete=goods['total'] == len(goods['rows']),
            platforms=[dict(goods_id=str(g['id']), attribute_id=str(g.get('aid')), region_id=str(g.get('sid')),
                quantity_group=g.get('num'), minimum=g.get('min_qty'), attributes_required=str(g.get('attr_switch')) == '1',
                sku_required=str(g.get('sku_switch')) == '1') for g in goods['rows']],
            quote_verified=False, checkout_verified=False))
    return dict(observed_at=datetime.now(timezone.utc).isoformat(), rules_version='fc27_weekly_selection_v1',
        models=resolved, latest_player_ids=[str(r['id']) for r in players],
        trio_player_ids=[str(r['id']) for r in players[:6]], scout_model_ids=[str(r['id']) for r in popular],
        sbc_model_ids=[str(r['id']) for r in cores], observations=observations, provider_observations=provider_observations,
        evidence=dict(categories=found, popular_tag_id=tag_id, tag_count=len(tags), tags_complete=True,
            popular_order='sort,desc', popular_scanned=scanned, popular_total=popular_total,
            latest_order='id,desc', latest_semantics='newest_model_identity_not_creation_timestamp',
            player_total=player_total, sbc_total=core_total, snapshot_atomic=False),
        publication=False, authoritative_quote=False, checkout_enabled=False)
