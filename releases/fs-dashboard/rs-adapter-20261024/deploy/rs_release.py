"""RS exact-target adapter; the original publisher keeps its guards and rollback."""
SCOPE='rs-business-adapter-20261024'
TARGETS={'source/rs_admin.py': '/opt/fs-exact-range-20261001/rs_admin.py', 'source/live_summary.py': '/opt/fs-exact-range-20261001/live_summary.py', 'source/summary_bridge.py': '/opt/fs-exact-range-20261001/summary_bridge.py', 'source/daily_archive.py': '/opt/fs-exact-range-20261001/daily_archive.py', 'source/range_primary_reader.py': '/opt/fs-exact-range-20261001/range_primary_reader.py', 'source/profit_queries.py': '/opt/fs-exact-range-20261001/profit_queries.py', 'source/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'source/profit_daily.py': '/opt/fs-transaction-snapshot/profit_daily.py', 'source/business.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/legacy-business.js', 'source/shell.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/shell.js', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/business.js', 'source/home-business.js', 'source/legacy-business.js', 'source/rs_admin.py', 'source/shell.js'])
ALIASES={'/var/lib/fs-navigation-formal-static/business-procurement-20261022-fb8814af4a60/business.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/business.js', '/var/lib/fs-navigation-formal-static/business-procurement-20261022-fb8814af4a60/home-business.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/home-business.js', '/var/lib/fs-navigation-formal-static/business-procurement-20261022-fb8814af4a60/legacy-business.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/legacy-business.js', '/var/lib/fs-navigation-formal-static/workspace-native-20261006-8b7908ecad30/shell.js': '/var/lib/fs-navigation-formal-static/rs-business-20261024-6fec65d27be0/shell.js'}
def candidate(before):
    result=before
    for old,new in ALIASES.items():
        needle=('alias '+old+';').encode()
        if before.count(needle)!=1:raise ValueError('exact RS aliases required')
        result=result.replace(needle,('alias '+new+';').encode(),1)
    return result
def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    base=release.load_base()
    # Changed dependencies are protected by their exact target CAS, not an unchanged SHA.
    base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    return base
if __name__=='__main__':load_base().main()
