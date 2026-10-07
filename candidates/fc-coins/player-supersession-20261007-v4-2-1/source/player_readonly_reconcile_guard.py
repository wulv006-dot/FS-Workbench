"""Proof validation only: no request, persistence, lock or business write."""
from datetime import datetime, timezone
from decimal import Decimal

def stable_view(proof):
    return [(s['model_id'],s['model_inputs'],
             sorted((r['id'],r['mid'],r['gid'],r['cid'],r['aid'],r['site_id'],r['status'],str(r['unit_price'])) for r in s['products']),
             sorted((r['product_id'],r['platform'],r['our_price_coins'],r['coefficient'],r['backend_usd'],r['public_usd']) for r in s['public_readback']))
            for s in proof['samples']]

def validate_proof(ledger,job,audit,policy,proof,now=None):
    now=now or datetime.now(timezone.utc)
    if (ledger.get('mode')!='category_all' or ledger.get('status')!='needs_reconcile'
        or ledger.get('stage')!='stopped' or ledger.get('error')!='player_sample_readback_timeout'
        or job.get('kind')!='player_sync' or job.get('status')!='failed'
        or job.get('error_detail')!='player_sample_readback_timeout'
        or ledger['job_id']!=job['job_id'] or proof['job_id']!=job['job_id']
        or ledger['coin_execution_id']!=audit['execution_id'] or proof['coin_execution_id']!=audit['execution_id']
        or audit.get('status')!='CONFIRMED' or audit.get('automatic') is not True
        or policy.get('enabled') is not True or policy.get('revision')!=job['request']['config_revision']
        or proof['player_policy']!=policy):
        raise ValueError('reconcile_state_changed')
    age=(now-datetime.fromisoformat(proof['checked_at'])).total_seconds()
    if not 0<=age<=60:raise ValueError('reconcile_proof_expired')
    expected={r['platform']:Decimal(str(r['b2c'])) for r in audit['after']['rows']}
    if set(expected)!={'PS','XBOX','PC'}:raise ValueError('reconcile_rates_incomplete')
    if {p:Decimal(v) for p,v in proof['expected_rates'].items()}!=expected:raise ValueError('reconcile_target_changed')
    reads=proof['coin_readbacks']
    if len(reads)!=6 or {(r['platform'],r['site_id']) for r in reads}!={(p,s) for p in expected for s in (0,266)}:
        raise ValueError('reconcile_coin_scope_changed')
    if any(r['http_status']!=200 or r['response_code']!=1 or Decimal(str(r['actual_unit_price']))!=expected[r['platform']] for r in reads):
        raise ValueError('reconcile_coin_baseline_changed')
    if (len(proof['samples'])!=ledger['sample_count'] or len(proof['samples'])!=5
        or [s['model_id'] for s in proof['samples']]!=ledger['sample_model_ids']):
        raise ValueError('reconcile_sample_scope_changed')
    for s in proof['samples']:
        mid=s['model_id'];model=s['model'];parts=s['public_readback']
        if int(model['id'])!=mid or int(model['gid'])!=1327 or int(model['cid'])!=9627 or str(model['status'])!='1':
            raise ValueError('reconcile_model_scope_changed')
        before=ledger['sample_before'][str(mid)]
        if len(parts)!=3 or {r['platform'] for r in parts}!=set(expected) or {r['product_id'] for r in parts}!={r['product_id'] for r in before}:
            raise ValueError('reconcile_product_scope_changed')
        for part in parts:
            prior=next(r for r in before if r['product_id']==part['product_id'])
            platform=part['platform']
            if (part['our_price_coins']!=prior['our_price_coins'] or part['coefficient']!=prior['coefficient']
                or Decimal(s['model_inputs'][platform])!=Decimal(part['our_price_coins'])
                or Decimal(s['model_inputs']['coefficient'])!=Decimal(part['coefficient'])):
                raise ValueError('reconcile_inputs_changed')
            target=Decimal(part['our_price_coins'])/1000*expected[platform]*Decimal(part['coefficient'])
            if abs(Decimal(part['backend_usd'])-target)>Decimal('.001') or abs(Decimal(part['public_usd'])-target)>Decimal('.001'):
                raise ValueError('reconcile_price_mismatch')
        for product in s['products']:
            if int(product['mid'])!=mid or int(product['gid'])!=1327 or int(product['cid'])!=9627 or int(product['site_id']) not in (0,266):
                raise ValueError('reconcile_linked_scope_changed')
            target=Decimal(s['model_inputs'][product['platform']])/1000*expected[product['platform']]*Decimal(s['model_inputs']['coefficient'])
            if abs(Decimal(str(product['unit_price']))-target)>Decimal('.001'):
                raise ValueError('reconcile_linked_price_mismatch')
    return True
