"""Dedicated export source; generic live page/worker policy remains unchanged."""
import datetime
import hashlib
import json
import sys
from pathlib import Path
from admin_live_page import AdminLivePage, LivePageError, utc_now, validate_period
from admin_site_authorizer import digest

FILTERS = {'progress': '=', 'status': '=', 'cid': '=', 'content': 'LIKE',
           'aid': '=', 'recommend_uid': '=', 'discount_code': '=',
           'promotion_id': '=', 'pid': '=', 'admin_id': '=', 'country': 'LIKE'}
NUMERIC = set(FILTERS) - {'content', 'discount_code', 'country'}
METADATA = {
    'progress': ('/admin/order.Order/getOrderProgress', ()),
    'status': ('/admin/order.Order/getOrderStatus', ('id',)),
    'sites': ('/admin/site.Site/siteList', ()),
    'types': ('/admin/order.Order/getProType', ()),
    'games': ('/admin/site.Game/gameList', ()),
    'servers': ('/admin/goods.GameServer/getServerByGid', ('gid',)),
    'admins': ('/admin/auth.Admin/getGroupAdminList', ('gid',)),
    'countries': ('/admin/order.Order/getCountryList', ())}


def validate_filters(value):
    if not isinstance(value, dict) or set(value) - set(FILTERS):
        raise ValueError('unsupported_export_filters')
    for key, item in value.items():
        if not isinstance(item, str) or not 1 <= len(item) <= 320 or any(ord(c) < 32 or ord(c) == 127 for c in item):
            raise ValueError('invalid_export_request')
        if key in NUMERIC and (not item.isascii() or not item.isdigit() or len(item) > 20):
            raise ValueError('invalid_export_request')
    return dict(value)


def source_params(request, page, observed_at=utc_now):
    start, end = validate_period(request, observed_at)
    terms = [('site_id', '=', request['site_id']), ('gid', '=', request['game_id']),
             ('paytime', 'RANGE', start.isoformat() + ' 00:00:00,' + (end - datetime.timedelta(days=1)).isoformat() + ' 23:59:59')]
    terms += [(key, FILTERS[key], value) for key, value in sorted(validate_filters(request.get('filters', {})).items())]
    params = dict(page=page, limit=20, order='id,desc')
    for i, (field, operator, value) in enumerate(terms):
        for key, item in [('field', field), ('operator', operator), ('val', value)]:
            params['search[%d][%s]' % (i, key)] = item
        if field == 'paytime':
            params['search[%d][render]' % i] = 'datetime'
    return params


def build_handler(*, load_config, load_policy, rbac, authorize, fetch, run_source, observed_at=utc_now):
    def get(params, user):
        if not user:
            return 401, {'error': 'login_required'}
        if not callable(run_source):
            return 503, {'error': 'live_admission_unavailable'}
        try:
            request = {k: v[0] for k, v in params.items() if k != 'filters'}
            request['filters'] = validate_filters(params.get('filters', [{}])[0])
            def grant(query):
                config = load_config()
                policy = rbac.validate(load_policy())
                if not isinstance(policy, dict) or config.get('activation_status') != 'W0_verified' or config.get('live_admin_single_page') is not True:
                    raise PermissionError()
                if authorize(user, {'scope': 'site', 'scope_id': request['site_id']}, True) is not True:
                    raise PermissionError()
                return dict(scope_hash=digest([user, request['site_id'], request['game_id'], request['filters']]), permission_epoch=digest([policy, config]), policy_version='admin-email-export-v2')
            expected = grant(request)
            def bounded_fetch(path, old_params, timeout, cap):
                def operation():
                    if grant(request) != expected:
                        raise PermissionError()
                    validate_period(request, observed_at)
                    return fetch(path, source_params(request, old_params['page'], observed_at), timeout, cap)
                return run_source(operation, timeout)
            page_request = {k: v for k, v in request.items() if k != 'filters'}
            page_request['fields'] = ['order_id', 'paid_at', 'status', 'customer_email']
            result = AdminLivePage(fetch=bounded_fetch, authorize=grant, expected_grant=expected,
                page_size=20, max_bytes=1048576, timeout_seconds=10, observed_at=observed_at)(page_request)
            return 206, result
        except PermissionError:
            return 403, {'error': 'scope_denied'}
        except LivePageError as error:
            code = error.code
            return (422 if code == 'invalid_request' else 403 if code == 'permission_denied' else 429 if code == 'source_busy' else 409 if code == 'source_changed' else 503), {'error': code, 'complete': False}
        except (ValueError, TypeError, KeyError, IndexError):
            return 422, {'error': 'invalid_export_request'}
        except Exception:
            return 503, {'error': 'export_source_unavailable'}
    return get


