"""Frozen user-analysis queries for the dashboard and authorized model consumers."""
from bisect import bisect_right
from collections import OrderedDict
import csv
from datetime import date, time, timedelta
from io import StringIO
import json
import re
from threading import RLock

from user_contract import TZ, aggregate_only, digest, stamp
from user_lifecycle import (analyze_cohorts, analyze_stages, complete_coverage,
                            amount_summary, customer_orders, stage_events)
from user_summary_jobs import SummaryJobs
from user_member_index import IndexUnavailable, build as build_member_index, member_record, page as indexed_member_page

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


def project_scope(game):
    if game != 'all':
        return dict(scope='project', scope_id=game)
    return dict(scope='global', scope_id='')


def authorization_scope(args, game):
    if args.get('scope') == 'site':
        return dict(scope='site', scope_id='266')
    if args.get('scope') == 'global':
        return dict(scope='global', scope_id='')
    return project_scope(game)


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
    return dict(authorization_scope(args, game), game=game, start=start.isoformat(), end_exclusive=end.isoformat(),
                cohort_start=cohort_start, cohort_end=cohort_end, windows=windows,
                return_after=after, return_within=within, customer_type=customer_type, repeat_status=repeat_status)


def section_result(value, section):
    if section not in SECTIONS:
        raise ValueError('v4_section')
    if section == 'summary':
        return value
    result = {key: part for key, part in value.items() if key not in ('cohorts', 'stages') or key == section}
    if section in ('cohorts', 'stages') and 'status' in result[section]:
        result['status'] = result[section]['status']
    return result


