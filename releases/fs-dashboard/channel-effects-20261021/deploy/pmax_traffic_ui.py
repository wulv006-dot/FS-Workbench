"""Static-only correction of the active PMax Ads source tab, using the original publisher."""
import subprocess
import release
SCOPE='fs-pmax-traffic-ui-20261022'
TARGETS={'generated/navigation.conf':'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
         'ui/google.js':'/var/lib/fs-navigation-formal-static/pmax-fc-traffic-20261022-v2/google.js'}
def candidate(before):
    old=b'alias /var/lib/fs-navigation-formal-static/pmax-fc-scope-20261022-v1/google.js;'
    new=b'alias /var/lib/fs-navigation-formal-static/pmax-fc-traffic-20261022-v2/google.js;'
    if before.count(old)!=1:raise ValueError('exact_pmax_traffic_alias_required')
    return before.replace(old,new)
def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset({'ui/google.js'})
    base=release.load_base();restart=base.restart_for
    def nginx_only(manifest,admission_fence=None):
        if manifest.get('scope')!=SCOPE:return restart(manifest,admission_fence)
        if admission_fence is None:raise ValueError('existing_admission_fence_required')
        subprocess.run(['nginx','-t'],check=True,timeout=20)
        subprocess.run(['systemctl','reload','nginx'],check=True,timeout=20)
    base.restart_for=nginx_only
    return base
if __name__=='__main__':load_base().main()
