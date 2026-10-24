"""RS website membership and filter layout through the existing exact publisher."""
def load_base():
 import actual_release
 actual_release.SCOPE='business-dashboard-backlog-20261025'
 actual_release.TARGETS={'source/business.js': '/var/lib/fs-navigation-formal-static/dashboard-rs-ui-20261025-4907be5bf596/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/dashboard-rs-ui-20261025-4907be5bf596/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/dashboard-rs-ui-20261025-4907be5bf596/legacy-business.js', 'source/shell.js': '/var/lib/fs-navigation-formal-static/dashboard-rs-ui-20261025-4907be5bf596/shell.js', 'source/rs_backlog.py': '/opt/fs-exact-range-20261001/rs_backlog.py', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
 actual_release.NEW=frozenset(['source/business.js', 'source/home-business.js', 'source/legacy-business.js', 'source/shell.js'])
 return actual_release.load_base()
if __name__=='__main__':load_base().main()
