"""B consumption of authorized A2 frozen receipts, not a query/auth backend.

No model, customer database, scheduler, action writer or automatic retry. The
host supplies an A2 context, explicit customer references and a page budget.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re

from b2_customer_followup import Observation, assess, moment


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def aware(value):
    if not isinstance(value, str):
        raise ValueError('source_time_required')
    return moment(datetime.fromisoformat(value.replace('Z', '+00:00')))


def cutoff(source):
    values = [source['query']['as_of'], source.get('coverage', {}).get('state_data_through'),
              source.get('weekly_cutoff')]
    return min(aware(v) for v in values if v is not None)


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('c_[a-f0-9]{32}', value):
        raise ValueError('opaque_customer_id')
    return value


def page_limits(page_budget, limit):
    if type(page_budget) is not int or page_budget < 1 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('page_budget_or_limit')


def source_key(source):
    fields = ('snapshot_id', 'evidence_id', 'data_version', 'scope_version',
              'identity_version', 'policy_version', 'contract_version', 'query',
              'coverage', 'weekly_cutoff')
    if any(source.get(k) is None for k in fields[:7]):
        raise ValueError('frozen_source_identity')
    return encoded({k: source.get(k) for k in fields})


def page_chain(context, *, method, snapshot_id, page_budget, limit=200, cursor=None, **selection):
    """Consume a bounded chain; a tail alone can never establish whole coverage.

    Items are temporary authorized projections. The final investigation emits
    only selected decisions and compact replayable references, never all rows.
    """
    page_limits(page_budget, limit)
    if method not in ('candidates', 'timeline'):
        raise ValueError('page_method')
    started = cursor is None
    items, seen, references = [], set(), []
    total = signature = source = None
    source_status = 'unknown'
    load = {'service_calls': 0, 'response_bytes': 0, 'source_rows_scanned': 'unknown'}
    first = last = None
    chain_digest = hashlib.sha256()
    for _ in range(page_budget):
        marker = encoded(cursor)
        if marker in seen:
            raise ValueError('cursor_cycle')
        seen.add(marker)
        try:
            page = getattr(context, method)(snapshot_id, cursor=cursor, limit=limit, **selection)
        except PermissionError:
            raise
        except (TimeoutError, ConnectionError, OSError):
            page = {'status': 'unknown'}
        if page.get('status') not in ('available', 'partial'):
            return {'status': page.get('status', 'unknown'), 'items': items,
                    'coverage': {'started_from_beginning': started, 'enumeration_complete': False,
                                 'observed': len(items), 'total': total,
                                 'pages': len(references), 'next_cursor': cursor}, 'source': source,
                    'evidence': {'first': first, 'last': last, 'pages': len(references),
                                 'chain_sha256': chain_digest.hexdigest()} if references else None,
                    'load': load}
        current = page['source']
        key = source_key(current)
        if current['snapshot_id'] != snapshot_id or (signature is not None and key != signature):
            raise ValueError('frozen_source_changed')
        reference = page['evidence_ref']
        expected = {'method': method, **selection, 'cursor': cursor, 'limit': limit}
        if (reference.get('snapshot_id') != snapshot_id or reference.get('evidence_id') != current['evidence_id']
                or reference.get('query') != expected or reference.get('scope') != {
                    k: current['query'][k] for k in ('scope', 'scope_id')}):
            raise ValueError('page_reference_mismatch')
        rows = page['rows' if method == 'candidates' else 'events']
        n, returned, following = page['total'], page['returned'], page['next_cursor']
        if (type(n) is not int or n < 0 or type(returned) is not int or not isinstance(rows, list)
                or returned != len(rows) or not 0 <= returned <= limit
                or (total is not None and n != total) or len(items) + returned > n
                or (following is not None and (not isinstance(following, str) or not following or not rows))):
            raise ValueError('page_count_contract')
        if method == 'candidates':
            ids = [identity(row['opaque_customer_id']) for row in rows]
            previous = items[-1]['opaque_customer_id'] if items else None
            if ids != sorted(set(ids)) or (ids and previous is not None and ids[0] <= previous):
                raise ValueError('candidate_order_or_duplicate')
        elif (type(page.get('offset')) is not int or (started and page['offset'] != len(items))):
            raise ValueError('timeline_offset_gap')
        signature, source, total = key, deepcopy(current), n
        source_status = page['status']
        first = first or deepcopy(reference)
        last = deepcopy(reference)
        chain_digest.update(encoded(reference).encode())
        references.append(reference)
        items.extend(deepcopy(rows))
        load['service_calls'] += page.get('load', {}).get('service_calls', 0)
        load['response_bytes'] += page.get('load', {}).get('response_bytes_before_size_field', 0)
        cursor = following
        if following is None:
            break
    complete = started and cursor is None and len(items) == total
    if started and cursor is None and not complete:
        raise ValueError('terminal_page_missing_rows')
    coverage = {'started_from_beginning': started, 'enumeration_complete': complete,
                'observed': len(items), 'total': total, 'pages': len(references), 'next_cursor': cursor}
    evidence = {'first': first, 'last': last, 'pages': len(references),
                'chain_sha256': chain_digest.hexdigest()}
    return {'status': 'available' if complete and source_status == 'available' else 'partial',
            'items': items, 'source': source, 'coverage': coverage, 'evidence': evidence, 'load': load}


def handoff_reference(source, reference, coverage, missing):
    """Use original us_/ua_ with scope/query/cursors; no new evidence ledger."""
    return {'ref': encoded(reference), 'source': 'authorized_frozen_user_analytics',
            'as_of': cutoff(source).isoformat(),
            'version': encoded({k: source.get(k) for k in (
                'data_version', 'scope_version', 'identity_version', 'policy_version', 'contract_version')}),
            'coverage': encoded(coverage), 'missing': sorted(set(missing))}


class _Meter:
    def __init__(self, context):
        self.context = context
        self.load = {'context_calls': {}, 'response_bytes': 0, 'source_rows_scanned': 'unknown'}

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.load['context_calls'][name] = self.load['context_calls'].get(name, 0) + 1
            value = getattr(self.context, name)(*args, **kwargs)
            self.load['response_bytes'] += len(encoded(value).encode())
            return value
        return call


def followup(change, source, *, now, observation_anchor):
    row = change.get('after')
    checks = change.get('checks', {})
    if not isinstance(row, dict) or 'recheck_at' not in checks:
        return {'state': 'needs_evidence', 'reason': 'projected_history_or_recheck_required'}
    identity_info, last, first = row['identity_reliability'], row['last_paid'], row['first_paid']
    coverage = source.get('coverage', {})
    known = (source.get('query') is not None and coverage.get('period_complete') is True
             and last.get('complete') is True)
    missing = []
    if not known:
        missing.append('incomplete_payment_history')
    if change['status'] == 'requires_review':
        missing.append('source_correction_requires_review')
    verified_first = (first.get('complete') is True and first.get('basis') == 'verified_historical_first_purchase'
                      and first.get('missing') is False and first.get('at') is not None)
    through = cutoff(source)
    latest_at = aware(last['at']) if last.get('at') else None
    first_at = aware(first['at']) if verified_first else None
    if latest_at is not None and latest_at > through:
        latest_at, known = None, False
        missing.append('payment_outside_conservative_cutoff')
    if first_at is not None and (latest_at is None or first_at > latest_at):
        first_at, known = None, False
        missing.append('history_order_not_verified_within_cutoff')
    observation = Observation(
        evidence_ref=source['evidence_id'], source='authorized_frozen_user_analytics',
        version=str(source['data_version']), as_of=through, complete=known,
        identity_verified=identity_info.get('complete') is True and identity_info.get('missing_identity_orders') == 0,
        missing=tuple(missing), first_paid_at=first_at, latest_paid_at=latest_at,
        refund_review_needed=row.get('refund_review', {}).get('status') != 'verified')
    return assess(observation, now=now, observation_anchor=observation_anchor,
                  recheck_at=aware(checks['recheck_at']['at']),
                  expected_next_purchase_at=aware(checks['expected_next_purchase_at']['at'])
                  if 'expected_next_purchase_at' in checks else None)


def investigate(context, *, request_id, baseline_snapshot_id, current_snapshot_id,
                observation_at, observation_anchor, now, customer_ids, page_budget, limit=200,
                group='known_pool', goal_active=True):
    """One host-requested frozen investigation, no model or business execution.

    Explicit IDs identify necessary drill-downs, not a hidden high-value rank.
    A's scoped context independently authorizes every call and observation plan.
    """
    if not isinstance(request_id, str) or not request_id.strip() or type(goal_active) is not bool:
        raise ValueError('investigation_identity')
    page_limits(page_budget, limit)
    if not isinstance(customer_ids, list) or len(customer_ids) > 200:
        raise ValueError('explicit_customer_ids')
    ids = [identity(cid) for cid in customer_ids]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate_customer_ids')
    checked_at, now, anchor = aware(observation_at), moment(now), moment(observation_anchor)
    if anchor > now or checked_at > now:
        raise ValueError('future_observation_anchor')
    context = _Meter(context)
    result = {'request_id': request_id, 'business_write_performed': False,
              'model_call_performed': False, 'retry_allowed': False,
              'options': [{'action': 'no_intervention', 'reason': 'No business action is performed'}],
              'verification': 'local_contract_only', 'decisions': [], 'evidence': [],
              'observation_at': observation_at, 'evaluated_at': now.isoformat(), 'load': context.load}
    if not goal_active:
        return dict(result, status='stopped')
    try:
        catalog = context.catalog()
        if catalog.get('status') == 'unavailable' or catalog.get('can_read_private') is not True:
            return dict(result, status='unavailable')
        aggregate = context.aggregate(snapshot_id=current_snapshot_id)
        if aggregate.get('status') not in ('available', 'partial'):
            return dict(result, status=aggregate.get('status', 'unknown'))
        source = aggregate['source']
        source_key(source)
        if (source['snapshot_id'] != current_snapshot_id or cutoff(source) > now
                or {k: source['query'][k] for k in ('scope', 'scope_id')} != catalog['scope']):
            raise ValueError('aggregate_snapshot_mismatch')
        result['source_as_of'] = cutoff(source).isoformat()
        result['evidence'].append(handoff_reference(source, aggregate['evidence_ref'],
                                                   {'scope': 'frozen_summary'}, aggregate['missing_fields']))
        baseline = (aggregate if baseline_snapshot_id == current_snapshot_id else
                    context.aggregate(snapshot_id=baseline_snapshot_id))
        if baseline.get('status') not in ('available', 'partial'):
            return dict(result, status=baseline.get('status', 'unknown'))
        previous = baseline['source']
        source_key(previous)
        if (previous['snapshot_id'] != baseline_snapshot_id or cutoff(previous) > now
                or {k: previous['query'][k] for k in ('scope', 'scope_id')} != catalog['scope']):
            raise ValueError('baseline_snapshot_mismatch')
        result['evidence'].append(handoff_reference(previous, baseline['evidence_ref'],
                                                   {'scope': 'frozen_baseline'}, baseline['missing_fields']))
        candidates = page_chain(context, method='candidates', snapshot_id=current_snapshot_id,
                                page_budget=page_budget, limit=limit, group=group)
        result['candidate_coverage'] = candidates['coverage']
        if candidates['evidence'] is None:
            return dict(result, status=candidates['status'])
        if source_key(candidates['source']) != source_key(source):
            raise ValueError('candidate_snapshot_changed')
        missing = list(aggregate['missing_fields'])
        if not candidates['coverage']['enumeration_complete']:
            missing.append('candidate_pages_unread')
        result['evidence'].append(handoff_reference(source, candidates['evidence'], candidates['coverage'], missing))
        if candidates['status'] not in ('available', 'partial'):
            return dict(result, status=candidates['status'])
        for cid in ids:
            try:
                timeline = page_chain(context, method='timeline', snapshot_id=current_snapshot_id,
                                      page_budget=page_budget, limit=limit, opaque_customer_id=cid)
            except LookupError:
                timeline = {'status': 'missing', 'coverage': {'enumeration_complete': False}}
            result['decisions'].append({'opaque_customer_id': cid, 'timeline_coverage': timeline['coverage']})
            if timeline.get('evidence') is not None:
                if source_key(timeline['source']) != source_key(source):
                    raise ValueError('timeline_snapshot_changed')
                result['evidence'].append(handoff_reference(source, timeline['evidence'], timeline['coverage'],
                    missing + ([] if timeline['coverage']['enumeration_complete'] else ['timeline_pages_unread'])))
            if timeline['status'] not in ('available', 'partial', 'missing'):
                return dict(result, status=timeline['status'])
        changes = context.changes_due(baseline_snapshot_id, current_snapshot_id, observation_at,
                                     [{'opaque_customer_id': cid, 'snapshot_id': baseline_snapshot_id} for cid in ids])
        result['comparison_status'] = changes.get('status', 'unknown')
        if changes.get('status') not in ('available', 'partial'):
            return dict(result, status=changes.get('status', 'unknown'))
        if source_key(changes['source']) != source_key(source):
            raise ValueError('comparison_snapshot_changed')
        old_ref = changes.get('baseline_evidence_ref', {})
        if (old_ref.get('snapshot_id') != baseline_snapshot_id
                or old_ref.get('evidence_id') != previous['evidence_id'] or old_ref.get('scope') != catalog['scope']):
            raise ValueError('comparison_baseline_mismatch')
        observations = changes['changes']
        if len(observations) != len(ids) or {r['opaque_customer_id'] for r in observations} != set(ids):
            raise ValueError('comparison_customer_mismatch')
        by_id = {row['opaque_customer_id']: row for row in observations}
        for decision in result['decisions']:
            change = by_id[decision['opaque_customer_id']]
            limits = missing + ([] if decision['timeline_coverage']['enumeration_complete'] else ['timeline_pages_unread'])
            next_step = {
                'refresh_required': 'obtain_an_authorized_snapshot_covering_the_checkpoint',
                'requires_review': 'verify_corrections_and_identity_before_intervention',
                'insufficient_evidence': 'obtain_missing_payment_history',
                'due_no_new_purchase_observed': 'investigate_cadence_and_service_context',
                'due_with_new_purchase': 'review_observed_purchase_and_followup_frequency',
                'not_due': 'wait_for_the_explicit_checkpoint',
            }.get(change['status'], 'review_missing_evidence')
            decision.update(payment_observation=change['status'], changed_fields=change.get('changed_fields', []),
                            followup=followup(change, source, now=now, observation_anchor=anchor),
                            limits=limits, causal_effect='unknown', net_contribution='unknown',
                            next_step=next_step, options=['no_intervention', 'investigate_evidence'])
        result['evidence'].append(handoff_reference(source, changes['evidence_ref'], changes['freshness'], missing))
        complete = (candidates['coverage']['enumeration_complete'] and
                    all(d['timeline_coverage']['enumeration_complete'] for d in result['decisions']))
        return dict(result, status='observed_with_limits' if complete else 'partial')
    except PermissionError:
        raise  # Never return already read private results after a live revocation.
    except (TimeoutError, ConnectionError, OSError):
        return dict(result, status='unknown', reason='source_outcome_unknown')
