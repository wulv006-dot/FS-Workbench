"""FC payload target adapter over the existing CAS/fence/backup publisher."""
import os
import re

SCOPE = 'fc-dashboard-20261106'


def load_base(version=None):
    version = version or os.environ.get('FS_FC_DASHBOARD_VERSION', '')
    if not re.fullmatch(r'fc-dashboard-20261106-[0-9a-f]{12}', version):
        raise ValueError('explicit_fc_dashboard_asset_version_required')
    import actual_release
    assets = ('business.js', 'home-business.js', 'legacy-business.js', 'business.css')
    modules = ('fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py', 'fc_dashboard.py')
    actual_release.SCOPE = SCOPE
    actual_release.TARGETS = {
        **{'source/' + name: '/var/lib/fs-navigation-formal-static/' + version + '/' + name for name in assets},
        **{'source/' + name: '/opt/fs-exact-range-20261001/' + name for name in modules},
        'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
    }
    actual_release.NEW = frozenset(['source/' + name for name in assets] + ['source/fc_dashboard.py'])
    return actual_release.load_base()


if __name__ == '__main__':
    load_base().main()
