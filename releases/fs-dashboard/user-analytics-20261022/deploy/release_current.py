"""Customer-basis correction through the same publisher and scoped tool restart."""
import release_tools as tools
adapter = tools.adapter
adapter.SCOPE = 'fs-user-analytics-current-basis-20261023'
adapter.TARGETS = {
    **{'runtime/'+name: '/opt/fs-hermes-fc/'+name for name in (
        'user_config.json','user_contract.py','user_lifecycle.py','user_query.py',
        'user_tools.py','user_jobs.py','user_store.py','user_source.py')},
    'runtime/backfill_history.py': '/opt/fs-hermes-fc/backfill_history.py',
    'ui/index.html': '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/index.html',
    'ui/users.js': '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js',
}
adapter.NEW = frozenset(['runtime/backfill_history.py'])
adapter.AUTHORIZED_TIMERS = frozenset()
load_base = tools.load_base

if __name__ == '__main__':
    load_base().main()
