"""Exact FC code targets; the knowledge catalog has a separate release."""
import ast
import hashlib

TARGET_COUNT = 101

# New curve modules belong to an explicit candidate scope. Merely adding a
# source file must not silently expand a historical publisher's exact targets.
CURVE_V6_SCOPE = 'fc-pricing-owned-curve-v6-20261113'
CURVE_V6_BASE = '7042edaf90647cbd51ab7df3e35f7b4341f72b3f'
CURVE_V6_MODULES = ('competitor_offers.py', 'cost_inputs_v6.py', 'cost_model.py', 'price_curve.py',
                    'pricing_proof_v6.py', 'planning_baskets_v6.py', 'curve_strategy_v6.py',
                    'order_projection_v6.py', 'native_checkout_evidence.py')
CURVE_V6_CHANGED_MODULES = (
    'adapters.py', 'api.py', 'business_source.py', 'daily.py', 'dispatch.py', 'engine.py',
    'ledger.py', 'market_registry.py', 'monitoring.py', 'observations.py', 'runtime.py', 'scheduler.py', 'selective_sources.py',
    'sources.py',
)
CURVE_V6_TOP_LEVEL = (
    'coin_all_sync_job.py', 'fc27_cloud_api.py', 'fc27_cloud_worker.py', 'price_writer.py', 'pricing_simulation.py',
    'pricing_sources.py',
    'reconcile_original.py', 'server_quote_job.py', 'snapshot_layer.py',
)
CURVE_V6_SOURCE_NAMES = frozenset(CURVE_V6_TOP_LEVEL) | {
    'fc_pricing_v3/' + name for name in CURVE_V6_CHANGED_MODULES + CURVE_V6_MODULES
}
# The ArabUT lease change ships through its existing node/control role publisher.
CURVE_V6_SEPARATE_ROLE_SOURCES = frozenset('fc_collection/' + name for name in (
    'adapters.py', 'client.py', 'contracts.py', 'public_sources.py',
))
CURVE_V6_NEW = frozenset(prefix + 'fc_pricing_v3/' + name
    for prefix in ('source/', 'source/hermes-copy/') for name in CURVE_V6_MODULES)
CURVE_AVERAGE_SCOPE = 'fc-pricing-v6-average-discount-20261113'
CURVE_AVERAGE_MODULES = ('average_discount_v6.py', 'business_source.py', 'curve_strategy_v6.py',
                         'daily.py', 'native_checkout_evidence.py', 'price_curve.py', 'pricing_proof_v6.py',
                         'runtime.py', 'selective_sources.py')
CURVE_AVERAGE_TOP_LEVEL = ('fc27_cloud_worker.py', 'server_quote_job.py', 'fc27-coins.html', 'fc-pricing-v3.js',
                           'hermes_pricing_bridge.py', 'pricing_operations.py')
CURVE_AVERAGE_TARGET_COUNT = len(CURVE_AVERAGE_TOP_LEVEL) + 2 * len(CURVE_AVERAGE_MODULES)
CURVE_AVERAGE_NEW = frozenset(prefix + 'fc_pricing_v3/average_discount_v6.py'
                              for prefix in ('source/', 'source/hermes-copy/'))
