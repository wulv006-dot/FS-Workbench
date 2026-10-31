"""Host-scoped frozen customer investigation. No collector, model or scheduler.

The host supplies identity, one scope and a live validator. The original Service
and authorizer are never mutated. Public snapshot IDs/cursors locate evidence;
they do not grant access. Customer bodies are projected before returning to B2.
"""
import base64
from copy import deepcopy
from datetime import datetime
import json
import re
from time import perf_counter

from user_contract import digest, stamp
from user_query import Service
from user_tools import invoke
from user_weekly import WeeklyUnavailable


def aware(value):
    if not isinstance(value, str):
        raise ValueError('aware_check_time_required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('aware_check_time_required')
    return parsed


def limit_value(limit):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('page_limit')


def opaque(value):
    if not isinstance(value, str) or not re.fullmatch('c_[a-f0-9]{32}', value):
        raise ValueError('opaque_customer_id')
    return value


class QueryContext:
    def __init__(self, service, identity, scope, validate, observation=None):
        self.identity, self.scope, self.validate = identity, deepcopy(scope), validate
        self.observation = deepcopy(observation)
        self.original = service
        self.service = None
        if self.configured():
            self.service = Service(service.store, self.source_authorized, clock=service.clock,
                                   customer_type_reader=service.customer_type_reader,
                                   weekly_publication=service.weekly_publication)

    def configured(self):
        shape = (isinstance(self.identity, str) and bool(self.identity) and callable(self.validate)
                and isinstance(self.scope, dict) and set(self.scope) == {'scope', 'scope_id'}
                and self.scope['scope'] in ('site', 'project')
                and isinstance(self.scope['scope_id'], str) and bool(self.scope['scope_id']))
        return bool(shape and self.scope['scope_id'] in self.original.store.config[
            'sites' if self.scope['scope'] == 'site' else 'projects'])

    def guard(self):
        if not self.configured():
            return False
        if self.validate(self.identity, deepcopy(self.scope)) is not True:
            raise PermissionError('host_scope_revoked')
        return True

    def source_authorized(self, user, query, private=False):
        return (self.guard() and user == self.identity
                and all(query.get(k) == v for k, v in self.scope.items())
                and self.original.authorizer(user, query, private) is True)

    def unavailable(self):
        return {'status': 'unavailable', 'reason': 'trusted_host_scope_required',
                'load': {'service_calls': 0, 'source_rows_scanned': 'unknown'}}

    def public(self, snapshot_id):
        if not isinstance(snapshot_id, str) or not re.fullmatch('us_[a-f0-9]{32}', snapshot_id):
            raise ValueError('snapshot_id')
        value = self.service.query({'snapshot_id': snapshot_id}, self.identity)
        if value.get('requires_global_scope'):
            raise PermissionError('snapshot_requires_global_scope')
        return value

    def receipt(self, public, data, query, started, calls, returned=None):
        fields = ('snapshot_id', 'evidence_id', 'contract_version', 'data_version', 'captured_at',
                  'scope_version', 'identity_version', 'policy_version', 'coverage',
                  'source_watermark', 'weekly_update', 'observation_date', 'query')
        evidence = {k: deepcopy(public[k]) for k in fields if k in public}
        evidence['weekly_cutoff'] = (public.get('weekly_update') or {}).get('cutoff')
        reference = {'scope': deepcopy(self.scope), 'snapshot_id': public['snapshot_id'],
                     'evidence_id': public.get('evidence_id'), 'query': deepcopy(query)}
        result = {'status': public.get('status', 'unknown'), **data, 'source': evidence,
                  'evidence_ref': reference,
                  'missing_fields': ['purchase_cost', 'net_contribution', 'complete_refund_change_cursor'],
                  'load': {'service_calls': calls, 'returned_rows': returned if returned is not None else 'not_applicable',
                           'source_rows_scanned': 'unknown', 'elapsed_ms': round((perf_counter()-started)*1000, 3)}}
        # Only metadata and the bounded projection are measured, not alleged backend scan volume.
        result['load']['response_bytes_before_size_field'] = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
        return result

    def catalog(self):
        if not self.guard():
            return self.unavailable()
        self.original.permit(self.identity, self.scope)
        result = deepcopy(self.original.catalog(self.identity))
        if self.scope['scope'] == 'site':
            result['sites'] = [s for s in result['sites'] if s['id'] == self.scope['scope_id']]
        else:
            result['projects'] = {k: v for k, v in result['projects'].items() if k == self.scope['scope_id']}
        result.update(scope=deepcopy(self.scope), groups=['known_pool', 'entered_silent', 'high_value_entered_silent'],
                      group_order='stable_opaque_customer_id_not_value_rank',
                      query_fields=['start', 'end_exclusive', 'as_of', 'state_basis', 'policy_version', 'policy_mode', 'H'],
                      scope_is_host_authority=True)
        result['can_read_private'] = self.service.authorizer(self.identity, self.scope, True) is True
        return result

    def aggregate(self, query=None, section='summary', snapshot_id=None):
        if not self.guard():
            return self.unavailable()
        started = perf_counter()
        if snapshot_id is not None:
            if query is not None:
                raise ValueError('snapshot_or_query')
            public = self.public(snapshot_id)
        else:
            if not isinstance(query, dict) or set(query) - {'start', 'end_exclusive', 'as_of', 'state_basis', 'policy_version', 'policy_mode', 'H'}:
                raise ValueError('aggregate_query_fields')
            try:
                public = self.service.query(dict(query, **self.scope, view='summary'), self.identity)
            except WeeklyUnavailable:
                return {'status': 'unavailable', 'reason': 'weekly_initial_publication_pending',
                        'load': {'service_calls': 1, 'source_rows_scanned': 'unknown'}}
        # No global/project matrices through a narrower scope, even if a page-level admin can read them.
        if section not in ('summary', 'coverage', 'trend', 'cohort', 'trajectories'):
            raise ValueError('aggregate_section')
        result = invoke(self.service, self.identity, {'snapshot_id': public['snapshot_id'], 'section': section})
        return self.receipt(public, {'data': result}, {'method': 'aggregate', 'section': section}, started, 2)

    def cursor(self, snapshot, kind, fields, after=None, token=None):
        binding = digest({'scope': self.scope, 'snapshot_id': snapshot, 'kind': kind, 'fields': fields})
        if token is None:
            return base64.urlsafe_b64encode(json.dumps({'binding': binding, 'after': after}).encode()).decode().rstrip('=')
        if not isinstance(token, str) or not 1 <= len(token) <= 2048:
            raise ValueError('cursor')
        try:
            value = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True))
        except (ValueError, UnicodeError):
            raise ValueError('cursor') from None
        if not isinstance(value, dict) or set(value) != {'binding', 'after'} or value['binding'] != binding:
            raise ValueError('cursor_query_mismatch')
        return value['after']

    def project(self, row, public):
        coverage, query = public.get('coverage', {}), public['query']
        complete = (coverage.get('period_complete') is True and coverage.get('identity_deduplication_complete') is True
                    and not coverage.get('missing_identity_orders'))
        historical = (complete and coverage.get('historical_origin') is not None
                      and query['state_basis'] != 'period_cohort' and row.get('first_verified') is True
                      and row.get('first_paid_at') is not None)
        purchases = {k: row.get(k) for k in ('period_orders', 'covered_history_orders', 'period_amount_orders',
                     'covered_history_amount_orders', 'period_amount_complete', 'covered_history_amount_complete')}
        for prefix in ('period', 'covered_history'):
            purchases[prefix + '_sales_usd'] = row.get(prefix + '_sales_usd') if row.get(prefix + '_amount_complete') is True else None
        return {'opaque_customer_id': opaque(row['customer_id']),
                'first_paid': {'at': row.get('first_paid_at') if historical else None,
                               'basis': 'verified_historical_first_purchase' if historical else 'unknown',
                               'complete': historical, 'missing': not historical},
                'observed_first': {'at': row.get('earliest_observed_at'), 'complete': False,
                                   'missing': row.get('earliest_observed_at') is None,
                                   'basis': 'selected_period_first_seen' if query['state_basis'] == 'period_cohort' else 'covered_history_first_seen'},
                'last_paid': {'at': row.get('last_paid_at'), 'complete': complete and row.get('stage') != 'unverified',
                              'missing': row.get('last_paid_at') is None,
                              'basis': 'last_effective_purchase_in_source_scope'},
                'purchases': purchases, 'amount_unit': 'USD', 'amount_basis': 'whole_order_sales_not_net_contribution',
                'stage': row.get('stage', 'unverified'),
                'identity_reliability': {'complete': coverage.get('identity_deduplication_complete') is True,
                                         'missing_identity_orders': coverage.get('missing_identity_orders')},
                'refund_review': {'status': 'requires_review', 'coverage': coverage.get('refund_correction')}}

    def candidates(self, snapshot_id, group='known_pool', cursor=None, limit=50):
        if not self.guard():
            return self.unavailable()
        limit_value(limit)
        if group not in ('known_pool', 'entered_silent', 'high_value_entered_silent'):
            raise ValueError('candidate_group')
        started = perf_counter()
        public = self.public(snapshot_id)
        fields = {'group': group}
        after = self.cursor(snapshot_id, 'candidates', fields, token=cursor) if cursor is not None else ''
        if not isinstance(after, str):
            raise ValueError('candidate_cursor')
        if after:
            opaque(after)
        page = self.service.members({'snapshot_id': snapshot_id, 'group': group, 'cursor': after, 'limit': limit}, self.identity)
        rows = [self.project(row, public) for row in page['rows']]
        next_cursor = self.cursor(snapshot_id, 'candidates', fields, page['next_cursor']) if page['next_cursor'] else None
        return self.receipt(public, {'rows': rows, 'total': page['total'], 'returned': len(rows),
                            'next_cursor': next_cursor, 'complete': cursor is None and next_cursor is None,
                            'selection_basis': (deepcopy(public.get('value_segment')) if group == 'high_value_entered_silent'
                                                else {'basis': 'source_defined_group'}),
                            'coverage_scope': 'selected_group_query', 'order': 'stable_opaque_customer_id'},
                            {'method': 'candidates', **fields, 'cursor': cursor, 'limit': limit}, started, 2, len(rows))

    def timeline(self, snapshot_id, opaque_customer_id, cursor=None, limit=50):
        if not self.guard():
            return self.unavailable()
        limit_value(limit)
        opaque(opaque_customer_id)
        started = perf_counter()
        public = self.public(snapshot_id)
        detail = self.service.detail({'snapshot_id': snapshot_id, 'customer_id': opaque_customer_id}, self.identity)
        fields = {'opaque_customer_id': opaque_customer_id}
        offset = self.cursor(snapshot_id, 'timeline', fields, token=cursor) if cursor is not None else 0
        events = detail['timeline']
        if type(offset) is not int or not 0 <= offset <= len(events):
            raise ValueError('timeline_cursor')
        end = min(len(events), offset + limit)
        projected = [{key: event.get(key) for key in ('at', 'kind', 'stage')} for event in events[offset:end]]
        return self.receipt(public, {'customer': self.project(detail['customer'], public), 'events': projected,
                            'total': len(events), 'returned': len(projected), 'offset': offset,
                            'next_cursor': self.cursor(snapshot_id, 'timeline', fields, end) if end < len(events) else None,
                            'complete': offset == 0 and end == len(events), 'coverage_scope': 'selected_customer_timeline'},
                            {'method': 'timeline', **fields, 'cursor': cursor, 'limit': limit}, started, 2, len(projected))

    def changes_due(self, baseline_snapshot_id, current_snapshot_id, observation_at, explicit_refs):
        if not self.guard():
            return self.unavailable()
        # This is a trusted host observation plan, never a newly scheduled model request.
        if not isinstance(self.observation, dict) or set(self.observation) != {'observation_at', 'checks'}:
            return {'status': 'unavailable', 'reason': 'trusted_observation_plan_required'}
        at = aware(observation_at)
        if at != aware(self.observation['observation_at']):
            raise PermissionError('observation_plan_mismatch')
        if not isinstance(explicit_refs, list) or len(explicit_refs) > 200:
            raise ValueError('explicit_refs')
        refs = []
        for ref in explicit_refs:
            if not isinstance(ref, dict) or set(ref) != {'opaque_customer_id', 'snapshot_id'}:
                raise ValueError('explicit_reference')
            cid = opaque(ref['opaque_customer_id'])
            if ref['snapshot_id'] not in (baseline_snapshot_id, current_snapshot_id) or cid in refs:
                raise ValueError('explicit_reference')
            if cid not in self.observation['checks']:
                raise PermissionError('customer_not_in_observation_plan')
            refs.append(cid)
        started = perf_counter()
        baseline, current = self.public(baseline_snapshot_id), self.public(current_snapshot_id)
        keys = ('contract_version', 'scope_version', 'identity_version', 'policy_version', 'lifecycle_policy')
        qkeys = ('scope', 'scope_id', 'start', 'state_basis', 'policy_mode', 'H')
        compatible = (all(baseline.get(k) is not None and baseline.get(k) == current.get(k) for k in keys)
                      and all(baseline['query'].get(k) == current['query'].get(k) for k in qkeys)
                      and stamp(baseline['query']['as_of']) <= stamp(current['query']['as_of']))
        query = {'method': 'changes_due', 'baseline_snapshot_id': baseline_snapshot_id,
                 'current_snapshot_id': current_snapshot_id, 'observation_at': observation_at, 'explicit_refs': deepcopy(explicit_refs)}
        if not compatible:
            return self.receipt(current, {'status': 'incomparable', 'changes': [],
                                         'baseline_evidence_ref': {'snapshot_id': baseline_snapshot_id, 'evidence_id': baseline.get('evidence_id')}}, query, started, 2)
        coverage = current.get('coverage', {})
        cutoffs = [current['query']['as_of'], coverage.get('state_data_through'), (current.get('weekly_update') or {}).get('cutoff')]
        through = min(stamp(v) for v in cutoffs if v is not None)
        fresh = (through >= at and current.get('status') == 'available' and coverage.get('period_complete') is True
                 and coverage.get('identity_deduplication_complete') is True and not coverage.get('missing_identity_orders'))
        changes, calls = [], 2
        for cid in refs:
            check = self.observation['checks'][cid]
            if not isinstance(check, dict) or set(check) - {'recheck_at', 'expected_next_purchase_at'} or not check:
                raise ValueError('observation_check')
            checkpoint = min(aware(value) for value in check.values())
            try:
                calls += 1
                before = self.service.detail({'snapshot_id': baseline_snapshot_id, 'customer_id': cid}, self.identity)['customer']
                calls += 1
                after = self.service.detail({'snapshot_id': current_snapshot_id, 'customer_id': cid}, self.identity)['customer']
            except LookupError:
                changes.append({'opaque_customer_id': cid, 'status': 'requires_review', 'reason': 'customer_not_in_both_snapshots'})
                continue
            old, new = self.project(before, baseline), self.project(after, current)
            changed = [key for key in ('first_paid', 'last_paid', 'purchases', 'stage', 'identity_reliability') if old[key] != new[key]]
            if at < checkpoint:
                status = 'not_due'
            elif not fresh:
                status = 'refresh_required'
            elif not old['last_paid']['at'] or not new['last_paid']['complete'] or not new['last_paid']['at']:
                status = 'insufficient_evidence'
            else:
                regressed = stamp(new['last_paid']['at']) < stamp(old['last_paid']['at']) or any(
                    type(old['purchases'].get(k)) is int and type(new['purchases'].get(k)) is int
                    and new['purchases'][k] < old['purchases'][k] for k in ('period_orders', 'covered_history_orders'))
                status = ('requires_review' if regressed else
                          'due_with_new_purchase' if stamp(new['last_paid']['at']) > stamp(old['last_paid']['at'])
                          else 'due_no_new_purchase_observed')
            changes.append({'opaque_customer_id': cid, 'status': status, 'changed_fields': changed,
                            'before': old, 'after': new, 'checkpoint': checkpoint.isoformat(),
                            'checks': {name: {'at': value, 'due': at >= aware(value)} for name, value in check.items()},
                            'review_required': ['refund_corrections', 'purchase_cost_missing', 'identity_changes_if_any']})
        return self.receipt(current, {'changes': changes, 'freshness': {'status': 'sufficient' if fresh else 'insufficient_freshness',
                            'snapshot_cutoff': through.isoformat(), 'observation_at': observation_at},
                            'baseline_evidence_ref': {'scope': deepcopy(self.scope), 'snapshot_id': baseline_snapshot_id,
                                                      'evidence_id': baseline.get('evidence_id')}}, query, started, calls, len(changes))


def context_factory(service, identity=None, allowed_scope=None, validate=None, observation=None):
    return QueryContext(service, identity, allowed_scope, validate, observation)
