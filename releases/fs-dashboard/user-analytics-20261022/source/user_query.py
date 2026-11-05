"""Permission-injected query layer shared by UI and both Hermes readers."""
from contextlib import ExitStack
from datetime import datetime, timedelta
from collections import OrderedDict
from copy import deepcopy
from threading import RLock, Timer
from time import monotonic
import json
import hashlib
import re

from user_contract import TZ, aggregate_only, checked_query, stamp, digest, METRIC_DEFINITIONS, OBSERVATION_POLICIES
from user_lifecycle import analyze, project_analysis, in_scope, covered


class Service:
    def __init__(self, store, authorizer, clock=None, customer_type_reader=None, weekly_publication=None, permission_epoch=None, export_sink=None, export_verifier=None, export_publisher=None):
        if not callable(authorizer):
            raise ValueError('existing_authorizer_required')
        self.store, self.authorizer = store, authorizer
        self.clock = clock or (lambda: datetime.now(TZ))
        self.customer_type_reader = customer_type_reader
        self.weekly_publication = weekly_publication
        self.permission_epoch,self.export_sink = permission_epoch,export_sink
        self.export_verifier,self.export_publisher = export_verifier,export_publisher
        self.cache = OrderedDict()
        self.cache_lock = RLock()
        self.private_lock = RLock()
        self.private_cache = None
        self.private_cache_timer = None

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
        storage = config.get('snapshot_storage', 'full')
        if storage not in ('full', 'recipe-v1'):
            raise ValueError('snapshot_storage_policy')
        if args.get('snapshot_id'):
            old, public = self.store.snapshot_public(args['snapshot_id'])
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
        with ExitStack() as archive_read:
            if self.weekly_publication is not False and config.get('update_cadence') in ('weekly-v1','daily-v1'):
                from user_customer_types import publication_archive_access
                archive_read.enter_context(publication_archive_access())
            publication = None
            if self.weekly_publication is not False and config.get('update_cadence') in ('weekly-v1', 'daily-v1'):
                from user_weekly import publication as read_publication
                publication = read_publication(self.store, self.clock())
                config = dict(publication['config'], weekly_data_cutoff=publication['cutoff'])
                args = {'start': (stamp(publication['cutoff'])-timedelta(days=7)).isoformat(), **args}
            query = checked_query(args, config, self.clock())
            self.permit(user, query)
            period_cohort = query['state_basis'] == 'period_cohort'
            flags, flag_source = ({}, dict(status='unavailable',source='Admin ES order-time new-customer flag'))
            if period_cohort and self.customer_type_reader and not publication:
                try:
                    flags, flag_source = self.customer_type_reader(query)
                except (OSError,ValueError,KeyError,TypeError,ImportError) as error:
                    flag_source = dict(status='unavailable',source='Admin ES order-time new-customer flag',reason='source_contract_unavailable',error_type=type(error).__name__)
            global_policy = query['policy_version'] if query['policy_version'] in OBSERVATION_POLICIES else config.get('global_policy_version', 'common-v1')
            global_query = dict(query, scope='global', scope_id='', policy_version=global_policy)
            global_allowed = self.authorizer(user, global_query, False) is True
            proof_path = self.store.root/'history-origin.json'
            bounded_path = self.store.root/'history-coverage.json'
            refresh_health = publication['refresh_health'] if publication else self.store.job_health()
            cache_key = digest([query, config, flag_source, publication['publication_id'] if publication else self.store.revision(), refresh_health, user, global_allowed,
                                proof_path.read_text('utf-8') if not publication and proof_path.is_file() else None,
                                bounded_path.read_text('utf-8') if not publication and bounded_path.is_file() else None])
            with self.cache_lock:
                if cache_key in self.cache:
                    self.cache.move_to_end(cache_key)
                    return deepcopy(self.cache[cache_key])
            if period_cohort and publication:
                from user_customer_types import read_pinned_flags
                try:
                    flags, flag_source = read_pinned_flags(query, publication['flag_manifests'])
                except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
                    flag_source = dict(status='unavailable', source='Admin ES order-time new-customer flag',
                                       reason='frozen_source_unavailable', error_type=type(error).__name__)
        period = dict(start=query['start'], end=query['end_exclusive']) if period_cohort else {}
        if publication:
            version, orders, jobs = publication['data_version'], self.store.read_at(publication['data_version'], **period), deepcopy(publication['jobs'])
        else:
            version, orders, jobs = self.store.read(analytics=True, **period)
        if period_cohort:
            config = dict(config, period_customer_types=flags)
        if not publication and proof_path.is_file():
            from user_store import safe
            safe(proof_path)
            proof = json.loads(proof_path.read_text('utf-8'))
            inventory = self.store.root/'history-full-inventory.json'
            safe(inventory)
            if (proof.get('contract') != 'fs-users-available-source-history-v1' or proof.get('sites') != sorted(config['sites'])
                    or proof.get('inventory_sha256') != digest(json.loads(inventory.read_text('utf-8')))
                    or not covered(jobs,list(config['sites']),stamp(proof['start']),stamp(proof['end_exclusive']))):
                raise ValueError('history_completion_proof_mismatch')
            config = dict(config,available_history_origin=proof['start'])
        result, private = analyze(orders, jobs, query, config)
        result.update(contract_version='fs-users-v3-period-cohort' if period_cohort else 'fs-users-v2', query=query, timezone='Asia/Shanghai',
                      scope_version=config['scope_version'], identity_version=config['identity_version'],
                      policy_version=query['policy_version'], data_version=version,
                      lifecycle_policy=dict(version=query['policy_version'], thresholds_days=list(config['policies'][query['policy_version']]), day_basis='Asia/Shanghai calendar days since last effective purchase'),
                      lifecycle_policies={name: list(points) for name, points in config['policies'].items()},
                      captured_at=max((json.loads(j['body']).get('captured_at', '') for j in jobs), default=None),
                      source_watermark=[dict(site=j['site'], start=j['start'], end_exclusive=j['end'], state=j['state']) for j in jobs],
                      source_status_rule_versions=sorted({json.loads(j['body'])['source_status_rule_sha256'] for j in jobs if json.loads(j['body']).get('source_status_rule_sha256')}),
                      refresh_health=refresh_health,
                      scope_label='已接入站点的购买客户', full_company_coverage=config.get('full_company_coverage', False),
                      status='available' if result['coverage']['period_complete'] and result['coverage']['identity_deduplication_complete'] and not result['coverage']['missing_identity_orders'] else 'partial')
        if period_cohort:
            result['customer_type_source'] = flag_source
            result['metric_definitions'] = {**METRIC_DEFINITIONS,
                'recent': dict(METRIC_DEFINITIONS['recent'],label='已复购且近期购买',definition='期间至少两笔有效订单，距期末末购尚未达到沉默阈值'),
                'known_pool': dict(METRIC_DEFINITIONS['known_pool'],label='所选期间购买邮箱',definition='只取所选开始日至昨日内至少一次有效购买的已核邮箱')}
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
        self.store.decorate_private_v1(private, orders, query, config, global_allowed)
        result['requires_global_scope'] = global_allowed
        result['coverage'].update(series_history_complete=config.get('series_history_complete', False), satellite_gaps=config.get('satellite_gaps', []), refund_policy=config.get('refund_policy'))
        progress = self.store.root / 'history-backfill.json'
        if not publication and progress.is_file():
            # Purpose-specific aggregate receipt only; never expose raw source diagnostics.
            receipt = json.loads(progress.read_text('utf-8'))
            result['coverage']['backfill'] = {key: receipt[key] for key in ('status', 'start', 'end_exclusive', 'target_start','target_end_exclusive','completed_windows', 'source_rows', 'at') if key in receipt}
        result['coverage']['backfill_target_start'] = config.get('history_backfill_start')
        if not publication and bounded_path.is_file():
            bounded = json.loads(bounded_path.read_text('utf-8'))
            inventory_file = bounded.get('inventory_file', 'history-full-inventory.json')
            if inventory_file != 'history-full-inventory.json' and not re.fullmatch(r'history-inventory-[a-f0-9]{64}\.json', inventory_file):
                raise ValueError('bounded_history_inventory_path')
            from user_store import safe
            safe(self.store.root/inventory_file)
            if (bounded.get('contract') != 'fs-users-bounded-history-v1' or bounded.get('sites') != sorted(config['sites'])
                    or stamp(bounded['start']) < stamp(config['history_backfill_start'])
                    or bounded.get('inventory_sha256') != digest(json.loads((self.store.root/inventory_file).read_text('utf-8')))
                    or not covered(jobs,list(config['sites']),stamp(bounded['start']),stamp(bounded['end_exclusive']))):
                raise ValueError('bounded_history_proof_mismatch')
            result['coverage']['history_window'] = dict(start=bounded['start'],end_exclusive=bounded['end_exclusive'],complete=True,earlier_history_included=False)
        if publication:
            from user_weekly import public_info
            result.update(captured_at=publication['captured_at'], source_status_rule_versions=publication['source_status_rule_versions'], weekly_update=public_info(publication))
            result['coverage'].update(publication['coverage_context'])
        aggregate_only(result)
        if storage == 'recipe-v1':
            private.pop('events', None)
            recipe_config = config
            if period_cohort:
                used = {json.loads(row['body']).get('order_no_hash') for row in orders
                        if row['customer_id'] in private['records'] and in_scope(row, query, config)}
                recipe_config = dict(config, period_customer_types={key: label for key, label in flags.items() if key in used})
            # Fixed inputs plus a checksum replace a permanently stored full customer list.
            members = dict(contract='fs-users-private-replay-v1', query=query, data_version=version,
                           config=recipe_config, jobs=[{key: j[key] for key in ('site', 'start', 'end', 'state')} for j in jobs],
                           global_allowed=global_allowed, private_sha256=digest(private))
        else:
            members = private
        frozen = self.store.save_snapshot(query, result, members)
        if self.store.config.get('member_keyset_index') is True:
            from user_member_index import build
            build(self.store, frozen, private)
        # A transient/partial pinned export must be retried on a later query, not frozen in the success cache.
        if not period_cohort or flag_source.get('status') == 'complete':
            with self.cache_lock:
                self.cache[cache_key] = deepcopy(frozen)
                if len(self.cache) > 8:
                    self.cache.popitem(last=False)
        return frozen

    def expire_private_cache(self, deadline):
        with self.private_lock:
            if self.private_cache is not None and self.private_cache[1] == deadline:
                remaining = deadline - monotonic()
                if remaining > 0:
                    self.schedule_private_expiry(deadline, remaining)
                else:
                    self.private_cache = None
                    self.private_cache_timer = None

    def schedule_private_expiry(self, deadline, delay=120):
        timer = Timer(delay, self.expire_private_cache, args=(deadline,))
        timer.daemon = True
        self.private_cache_timer = timer
        timer.start()

    def private_snapshot(self, ident, user):
        query, public = self.store.snapshot_public(ident)
        self.permit_snapshot(user, query, public, True)
        # Serialize reconstruction and retain one cached list, also expiring while idle.
        with self.private_lock:
            token = self.store.snapshot_token(ident)
            if self.private_cache is not None:
                if token is not None and self.private_cache[0] == ident and monotonic() < self.private_cache[1] and self.private_cache[2] == token:
                    return self.private_cache[3]
            self.private_cache = None
            if self.private_cache_timer is not None:
                self.private_cache_timer.cancel()
                self.private_cache_timer = None
            value = self.store.snapshot(ident)
            if token is not None:
                deadline = monotonic() + 120
                self.private_cache = (ident, deadline, token, value)
                self.schedule_private_expiry(deadline)
            return value

    def catalog(self, user):
        allowed = []
        for sid, site in self.store.config['sites'].items():
            if self.authorizer(user, {'scope': 'site', 'scope_id': sid}, False) is True:
                allowed.append(dict(id=sid, label=site['label']))
        if not allowed:
            raise PermissionError('user_scope_denied')
        value = dict(contract_version='fs-users-v1', sites=allowed, projects=self.store.config['projects'],
                    policies=self.store.config['policies'], full_company_coverage=self.store.config.get('full_company_coverage', False),
                    metric_definitions=METRIC_DEFINITIONS, history_backfill_start=self.store.config.get('history_backfill_start'),
                    can_read_private=self.authorizer(user, {'scope': 'global', 'scope_id': ''}, True) is True)
        if self.store.config.get('update_cadence') in ('weekly-v1', 'daily-v1'):
            from user_weekly import publication, public_info, small_state, WeeklyUnavailable
            try:
                value['weekly_update'] = public_info(publication(self.store, self.clock()))
            except WeeklyUnavailable:
                value['weekly_update'] = dict(cadence='daily' if self.store.config.get('update_cadence') == 'daily-v1' else 'weekly', status='initial_publication_pending')
            state = small_state(self.store.root)
            if state and state.get('phase') != 'complete':
                value['weekly_update']['pending'] = {k: state[k] for k in ('cutoff', 'phase', 'error', 'retryable') if k in state}
                if state.get('review_policy') == 'calendar-months-v1' and state.get('review_start'):
                    pending=value['weekly_update']['pending']
                    pending['review_pending']=not state.get('review_complete',False)
                    pending['cleanup_pending']=bool(state.get('review_complete'))
                    pending['daily_current']=bool(value['weekly_update'].get('cutoff') and not state.get('daily_error') and stamp(value['weekly_update']['cutoff'])>=self.clock().astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0))
                    for key in ('daily_error','cleanup_error'):
                        if key in state:
                            error=state[key] if isinstance(state[key],dict) else {}
                            code=error.get('error','source_error')
                            pending[key]=dict(error=code if isinstance(code,str) and re.fullmatch('[A-Za-z_:]{1,120}',code) else 'source_error',retryable=error.get('retryable') is True)
        return value

    def search(self, args, user):
        if not isinstance(args, dict) or set(args) != {'snapshot_id', 'email'}:
            raise ValueError('private_search_fields')
        query, public, private = self.private_snapshot(args['snapshot_id'], user)
        if query.get('state_basis') != 'period_cohort':
            raise ValueError('period_cohort_required')
        email = args['email']
        if not isinstance(email, str) or not 3 <= len(email.strip()) <= 320 or '@' not in email or any(ord(c) < 32 for c in email):
            raise ValueError('invalid_email')
        if not public['coverage']['identity_deduplication_complete']:
            raise ValueError('cross_site_identity_unverified')
        ids = self.store.find_email(email.strip(), public['coverage']['sites']) & private['records'].keys()
        if len(ids) > 1:
            raise ValueError('cross_site_identity_unverified')
        if not ids:
            return dict(snapshot_id=public['snapshot_id'], found=False, period_complete=public['coverage']['period_complete'])
        return dict(self.detail(dict(snapshot_id=args['snapshot_id'], customer_id=next(iter(ids))), user), found=True)

    def detail(self, args, user):
        if set(args) != {'snapshot_id', 'customer_id'}:
            raise ValueError('private_detail_fields')
        query, public, private = self.private_snapshot(args['snapshot_id'], user)
        cid = args['customer_id']
        if cid not in private['records']:
            raise LookupError('customer_not_in_snapshot')
        orders = [dict(site=r['site'], project_id=r['gid'], paid_at=r['paid_at'], valid=bool(r['valid']), **json.loads(r['body']))
                  for r in self.store.orders_at(public['data_version'], cid)
                  if stamp(r['paid_at']) < stamp(query['as_of']) and (query.get('state_basis') != 'period_cohort' or stamp(r['paid_at']) >= stamp(query['start'])) and r['site'] in self.store.config['sites']
                  and (query['scope'] != 'site' or r['site'] == query['scope_id']) and ((query.get('state_basis') != 'period_cohort' and public.get('requires_global_scope')) or in_scope(r, query, dict(self.store.config, projects=private.get('scope_projects', self.store.config['projects']))))]
        scoped = [r for r in orders if r['valid'] and in_scope(dict(r, gid=r['project_id']), query, dict(self.store.config, projects=private.get('scope_projects', self.store.config['projects'])))]
        if query.get('state_basis') == 'period_cohort':
            scoped.sort(key=lambda r:(r['paid_at'],int(r.get('id') or 0),r['order_no']))
        points = public.get('lifecycle_policy', {}).get('thresholds_days', self.store.config['policies'][query['policy_version']])
        jobs = [dict(site=j['site'], start=j['start'], end=j['end_exclusive'], state=j['state']) for j in public['source_watermark']]
        timeline = []
        first = private['records'][cid]['first_paid_at']
        for index, row in enumerate(scoped):
            paid = stamp(row['paid_at'])
            following = stamp(scoped[index+1]['paid_at']) if index+1 < len(scoped) else stamp(query['as_of'])
            previous = stamp(scoped[index-1]['paid_at']) if index else None
            gap = (paid.date()-previous.date()).days if previous else None
            if previous and paid.time() == datetime.min.time() and gap in points:
                gap -= 1
            kind = 'first_purchase' if not index else 'lost_return' if gap >= points[1] else 'silent_wakeup' if gap >= points[0] else 'repeat_purchase'
            observed = stamp(private['records'][cid]['earliest_observed_at']).date()
            timeline.append(dict(at=paid.isoformat(), kind=kind, stage='waiting' if query.get('state_basis') == 'period_cohort' and not index else 'recent', days_from_d0=(paid.date()-stamp(first).date()).days if first else None,days_from_observed_first=(paid.date()-observed).days))
            for threshold, stage_name in zip(points, ('silent','lost','long_lost')):
                at = datetime.combine(paid.date()+timedelta(days=threshold), datetime.min.time(), TZ)
                through = min(at, stamp(public['coverage'].get('state_data_through',query['as_of'])))
                if at < following and at < stamp(query['as_of']) and covered(jobs, public['coverage']['sites'], paid, through):
                    timeline.append(dict(at=at.isoformat(),kind='enter',stage=stage_name,days_from_d0=(at.date()-stamp(first).date()).days if first else None,days_from_observed_first=(at.date()-observed).days))
        return dict(snapshot_id=public['snapshot_id'], customer=deepcopy(private['records'][cid]), timeline=timeline,
                    email=self.store.email(cid), orders=orders,
                    note=('D0为所选期间第一笔有效购买；新老客取该单的ES原标记，状态只算到昨日，不代表终身首次购买。' if query.get('state_basis') == 'period_cohort' else '时间线从已覆盖最早购买记为观察D0；更早历史未齐时不代表真实首购。')+'按当前已知状态冻结，金额为整单关联金额，不跨项目分摊。')

    def filtered_members(self, query, private, args):
        repeat, customer_type = args.get('repeat_status','all'), args.get('customer_type','all')
        if repeat not in ('all','repeated','not_repeated') or customer_type not in ('all','new','old','unknown'):
            raise ValueError('private_period_filter')
        if query.get('state_basis') != 'period_cohort' and (repeat != 'all' or customer_type != 'all'):
            raise ValueError('period_cohort_filter_required')
        group = args['group']
        if group not in private['members']:
            raise ValueError('private_group_or_limit')
        ids = private['members'][group]
        if repeat != 'all':
            ids = [cid for cid in ids if private['records'][cid].get('period_repeated') is (repeat == 'repeated')]
        if customer_type != 'all':
            ids = [cid for cid in ids if private['records'][cid].get('period_entry_customer_type') in (('unknown','conflict') if customer_type == 'unknown' else (customer_type,))]
        return ids

    def members(self, args, user):
        if set(args) - {'snapshot_id', 'group', 'cursor', 'limit','repeat_status','customer_type'} or not {'snapshot_id', 'group'} <= set(args):
            raise ValueError('private_query_fields')
        if self.store.config.get('member_keyset_index') is True:
            return self.indexed_members(args, user)
        query, public, private = self.private_snapshot(args['snapshot_id'], user)
        if not public['coverage']['identity_deduplication_complete']:
            raise ValueError('cross_site_identity_unverified')
        group, cursor, limit = args['group'], args.get('cursor', ''), args.get('limit', 50)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('private_group_or_limit')
        ids = self.filtered_members(query, private, args)
        if cursor and cursor not in ids:
            raise ValueError('private_cursor_mismatch')
        offset = ids.index(cursor) + 1 if cursor else 0
        selected = ids[offset:offset + limit]
        return dict(snapshot_id=public['snapshot_id'], total=len(ids), group=group,
                    rows=[deepcopy(private['records'][cid]) for cid in selected],
                    next_cursor=selected[-1] if offset + limit < len(ids) else None)

    def export(self, args, user):
        # JSON export is frozen and contains the same administrator-only masked rows.
        if self.store.config.get('member_keyset_index') is True:
            from user_member_index import IndexUnavailable
            if not isinstance(args,dict) or set(args)-{'snapshot_id','group','repeat_status','customer_type'} or not {'snapshot_id','group'}<=set(args):raise ValueError('private_export_fields')
            if not all(callable(callback) for callback in (self.export_sink,self.export_verifier,self.export_publisher)):raise IndexUnavailable('streaming_export_host_required')
            header=self.indexed_members(dict(args,limit=1),user)
            header={k:v for k,v in header.items() if k not in ('rows','next_cursor')}
            header['export_filter_hash']=digest([header['snapshot_id'],args['group'],args.get('repeat_status','all'),args.get('customer_type','all'),header['data_version'],header['permission_epoch']])
            completion={}
            prepared=self.export_sink(header,self.export_iter(args,user,completion))
            if not completion.get('complete'):raise IndexUnavailable('streaming_export_incomplete')
            def checked(receipt,phase):
                if not isinstance(receipt,dict) or receipt.get('contract')!='fs-member-export-receipt-v1' or receipt.get('status')!=phase or not isinstance(receipt.get('artifact_id'),str) or re.fullmatch('[A-Za-z0-9_-]{1,160}',receipt['artifact_id']) is None:raise IndexUnavailable('streaming_export_receipt_invalid')
                expected=dict(snapshot_id=header['snapshot_id'],data_version=header['data_version'],export_filter_hash=header['export_filter_hash'],rows=completion['rows'],bytes=completion['bytes'],sha256=completion['sha256'])
                if any(type(receipt.get(key)) is not type(value) or receipt[key]!=value for key,value in expected.items()):raise IndexUnavailable('streaming_export_receipt_invalid')
                if self.export_verifier(user,header,receipt) is not True:raise IndexUnavailable('streaming_export_publication_unverified')
            checked(prepared,'prepared')
            query,public=self.store.snapshot_public(header['snapshot_id'])
            publication_check=[False]
            def revalidate():
                self.permit_snapshot(user,query,public,True)
                if self.permission_epoch(user,query)!=header['permission_epoch']:raise PermissionError('export_permission_changed')
                publication_check[0]=True
                return True
            revalidate();publication_check[0]=False
            # Publisher must invoke this callback inside its existing publication
            # lock immediately before committing the artifact manifest.
            receipt=self.export_publisher(user,header,prepared,revalidate)
            if not publication_check[0]:raise IndexUnavailable('streaming_export_publication_not_authorized')
            checked(receipt,'published');revalidate()
            return dict(receipt,**header,complete=True,exported_rows=completion['rows'])
        query, public, private = self.private_snapshot(args.get('snapshot_id'), user)
        if set(args) - {'snapshot_id', 'group','repeat_status','customer_type'} or not {'snapshot_id','group'} <= set(args):
            raise ValueError('private_export_fields')
        if not public['coverage']['identity_deduplication_complete']:
            raise ValueError('cross_site_identity_unverified')
        ids = self.filtered_members(query, private, args)
        return dict(snapshot_id=public['snapshot_id'], total=len(ids), group=args['group'],
                    rows=[deepcopy(private['records'][cid]) for cid in ids])

    def indexed_members(self,args,user):
        from user_member_index import page,IndexUnavailable
        if not isinstance(args,dict) or set(args)-{'snapshot_id','group','cursor','limit','repeat_status','customer_type'} or not {'snapshot_id','group'}<=set(args):raise ValueError('private_query_fields')
        query,public=self.store.snapshot_public(args['snapshot_id'])
        self.permit_snapshot(user,query,public,True)
        if not public['coverage']['identity_deduplication_complete']:raise ValueError('cross_site_identity_unverified')
        if not callable(self.permission_epoch):raise IndexUnavailable('permission_epoch_required')
        return page(self.store,query,public,args,user,self.permission_epoch(user,query))

    def export_iter(self,args,user,completion=None):
        """Yield actual frozen DB pages; the existing export host consumes the iterator."""
        from user_member_index import IndexUnavailable
        if self.store.config.get('member_keyset_index') is not True:raise IndexUnavailable('member_index_not_enabled')
        if not isinstance(args,dict) or set(args)-{'snapshot_id','group','repeat_status','customer_type'} or not {'snapshot_id','group'}<=set(args):raise ValueError('private_export_fields')
        budget=self.store.config.get('member_export_max_bytes',8*1024*1024)
        if type(budget) is not int or not 0<budget<=512*1024*1024:raise ValueError('private_export_budget')
        cursor=None;count=size=0;checksum=hashlib.sha256()
        while True:
            request=dict(args,limit=200)
            if cursor is not None:request['cursor']=cursor
            value=self.members(request,user)
            for row in value['rows']:
                from user_contract import canonical
                raw=canonical(row).encode()+b'\n';size+=len(raw);checksum.update(raw)
                if size>budget:raise IndexUnavailable('streaming_export_budget_exhausted')
                count+=1
                yield row
            cursor=value['next_cursor']
            if cursor is None:break
        if count!=value['total']:raise ValueError('member_projection_incomplete')
        if completion is not None:completion.update(complete=True,rows=count,bytes=size,sha256=checksum.hexdigest())