def member_csv(rows, cohort, budget):
    columns = ['邮箱', '客户 ID', '站内首单', '末次购买', '阶段']
    if cohort:
        columns.extend(['时间窗状态', '计入分子'])
    stage_names = {'recent': '近期', 'silent': '沉默', 'lost': '流失', 'long_lost': '长期流失', 'unverified': '待核'}
    window_names = {'denominator': '已满窗（分母）', 'observing': '观察中', 'coverage_gap': '覆盖缺口'}
    line = StringIO(newline='')
    writer = csv.writer(line, quoting=csv.QUOTE_ALL)
    output = StringIO(newline='')
    output.write('\ufeff')
    size = 3

    def write(parts):
        nonlocal size
        line.seek(0)
        line.truncate()
        writer.writerow(parts)
        text = line.getvalue()
        size += len(text.encode('utf-8'))
        if size > budget:
            raise IndexUnavailable('streaming_export_budget_exhausted')
        output.write(text)

    write(columns)
    for row in rows:
        email = row['email']
        if re.match(r'^\s*[=+\-@\t\r\n]', email):
            email = "'" + email
        parts = [email, row['customer_id'], row.get('first_paid_at'),
                 row.get('last_paid_at'), stage_names.get(row.get('stage'))]
        if cohort:
            included = row.get('in_numerator')
            parts.extend([window_names.get(row.get('window_status')),
                          '' if included is None else '是' if included else '否'])
        write(parts)
    return output.getvalue()


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
            self.authorize(user, authorization_scope(args, game))
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
        detail_customer_types = {}
        game = query['game']
        for cid, purchases in people.items():
            if cid in records:
                continue
            flag = flags.get(purchases[0][3]['order_no_hash'])
            if flag in ('new', 'old') and (game == 'all' or any(order[2] == game for order in purchases)):
                detail_customer_types[cid] = flag
        query['as_of'] = cutoff.isoformat()
        period_complete = covered(stamp(query['start']), stamp(query['end_exclusive']))
        flag_status = flag_source.get('status')
        if flag_status not in ('complete', 'partial', 'unavailable'):
            flag_status = 'unavailable'
        cohorts.update(customer_type_source=flag_status,
                       status='partial' if gaps or missing_identity or flag_status != 'complete' else 'available')
        stages['status'] = ('partial' if not period_complete or missing_identity or stage_members['stage:unverified']
                            else 'available')
        public = dict(contract_version=VERSION, query=query,
                      status='partial' if 'partial' in (cohorts['status'], stages['status']) else 'available',
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
        if detail_customer_types:
            # Bind the new private evidence to its own immutable snapshot ID.
            public['detail_customer_type_revision'] = digest(detail_customer_types)
        aggregate_only(public)
        members = {group: sorted(ids) for group, ids in {**cohort_members, **stage_members}.items()}
        private = dict(members=members, records=records, segments=segments,
                       cohort_memberships=cohort_members,
                       jobs=[{key: job[key] for key in ('site', 'start', 'end', 'state')} for job in jobs])
        if detail_customer_types:
            private['detail_customer_types'] = detail_customer_types
        result = self.store.save_snapshot(query, public, private)
        if self.store.config.get('member_keyset_index') is True:
            build_member_index(self.store, result, private)
        if flag_status != 'unavailable':
            with self.lock:
                if len(self.cache) >= 8:
                    self.cache.popitem(last=False)
                self.cache[cache_key] = result['snapshot_id']
        return result

    def private(self, ident, user, admin):
        self.snapshot(ident, user, admin)
        return self.store.snapshot(ident)

    def members(self, args, user, *, admin=False):
        fields = {'snapshot_id', 'group'}
        if set(args) - (fields | {'limit', 'cursor'}) or not fields <= set(args):
            raise ValueError('v4_member_fields')
        query, public = self.snapshot(args['snapshot_id'], user, admin)
        private = None
        if self.store.config.get('member_keyset_index') is not True:
            _, _, private = self.store.snapshot(args['snapshot_id'])
        return self.member_page(args, user, query, public, private, admin=admin)

    def member_page(self, args, user, query, public, private, *, admin=False):
        group, limit, cursor = args['group'], args.get('limit', 50), args.get('cursor', '')
        if not isinstance(group, str) or not isinstance(cursor, str) or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('v4_member_group_or_limit')
        self.authorize(user, query, admin)
        if private is None:
            request = dict(args)
            if not cursor:
                request.pop('cursor', None)
            epoch = self.service.export_epoch(user, query)
            value = indexed_member_page(self.store, query, public, request, user, epoch)
        else:
            if group not in private['members']:
                raise ValueError('v4_member_group_or_limit')
            ids = private['members'][group]
            offset = 0
            prefix = digest([args['snapshot_id'], group])[:16]
            if cursor:
                context, _, previous = cursor.partition(':')
                offset = bisect_right(ids, previous)
                if context != prefix or not offset or ids[offset - 1] != previous:
                    raise ValueError('v4_member_cursor')
            selected = ids[offset:offset + limit]
            value = dict(snapshot_id=public['snapshot_id'], total=len(ids), group=group,
                         rows=[dict(member_record(private, group, cid)) for cid in selected],
                         next_cursor=prefix + ':' + selected[-1] if offset + limit < len(ids) else None)
        if not admin:
            emails = self.store.emails([row['customer_id'] for row in value['rows']])
            for row in value['rows']:
                row['email'] = emails[row['customer_id']]
        self.authorize(user, query, admin)
        return {key: value[key] for key in ('snapshot_id', 'total', 'group', 'rows', 'next_cursor')}

    def export(self, args, user):
        if set(args) != {'snapshot_id', 'group'} or not isinstance(args['group'], str):
            raise ValueError('v4_member_fields')
        query, public = self.snapshot(args['snapshot_id'], user)
        epoch = self.service.export_epoch(user, query)
        private = None
        if self.store.config.get('member_keyset_index') is not True:
            _, _, private = self.store.snapshot(args['snapshot_id'])

        def read_page(request):
            if self.service.export_epoch(user, query) != epoch:
                raise PermissionError('export_permission_changed')
            return self.member_page(request, user, query, public, private)

        cohort = args['group'].startswith('cohort:')
        completion = {}
        rows = self.service.stream_export_rows(args, read_page, completion)
        content = member_csv(rows, cohort, self.service.export_budget())
        # The authenticated JSON host delivers this single bounded CSV in the
        # current response. Publish only after the last live grant/epoch check.
        with self.service.export_publication_lock:
            self.authorize(user, query)
            if self.service.export_epoch(user, query) != epoch:
                raise PermissionError('export_permission_changed')
            return dict(snapshot_id=public['snapshot_id'], group=args['group'],
                        exported_rows=completion['rows'], csv=content)

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
        if 'customer_type' not in customer:
            customer['customer_type'] = private.get('detail_customer_types', {}).get(cid, 'unknown')
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
