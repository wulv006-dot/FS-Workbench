"""A2 frozen-summary consumer driving a goal's persistent reservation only.

Server-injected scope resolution and A2 context remain access authorities. No
collector, customer list, scheduler, task spec, worker or provider client. Native
snapshot data/policy versions and conservative cutoff are read, not invented.
"""
from copy import deepcopy
import hashlib
import json
import re

from b2_frozen_investigation import aware, cutoff, encoded, handoff_reference, source_key
from b2_goal_host import GoalHost
from b2_goal_state import PENDING, _at

SOURCE = 'authorized_frozen_user_analytics'


class FactUnavailable(ValueError):
    pass


def frozen_fact(receipt, *, scope, snapshot_id, now):
    """Validate the real A2 source + compact summary, not a model supplied hash."""
    if receipt.get('status') not in {'available', 'partial'}:
        raise FactUnavailable('frozen_summary_unavailable')
    source, data = receipt.get('source'), receipt.get('data')
    if not isinstance(source, dict) or not isinstance(data, dict):
        raise FactUnavailable('frozen_summary_missing')
    for name, prefix in (('snapshot_id', 'us_'), ('evidence_id', 'ua_')):
        if not isinstance(source.get(name), str) or not re.fullmatch(prefix + '[a-f0-9]{32}', source[name]):
            raise FactUnavailable('frozen_identity_missing')
    if source['snapshot_id'] != snapshot_id:
        raise ValueError('frozen_snapshot_mismatch')
    versions = ('snapshot_id', 'evidence_id', 'data_version', 'scope_version',
                'identity_version', 'policy_version', 'contract_version')
    for name in versions:
        value = source.get(name)
        valid = (isinstance(value, str) and value.strip()
                 and value.lower() not in {'unknown', 'unavailable', 'pending'})
        if name == 'data_version' and type(value) is int and value >= 0:
            valid = True
        if not valid:
            raise FactUnavailable('frozen_version_missing')
        if type(data.get(name)) is not type(value) or data[name] != value:
            raise ValueError('summary_source_version_mismatch')
    query = source.get('query')
    if (not isinstance(query, dict) or data.get('query') != query
            or {k: query.get(k) for k in ('scope', 'scope_id')} != scope):
        raise ValueError('frozen_scope_or_query_mismatch')
    reference = receipt.get('evidence_ref')
    if reference != dict(scope=scope, snapshot_id=snapshot_id, evidence_id=source['evidence_id'],
                         query={'method': 'aggregate', 'section': 'summary'}):
        raise ValueError('frozen_reference_mismatch')
    policy = data.get('lifecycle_policy')
    if (not isinstance(policy, dict) or policy.get('version') != source['policy_version']
            or query.get('policy_version') != source['policy_version']
            or not isinstance(policy.get('day_basis'), str) or not policy['day_basis']
            or not isinstance(policy.get('thresholds_days'), list)
            or not policy['thresholds_days']
            or any(type(v) is not int or v <= 0 for v in policy['thresholds_days'])
            or policy['thresholds_days'] != sorted(set(policy['thresholds_days']))):
        raise FactUnavailable('actual_frozen_lifecycle_policy_missing')
    coverage, watermark = source.get('coverage'), source.get('source_watermark')
    if not isinstance(coverage, dict) or not isinstance(watermark, list):
        raise FactUnavailable('frozen_coverage_or_watermark_missing')
    dates = [query.get('as_of'), coverage.get('state_data_through'), source.get('weekly_cutoff'),
             source.get('captured_at')]
    if not dates[0]:
        raise FactUnavailable('business_cutoff_missing')
    try:
        times = [aware(value) for value in dates if value is not None]
        through = cutoff(source)
    except (ValueError, TypeError, KeyError):
        raise FactUnavailable('frozen_time_missing') from None
    if any(value > _at(now) for value in times):
        raise ValueError('future_frozen_source')
    signature = dict(source=json.loads(source_key(source)), lifecycle_policy=policy,
                     source_watermark=watermark)
    version = 'b2f_' + hashlib.sha256(encoded(signature).encode('utf-8')).hexdigest()
    compatibility = dict(scope=scope, **{k: source[k] for k in versions[3:]},
                         lifecycle_policy=policy,
                         query_basis={k: query.get(k) for k in ('start', 'state_basis', 'policy_mode', 'H')})
    missing = deepcopy(receipt.get('missing_fields'))
    if not isinstance(missing, list) or any(not isinstance(v, str) for v in missing):
        raise ValueError('frozen_missing_fields')
    if receipt['status'] == 'partial':
        missing.append('frozen_summary_partial')
    ref = handoff_reference(source, reference,
        dict(scope='frozen_summary', source_cutoff=through.isoformat(), source_status=receipt['status'],
             period_complete=coverage.get('period_complete'), enumeration_complete=False), missing)
    ref['version'] = encoded(dict(contract='b2_goal_facts_v1', fact_version=version,
                                  data_version=source['data_version'], compatibility=compatibility))
    return dict(fact_version=version, evidence=ref, compatibility=compatibility, cutoff=through)


