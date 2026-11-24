"""Both Hermes paths delegate to Service; registration is a separate live integration step."""
import json

from user_contract import VIEWS, aggregate_only, POLICIES, METRIC_DEFINITIONS
from user_lifecycle import coverage_runs
from user_query_v4 import SECTIONS, SnapshotVersionRetired

LEGACY_PROPERTIES = {
    'section': {'type': 'string', 'enum': [*VIEWS, 'coverage']},
    'view': {'type': 'string', 'enum': list(VIEWS)},
    'scope': {'type': 'string', 'enum': ['global', 'site', 'series', 'project']},
    'scope_id': {'type': 'string'}, 'start': {'type': 'string'}, 'end_exclusive': {'type': 'string'},
    'as_of': {'type': 'string'}, 'policy_version': {'type': 'string', 'description': 'short-term-v1 uses 7/14/30 days; long-term-v1 uses 14/30/60 days. Both apply the selected thresholds to all projects. Legacy versions and frozen snapshots keep their original rules.'},
    'state_basis': {'type': 'string', 'enum': ['period_cohort','current', 'period_end'], 'description': 'Daily mode shows the latest seven complete days; cutoff advances only after a successful daily publication. An optional earlier start date retains the latest successful publication cutoff; period_cohort as_of is forbidden. Read weekly_update for exact dates and data_version; never advance to yesterday without a new publication. Period first-order ES flag supplies new/old; current and period_end retain all-history views with a fixed observation date. Frozen legacy snapshots preserve original dates.'},
    'policy_mode': {'type': 'string', 'enum': ['per_project', 'uniform']},
    'snapshot_id': {'type': 'string'}, 'H': {'type': 'integer', 'enum': [7, 30], 'description': 'Second-purchase observation horizon only; never the recent/silent/lost thresholds.'},
    'evidence_id': {'type': 'string'},
}

TEXT = {'type': 'string'}
PROPERTIES = {
    'section': {'type': 'string', 'enum': list(SECTIONS)},
    'scope': {'type': 'string', 'enum': ['global', 'site', 'project']},
    'scope_id': TEXT, 'game': TEXT, 'start': TEXT, 'end_exclusive': TEXT,
    'cohort_start': TEXT, 'cohort_end': TEXT,
    'windows': {'type': 'string', 'description': 'Ascending comma-separated window days, for example 30,90,180.'},
    'return_after': {'type': 'integer', 'minimum': 2, 'maximum': 364},
    'return_within': {'type': 'integer', 'minimum': 3, 'maximum': 365},
    'customer_type': {'type': 'string', 'enum': ['all', 'new', 'old', 'unknown']},
    'repeat_status': {'type': 'string', 'enum': ['all', 'repeated', 'not_repeated']},
    'snapshot_id': TEXT, 'query_id': TEXT, 'evidence_id': TEXT,
}
DESCRIPTION = (
    'Read the fs-users-v4 frozen aggregate. New customers are identified by the ES flag on the first valid '
    'site order observed since 2026-01-01. A repeat is a distinct valid order at least 24 hours later. '
    'Cohort window N ends before the first order plus N days. Rates use only fully observed, covered windows. '
    'Silent return requires a fully covered Y-day window, no repeat before X days, and a repeat from X to before Y days. '
    'Stage customers bought in the selected period, and their stages use the displayed Shanghai observation date. '
    'When pending, poll with query_id and optional section only. Reuse snapshot_id for the same results.'
)


def read_v4(service, user, args, *, wait_seconds=10, require_poll_section=False):
    if not isinstance(args, dict) or set(args) - PROPERTIES.keys():
        raise ValueError('user_tool_fields')
    args = dict(args)
    if require_poll_section and 'query_id' in args and 'section' not in args:
        raise ValueError('user_tool_section')
    section = args.pop('section', 'summary')
    if 'evidence_id' in args:
        evidence = args.pop('evidence_id')
        if not isinstance(evidence, str) or len(evidence) != 35 or not evidence.startswith('ua_'):
            raise ValueError('user_evidence_id')
        snapshot = 'us_' + evidence[3:]
        if args.get('snapshot_id', snapshot) != snapshot:
            raise ValueError('user_evidence_snapshot_mismatch')
        args['snapshot_id'] = snapshot
    status, value = service.v4.get(args, user, wait_seconds=wait_seconds, section=section)
    if status == 200:
        value = dict(value, result_section=section, available_sections=list(SECTIONS))
    return status, value


def invoke_v4(service, user, args):
    try:
        status, value = read_v4(service, user, args)
    except SnapshotVersionRetired:
        status, value = 422, {'error': 'snapshot_version_retired'}
    return value if status == 200 else dict(value, http_status=status)


def schema(name):
    return dict(name=name, description=DESCRIPTION,
                parameters=dict(type='object', properties=PROPERTIES, additionalProperties=False))