CURVE_INSURANCE_SCOPE = 'fc-pricing-v6-insurance-20261117'
CURVE_INSURANCE_TARGET_COUNT = 9
CURVE_STABILITY_SCOPE = 'fc-pricing-v6-stability-20261117'
CURVE_STABILITY_TARGET_COUNT = 8
CURVE_MARKET_SCOPE = 'fc-pricing-v6-market-anchor-20261117'
CURVE_MARKET_TARGET_COUNT = 10
CURVE_ARAB_QUOTE_SCOPE = 'fc-pricing-v6-arab-quote-20261119'
CURVE_ARAB_QUOTE_TARGET_COUNT = 2
CURVE_MARGIN_BAND_SCOPE = 'fc-pricing-v6-margin-band-20261118'
CURVE_MARGIN_BAND_TARGET_COUNT = 13
CURVE_WEEKLY_SCOPE = 'fc-pricing-v6-weekly-ladder-20261117'
CURVE_WEEKLY_TARGET_COUNT = 12
CURVE_WEEKLY_NEW = frozenset(prefix+'fc_pricing_v3/weekly_ladder.py' for prefix in ('source/', 'source/hermes-copy/'))
CURVE_STABILITY_REPOSITORY_SOURCES = {'source/collect_p2pah_cost.sh':
    'releases/fc-coins/cost-timeout-20261025/source/collect_p2pah_cost.sh'}

# The original V3 mapping must also be available from a partial V6 stage.
BASE_MODULES = (
    '__init__.py', 'adapters.py', 'admin_readback.py', 'api.py', 'business_source.py',
    'daily.py', 'demand_model.py', 'dispatch.py', 'engine.py', 'financial.py', 'history.py',
    'ledger.py', 'legacy_simulation/__init__.py', 'legacy_simulation/dual10_engine.py',
    'legacy_simulation/dual10_financial.py', 'legacy_simulation/itemd2r_parity.py',
    'legacy_simulation/weighted_80_15_5.py', 'market_registry.py', 'monitoring.py',
    'observations.py', 'order_close.py', 'region_adapter.py', 'region_source.py',
    'regional_public.py', 'runtime.py', 'scheduler.py', 'selective_sources.py',
    'shadow_worker.py', 'simulation.py', 'smart.py', 'sources.py', 'uk_retirement.py',
)

LOOTBAR_CALLER_SCOPE='fc-lootbar-183-caller-20261111'
LOOTBAR_CALLER_NAMES=tuple('source/'+n for n in ('snapshot_layer.py','server_quote_job.py','fc27_cloud_worker.py','collect_lootbar.sh'))
LOOTBAR_CALLER_SOURCE='fc27_cloud_browser/collect_lootbar.sh'
LOOTBAR_CALLER_EXTRA={'source/collect_lootbar.sh':'/opt/fc27-cloud-browser/collect_lootbar.sh'}
LOOTBAR_CALLER_REPOSITORY_SOURCES={'source/collect_lootbar.sh':LOOTBAR_CALLER_SOURCE}
for _name in ('lootbar_server_collector.py','background.js'):
    _candidate='source/lootbar-collector/'+_name
    LOOTBAR_CALLER_EXTRA[_candidate]='/opt/fc27-cloud-browser/collector/'+_name
    LOOTBAR_CALLER_REPOSITORY_SOURCES[_candidate]='releases/ops/pricing-recovery-20261023/fc_residency/source/'+_name
    LOOTBAR_CALLER_NAMES+=(_candidate,)

CURVE_V6_COLLECTION_TARGETS = {
    **LOOTBAR_CALLER_EXTRA,
    'source/collect_competitor.sh': '/opt/fc27-cloud-browser/collect_competitor.sh',
    'source/collector/collect_competitor_browser.py': '/opt/fc27-cloud-browser/collector/collect_competitor_browser.py',
}
CURVE_V6_REPOSITORY_SOURCES = {
    **LOOTBAR_CALLER_REPOSITORY_SOURCES,
    'source/collect_competitor.sh': 'fc27_cloud_browser/collect_competitor.sh',
    'source/collector/collect_competitor_browser.py': 'fc27_cloud_browser/collect_competitor_browser.py',
}
CURVE_V6_EXECUTABLES = ('source/collect_lootbar.sh', 'source/collect_competitor.sh')
CURVE_V6_PROTECTED = (
    '/opt/fs-sports-outbound/collect_fc_u4gm.py',
    '/opt/fs-exact-range-20261001/order_facts_runtime.py',
    '/opt/fs-exact-range-20261001/order_facts_source.py',
    '/opt/fs-exact-range-20261001/order_facts.py',
    '/opt/fs-hermes-fc/shared_es_facts.py',
    '/opt/fs-hermes-fc/order_attribution.py',
)

