"""Email lookup and UI polish using the original publisher, CAS and admission fence."""
import subprocess
import release_tools as tools

adapter = tools.adapter
adapter.SCOPE = 'fs-user-analytics-search-help-20261023'
adapter.TARGETS = {
    **{'runtime/'+name: '/opt/fs-hermes-fc/'+name for name in ('user_store.py','user_query.py','user_http.py')},
    'integration/range_api.py': '/opt/fs-exact-range-20261001/range_api.py',
    'nav/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
    **{'ui/'+name: '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/'+name for name in ('index.html','users.js','users.css')},
}
adapter.NEW = frozenset()
adapter.AUTHORIZED_TIMERS = frozenset()


def load_base():
    base = tools.load_base()
    base.TARGETS_CHANGED_NAV = {'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
    restart = base.restart_for

    def scoped_restart(manifest, admission_fence=None):
        if manifest.get('scope') != adapter.SCOPE:
            return restart(manifest, admission_fence)
        if admission_fence is None:
            raise ValueError('existing_admission_fence_required')
        admission_fence.stop_then_unlock_database()
        restart(dict(manifest, scope=base.DEEP_SCOPE), admission_fence)
        subprocess.run(['nginx','-t'],check=True,timeout=20)
        subprocess.run(['systemctl','reload','nginx'],check=True,timeout=20)

    base.restart_for = scoped_restart
    return base


if __name__ == '__main__':
    load_base().main()
