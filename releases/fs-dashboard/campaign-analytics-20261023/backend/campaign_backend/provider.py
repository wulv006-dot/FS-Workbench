"""Bounded management-only Admin observations, never an authoritative quote or sellable pool."""
import hashlib
import json
import re
import math
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from .catalog import positive_id, specification_projection
from .core import ContractError
from .models import label, observed_quantity


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,
        allow_nan=False).encode()).hexdigest()


def scope(request,pool=False):
    allowed={'action','site_id','game_id','category_id'} | (
        {'keyword','max_pages','page_size','exclude_model_ids','resolve_associations'} if pool else {'model_id'})
    if set(request)-allowed:raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
    site,game,category=(positive_id(request.get(k)) for k in ('site_id','game_id','category_id'))
    if site!='266':raise ContractError('PROJECT_SITE_REQUIRED')
    result=dict(site_id=site,game_id=game,category_id=category)
    if not pool:
        result['model_id']=positive_id(request.get('model_id'));return result
    pages,size=request.get('max_pages',1),request.get('page_size',10)
    if type(pages) is not int or not 1<=pages<=3 or type(size) is not int or not 1<=size<=20:
        raise ContractError('INVALID_CATALOG_PAGE')
    keyword=request.get('keyword')
    if keyword is not None:
        if not isinstance(keyword,str) or not 2<=len(keyword.strip())<=80 or any(ord(c)<32 for c in keyword):
            raise ContractError('INVALID_CATALOG_KEYWORD')
        keyword=keyword.strip()
    excluded=request.get('exclude_model_ids',[])
    if not isinstance(excluded,list) or len(excluded)>100:raise ContractError('INVALID_MODEL_EXCLUSIONS')
    resolve=request.get('resolve_associations',False)
    if type(resolve) is not bool:raise ContractError('INVALID_RESOLVE_ASSOCIATIONS')
    result.update(max_pages=pages,page_size=size,keyword=keyword,excluded={positive_id(v) for v in excluded},
        resolve_associations=resolve)
    return result


def decimal_observation(value,positive=False):
    # Source numbers only, no symbols, exponent strings, conversion, currency assumption or rounding.
    if type(value) not in (int,float,str):return None
    text=str(value)
    if not re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,12})?',text):return None
    try:number=Decimal(text)
    except InvalidOperation:return None
    if not number.is_finite() or positive and number<=0:return None
    return format(number,'f')


def optional_id(row,key):
    try:return positive_id(row.get(key))
    except ContractError:return None


def raw_state(row):
    return {key:row.get(key) if type(row.get(key)) in (int,str) and row[key] in (0,1,'0','1') else None
        for key in ('status','buy_status','auto_off','sku_switch','attr_switch')}


def identity(row,args,model=False):
    if (not isinstance(row,dict) or positive_id(row.get('gid'))!=args['game_id']
            or positive_id(row.get('cid'))!=args['category_id']):
        raise ContractError('PROVIDER_SCOPE_MISMATCH')
    rid=positive_id(row.get('id'))
    if model:
        if args.get('model_id',rid)!=rid:raise ContractError('DETAIL_ID_MISMATCH')
    elif (positive_id(row.get('site_id'))!=args['site_id']
            or positive_id(row.get('mid'))!=args['model_id']):
        raise ContractError('PROVIDER_SCOPE_MISMATCH')
    return rid


def tier_observations(row):
    more=row.get('more')
    if not isinstance(more,dict):return [],'QUANTITY_TABLE_NOT_OBSERVED'
    arrays=[more.get(k) for k in ('gold','price','discount')]
    if all(v is None for v in arrays):return [],'QUANTITY_TABLE_NOT_OBSERVED'
    if (any(not isinstance(v,list) for v in arrays) or not 0<len(arrays[0])<=100
            or len({len(v) for v in arrays})!=1):
        return [],'QUANTITY_TABLE_SHAPE_UNVERIFIED'
    tiers=[];seen=set()
    for index,(quantity,price,discount) in enumerate(zip(*arrays)):
        qty=decimal_observation(quantity,True);price=decimal_observation(price);discount=decimal_observation(discount)
        if qty is None or price is None or discount is None or Decimal(qty) in seen:
            return [],'QUANTITY_TABLE_VALUE_UNVERIFIED'
        seen.add(Decimal(qty))
        tiers.append(dict(source_index=index,quantity=qty,unit=observed_quantity(row)['unit'] if observed_quantity(row) else None,
            source_price=price,source_discount=discount,currency=None,authoritative=False))
    return tiers,None


