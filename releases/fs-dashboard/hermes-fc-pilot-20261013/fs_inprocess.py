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


def spending_hold(daily, tasks, owner):
    from proxy_gateway import require_reconciled_usage
    with daily.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hermes_reservations'").fetchone():
            return None
        rows = db.execute('SELECT r.fingerprint,r.owner,r.task,r.microcny,m.state FROM hermes_reservations r '
                          'JOIN model_calls m ON m.fingerprint=r.fingerprint').fetchall()
    try:
        require_reconciled_usage(rows, {}, owner, None, allow_unknown_costs=True)
    except ValueError as error:
        if str(error) != 'pilot_usage_hold':
            raise
        return 'pilot_usage_hold'
    return None


def gateway(daily, tasks, book):
    from fc_daily import provider_slot, model_daily_limit
    from direct_provider import MODEL, POLICY_ID, request_model, prepare_request
    from proxy_gateway import schemas
    policy = {'id': POLICY_ID, 'model': MODEL,
              'price_version': 'deepseek-direct-no-cny-invoice-or-fx-v1',
              'input_microcny': None, 'output_microcny': None}
    def provider(request):
        raw = request_model(request, schemas())
        if not isinstance(raw, dict) or raw.get('model') != MODEL:
            status=raw.get('status') if isinstance(raw,dict) else None
            known={'configuration_missing','configuration_invalid','input_too_large','invalid_response','http_rejected','unknown_transport'}
            code=raw.get('http_status') if isinstance(raw,dict) else None
            error=ValueError('provider_'+status+('_'+str(code) if type(code) is int and 100<=code<=599 else '') if status in known else 'provider_identity_or_outcome')
            error.response=raw
            raise error
        return raw
    return ModelGateway(ScopedTools(tasks, book, lambda: datetime.now(timezone.utc)),
                        UnifiedBudget(daily.db, policy, lambda: datetime.now(timezone.utc),allow_unknown_costs=True),
                        lambda: provider_slot(daily.root), provider,
                        # Conservative byte+framing reservation bound; no cumulative quota.
                        # Actual usage remains authoritative and missing usage stays unknown.
                        conservative_input_bound,
                        model_daily_limit, preflight=lambda req:prepare_request(req,schemas()))


def approved_background(root):
    root = Path(root)/'assets'
    meta = json.loads((root/'knowledge-derived.json').read_text('utf-8'))
    content = (root/'knowledge-derived.md').read_text('utf-8')
    return import_background(content, approved_sha256=meta['sha256'], version=meta['version'],
                             source_reference=meta['source_reference'])