def _summary_ref(evidence, scope):
    """Existing B2 producer and this bridge put the current summary first."""
    refs, other = [], []
    for value in evidence:
        if value['source'] != SOURCE:
            other.append(deepcopy(value))
            continue
        try:
            ref = json.loads(value['ref'])
        except (ValueError, TypeError):
            raise FactUnavailable('baseline_locator_missing')
        if not isinstance(ref, dict):
            raise FactUnavailable('baseline_locator_missing')
        locators = [ref] if 'scope' in ref else [ref.get('first'), ref.get('last')]
        if any(not isinstance(item, dict) or item.get('scope') != scope for item in locators):
            raise PermissionError('goal_baseline_scope_mismatch')
        if ref.get('query') == {'method': 'aggregate', 'section': 'summary'}:
            if ref.get('scope') != scope:
                raise PermissionError('goal_baseline_scope_mismatch')
            refs.append((value, ref['snapshot_id']))
        else:
            # Preserve previous page-chain/other references and their missing
            # fields; only redundant aggregate summaries are compacted.
            other.append(deepcopy(value))
    return (refs[0] if refs else None), other


class FrozenGoalFacts:
    def __init__(self, host, *, resolve_scope, context_for):
        if not callable(resolve_scope) or not callable(context_for):
            raise ValueError('trusted_fact_callbacks_required')
        self.host, self.resolve_scope, self.context_for = host, resolve_scope, context_for

    def step(self, goal_id, *, snapshot_id, mutation_id, request_id, now):
        state = self.host._load(goal_id)
        if state['status'] != 'active' or (state['work'] and state['work']['status'] in PENDING):
            # Reconcile the original task without any catalog/aggregate reads.
            result = self.host.step(goal_id, mutation_id=mutation_id, request_id=request_id,
                                    fact_version=None, now=now, expected_revision=state['revision'])
            # Goal/task metadata may remain owner-readable, but the current
            # source grant was not revalidated here. Do not return cached refs.
            result.pop('state', None)
            return result
        scope = self.resolve_scope(self.host.owner, state['scope_ref'])
        if (not isinstance(scope, dict) or set(scope) != {'scope', 'scope_id'}
                or scope['scope'] not in {'site', 'project'}
                or not isinstance(scope['scope_id'], str) or not scope['scope_id']):
            return dict(action='unavailable', goal_id=goal_id, reason='trusted_scope_mapping_required')
        context = self.context_for(self.host.owner, deepcopy(scope))
        if context is None:
            return dict(action='unavailable', goal_id=goal_id, reason='trusted_context_required')
        if context.identity != self.host.owner or context.scope != scope:
            raise PermissionError('goal_context_identity_or_scope')
        def authorize(owner, ref):
            return (ref == state['scope_ref'] and self.host.authorize(owner, ref) is True
                    and context.source_authorized(owner, deepcopy(scope), True) is True)
        # Reuse A's original grant intersection all the way through goal CAS,
        # admission and returning state. No cached private result after revoke.
        bound = GoalHost(self.host.goals, owner=self.host.owner, cid=self.host.cid,
                         authorize=authorize, dispatcher=self.host.dispatcher,
                         verify_receipt=self.host.verify_receipt)
        bound._check(goal_id, state)
        try:
            catalog = context.catalog()
            if (catalog.get('status', 'available') != 'available'
                    or catalog.get('scope') != scope or catalog.get('can_read_private') is not True):
                return dict(action='unavailable', goal_id=goal_id, reason='private_frozen_scope_required')
            current = context.aggregate(snapshot_id=snapshot_id, section='summary')
            if current.get('status') not in {'available', 'partial'}:
                return dict(action=current.get('status', 'unknown'), goal_id=goal_id)
            fact = frozen_fact(current, scope=scope, snapshot_id=snapshot_id, now=now)
            previous, other = _summary_ref(state['evidence'], scope)
            evidence = [fact['evidence']]
            if previous is not None and previous[1] == snapshot_id:
                fact['evidence']['missing'] = sorted(set(fact['evidence']['missing'] + previous[0]['missing']))
            elif previous is not None:
                baseline = context.aggregate(snapshot_id=previous[1], section='summary')
                if baseline.get('status') not in {'available', 'partial'}:
                    return dict(action='unavailable', goal_id=goal_id, reason='baseline_unavailable')
                old = frozen_fact(baseline, scope=scope, snapshot_id=previous[1], now=now)
                if old['compatibility'] != fact['compatibility'] or old['cutoff'] > fact['cutoff']:
                    return dict(action='incomparable', goal_id=goal_id)
                old['evidence']['missing'] = sorted(set(old['evidence']['missing'] + previous[0]['missing']))
                evidence.append(old['evidence'])
            evidence.extend(other)
        except PermissionError:
            raise
        except FactUnavailable as exc:
            return dict(action='unavailable', goal_id=goal_id, reason=str(exc))
        except LookupError:
            return dict(action='unavailable', goal_id=goal_id, reason='frozen_snapshot_unavailable')
        except (OSError, TimeoutError, ConnectionError):
            return dict(action='unknown', goal_id=goal_id, reason='frozen_read_outcome_unknown')
        return bound.step(goal_id, mutation_id=mutation_id, request_id=request_id,
                          fact_version=fact['fact_version'], evidence=evidence, now=now,
                          expected_revision=state['revision'])
