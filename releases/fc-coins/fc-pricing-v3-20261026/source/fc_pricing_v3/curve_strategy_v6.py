"""Offline V6 fixed-reference candidates and confirmation-bound adoption."""
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
import json

from .financial import fingerprint, instant
from .price_curve import compile_curve, curve_key, quote_native, read_curve
from .pricing_proof_v6 import CONTRACT as PROOF_CONTRACT, FAILED, INCOMPLETE, PROVEN
from .admin_readback import GID_FC27, MID_FC27_COINS, PLATFORM_AID, SITE_MAIN


ANCHORS = {'small': '100', 'large': '1000'}
STEP = Decimal('.03')
CENT = Decimal('.01')


def curve_strategy_key(platform):
    return 'owned-curve-strategy-v6:' + platform


def primary_reference_curve(curve, platform):
    from .regional_public import SKU_IDS

    confirmed = _saved(curve)
    identity = confirmed['identity']
    if (identity['site_id'] != SITE_MAIN or identity['aid'] != PLATFORM_AID.get(platform)
            or identity['mid'] != MID_FC27_COINS or identity['gid'] != GID_FC27 or identity['cid'] != '9623'
            or identity['id'] != str(SKU_IDS.get(platform))):
        raise ValueError('strategy_reference_scope_mismatch')
    return confirmed


def _saved(curve):
    # Reuse F0's catalogue-origin check. A caller still supplies the confirmed
    # Goods readback and its original operation/receipt provenance.
    quote = quote_native(curve, dict(site_id=curve['identity']['site_id'], currency='USD',
                                     purchase_k='100', multiplier=1))
    if quote['catalogue_status'] != 'saved_tier':
        raise ValueError('strategy_confirmed_catalogue_required')
    return read_curve(curve['native_payload'], curve['identity'], curve['native_contract'])


def _shape(curve):
    """Compare saved terms apart from editor price controls and provenance."""
    row = deepcopy(curve['native_payload'])
    more = row['more'] if isinstance(row['more'], dict) else json.loads(row['more'])
    more['price'] = ['1'] * len(more['gold'])
    more['discount'] = ['100'] * len(more['gold'])
    row.update(unit_price='1', more=more)
    # Keep versioned semantics and unknown native controls in the terms key.
    contract = {key: value for key, value in curve['native_contract'].items()
                if key not in ('source', 'verified_domain', 'editor_asset_sha256', 'editor_handler_sha256')}
    return curve_key(read_curve(row, curve['identity'], contract))


def _group(quantity):
    return 'small' if Decimal(quantity) < 1000 else 'large'


def _saved_discount_changed_at_same_price(current, adopted):
    previous_tiers = {tier['purchase_k']: tier for tier in adopted['tiers']}
    for tier in current['tiers']:
        previous = previous_tiers.get(tier['purchase_k'])
        if (previous and tier['native_price_usd'] == previous['native_price_usd']
                and tier['native_discount'] != previous['native_discount']):
            return True
    return False


def _candidate(curve, labels, current):
    discount_changes = [dict(purchase_k=before['purchase_k'], before=before['native_discount'],
                             after=after['native_discount'])
                        for before, after in zip(current['tiers'], curve['tiers'])
                        if before['native_discount'] != after['native_discount']]
    return dict(curve=curve, curve_key=curve_key(curve), labels=labels,
                discount_changes=discount_changes,
                write_gaps=['native_discount_write_unverified'] if discount_changes else [])


