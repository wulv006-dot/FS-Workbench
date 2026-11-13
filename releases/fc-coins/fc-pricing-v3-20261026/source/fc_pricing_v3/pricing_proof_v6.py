"""Evaluate frozen V6 quote evidence for one platform's proposed curve."""
from decimal import Context, Decimal, localcontext

from .admin_readback import GID_FC27, MID_FC27_COINS, PLATFORM_AID, SITE_MAIN
from .cost_model import BASES
from .financial import fingerprint, number
from .price_curve import curve_key


CONTRACT = 'fc_pricing_proof_v6'
PROVEN = 'PROVEN'
INCOMPLETE = 'PROOF_INCOMPLETE'
FAILED = 'HARD_CONSTRAINT_FAILED'
NOT_EVALUABLE = 'NOT_EVALUABLE'
HARD_MARGIN = Decimal('.18')
TARGET_MARGIN = Decimal('.25')
DOMAIN_REVISIONS = ('quantity', 'offers', 'fulfilment', 'propagation')
PATH_REFERENCES = ('quote_ref', 'cost_ref', 'fee_ref', 'native_tier_or_rule',
                   'rounding_contract', 'offer_version', 'fulfilment_contract')
BASKET_SELECTIONS = {'main': ('closed_bjt_7d',),
                     'recent': ('latest_24h', 'latest_3d', 'main_fallback')}


def _reference(value):
    return isinstance(value, str) and bool(value.strip())


def _decimal(value, *, zero=False):
    try:
        return number(value, zero=zero)
    except ValueError:
        return None


def _decimal_string(value):
    if value is None:
        return None
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _strings(values):
    return isinstance(values, (list, tuple)) and all(_reference(value) for value in values)


def _coverage(record, result):
    status = record.get('coverage_status')
    source_gaps = record.get('coverage_gaps')
    result['coverage_status'] = status if _reference(status) else None
    result['coverage_gaps'] = sorted(set(source_gaps)) if _strings(source_gaps) else None
    if status != 'complete' or result['coverage_gaps'] != []:
        return ['coverage_incomplete']
    return []


def _index(rows, key):
    indexed, duplicate = {}, set()
    invalid = 0
    if not isinstance(rows, (list, tuple)):
        return {}, set(), 1
    for row in rows:
        identifier = row.get(key) if isinstance(row, dict) else None
        if not _reference(identifier):
            invalid += 1
        elif identifier in indexed:
            duplicate.add(identifier)
        else:
            indexed[identifier] = row
    return indexed, duplicate, invalid


def _scope(curve, domain):
    identity = curve['identity']
    platform = next((name for name, aid in PLATFORM_AID.items() if aid == identity['aid']), None)
    result = dict(platform=platform, curve_site_id=identity['site_id'])
    gaps = _coverage(domain, result)
    if (platform is None or domain.get('platform') != platform or identity['site_id'] not in ('0', SITE_MAIN)
            or identity['mid'] != MID_FC27_COINS or identity['gid'] != GID_FC27):
        gaps.append('curve_scope_mismatch')
    result['version'] = domain.get('version') if _reference(domain.get('version')) else None
    if result['version'] is None:
        gaps.append('domain_version_missing')
    revisions = domain.get('source_revisions')
    revisions = revisions if isinstance(revisions, dict) else {}
    result['source_revisions'] = {key: revisions[key] for key in DOMAIN_REVISIONS
                                  if _reference(revisions.get(key))}
    gaps.extend(f'domain_revision_missing:{key}' for key in DOMAIN_REVISIONS
                if key not in result['source_revisions'])

    sites = domain.get('site_paths')
    required = {}
    if not isinstance(sites, dict) or SITE_MAIN not in sites:
        gaps.append('main_site_domain_missing')
    result['site_paths'] = {}
    if isinstance(sites, dict):
        for site, paths in sorted(sites.items(), key=lambda item: str(item[0])):
            if not _reference(site) or not site.isascii() or not site.isdecimal() or site[0] == '0':
                gaps.append('invalid_domain_site')
                continue
            if not _strings(paths) or not paths:
                gaps.append(f'site_paths_missing:{site}')
                result['site_paths'][site] = []
                continue
            result['site_paths'][site] = sorted(set(paths))
            for path in sorted(paths):
                if path in required:
                    gaps.append(f'duplicate_domain_path:{path}')
                else:
                    required[path] = site
    return result, required, gaps


