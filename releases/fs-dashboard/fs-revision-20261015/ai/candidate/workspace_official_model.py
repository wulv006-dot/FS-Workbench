"""Use the existing FS-owned official provider and ledger for structured facts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# This is the existing deployed, reviewed runtime; no second credentials or provider.
RUNTIME = '/opt/fs-hermes-fc'
MODEL = 'deepseek-flash'
CONTEXT_TOKENS = 1048576
OUTPUT_TOKENS = 393216
POLICY = 'workspace-official-high-v1'


def runtime():
    if RUNTIME not in sys.path:
        sys.path.insert(0, RUNTIME)
    import direct_provider
    from proxy_gateway import schemas
    return direct_provider, schemas()


def bounded_model(projected, callback):
    from fc_daily import DailyReports
    provider, _ = runtime()
    # Separate fingerprints from retired supplier receipts; preserve old ledger rows.
    envelope = {'provider_policy': POLICY, 'facts': projected}
    ledger = DailyReports(None, '/var/lib/fs-business-ranges/fc-daily',
                          is_configured=lambda: Path(provider.DEFAULT_KEY_FILE).is_file())
    return ledger.bounded_model(envelope, lambda value: callback(value['facts']))


def request_model(messages, projected, validator, *, max_tokens=6000, timeout=120):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 1800:
        return {'status': 'configuration_invalid'}
    provider, tools = runtime()
    request = {'model': MODEL, 'messages': messages, 'max_tokens': provider.OUTPUT_TOKENS,
               'tools': [], 'stream': False, 'enable_thinking': True, 'reasoning_effort': 'high'}
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout)
    raw = provider.request_model(request, tools, deadline=deadline)
    if not isinstance(raw, dict):
        return {'status': 'invalid_response'}
    if raw.get('status'):
        return raw
    # Diagnostic storage needs public output and usage, never private reasoning.
    for choice in raw.get('choices', []):
        if isinstance(choice.get('message'), dict):
            choice['message'].pop('reasoning_content', None)
    return validator(raw, projected)