def build_candidates(confirmed_current_curve, reference, episode, selected_segment,
                     *, unit_price_usd_per_k=None, editor_contract=None,
                     check_saved_discount_terms=False):
    """Freeze one platform and compile only the requested segment off adopted A.

    Reference holds reference_curve/reference_curve_id. Episode holds
    comparison_episode_id and initial_reference_curve/initial_reference_curve_id.
    The caller supplies the evidence-appropriate editor base, when needed.
    Offline editor evidence can be separate from the saved curve's own contract.
    A fresh saved preview also checks for discount edits with no price change.
    """
    anchor = ANCHORS.get(selected_segment)
    if anchor is None:
        raise ValueError('strategy_segment_invalid')
    current = _saved(confirmed_current_curve)
    adopted = _saved(reference['reference_curve'])
    initial = _saved(episode['initial_reference_curve'])
    if current['identity'] != adopted['identity'] or current['identity'] != initial['identity']:
        raise ValueError('strategy_curve_identity_mismatch')
    if any(not isinstance(value, str) or not value.strip() for value in
           (reference['reference_curve_id'], episode['comparison_episode_id'],
            episode['initial_reference_curve_id'])):
        raise ValueError('strategy_reference_or_episode_invalid')
    result = dict(confirmed_current_curve=current, confirmed_current_curve_key=curve_key(current),
                  reference_curve=adopted, reference_curve_id=reference['reference_curve_id'],
                  comparison_episode_id=episode['comparison_episode_id'],
                  initial_reference_curve=initial,
                  initial_reference_curve_id=episode['initial_reference_curve_id'],
                  selected_segment=selected_segment, candidates=[], gaps={},
                  boundary_search_status='intermediate_native_steps_unsearched')
    if (_shape(current) != _shape(adopted)
            or (check_saved_discount_terms and _saved_discount_changed_at_same_price(current, adopted))):
        result['candidates'] = [_candidate(current, ['CURRENT'], current)]
        result['gaps'] = {label: ['current_reference_catalogue_terms_differ'] for label in 'ABC'}
        return result

    by_key = {}

    def add(curve, label):
        key = curve_key(curve)
        if key in by_key:
            by_key[key]['labels'].append(label)
        else:
            by_key[key] = _candidate(curve, [label], current)

    add(current, 'CURRENT')
    add(adopted, 'A')
    result['candidates'] = list(by_key.values())
    basis = next((Decimal(tier['native_price_usd']) for tier in adopted['tiers']
                  if tier['purchase_k'] == anchor), None)
    if basis is None:
        result['gaps'].update(B=['reference_anchor_missing'], C=['reference_anchor_missing'])
        return result
    for label, direction, rounding in (('B', -1, ROUND_CEILING), ('C', 1, ROUND_FLOOR)):
        with localcontext() as context:
            context.prec = max(28, len(basis.as_tuple().digits) + 6)
            target = (basis * (1 + direction * STEP)).quantize(CENT, rounding=rounding)
        if target == basis:
            result['gaps'][label] = ['anchor_rounding_has_no_price_step']
            continue
        targets = dict(anchor_prices_usd={anchor: str(target)})
        if unit_price_usd_per_k is not None:
            targets['unit_price_usd_per_k'] = unit_price_usd_per_k
        compiled = compile_curve(adopted, targets, current['native_contract']
                                 if editor_contract is None else editor_contract)
        if compiled['compilation_status'] != 'EDITOR_CANDIDATE':
            result['gaps'][label] = compiled['gaps']
            continue
        for before, after in zip(adopted['tiers'], compiled['tiers']):
            old, new = Decimal(before['native_price_usd']), Decimal(after['native_price_usd'])
            if _group(before['purchase_k']) != selected_segment:
                legal = old == new
            else:
                with localcontext() as context:
                    context.prec = max(28, len(old.as_tuple().digits) + len(new.as_tuple().digits) + 6)
                    legal = 0 <= direction * (new - old) <= STEP * old
            if not legal:
                result['gaps'][label] = [dict(code='compiled_tier_outside_segment_step',
                                              purchase_k=before['purchase_k'])]
                break
        else:
            add(compiled, label)
    result['candidates'] = list(by_key.values())
    return result


def curve_proof_bound(proof, key):
    return (isinstance(proof, dict) and proof.get('contract') == PROOF_CONTRACT
            and proof.get('curve_key') == key
            and proof.get('proof_hash') == fingerprint({k: v for k, v in proof.items() if k != 'proof_hash'}))


