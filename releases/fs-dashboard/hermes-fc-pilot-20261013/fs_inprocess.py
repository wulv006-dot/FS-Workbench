"""Provider and source factories for the original FS process, never a new key owner."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import stat

from background import import_background
from proxy_gateway import ModelGateway, ScopedTools, UnifiedBudget
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


def gateway(daily, tasks, book):
    from fc_daily import provider_slot, model_daily_limit
    from fc_daily_model import MODEL
    from ai_advisor_model import request_model
    policy = {'id': 'no-pilot-quotas-public-peak-estimate-v1', 'model': MODEL,
              'price_version': 'bailian-public-20261013-beijing-peak-no-discounts',
              'input_microcny': 2, 'output_microcny': 8}
    def provider(request):
        # request_model continues to load its existing key inside this process.
        # Its opt-in tools argument is the only shared provider-source delta.
        raw = request_model(request['messages'], {}, lambda value, _: value,
                            max_tokens=request['max_tokens'], timeout=120, tools=request['tools'],
                            reasoning_effort=request.get('reasoning_effort'))
        if not isinstance(raw, dict) or raw.get('model') != MODEL:
            status=raw.get('status') if isinstance(raw,dict) else None
            known={'configuration_missing','configuration_invalid','input_too_large','invalid_response','http_rejected','unknown_transport'}
            code=raw.get('http_status') if isinstance(raw,dict) else None
            error=ValueError('provider_'+status+('_'+str(code) if type(code) is int and 100<=code<=599 else '') if status in known else 'provider_identity_or_outcome')
            error.response=raw
            raise error
        return raw
    return ModelGateway(ScopedTools(tasks, book, lambda: datetime.now(timezone.utc)),
                        UnifiedBudget(daily.db, policy, lambda: datetime.now(timezone.utc),accepted_unknowns=approved_unknowns(tasks)),
                        lambda: provider_slot(daily.root), provider,
                        # Conservative byte+framing reservation bound; no cumulative quota.
                        # Actual usage remains authoritative and missing usage stays unknown.
                        lambda req: len(json.dumps(req, ensure_ascii=False).encode())+8192,
                        model_daily_limit)


def approved_background(root):
    root = Path(root)/'assets'
    meta = json.loads((root/'knowledge-derived.json').read_text('utf-8'))
    content = (root/'knowledge-derived.md').read_text('utf-8')
    return import_background(content, approved_sha256=meta['sha256'], version=meta['version'],
                             source_reference=meta['source_reference'])
