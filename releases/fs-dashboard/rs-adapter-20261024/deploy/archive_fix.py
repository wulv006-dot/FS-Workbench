"""Exact five-target follow-up using the original CAS publisher."""
SCOPE='rs-archive-fix-20261024'
TARGETS={'source/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'source/business.js': '/var/lib/fs-navigation-formal-static/rs-archive-fix-20261024-62812003d735/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/rs-archive-fix-20261024-62812003d735/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/rs-archive-fix-20261024-62812003d735/legacy-business.js', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/business.js', 'source/home-business.js', 'source/legacy-business.js'])
def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    base=release.load_base()
    base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    return base
if __name__=='__main__':load_base().main()
