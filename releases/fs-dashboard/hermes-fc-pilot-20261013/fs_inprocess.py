"""Provider and source factories for the original FS process, never a new key owner."""
from datetime import datetime, timezone
from pathlib import Path
import json

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
            raise ValueError('provider_identity_or_outcome')
        return raw
    return ModelGateway(ScopedTools(tasks, book, lambda: datetime.now(timezone.utc)),
                        UnifiedBudget(daily.db, policy, lambda: datetime.now(timezone.utc)),
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