THREE_PLATFORM_SCOPE='fc-pricing-three-platform-20261110'
THREE_PLATFORM_MODULES=('platforms.py','legacy_simulation/platform_v2_engine.py',
                        'legacy_simulation/platform_v2_financial.py')
THREE_PLATFORM_TARGET_COUNT=TARGET_COUNT+2*len(THREE_PLATFORM_MODULES)
CURVE_V6_TARGET_COUNT = (len(CURVE_V6_TOP_LEVEL) + len(CURVE_V6_COLLECTION_TARGETS)
                         + 2 * len(CURVE_V6_CHANGED_MODULES + CURVE_V6_MODULES))
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
    rows.update(module_targets(BASE_MODULES))
    return rows


def three_platform_targets(source):
    return {**targets(source), **module_targets(THREE_PLATFORM_MODULES)}


def curve_v6_targets(source):
    current = targets(source)
    return {
        **{name: current[name] for name in CURVE_V6_TOP_LEVEL},
        **module_targets(CURVE_V6_CHANGED_MODULES + CURVE_V6_MODULES),
        **{name.removeprefix('source/'): path for name, path in CURVE_V6_COLLECTION_TARGETS.items()},
    }


def module_targets(modules):
    rows = {}
    for name in modules:
        relative = 'fc_pricing_v3/' + name
        rows[relative] = '/opt/fc27-cloud-browser/' + relative
        rows['hermes-copy/' + relative] = '/opt/fs-hermes-fc/' + relative
    return rows


def curve_average_targets(source):
    current = targets(source)
    return {**{name:current[name] for name in CURVE_AVERAGE_TOP_LEVEL},
            **module_targets(CURVE_AVERAGE_MODULES)}


def curve_insurance_targets(source):
    return {'coin_all_sync_job.py': targets(source)['coin_all_sync_job.py'],
            **module_targets(('average_discount_v6.py', 'cost_inputs_v6.py', 'pricing_proof_v6.py', 'runtime.py'))}


def curve_weekly_targets(source):
    current=targets(source)
    return {**{name:current[name] for name in ('fc27-coins.html','fc-pricing-v3.js')},
            **module_targets(('api.py','ledger.py','runtime.py','scheduler.py','weekly_ladder.py'))}


def curve_arab_quote_targets(source):
    return module_targets(('market_registry.py',))


ORDER_COST_CHANNEL_REPOSITORY = 'releases/fs-dashboard/dashboard-refresh-20261025/source/channel_source.py'
HOURLY_COST_CHANNEL_BASE = '807cfd5369eb2a2ccf7f06e8e4238dffa9e6251d'
ORDER_COST_CHANNEL_OVERLAY = {
    'candidate': 'source/channel_source.py',
    'target': '/opt/fs-hermes-fc/channel_source.py',
    'beforeSha256': '94c5a99edced5c27cd235fd587a8bd7eac86e740597f62063b7449b00f58cb4b',
}
HOURLY_COST_CHANNEL_OVERLAY = dict(ORDER_COST_CHANNEL_OVERLAY,
    beforeSha256='d1263f5e74d5b9a845f1d98258025a9758865a362419dea7d969e76c9872981c')


def _hourly_cost_refresh_parts(source):
    start, end = b'\ndef enrich(', b'\ndef shared_view('
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError('hourly_cost_channel_boundary_changed')
    prefix, refresh = source.split(start)
    refresh, suffix = refresh.split(end)
    return prefix, start + refresh, end + suffix