def invoke(service, user, args):
    if not isinstance(args, dict) or set(args) - set(LEGACY_PROPERTIES):
        raise ValueError('user_tool_fields')
    args = dict(args)
    section = args.pop('section', None)
    if section is not None and section not in (*VIEWS, 'coverage'):
        raise ValueError('user_tool_section')
    if 'evidence_id' in args:
        evidence = args.pop('evidence_id')
        if not isinstance(evidence, str) or len(evidence) != 35 or not evidence.startswith('ua_'):
            raise ValueError('user_evidence_id')
        snapshot = 'us_' + evidence[3:]
        if args.get('snapshot_id', snapshot) != snapshot:
            raise ValueError('user_evidence_snapshot_mismatch')
        args['snapshot_id'] = snapshot
    value = service.query(args, user)
    aggregate_only(value)
    section = section or value['query']['view']
    heavy = {'projects', 'migration', 'trend', 'cohort_weeks', 'trajectories', 'source_watermark'}
    result = {key: part for key, part in value.items() if key not in heavy}
    if value.get('weekly_update'):
        from user_weekly import small_state
        state = small_state(service.store.root)
        result['weekly_refresh_status'] = {key: state[key] for key in ('cutoff', 'phase', 'error', 'retryable') if key in state} if state else dict(phase='unknown')
    windows = value.get('source_watermark', [])
    runs = coverage_runs([dict(site=w['site'], start=w['start'], end=w['end_exclusive'], state=w['state']) for w in windows], sorted({w['site'] for w in windows}))
    result.update(source_coverage=[dict(site=site,start=a.isoformat(),end_exclusive=b.isoformat()) for site, intervals in runs.items() for a,b in intervals],
                  source_window_counts={state: sum(w['state']==state for w in windows) for state in ('complete','failed')})
    fields = {'summary': (), 'projects': ('projects',), 'transitions': ('migration',),
              'migration': ('migration',), 'trend': ('trend',), 'cohort': ('cohort_weeks',), 'trajectories': ('trajectories',), 'coverage': ()}[section]
    if any(key not in value for key in fields):
        raise ValueError('section_not_in_frozen_snapshot')
    result.update({key: value[key] for key in fields})
    policy = value.get('lifecycle_policy')
    if policy is None and value['policy_version'] in POLICIES:
        # These built-in v1 names retain their originally shipped definitions for old snapshots.
        policy = dict(version=value['policy_version'], thresholds_days=list(POLICIES[value['policy_version']]),
                      day_basis='Asia/Shanghai calendar days since last effective purchase', definition_source='versioned_builtin_contract')
    period_cohort = value['query'].get('state_basis') == 'period_cohort'
    result.update(lifecycle_policy=policy, metric_definitions=value.get('metric_definitions',METRIC_DEFINITIONS),
                  lifecycle_policies=value.get('lifecycle_policies', {name: list(points) for name, points in POLICIES.items()}),
                  project_policy_versions={row['project_id']: row['policy_version'] for row in value.get('projects', [])},
                  source_status_codes=dict(pay_status={'1': 'included by the confirmed effective-payment projection', '2': 'excluded'},
                                           order_status={'86': 'source partial-refund status code; not a number of orders'}),
                  interpretation=dict(H=('period first valid order + H*24h second-purchase horizon; includes ES-new and ES-old' if period_cohort else 'verified first purchase + H*24h second-purchase horizon')+'; does not set lifecycle thresholds',
                                      stock='Only purchasing emails in the selected period, ending yesterday; waiting is no repeat yet and below silence threshold. Other stages use last valid period order; previous/today orders do not enter. ES labels and lifetime first purchase are separate.' if period_cohort else 'state_basis=current uses today and all covered history; period_end uses historical cutoff. Interval dates never restrict the current customer pool. Partial history and observed zero do not prove no real churn',
                                      trend='each day recalculated from facts before its cutoff; early zero can follow short source history',
                                      high_value_entered_silent='interval entry event group; not current high-value silent stock',
                                      project_rules='project_policy_versions applies to project summaries and migration rows; top lifecycle_policy applies only to the selected summary',
                                      future_comparison='reuse one snapshot for its cards/tools; a later date or new data needs a new snapshot, preserving the old snapshot as baseline'))
    result.update(result_section=section, available_sections=[name for name, keys in (
        ('summary', ()), ('projects', ('projects',)), ('migration', ('migration',)),
        ('trend', ('trend',)), ('cohort', ('cohort_weeks',)), ('trajectories', ('trajectories',)), ('coverage', ())) if all(key in value for key in keys)])
    return result


def runtime_invoke(owner, args, detail=None):
    from user_runtime import build
    value = invoke_v4(build(), owner, args)
    if detail is not None and 'snapshot_id' in value:
        from workspace_evidence import save
        archive = save(detail, 'user_analytics', value['query'], value)
        if archive.get('archive_id'):
            value = dict(value, workspace_archive_id=archive['archive_id'])
    return value


def research_schema():
    return dict(type='function', function=schema('mcp__fcro__fc_query_user_analytics'))


def research_call(service, owner, args):
    return invoke_v4(service, owner, args)


def register_native(ctx, service, trusted_owner):
    # trusted_owner comes from the existing server profile, never browser request arguments.
    name = 'fs_query_user_analytics'
    def handler(args, **context):
        return json.dumps(invoke_v4(service, trusted_owner, args), ensure_ascii=False, allow_nan=False)
    ctx.register_tool(name=name, toolset='fs_readonly', schema=schema(name), handler=handler)