def specification(row):
    more=row.get('more')
    return {key:dict(present=isinstance(more,dict) and key in more,
        observed=specification_projection(more[key]) if isinstance(more,dict) and key in more else None)
        for key in ('saleprop','skuTableSet','baseprop')}


def project_source(row,args,model=False):
    rid=identity(row,args,model)
    tiers,warning=tier_observations(row)
    result=dict(model_id=rid if model else args['model_id'],title=label(row.get('title')),
        game_id=args['game_id'],category_id=args['category_id'],region_id=optional_id(row,'sid'),
        platform_attribute_id=optional_id(row,'aid'),raw_state=raw_state(row),quantity=observed_quantity(row),
        tiers=tiers,source_unit_price=decimal_observation(row.get('unit_price')) if not model else None,
        source_display_price=decimal_observation(row.get('full_price_format')),
        source_price=decimal_observation(row.get('price')),source_discount=decimal_observation(row.get('discount')),
        specification=specification(row),currency=None,authoritative=False,available=False,checkout_enabled=False,
        warnings=[warning] if warning else [],verification_scope='observed_admin_fields_not_cart_serialization')
    if not model:result['product_ref']=dict(site_id=args['site_id'],game_id=args['game_id'],model_id=args['model_id'],goods_id=rid)
    return result


def bounded_pages(fetch,max_pages,size):
    """No snapshot claim: detect observed drift/overlap, bound all reads, recheck first-page anchor."""
    first=fetch(1);total=first['total'];rows=[];seen={};reason=None;pages_read=0
    previous=None
    for page_number in range(1,max_pages+1):
        page=first if page_number==1 else fetch(page_number)
        pages_read+=1
        if page['total']!=total:raise ContractError('PAGINATION_CHANGED')
        page_rows=page['rows']
        expected=min(size,max(0,total-(page_number-1)*size))
        if len(page_rows)!=expected:raise ContractError('INCOMPLETE_PAGES')
        overlap=False
        for row in page_rows:
            rid=positive_id(row.get('id'));fingerprint=digest(row)
            if rid in seen:
                if seen[rid]!=fingerprint:raise ContractError('PAGINATION_CHANGED')
                overlap=True;continue
            if previous is not None and int(rid)>=previous:raise ContractError('PAGINATION_ORDER_CHANGED')
            previous=int(rid);seen[rid]=fingerprint;rows.append(row)
        if overlap:reason='PAGINATION_OVERLAP';break
        if not page['has_more']:break
    if reason is None and len(rows)<total:reason='PAGE_LIMIT_REACHED'
    if pages_read>1:
        check=fetch(1)
        if check['total']!=total or digest(check['rows'])!=digest(first['rows']):
            raise ContractError('PAGINATION_CHANGED')
    return rows,dict(complete=reason is None,reason=reason,observed_count=len(rows),reported_total=total,
        pages_read=pages_read,page_size=size,max_pages=max_pages,row_limit=max_pages*size,
        anchor_rechecked=pages_read>1,snapshot_atomic=False,sellability_verified=False)


