"""The real mechanical writer boundary admits only the coordinator's original bundle."""
import json
from pathlib import Path


def proven_not_sent(audit):
    return bool(audit and audit.get('status')=='FAILED_BEFORE_WRITE' and audit.get('changed')==[] and
                audit.get('sync_confirmed') is False and audit.get('business_dispatch_started') is False)


def validate_dispatch(operation_id,preview_id,selected):
    from .runtime import ROOT
    control=json.loads((ROOT/'config/v3-control.json').read_text())
    auth=json.loads((ROOT/'v3/authorizations'/(operation_id+'.json')).read_text())
    preview=json.loads((ROOT/'previews'/(preview_id+'.json')).read_text())
    quote=json.loads((ROOT/'quotes'/(preview['run_id']+'.json')).read_text())
    bundle=quote['result']['decision_receipt']
    reference=auth.get('v3_execution_step')
    if reference:
        from .runtime import read_operation
        from .adapters import base_execution_id
        op=read_operation(reference['operation_id'])
        step=next((s for s in (op or {}).get('steps',[]) if s['step_id']==reference['step_id']),None)
        if (not step or step['state'] not in ('DISPATCHED','UNKNOWN') or step['kind']!='base' or
                base_execution_id(op,step)!=operation_id or preview.get('v3_execution_step')!=reference or op['bundle']['sha256']!=bundle['sha256']):
            raise ValueError('pricing_base_step_dispatch_changed')
    if (not control.get('enabled') or control['generation']!=auth['generation'] or
            auth['operation_id']!=operation_id or auth['run_id']!=preview['run_id'] or
            auth['selected']!=selected or auth['bundle_sha256']!=bundle['sha256'] or
            auth['generation']!=bundle['engine_generation']):
        raise ValueError('pricing_v3_dispatch_authorization_mismatch')
    path=ROOT/'executions'/(operation_id+'.json')
    if path.exists():
        from .financial import fingerprint
        previous=json.loads(path.read_text())
        if not proven_not_sent(previous) or fingerprint(previous)!=auth.get('not_sent_audit_sha256'):
            raise ValueError('pricing_original_dispatch_already_recorded')
