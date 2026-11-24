"""Frozen user-analysis queries for the dashboard and authorized model consumers."""
from collections import OrderedDict
from datetime import date, time, timedelta
import json
import re
from threading import RLock

from user_contract import TZ, aggregate_only, digest, stamp
from user_lifecycle import (analyze_cohorts, analyze_stages, complete_coverage,
                            amount_summary, customer_orders, stage_events)
from user_summary_jobs import SummaryJobs

VERSION = 'fs-users-v4'
SECTIONS = ('summary', 'cohorts', 'stages', 'coverage')
FIELDS = {'scope', 'scope_id', 'game', 'start', 'end_exclusive', 'cohort_start', 'cohort_end',
          'windows', 'return_after', 'return_within', 'customer_type', 'repeat_status'}
SEGMENTS_PATH = '/var/lib/fs-customer-segments/segments.json'


class SnapshotVersionRetired(ValueError):
    def __init__(self):
        super().__init__('snapshot_version_retired')


def month(text):
    if not isinstance(text, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}', text) is None:
        raise ValueError('cohort_month')
    return date.fromisoformat(text + '-01')


def project_scope(game, *, site=False):
    if game != 'all':
        return dict(scope='project', scope_id=game)
    return dict(scope='site', scope_id='266') if site else dict(scope='global', scope_id='')