def model_provider(reader,args):
    model=reader.catalog_model(args['model_id']);projected=project_source(model,args,True)
    rows,coverage=bounded_pages(lambda page:reader.search_goods_page(args['site_id'],args['game_id'],
        model_id=args['model_id'],category_id=args['category_id'],page=page,limit=50),4,50)
    # Admin's association LIST omits formatted one-item totals. Read the
    # existing detail endpoint only for bounded rows which actually need it;
    # never infer rounding from a raw high-precision unit price.
    detail_rows=[];detail_count=0
    for row in rows:
        tiers,_=tier_observations(row)
        if not tiers and decimal_observation(row.get('full_price_format')) is None:
            detail_count+=1
            if detail_count>12:raise ContractError('ASSOCIATION_DETAIL_LIMIT')
            rid=identity(row,args)
            current=reader.catalog_goods(rid)
            if identity(current,args)!=rid:raise ContractError('DETAIL_ID_MISMATCH')
            row=current
        detail_rows.append(row)
    products=[project_source(row,args) for row in detail_rows]
    warnings=['CURRENCY_MAPPING_REQUIRED','CART_SERIALIZATION_UNVERIFIED','SELLABILITY_UNVERIFIED']
    if not coverage['complete']:warnings.append('ASSOCIATION_INCOMPLETE')
    if not rows:warnings.append('SITE_ASSOCIATION_NOT_OBSERVED')
    return dict(model=projected,products=products,coverage=coverage,currency=None,management_only=True,
        source='admin_readonly',observed_at=datetime.now(timezone.utc).isoformat(),
        site_association='observed' if rows else 'not_observed',authoritative=False,available=False,
        checkout_enabled=False,warnings=warnings,verification_scope='observed_admin_provider_only')


def model_provider_batch(reader,items):
    """Observe several models with one catalogue sweep per game.

    The list route is the slow, occasionally stalling call, so one sweep per game
    replaces one sweep per model. Failures stay per model and per game, mirroring the
    single-model action: a stalled game is reported for its own models only instead of
    taking every other game's prices down with it.
    """
    groups={}
    for item in items:
        groups.setdefault((item['site_id'],item['game_id']),[]).append(item)
    readings={}
    for (site_id,game_id),group in sorted(groups.items()):
        try:
            reader.begin_catalog_read()
            reader.prefetch_goods(site_id,game_id,[item['model_id'] for item in group])
            # The sweep gets its own window; the per-model details below must not inherit
            # a budget the sweep already spent.
            reader.reset_catalog_budget()
        except ContractError as error:
            code=str(error)
            code=code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) else 'ASSOCIATION_READ_FAILED'
            for item in group:readings[item['key']]=dict(status='error',error=code)
            continue
        for item in group:
            args=dict(site_id=site_id,game_id=game_id,category_id=item['category_id'],model_id=item['model_id'])
            try:
                # Each model detail gets its own window. Sharing one window across 44 models
                # made the last ones time out purely because the earlier ones spent it.
                reader.reset_catalog_budget()
                readings[item['key']]=dict(status='ok',data=model_provider(reader,args))
            except ContractError as error:
                # Only fixed project codes cross the process boundary, never upstream text.
                code=str(error)
                readings[item['key']]=dict(status='error',
                    error=code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) else 'ASSOCIATION_READ_FAILED')
    return dict(readings=readings)


def category_pool(reader,args,fixed_ids):
    rows,coverage=bounded_pages(lambda page:reader.search_models_page(args['game_id'],args['category_id'],
        args['keyword'],page,args['page_size']),args['max_pages'],args['page_size'])
    exclusions=set(fixed_ids)|args['excluded'];items=[];excluded=0
    for row in rows:
        rid=identity(row,args,True)
        if rid in exclusions:excluded+=1;continue
        items.append(dict(model_id=rid,title=label(row.get('title')),game_id=args['game_id'],category_id=args['category_id'],
            raw_state=raw_state(row),site_association='not_yet_verified',authoritative=False,available=False,checkout_enabled=False))
    return dict(items=items,coverage=coverage,excluded_count=excluded,eligible_for_draw=False,
        source='admin_readonly',observed_at=datetime.now(timezone.utc).isoformat(),
        blocked_reasons=['SITE_ASSOCIATIONS_NOT_RESOLVED','SELLABILITY_UNVERIFIED','CURRENCY_MAPPING_REQUIRED'],
        management_only=True,authoritative=False,available=False,checkout_enabled=False,
        verification_scope='bounded_category_candidates_not_sellable_pool')


def original_guard(state):
    """Original activity-core status/auto_off guard; no new sale/status semantics."""
    if state['status'] is None or state['auto_off'] is None:return 'unknown'
    return 'observed_original_guard' if str(state['status'])=='1' and str(state['auto_off'])=='0' else 'original_guard_failed'


