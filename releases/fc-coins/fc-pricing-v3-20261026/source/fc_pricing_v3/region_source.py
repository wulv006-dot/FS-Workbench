"""Read verified Admin region rules through the caller's existing shared session."""
from decimal import Decimal

CONTROLLER = '/admin/GoodsRegionPrice/'
SCOPE_FIELDS = ('site_id', 'lang_region_id', 'goods_id', 'gid', 'top_cid', 'cid', 'sid', 'aid')


def rule_expectations(rows):
    return sorted([{k:r[k] for k in ('id','status')+SCOPE_FIELDS} | {'factor':format(Decimal(str(r['factor'])),'.4f')}
                   for r in rows if r['lang_region_id']==39],key=lambda r:r['id'])


def read_rules(session, pages):
    # Generic site/game rules must be included before resolving exact FC scopes.
    rows = pages(session, CONTROLLER + 'index')
    for row in rows:
        if not isinstance(row, dict) or any(k not in row for k in ('id', 'factor', 'status') + SCOPE_FIELDS):
            raise ValueError('region_rule_fields_missing')
        factor = Decimal(str(row['factor']))
        if not factor.is_finite() or factor <= 0 or factor != factor.quantize(Decimal('.0001')):
            raise ValueError('region_rule_factor_invalid')
        if row['status'] not in (0, 1) or any(type(row[k]) is not int or row[k] < 0 for k in ('id',) + SCOPE_FIELDS):
            raise ValueError('region_rule_scope_invalid')
    return [row for row in rows if row['site_id'] in (0, 266) and row['gid'] in (0, 1327)]


def read_detail(session, rule_id):
    if type(rule_id) is not int or rule_id <= 0:
        raise ValueError('region_rule_id_invalid')
    status, body = session.get_admin(CONTROLLER + 'edit', id=rule_id)
    row = (body.get('data') or {}).get('row')
    if status != 200 or body.get('code') != 1 or not isinstance(row, dict) or row.get('id') != rule_id:
        raise ValueError('region_rule_readback_failed')
    return row


def exact_scope(rows,scope):
    return [row for row in rows if all(row[field]==scope[field] for field in SCOPE_FIELDS)]


def save_rule(session,pages,step,before_send=None):
    """One claimed request. Unknown callers reconcile the exact scope instead of resending."""
    from .financial import fingerprint
    scope=step['scope']
    retirement=step.get('intent')=='retire_uk_discount_v1'
    if retirement:
        from .uk_retirement import SCOPE
        if scope!=SCOPE or step.get('rule_id')!=1 or step.get('target_status')!=0 or Decimal(str(step['value']))!=Decimal('.91'):
            raise ValueError('pricing_region_write_scope_invalid')
    elif (scope['site_id']!=266 or scope['gid']!=1327 or scope['lang_region_id']!=21 or
            scope['top_cid']!=1 or scope['sid']!=7645 or scope['aid'] not in (21587,21585,21589)):
        raise ValueError('pricing_region_write_scope_invalid')
    factor=Decimal(str(step['value']))
    if not Decimal('.0001')<=factor<=1 or factor!=factor.quantize(Decimal('.0001')):
        raise ValueError('pricing_region_write_factor_invalid')
    current=read_rules(session,pages)
    if fingerprint(current)!=step['expected_rule_set_sha256']:
        raise ValueError('pricing_region_rule_set_changed')
    matches=exact_scope(current,scope)
    if len(matches)>1:
        raise ValueError('pricing_region_scope_ambiguous')
    if retirement and (len(matches)!=1 or matches[0]['id']!=1 or matches[0]['status']!=1 or Decimal(str(matches[0]['factor']))!=Decimal('.91')):
        raise ValueError('pricing_uk_retirement_rule_changed')
    target_status=0 if retirement else 1
    payload=dict(scope,factor=str(factor),status=target_status)
    action='edit' if matches else 'add'
    if matches:
        payload['id']=matches[0]['id']
    if before_send:before_send(CONTROLLER+action,payload)
    status,body=session.post_admin(CONTROLLER+action,payload)
    if status!=200 or body.get('code')!=1:
        return dict(status='UNKNOWN',http_status=status,backend_code=body.get('code'),scope=scope)
    found=exact_scope(read_rules(session,pages),scope)
    if len(found)!=1 or retirement and found[0]['id']!=1 or Decimal(str(found[0]['factor']))!=factor or found[0]['status']!=target_status:
        return dict(status='UNKNOWN',scope=scope,reply_received=True)
    return dict(status='CONFIRMED',rule_id=found[0]['id'],scope=scope,factor=str(factor),
                rule_set_sha256=fingerprint(read_rules(session,pages)))
