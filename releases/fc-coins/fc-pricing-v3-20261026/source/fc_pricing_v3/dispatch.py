"""The real mechanical writer boundary admits only the coordinator's original bundle."""
import json
from pathlib import Path


CURVE_WRITE_PROTOCOL = 'fc27_curve_v6'
CURVE_REJECTED = 'REJECTED_NO_CHANGE'


def write_protocol(bundle):
    protocol = bundle.get('write_protocol')
    has_curves = any('curves' in (bundle.get(field) or {})
                     for field in ('before_action', 'action'))
    if protocol == CURVE_WRITE_PROTOCOL and has_curves:
        return protocol
    if protocol is not None or has_curves:
        raise ValueError('pricing_write_protocol_invalid')
    return None


def prewrite_refusal(raw):
    """Only the shell's branch before Docker may emit this refusal receipt."""
    safe = {'pricing_admin_shared_source_timeout', 'pricing_admin_shared_source_unavailable',
            'pricing_current_public_required', 'pricing_promotions_changed_since_quote',
            'pricing_average_history_changed_since_quote', 'restore_current_cost_quote_required',
            'pricing_live_constraints_unavailable', 'pricing_authorization_expired',
            'pricing_authorization_expired_or_unowned', 'TimeoutError', 'TimeoutExpired',
            'OSError', 'PermissionError', 'FileNotFoundError', 'JSONDecodeError', 'KeyError', 'TypeError'}
    try:
        value=json.loads(raw.splitlines()[-1]);reason=value.get('reason')
    except (IndexError,ValueError,TypeError,AttributeError):reason=None
    return dict(status='NOT_SENT',stage='prewrite_source_guard',
                reason=reason if isinstance(reason,str) and reason in safe else 'pricing_live_constraints_unavailable',
                price_post_attempted=False,business_dispatch_started=False,writer_started=False)


def proven_not_sent(audit):
    return bool(audit and audit.get('status')=='FAILED_BEFORE_WRITE' and audit.get('changed')==[] and
                audit.get('sync_confirmed') is False and audit.get('business_dispatch_started') is False)


def validate_dispatch(operation_id,preview_id,selected,*,protocol=None):
    from .runtime import ROOT
    control=json.loads((ROOT/'config/v3-control.json').read_text())
    auth=json.loads((ROOT/'v3/authorizations'/(operation_id+'.json')).read_text())
    preview=json.loads((ROOT/'previews'/(preview_id+'.json')).read_text())
    quote=json.loads((ROOT/'quotes'/(preview['run_id']+'.json')).read_text())
    bundle=quote['result']['decision_receipt']
    if write_protocol(bundle) != protocol:
        raise ValueError('pricing_write_protocol_mismatch')
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
    return bundle


def validate_curve_send(root, bundle, platform):
    """Read the original ownership, lease and plan revision immediately before sending."""
    from contextlib import closing
    from datetime import datetime, timezone
    import sqlite3

    from .financial import fingerprint, instant

    operation_id = bundle['decision_bundle_id']
    plan_id, revision, generation = (bundle[key] for key in ('plan_id', 'revision', 'engine_generation'))
    if bundle['sha256'] != fingerprint({k: v for k, v in bundle.items() if k != 'sha256'}):
        raise ValueError('pricing_curve_bundle_hash_mismatch')
    control = json.loads((root/'config/v3-control.json').read_text())
    if control.get('enabled') is not True or control.get('generation') != generation:
        raise ValueError('pricing_generation_retired')
    uri = (root/'v3/control.sqlite3').resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
        conn.execute('BEGIN')

        def body(table, key):
            row = conn.execute('SELECT body FROM ' + table + ' WHERE id=?', (key,)).fetchone()
            return json.loads(row[0]) if row else {}

        operation = body('operations', operation_id)
        plan = body('pricing_plans', plan_id)
        resource = 'base:' + platform
        if (operation.get('operation_id') != operation_id or operation.get('bundle') != bundle
                or operation.get('status') != 'DISPATCHED'
                or (operation.get('plan_id'), operation.get('revision'), operation.get('generation'))
                != (plan_id, revision, generation)
                or platform not in operation.get('dispatch_context', {}).get('selected', ())
                or resource not in bundle.get('mutable_resources', ())
                or not any(step.get('kind') == 'base' and step.get('state') == 'DISPATCHED'
                           and step.get('dispatched_at') for step in operation.get('steps', ()))):
            raise ValueError('pricing_curve_original_dispatch_invalid')
        if (body('metadata', 'generation').get('id') != generation
                or (plan.get('plan_id'), plan.get('revision'), plan.get('generation'))
                != (plan_id, revision, generation)):
            raise ValueError('pricing_curve_plan_revision_changed')
        if (bundle.get('activation_revision') is not None
                and (plan.get('write_protocol') != CURVE_WRITE_PROTOCOL
                     or plan.get('activation_revision') != bundle['activation_revision'])):
            raise ValueError('pricing_curve_plan_revision_changed')
        now = datetime.now(timezone.utc)
        if (plan.get('state') != 'ACTIVE' or now >= instant(bundle['valid_until'])
                or plan.get('ends_at') and now >= instant(plan['ends_at'])):
            raise ValueError('pricing_authorization_expired')
        owner = conn.execute('SELECT plan_id,revision,generation FROM plan_ownership WHERE resource=?',
                             (resource,)).fetchone()
        lease = conn.execute('SELECT operation_id FROM resource_leases WHERE resource=?', (resource,)).fetchone()
        if owner != (plan_id, revision, generation) or lease != (operation_id,):
            raise ValueError('pricing_curve_resource_fence_changed')