def resolve_category_pool(reader,args,fixed_ids):
    """Explicit, bounded site associations; never truncate a larger pool into a complete one."""
    reader.begin_catalog_read()
    result=category_pool(reader,args,fixed_ids)
    coverage=dict(requested=True,complete=False,model_budget=3,models_attempted=0,models_resolved=0,
        reason=None,aggregate_deadline_seconds=20)
    result['association_coverage']=coverage
    if not result['coverage']['complete']:
        coverage['reason']='CATEGORY_PAGINATION_INCOMPLETE';return result
    if len(result['items'])>3:
        coverage['reason']='MODEL_RESOLUTION_BUDGET_EXCEEDED';return result
    for item in result['items']:
        coverage['models_attempted']+=1
        try:
            provider=model_provider(reader,dict(site_id=args['site_id'],game_id=args['game_id'],
                category_id=args['category_id'],model_id=item['model_id']))
        except ContractError as error:
            # All exposed codes are fixed project contract codes, never arbitrary upstream messages.
            code=str(error)
            coverage['reason']=code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',code) else 'ASSOCIATION_READ_FAILED'
            return result
        item['association']=provider
        item['site_association']=provider['site_association']
        item['original_guard_observation']=original_guard(provider['model']['raw_state'])
        for product in provider['products']:
            own_guard=original_guard(product['raw_state'])
            product['original_guard_observation']=(own_guard if item['original_guard_observation']=='observed_original_guard'
                else item['original_guard_observation'])
        if not provider['coverage']['complete']:
            coverage['reason']='PRODUCT_ASSOCIATIONS_INCOMPLETE';return result
        coverage['models_resolved']+=1
    coverage['complete']=True
    result['blocked_reasons']=['SELLABILITY_UNVERIFIED','CURRENCY_MAPPING_REQUIRED','CART_SERIALIZATION_UNVERIFIED']
    if any(item['site_association']!='observed' for item in result['items']):
        result['blocked_reasons'].append('SITE_ASSOCIATION_NOT_OBSERVED')
    result['observed_at']=datetime.now(timezone.utc).isoformat()
    return result


