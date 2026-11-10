"""Exact V3 code targets; the knowledge catalog has a separate immutable release."""
from pathlib import Path

TARGET_COUNT = 101

THREE_PLATFORM_SCOPE='fc-pricing-three-platform-20261110'
THREE_PLATFORM_MODULES=('platforms.py','legacy_simulation/platform_v2_engine.py',
                        'legacy_simulation/platform_v2_financial.py')
THREE_PLATFORM_TARGET_COUNT=TARGET_COUNT+2*len(THREE_PLATFORM_MODULES)
MONITOR_SQLITE_CANDIDATE='source/monitor-runtime/libsqlite3.so.0'
MONITOR_SQLITE_SOURCE='/opt/auth-portal/registration-runtime-deps/sqlite-3.53.4/lib/libsqlite3.so.3.53.4'
MONITOR_SQLITE_SHA='d3d896ba27628b174c67cfc6127c92f29c97b48dc3dfe70c84c5f6c28ca4c5f8'
MONITOR_SQLITE_PROVENANCE={'candidate':MONITOR_SQLITE_CANDIDATE,'source':MONITOR_SQLITE_SOURCE,'sha256':MONITOR_SQLITE_SHA}
THREE_PLATFORM_NEW=frozenset(prefix+'fc_pricing_v3/'+name
    for prefix in ('source/','source/hermes-copy/') for name in THREE_PLATFORM_MODULES)
THREE_PLATFORM_NEW=THREE_PLATFORM_NEW|{MONITOR_SQLITE_CANDIDATE}
THREE_PLATFORM_REPOSITORY_SOURCES={
    'source/pack_bundles_server.py':'fc27_pack_bundles_20261013/src/pack_bundles_server.py',
    'source/pack_bundles.html':'fc27_pack_bundles_20261013/web/index.html',
    'source/monitor-hooks.py':'releases/fc-coins/monitor-health-20261020/source/hooks.py',
    'source/monitor-collector.py':'releases/fc-coins/prewrite-recovery-20261012/source/monitor/collector.py'}
THREE_PLATFORM_EXTRA={
    'source/pack_bundles_server.py':'/opt/fc27-pack-bundles/pack_bundles_server.py',
    'source/pack_bundles.html':'/var/www/dashboard/modules/sports/bundles/index.html',
    'source/monitor-hooks.py':'/opt/fc-ops-readonly-monitor/hooks.py',
    'source/monitor-collector.py':'/opt/fc-ops-readonly-monitor/collector.py',
    MONITOR_SQLITE_CANDIDATE:'/opt/fc-ops-readonly-monitor/runtime/sqlite-3.53.4/lib/libsqlite3.so.0'}
THREE_PLATFORM_NAMES=tuple(prefix+'fc_pricing_v3/'+name
    for prefix in ('source/','source/hermes-copy/') for name in (
        'adapters.py','api.py','business_source.py','daily.py','engine.py','financial.py','ledger.py',
        'legacy_simulation/__init__.py','monitoring.py','order_close.py','runtime.py','scheduler.py',
        'selective_sources.py','simulation.py','smart.py','sources.py','uk_retirement.py',
        *THREE_PLATFORM_MODULES))
THREE_PLATFORM_NAMES+=tuple('source/'+name for name in ('automation_policy.py','coin_all_sync_job.py',
    'fc-pricing-v3.js','fc27-coins.html','fc27_cloud_worker.py','player_sync_job.py','pricing_sources.py','pricing_simulation.py','read_only_status.py','probe_worker.py','reconcile_original.py'))
THREE_PLATFORM_NAMES+=tuple(THREE_PLATFORM_EXTRA)

COUPON_DISPLAY_SCOPE='fc-pricing-v3-coupon-display-20261109'
COUPON_DISPLAY_SOURCE='fc27_cloud_browser/storefront_monitor.py'
COUPON_DISPLAY_EXTRA={'source/storefront_monitor.py':'/opt/fc27-cloud-browser/storefront_monitor.py'}
COUPON_DISPLAY_NAMES=('source/storefront_monitor.py',)+tuple(prefix+'fc_pricing_v3/'+name
    for prefix in ('source/','source/hermes-copy/') for name in ('smart.py','runtime.py'))
COUPON_DISPLAY_PROTECTED=('/opt/fc27-cloud-browser/local_collection.py',
    '/opt/fs-fc-control/code/manifest.json','/opt/fs-fc-control/code/fc_collection/public_sources.py',
    '/opt/fs-fc-control/code/fc_collection/client.py')

DAILY_SUMMARY_SCOPE='fc-pricing-v3-daily-summary-v2-20261109'
DAILY_SUMMARY_NAMES=('source/hermes_pricing_bridge.py','source/conversation_http.py','source/pricing_operations.py',
                     'source/fc_pricing_v3/api.py','source/hermes-copy/fc_pricing_v3/api.py')

DAILY_REPAIR_SCOPE='fc-pricing-v3-daily-repair-20261109'
DAILY_REPAIR_NAMES=('source/hermes_pricing_bridge.py','source/fc_pricing_v3/daily.py','source/hermes-copy/fc_pricing_v3/daily.py')

COLLECTION_SCOPE='fc-pricing-v3-collection-routing-20261102'
COLLECTION_NAMES=('source/fc_pricing_v3/sources.py','source/hermes-copy/fc_pricing_v3/sources.py','source/server_quote_job.py')

REPAIR_SCOPE='fc-pricing-v3-quote-tool-repair-20261107'
REPAIR_NAMES=('source/server_quote_job.py','source/pricing_operations.py',
              'source/fc_pricing_v3/api.py','source/hermes-copy/fc_pricing_v3/api.py')

