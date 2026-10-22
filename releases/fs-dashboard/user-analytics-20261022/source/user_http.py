"""Thin dispatch for the existing authenticated host. Does not start a new web server."""


def get(service, path, params, user):
    if not user:
        return 401, {'error': 'login_required'}
    if path not in ('/users', '/users/private'):
        return 404, {'error': 'not_found'}
    if service is None:
        return 503, {'error': 'users_not_enabled'}
    try:
        if not isinstance(params, dict) or len(params) > 14 or any(not isinstance(v, list) or len(v) != 1 for v in params.values()):
            raise ValueError('query_shape')
        args = {k: v[0] for k, v in params.items()}
        if any(not isinstance(v, str) or len(v) > 160 for v in args.values()):
            raise ValueError('query_value')
        action = args.pop('action', 'summary' if path == '/users' else 'members')
        for key in ('H', 'limit'):
            if key in args:
                if not args[key].isdigit():
                    raise ValueError('query_integer')
                args[key] = int(args[key])
        if path == '/users/private':
            if action not in ('members', 'export', 'detail'):
                raise ValueError('private_action')
            return 200, getattr(service, action)(args, user)
        if action == 'catalog' and not args:
            return 200, service.catalog(user)
        if action != 'summary':
            raise ValueError('public_action')
        return 200, service.query(args, user)
    except PermissionError:
        return 403, {'error': 'scope_or_admin_required'}
    except LookupError:
        return 404, {'error': 'snapshot_not_found'}
    except (ValueError, TypeError):
        return 422, {'error': 'invalid_user_query'}

