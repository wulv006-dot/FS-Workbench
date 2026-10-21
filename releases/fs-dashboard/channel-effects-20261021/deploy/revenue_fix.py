"""Channel read/cache release with original CAS, backup and admission fence."""
import release
SCOPE='fs-channel-admin-revenue-20261022'
TARGETS={'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', 'ui/index.html': '/var/lib/fs-navigation-formal-static/channel-effects-74e0239b32e7/index.html', 'ui/channel.js': '/var/lib/fs-navigation-formal-static/channel-effects-74e0239b32e7/channel.js', 'ui/channel.css': '/var/lib/fs-navigation-formal-static/channel-effects-74e0239b32e7/channel.css', 'runtime/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py', 'runtime/channel_source.py': '/opt/fs-hermes-fc/channel_source.py', 'runtime/channel_cache.py': '/opt/fs-hermes-fc/channel_cache.py', 'runtime/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md'}
OLD='channel-effects-64ded3f49f1a'
NEW='channel-effects-74e0239b32e7'
SOURCES={k:('releases/fs-dashboard/fc-coins-workflow-20261022/source/business-baseline.md' if k=='runtime/business-baseline.md' else 'releases/fs-dashboard/channel-effects-20261021/'+(k if k.startswith('ui/') else 'source/'+k.split('/')[-1])) for k in TARGETS if not k.startswith('generated/')}

def candidate(before):
    needle=('alias /var/lib/fs-navigation-formal-static/'+OLD+'/').encode()
    if before.count(needle)!=3:raise ValueError('exact_channel_ui_bindings_required')
    return before.replace(needle,('alias /var/lib/fs-navigation-formal-static/'+NEW+'/').encode())
def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset(k for k in TARGETS if k.startswith('ui/'))
    base=release.load_base()
    return base
if __name__=='__main__':load_base().main()