def choose_action(comparison, curve_proofs, *, preferred_label='CURRENT'):
    """Evaluate the caller's frozen F2 outputs. Runtime freshness is separate.

    The explicit label can come from the existing scheduler or a documented
    business decision. There is no automatic rank by target margin or competitor.
    """
    if preferred_label not in ('CURRENT', 'A', 'B', 'C'):
        raise ValueError('strategy_preferred_label_invalid')
    result = dict(status=INCOMPLETE, execution_authorized=False, selected=None,
                  comparison_episode_id=comparison['comparison_episode_id'],
                  reference_curve_id=comparison['reference_curve_id'],
                  confirmed_current_curve_key=comparison['confirmed_current_curve_key'],
                  preferred_label=preferred_label, candidate_proofs={},
                  gaps=list(comparison['gaps'].get(preferred_label, [])))
    for candidate in comparison['candidates']:
        key = candidate['curve_key']
        proof = curve_proofs.get(key)
        bound = curve_proof_bound(proof, key)
        status = proof.get('status') if bound else INCOMPLETE
        result['candidate_proofs'][key] = status
        if preferred_label not in candidate['labels']:
            continue
        if status != PROVEN:
            result['gaps'].extend(proof.get('gaps', []) if bound else ['curve_proof_missing_or_unbound'])
            if bound and proof.get('hard_failures'):
                result['gaps'].extend(proof['hard_failures'])
            if status == FAILED:
                result['status'] = 'PREFERRED_HARD_CONSTRAINT_FAILED'
            continue
        result.update(status='KEEP' if key == comparison['confirmed_current_curve_key'] else 'BOUNDED_TRIAL',
                      selected=deepcopy(candidate), proof_hash=proof['proof_hash'])
        result['gaps'].extend(candidate['write_gaps'])
    if result['selected'] is None and not result['gaps']:
        result['gaps'].append('preferred_candidate_or_complete_proof_unavailable')
    return result


def propose_adoption(reference, comparison, decision, evidence, *, operation_id):
    """Record a proposed business adoption and its meaningful evidence delta.

    order_revisions maps stable order identities to upstream semantic revisions
    (amounts, costs, customer cohort and outcome, without capture timestamps).
    The caller supplies the judgment and comparable cumulative business results.
    """
    selected = decision.get('selected') or {}
    if (decision.get('status') not in ('KEEP', 'BOUNDED_TRIAL') or not selected
            or decision.get('proof_hash') is None or selected['curve_key'] == curve_key(reference['reference_curve'])
            or decision.get('reference_curve_id') != reference['reference_curve_id']
            or decision.get('comparison_episode_id') != comparison['comparison_episode_id']
            or selected not in comparison['candidates']):
        raise ValueError('strategy_adoption_candidate_unproven')
    revisions = evidence.get('order_revisions')
    windows = evidence.get('window_ids')
    cumulative = evidence.get('cumulative') or {}
    required = [operation_id, evidence.get('reason'), evidence.get('changed_judgment'),
                evidence.get('maturity'), evidence.get('cost_revision'), cumulative.get('evidence_ref')]
    if (not isinstance(revisions, dict) or not revisions or not isinstance(windows, list) or not windows
            or any(not isinstance(value, str) or not value.strip()
                   for value in required + list(revisions) + list(revisions.values()) + windows)
            or cumulative.get('initial_reference_curve_id') != comparison['initial_reference_curve_id']
            or any(cumulative.get(key) is None for key in ('revenue_delta_usd', 'procurement_gross_delta_usd',
                                                           'new_customer_delta'))
            or instant(evidence['window_start']) >= instant(evidence['window_end'])):
        raise ValueError('strategy_adoption_evidence_incomplete')
    evidence_hash = fingerprint(revisions)
    history = reference.get('adoption_evidence') or {}
    prior_revisions = history.get('order_revisions', {})
    seen_revisions = history.get('used_order_revisions', {})
    changed = {key: dict(before=prior_revisions.get(key), after=value) for key, value in revisions.items()
               if prior_revisions.get(key) != value and value not in seen_revisions.get(key, ())}
    if not changed or evidence_hash in history.get('used_evidence_hashes', ()):
        raise ValueError('strategy_adoption_has_no_new_evidence')
    initial_prices = {tier['purchase_k']: tier['native_price_usd']
                      for tier in comparison['initial_reference_curve']['tiers']}
    cumulative_tier_prices = [dict(purchase_k=tier['purchase_k'],
                                  initial_usd=initial_prices.get(tier['purchase_k']),
                                  target_usd=tier['native_price_usd']) for tier in selected['curve']['tiers']]
    proposal = dict(kind='BUSINESS_ADOPT', operation_id=operation_id, target_curve_key=selected['curve_key'],
                    proof_hash=decision['proof_hash'], reference_curve_id=reference['reference_curve_id'],
                    comparison_episode_id=comparison['comparison_episode_id'],
                    initial_reference_curve_id=comparison['initial_reference_curve_id'],
                    evidence_hash=evidence_hash, order_revisions=dict(revisions), evidence_delta=changed,
                    window_ids=sorted(set(windows)), window_start=evidence['window_start'],
                    window_end=evidence['window_end'], cost_revision=evidence['cost_revision'],
                    maturity=evidence['maturity'], reason=evidence['reason'],
                    changed_judgment=evidence['changed_judgment'], cumulative=deepcopy(cumulative),
                    cumulative_tier_prices=cumulative_tier_prices)
    proposal['adoption_id'] = fingerprint(proposal)
    return proposal


