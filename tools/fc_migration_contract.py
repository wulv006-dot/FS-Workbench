"""Read-only migration preflight of already-approved FC state; never creates policy/tiers."""
from decimal import Decimal, InvalidOperation

APPROVED_BANDS = {'at_least_40':('6.00','8.00'),'30_to_40':('5.00','6.00'),
                  '20_to_30':('0.00','5.00'),'below_20':('0.00','0.00')}
PLATFORMS=('PS','XBOX','PC')
PRODUCTS={'PS':(163329309,163329311,21587),'XBOX':(163329275,163329277,21585),
          'PC':(163329343,163329345,21589)}

def row_identity(platform, site):
    all_id, site_id, aid=PRODUCTS[platform]
    return {'id':all_id if site==0 else site_id,'mid':41217957,'gid':1327,'cid':9623,
            'site_id':site,'aid':aid,'unit':'K','title':'coins','status':1}

def quantity_vector(values):
    if not isinstance(values,list) or len(values)!=15:
        raise ValueError('APPROVED_FIFTEEN_TIERS_REQUIRED')
    numbers=[]
    for value in values:
        try:number=Decimal(str(value))
        except (InvalidOperation,ValueError):raise ValueError('INVALID_TIER_QUANTITY') from None
        if isinstance(value,bool) or not number.is_finite() or number<=0:
            raise ValueError('INVALID_TIER_QUANTITY')
        numbers.append(number)
    if len(set(numbers))!=15:raise ValueError('DUPLICATE_TIER_QUANTITY')
    if any(x in (20,30,40) for x in numbers):raise ValueError('REMOVED_TIERS_MUST_NOT_RETURN')
    return numbers
def validate_policy_migration(policy, expected_revision=25):
    if not isinstance(policy,dict) or policy.get('revision') != expected_revision:
        raise ValueError('EXISTING_POLICY_REVISION_REQUIRED')
    if (policy.get('schedule_revision') != 23 or policy.get('interval_minutes') != 60
            or policy.get('mode') != 'auto' or policy.get('system_enabled') is not True
            or Decimal(str(policy.get('minimum_gross_margin_pct'))) != 10
            or policy.get('platforms') != list(PLATFORMS)):
        raise ValueError('APPROVED_EXISTING_POLICY_REQUIRED')
    rules=policy.get('pricing_rules')
    if not isinstance(rules,dict) or rules.get('schema_version') != 1 or set(rules.get('bands',{})) != set(APPROVED_BANDS):
        raise ValueError('APPROVED_EXISTING_RANGES_REQUIRED')
    for band,(low,high) in APPROVED_BANDS.items():
        row=rules['bands'][band]
        if Decimal(str(row.get('min_discount_pct'))) != Decimal(low) or Decimal(str(row.get('max_discount_pct'))) != Decimal(high):
            raise ValueError('APPROVED_EXISTING_RANGES_REQUIRED')
    return True

def validate_six_tier_rows(rows, expected_quantities_by_platform):
    """Expected quantities must come from an approved real preflight, never a guessed list."""
    if not isinstance(expected_quantities_by_platform,dict) or set(expected_quantities_by_platform)!=set(PLATFORMS):
        raise ValueError('APPROVED_QUANTITY_VECTORS_REQUIRED')
    if not isinstance(rows,dict) or set(rows)!={(p,s) for p in PLATFORMS for s in (0,266)}:
        raise ValueError('SIX_BACKEND_ROWS_REQUIRED')
    for platform in PLATFORMS:
        expected=expected_quantities_by_platform[platform]
        expected_numbers=quantity_vector(expected)
        source,fallback=rows[(platform,266)],rows[(platform,0)]
        for site,row in ((266,source),(0,fallback)):
            if not isinstance(row,dict) or any(str(row.get(k))!=str(v) for k,v in row_identity(platform,site).items()):
                raise ValueError('COIN_PRODUCT_SCOPE_CHANGED')
            more=row.get('more',{})
            if not isinstance(more,dict) or quantity_vector(more.get('gold'))!=expected_numbers:
                raise ValueError('TIER_VECTOR_CHANGED')
            if more.get('gold')!=expected or any(not isinstance(more.get(k),list) or len(more[k])!=15 for k in ('gold','price','discount','give','delivery_time','hot')):
                raise ValueError('TIER_VECTOR_CHANGED')
        if any(source['more'][k]!=fallback['more'][k] for k in ('gold','discount','give')):
            raise ValueError('SOURCE_ALL_BASIS_CHANGED')
    return True
