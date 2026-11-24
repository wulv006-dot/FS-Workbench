"""B2 consumer of minimal, authorized A2 observation summaries.

Reads use only the host's existing A2 context. No scheduler, customer database,
model calls or business actions. A owns identity/scope validation and aggregation.
This module cannot authorize access or turn an evidence locator into a grant.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from copy import deepcopy
import re

BEIJING = timezone(timedelta(hours=8))


def moment(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_datetime_required")
    return value


@dataclass(frozen=True)
class Observation:
    evidence_ref: str
    source: str
    version: str
    as_of: datetime
    complete: bool
    identity_verified: bool
    missing: tuple = ()
    first_paid_at: datetime = None
    latest_paid_at: datetime = None
    refund_review_needed: bool = False


def observation_from_a2(receipt, *, now):
    """Consume the current host QueryContext projection, never authorize a locator.

    A timeline page's complete flag describes its event slice, not history.
    Read time is not the source cutoff, and a period first-seen is not Day0.
    Live-order pages are a different, non-snapshot contract and cannot enter here.
    """
    moment(now)
    if (type(receipt) is not dict or receipt.get('status') not in ('available', 'partial')
            or type(receipt.get('source')) is not dict or type(receipt.get('customer')) is not dict):
        raise ValueError('a2_customer_receipt')
    source, customer = receipt['source'], receipt['customer']
    if (type(source.get('query')) is not dict or type(source.get('coverage')) is not dict
            or not re.fullmatch(r'c_[a-f0-9]{32}', customer.get('opaque_customer_id', ''))):
        raise ValueError('a2_customer_receipt')
    query, coverage = source['query'], source['coverage']
    def at(value):
        if type(value) is not str:
            raise ValueError('a2_source_time')
        try:
            result = moment(datetime.fromisoformat(value.replace('Z', '+00:00')))
        except ValueError:
            raise ValueError('a2_source_time') from None
        if result > now:
            raise ValueError('future_observation')
        return result
    cutoffs = [at(query.get('as_of'))]
    for value in (coverage.get('state_data_through'), source.get('weekly_cutoff')):
        if value is not None:
            cutoffs.append(at(value))
    through = min(cutoffs)
    identity = (coverage.get('identity_deduplication_complete') is True
                and type(coverage.get('missing_identity_orders')) is int
                and coverage['missing_identity_orders'] == 0)
    complete = (receipt['status'] == 'available' and coverage.get('period_complete') is True
                and coverage.get('state_data_through') is not None and identity)
    first, last = customer.get('first_paid', {}), customer.get('last_paid', {})
    if type(first) is not dict or type(last) is not dict:
        raise ValueError('a2_customer_receipt')
    first_known = complete and first.get('complete') is True and first.get('missing') is False
    if source.get('contract_version') == 'fs-users-v4':
        first_verified = (first_known and bool(coverage.get('history_start'))
                          and first.get('basis') == 'es_new_customer_at_first_observed_site_order')
    else:
        first_verified = (first_known and coverage.get('historical_origin') is not None
                          and query.get('state_basis') != 'period_cohort'
                          and first.get('basis') == 'verified_historical_first_purchase')
    first_at = at(first['at']) if first_verified and first.get('at') is not None else None
    last_at = at(last['at']) if last.get('at') is not None else None
    if ((first_at is not None and (last_at is None or first_at > last_at))
            or last_at is not None and last_at > through):
        raise ValueError('purchase_after_source_cutoff')
    ref, version = source.get('evidence_id'), source.get('data_version')
    if not isinstance(ref, str) or not re.fullmatch(r'ua_[a-f0-9]{32}', ref) or version is None:
        raise ValueError('a2_evidence_identity')
    missing = tuple(receipt.get('missing_fields', ()))
    if any(type(value) is not str for value in missing):
        raise ValueError('missing_fields')
    return Observation(ref, 'FS/A2/frozen_customer', str(version), through, complete, identity,
                       missing=missing, first_paid_at=first_at, latest_paid_at=last_at,
                       refund_review_needed=customer.get('refund_review', {}).get('status') != 'complete')


def describe_customer(context, *, snapshot_id, customer_id, now):
    """Ordinary read-only analysis through a host-injected, live-authorized A2 context.

    No owner argument, HTTP client, collection, task, goal or schedule is created.
    Explicit follow-up may pass observation_from_a2 to existing assess/GoalState.
    """
    receipt = context.timeline(snapshot_id, customer_id, limit=1)
    if receipt.get('status') == 'unavailable':
        return {'status': 'unavailable', 'reason': 'trusted_customer_context_required',
                'business_write_performed': False}
    observation = observation_from_a2(receipt, now=now)
    customer, source = receipt['customer'], receipt['source']
    if customer['opaque_customer_id'] != customer_id or source.get('snapshot_id') != snapshot_id:
        raise PermissionError('customer_projection_mismatch')
    limitations = list(observation.missing)
    if observation.first_paid_at is None:
        limitations.append('historical_first_purchase_unverified')
    if not observation.complete:
        limitations.append('partial_source_history')
    if not observation.identity_verified:
        limitations.append('identity_unresolved')
    if observation.refund_review_needed:
        limitations.append('refund_corrections_require_review')
    purchases = customer.get('purchases', {})
    facts = {key: deepcopy(purchases.get(key)) for key in
             ('period_orders', 'covered_history_orders', 'period_sales_usd', 'covered_history_sales_usd')}
    facts.update(first_paid_at=observation.first_paid_at.isoformat() if observation.first_paid_at else None,
                 observed_first_at=customer.get('observed_first', {}).get('at'),
                 latest_observed_paid_at=observation.latest_paid_at.isoformat() if observation.latest_paid_at else None,
                 source_stage=customer.get('stage', 'unverified'),
                 amount_unit='USD', amount_basis='whole_order_sales_not_net_contribution')
    return dict(status='observed', customer_id=customer_id, facts=facts,
                source={key: deepcopy(source.get(key)) for key in
                        ('snapshot_id', 'evidence_id', 'data_version', 'policy_version',
                         'identity_version', 'scope_version', 'query', 'coverage', 'weekly_cutoff')},
                evidence_ref=deepcopy(receipt['evidence_ref']), as_of=observation.as_of.isoformat(),
                limitations=limitations, refund_review_needed=observation.refund_review_needed,
                options=[{'action': 'no_intervention', 'reason': 'analysis_does_not_authorize_business_action'}],
                business_write_performed=False)


def observe_live_orders(fetch, *, customer_id, site_id, game_id, start,
                        end_exclusive, max_pages, now):
    """Bounded live observations, not a frozen lifecycle or paid-purchase count.

    Host fetch is run/actor/customer-bound and adds any private email selector
    after private permission + snapshot membership checks. No email argument or
    output is exposed here. Existing FS owns pagination and valid-order policy.
    """
    from live_order_consumer import iter_pages
    today = moment(now).astimezone(BEIJING).date()
    if not isinstance(customer_id, str) or not re.fullmatch(r'c_[a-f0-9]{32}', customer_id):
        raise ValueError('opaque_customer_id')
    try:
        begin, end = date.fromisoformat(start), date.fromisoformat(end_exclusive)
        if (begin.isoformat() != start or end.isoformat() != end_exclusive
                or not today-timedelta(days=365) <= begin < end <= today+timedelta(days=1)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('live_date_boundary') from None
    pages = rows = 0
    states = {}
    for page in iter_pages(fetch, site_id=site_id, game_id=game_id, start=start,
                           end_exclusive=end_exclusive, max_pages=max_pages):
        data = page['data']
        if 'observed_page_rows' in page and page['observed_page_rows'] != len(data):
            raise PermissionError('live_private_projection_required')
        if len(data) > 20:
            raise ValueError('live_page_size')
        pages += 1
        rows += len(data)
        for item in data:
            if type(item) is not dict:
                raise ValueError('live_order_projection')
            pair = tuple(str(item[key]) if type(item.get(key)) in (str, int)
                         and re.fullmatch(r'[0-9]{1,8}', str(item[key])) else 'unmapped'
                         for key in ('status', 'pay_status'))
            states[pair] = states.get(pair, 0) + 1
    return dict(status='partial', semantics='live_non_snapshot', complete=False,
                customer_id=customer_id, source='FS/live-orders',
                scope=dict(site_id=site_id, game_id=game_id, start=start, end_exclusive=end_exclusive),
                pages=pages, observed_order_rows=rows,
                source_states=[dict(status=pair[0], pay_status=pair[1], rows=count)
                               for pair, count in sorted(states.items())],
                lifetime_first_paid_at=None,
                limitations=['bounded_non_snapshot_observation', 'rows_not_a_distinct_valid_purchase_count',
                             'not_lifetime_history', 'cross_site_identity_not_inferred'],
                business_write_performed=False)


def assess(observation, *, now, observation_anchor, recheck_at,
           expected_next_purchase_at=None, previous_evidence_ref=None,
           goal_active=True):
    """Decide whether to investigate, wait or review again; never infer causality.

