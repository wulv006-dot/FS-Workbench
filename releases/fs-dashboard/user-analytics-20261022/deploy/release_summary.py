"""Compact history metadata and coverage notice through the same scoped publisher."""
import release_tools as tools
adapter=tools.adapter
adapter.SCOPE='fs-user-analytics-history-summary-20261023'
adapter.TARGETS={
    'runtime/user_tools.py':'/opt/fs-hermes-fc/user_tools.py',
    'runtime/user_runtime.py':'/opt/fs-hermes-fc/user_runtime.py',
    'runtime/user_store.py':'/opt/fs-hermes-fc/user_store.py',
    'runtime/user_query.py':'/opt/fs-hermes-fc/user_query.py',
    'ui/users.js':'/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js',
}
adapter.NEW=frozenset()
adapter.AUTHORIZED_TIMERS=frozenset()
load_base=tools.load_base

if __name__=='__main__':load_base().main()
