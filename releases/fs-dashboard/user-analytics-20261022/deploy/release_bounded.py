"""User-requested July history bound through the same scoped publisher."""
import release_tools as tools
adapter=tools.adapter
adapter.SCOPE='fs-user-analytics-july-bound-20261023'
adapter.TARGETS={
    **{'runtime/'+name:'/opt/fs-hermes-fc/'+name for name in ('user_config.json','user_jobs.py','user_query.py')},
    'runtime/backfill_history.py':'/opt/fs-hermes-fc/backfill_history.py',
    'ui/users.js':'/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js',
}
adapter.NEW=frozenset()
adapter.AUTHORIZED_TIMERS=frozenset()
load_base=tools.load_base

if __name__=='__main__':load_base().main()