QUOTE_FRAGMENT_SCOPE='fc-pricing-v3-quote-fragment-20261108'
QUOTE_FRAGMENT_NAMES=('source/fc27_cloud_api.py','source/pricing_operations.py')

QUOTE_PREVIEW_SCOPE='fc-pricing-v3-quote-preview-20261108'
QUOTE_PREVIEW_NAMES=QUOTE_FRAGMENT_NAMES+('source/repricing_logic.js',)

BIDIRECTIONAL_SCOPE='fc-pricing-smart-bidirectional-20261107'
BIDIRECTIONAL_NAMES=tuple(prefix+'fc_pricing_v3/'+name for prefix in ('source/','source/hermes-copy/') for name in (
    'api.py','business_source.py','daily.py','engine.py','ledger.py','market_registry.py','observations.py',
    'runtime.py','scheduler.py','selective_sources.py','smart.py'))
BIDIRECTIONAL_NAMES+=('source/fc27_cloud_worker.py','source/fc-pricing-v3.js','source/pricing_simulation.py')

DELTA_SCOPE='fc-pricing-v3-smart-decision-20261105'
DELTA_NAMES=tuple(prefix+'fc_pricing_v3/'+name for prefix in ('source/','source/hermes-copy/') for name in (
    'api.py','business_source.py','demand_model.py','engine.py','ledger.py','runtime.py','scheduler.py','selective_sources.py','smart.py'))
DELTA_NAMES+=('source/fc27-coins.html','source/fc-pricing-v3.js','source/pricing_simulation.py')
DELTA_NEW=frozenset(prefix+'fc_pricing_v3/smart.py' for prefix in ('source/','source/hermes-copy/'))
SHADOW_SCOPE = 'fc-pricing-v3-sqlite-shadow-20261026'
SHADOW_NAMES = tuple(prefix + 'fc_pricing_v3/' + name for prefix in ('source/', 'source/hermes-copy/')
                     for name in ('ledger.py', 'scheduler.py', 'simulation.py', 'shadow_worker.py'))
SHADOW_NAMES += ('source/hermes_pricing_bridge.py',)


OPERATING_SCOPE='fc-pricing-v3-daily-program-20261026'
OPERATING_NAMES=tuple('source/'+name for name in (
    'automation_policy.py','fc27_cloud_worker.py','hermes_pricing_bridge.py','pricing_operations.py',
    'server_quote_job.py','snapshot_layer.py','conversation_service.py','conversation_http.py',
    'fc27-coins.html','fc-pricing-v3.js','systemd/fc-pricing-v3-shadow.service'))
OPERATING_NAMES+=tuple(prefix+'fc_pricing_v3/'+name for prefix in ('source/','source/hermes-copy/') for name in (
    '__init__.py','api.py','business_source.py','ledger.py','monitoring.py','observations.py','regional_public.py',
    'runtime.py','scheduler.py','shadow_worker.py','simulation.py','sources.py','selective_sources.py','daily.py'))
OPERATING_NEW=frozenset(prefix+'fc_pricing_v3/'+name for prefix in ('source/','source/hermes-copy/') for name in ('selective_sources.py','daily.py'))


def targets(source):
    source = Path(source)
    rows = {}
    for name in ('collect_p2pah_cost.py', 'automation_policy.py', 'automation_tick.py', 'clear_cache_after_write.py',
                 'clear_cache_after_write.sh', 'coin_all_sync_job.py', 'execute_price.sh',
                 'fc27_cloud_api.py', 'fc27_cloud_worker.py', 'fc27_quote_engine.py',
                 'hermes_pricing_bridge.py', 'itemd2r_reader.py', 'player_sync_job.py', 'price_writer.py', 'pricing_state.py',
                 'pricing_v2.py', 'pricing_sources.py', 'reconcile_original.py', 'reconcile_price.sh',
                 'repricing_logic.js', 'restore_price.sh', 'sync_players.sh', 'server_quote_job.py', 'snapshot_layer.py'):
        rows[name] = '/opt/fc27-cloud-browser/' + name
    rows['fc_shared_admin.py'] = '/opt/fc27-cloud-browser/fc_shared_admin.py'
    for name in ('pricing_operations.py', 'pricing_simulation.py', 'strategy_tools.py'):
        rows[name] = '/opt/fs-hermes-fc/' + name
    rows['conversation_service.py'] = '/opt/fs-hermes-fc/conversation_service.py'
    rows['conversation_http.py'] = '/opt/fs-exact-range-20261001/conversation_http.py'
    for name in ('probe_worker.py', 'read_only_status.py'):
        rows[name] = '/opt/fc-ops-readonly-monitor/' + name
    for name in ('fc27-coins.html', 'fc27-quote-cloud.js', 'fc-pricing-v3.js'):
        rows[name] = '/var/www/dashboard/' + name
    for name in ('fc-pricing-v3.service', 'fc-pricing-v3-shadow.service'):
        rows['systemd/' + name] = '/etc/systemd/system/' + name
    for file in (source/'fc_pricing_v3').rglob('*.py'):
        name = file.relative_to(source).as_posix()
        if name.removeprefix('fc_pricing_v3/') in THREE_PLATFORM_MODULES:
            continue
        rows[name] = '/opt/fc27-cloud-browser/' + name
        rows['hermes-copy/' + name] = '/opt/fs-hermes-fc/' + name
    return rows


def three_platform_targets(source):
    rows=targets(source)
    for name in THREE_PLATFORM_MODULES:
        relative='fc_pricing_v3/'+name
        rows[relative]='/opt/fc27-cloud-browser/'+relative
        rows['hermes-copy/'+relative]='/opt/fs-hermes-fc/'+relative
    return rows
