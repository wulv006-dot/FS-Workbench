"""Profit label/description follow-up through the existing static-only publisher."""
SCOPE='business-shipping-profit-labels-20261024'
TARGETS={'source/business.js': '/var/lib/fs-navigation-formal-static/shipping-profit-labels-20261024-b6acfb909888/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/shipping-profit-labels-20261024-b6acfb909888/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/shipping-profit-labels-20261024-b6acfb909888/legacy-business.js', 'source/shell.js': '/var/lib/fs-navigation-formal-static/shipping-profit-labels-20261024-b6acfb909888/shell.js', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/business.js', 'source/home-business.js', 'source/legacy-business.js', 'source/shell.js'])
def load_base():
    import ui_fix
    ui_fix.SCOPE,ui_fix.TARGETS,ui_fix.NEW=SCOPE,TARGETS,NEW
    return ui_fix.load_base()
if __name__=='__main__':load_base().main()