def hourly_cost_channel_overlay(live, updated, *, repository_before=None):
    """Replace just the verified channel refresh function in the live source."""
    if hashlib.sha256(live).hexdigest() != HOURLY_COST_CHANNEL_OVERLAY['beforeSha256']:
        raise ValueError('hourly_cost_channel_baseline_changed')
    prefix, refresh, suffix = _hourly_cost_refresh_parts(live)
    repo_prefix, new_refresh, repo_suffix = _hourly_cost_refresh_parts(updated)
    if repository_before is not None:
        old_prefix, old_refresh, old_suffix = _hourly_cost_refresh_parts(repository_before)
        if old_refresh != refresh:
            raise ValueError('hourly_cost_refresh_function_drift')
        if (old_prefix, old_suffix) != (repo_prefix, repo_suffix):
            raise ValueError('hourly_cost_change_outside_refresh')
    if new_refresh == refresh:
        raise ValueError('hourly_cost_refresh_change_missing')
    return prefix + new_refresh + suffix


ORDER_COST_FC_BASELINES = {
    'source/collect_p2pah_cost.py': '7c60ad5d4dc517b7e6c6b9a93cf6e8fba2f5ef0f2df9fed96411b94335ae351e',
    'source/fc_pricing_v3/business_source.py': 'f1b86fc89b947425b84eba2d7cdcd4ac9f316cf83b2f4e1b6da8a2082773eef5',
    'source/hermes-copy/fc_pricing_v3/business_source.py': 'f1b86fc89b947425b84eba2d7cdcd4ac9f316cf83b2f4e1b6da8a2082773eef5',
}
ORDER_COST_CHANNEL_INSERT = (b"        if data.get('include_cost_delivery_rows') is True:\n"
                             b"            data['cost_delivery_rows'] = deliveries\n")


def order_cost_channel_overlay(source):
    if hashlib.sha256(source).hexdigest() != ORDER_COST_CHANNEL_OVERLAY['beforeSha256']:
        raise ValueError('order_cost_channel_baseline_drift')
    anchor = b"        data['sources']['cost'] = cost_info\n"
    if source.count(anchor) != 1 or ORDER_COST_CHANNEL_INSERT in source:
        raise ValueError('order_cost_channel_anchor_drift')
    return source.replace(anchor, anchor + ORDER_COST_CHANNEL_INSERT, 1)


CURVE_RECOVERY_TARGETS = {
    'order-cost': {
        'collect_p2pah_cost.py': '/opt/fc27-cloud-browser/collect_p2pah_cost.py',
        'channel_source.py': ORDER_COST_CHANNEL_OVERLAY['target'],
        **module_targets(('business_source.py',)),
    },
    'live-order-cost': {
        'collect_p2pah_cost.py': '/opt/fc27-cloud-browser/collect_p2pah_cost.py',
        'snapshot_layer.py': '/opt/fc27-cloud-browser/snapshot_layer.py',
    },
    'shared-order': {
        'collect_p2pah_cost.py': '/opt/fc27-cloud-browser/collect_p2pah_cost.py',
        'snapshot_layer.py': '/opt/fc27-cloud-browser/snapshot_layer.py',
        **module_targets(('business_source.py', 'runtime.py', 'average_discount_v6.py')),
    },
    'round-latency': {
        'fc27_cloud_worker.py': '/opt/fc27-cloud-browser/fc27_cloud_worker.py',
        'snapshot_layer.py': '/opt/fc27-cloud-browser/snapshot_layer.py',
        'collect_p2pah_cost.py': '/opt/fc27-cloud-browser/collect_p2pah_cost.py',
        **module_targets(('business_source.py', 'runtime.py', 'planning_baskets_v6.py')),
    },
    'recent-orders': module_targets(('business_source.py', 'planning_baskets_v6.py', 'runtime.py')),
    'catalogue-inputs': module_targets(('runtime.py',)),
    'hourly-order-cost': {'channel_source.py': HOURLY_COST_CHANNEL_OVERLAY['target'],
                          **module_targets(('scheduler.py', 'business_source.py'))},
    'cycle-recovery': {
        'snapshot_layer.py': '/opt/fc27-cloud-browser/snapshot_layer.py',
        **module_targets(('scheduler.py',)),
    },
    'targeted-price-reads': {
        'coin_all_sync_job.py': '/opt/fc27-cloud-browser/coin_all_sync_job.py',
        **module_targets(('business_source.py', 'daily.py')),
    },
    'outcomes': module_targets(('business_source.py', 'daily.py')),
    'cost-incidents': module_targets(('cost_inputs_v6.py', 'ledger.py', 'runtime.py', 'scheduler.py')),
}
CURVE_RECOVERY_SCOPES = {name: 'fc-pricing-v6-recovery-' + name + '-20261119'
                         for name in CURVE_RECOVERY_TARGETS}