def validate_metadata_args(name, args):
    if not isinstance(name, str) or name not in METADATA or not isinstance(args, dict) or set(args) != set(METADATA[name][1]):
        return False
    if name == 'admins':
        return args['gid'] == '8,11'
    return all(isinstance(v, str) and v.isascii() and v.isdigit() and 1 <= len(v) <= 20 for v in args.values())


def directory_read(name, args, *, deps, run_source, check, epoch):
    """Enumerate a bounded directory or fail closed; never return a partial list."""
    if not validate_metadata_args(name, args):
        raise ValueError('invalid_metadata_request')
    rows, seen, total, byte_count = [], set(), None, 0
    key = {'status': 'status', 'countries': 'country'}.get(name, 'id')
    for page in range(1, 101):
        def operation():
            if check() != epoch:
                raise PermissionError()
            return deps['fetch']('/admin/order.Order/index', dict(metadata=name, arguments=args, page=page), 10, 1048576)
        status, raw = run_source(operation, 10)
        if check() != epoch:
            raise PermissionError()
        if status != 200:
            raise RuntimeError('metadata_source_unavailable')
        if not isinstance(raw, bytes):
            raise RuntimeError('metadata_source_schema_changed')
        byte_count += len(raw)
        if len(raw) > 1048576 or byte_count > 4194304:
            raise RuntimeError('metadata_coverage_incomplete')
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise RuntimeError('metadata_source_schema_changed')
        if not isinstance(result, dict) or type(result.get('code')) is not int or result['code'] != 1:
            raise RuntimeError('metadata_source_schema_changed')
        data = result.get('data')
        if not isinstance(data, dict):
            raise RuntimeError('metadata_coverage_incomplete')
        batch = data.get('options', data.get('list'))
        reported = data.get('total')
        # Admin's fixed list directories omit total; its own remote select uses that full list.
        if 'total' not in data and 'list' in data and 'options' not in data and isinstance(batch, list):
            reported = len(batch)
        if not isinstance(batch, list) or type(reported) is not int or not 0 <= reported <= 10000:
            raise RuntimeError('metadata_coverage_incomplete')
        if total is not None and total != reported:
            raise RuntimeError('metadata_source_changed')
        total = reported
        for row in batch:
            if not isinstance(row, dict) or type(row.get(key)) not in (str, int) or str(row[key]) in seen:
                raise RuntimeError('metadata_source_schema_changed')
            seen.add(str(row[key]))
            rows.append(row)
        if len(rows) == total:
            return rows
        if not batch or len(rows) > total:
            raise RuntimeError('metadata_coverage_incomplete')
    raise RuntimeError('metadata_coverage_incomplete')


def options_get(request, user, *, run_source=None, deps=None):
    if not user:
        return 401, {'error': 'login_required'}
    if not callable(run_source):
        return 503, {'error': 'live_admission_unavailable'}
    try:
        if not isinstance(request, dict) or set(request) - {'progress', 'game_ids'}:
            raise ValueError()
        progress, games = request.get('progress', '1'), request.get('game_ids', [])
        if not isinstance(progress, str) or (progress and (not progress.isascii() or not progress.isdigit() or len(progress) > 20)):
            raise ValueError()
        if not isinstance(games, list) or len(games) > 100 or any(not isinstance(g, str) or not g.isascii() or not g.isdigit() or not 1 <= len(g) <= 20 for g in games) or len(games) != len(set(games)):
            raise ValueError()
        deps = dependencies() if deps is None else deps
        def check():
            config = deps['load_config']()
            policy = deps['rbac'].validate(deps['load_policy']())
            if not isinstance(policy, dict) or config.get('activation_status') != 'W0_verified' or config.get('live_admin_single_page') is not True:
                raise PermissionError()
            if deps['authorize'](user, {'scope': 'all'}, True) is not True:
                raise PermissionError()
            return digest([config, policy])
        epoch = check()
        def read(name, args=None):
            return directory_read(name, args or {}, deps=deps, run_source=run_source, check=check, epoch=epoch)
        def options(rows, key='id', label='title'):
            result = []
            for row in rows:
                value, text = row.get(key), row.get(label)
                if type(value) not in (str, int) or not str(value) or not isinstance(text, str) or not text:
                    raise RuntimeError('metadata_source_schema_changed')
                result.append(dict(value=str(value), label=text))
            return result
        result = dict(sites=options([r for r in read('sites') if deps['authorize'](user, {'scope': 'site', 'scope_id': str(r.get('id'))}, True) is True], label='full_title'),
                      games=options(read('games')),
                      progress=[dict(value='1', label='1 | 已支付')], status=[], cid=[],
                      aid=[], admin_id=[],
                      country=options(read('countries'), key='country', label='country'))
        if progress:
            if progress not in {o['value'] for o in result['progress']}:
                raise ValueError()
            result['status'] = [dict(value='11', label='11 | 已支付')]
        if any(g not in {o['value'] for o in result['games']} for g in games):
            raise PermissionError()
        # Admin UI evidence: getProType is global, but selection is enabled after games.
        if games:
            result['cid'] = [dict(value=value, label=label) for value, label in (
                ('1', '货币(Gold)'), ('0', '物品(Items)'), ('3', '账号(Account)'),
                ('2', '代练(Powerleveling)'), ('5', '代练包(Package)'),
                ('7', '礼品卡(Gift Cards)'), ('8', '充值(Top Up)'), ('9', '陪玩(Coach)'))]
        servers, unavailable = {}, {}
        try:
            for game in games:
                for option in options(read('servers', {'gid': game})):
                    servers[option['value']] = option
        except RuntimeError as error:
            # Only source refusal is optional; schema/coverage failures stay fail closed.
            if str(error) != 'metadata_source_unavailable':
                raise
            unavailable['aid'] = 'metadata_source_unavailable'
        if not unavailable:
            result['aid'] = list(servers.values())
        if check() != epoch:
            raise PermissionError()
        payload = {'options': result, 'semantics': 'live_non_snapshot'}
        if unavailable:
            payload['unavailable'] = unavailable
        return 200, payload
    except PermissionError:
        return 403, {'error': 'scope_denied'}
    except (ValueError, TypeError, KeyError):
        return 422, {'error': 'invalid_metadata_request'}
    except Exception:
        return 503, {'error': 'metadata_source_unavailable', 'complete': False}


