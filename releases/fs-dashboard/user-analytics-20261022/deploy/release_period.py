"""Selected-period customer correction through the original scoped publisher."""
import release_tools as tools
adapter = tools.adapter
adapter.SCOPE = 'fs-user-analytics-period-cohort-20261023'
adapter.TARGETS = {
    **{'runtime/'+name: '/opt/fs-hermes-fc/'+name for name in (
        'user_contract.py','user_customer_types.py','user_store.py','user_query.py',
        'user_lifecycle.py','user_runtime.py','user_jobs.py','user_tools.py')},
    'ui/index.html': '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/index.html',
    'ui/users.js': '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js',
}
adapter.NEW = frozenset(['runtime/user_customer_types.py'])
adapter.AUTHORIZED_TIMERS = frozenset()
load_base = tools.load_base

if __name__ == '__main__':
    load_base().main()
