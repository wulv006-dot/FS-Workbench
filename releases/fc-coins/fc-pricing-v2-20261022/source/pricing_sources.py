"""Read FC pricing constraints through the existing FS Admin session, never log credentials."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

from pricing_v2 import number, fingerprint, instant

ROOT = Path('/var/lib/fc27-cloud')
FILE = ROOT / 'config/pricing-inputs.json'
CUSTOM_URL='https://www.mmoexp.com/mmoexp-v250528/js/goods/mlb26-landing.min.js'
CUSTOM_SHA='ad92c2d1c36bfd4d0de8fe4c6cb566be3957209aec86cb3f64fcd9299074c10d'
CART_SHA='605a07a7bec2cde23b5201a30d147b94ed01c5c24a4e41ecb0a989880191a93f'


def ids(value):
    return {v.strip() for v in str(value or '0').split(',')}


def active(row, now, *, coupon=False):
    if str(row.get('status')) != '1' or str(row.get('site_id')) not in {'0','266'}:
        return False
    if not ids(row.get('game_id' if coupon else 'gid')) & {'0','1327'}:
        return False
    if not coupon and '1327' in ids(row.get('exclude_gids')):
        return False
    if coupon and str(row.get('product_type')) not in {'0','1'}:
        return False
    start, end = (row.get('start_time'),row.get('end_time')) if coupon else (row.get('timestart'),row.get('timeend'))
    if coupon and str(row.get('time_effect')) == '2':
        return True  # Issued relative coupons may still be redeemable regardless of claim quotas.
    for value, before in ((start,True),(end,False)):
        if value in (None,'',0,'0','~'):
            continue
        at = datetime.fromtimestamp(int(value),timezone.utc) if str(value).isdigit() else instant(value)
        if before and now<at or not before and now>at:
            return False
    return True


def normalize(discounts, coupons, goods, storefront, *, now=None):
    now = now or datetime.now(timezone.utc)
    codes=[];vouchers=[];unissued_directed=[]
    for row in discounts:
        if not active(row,now):continue
        if str(row.get('type')) != '1':
            raise ValueError('pricing_discount_mode_unverified')
        ratio=number(row.get('discount'))/100
        if ratio>1:raise ValueError('pricing_discount_ratio_invalid')
        codes.append(dict(id=str(row['id']),retained_ratio=str(ratio),scope='overinclusive_FC_Coins_envelope'))
    code_min=min([number(r['retained_ratio']) for r in codes]+[Decimal(1)])
    for row in coupons:
        if not active(row,now,coupon=True):continue
        # Directed templates with no issued coupons cannot be redeemed; a first issue changes the envelope.
        if (str(row.get('fetch_scene'))=='4' and str(row.get('fetch_qty'))=='0' and str(row.get('used_qty'))=='0'
                and str(row.get('mode_type'))=='1'):
            unissued_directed.append(dict(id=str(row['id']),fetch_qty=0,used_qty=0,reason='backend_directed_template_no_issued_coupon'))
            continue
        # A fixed/converted coupon needs its issued-value and cart allocation contract.
        if str(row.get('type'))!='1' or str(row.get('mode_type'))!='2' or str(row.get('is_open')) not in {'0','1'}:
            raise ValueError('pricing_coupon_mode_unverified')
        ratio=number(row.get('reduce'))/100
        if ratio>1:raise ValueError('pricing_coupon_ratio_invalid')
        stack=str(row['is_open'])=='1'
        # Cart computes separate deductions on the original total; coupon selection clears points, not VIP.
        combined=ratio-(1-code_min if stack else 0)-Decimal('.05')
        if combined<=0:raise ValueError('pricing_coupon_no_positive_retention')
        vouchers.append(dict(id=str(row['id']),retained_ratio=str(combined),coupon_retained_ratio=str(ratio),
                             code_stack=stack,threshold_ignored_conservatively=True,
                             cap_ignored_conservatively=True))
    # Current published VIP contract: automatic discount <=5%, points <=10%, mutually
    # exclusive with regular codes. Both are dominated by the observed FC 30% coupon.
    vip_ratio=Decimal('.90')
    minimum=min([code_min,vip_ratio]+[number(r['retained_ratio']) for r in vouchers])
    packages={};by_id={str(r['id']):r for r in goods}
    for platform,own in storefront['rows'].items():
        row=by_id.get(str(own['sku_id']))
        if not row or str(row.get('site_id'))!='266' or str(row.get('gid'))!='1327' or str(row.get('top_cid'))!='1' or row.get('unit')!='K' or str(row.get('status'))!='1':
            raise ValueError('pricing_catalog_scope_invalid')
        more=row.get('more') or {}
        if isinstance(more,str):more=json.loads(more)
        quantities,gifts,reductions=more.get('gold'),more.get('give'),more.get('discount')
        if not isinstance(quantities,list) or not 1<=len(quantities)<=100 or not isinstance(gifts,list) or not isinstance(reductions,list) or len({len(quantities),len(gifts),len(reductions)})!=1:
            raise ValueError('pricing_catalog_package_contract')
        product_ratio=number(row.get('discount'))/100
        if product_ratio>1:raise ValueError('pricing_catalog_discount')
        tiers=[]
        for q,g,d in zip(quantities,gifts,reductions):
            q,g,d=number(q),number(g,zero=True),number(d)/100*product_ratio
            if d>1 or g>q:raise ValueError('pricing_catalog_package_invalid')
            tiers.append(dict(base_k=str(q),bonus_k=str(g),retained_ratio=str(d)))
        matching=[v for v in tiers if number(v['base_k'])==100]
        if len(matching)!=1 or number(matching[0]['bonus_k'],zero=True)!=number(own['bonus_k'],zero=True):
            raise ValueError('pricing_catalog_public_bonus_mismatch')
        if number(matching[0]['retained_ratio'])!=1:
            raise ValueError('pricing_catalog_base_discount_changed')
        unit=number(row['unit_price'])
        observed=number(own['package_usd'])
        # Source agreement within the site's cent display; no stale Admin price replaces public.
        if abs(unit*100*number(matching[0]['retained_ratio'])-observed)>Decimal('.01'):
            raise ValueError('pricing_catalog_public_price_mismatch')
        packages[platform]=dict(sku_id=str(row['id']),model_id=str(row['mid']),tiers=tiers,
            min_custom_k=str(min(number(t['base_k']) for t in tiers)),
            max_delivered_ratio=str(max((number(t['base_k'])+number(t['bonus_k'],zero=True))/number(t['base_k']) for t in tiers)),
            minimum_package_retained_ratio=str(min(number(t['retained_ratio']) for t in tiers)),
            source='Admin product quantity/gift/discount configuration, checked against same-run public 100K',
            custom_basis='existing integer-K custom amount, minimum published tier; no formula changes')
    body=dict(contract='fc-coins-promotion-envelope-v1',status='verified',site_id=266,game_id=1327,
        coupon_other_benefits_contract='verified_included_in_envelope' if vouchers else 'not_applicable',
        minimum_retained_ratio=str(minimum),code_count=len(codes),coupon_count=len(vouchers),
        codes_sha256=fingerprint(codes),coupons=vouchers,packages=packages,
        unissued_directed_templates=unissued_directed,
        vip_contract=dict(url='https://www.mmoexp.com/Vip.html',verified_date='2026-10-22',
                          automatic_discount_max_pct='5',points_max_pct='10',regular_code_exclusive=True,
                          coupon_points_exclusive=True,coupon_vip_allowance_pct='5',
                          combination='conservative additive original-amount deductions',
                          cart_source_url='https://www.mmoexp.com/Cart.html',cart_source_sha256=CART_SHA,
                          verification='public cart computeCouponPrice/clearPointsUi/priceProcessing source inspected; backend transaction not placed'),
        custom_contract=dict(url=CUSTOM_URL,sha256=CUSTOM_SHA,integer_k=True,
            minimum='minimum_public_tier',non_tier_gifts='0',tier_discount_bound='minimum_configured_discount',
            unit_bound='custom uses max(current unit, derived tier unit)',verified_date='2026-10-22',
            verification='workstation public source inspection; fixed formula retained by user, not a per-cycle remote fetch'),
        scope='all current applicable percentage promotions; ignored caps/eligibility only overestimate discounts')
    return dict(body,sha256=fingerprint(body),checked_at=now.isoformat())


def _collect_shared_admin(storefront, *, persist=True):
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages, COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    session=auth.Session();token,reason=auth.admin_token_from_service()
    if not token:raise ValueError('pricing_admin_shared_source_unavailable')
    session.bind_admin_token(token);del token
    try:
        discounts=pages(session,'/admin/market.Discount/index')
        coupons=pages(session,'/admin/market.Coupon/index')
        wanted=','.join(str(r['sku_id']) for r in storefront['rows'].values())
        goods=pages(session,'/admin/goods.Goods/index',[('id','IN',wanted)])
    finally:session.close()
    result=normalize(discounts,coupons,goods,storefront)
    if persist:
        from snapshot_layer import atomic_json
        atomic_json(FILE,result)
        import os
        os.chown(FILE,0,11028);os.chmod(FILE,0o640)
    return result


def collect(storefront, *, persist=True):
    # FC's system Python is stdlib-only; keep the existing authenticated client in its runtime.
    import subprocess
    try:
        done=subprocess.run(['/opt/python39/bin/python3','-B',str(Path(__file__).resolve()),'collect'],
            input=json.dumps(dict(storefront=storefront,persist=persist)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            universal_newlines=True,timeout=40)
    except subprocess.TimeoutExpired:raise ValueError('pricing_admin_shared_source_timeout') from None
    try:value=json.loads(done.stdout)
    except ValueError:raise ValueError('pricing_admin_shared_source_reply_invalid') from None
    if done.returncode:raise ValueError(value.get('reason') or 'pricing_admin_shared_source_failed')
    if value.get('status')!='verified':raise ValueError('pricing_admin_shared_source_unverified')
    return value


def refresh_before_write(request,root=ROOT):
    from pricing_v2 import verify_quote,fresh
    from automation_policy import load_policy
    import uuid
    if request.get('source_execution_id'):
        uuid.UUID(request['source_execution_id'])
        path=max((root/'quotes').glob('*.json'),key=lambda p:p.stat().st_mtime,default=None)
        if path is None:raise ValueError('restore_current_cost_quote_required')
    else:
        preview=json.loads((root/'previews'/(str(uuid.UUID(request['preview_id']))+'.json')).read_text('utf-8'))
        path=root/'quotes'/(str(uuid.UUID(preview['run_id']))+'.json')
    quote=json.loads(path.read_text('utf-8'));policy=load_policy()
    verify_quote(quote,policy,request.get('platforms') or list(('PS','XBOX','PC')),for_execution=True)
    public=json.loads((root/'monitor/storefront.json').read_text('utf-8'))
    if public.get('status')!='ok' or public.get('source')!='https://www.mmoexp.com/Fc-27/Coins.html' or public.get('currency')!='USD' or set(public.get('rows') or {})!={'PS','XBOX','PC'}:
        raise ValueError('pricing_current_public_required')
    for platform,row in public['rows'].items():
        fresh(row['checked_at'],datetime.now(timezone.utc),seconds=900)
        if row.get('platform')!=platform or row.get('status')!='ok' or number(row['base_k'])!=100 or row['sku_id']!=quote['evidence']['storefront']['rows'][platform]['sku_id']:
            raise ValueError('pricing_current_public_required')
    current=collect(public,persist=True)
    if current['sha256']!=quote['evidence']['promotion_envelope']['sha256']:
        raise ValueError('pricing_promotions_changed_since_quote')
    return dict(status='current_promotions_rechecked',promotion_sha256=current['sha256'],checked_at=current['checked_at'],price_write_performed=False)


if __name__=='__main__':
    try:
        if sys.argv[1]=='collect':
            data=json.load(sys.stdin)
            if set(data)!={'storefront','persist'} or type(data['persist']) is not bool:raise ValueError('pricing_source_fields')
            result=_collect_shared_admin(data['storefront'],persist=data['persist'])
        else:
            request=json.loads(Path(sys.argv[1]).read_text('utf-8'));result=refresh_before_write(request)
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps(dict(status='FAILED',reason=str(exc)[:100] if isinstance(exc,ValueError) else type(exc).__name__)))
        raise SystemExit(1)
