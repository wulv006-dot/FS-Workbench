"""FS-owned nightly entry; missing installation evidence is reported, never fabricated."""
import argparse
import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

from .contracts import make_daily_context
from .daily import run_daily
from .retention import ResourcePolicy, footprint, backup_verified, cleanup_owned_data, cleanup_ai, memory_admission, temporary_reserve
from .sources import GoogleSource, GoogleTransport
from .store import Store


def run(config, clock=lambda: dt.datetime.now(dt.timezone.utc), *, order_reader=None):
    context = make_daily_context(clock())
    if not context.collection_allowed:
        return dict(status='outside_night_window')
    configured = config.get('sources', {})
    missing = [name for name in ('gsc', 'ga4', 'admin') if not configured.get(name)]
    if not config.get('resource_policy') or not config.get('memory_policy'):
        return dict(status='resource_baseline_missing', missing_sources=missing)
    policy = ResourcePolicy(**config['resource_policy'])
    root = Path(config['data_root'])
    limits = config['http']
    margin = config.get('publication_finish_seconds')
    if type(margin) not in (int, float) or not 0 <= margin < 6.5*3600:
        raise ValueError('PUBLICATION_FINISH_MARGIN_REQUIRED')
    transport = GoogleTransport(**limits, clock=clock)
    core = Store(root)
    serp_transport = calendar_source = None
    summary_reader = None
    sources = [GoogleSource(name, transport, **configured[name]) for name in ('gsc', 'ga4') if configured.get(name)]
    if configured.get('admin'):
        from .admin_summary import NativeSummaryReader, AdminSummarySource
        summary_reader = NativeSummaryReader(clock=clock)
        sources.append(AdminSummarySource(summary_reader))
    if isinstance(configured.get('orders'), dict) and configured['orders'].get('enabled') is True:
        if order_reader is None:
            missing.append('orders')
        else:
            from .order_source import OrderSource
            sources.append(OrderSource(order_reader))
    if configured.get('pages'):
        from .pages import PageSource
        sources.append(PageSource(configured['pages']['urls'], clock=clock,
            http={key:limits[key] for key in ('connect_seconds','idle_seconds','response_emergency_bytes')}))
    if configured.get('serp') and (not isinstance(configured['serp'],dict) or configured['serp'].get('enabled') is True):
        from .serp import BrightDataTransport, SerpSource
        serp_transport=BrightDataTransport(core,configured['serp'],limits,clock=clock,finish_margin_seconds=margin)
        sources.append(SerpSource(configured['serp'],serp_transport,clock=clock))
    if configured.get('calendar') and (not isinstance(configured['calendar'],dict) or configured['calendar'].get('enabled') is True):
        from .calendar import CalendarSource
        calendar_source=CalendarSource(configured['calendar'],http=limits,clock=clock,finish_margin_seconds=margin)
        sources.append(calendar_source)
    growth = config['temporary_reserve_bytes']
    if type(growth) is not int or growth <= 0:
        raise ValueError('TEMPORARY_RESERVE_REQUIRED')
    decisions = {}
    def admit():
        used = footprint(root)+(footprint(Path(config['control_root'])) if config.get('control_root') else 0)
        try:
            ai_bytes = footprint(Path(config['ai_root'])) if config.get('ai_root') else 0
            decisions['ai_storage'] = dict(status='measured',physical_bytes=ai_bytes)
            decisions['seo_total_physical_bytes'] = used+ai_bytes
        except (OSError,ValueError) as error:
            decisions['ai_storage'] = dict(status='unavailable',error=type(error).__name__)
            decisions['seo_total_physical_bytes'] = None
        # AI occupancy is recorded separately; host free space still includes its real disk use.
        decision = policy.admit(used=used, free=shutil.disk_usage(root).free, estimate=temporary_reserve(core,growth))
        memory = memory_admission(config['memory_policy'])
        decisions['memory_'+memory['state']] = decisions.get('memory_'+memory['state'],0)+1
        decisions['memory_peak_rss_bytes'] = max(decisions.get('memory_peak_rss_bytes',0),memory['rss_bytes'])
        decisions[decision['state']] = decisions.get(decision['state'], 0) + 1
        return decision['allowed'] and memory['allowed']
    try:
        result = run_daily(core, sources, clock=clock, admit=admit, finish_margin_seconds=margin)
    finally:
        transport.close()
    result.update(missing_sources=missing, upstream_requests=transport.calls+(summary_reader.calls if summary_reader else 0)+(serp_transport.calls+serp_transport.resolution_calls if serp_transport else 0)+(calendar_source.calls if calendar_source else 0)+getattr(order_reader,'calls',0), resource_states=decisions)
    maintenance = {}
    try:
        maintenance['cleanup'] = cleanup_owned_data(core,dt.date.fromisoformat(context.publication_date))
        if admit():
            maintenance['backup'] = backup_verified(core)
        else:
            maintenance['status'] = 'resource_emergency_deferred'
    except (OSError, ValueError, sqlite3.Error) as error:
        maintenance.update(status='failed', error=type(error).__name__)
    if config.get('ai_root'):
        try:
            maintenance['ai_cleanup'] = cleanup_ai(config['ai_root'],dt.date.fromisoformat(context.publication_date))
        except (OSError, ValueError, sqlite3.Error) as error:
            maintenance['ai_cleanup'] = dict(status='failed',error=type(error).__name__)
    result['maintenance'] = maintenance
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    order_reader = None
    orders = config.get('sources', {}).get('orders')
    if isinstance(orders, dict) and orders.get('enabled') is True:
        from .order_reader import NativeOrderFactsReader
        order_reader = NativeOrderFactsReader()
    receipt = run(config, order_reader=order_reader)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt['status'] == 'published' else 1


if __name__ == '__main__':
    raise SystemExit(main())