def _evaluate_path(row, path_id, site_id, key, unavailable):
    result = dict(path_id=path_id, site_id=site_id, zero_line_status=INCOMPLETE,
                  zero_line_surplus_usd=None, basket_input_complete=False, gaps=[])
    if unavailable:
        result['gaps'].append(unavailable)
        return result

    gaps = result['gaps']
    if row.get('site_id') != site_id:
        gaps.append('path_site_mismatch')
    if row.get('curve_key') != key:
        gaps.append('path_curve_key_mismatch')
    if row.get('proof_status') != 'verified':
        gaps.append('native_quote_unverified')
    if row.get('currency') != 'USD' or row.get('amount_kind') != 'TOTAL':
        gaps.append('expected_total_usd_amounts')
    if row.get('cost_status') != 'verified' or row.get('quantity_basis') not in BASES:
        gaps.append('cost_unverified')
    for field in PATH_REFERENCES:
        result[field] = row.get(field) if _reference(row.get(field)) else None
        if result[field] is None and field != 'fee_ref':
            gaps.append(f'missing_reference:{field}')
    for field in ('proof_status', 'currency', 'amount_kind', 'cost_status', 'quantity_basis', 'fee_status'):
        result[field] = row.get(field) if _reference(row.get(field)) else None

    values = {}
    for field in ('purchase_k', 'promised_bonus_k', 'promised_delivered_k', 'regular_usd',
                  'net_receipt_usd', 'expected_cost_usd', 'safe_cost_usd', 'stress_cost_usd',
                  'known_fee_usd'):
        value = _decimal(row.get(field), zero=field not in ('purchase_k', 'promised_delivered_k'))
        values[field] = value
        result[field] = _decimal_string(value)
        if value is None and field != 'known_fee_usd':
            gaps.append(f'amount_missing_or_invalid:{field}')

    purchase, bonus, delivered = (values[key] for key in ('purchase_k', 'promised_bonus_k',
                                                        'promised_delivered_k'))
    if all(value is not None for value in (purchase, bonus, delivered)) and purchase + bonus != delivered:
        gaps.append('promised_delivery_mismatch')
    expected, safe, stress = (values[key] for key in ('expected_cost_usd', 'safe_cost_usd', 'stress_cost_usd'))
    if all(value is not None for value in (expected, safe, stress)) and not expected <= safe <= stress:
        gaps.append('cost_bounds_inconsistent')
    result['basket_input_complete'] = not gaps

    if row.get('fee_status') not in ('verified', 'contract_upper_bound'):
        gaps.append('fee_unverified')
        result['known_fee_usd'] = None
    if result['fee_ref'] is None:
        gaps.append('missing_reference:fee_ref')
    if values['known_fee_usd'] is None:
        gaps.append('amount_missing_or_invalid:known_fee_usd')
    if not gaps:
        surplus = values['net_receipt_usd'] - stress - values['known_fee_usd']
        result['zero_line_surplus_usd'] = _decimal_string(surplus)
        result['zero_line_status'] = PROVEN if surplus >= 0 else FAILED
    return result


def _evaluate_basket(name, basket, paths):
    basket = basket if isinstance(basket, dict) else {}
    result = dict(status=NOT_EVALUABLE, net_receipt_usd=None, safe_cost_usd=None,
                  safe_procurement_margin=None, members=[])
    gaps = _coverage(basket, result)
    evidence_ref = basket.get('evidence_ref')
    result['evidence_ref'] = evidence_ref if _reference(evidence_ref) else None
    if result['evidence_ref'] is None:
        gaps.append('basket_evidence_missing')
    selection = basket.get('selection')
    result['selection'] = selection if _reference(selection) else None
    if selection not in BASKET_SELECTIONS[name]:
        gaps.append('basket_selection_unverified')
    members, duplicate, invalid = _index(basket.get('members'), 'path_id')
    result['invalid_member_count'] = invalid
    if invalid:
        gaps.append('basket_member_invalid')
    if not members:
        gaps.append('basket_empty')

    revenue = costs = Decimal(0)
    for path_id, member in sorted(members.items()):
        weight = None if path_id in duplicate else _decimal(member.get('weight'))
        path = paths.get(path_id)
        member_gaps = []
        if path_id in duplicate:
            member_gaps.append('basket_member_duplicate')
        elif weight is None:
            member_gaps.append('basket_weight_missing_or_invalid')
        if path is None or path['site_id'] != SITE_MAIN:
            member_gaps.append('main_site_path_missing')
        elif not path['basket_input_complete']:
            member_gaps.append('basket_path_incomplete')
        result['members'].append(dict(path_id=path_id, weight=_decimal_string(weight), gaps=member_gaps))
        gaps.extend(f'{gap}:{path_id}' for gap in member_gaps)
        if not member_gaps:
            revenue += weight * Decimal(path['net_receipt_usd'])
            costs += weight * Decimal(path['safe_cost_usd'])

    result['gaps'] = sorted(gaps)
    if not members or not any(member['weight'] is not None for member in result['members']):
        return result
    if gaps:
        result['status'] = INCOMPLETE
        return result
    result.update(net_receipt_usd=_decimal_string(revenue), safe_cost_usd=_decimal_string(costs))
    if revenue == 0:
        result['gaps'].append('basket_zero_revenue')
        return result
    gross = revenue - costs
    result.update(status=PROVEN if gross >= HARD_MARGIN * revenue else FAILED,
                  safe_procurement_margin=_decimal_string(gross / revenue))
    return result


