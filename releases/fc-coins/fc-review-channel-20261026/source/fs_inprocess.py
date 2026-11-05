"""Provider and source factories for the original FS process, never a new key owner."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import stat

from background import import_background
from proxy_gateway import ModelGateway, ScopedTools, UnifiedBudget, conservative_input_bound, MAX_PROVIDER_WAIT_SECONDS
from source_projection import project_capture


def source_book(detail, at):
    from fc_deep_sources import EvidenceReader
    from fc_deep_analysis import plan, build_evidence
    from pilot import complete_week
    from datetime import date, timedelta
    period = complete_week(at)
    end = (date.fromisoformat(period['end_exclusive'])-timedelta(days=1)).isoformat()
    query = plan(period['start'], end, at)
    raw, config = EvidenceReader(detail).capture(query)
    # Existing source capture/refresh policy is preserved. No report generation or
    # original advisor model is called, and raw rows stay in this process.
    evidence = build_evidence(query, raw, config, at)
    return project_capture(evidence)


def approved_unknowns(tasks):
    """Explicit owner confirmation lives outside all Hermes mounts and tools."""
    path=Path(tasks.path).parent/'unknown-usage-approvals.json'
    if not path.exists():return {}
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid!=os.geteuid() or info.st_size>4096:
        raise ValueError('unknown_approval_file_invalid')
    value=json.loads(path.read_text('utf-8'))
    if set(value)!={'contract','approvals'} or value['contract']!='explicit-unknown-usage-acceptance-v1' or not isinstance(value['approvals'],list):
        raise ValueError('unknown_approval_contract')
    result={}
    for item in value['approvals']:
        if (not isinstance(item,dict) or set(item)!={'fingerprint','reserved_upper_microcny','confirmation_reference','scope'} or
                item['scope']!='new_tasks_only' or not isinstance(item['fingerprint'],str) or not re.fullmatch(r'[a-f0-9]{64}',item['fingerprint']) or
                type(item['reserved_upper_microcny']) is not int or item['reserved_upper_microcny']<=0 or
                not isinstance(item['confirmation_reference'],str) or not re.fullmatch(r'[A-Za-z0-9_:/.-]{4,160}',item['confirmation_reference']) or item['fingerprint'] in result):
            raise ValueError('unknown_approval_fields')
        result[item['fingerprint']]=item['reserved_upper_microcny']
    return result


def active_model_tasks(tasks):
    with tasks.db() as db:
        active={(r['owner'],r['id']) for r in db.execute("SELECT owner,id FROM tasks WHERE state='RUNNING' AND run_id IS NOT NULL AND lease IS NOT NULL")}
    # Trusted host registration only. The callback must query native rows directly,
    # never call this union helper again. No cross-DB callback under the tasks lock.
    native=getattr(tasks,'_native_active_model_tasks',None)
    if native is not None:
        if not callable(native):raise ValueError('native_liveness_callback_required')
        active.update(native())
    return active


def spending_hold(daily, tasks, owner, *, active_tasks=None):
    """Include host-verified native turns without replacing original FC liveness."""
    from proxy_gateway import require_reconciled_usage
    if active_tasks is not None and not callable(active_tasks):
        raise ValueError('active_tasks_callback_required')
    with daily.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_reservations'").fetchone():
            return None
        rows = db.execute('SELECT r.fingerprint,r.owner,r.task,r.microcny,m.state FROM hermes_reservations r '
                          'JOIN model_calls m ON m.fingerprint=r.fingerprint').fetchall()
    running=active_model_tasks(tasks)
    if active_tasks is not None:running.update(active_tasks())
    try:
        require_reconciled_usage(rows, {}, owner, None, allow_unknown_costs=True,active_tasks=running)
    except ValueError as error:
        if str(error) != 'pilot_usage_hold':
            raise
        return 'pilot_usage_hold'
    return None


def gateway(daily, tasks, book, deadline=None, provider_lane="general", *, material_execution=False,
            native_chat_scope=None, active_native_tasks=None):
    from fc_daily import provider_slot, model_daily_limit
    from direct_provider import MODEL, POLICY_ID, request_model, prepare_request
    from proxy_gateway import schemas, task_schemas, native_scope
    native = native_chat_scope is not None
    if native and (not native_scope(native_chat_scope) or book is not native_chat_scope or
                   not callable(active_native_tasks) or material_execution):
        raise ValueError('native_gateway_identity')
    if native:
        bound=native_chat_scope._binding
        native_chat_scope.context(bound['owner'],bound['turn_id'],bound['lease'])
        pricing=native_chat_scope.pricing_context
        expected='pricing' if pricing is not None else 'general'
        if provider_lane != expected:raise PermissionError('native_provider_lane')
        if pricing is not None:
            from conversation_native import validate_pricing_context
            validate_pricing_context(pricing,bound['conversation_id'])
    if material_execution is not bool(getattr(book, 'material_execution', False)):
        raise ValueError('material_gateway_identity')
    if material_execution and provider_lane != 'general':
        raise PermissionError('material_pricing_lane_denied')
    def effective_schemas():
        return task_schemas(book) if material_execution or native else schemas()
    policy = {'id': POLICY_ID, 'model': MODEL,
              'price_version': 'deepseek-direct-no-cny-invoice-or-fx-v1',
              'input_microcny': None, 'output_microcny': None}
    def provider(request):
        options={'native_chat':True} if native else {}
        if deadline is not None:options['deadline']=deadline
        raw = request_model(request,effective_schemas(),**options)
        if not isinstance(raw, dict) or raw.get('model') != MODEL:
            status=raw.get('status') if isinstance(raw,dict) else None
            known={'configuration_missing','configuration_invalid','input_too_large','invalid_response','http_rejected','unknown_transport','scheduled_deadline'}
            code=raw.get('http_status') if isinstance(raw,dict) else None
            error=ValueError('provider_'+status+('_'+str(code) if type(code) is int and 100<=code<=599 else '') if status in known else 'provider_identity_or_outcome')
            error.response=raw
            raise error
        return raw
    if provider_lane not in ('general','pricing'):raise ValueError('provider_lane_invalid')
    slot_root=daily.root if provider_lane=='general' else daily.root/'pricing-review'
    slot_root.mkdir(mode=0o700,exist_ok=True)
    budget=UnifiedBudget(daily.db, policy, lambda: datetime.now(timezone.utc),allow_unknown_costs=True)
    budget.active_tasks=active_native_tasks if native else lambda:active_model_tasks(tasks)
    scope = native_chat_scope if native else ScopedTools(tasks, book, lambda: datetime.now(timezone.utc),deadline=deadline)
    return ModelGateway(scope,
                        budget, lambda: provider_slot(slot_root), provider,
                        # Conservative byte+framing reservation bound; no cumulative quota.
                        # Actual usage remains authoritative and missing usage stays unknown.
                        conservative_input_bound,
                          model_daily_limit, preflight=lambda req:prepare_request(req,effective_schemas(),native_chat=True) if native else prepare_request(req,effective_schemas()),transport_retries=0 if material_execution or native else 2)


def native_gateway(daily, scope, *, active_tasks, deadline=None, provider_lane="general"):
    """Use the existing provider, limits and usage ledger without an FC TaskStore."""
    return gateway(daily, None, scope, deadline=deadline, provider_lane=provider_lane, native_chat_scope=scope,
                   active_native_tasks=active_tasks)


def approved_background(root):
    root = Path(root)/'assets'
    meta = json.loads((root/'knowledge-derived.json').read_text('utf-8'))
    content = (root/'knowledge-derived.md').read_text('utf-8')
    return import_background(content, approved_sha256=meta['sha256'], version=meta['version'],
                             source_reference=meta['source_reference'])
