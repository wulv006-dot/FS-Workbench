"""Permission-injected query layer shared by UI and both Hermes readers."""
from datetime import datetime
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
import json

from user_contract import TZ, aggregate_only, checked_query, stamp, digest, METRIC_DEFINITIONS
from user_lifecycle import analyze, project_analysis, in_scope


class Service:
    def __init__(self, store, authorizer, clock=None):
        if not callable(authorizer):
            raise ValueError('existing_authorizer_required')
        self.store, self.authorizer = store, authorizer
        self.clock = clock or (lambda: datetime.now(TZ))
        self.cache = OrderedDict()
        self.cache_lock = RLock()

    def permit(self, user, query, private=False):
        if not user or self.authorizer(user, query, private) is not True:
            raise PermissionError('user_scope_denied')

    def permit_snapshot(self, user, query, public, private=False):
        self.permit(user, query, private)
        if public.get('requires_global_scope'):
            self.permit(user, dict(query, scope='global', scope_id=''))

    def query(self, args, user):
        if not isinstance(args, dict):
            raise ValueError('query_fields')
        config = self.store.config
        if args.get('snapshot_id'):
            old, public, members = self.store.snapshot(args['snapshot_id'])
            # Query retrieval never silently switches to the newest version or a different scope.
            requested = {k: v for k, v in args.items() if k != 'snapshot_id'}
            for key, value in requested.items():
                if key not in old or type(value) not in (str, int):
                    raise ValueError('snapshot_query_fields')
                normalized = stamp(value).isoformat() if key in ('start', 'end_exclusive', 'as_of') else str(value) if key == 'scope_id' else value
                if normalized != old[key]:
                    raise ValueError('snapshot_query_mismatch')
            self.permit_snapshot(user, old, public)
            return public
        query = checked_query(args, config, self.clock())
        self.permit(user, query)
        global_query = dict(query, scope='global', scope_id='', policy_version=config.get('global_policy_version', 'common-v1'))
        global_allowed = self.authorizer(user, global_query, False) is True
        cache_key = digest([query, config, self.store.revision(), self.store.job_health(), user, global_allowed])
        with self.cache_lock:
            if cache_key in self.cache:
                self.cache.move_to_end(cache_key)
                return deepcopy(self.cache[cache_key])
        version, orders, jobs = self.store.read()
        result, private = analyze(orders, jobs, query, config)
        result.update(contract_version='fs-users-v1', query=query, timezone='Asia/Shanghai',
                      scope_version=config['scope_version'], identity_version=config['identity_version'],
                      policy_version=query['policy_version'], data_version=version,
                      lifecycle_policy=dict(version=query['policy_version'], thresholds_days=list(config['policies'][query['policy_version']]), day_basis='Asia/Shanghai calendar days since last effective purchase'),
                      captured_at=max((json.loads(j['body']).get('captured_at', '') for j in jobs), default=None),
                      source_watermark=[dict(site=j['site'], start=j['start'], end_exclusive=j['end'], state=j['state']) for j in jobs],
                      refresh_health=self.store.job_health(),
                      scope_label='已接入站点的购买客户', full_company_coverage=config.get('full_company_coverage', False),
                      status='available' if result['coverage']['period_complete'] and result['coverage']['identity_deduplication_complete'] and not result['coverage']['missing_identity_orders'] else 'partial')
        # Project matrix always compares with whole connected-company activity at the same as_of.
        global_config = config
        if query['scope'] == 'site':
            global_config = dict(config, sites={query['scope_id']: config['sites'][query['scope_id']]})
        if query['view'] in ('projects', 'transitions', 'migration') or query['view'] == 'summary' and global_allowed:
            self.permit(user, global_query)
            if query == global_query and global_config is config:
                global_result, global_private = result, private
            else:
                global_result, global_private = analyze(orders, jobs, global_query, global_config)
            result['projects'], result['migration'] = project_analysis(orders, jobs, query, global_config, global_result, global_private)
        by_customer = {}
        cutoff = stamp(query['as_of'])
        for row in orders:
            cid = row['customer_id']
            if cid and cid in private['records'] and row['site'] in config['sites'] and stamp(row['paid_at']) < cutoff:
                if row['valid']:
                    by_customer.setdefault(cid, []).append(row)
        for cid, record in private['records'].items():
            whole = by_customer.get(cid, [])
            if global_allowed:
                record.update(global_earliest_observed_at=min((r['paid_at'] for r in whole), default=None),
                              global_last_paid_at=max((r['paid_at'] for r in whole), default=None))
        result['requires_global_scope'] = global_allowed
        private['scope_projects'] = config['projects']
        result['coverage'].update(series_history_complete=config.get('series_history_complete', False), satellite_gaps=config.get('satellite_gaps', []), refund_policy=config.get('refund_policy'))
        aggregate_only(result)
        frozen = self.store.save_snapshot(query, result, private)
        with self.cache_lock:
            self.cache[cache_key] = deepcopy(frozen)
            if len(self.cache) > 8:
                self.cache.popitem(last=False)
        return frozen

    def catalog(self, user):
        allowed = []
        for sid, site in self.store.config['sites'].items():
            if self.authorizer(user, {'scope': 'site', 'scope_id': sid}, False) is True:
                allowed.append(dict(id=sid, label=site['label']))
        if not allowed:
            raise PermissionError('user_scope_denied')
        return dict(contract_version='fs-users-v1', sites=allowed, projects=self.store.config['projects'],
                    policies=self.store.config['policies'], full_company_coverage=self.store.config.get('full_company_coverage', False),
                    metric_definitions=METRIC_DEFINITIONS,
                    can_read_private=self.authorizer(user, {'scope': 'global', 'scope_id': ''}, True) is True)

    def detail(self, args, user):
        if set(args) != {'snapshot_id', 'customer_id'}:
            raise ValueError('private_detail_fields')
        query, public, private = self.store.snapshot(args['snapshot_id'])
        self.permit_snapshot(user, query, public, True)
        cid = args['customer_id']
        if cid not in private['records']:
            raise LookupError('customer_not_in_snapshot')
        orders = [dict(site=r['site'], project_id=r['gid'], paid_at=r['paid_at'], valid=bool(r['valid']), **json.loads(r['body']))
                  for r in self.store.orders_at(public['data_version'], cid)
                  if stamp(r['paid_at']) < stamp(query['as_of']) and r['site'] in self.store.config['sites']
                  and (query['scope'] != 'site' or r['site'] == query['scope_id']) and (public.get('requires_global_scope') or in_scope(r, query, dict(self.store.config, projects=private.get('scope_projects', self.store.config['projects']))))]
        return dict(snapshot_id=public['snapshot_id'], customer=private['records'][cid],
                    email=self.store.email(cid), orders=orders,
                    note='按当前已知状态冻结的历史；金额为整单关联金额，不跨项目分摊。')

    def members(self, args, user):
        if set(args) - {'snapshot_id', 'group', 'cursor', 'limit'} or not {'snapshot_id', 'group'} <= set(args):
            raise ValueError('private_query_fields')
        query, public, private = self.store.snapshot(args['snapshot_id'])
        self.permit_snapshot(user, query, public, True)
        if not public['coverage']['identity_deduplication_complete']:
            raise ValueError('cross_site_identity_unverified')
        group, cursor, limit = args['group'], args.get('cursor', ''), args.get('limit', 50)
        if group not in private['members'] or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('private_group_or_limit')
        ids = private['members'][group]
        if cursor and cursor not in ids:
            raise ValueError('private_cursor_mismatch')
        offset = ids.index(cursor) + 1 if cursor else 0
        selected = ids[offset:offset + limit]
        return dict(snapshot_id=public['snapshot_id'], total=len(ids), group=group,
                    rows=[private['records'][cid] for cid in selected],
                    next_cursor=selected[-1] if offset + limit < len(ids) else None)

    def export(self, args, user):
        # JSON export is frozen and contains the same administrator-only masked rows.
        query, public, private = self.store.snapshot(args.get('snapshot_id'))
        self.permit_snapshot(user, query, public, True)
        if set(args) != {'snapshot_id', 'group'} or args['group'] not in private['members']:
            raise ValueError('private_export_fields')
        if not public['coverage']['identity_deduplication_complete']:
            raise ValueError('cross_site_identity_unverified')
        ids = private['members'][args['group']]
        return dict(snapshot_id=public['snapshot_id'], total=len(ids), group=args['group'],
                    rows=[private['records'][cid] for cid in ids])