def metadata_get(request, user, *, run_source=None, deps=None):
    """One allowlisted directory read; caller supplies verified actor/admission."""
    if not user:
        return 401, {'error': 'login_required'}
    if not callable(run_source):
        return 503, {'error': 'live_admission_unavailable'}
    try:
        if not isinstance(request, dict) or set(request) - {'site_id', 'game_id', 'directory', 'arguments'} or not {'site_id', 'directory'} <= set(request):
            raise ValueError()
        name, args = request['directory'], request.get('arguments', {})
        if not validate_metadata_args(name, args):
            raise ValueError()
        deps = dependencies() if deps is None else deps
        def check():
            config = deps['load_config']()
            policy = deps['rbac'].validate(deps['load_policy']())
            if not isinstance(policy, dict):
                raise PermissionError()
            if config.get('activation_status') != 'W0_verified' or config.get('live_admin_single_page') is not True:
                raise PermissionError()
            if deps['authorize'](user, {'scope': 'site', 'scope_id': request['site_id']}, True) is not True:
                raise PermissionError()
            game = args.get('gid') if name == 'servers' else request.get('game_id')
            return digest([config, policy])
        epoch = check()
        rows = directory_read(name, args, deps=deps, run_source=run_source, check=check, epoch=epoch)
        return 200, {'directory': name, 'data': rows, 'semantics': 'live_non_snapshot'}
    except PermissionError:
        return 403, {'error': 'scope_denied'}
    except (ValueError, TypeError, KeyError):
        return 422, {'error': 'invalid_metadata_request'}
    except Exception:
        return 503, {'error': 'metadata_source_unavailable'}


def dependencies():
    from admin_live_host import read_existing_json, CONFIG
    from admin_supervised_transport import SupervisedAdminTransport
    sys.path.insert(0, '/opt/fs-access-policy')
    import rbac
    from user_runtime import authorize
    worker = Path(__file__).with_name('admin_email_export_worker.py')
    # Pinned worker bytes; transport independently verifies ownership and content.
    worker_hash = WORKER_SHA256
    return dict(load_config=lambda: read_existing_json(CONFIG), load_policy=lambda: read_existing_json(rbac.LIVE_POLICY),
                rbac=rbac, authorize=authorize, fetch=SupervisedAdminTransport(worker=str(worker), worker_sha256=worker_hash, python=sys.executable))


WORKER_SHA256 = 'd1b67b4f11c08fef0e0651b71e6f45e82af3f818d23c14f7645458ba4204bef6'


def get(params, user, *, run_source=None):
    if not user:
        return 401, {'error': 'login_required'}
    if not callable(run_source):
        return 503, {'error': 'live_admission_unavailable'}
    try:
        return build_handler(**dependencies(), run_source=run_source)(params, user)
    except Exception:
        return 503, {'error': 'export_source_unavailable'}
