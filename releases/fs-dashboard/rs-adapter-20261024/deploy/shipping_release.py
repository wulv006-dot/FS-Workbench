"""Exact RS shipping-source targets; unchanged original CAS/backup/rollback publisher."""
SCOPE='rs-shipping-profit-20261024'
TARGETS={'source/rs_shipping.py': '/opt/fs-exact-range-20261001/rs_shipping.py', 'source/live_summary.py': '/opt/fs-exact-range-20261001/live_summary.py', 'source/summary_bridge.py': '/opt/fs-exact-range-20261001/summary_bridge.py', 'source/daily_archive.py': '/opt/fs-exact-range-20261001/daily_archive.py', 'source/profit_daily.py': '/opt/fs-transaction-snapshot/profit_daily.py', 'source/profit_queries.py': '/opt/fs-exact-range-20261001/profit_queries.py', 'source/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'source/business.js': '/var/lib/fs-navigation-formal-static/rs-shipping-20261024-3318ca1016cf/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/rs-shipping-20261024-3318ca1016cf/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/rs-shipping-20261024-3318ca1016cf/legacy-business.js', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/rs_shipping.py', 'source/business.js', 'source/home-business.js', 'source/legacy-business.js'])
def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    base=release.load_base()
    base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    from shipping_readiness import extend
    extend(base,SCOPE)
    return base
if __name__=='__main__':load_base().main()