The trusted goal supplies cadence and recheck time. No universal inactivity
threshold, invented high-value definition, churn probability or net profit.
"""
    o = observation
    if not isinstance(o, Observation):
        raise ValueError("observation_contract")
    now, anchor, due = map(moment, (now, observation_anchor, recheck_at))
    moment(o.as_of)
    if o.as_of > now or anchor > now:
        raise ValueError("future_observation")
    if not all(isinstance(s, str) and s.strip() for s in (o.evidence_ref, o.source, o.version)):
        raise ValueError("evidence_identity")
    if previous_evidence_ref is not None and (not isinstance(previous_evidence_ref, str) or not previous_evidence_ref):
        raise ValueError("previous_evidence_identity")
    if any(type(v) is not bool for v in (o.complete, o.identity_verified, o.refund_review_needed, goal_active)):
        raise ValueError("observation_flags")
    if not isinstance(o.missing, tuple) or any(not isinstance(s, str) for s in o.missing):
        raise ValueError("missing_fields")
    for paid in (o.first_paid_at, o.latest_paid_at):
        if paid is not None and moment(paid) > o.as_of:
            raise ValueError("purchase_after_source_cutoff")
    if o.first_paid_at is not None and (o.latest_paid_at is None or o.first_paid_at > o.latest_paid_at):
        raise ValueError("purchase_history_order")
    if expected_next_purchase_at is not None:
        moment(expected_next_purchase_at)
    result = dict(
        evidence=dict(ref=o.evidence_ref, source=o.source, version=o.version,
                      as_of=o.as_of.isoformat(), complete=o.complete, missing=list(o.missing)),
        recheck_at=due.isoformat(),
        limitations=list(o.missing),
        refund_review_needed=o.refund_review_needed,
        options=[dict(action="no_intervention", reason="No business action authorized by this assessment")],
        business_write_performed=False,
        maturity={str(days): None for days in (7, 14, 30)},
        purchase_since_anchor=None,
        verification="local_contract_only",
    )
    # Only complete, unambiguous history can establish a credible Day0.
    if (o.complete and o.identity_verified and not o.missing
            and not o.refund_review_needed and o.first_paid_at is not None):
        result["maturity"] = {str(days): o.as_of >= o.first_paid_at + timedelta(days=days)
                              for days in (7, 14, 30)}
    def finish(state, reason):
        return dict(result, state=state, reason=reason)
    if not goal_active:
        return finish("stopped", "goal_inactive")
    if not o.identity_verified:
        return finish("needs_evidence", "identity_unresolved")
    # Financial contribution and an incomplete historical refund cursor remain
    # limitations for Agent interpretation; they do not cancel a read-only due
    # review or the fact of a purchase under the source's effective-order policy.
    supplemental = {'purchase_cost', 'net_contribution', 'complete_refund_change_cursor'}
    if not o.complete or any(field not in supplemental for field in o.missing):
        return finish("needs_evidence", "partial_or_missing_history")
    if o.as_of < anchor:
        return finish("needs_evidence", "source_predates_observation_anchor")
    # Preserve the observed fact separately: it must not suppress elapsed
    # deadlines or their freshness requirements on later assessments.
    result["purchase_since_anchor"] = o.latest_paid_at is not None and o.latest_paid_at > anchor
    if now >= due:
        if o.as_of < due:
            return finish("refresh_required", "source_does_not_cover_due_check")
        return finish("review_due", "scheduled_recheck_due")
    if expected_next_purchase_at is not None and now >= expected_next_purchase_at:
        if o.as_of < expected_next_purchase_at:
            return finish("refresh_required", "source_does_not_cover_expected_purchase")
        return finish("investigate", "past_supplied_purchase_cadence_not_confirmed_churn")
    # A purchase alone proves neither intervention success nor incrementality.
    if result["purchase_since_anchor"]:
        return finish("purchase_observed", "reassess_or_reduce_frequency")
    if previous_evidence_ref == o.evidence_ref:
        return finish("waiting", "unchanged_evidence_before_due")
    if expected_next_purchase_at is None:
        return finish("investigate", "purchase_cadence_not_established")
    return finish("waiting", "within_supplied_purchase_cadence")
