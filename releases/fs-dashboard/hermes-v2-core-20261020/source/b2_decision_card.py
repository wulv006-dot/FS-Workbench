"""Unwired B2 decision view of an already authorized frozen investigation.

No source reads, model, scheduling, storage or actions. The host must authorize
delivery and future reads independently; evidence references grant no access.
"""
from copy import deepcopy
import json
import re

from b1_model_routing import handoff
from b2_frozen_investigation import aware, identity


def _customer_refs(value):
    if isinstance(value, dict):
        return set().union(*(_customer_refs(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_customer_refs(v) for v in value)) if value else set()
    return {value} if isinstance(value, str) and re.fullmatch('c_[a-f0-9]{32}', value) else set()


def decision_card(investigation, *, opaque_customer_id, goal, recheck_at):
    """Answer the plan's six decision questions without inventing an intervention.

    Only no-intervention or further evidence investigation is recommended here.
    Neither an observed purchase nor completed pagination establishes benefit,
    net contribution, business permission or long-term goal completion.
    """
    cid = identity(opaque_customer_id)
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 2048:
        raise ValueError('decision_goal')
    aware(recheck_at)  # Explicit host checkpoint, never a new automatic schedule.
    if not isinstance(investigation, dict):
        raise ValueError('investigation_receipt')
    status = investigation.get('status')
    base = dict(status=status, business_write_performed=False, model_call_performed=False,
                goal_completed=False, execution_allowed=False,
                verification='local_contract_only')
    if status in {'stopped', 'unavailable', 'unknown', 'incomparable'}:
        return base  # No cached private decisions after source/access failure.
    if status not in {'observed_with_limits', 'partial'}:
        raise ValueError('investigation_status')
    if any(investigation.get(field) is not False
           for field in ('business_write_performed', 'model_call_performed')):
        raise ValueError('frozen_investigation_only')
    decisions = investigation.get('decisions')
    if not isinstance(decisions, list) or any(not isinstance(d, dict) for d in decisions):
        raise ValueError('investigation_decisions')
    ids = [identity(d.get('opaque_customer_id')) for d in decisions]
    if len(set(ids)) != len(ids) or ids.count(cid) != 1:
        raise ValueError('decision_customer')
    selected = decisions[ids.index(cid)]
    followup = selected.get('followup', {})
    state = followup.get('state')
    if state not in {'needs_evidence', 'refresh_required', 'review_due', 'investigate',
                     'waiting', 'purchase_observed', 'stopped'}:
        raise ValueError('followup_state')
    reason = followup.get('reason')
    if not isinstance(reason, str) or not reason:
        raise ValueError('followup_reason')
    source_at, evaluated_at = investigation.get('source_as_of'), investigation.get('evaluated_at')
    if aware(source_at) > aware(evaluated_at):
        raise ValueError('future_source_cutoff')
    evidence = handoff(task_id=investigation.get('request_id'), revision=1, goal=goal,
                       constraints=[], evidence=investigation.get('evidence'),
                       completed_actions=[], next_step='review frozen evidence')['evidence']
    relevant, withheld = [], set()
    for ref in evidence:
        try:
            locator = json.loads(ref['ref'])
        except (ValueError, TypeError):
            raise ValueError('frozen_evidence_locator') from None
        if not isinstance(locator, dict) or aware(ref['as_of']) > aware(evaluated_at):
            raise ValueError('frozen_evidence_locator')
        queries = [locator.get('query', {})] + [
            locator.get(edge, {}).get('query', {}) for edge in ('first', 'last')]
        methods = {q.get('method') for q in queries}
        if 'candidates' in methods:
            # Candidate cursors encode positions belonging to OTHER customers.
            # Keep the coverage summary, not the group page-chain locator. Do
            # not decode/rewrite A's opaque cursor into a new source query.
            withheld.add('candidate_reference_withheld_for_privacy')
        elif not _customer_refs(locator) <= {cid}:
            withheld.add('comparison_reference_withheld_for_privacy'
                         if 'changes_due' in methods else 'customer_reference_withheld_for_privacy')
        else:
            relevant.append(ref)
    if not relevant:
        raise ValueError('decision_evidence_required')
    limits = selected.get('limits')
    if not isinstance(limits, list) or any(not isinstance(v, str) for v in limits):
        raise ValueError('decision_limits')
    coverage = {}
    for name, value in (
            ('candidates_complete', investigation.get('candidate_coverage', {}).get('enumeration_complete')),
            ('timeline_complete', selected.get('timeline_coverage', {}).get('enumeration_complete'))):
        if type(value) is not bool:
            raise ValueError('decision_coverage')
        coverage[name] = value
    missing = set(limits)
    followup_missing = followup.get('evidence', {}).get('missing', [])
    if not isinstance(followup_missing, list) or any(not isinstance(v, str) for v in followup_missing):
        raise ValueError('followup_missing')
    missing.update(followup_missing)
    for ref in evidence:
        # Withholding a locator does not erase the source's declared gaps.
        missing.update(ref['missing'])
    if not coverage['candidates_complete']:
        missing.add('candidate_pages_unread')
    if not coverage['timeline_complete']:
        missing.add('timeline_pages_unread')
    if not all(coverage.values()):
        base['status'] = 'partial'
    if withheld - {'candidate_reference_withheld_for_privacy'}:
        base['status'] = 'partial'
    analysis_missing = missing | (withheld - {'candidate_reference_withheld_for_privacy'})
    missing.update(withheld)
    # A provider or caller cannot append discount/contact options to enable them.
    investigate = (state in {'needs_evidence', 'refresh_required', 'review_due', 'investigate'}
                   or status == 'partial' or bool(analysis_missing))
    recommendation = 'investigate_evidence' if investigate else 'no_intervention'
    if state == 'stopped':
        recommendation = 'no_intervention'
    result = dict(base, subject=cid, goal=goal, request_id=investigation['request_id'],
                  source_as_of=source_at, evaluated_at=evaluated_at, recheck_at=recheck_at,
                  state=state, reason=reason, recommendation=recommendation,
                  coverage=coverage, missing=sorted(missing), evidence=relevant,
                  evidence_delivery='partial' if withheld else 'complete',
                  alternatives=[
                      dict(action='no_intervention',
                           reason='Preserve current operations; no intervention benefit is established.'),
                      dict(action='investigate_evidence',
                           reason='Resolve coverage, cadence or correction questions before any intervention.')],
                  authorization=dict(reads='host_must_revalidate_scope_on_each_call',
                                     execution='not_granted_by_this_card'),
                  net_contribution='unknown', causal_effect='unknown')
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 32768:
        raise ValueError('decision_card_too_large')
    return deepcopy(result)