def confirm_adoption(reference, proposal, confirmed_current_curve, receipt):
    """Promote adopted A only against the original operation's full readback.

    Receipt is the caller's normalized operation confirmation. An already
    confirmed target can use that original operation id and its receipt.
    """
    confirmed = _saved(confirmed_current_curve)
    if (receipt.get('operation_id') != proposal['operation_id']
            or receipt.get('status') not in ('COMPLETED', 'NO_CHANGE')
            or receipt.get('complete_curve_readback') is not True
            or receipt.get('curve_key') != proposal['target_curve_key']
            or curve_key(confirmed) != proposal['target_curve_key']
            or confirmed['identity'] != reference['reference_curve']['identity']
            or not isinstance(receipt.get('readback_ref'), str) or not receipt['readback_ref'].strip()):
        raise ValueError('strategy_adoption_original_readback_unconfirmed')
    if reference['reference_curve_id'] == proposal['adoption_id']:
        return deepcopy(reference)
    if reference['reference_curve_id'] != proposal['reference_curve_id']:
        raise ValueError('strategy_adoption_reference_changed')
    history = reference.get('adoption_evidence') or {}
    revisions = dict(history.get('order_revisions', {}))
    seen = deepcopy(history.get('used_order_revisions', {}))
    for order, delta in proposal['evidence_delta'].items():
        used_order = seen.setdefault(order, [])
        for revision in (revisions.get(order), delta['after']):
            if revision is not None and revision not in used_order:
                used_order.append(revision)
        revisions[order] = delta['after']
    used = list(history.get('used_evidence_hashes', ())) + [proposal['evidence_hash']]
    return dict(reference_curve=confirmed, reference_curve_id=proposal['adoption_id'],
                adoption_evidence=dict(order_revisions=revisions, used_evidence_hashes=used, used_order_revisions=seen),
                comparison_episode_id=proposal['comparison_episode_id'],
                initial_reference_curve_id=proposal['initial_reference_curve_id'],
                adoption=deepcopy(proposal), confirmed_operation_id=receipt['operation_id'],
                readback_ref=receipt['readback_ref'])
