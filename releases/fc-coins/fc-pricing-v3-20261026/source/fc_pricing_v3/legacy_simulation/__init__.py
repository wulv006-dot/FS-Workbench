"""Pinned, read-only replay of retired selectors on historical evidence."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
from pathlib import Path


SOURCES = {
    'legacy_80_15_5': ('weighted_80_15_5.py', '91f8d143e21e05544b17442bd8a20d3735f62caa4aa5b182584a4fd4c4ec993a'),
    'legacy_itemd2r_parity': ('itemd2r_parity.py', 'f68459feb07ff59690a4a6b716e9760a7c556e74b92b7e02dfa4c57d23eb0a42'),
}

DUAL10_PINS = {'dual10_financial.py':'6ed1df03da6d3e667c154b76c9ab9f01d6e82bf62e91e3d0ccc9d26f4d6cd730',
               'dual10_engine.py':'f5483cd185cfbc016f445ada1682aeef2aa3d886e58a548fc26de0f671076ff6'}

def evaluate_dual10(evidence,mode,**kwargs):
    for name,expected in DUAL10_PINS.items():
        if hashlib.sha256((Path(__file__).parent/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:raise ValueError('simulation_dual10_archive_changed')
    from .dual10_engine import evaluate
    result=evaluate(evidence,mode,**kwargs)
    return dict(result,financial_contract_version='fc27_dual10_archived_v15',execution_authorized=False)


def replay(snapshot, name):
    """Return a frozen action or an explicit gap; never a production decision ID."""
    filename, expected = SOURCES[name]
    source = Path(__file__).parent / filename
    if hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
        return dict(status='legacy_source_version_mismatch', source_sha256=expected)
    evidence = deepcopy(snapshot.get('evidence') or {})
    try:
        # A source collected after the job started can still precede its saved decision.
        as_of = datetime.fromisoformat((snapshot.get('created_at') or evidence['checked_at']).replace('Z', '+00:00'))
        if as_of.tzinfo is None:
            raise ValueError('historical_asof_timezone_missing')
        spec = importlib.util.spec_from_file_location('frozen_' + name, source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows = [dict(platform=p) for p in ('PS', 'XBOX', 'PC')]
        module.apply_decision(rows, evidence, {}, now=as_of)
        prices = {r['platform']: Decimal(r['target_page_usd']) for r in rows}
        if prices['PS'] != prices['XBOX'] or any(value <= 0 for value in prices.values()):
            raise ValueError('legacy_price_scope_invalid')
        return dict(status='available', source_sha256=expected,
                    action=dict(base_prices=dict(console=str(prices['PS']), pc=str(prices['PC'])),
                                region_coefficients={}),
                    as_of=as_of.isoformat(), read_only=True, execution_authorized=False,
                    training_eligible=False)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return dict(status='legacy_replay_gap', source_sha256=expected,
                    reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    read_only=True, execution_authorized=False, training_eligible=False)


# Original e915cce evaluator; used exclusively by historical shadow replay.
PLATFORM_V2_PINS = {'platform_v2_financial.py': 'b44b8abecc504c0975ee1dab38aaf714112c3dd43733eb9af927cba526e25d63', 'platform_v2_engine.py': 'dc3107cd747e3a429b7d2e73d59d0ffc18a254856471b71cc70eb6386d76fa75'}

def evaluate_platform_v2(evidence,mode,**kwargs):
    context=kwargs.get('evaluation_context') or {}
    if context.get('mode')!='shadow' or context.get('training_eligible') is not False or mode not in ('daily','revenue_sprint'):
        raise ValueError('simulation_platform_v2_read_only_required')
    for name,expected in PLATFORM_V2_PINS.items():
        raw=(Path(__file__).parent/name).read_bytes().replace(b'\r\n',b'\n')
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('simulation_platform_v2_archive_changed')
    from .platform_v2_engine import evaluate
    result=evaluate(evidence,mode,**kwargs)
    return dict(result,financial_contract_version='fc27_dual20_d9_d2_v2',execution_authorized=False,training_eligible=False)
