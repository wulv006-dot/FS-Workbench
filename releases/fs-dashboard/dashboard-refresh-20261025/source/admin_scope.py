"""Verified Admin aggregate scope and independent native/local repeat-rate mapping."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

VERSION = 'admin-native-scope-repeat-20261113-v1'
UNSUPPORTED = ('channel', 'customer_type', 'payment', 'device', 'platform', 'product')


def scope_metadata(payload, mapped):
    requested = dict(site=str(payload.get('site') or 'all'), game=str(payload.get('game') or 'all'),
                     country_code=payload.get('country_code') or 'all', period=dict(zip(('start','end'),payload['date'])))
    effective = dict(requested)
    dimensions = mapped.get('dimensions') or {}
    total = mapped.get('metrics',{}).get('orders',{}).get('value')
    checks = {}
    for field, dimension in (('site','channels'), ('game','games'), ('country_code','countries')):
        selected = requested[field]
        if selected == 'all':
            checks[field] = 'no_filter_requested'
            continue
        rows = dimensions.get(dimension)
        expected = 'www.mmoexp.com' if field == 'site' and selected == '266' else selected
        def ident(row):
            return str(row.get('adminGameId') or '') if field == 'game' else str(row.get('code') or row.get('name') or '')
        if rows and any(ident(row) != expected for row in rows):
            raise ValueError('admin_' + field + '_filter_not_applied')
        if total == 0:
            effective[field] = None
            checks[field] = 'empty_result_membership_unverified'
        elif rows:
            checks[field] = 'verified_by_returned_ranks'
        else:
            effective[field] = None
            checks[field] = 'not_provided_by_upstream'
            # New country selections cannot fall back to an unfiltered aggregate.
            if field == 'country_code':
                raise ValueError('admin_country_filter_not_applied')
    status = ('empty_result_membership_unverified' if total == 0 else
              'partial_scope_evidence' if None in (effective['site'],effective['game'],effective['country_code']) else 'verified_by_returned_ranks')
    return dict(requested_scope=requested, effective_scope=effective, unsupported_filters=[],
                coverage=dict(scope_status=status, filters=checks,
                              time_boundary_status='upstream_minute_boundary_unverified'),
                time_basis='Admin pay_status=1/time_unit=1', source_timezone='Asia/Shanghai',
                data_revision=None, metric_definition_version=VERSION,
                actual_cutoff=payload['date'][1])


def repeat_metrics(raw, scope, local=None):
    """Local input is the existing user replay period_cohort result, not a second calculator."""
    original = raw.get('repeat_rete')
    value = None
    text = original.strip() if isinstance(original,str) else ''
    if text.endswith('%'):
        try:
            parsed = Decimal(text[:-1])
            if parsed.is_finite() and 0 <= parsed <= 100: value = float(parsed)
        except InvalidOperation: pass
    try:
        zero = not isinstance(raw.get('paid_payments'),bool) and Decimal(str(raw.get('paid_payments')).strip()) == 0
    except InvalidOperation: zero = False
    native = dict(raw=original, raw_value=value, value=None if zero else value, unit='percent',
                  numerator=None, denominator=None, scope=deepcopy(scope),
                  status='not_applicable' if zero else 'available' if value is not None else 'not_provided',
                  definition='Admin repeat_rete; numerator and denominator not published',
                  population='upstream_native_buyers; membership_and_formula_unverified')
    result = dict(value=None,numerator=None,denominator=None,unit='percent',status='unavailable',
                  source='user_replay_v1.period_cohort',scope=None,coverage=None,
                  identity_basis='existing user_store.customer_id mapping; not a uid-only cohort',
                  population='covered_identified_period_purchasers')
    if local is not None:
        coverage = local.get('coverage') or {}
        rate = local.get('repeat_rate') or {}
        result.update(scope=deepcopy(local.get('scope',local.get('query'))),coverage=deepcopy(coverage),
                      data_revision=local.get('data_revision'),definition=rate.get('basis'))
        complete = (coverage.get('period_complete') is True and coverage.get('identity_deduplication_complete') is True
                    and coverage.get('state_basis') == 'period_cohort' and rate.get('status') == 'available'
                    and rate.get('basis') == 'at_least_two_distinct_valid_orders_within_selected_period')
        if complete:
            n,d = rate.get('numerator'),rate.get('denominator')
            if type(n) is not int or type(d) is not int or not 0 <= n <= d:
                raise ValueError('local_repeat_contract')
            result.update(value=100*n/d if d else None,numerator=n,denominator=d,
                          status='available' if d else 'not_applicable')
    return dict(admin_repeat_rate_raw=original,native_repeat_rate=native,local_repeat_rate=result,
                reconciliation_status='not_aligned',
                reconciliation_reason='native_membership_formula_and_revision_not_verified')


def enrich(result, raw, local=None):
    metadata = scope_metadata(result['filters'],result)
    result.update(metadata)
    result.update(repeat_metrics(raw,metadata['effective_scope'],local))
    # Existing UI metric keeps its field/name; zero buyers are not an observed 0% rate.
    if 'repeatRatePct' in result.get('metrics',{}):
        result['metrics']['repeatRatePct'].update(raw=raw.get('repeat_rete'),
            value=result['native_repeat_rate']['value'],status=result['native_repeat_rate']['status'])
    return result