def selection(args, config, cutoff):
    if not isinstance(args, dict) or set(args) - FIELDS:
        raise ValueError('v4_query_fields')
    game = args.get('game', 'all')
    scope, ident = args.get('scope'), args.get('scope_id')
    if scope == 'project' and isinstance(ident, str) and ident in config['projects']:
        if 'game' in args and game != ident:
            raise ValueError('game_scope_mismatch')
        game = ident
    elif (scope, ident) not in ((None, None), ('global', ''), ('global', None), ('site', '266')):
        raise ValueError('v4_scope')
    if not isinstance(game, str) or game != 'all' and game not in config['projects']:
        raise ValueError('v4_game')
    origin = stamp(config['history_backfill_start'])
    start = stamp(args.get('start', max(origin, cutoff - timedelta(days=7)).isoformat()))
    end = stamp(args.get('end_exclusive', cutoff.isoformat()))
    if not origin <= start < end <= cutoff or start.time() != time.min or end.time() != time.min:
        raise ValueError('v4_stage_period')
    previous_month = (cutoff.date().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    cohort_start = args.get('cohort_start', origin.strftime('%Y-%m'))
    cohort_end = args.get('cohort_end', max(cohort_start, previous_month))
    if not origin.date().replace(day=1) <= month(cohort_start) <= month(cohort_end) <= (cutoff.date()-timedelta(days=1)).replace(day=1):
        raise ValueError('v4_cohort_period')
    windows = args.get('windows', '30,90,180')
    if isinstance(windows, str) and re.fullmatch(r'[0-9]{1,3}(,[0-9]{1,3}){0,4}', windows):
        windows = [int(value) for value in windows.split(',')]
    if not isinstance(windows, list) or not 1 <= len(windows) <= 5 or any(type(v) is not int or not 2 <= v <= 365 for v in windows) or sorted(set(windows)) != windows:
        raise ValueError('v4_windows')
    after, within = (args.get('return_after', 60), args.get('return_within', 180))
    if any(type(value) is not int for value in (after, within)) or not 2 <= after < within <= 365:
        raise ValueError('v4_return_window')
    customer_type, repeat_status = args.get('customer_type', 'all'), args.get('repeat_status', 'all')
    if customer_type not in ('all', 'new', 'old', 'unknown') or repeat_status not in ('all', 'repeated', 'not_repeated'):
        raise ValueError('v4_stage_filter')
    return dict(project_scope(game, site=scope == 'site'), game=game, start=start.isoformat(), end_exclusive=end.isoformat(),
                cohort_start=cohort_start, cohort_end=cohort_end, windows=windows,
                return_after=after, return_within=within, customer_type=customer_type, repeat_status=repeat_status)


def section_result(value, section):
    if section not in SECTIONS:
        raise ValueError('v4_section')
    if section == 'summary':
        return value
    return {key: part for key, part in value.items() if key not in ('cohorts', 'stages') or key == section}


class UsersV4:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.jobs = SummaryJobs(self.query)
        self.cache = OrderedDict()
        self.lock = RLock()

    def authorize(self, user, query, private=False):
        self.service.permit(user, query, private)

    def snapshot(self, snapshot_id, user, private=False):
        query, public = self.store.snapshot_public(snapshot_id)
        self.authorize(user, query or project_scope('all'), private)
        if public.get('contract_version') != VERSION:
            raise SnapshotVersionRetired()
        return query, public

    def get(self, args, user, *, wait_seconds=10, section='summary'):
        if section not in SECTIONS:
            raise ValueError('v4_section')
        if not isinstance(args, dict):
            raise ValueError('v4_query_fields')
        if 'snapshot_id' not in args and 'query_id' not in args:
            game = args.get('game', args.get('scope_id') if args.get('scope') == 'project' else 'all')
            self.authorize(user, project_scope(game, site=args.get('scope') == 'site'))
            config, _, cutoff = self.read_context()
            args = selection(args, config, cutoff)
            self.authorize(user, args)
        status, value = self.jobs.read(args, user, wait_seconds=wait_seconds)
        return status, section_result(value, section) if status == 200 else value

    def catalog(self, user, *, admin=False):
        self.authorize(user, project_scope('all'))
        original = self.service.catalog(user)
        return dict(contract_version=VERSION, sites=original['sites'], projects=original['projects'],
                    history_backfill_start=original['history_backfill_start'],
                    weekly_update=original.get('weekly_update'),
                    can_read_private=(original['can_read_private'] if admin else True),
                    available_sections=list(SECTIONS))

    def read_context(self):
        from user_weekly import publication as read_publication

        config = self.store.config
        publication = None
        if self.service.weekly_publication is not False and config.get('update_cadence') in ('daily-v1', 'weekly-v1'):
            publication = read_publication(self.store, self.service.clock())
            config = publication['config']
        cutoff = stamp(publication['cutoff']) if publication else self.service.clock().astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        return config, publication, cutoff

    def query(self, args, user):
        if 'snapshot_id' in args:
            if set(args) != {'snapshot_id'}:
                raise ValueError('snapshot_or_query')
            return self.snapshot(args['snapshot_id'], user)[1]
        from customer_segments import load_config as load_segments

        config, publication, cutoff = self.read_context()
        query = selection(args, config, cutoff)
        self.authorize(user, query)
        segments, version, source = load_segments(SEGMENTS_PATH)
        revision = publication['data_version'] if publication else self.store.revision()
        cache_key = digest([query, revision, publication['publication_id'] if publication else None, segments, source])
        with self.lock:
            ident = self.cache.get(cache_key)
            if ident is not None:
                self.cache.move_to_end(cache_key)
        if ident is not None:
            return self.snapshot(ident, user)[1]

        if not self.service.summary_slot.acquire(blocking=False):
            from user_query import SummaryBusy
            raise SummaryBusy('users_summary_busy')
        try:
            return self.materialize(query, config, cutoff, publication, revision, segments, version, source, cache_key)
        finally:
            self.service.summary_slot.release()

    def materialize(self, query, config, cutoff, publication, revision, segments, version, source, cache_key):
        from customer_segments import stage, thresholds

        origin = config['history_backfill_start']
        flag_query = dict(start=origin, end_exclusive=cutoff.isoformat())
        try:
            if publication is not None:
                from user_customer_types import read_pinned_flags
                flags, flag_source = read_pinned_flags(flag_query, publication['flag_manifests'], allow_gaps=True)
            elif self.service.customer_type_reader:
                flags, flag_source = self.service.customer_type_reader(flag_query)
            else:
                flags, flag_source = {}, {'status': 'unavailable'}
        except (OSError, ValueError) as error:
            flags, flag_source = {}, dict(status='unavailable', reason='frozen_source_unavailable',
                                          error_type=type(error).__name__)
        if publication is not None:
            orders = self.store.read_at(revision, start=origin, end=cutoff.isoformat())
            jobs = publication['jobs']
        else:
            read_revision, orders, jobs = self.store.read(analytics=True, start=origin, end=cutoff.isoformat())
            if read_revision != revision:
                from user_query import SummaryBusy
                raise SummaryBusy('users_publication_changed')
        people = customer_orders(orders, cutoff)
        cohorts, cohort_members = analyze_cohorts(orders, jobs, query, cutoff, flags, people=people)
        stages, stage_members, records = analyze_stages(orders, jobs, query, cutoff, flags, segments, people=people)
        covered = complete_coverage(jobs)
        day = stamp(origin)
        gaps = 0
        while day < cutoff:
            following = day + timedelta(days=1)
            gaps += not covered(day, following)
            day = following
        missing_identity = sum(row['site'] == '266' and not row['customer_id'] for row in orders)
        observation = (cutoff - timedelta(days=1)).date()
        cohort_customers = {identity for ids in cohort_members.values() for identity in ids}
        for cid in cohort_customers - records.keys():
            orders = people[cid]
            first = orders[0][0]
            last = next(order[0] for order in reversed(orders) if query['game'] in ('all', order[2]))
            records[cid] = dict(customer_id=cid, first_paid_at=first.isoformat(), customer_type='new',
                                last_paid_at=last.isoformat(),
                                stage=stage(last, observation, query['game'], segments, covered(last, cutoff)))
        query['as_of'] = cutoff.isoformat()
        period_complete = covered(stamp(query['start']), stamp(query['end_exclusive']))
        public = dict(contract_version=VERSION, query=query, status='partial' if gaps or missing_identity else 'available',
                      scope_version=config['scope_version'], identity_version=config['identity_version'],
                      policy_version=version, lifecycle_policy={'thresholds_days': list(thresholds(query['game'], segments))},
                      data_version=revision, observation_date=observation.isoformat(),
                      config_version=version, config_source=source, timezone='Asia/Shanghai',
                      cohorts=cohorts, stages=stages,
                      coverage=dict(history_start=origin, data_end_exclusive=cutoff.isoformat(),
                                    order_missing_days=gaps, missing_identity_orders=missing_identity,
                                    period_complete=period_complete, identity_deduplication_complete=True,
                                    state_data_through=cutoff.isoformat(),
                                    new_customer_flags=flag_source),
                      publication_id=publication['publication_id'] if publication else None)
        aggregate_only(public)
        members = {group: sorted(ids) for group, ids in {**cohort_members, **stage_members}.items()}
        private = dict(members=members, records=records, segments=segments,
                       jobs=[{key: job[key] for key in ('site', 'start', 'end', 'state')} for job in jobs])
        result = self.store.save_snapshot(query, public, private)
        if flag_source.get('status') != 'unavailable':
            with self.lock:
                if len(self.cache) >= 8:
                    self.cache.popitem(last=False)
                self.cache[cache_key] = result['snapshot_id']
        return result

    def private(self, ident, user, admin):
        self.snapshot(ident, user, admin)
        return self.store.snapshot(ident)

    def members(self, args, user, *, admin=False, export=False):
        fields = {'snapshot_id', 'group'}
        if set(args) - (fields if export else fields | {'limit', 'cursor'}) or not fields <= set(args):
            raise ValueError('v4_member_fields')
        query, public, private = self.private(args['snapshot_id'], user, admin)
        group, limit, cursor = args['group'], args.get('limit', 50), args.get('cursor', '')
        if not isinstance(group, str) or group not in private['members'] or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('v4_member_group_or_limit')
        ids = private['members'][group]
        offset = 0
        if cursor:
            prefix = digest([args['snapshot_id'], group])[:16]
            if not isinstance(cursor, str) or not cursor.startswith(prefix + ':') or cursor.split(':', 1)[1] not in ids:
                raise ValueError('v4_member_cursor')
            offset = ids.index(cursor.split(':', 1)[1]) + 1
        page = ids if export else ids[offset:offset + limit]
        rows = [dict(private['records'][cid]) for cid in page]
        if not admin:
            emails = self.store.emails(page)
            for row in rows:
                row['email'] = emails[row['customer_id']]
        self.authorize(user, query, admin)
        return dict(snapshot_id=public['snapshot_id'], total=len(ids), group=group, rows=rows,
                    next_cursor=(digest([args['snapshot_id'], group])[:16] + ':' + page[-1]
                                 if not export and offset + limit < len(ids) else None))

    def search(self, args, user, *, admin=False):
        if not isinstance(args, dict) or set(args) != {'snapshot_id', 'email'} or not isinstance(args['email'], str):
            raise ValueError('v4_email_fields')
        email = args['email'].strip()
        if len(email) > 320 or not re.fullmatch(r'[^\s@]+@[^\s@]+', email):
            raise ValueError('v4_email')
        ident = args['snapshot_id']
        self.snapshot(ident, user, admin)
        ids = self.store.find_email(email, ['266'])
        if len(ids) == 1:
            try:
                return dict(self.detail(dict(snapshot_id=ident, customer_id=next(iter(ids))), user, admin=admin), found=True)
            except LookupError:
                pass
        self.snapshot(ident, user, admin)
        return dict(snapshot_id=ident, found=False)

    def detail(self, args, user, *, admin=False):
        from customer_segments import is_repeat, stage

        if set(args) != {'snapshot_id', 'customer_id'} or not isinstance(args['customer_id'], str):
            raise ValueError('v4_detail_fields')
        query, public, private = self.private(args['snapshot_id'], user, admin)
        cid = args['customer_id']
        cutoff = stamp(public['coverage']['data_end_exclusive'])
        raw_rows = [row for row in self.store.orders_at(public['data_version'], cid)
                    if row['valid'] and row['site'] == '266' and stamp(public['coverage']['history_start']) <= stamp(row['paid_at']) < cutoff]
        purchases = customer_orders([self.store.analytics_row_v1(row) for row in raw_rows], cutoff).get(cid)
        game = query['game']
        scoped = [order for order in purchases or () if game in ('all', order[2])]
        if not scoped:
            raise LookupError('customer_not_in_snapshot_scope')
        config = private['segments']
        first = purchases[0]
        last = scoped[-1][0]
        covered = complete_coverage(private['jobs'])
        timeline = list(stage_events(scoped, stamp(public['coverage']['history_start']), cutoff, game, config, covered))
        for paid, key, _gid, _body in scoped:
            kind = 'first_order' if key == first[1] else 'repeat' if is_repeat(first[0], paid) else 'purchase'
            timeline.append(dict(at=paid.isoformat(), kind=kind))
        orders = [dict(paid_at=row['paid_at'], project_id=row['gid'], site=row['site'], **json.loads(row['body']))
                  for row in raw_rows if game in ('all', row['gid'])]
        customer = dict(private['records'].get(cid, {}), customer_id=cid, first_paid_at=first[0].isoformat(),
                        last_paid_at=last.isoformat(),
                        stage=stage(last, public['observation_date'], game, config, covered(last, cutoff)))
        begin, end = stamp(query['start']), stamp(query['end_exclusive'])
        for label, matching in (('period', [order for order in scoped if begin <= order[0] < end]),
                                ('covered_history', scoped)):
            totals = amount_summary(matching)
            customer[label + '_orders'] = len(matching)
            customer[label + '_sales_usd'] = totals['known_usd']
            customer[label + '_amount_complete'] = totals['unknown_orders'] == 0
            customer[label + '_unknown_amount_orders'] = totals['unknown_orders']
        self.authorize(user, query, admin)
        return dict(snapshot_id=public['snapshot_id'], customer=customer, orders=orders,
                    email=self.store.email(cid), timeline=sorted(timeline, key=lambda event: event['at']))
