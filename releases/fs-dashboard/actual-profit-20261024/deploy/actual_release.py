"""Exact actual-profit adapter; reuse original CAS, fence, backup and rollback."""
SCOPE='business-actual-profit-20261024'
TARGETS={'source/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md', 'source/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json', 'source/business.js': '/var/lib/fs-navigation-formal-static/actual-profit-20261024-8b55ccbf89c7/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/actual-profit-20261024-8b55ccbf89c7/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/actual-profit-20261024-8b55ccbf89c7/legacy-business.js', 'source/shell.js': '/var/lib/fs-navigation-formal-static/actual-profit-20261024-8b55ccbf89c7/shell.js', 'source/actual_profit.py': '/opt/fs-exact-range-20261001/actual_profit.py', 'source/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py', 'source/channel_cost_source.py': '/opt/fs-hermes-fc/channel_cost_source.py', 'source/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'source/live_summary.py': '/opt/fs-exact-range-20261001/live_summary.py', 'source/daily_archive.py': '/opt/fs-exact-range-20261001/daily_archive.py', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/business.js', 'source/home-business.js', 'source/legacy-business.js', 'source/shell.js', 'source/actual_profit.py'])
def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    base=release.load_base();base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    from shipping_readiness import extend
    extend(base,SCOPE)
    return base
if __name__=='__main__':load_base().main()