def preview_eligibility(pool,server_policy,*,now):
    """Pure trusted-server rule, never accept pool/policy/clock from an HTTP client.

    Caller supplies explicit freshness policy and fixed IDs from its accepted references.
    Admin timestamp/provenance is trusted only because that caller owns the actual reader;
    this function cannot authenticate an arbitrary JSON object or prove a future sale.
    """
    output=dict(eligible_for_preview=False,candidates=[],candidate_count=0,excluded=[],blocked_reasons=[],
        warnings=['TRANSACTION_SELLABILITY_UNVERIFIED','CURRENCY_MAPPING_REQUIRED','CART_SERIALIZATION_UNVERIFIED'],
        authoritative=False,eligible_for_draw=False,checkout_enabled=False,
        verification_scope='observed_original_guard_preview_only')
    def blocked(reason):
        output['blocked_reasons'].append(reason);return output
    required={'site_id','game_id','category_id','max_age_seconds','fixed_model_ids'}
    if not isinstance(server_policy,dict) or set(server_policy)!=required:
        return blocked('SERVER_PREVIEW_POLICY_REQUIRED')
    age=server_policy['max_age_seconds']
    if type(age) not in (int,float) or age<=0 or type(age) is float and not math.isfinite(age):
        return blocked('SERVER_MAX_AGE_REQUIRED')
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset().total_seconds()!=0:
        return blocked('SERVER_UTC_CLOCK_REQUIRED')
    try:
        site,game,category=(positive_id(server_policy[k]) for k in ('site_id','game_id','category_id'))
        fixed=server_policy['fixed_model_ids']
        if site!='266' or not isinstance(fixed,(list,tuple,set,frozenset)):raise ValueError()
        fixed={positive_id(v) for v in fixed}
    except (ContractError,ValueError,TypeError):return blocked('SERVER_PREVIEW_POLICY_REQUIRED')
    def fresh(value):
        if not isinstance(value,dict) or value.get('source')!='admin_readonly':return False
        stamp=value.get('observed_at')
        if not isinstance(stamp,str) or len(stamp)>64:return False
        try:
            stamp=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            return stamp.tzinfo is not None and stamp.utcoffset().total_seconds()==0 and 0<=(now-stamp).total_seconds()<=age
        except (ValueError,TypeError,OverflowError):return False
    def complete(value):
        return isinstance(value,dict) and value.get('complete') is True
    def guarded(value):
        return (isinstance(value,dict) and type(value.get('status')) in (str,int) and value['status'] in (1,'1')
            and type(value.get('auto_off')) in (str,int) and value['auto_off'] in (0,'0'))
    if not fresh(pool):return blocked('CATEGORY_SOURCE_MISSING_OR_STALE')
    if not complete(pool.get('coverage')) or not complete(pool.get('association_coverage')):
        return blocked('CATEGORY_OR_ASSOCIATIONS_INCOMPLETE')
    items=pool.get('items')
    if not isinstance(items,list) or len(items)>3:return blocked('BOUNDED_POOL_REQUIRED')
    seen_models={};seen_goods={};candidates=[]
    for item in items:
        reason=None;mid=None
        try:
            mid=positive_id(item['model_id']);fingerprint=digest(item)
            if mid in seen_models:
                if seen_models[mid]!=fingerprint:return blocked('SOURCE_IDENTITY_CONFLICT')
                continue
            seen_models[mid]=fingerprint
            if mid in fixed:reason='FIXED_MODEL_EXCLUDED'
            provider=item.get('association');model=provider.get('model') if isinstance(provider,dict) else None
            if reason is None and (not fresh(provider) or not complete(provider.get('coverage'))):reason='MODEL_SOURCE_MISSING_OR_STALE'
            if reason is None and (not isinstance(model,dict) or positive_id(model.get('model_id'))!=mid
                    or positive_id(model.get('game_id'))!=game or positive_id(model.get('category_id'))!=category
                    or positive_id(item.get('game_id'))!=game or positive_id(item.get('category_id'))!=category):
                reason='MODEL_SCOPE_MISMATCH'
            if reason is None and not guarded(model.get('raw_state')):reason='MODEL_ORIGINAL_GUARD_NOT_OBSERVED'
            products=provider.get('products') if isinstance(provider,dict) else None
            if reason is None and (not isinstance(products,list) or not products or len(products)>60):reason='PRODUCT_SOURCE_MISSING'
            refs=[];local={}
            if reason is None:
                for product in products:
                    ref=product['product_ref'];gid=positive_id(ref.get('goods_id'))
                    if (positive_id(ref.get('site_id'))!=site or positive_id(ref.get('game_id'))!=game
                            or positive_id(ref.get('model_id'))!=mid or positive_id(product.get('category_id'))!=category):
                        reason='PRODUCT_SCOPE_MISMATCH';break
                    hashed=digest(product)
                    if gid in seen_goods and seen_goods[gid]!=mid:return blocked('SOURCE_IDENTITY_CONFLICT')
                    seen_goods[gid]=mid
                    if gid in local:
                        if local[gid]!=hashed:return blocked('SOURCE_IDENTITY_CONFLICT')
                        continue
                    local[gid]=hashed
                    if guarded(product.get('raw_state')):refs.append(dict(ref))
                if reason is None and not refs:reason='PRODUCT_ORIGINAL_GUARD_NOT_OBSERVED'
        except (ContractError,ValueError,TypeError,KeyError):reason='MODEL_SOURCE_INVALID'
        if reason:output['excluded'].append(dict(model_id=mid,reason=reason));continue
        candidates.append(dict(model_id=mid,product_refs=refs,original_guard_observation='observed_original_guard',
            eligibility_scope='display_preview_only',checkout_enabled=False))
    output['candidate_count']=len(candidates)
    if len(candidates)<2:return blocked('AT_LEAST_TWO_PREVIEW_CANDIDATES_REQUIRED')
    output.update(eligible_for_preview=True,candidates=candidates)
    return output
