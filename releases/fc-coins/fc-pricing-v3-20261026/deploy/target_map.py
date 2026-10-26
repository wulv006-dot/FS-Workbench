"""Exact V3 code targets; the knowledge catalog has a separate immutable release."""
from pathlib import Path


def targets(source):
    source = Path(source)
    rows = {}
    for name in ('automation_policy.py', 'automation_tick.py', 'clear_cache_after_write.py',
                 'clear_cache_after_write.sh', 'coin_all_sync_job.py', 'execute_price.sh',
                 'fc27_cloud_api.py', 'fc27_cloud_worker.py', 'fc27_quote_engine.py',
                 'hermes_pricing_bridge.py', 'price_writer.py', 'pricing_state.py',
                 'pricing_v2.py', 'reconcile_original.py', 'reconcile_price.sh',
                 'repricing_logic.js', 'restore_price.sh', 'server_quote_job.py'):
        rows[name] = '/opt/fc27-cloud-browser/' + name
    for name in ('pricing_operations.py', 'pricing_simulation.py', 'strategy_tools.py'):
        rows[name] = '/opt/fs-hermes-fc/' + name
    for name in ('probe_worker.py', 'read_only_status.py'):
        rows[name] = '/opt/fc-ops-readonly-monitor/' + name
    for name in ('fc27-coins.html', 'fc27-quote-cloud.js', 'fc-pricing-v3.js'):
        rows[name] = '/var/www/dashboard/' + name
    for name in ('fc-pricing-v3.service', 'fc-pricing-v3-shadow.service'):
        rows['systemd/' + name] = '/etc/systemd/system/' + name
    for file in (source/'fc_pricing_v3').rglob('*.py'):
        name = file.relative_to(source).as_posix()
        rows[name] = '/opt/fc27-cloud-browser/' + name
        rows['hermes-copy/' + name] = '/opt/fs-hermes-fc/' + name
    return rows
