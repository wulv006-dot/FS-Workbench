"""User-accepted January extension using the existing reader/static publisher."""
import release_search as search

search.adapter.TARGETS = {
    **{'runtime/'+name: '/opt/fs-hermes-fc/'+name for name in ('user_config.json','user_query.py','backfill_history.py')},
    **{'ui/'+name: '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/'+name for name in ('index.html','users.js')},
}
load_base = search.load_base

if __name__ == '__main__':
    load_base().main()