def _target(main):
    result = dict(target_margin='0.25', target_is_hard_constraint=False, target_gap_pp=None,
                  gain_needed_at_fixed_revenue_usd=None, net_revenue_needed_at_fixed_cost_usd=None)
    if main['safe_procurement_margin'] is not None:
        costs, revenue = Decimal(main['safe_cost_usd']), Decimal(main['net_receipt_usd'])
        target_cost_share = 1 - TARGET_MARGIN
        gap = max(Decimal(0), costs - target_cost_share * revenue)
        result.update(target_gap_pp=_decimal_string(gap / revenue * 100),
                      gain_needed_at_fixed_revenue_usd=_decimal_string(gap),
                      net_revenue_needed_at_fixed_cost_usd=_decimal_string(gap / target_cost_share))
    return result


def validate_curve(curve, baskets, evidence, validation_domain):
    """Verify 0/18/25 over a caller-attested domain and frozen total USD quote rows.

    ``curve`` is the F0 read_curve result. Domain revisions attest which sites and
    paths are covered. Evidence binds native quotes, costs and fees to that same
    curve key. Baskets contain the current-quote path ids and original weights.
    The caller establishes source authenticity, freshness and domain completeness.
    """
    if not all(isinstance(record, dict) for record in (curve, baskets, evidence, validation_domain)):
        raise ValueError('pricing_proof_expected_dicts')
    key = curve_key(curve)
    with localcontext(Context(prec=80)):
        scope, required, gaps = _scope(curve, validation_domain)
        bound = evidence.get('curve_key') == validation_domain.get('curve_key') == key
        if not bound:
            gaps.append('curve_key_mismatch')
        rows, duplicate, invalid = _index(evidence.get('paths'), 'path_id')
        if invalid:
            gaps.append('quote_path_invalid')
        gaps.extend(f'unexpected_quote_path:{path_id}' for path_id in rows.keys() - required.keys())

        paths, failures = {}, []
        for path_id, site_id in sorted(required.items()):
            unavailable = None
            if not bound:
                unavailable = 'quote_curve_unbound'
            elif path_id in duplicate:
                unavailable = 'quote_path_duplicate'
            elif path_id not in rows:
                unavailable = 'quote_path_missing'
            path = _evaluate_path(rows.get(path_id), path_id, site_id, key, unavailable)
            paths[path_id] = path
            gaps.extend(f'path:{path_id}:{gap}' for gap in path['gaps'])
            if path['zero_line_status'] == FAILED:
                failures.append(f'zero_line:{path_id}')

        evaluated = {name: _evaluate_basket(name, baskets.get(name), paths) for name in BASKET_SELECTIONS}
        recent = evaluated['recent']
        main = evaluated['main']
        if recent['selection'] == 'main_fallback' and (recent['members'] != main['members'] or main['gaps']):
            recent.update(status=INCOMPLETE, net_receipt_usd=None, safe_cost_usd=None,
                          safe_procurement_margin=None)
            recent['gaps'].append('fallback_members_mismatch' if recent['members'] != main['members']
                                  else 'fallback_main_not_evaluable')
        for name, basket in evaluated.items():
            gaps.extend(f'{name}:{gap}' for gap in basket['gaps'])
            if basket['status'] == FAILED:
                failures.append(f'platform_margin:{name}')
        margins = [basket['safe_procurement_margin'] for basket in evaluated.values()]
        minimum = min(map(Decimal, margins)) if all(margin is not None for margin in margins) else None
        result = dict(contract=CONTRACT, curve_key=key, scope=scope, paths=list(paths.values()),
                      baskets=evaluated, minimum_safe_procurement_margin=_decimal_string(minimum),
                      hard_margin=_decimal_string(HARD_MARGIN), target=_target(main), gaps=sorted(set(gaps)),
                      hard_failures=sorted(failures),
                      status=INCOMPLETE if gaps else FAILED if failures else PROVEN)
    result['proof_hash'] = fingerprint(result)
    return result
