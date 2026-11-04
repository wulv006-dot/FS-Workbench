"""FS-owned nightly entry; missing installation evidence is reported, never fabricated."""
import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

from .contracts import make_daily_context
from .daily import run_daily
from .retention import ResourcePolicy, footprint, backup_verified, cleanup_owned_data
from .sources import GoogleSource, GoogleTransport
from .store import Store


def run(config, clock=lambda: dt.datetime.now(dt.timezone.utc)):
    context = make_daily_context(clock())
    if not context.collection_allowed:
        return dict(status='outside_night_window')
    configured = config.get('sources', {})
    missing = [name for name in ('gsc', 'ga4', 'orders') if not configured.get(name)]
    if not config.get('resource_policy'):
        return dict(status='resource_baseline_missing', missing_sources=missing)
    policy = ResourcePolicy(**config['resource_policy'])
    root = Path(config['data_root'])
    limits = config['http']
    transport = GoogleTransport(**limits, clock=clock)
    sources = [GoogleSource(name, transport, **configured[name]) for name in ('gsc', 'ga4') if configured.get(name)]
    if configured.get('pages'):
        from .pages import PageSource
        sources.append(PageSource(configured['pages']['urls'], clock=clock,
            http={key:limits[key] for key in ('connect_seconds','idle_seconds','response_emergency_bytes')}))
    if configured.get('orders'):
        raise ValueError('ADMIN_ORDER_LIVE_BINDING_NOT_IMPLEMENTED')
    core = Store(root)
    growth = config['temporary_reserve_bytes']
    if type(growth) is not int or growth <= 0:
        raise ValueError('TEMPORARY_RESERVE_REQUIRED')
    margin = config.get('publication_finish_seconds')
    if type(margin) not in (int, float) or not 0 <= margin < 6.5*3600:
        raise ValueError('PUBLICATION_FINISH_MARGIN_REQUIRED')
    decisions = {}
    def admit():
        decision = policy.admit(used=footprint(root), free=shutil.disk_usage(root).free, estimate=growth)
        decisions[decision['state']] = decisions.get(decision['state'], 0) + 1
        return decision['allowed']
    try:
        result = run_daily(core, sources, clock=clock, admit=admit, finish_margin_seconds=margin)
    finally:
        transport.close()
    result.update(missing_sources=missing, upstream_requests=transport.calls, resource_states=decisions)
    if result['status'] == 'published':
        try:
            if admit():
                result['maintenance'] = dict(backup=backup_verified(core), cleanup=cleanup_owned_data(core, dt.date.fromisoformat(context.publication_date)))
            else:
                result['maintenance'] = dict(status='resource_emergency_deferred')
        except (OSError, ValueError) as error:
            result['maintenance'] = dict(status='failed', error=type(error).__name__)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    receipt = run(config)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt['status'] == 'published' else 1


if __name__ == '__main__':
    raise SystemExit(main())
