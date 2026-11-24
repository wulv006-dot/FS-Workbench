"""Thin dispatch for the existing authenticated host. Does not start a new web server."""
from user_weekly import WeeklyUnavailable
from user_store import StoreUnavailable
from user_member_index import IndexUnavailable
from user_query import SummaryBusy
from user_query_v4 import SnapshotVersionRetired


def search(service, body, user):
    if not user:
        return 401, {'error': 'login_required'}
    if service is None:
        return 503, {'error': 'users_not_enabled'}
    try:
        if not isinstance(body, dict):
            raise ValueError('v4_email_fields')
        args = dict(body)
        source = args.pop('source', 'page')
        if source not in ('page', 'connector'):
            raise ValueError('v4_search_source')
        return 200, service.v4.search(args, user, admin=source == 'connector')
    except PermissionError:
        return 403, {'error': 'scope_or_admin_required'}
    except IndexUnavailable:
        return 503, {'error': 'snapshot_member_index_unavailable'}
    except StoreUnavailable:
        return 503, {'error': 'users_store_unavailable', 'recovery_required': True}
    except WeeklyUnavailable:
        return 503, {'error': 'weekly_initial_publication_pending'}
    except LookupError:
        return 404, {'error': 'snapshot_not_found'}
    except SnapshotVersionRetired:
        return 422, {'error': 'snapshot_version_retired'}
    except (ValueError, TypeError):
        return 422, {'error': 'invalid_user_query'}


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
        for key in ('return_after', 'return_within', 'limit'):
            if key in args:
                if not args[key].isdigit():
                    raise ValueError('query_integer')
                args[key] = int(args[key])
        if path == '/users/private':
            admin = action.startswith('connector_')
            action = action[len('connector_'):] if admin else action
            if action == 'detail':
                return 200, service.v4.detail(args, user, admin=admin)
            if action == 'members':
                return 200, service.v4.members(args, user, admin=admin)
            if action == 'export' and not admin:
                return 200, service.v4.export(args, user)
            raise ValueError('private_action')
        if action in ('catalog', 'connector_catalog') and not args:
            return 200, service.v4.catalog(user, admin=action == 'connector_catalog')
        if action in ('tool', 'connector_section'):
            from user_tools import read_v4
            return read_v4(service, user, args, wait_seconds=3 if action == 'connector_section' else 10,
                           require_poll_section=action == 'connector_section')
        if action in ('summary', 'connector_summary'):
            return service.v4.get(args, user, wait_seconds=3 if action == 'connector_summary' else 10)
        raise ValueError('public_action')
    except SummaryBusy:
        return 429, {'error': 'users_summary_busy', 'retryable': True, 'retryAfter': 5}
    except PermissionError:
        return 403, {'error': 'scope_or_admin_required'}
    except IndexUnavailable:
        return 503, {'error': 'snapshot_member_index_unavailable'}
    except StoreUnavailable:
        return 503, {'error': 'users_store_unavailable', 'recovery_required': True}
    except WeeklyUnavailable:
        return 503, {'error': 'weekly_initial_publication_pending'}
    except LookupError:
        return 404, {'error': 'snapshot_not_found'}
    except SnapshotVersionRetired:
        return 422, {'error': 'snapshot_version_retired'}
    except (ValueError, TypeError):
        return 422, {'error': 'invalid_user_query'}

