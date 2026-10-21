"""Display-only release using the original CAS, admission fence and rollback."""

import subprocess

import release

SCOPE='fs-channel-revenue-labels-20261022'

TARGETS={'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', 'ui/index.html': '/var/lib/fs-navigation-formal-static/channel-effects-a8c5835cbdf9/index.html', 'ui/channel.js': '/var/lib/fs-navigation-formal-static/channel-effects-a8c5835cbdf9/channel.js', 'ui/channel.css': '/var/lib/fs-navigation-formal-static/channel-effects-a8c5835cbdf9/channel.css'}

OLD='channel-effects-74e0239b32e7'

NEW='channel-effects-a8c5835cbdf9'



def candidate(before):

    needle=('alias /var/lib/fs-navigation-formal-static/'+OLD+'/').encode()

    if before.count(needle)!=3:raise ValueError('exact_channel_ui_bindings_required')

    return before.replace(needle,('alias /var/lib/fs-navigation-formal-static/'+NEW+'/').encode())



def load_base():

    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset(k for k in TARGETS if k.startswith('ui/'))

    base=release.load_base()

    restart=base.restart_for

    def nginx_only(manifest,admission_fence=None):

        if manifest.get('scope')!=SCOPE:return restart(manifest,admission_fence)

        if admission_fence is None:raise ValueError('channel admission fence required')

        subprocess.run(['nginx','-t'],check=True,timeout=20)

        subprocess.run(['systemctl','reload','nginx'],check=True,timeout=20)

    base.restart_for=nginx_only

    return base

if __name__=='__main__':load_base().main()

