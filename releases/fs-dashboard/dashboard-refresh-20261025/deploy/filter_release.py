"""Website/game filters over the original exact CAS publisher."""

def load_base():
 import actual_release
 actual_release.SCOPE='business-filter-layout-20261025'
 actual_release.TARGETS={'source/business.js': '/var/lib/fs-navigation-formal-static/business-filter-layout-20261025-d1d0dca75114/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/business-filter-layout-20261025-d1d0dca75114/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/business-filter-layout-20261025-d1d0dca75114/legacy-business.js', 'source/shell.js': '/var/lib/fs-navigation-formal-static/business-filter-layout-20261025-d1d0dca75114/shell.js', 'source/live_summary.py': '/opt/fs-exact-range-20261001/live_summary.py', 'source/daily_archive.py': '/opt/fs-exact-range-20261001/daily_archive.py', 'source/summary_bridge.py': '/opt/fs-exact-range-20261001/summary_bridge.py', 'source/site_summary.py': '/opt/fs-exact-range-20261001/site_summary.py', 'source/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md', 'source/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
 actual_release.NEW=frozenset({'source/legacy-business.js', 'source/site_summary.py', 'source/shell.js', 'source/home-business.js', 'source/business.js'})
 return actual_release.load_base()

if __name__=='__main__':load_base().main()
