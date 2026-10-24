"""Exact two-target static status update; keep CAS/fences and original service processes."""
SCOPE='rs-status-copy-20261024'
TARGETS={'source/shell.js': '/var/lib/fs-navigation-formal-static/rs-status-20261024-96a1c925325c/shell.js', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/shell.js'])
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
