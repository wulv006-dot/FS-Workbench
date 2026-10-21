"""Channel read/cache release with original CAS, backup and admission fence."""
import subprocess
import release
SCOPE='fs-channel-customer-20261021'
TARGETS={'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', 'ui/index.html': '/var/lib/fs-navigation-formal-static/channel-effects-fafdf954fbb3/index.html', 'ui/channel.js': '/var/lib/fs-navigation-formal-static/channel-effects-fafdf954fbb3/channel.js', 'ui/channel.css': '/var/lib/fs-navigation-formal-static/channel-effects-fafdf954fbb3/channel.css', 'runtime/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py', 'runtime/channel_source.py': '/opt/fs-hermes-fc/channel_source.py'}
OLD='channel-effects-b8831c5eacc0'
NEW='channel-effects-fafdf954fbb3'
def candidate(before):
    needle=('alias /var/lib/fs-navigation-formal-static/'+OLD+'/').encode()
    if before.count(needle)!=3:raise ValueError('exact_channel_ui_bindings_required')
    return before.replace(needle,('alias /var/lib/fs-navigation-formal-static/'+NEW+'/').encode())
def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset(k for k in TARGETS if k.startswith('ui/'))
    base=release.load_base()
    return base
if __name__=='__main__':load_base().main()