def curve_margin_band_targets(source):
    return {'fc-pricing-v3.js': targets(source)['fc-pricing-v3.js'],
            **module_targets(('api.py', 'average_discount_v6.py', 'curve_strategy_v6.py',
                              'ledger.py', 'runtime.py', 'weekly_ladder.py'))}


def curve_market_targets(source):
    return module_targets(('api.py', 'curve_strategy_v6.py', 'ledger.py', 'platforms.py', 'runtime.py'))


def curve_stability_targets(source):
    return {'collect_p2pah_cost.py': targets(source)['collect_p2pah_cost.py'],
            'collect_p2pah_cost.sh': '/opt/fc27-cloud-browser/collect_p2pah_cost.sh',
            'snapshot_layer.py': targets(source)['snapshot_layer.py'],
            'server_quote_job.py': targets(source)['server_quote_job.py'],
            **module_targets(('cost_inputs_v6.py', 'runtime.py'))}


def require_curve_scope_for_imports(name, payload):
    if not name.endswith('.py'):
        return
    # Include local imports inside functions. A stage may import successfully
    # at startup while still failing later on an enabled quote or writer path.
    modules = {filename.removesuffix('.py') for filename in CURVE_V6_MODULES} | {'weekly_ladder'}
    # These symbols live in existing files that have to move with V6 callers.
    curve_symbols = {
        'ledger': {'confirmed_curve_window'},
        'dispatch': {'CURVE_WRITE_PROTOCOL', 'write_protocol', 'validate_curve_send'},
        'coin_all_sync_job': {'curve_admin_manager', 'curve_catalog_plan', 'curve_result',
                             'curve_writer_capabilities', 'reconcile_curve_catalog'},
    }
    watched = modules | set().union(*curve_symbols.values())
    if not any(symbol.encode('ascii') in payload for symbol in watched):
        return
    for node in ast.walk(ast.parse(payload, filename=name)):
        if isinstance(node, ast.ImportFrom):
            aliases = {alias.name for alias in node.names}
            module = node.module or ''
            if module == 'fc_pricing_v3' or (node.level == 1 and not module):
                missing = modules.intersection(aliases)
            elif module == 'coin_all_sync_job' or module.startswith('fc_pricing_v3.') or (
                    node.level == 1 and '/fc_pricing_v3/' in '/' + name):
                module = module.removeprefix('fc_pricing_v3.')
                missing = {module} if module in modules else curve_symbols.get(module, set()).intersection(aliases)
            else:
                missing = set()
        elif isinstance(node, ast.Import):
            missing = modules.intersection(alias.name.removeprefix('fc_pricing_v3.') for alias in node.names
                                           if alias.name.startswith('fc_pricing_v3.'))
        else:
            continue
        if missing:
            raise ValueError('curve_v6_scope_required:' + name + ':' + ','.join(sorted(missing)))


CURVE_REVIEW_SCOPE = 'fc-pricing-v6-closeout-review-20261117'
CURVE_REVIEW_TARGET_COUNT = 4


def curve_review_targets(source):
    return module_targets(('monitoring.py', 'weekly_ladder.py'))
