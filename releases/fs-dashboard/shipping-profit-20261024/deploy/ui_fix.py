"""Static-only FC visibility follow-up; original CAS, fences and rollback stay active."""
SCOPE='business-shipping-profit-ui-20261024'
TARGETS={'source/business.js': '/var/lib/fs-navigation-formal-static/shipping-profit-ui-20261024-33653b6cce69/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/shipping-profit-ui-20261024-33653b6cce69/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/shipping-profit-ui-20261024-33653b6cce69/legacy-business.js', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/business.js', 'source/home-business.js', 'source/legacy-business.js'])
def load_base():
    import release,subprocess
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    base=release.load_base();base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    original=base.restart_for
    def static_reload(manifest,admission_fence=None):
        if manifest.get('scope')!=SCOPE:return original(manifest,admission_fence)
        if admission_fence is None:raise ValueError('static admission fence required')
        subprocess.run(['nginx','-t'],check=True,timeout=20)
        subprocess.run(['systemctl','reload','nginx'],check=True,timeout=20)
    base.restart_for=static_reload
    return base
if __name__=='__main__':load_base().main()
