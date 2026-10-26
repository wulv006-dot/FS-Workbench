"""Shared Admin transport for a single durably claimed, exact-scope region step."""
from datetime import datetime,timezone
from decimal import Decimal
import json
import sys


def operation_step(operation_id,step_id,*,write=False):
    from .runtime import ledger,ROOT
    from .financial import fingerprint
    from .region_source import read_rules,exact_scope,save_rule
    from .uk_retirement import authority_resources
    db=ledger()
    with db.transaction() as conn:
        op=db.get('operations',operation_id,conn)
        if not op:raise ValueError('pricing_operation_missing')
        step=next((s for s in op['steps'] if s['step_id']==step_id),None)
        if write and step is None:raise ValueError('pricing_region_step_missing')
        if write:
            control=json.loads((ROOT/'config/v3-control.json').read_text())
            if not control['enabled'] or control['generation']!=op['generation']:
                raise ValueError('pricing_generation_retired')
            plan=db.get('pricing_plans',op['plan_id'],conn)
            db.owns(plan,authority_resources(op['bundle']),conn)
            if step.get('transport_claimed_at'):
                return dict(status='UNKNOWN',reason='original_region_transport_already_claimed')
            if step.get('state')!='DISPATCHED':raise ValueError('pricing_region_step_not_claimed')
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages,COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    session=auth.Session()
    token,reason=auth.admin_token_from_service()
    if not token:
        session.close()
        return dict(status='NOT_SENT',reason='pricing_region_shared_session_unavailable',original_operation_id=operation_id,write_performed=False)
    session.bind_admin_token(token)
    del token
    try:
        if step is None:return dict(status='verified',rules=read_rules(session,pages))
        if write:
            def before_send(path,payload):
                from .financial import instant
                with db.transaction() as conn:
                    original=db.get('operations',operation_id,conn)
                    claimed=next(s for s in original['steps'] if s['step_id']==step_id)
                    if claimed.get('transport_claimed_at'):raise ValueError('pricing_region_transport_already_claimed')
                    active=json.loads((ROOT/'config/v3-control.json').read_text())
                    if not active['enabled'] or active['generation']!=original['generation']:raise ValueError('pricing_generation_retired')
                    plan=db.get('pricing_plans',original['plan_id'],conn)
                    db.owns(plan,authority_resources(original['bundle']),conn)
                    now=datetime.now(timezone.utc)
                    if plan['state']!='ACTIVE' or now>=instant(original['bundle']['valid_until']):raise ValueError('pricing_authorization_expired')
                    claimed.update(transport_claimed_at=now.isoformat(),transport_payload_sha256=fingerprint(dict(path=path,payload=payload)))
                    db.put('operations',operation_id,original,conn)
            try:return save_rule(session,pages,step,before_send=before_send)
            except Exception as exc:
                original=db.get('operations',operation_id)
                claimed=next(s for s in original['steps'] if s['step_id']==step_id)
                return dict(status='UNKNOWN' if claimed.get('transport_claimed_at') else 'NOT_SENT',
                            reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__,
                            original_operation_id=operation_id,write_performed=None if claimed.get('transport_claimed_at') else False)

        rules=read_rules(session,pages)
        found=exact_scope(rules,step['scope'])
        if len(found)==1 and (step.get('rule_id') is None or found[0]['id']==step['rule_id']) and Decimal(str(found[0]['factor']))==Decimal(str(step['value'])) and found[0]['status']==step.get('target_status',1):
            return dict(status='CONFIRMED',rule_id=found[0]['id'],scope=step['scope'],factor=str(found[0]['factor']),rule_set_sha256=fingerprint(rules),
                        checked_at=datetime.now(timezone.utc).isoformat(),original_operation_id=operation_id,write_performed=False)
        return dict(status='UNKNOWN',scope=step['scope'],reason='original_region_value_not_confirmed',write_performed=False)
    finally:
        session.close()


if __name__=='__main__':
    request=json.load(sys.stdin)
    try:
        print(json.dumps(operation_step(request['operation_id'],request['step_id'],write=request.get('mode')=='write')))
    except Exception as exc:
        print(json.dumps(dict(status='UNKNOWN',error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)))
        raise SystemExit(1)
