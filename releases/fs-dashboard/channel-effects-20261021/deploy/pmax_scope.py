"""Scoped PMax data/UI update over the existing admission, CAS and backup publisher."""
import release

SCOPE = 'fs-pmax-fc-scope-20261022'
ASSETS = '/var/lib/fs-navigation-formal-static/pmax-fc-scope-20261022-v1/'
TARGETS = {
    'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
    'ui/index.html': ASSETS+'index.html',
    'ui/channel.js': ASSETS+'channel.js',
    'ui/channel.css': ASSETS+'channel.css',
    'ui/google.js': ASSETS+'google.js',
    'runtime/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py',
    'runtime/channel_source.py': '/opt/fs-hermes-fc/channel_source.py',
    'runtime/traffic_contract.py': '/opt/fs-hermes-fc/traffic_contract.py',
    'details/traffic_contract.py': '/opt/mmoexp-marketing/details/traffic_contract.py',
    'details/game_dimensions.py': '/opt/mmoexp-marketing/details/game_dimensions.py',
    'runtime/es_order_structure.py': '/opt/fs-hermes-fc/es_order_structure.py',
    'runtime/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md',
    'runtime/learning-loop.md': '/opt/fs-hermes-fc/learning-loop.md',
}


def candidate(before):
    channel=b'alias /var/lib/fs-navigation-formal-static/channel-effects-a8c5835cbdf9/'
    traffic=b'alias /var/lib/fs-navigation-formal-static/workspace-native-20261019-traffic-v3/google.js;'
    if before.count(channel)!=3 or before.count(traffic)!=1:
        raise ValueError('exact_current_pmax_ui_aliases_required')
    return before.replace(channel,('alias '+ASSETS).encode()).replace(traffic,('alias '+ASSETS+'google.js;').encode())


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset(k for k in TARGETS if k.startswith('ui/'))
    return release.load_base()


if __name__=='__main__':load_base().main()
