"""Bind the exact weekly payload to the existing host/P4 publisher, without replacing its lifecycle."""

SCOPE = 'user-weekly-20261030'
TARGETS = {
    **{'source/' + name: '/opt/fs-hermes-fc/' + name for name in (
        'user_runtime.py', 'user_contract.py', 'user_jobs.py', 'user_query.py',
        'user_http.py', 'user_customer_types.py', 'user_tools.py', 'user_weekly.py')},
    **{'ui/' + name: '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/' + name
       for name in ('index.html', 'users.js')},
}
NEW = frozenset({'source/user_weekly.py'})


def load_base():
    # These modules come from the sealed, already used host release stage.
    # host.load_base retains exact manifest validation; P4 retains admission,
    # source-idle checks, original maintenance, CAS, journal and rollback.
    import host_release
    import p4_release
    host_release.SCOPE, host_release.TARGETS, host_release.NEW = SCOPE, dict(TARGETS), NEW
    return p4_release.load_base()


if __name__ == '__main__':
    load_base().main()
