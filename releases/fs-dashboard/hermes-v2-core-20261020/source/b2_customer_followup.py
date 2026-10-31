"""Unwired B2 consumer of minimal, authorized A2 observation summaries.

No reads, scheduler, customer database, model calls or business actions. A owns
identity/scope validation and aggregation. This module cannot authorize access.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
        options=[dict(action="no_intervention", reason="No business action authorized by this assessment")],
        business_write_performed=False,
        maturity={str(days): None for days in (7, 14, 30)},
        verification="local_contract_only",
    )
    # Only complete, unambiguous history can establish a credible Day0.
    if o.complete and o.identity_verified and o.first_paid_at is not None:
        elapsed = (o.as_of.astimezone(BEIJING).date() - o.first_paid_at.astimezone(BEIJING).date()).days
        result["maturity"] = {str(days): elapsed >= days for days in (7, 14, 30)}
    def finish(state, reason):
        return dict(result, state=state, reason=reason)
    if not goal_active:
        return finish("stopped", "goal_inactive")
    if not o.identity_verified:
        return finish("needs_evidence", "identity_unresolved")
    if not o.complete or o.missing:
        return finish("needs_evidence", "partial_or_missing_history")
    if o.refund_review_needed:
        return finish("needs_evidence", "refund_correction_requires_review")
    if o.as_of < anchor:
        return finish("needs_evidence", "source_predates_observation_anchor")
    # A purchase strictly after the observation anchor is an observation only;
    # it proves neither successful intervention nor incremental revenue.
    if o.latest_paid_at is not None and o.latest_paid_at > anchor:
        return finish("purchase_observed", "reassess_or_reduce_frequency")
    if now >= due:
        if o.as_of < due:
            return finish("refresh_required", "source_does_not_cover_due_check")
        return finish("review_due", "due_even_without_new_orders")
    if expected_next_purchase_at is not None and now >= expected_next_purchase_at:
        if o.as_of < expected_next_purchase_at:
            return finish("refresh_required", "source_does_not_cover_expected_purchase")
        return finish("investigate", "past_supplied_purchase_cadence_not_confirmed_churn")
    if previous_evidence_ref == o.evidence_ref:
        return finish("waiting", "unchanged_evidence_before_due")
    if expected_next_purchase_at is None:
        return finish("investigate", "purchase_cadence_not_established")
    return finish("waiting", "within_supplied_purchase_cadence")
