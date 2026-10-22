"""Permission-injected query layer shared by UI and both Hermes readers."""
from datetime import datetime
import json

from user_contract import TZ, aggregate_only, checked_query, stamp
from user_lifecycle import analyze, project_analysis


class Service:
    def __init__(self, store, authorizer, clock=None):
        if not callable(authorizer):
            raise ValueError('existing_authorizer_required')
        self.store, self.authorizer = store, authorizer
        self.clock = clock or (lambda: datetime.now(TZ))

    def permit(self, user, query, private=False):
        if not user or self.authorizer(user, query, private) is not True:
            raise PermissionError('user_scope_denied')

    def query(self, args, user):
        if not isinstance(args, dict):
            raise ValueError('query_fields')
        config = self.store.config
        if args.get('snapshot_id'):
            old, public, members = self.store.snapshot(args['snapshot_id'])
            # Query retrieval never silently switches to the newest version or a different scope.
            requested = {k: v for k, v in args.items() if k != 'snapshot_id'}
            if requested:
                if checked_query(requested, config, self.clock()) != old:
                    raise ValueError('snapshot_query_mismatch')
            self.permit(user, old)
            return public
        query = checked_query(args, config, self.clock())
        self.permit(user, query)
        version, orders, jobs = self.store.read()
        result, private = analyze(orders, jobs, query, config)
        result.update(contract_version='fs-users-v1', query=query, timezone='Asia/Shanghai',
                      scope_version=config['scope_version'], identity_version=config['identity_version'],
                      policy_version=query['policy_version'], data_version=version,
                      captured_at=max((json.loads(j['body']).get('captured_at', '') for j in jobs), default=None),
                      source_watermark=[dict(site=j['site'], start=j['start'], end_exclusive=j['end'], state=j['state']) for j in jobs],
                      scope_label='已接入站点的购买客户', full_company_coverage=config.get('full_company_coverage', False),
                      status='available' if result['coverage']['period_complete'] and result['coverage']['identity_deduplication_complete'] and not result['coverage']['missing_identity_orders'] else 'partial')
        # Project matrix always compares with whole connected-company activity at the same as_of.
        global_query = dict(query, scope='global', scope_id='', policy_version=config.get('global_policy_version', 'common-v1'))
        global_config = config
        if query['scope'] == 'site':
            global_config = dict(config, sites={query['scope_id']: config['sites'][query['scope_id']]})
        if query['view'] in ('projects', 'transitions', 'migration'):
            self.permit(user, global_query)
            global_result, global_private = analyze(orders, jobs, global_query, global_config)
            result['projects'], result['migration'] = project_analysis(orders, jobs, query, global_config, global_result, global_private)
        aggregate_only(result)
        return self.store.save_snapshot(query, result, private)

    def catalog(self, user):
        allowed = []
        for sid, site in self.store.config['sites'].items():
            if self.authorizer(user, {'scope': 'site', 'scope_id': sid}, False) is True:
                allowed.append(dict(id=sid, label=site['label']))
        if not allowed:
            raise PermissionError('user_scope_denied')
        return dict(contract_version='fs-users-v1', sites=allowed, projects=self.store.config['projects'],
                    policies=self.store.config['policies'], full_company_coverage=self.store.config.get('full_company_coverage', False))

    def members(self, args, user):
        if set(args) - {'snapshot_id', 'group', 'cursor', 'limit'} or not {'snapshot_id', 'group'} <= set(args):
            raise ValueError('private_query_fields')
        query, public, private = self.store.snapshot(args['snapshot_id'])
        self.permit(user, query, True)
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
        self.permit(user, query, True)
        if set(args) != {'snapshot_id', 'group'} or args['group'] not in private['members']:
            raise ValueError('private_export_fields')
        if not public['coverage']['identity_deduplication_complete']:
            raise ValueError('cross_site_identity_unverified')
        ids = private['members'][args['group']]
        return dict(snapshot_id=public['snapshot_id'], total=len(ids), group=args['group'],
                    rows=[private['records'][cid] for cid in ids])
