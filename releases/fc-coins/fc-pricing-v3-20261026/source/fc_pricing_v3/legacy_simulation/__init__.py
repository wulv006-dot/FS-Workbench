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


def replay(snapshot, name):
    """Return a frozen action or an explicit gap; never a production decision ID."""
    filename, expected = SOURCES[name]
    source = Path(__file__).parent / filename
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        return dict(status='legacy_source_version_mismatch', source_sha256=expected)
    evidence = deepcopy(snapshot.get('evidence') or {})
    try:
        as_of = datetime.fromisoformat(evidence['checked_at'].replace('Z', '+00:00'))
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
