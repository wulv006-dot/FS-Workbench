"""One shared-session source snapshot; no credentials leave the existing broker."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

from .financial import fingerprint


def _admin_product_scopes(storefront,products):
    from .regional_public import canonical_products,SCOPE_FIELDS
    expected=canonical_products()
    for platform,scope in expected.items():
        sku=int(storefront['rows'][platform]['sku_id'])
        rows=[row for row in products if int(row['id'])==sku]
        if len(rows)!=1:
            raise ValueError('pricing_region_admin_product_scope_ambiguous:'+platform)
        scope['id']=sku
        if any(str(rows[0].get(field))!=str(scope[field]) for field in SCOPE_FIELDS):
            raise ValueError('pricing_region_admin_product_scope_mismatch:'+platform)
        expected[platform]={field:rows[0][field] for field in SCOPE_FIELDS}
    return expected


def _rule_matches_product(rule,product):
    fields=dict(site_id='site_id',gid='gid',top_cid='top_cid',cid='cid',sid='sid',aid='aid',goods_id='id')
    return all(rule[field] in (0,int(product[native])) for field,native in fields.items())


def _public_matches(observed,region_id,platform,product,factor):
    """A control cannot turn a failed public/backend reconciliation into trusted evidence."""
    code={39:'uk',21:'ar'}.get(region_id)
    offer=(observed.get('offers') or {}).get(platform) or {}
    context=offer.get('selection_context') or {}
    if (not code or observed.get('status')!='verified' or observed.get('region_id')!=region_id or
            observed.get('code')!=code or offer.get('selection_verified') is not True or
            offer.get('region_id')!=region_id or offer.get('platform')!=platform or offer.get('currency')!='USD' or
            any(context.get(k)!=v for k,v in dict(code=code,region_id=region_id,currency='USD',currency_rate='1',selected_header=code.upper()+' | USD').items()) or
            not context.get('landing_sha256') or observed.get('selection_context')!=context or
            any(str((offer.get('product_scope') or {}).get(k))!=str(v) for k,v in product.items()) or
            str(offer.get('sku_id'))!=str(product['id']) or offer.get('aid')!=int(product['aid'])):
        return False
    return Decimal(offer['coefficient'])==Decimal(str(factor))


def collect_context(evidence):
    parent=None
    original_created=evidence.get('checked_at') or evidence.get('created_at')
    if evidence.get('run_id') and original_created:
        try:
            created=datetime.fromisoformat(original_created.replace('Z','+00:00'))
            deadline=min(datetime.now(timezone.utc)+timedelta(seconds=210),created+timedelta(seconds=900))
            if evidence.get('collection_deadline_at'):
                deadline=min(deadline,datetime.fromisoformat(evidence['collection_deadline_at'].replace('Z','+00:00')))
            parent=dict(run_id=evidence['run_id'],created_at=original_created,deadline_at=deadline.isoformat())
        except (ValueError,TypeError,AttributeError):
            pass
    done=subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.sources'],
        input=json.dumps(dict(storefront=evidence['storefront'],arab_ut_status=evidence.get('arab_ut_status'),price_windows=evidence.get('price_windows',[]),active_mode=evidence.get('active_mode'),scope=evidence.get('active_scope'),history_cache=evidence.get('history_cache'),history_signature=evidence.get('history_signature'),online_context=evidence.get('online_context'),shared_order_facts=evidence.get('shared_order_facts'),collection_context=parent,collection_mode=evidence.get('collection_mode'))),capture_output=True,text=True,
        timeout=240,cwd='/opt/fc27-cloud-browser')
    try:
        value=json.loads(done.stdout)
    except ValueError:
        raise ValueError('pricing_v3_source_reply_invalid') from None
    if done.returncode:
        raise ValueError(value.get('error','pricing_v3_shared_source_unavailable'))
    return value


def _regional_history(replay,region_id,platforms):
    histories={}
    for platform in platforms:
        child=(replay.get('by_platform') or {}).get(platform,{})
        child=(child.get('region_layers') or {}).get(str(region_id),child)
        histories[platform]=dict(basis='historical_eligibility_current_terms_projected',
            basis_lower_bound_sufficient=child.get('basis_lower_bound_sufficient'),
            replay_paths=child.get('paths') if child.get('status') in ('verified','available') else None,
            source_sha256=child.get('source_sha256'),source_scope=child.get('source_scope'),
            original_basis_reconciliation=child.get('original_basis_reconciliation'),coverage=child.get('coverage'))
    return dict(platform_contract=replay.get('platform_contract'),by_platform=histories)


def shared_context(storefront,arab_ut_status=None,price_windows=None,*,active_mode=None,scope=None,history_cache=None,history_signature=None,online_context=None,collection_context=None,collection_mode=None,shared_order_facts=None):
    from .market_registry import arab_normal
    def read_arab():
        routing=Path('/var/lib/fc27-cloud/collection-access/routing.json')
        if not routing.exists() and not routing.is_symlink():
            return arab_normal()
        sys.path.insert(0,'/opt/fs-fc-control/code')
        from fc_collection.client import arab_normal as routed
        return routed(arab_normal,collection_context,pinned=collection_mode)
    try:arab=(arab_ut_status if isinstance(arab_ut_status,dict) else read_arab()) if active_mode is None else dict(status='not_required',offers=[])
    except Exception as exc:arab=dict(status='unavailable',reason=type(exc).__name__,offers=[])
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages,COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    from .region_source import read_rules
    session=auth.Session()
    token,reason=auth.admin_token_from_service()
    if not token:
        raise ValueError('pricing_admin_shared_source_unavailable')
    session.bind_admin_token(token)
    del token
    try:
        rules=read_rules(session,pages)
        wanted=','.join(str(row['sku_id']) for row in storefront['rows'].values())
        products=pages(session,'/admin/goods.Goods/index',[('id','IN',wanted)])
        from .business_source import collect as collect_business
        selective_plan=None
        if active_mode is None:
            business=collect_business(session,pages,storefront,products,price_windows=price_windows)
        else:
            from .selective_sources import source_plan
            from .business_source import collect_selective_business
            native_scopes=_admin_product_scopes(storefront,products)
            requested_platforms=(scope or {}).get('platforms',['PS','XBOX','PC'])
            known_regions={r['lang_region_id'] for r in rules if r['status']==1 and any(_rule_matches_product(r,p) for key,p in native_scopes.items() if key in requested_platforms)}
            selective_plan=source_plan(active_mode,scope,known_region_ids=known_regions)
            business_envelope=collect_selective_business(session,pages,storefront,products,active_mode=active_mode,scope=scope,
                history_cache=history_cache,source_signature=history_signature,online_context=online_context,
                **(dict(shared_order_facts=shared_order_facts) if shared_order_facts is not None else {}))
            business=business_envelope['context']
    finally:
        session.close()
    if active_mode is not None and 'ArabUT' in selective_plan['required_markets']:
        try:arab=arab_ut_status if isinstance(arab_ut_status,dict) else read_arab()
        except Exception as exc:arab=dict(status='unavailable',reason=type(exc).__name__,offers=[])
    aids={'PS':21587,'XBOX':21585,'PC':21589}
    product_scopes=_admin_product_scopes(storefront,products)
    matched=[]
    from .regional_public import collect as public_region
    from concurrent.futures import ThreadPoolExecutor
    public={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        public_scopes=(('uk',39),('ar',21)) if active_mode is None else [(code,rid) for code,rid in (('uk',39),('ar',21)) if rid in selective_plan['region_ids']]
        public_options={} if active_mode is None else dict(platforms=selective_plan['platforms'])
        futures={rid:pool.submit(public_region,code,rid,expected_products=product_scopes,**public_options) for code,rid in public_scopes}
        for rid,future in futures.items():
            try:public[rid]=future.result()
            except Exception as exc:public[rid]=dict(status='unavailable',reason=type(exc).__name__,region_id=rid)
    for rule in rules:
        if rule['status']!=1:
            continue
        platforms=[p for p in aids if (active_mode is None or p in selective_plan['platforms']) and _rule_matches_product(rule,product_scopes[p])]
        if not platforms:
            continue
        matching=[r for r in matched if r['region_id']==rule['lang_region_id'] and set(r['platforms'])&set(platforms)]
        if matching:
            raise ValueError('pricing_region_overlapping_rule_priority_pending')
        observed=public.get(rule['lang_region_id'],{})
        verified=all(_public_matches(observed,rule['lang_region_id'],p,product_scopes[p],rule['factor']) for p in platforms)
        replay=business.get('history_replay') or {}
        matched.append(dict(rule,region_id=rule['lang_region_id'],platforms=platforms,
            factor=rule['factor'],price_semantics='regional_regular_multiplicative',
            verified=verified,rounding='half_up_cent',history=_regional_history(replay,rule['lang_region_id'],platforms),
            resource='region_rule:'+str(rule['id']),public_rule_trace=observed,
            verification_status='public_factor_and_unique_backend_rule_verified' if verified else 'regional_public_pending'))
    contract=dict(schema_version='fc27-region-observed-20261026-v1',rules=rules,
                  rule_set_sha256=fingerprint(rules),admin_product_scopes=product_scopes,
                  checked_at=datetime.now(timezone.utc).isoformat(),unique_current_matches=True)
    controls=[]
    for p,aid in aids.items():
        if active_mode is not None and p not in selective_plan['platforms']:continue
        current=next((r for r in matched if r['region_id']==21 and p in r['platforms']),None)
        observed=(public.get(21,{}).get('offers') or {}).get(p)
        scope=dict(site_id=266,lang_region_id=21,goods_id=0,gid=1327,top_cid=1,cid=0,sid=7645,aid=aid)
        if current:
            scope={field:current[field] for field in scope}
        factor=(current or {}).get('factor','1')
        verified=(current['verified'] if current else _public_matches(public.get(21,{}),21,p,product_scopes[p],'1'))
        replay=business.get('history_replay') or {}
        controls.append(dict(id=(current or {}).get('id'),resource='region:21:'+p,region_id=21,platforms=[p],
            factor=factor,scope=scope,price_semantics='regional_regular_multiplicative',
            verified=verified,rounding='half_up_cent',
            verification_status=('unique_backend_rule_and_public_scope_verified' if current else 'no_matching_backend_rule_and_public_factor_one_verified') if verified else 'regional_public_pending',
            history=current['history'] if current else _regional_history(replay,21,[p]),public_rule_trace=observed,
            expected_rule_set_sha256=fingerprint(rules)))
    result=dict(business,region_rules=matched,regional_controls=controls,region_contract=contract,
                region_contract_sha256=fingerprint(contract),admin_products=products,
                regional_public_readback=public,arab_ut_quotes=arab['offers'],arab_ut_status=arab)
    if active_mode is None:return result
    from .selective_sources import lightweight_snapshot
    result['source_plan']=selective_plan
    return dict(context=lightweight_snapshot(result),private_updates=business_envelope['private_updates'],source_plan=selective_plan)


def collect_historical_source(data):
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages,COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    from .business_source import collect_historical_attachment
    session=auth.Session();token,_=auth.admin_token_from_service()
    if not token:raise ValueError('historical_shared_admin_unavailable')
    session.bind_admin_token(token);del token
    try:return collect_historical_attachment(data['period'],session,pages)
    finally:session.close()


if __name__=='__main__':
    try:
        data=json.load(sys.stdin)
        if data.get('action')=='historical':
            print(json.dumps(collect_historical_source(data),ensure_ascii=False));raise SystemExit(0)
        print(json.dumps(shared_context(data['storefront'],data.get('arab_ut_status'),data.get('price_windows'),active_mode=data.get('active_mode'),scope=data.get('scope'),history_cache=data.get('history_cache'),history_signature=data.get('history_signature'),online_context=data.get('online_context'),collection_context=data.get('collection_context'),collection_mode=data.get('collection_mode'),shared_order_facts=data.get('shared_order_facts')),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps(dict(error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)))
        raise SystemExit(1)
