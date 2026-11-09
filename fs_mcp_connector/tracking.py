"""Project existing customer-tracking business data without collecting or recalculating."""
from .redaction import redact


class TrackingError(ValueError):
    code = 'unexpected_tracking_shape'


def fields(*names):
    return dict.fromkeys(names)


CONFIG = {
    **fields('profile', 'site_id', 'min_order_usd_exclusive', 'max_discount_usd_exclusive',
             'enabled', 'version', 'last_request_id'),
    'product_types': [None], 'customer_flags': [None], 'enabled_profiles': [None],
}
MARKERS = [fields('days', 'reached', 'date')]
MILESTONES = [fields('track_id', 'days', 'due_at', 'state', 'evidence_id',
                     'conversation_id', 'turn_id', 'artifact_id')]
CLOCK = {
    **fields('first_paid_at', 'first_paid_status', 'first_paid_scope', 'lifecycle_day',
             'phase', 'clock_rule', 'history_observed_at'),
    'stage_markers': MARKERS,
}
ORDER = {
    **fields('candidate_id', 'order_no', 'email', 'uid', 'profile', 'site_id', 'gid',
             'pay_status', 'paid_at', 'observed_at', 'current_status', 'selected_game',
             'order_usd', 'order_usd_source', 'admin_order_usd', 'es_order_usd',
             'discount_usd', 'customer_flag', 'product_type', 'identity_status',
             'identity_reason', 'identity_source', 'amount_conflict'),
    'product_types': [None], 'payment': fields('amount', 'currency'),
    'es_identity': fields('buyer_id', 'uid', 'status', 'source'),
}
COVERAGE = {
    **fields('complete', 'source_total', 'received', 'unique_source_ids',
             'source_captured_at', 'source_version', 'source_total_basis',
             'quick_search_is_broad', 'customer_email_exact', 'site_id',
             'excluded_nonmatching_email', 'excluded_other_site', 'unknown_date_excluded',
             'conflicting_order_numbers', 'selected_game_orders', 'other_game_orders',
             'currency_and_discount_not_inferred', 'scope_matched_source_rows',
             'scope_matched_unique_ids', 'scope_excluded_source_rows',
             'matched_candidate_orders', 'candidate_orders_requested', 'missing_candidate_orders',
             'file_set_complete', 'declared_files', 'read_files', 'parse_failures', 'rows',
             'es_rows', 'criteria_matches', 'identity_verified', 'identity_unavailable', 'conflicts'),
    'pages': [fields('page', 'rows', 'source_total')],
    'scope_excluded_by_field': fields('gid', 'site_id', 'pay_status'),
    'excluded': fields('scope_or_product_unknown', 'order_or_money_missing', 'paid_at_missing',
                      'conflicting_order_rows', 'criteria_not_met', 'order_no_unmatched',
                      'admin_scope_mismatch', 'order_usd_missing'),
}
COVERAGE.update({key: dict(COVERAGE) for key in ('es', 'admin', 'criteria')})
JOB = fields('day', 'config_version', 'state', 'request_id', 'updated_at', 'reason', 'retry_after')
RECOVERY = {
    **fields('expected_job_sha256', 'es_receipt_sha256', 'actor', 'resumed_at'),
    'prior_failure': JOB,
    'proof': {**fields('receipt_sha256', 'original_denial_sha256', 'source_version', 'captured_at'),
              'query': fields('profile', 'start', 'end')},
}
RESULT = {
    **CONFIG, **fields('status', 'state', 'tracking_id', 'tracked_at', 'candidate_id',
                       'request_id', 'reused', 'report_policy', 'date', 'day', 'config_version',
                       'created_at', 'conversation_id', 'turn_id', 'artifact_id', 'customer_count'),
    'milestones': MILESTONES, 'permission_recovery': RECOVERY,
}
COMMON = fields('status', 'reason', 'retry_after', 'retryAfter', 'retryable', 'stored_only',
                'refreshed', 'refresh_status', 'stale', 'partial', 'complete', 'cursor', 'next_cursor')
VIEWS = {
    'config': {**CONFIG, **COMMON},
    'candidates': {**COMMON, **fields('date', 'day', 'config_version', 'captured_at'),
                   'items': [ORDER], 'coverage': COVERAGE},
    'tracked': {**COMMON, 'report_policy': None, 'items': [{**CLOCK,
        **fields('tracking_id', 'candidate_id', 'email', 'uid', 'tracked_at', 'status')}]},
    'detail': {**COMMON, **CLOCK,
        **fields('tracking_id', 'email', 'uid', 'tracked_at', 'owner', 'report_policy'),
        'orders': [ORDER], 'milestones': MILESTONES, 'history_coverage': COVERAGE,
        'buyer_identity_evidence': fields('status', 'covered_orders', 'total_orders',
            'distinct_observed_buyers', 'conflict_orders', 'identity_basis', 'canonical_identity_updated')},
    'request': {**COMMON, 'action': None, 'result': RESULT},
}


def _project(value, shape):
    if value is None:
        return None
    if shape is None:
        if type(value) not in (str, int, float, bool):
            raise TrackingError('unexpected_tracking_shape')
        return redact(value) if isinstance(value, str) else value
    if isinstance(shape, list):
        if not isinstance(value, list):
            raise TrackingError('unexpected_tracking_shape')
        return [_project(item, shape[0]) for item in value]
    if not isinstance(value, dict):
        raise TrackingError('unexpected_tracking_shape')
    return {key: _project(value[key], child) for key, child in shape.items() if key in value}


def project(value, view):
    """Keep authorized customer identifiers and original partial states; discard credentials."""
    if view not in VIEWS or not isinstance(value, dict):
        raise TrackingError('unexpected_tracking_shape')
    return _project(value, VIEWS[view])
